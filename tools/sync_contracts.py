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
    else:
        if destination.exists():
            actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
            if actual-files.keys(): raise ValueError('Untracked snapshot paths; inspect before updating')
        for name, raw in files.items():
            path = destination/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    print(f'Contracts: {len(files)-1} source files verified')

if __name__ == '__main__': main()
