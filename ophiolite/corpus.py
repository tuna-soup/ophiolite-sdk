"""AI-ready corpora (E14): an E18 portable bundle plus a corpus manifest, grouped splits and
long-form samples, produced only for a selection the server authorized for one AI purpose.

    corpus = client.export_corpus([(asset, revision, ['GR'])], 'corpus-2026-09', purpose='training', seed=7)
    ophiolite.corpus.verify('corpus-2026-09')        # digests, membership, splits and samples

Layout: `bundle/` (the ordinary portable bundle: exact originals, descriptors, curves),
`corpus.json` (`ophiolite.ai-corpus/1`), `samples.jsonl` and, when pyarrow is installed,
`samples.parquet`. The corpus adds selection, rights and splits; the scientific data and its
integrity are the bundle's. Holding a corpus grants no rights beyond the recorded purpose.
"""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from .errors import Refused, VerificationFailed

SCHEMA = 'ophiolite.ai-corpus/1'
ALGORITHM = 'split/1'
SPLITS = ('train', 'validation', 'test')
COLUMNS = ('position', 'asset_id', 'revision', 'group', 'split', 'curve', 'unit', 'depth', 'depth_unit', 'depth_reference', 'value')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def group_key(well=None, group=None):
    """`group:<name>` for a reviewed group the caller names, else `las-well:<WELL>` normalized
    (whitespace collapsed, upper case). None when there is nothing to group by."""
    if group is not None:
        if not isinstance(group, str) or not group.strip(): raise Refused('A group name must be text.')
        return 'group:' + ' '.join(group.split())
    if not isinstance(well, str) or not well.strip(): return None
    return 'las-well:' + ' '.join(well.split()).upper()


def assign(key, seed, fractions):
    """split/1: sha256(str(seed) + NUL + key) as a fraction of 2**256, placed on the cumulative fractions."""
    point = int(hashlib.sha256((str(seed) + '\0' + key).encode('utf-8')).hexdigest(), 16) / 2 ** 256
    edge = 0.0
    for name, share in zip(SPLITS, fractions):
        edge += share
        if point < edge: return name
    return SPLITS[-1]


def _fractions(fractions):
    if (not isinstance(fractions, (list, tuple)) or len(fractions) != 3 or any(not isinstance(f, (int, float)) or f < 0 for f in fractions)
            or abs(sum(fractions) - 1) > 1e-9):
        raise Refused('Give three split fractions (train, validation, test) that add up to 1.')
    return [float(f) for f in fractions]


def _samples(bundle, selection):
    rows = []
    for entry, asset in zip(selection, bundle.assets):
        for name in entry['curves']:
            curve = asset.curves[name]
            for depth, value in zip(curve.axis, curve.values):
                rows.append({'position': entry['position'], 'asset_id': asset.asset_id, 'revision': asset.revision, 'group': entry['group'],
                             'split': entry['split'], 'curve': name, 'unit': curve.unit, 'depth': depth,
                             'depth_unit': curve.context.get('depth_unit'), 'depth_reference': curve.context.get('depth_reference'), 'value': value})
    return rows


def _jsonl(rows):
    return ''.join(canonical([r[c] for c in COLUMNS]) + '\n' for r in rows).encode()


def _parquet(rows, path):
    try: import pyarrow as pa, pyarrow.parquet as pq
    except ImportError: return False
    table = pa.table({c: [r[c] for r in rows] for c in COLUMNS})
    pq.write_table(table, path, compression='zstd')
    return True


