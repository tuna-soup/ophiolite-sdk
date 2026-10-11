"""Maintainer-only exact, complete tracked contract snapshot; no runtime imports."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])

def snapshot(source):
    if git(source, 'status', '--porcelain').strip():
        raise ValueError('Contract source checkout must be clean')
    commit = git(source, 'rev-parse', 'HEAD').decode().strip()
    tree = git(source, 'rev-parse', 'HEAD:contracts').decode().strip()
    paths = git(source, 'ls-tree', '-rz', 'HEAD', 'contracts').split(b'\0')
    files = {}
    for row in filter(None, paths):
        mode, kind, rest = row.split(b' ', 2)
        digest, path = rest.split(b'\t', 1)
        if mode != b'100644' or kind != b'blob':
            raise ValueError('Contracts must contain regular non-executable files')
        name = path.decode().removeprefix('contracts/')
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe contract path')
        files[name] = git(source, 'cat-file', 'blob', digest.decode())
    index = json.loads(files['registry.json'])
    required = {'registry-schema.json', 'profile-schema.json', 'registry.json'}
    required.update(entry['path'] for group in ('schemas', 'profiles', 'documents') for entry in index[group])
    if not required <= files.keys():
        raise ValueError('Incomplete registry snapshot')
    # Every local reference must resolve inside the copied tree, including $defs.
    def refs(value, base):
        if isinstance(value, dict):
            if '$ref' in value:
                ref = value['$ref']
                if '://' in ref or ref.startswith('/'):
                    raise ValueError('External/absolute schema reference: '+ref)
                path, _, fragment = ref.partition('#')
                target = (Path(base).parent / path).as_posix() if path else base
                if '..' in Path(target).parts or target not in files:
                    raise ValueError('Missing or unsafe schema reference: '+ref)
                item = json.loads(files[target])
                if fragment:
                    if not fragment.startswith('/'):
                        raise ValueError('Unsupported reference fragment')
                    for key in fragment[1:].split('/'):
                        item = item[key.replace('~1', '/').replace('~0', '~')]
            for child in value.values(): refs(child, base)
        elif isinstance(value, list):
            for child in value: refs(child, base)
    # OpenAPI carries its own document references; scan schema inputs only.
    for name in required:
        if name.endswith('schema.json'):
            refs(json.loads(files[name]), name)
    provenance = {'platform_commit': commit, 'contracts_tree': tree,
                  'registry_version': index['version'],
                  'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}}
    files['SOURCE.json'] = (json.dumps(provenance, indent=2)+'\n').encode()
    return files

PROVENANCE = 'tests/fixtures/PROVENANCE.json'
PREFIX = 'ophiolite/contracts/'
PENDING_REVIEW = 3  # exit code: the snapshot is written and a new path's row waits for a person's disposition


def provenance_rows(manifest, files):
    """The public-input rows kept true to the new snapshot: a contract row gets the new sha256 and source_commit, a row
    whose path left the snapshot is dropped, a new path gets a pending-review row with empty evidence (check_public_inputs
    rejects it until a person writes the disposition; this tool never does). Other fields, row order and rows that did
    not change are kept as they were."""
    source = json.loads(files['SOURCE.json']); commit, digests = source['platform_commit'], source['files']
    rows, seen = [], set()
    for row in manifest['inputs']:
        if row['path'].startswith(PREFIX):
            name = row['path'].removeprefix(PREFIX)
            if name not in digests:
                continue
            seen.add(name)
            if (row.get('sha256'), row.get('source_commit')) != (digests[name], commit):
                row = {**row, 'sha256': digests[name], 'source_commit': commit}
        rows.append(row)
    pending = [PREFIX + name for name in digests if name not in seen]
    rows += [{'path': path, 'sha256': digests[path.removeprefix(PREFIX)], 'source_commit': commit,
              'origin': 'Ophiolite Platform contracts/' + path.removeprefix(PREFIX), 'license': '',
              'disposition': 'pending-review', 'evidence': ''} for path in pending]
    return {**manifest, 'inputs': rows}, pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT.parent/'ophiolite-platform')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(); files = snapshot(args.source)
    destination = ROOT/'ophiolite/contracts'
    if args.check:
        actual = {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
        # An unchanged tree can be sourced from an earlier immutable Platform commit.
        old = json.loads(actual['SOURCE.json'])
        if git(args.source, 'rev-parse', old['platform_commit']+':contracts').decode().strip() != old['contracts_tree']:
            raise ValueError('Recorded contract source tree does not match commit')
        new = json.loads(files['SOURCE.json'])
        new['platform_commit'] = old['platform_commit']
        files['SOURCE.json'] = (json.dumps(new, indent=2)+'\n').encode()
        if actual != files: raise ValueError('Contract snapshot differs by paths or bytes')
        print(f'Contracts: {len(files)-1} source files verified')
        return 0
    # H44: everything is decided before anything is written, so a refusal changes nothing.
    removed = set()
    if destination.exists():
        actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
        recorded = destination/'SOURCE.json'
        previous = set(json.loads(recorded.read_text())['files']) | {'SOURCE.json'} if recorded.is_file() else set()
        extra = actual - files.keys()
        # Only a file the last snapshot listed may go (Platform removed it); anything else is someone's.
        if extra - previous: raise ValueError('Untracked snapshot paths; inspect before updating')
        removed = extra
    record = ROOT/PROVENANCE
    manifest, pending = provenance_rows(json.loads(record.read_text()), files)
    for name in sorted(removed):
        path = destination/name; path.unlink()
        for folder in path.parents:
            if folder == destination or any(folder.iterdir()): break
            folder.rmdir()
    for name, raw in files.items():
        path = destination/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    record.write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Contracts: {len(files)-1} source files verified')
    if removed: print('Pruned (listed by the last snapshot, removed upstream): ' + ', '.join(sorted(removed)))
    print(f'Provenance: {len(manifest["inputs"])} inputs ({PROVENANCE}; tests/test_public_inputs.py keeps the count by hand)')
    if pending:
        print('Pending review (write disposition and evidence by hand): ' + ', '.join(pending))
        return PENDING_REVIEW
    return 0

if __name__ == '__main__': raise SystemExit(main())