def export_corpus(client, selections, destination, *, purpose, seed=0, fractions=(0.8, 0.1, 0.1), groups=None):
    """Authorize, read and write a corpus. `selections` are (asset, revision, [curves]); `groups`
    optionally maps asset ids to reviewed group names (overriding the LAS well)."""
    from .bundle import write_bundle, open_bundle
    from ._version import __version__
    destination = Path(destination)
    if destination.exists(): raise Refused('The destination already exists; choose a new folder.')
    fractions = _fractions(fractions); groups = dict(groups or {})
    if not isinstance(selections, (list, tuple)) or not selections: raise Refused('Choose at least one exact revision.')
    if any(not curves for _, _, curves in selections): raise Refused('Corpora hold well-log curves in this version; name the curves of every item.')
    authorized = client._post('ai-use', 'corpus', {'purpose': purpose, 'items': [{'asset_id': a, 'revision': r} for a, r, _ in selections]})
    permits = authorized['items']
    if [(p['asset_id'], p['revision']) for p in permits] != [(a, r) for a, r, _ in selections]:
        raise VerificationFailed('The server authorized a different selection than was asked for.')
    selection, missing = [], []
    for position, ((asset, revision, curves), permit) in enumerate(zip(selections, permits)):
        key = group_key(permit.get('well'), groups.get(asset))
        if key is None: missing.append(position + 1); continue
        selection.append({'position': position, 'asset_id': asset, 'revision': revision, 'curves': list(curves), 'group': key,
                          'group_source': 'group' if asset in groups else 'las-well', 'split': assign(key, seed, fractions),
                          'basis': permit['basis'], 'ai_use_generation': permit['ai_use_generation']})
    if missing:
        raise Refused('Item%s %s ha%s no well to group by; name a group for %s.' % ('s' if len(missing) > 1 else '', ', '.join(map(str, missing)),
                                                                              've' if len(missing) > 1 else 's', 'them' if len(missing) > 1 else 'it'))
    items = [({'asset_id': e['asset_id'], 'revision': e['revision'], 'curves': e['curves']}, client.read(e['asset_id'], e['revision'], e['curves'])) for e in selection]
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.staging-', dir=destination.parent)); os.chmod(staging, 0o700)
    try:
        write_bundle(staging / 'bundle', items)
        bundle = open_bundle(staging / 'bundle')
        rows = _samples(bundle, selection)
        (staging / 'samples.jsonl').write_bytes(_jsonl(rows))
        parquet = _parquet(rows, staging / 'samples.parquet')
        files = {name: sha((staging / name).read_bytes()) for name in ['bundle/manifest.json', 'samples.jsonl'] + (['samples.parquet'] if parquet else [])}
        counts = {'items': len(selection), 'samples': len(rows), 'by_split': {s: sum(1 for r in rows if r['split'] == s) for s in SPLITS}}
        manifest = {'schema': SCHEMA, 'purpose': purpose,
                    'authorization': {k: authorized[k] for k in ('authorization', 'authorized_at', 'expires_at')},
                    'selection': selection, 'split': {'algorithm': ALGORITHM, 'seed': seed, 'fractions': fractions, 'grouped_by': 'well'},
                    'transformations': [], 'columns': list(COLUMNS), 'counts': counts, 'files': files,
                    'parquet': 'written' if parquet else 'not written: pyarrow is not installed',
                    'code': {'exporter': 'ophiolite-sdk', 'version': __version__},
                    'restrictions': {'purpose': purpose, 'note': 'Use only for the recorded purpose; the corpus grants no other right.'}}
        digest = sha(canonical({k: v for k, v in manifest.items()}).encode())
        manifest['mlflow'] = {'name': destination.name, 'digest': digest[:8], 'source': str(destination.resolve()), 'source_type': 'local',
                              'profile': {'purpose': purpose, 'items': counts['items'], 'samples': counts['samples']}}
        (staging / 'corpus.json').write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n')
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True); raise
    return verify(destination)


def verify(folder):
    """Check a corpus against itself and its bundle; returns a summary or raises VerificationFailed."""
    from .bundle import open_bundle
    folder = Path(folder)
    try: manifest = json.loads((folder / 'corpus.json').read_text())
    except (OSError, ValueError): raise VerificationFailed('This folder has no readable corpus.json.') from None
    if manifest.get('schema') != SCHEMA: raise VerificationFailed('This is not an Ophiolite AI corpus (or a newer version).')
    for name, digest in manifest['files'].items():
        path = folder / name
        if not path.is_file() or sha(path.read_bytes()) != digest: raise VerificationFailed('A corpus file is missing or changed: ' + name)
    bundle = open_bundle(folder / 'bundle')
    selection = manifest['selection']
    if [(e['asset_id'], e['revision']) for e in selection] != [(a.asset_id, a.revision) for a in bundle.assets]:
        raise VerificationFailed('The corpus selection does not match its bundle.')
    split = manifest['split']
    if split['algorithm'] != ALGORITHM: raise VerificationFailed('Unknown split algorithm.')
    for entry in selection:
        if assign(entry['group'], split['seed'], split['fractions']) != entry['split']: raise VerificationFailed('A split assignment does not follow its seed.')
    rows = _samples(bundle, selection)
    if _jsonl(rows) != (folder / 'samples.jsonl').read_bytes(): raise VerificationFailed('samples.jsonl does not equal the bundle curves.')
    if 'samples.parquet' in manifest['files']:
        import pyarrow.parquet as pq
        table = pq.read_table(folder / 'samples.parquet')
        if [list(r.values()) for r in table.to_pylist()] != [[r[c] for c in COLUMNS] for r in rows]: raise VerificationFailed('samples.parquet does not equal samples.jsonl.')
    if manifest['counts']['samples'] != len(rows) or manifest['counts']['items'] != len(selection): raise VerificationFailed('The corpus counts are wrong.')
    return {'purpose': manifest['purpose'], 'items': len(selection), 'samples': len(rows), 'by_split': manifest['counts']['by_split'],
            'parquet': 'samples.parquet' in manifest['files'], 'authorization': manifest['authorization']['authorization']}
