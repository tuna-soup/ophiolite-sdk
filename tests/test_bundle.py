"""E18: portable bundles are written atomically and checked completely before use, offline."""
import ast
import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path
import pytest
from ophiolite import bundle
from ophiolite.errors import VerificationFailed, Refused

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


class Read:
    """The shape Client.read returns: exact artifact plus the served descriptor and curve."""
    def __init__(self):
        self.artifact = FIXTURES.joinpath('original.las').read_bytes()
        self._wire_descriptors = [json.loads(FIXTURES.joinpath('source.json').read_bytes())]
        self._wire_curves = [json.loads(FIXTURES.joinpath('curve.json').read_bytes())]
        self._wire_curve_bytes = [FIXTURES.joinpath('curve.json').read_bytes()]


def written(tmp_path):
    d = Read()._wire_descriptors[0]
    return bundle.write_bundle(tmp_path / 'bundle', [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())])


def rewrite(root, mutate):
    manifest = json.loads((root / 'manifest.json').read_text()); mutate(manifest)
    (root / 'manifest.json').write_text(json.dumps(manifest))


def test_round_trip_keeps_zero_missing_units_and_exact_bytes(tmp_path):
    opened = written(tmp_path)
    [asset] = opened.assets; curve = asset.curves['GR']
    served = json.loads(FIXTURES.joinpath('curve.json').read_bytes())
    assert curve.values == served['values'] and curve.values[0] == 0.0 and curve.values[2] is None
    assert curve.unit == served['unit'] and curve.context == served['context'] and curve.axis == served['axis']
    assert asset.original == FIXTURES.joinpath('original.las').read_bytes()
    manifest = opened.manifest
    assert manifest['scope'] == 'selection' and manifest['groups'] is None and manifest['recommendations'] is None
    assert manifest['bundle_version'].startswith('1.') and 'integrity' in manifest['notice']
    assert opened.unlisted == []
    assert bundle.plot_svg(curve, tmp_path / 'gr.svg').read_text().startswith('<svg')
    with pytest.raises(Refused): bundle.write_bundle(tmp_path / 'bundle', [({}, Read())])  # never overwrites


@pytest.mark.parametrize('case', ['major', 'digest', 'descriptor-edit', 'size', 'traversal', 'absolute', 'duplicate', 'oversized', 'nonfinite', 'scope', 'groups', 'missing', 'link'])
def test_refusals(tmp_path, case):
    root = written(tmp_path).path
    first = lambda m: m['assets'][0]['files'][0]
    if case == 'major': rewrite(root, lambda m: m.update(bundle_version='2.0.0'))
    if case == 'digest':
        target = root / 'assets/0/original.las'; raw = target.read_bytes(); target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    if case == 'size': (root / 'assets/0/original.las').write_bytes(b'short')
    if case == 'descriptor-edit':  # same scientific content, edited copy: only the manifest digest can tell
        target = root / 'assets/0/descriptor-GR.json'; target.write_text(target.read_text() + ' ')
        rewrite(root, lambda m: [f.update(bytes=target.stat().st_size) for f in m['assets'][0]['files'] if f['path'].endswith('descriptor-GR.json')])
    if case == 'traversal':  # an existing, otherwise valid file outside the bundle: only the path rule can refuse it
        (tmp_path / 'escape').write_bytes((root / 'assets/0/original.las').read_bytes())
        rewrite(root, lambda m: [f.update(path='assets/0/../../../escape') for f in m['assets'][0]['files'] if f['role'] == 'original'])
    if case == 'absolute': rewrite(root, lambda m: first(m).update(path='/etc/passwd'))
    if case == 'duplicate': rewrite(root, lambda m: m['assets'][0]['files'].append(dict(first(m))))
    if case == 'oversized': rewrite(root, lambda m: first(m).update(bytes=64 * 1024 * 1024))
    if case == 'nonfinite': (root / 'manifest.json').write_text((root / 'manifest.json').read_text().replace('"max_assets": 128', '"max_assets": NaN'))
    if case == 'scope': rewrite(root, lambda m: m.update(scope='project'))
    if case == 'groups': rewrite(root, lambda m: m.update(groups=[]))
    if case == 'missing': (root / 'assets/0/original.las').unlink()
    if case == 'link':
        target = root / 'assets/0/original.las'; (tmp_path / 'elsewhere').write_bytes(target.read_bytes()); target.unlink(); target.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises((VerificationFailed, Refused)): bundle.open_bundle(root)


def test_unlisted_files_are_reported_not_trusted(tmp_path):
    root = written(tmp_path).path
    (root / 'assets/0/extra.txt').write_text('not listed')
    assert bundle.open_bundle(root).unlisted == ['assets/0/extra.txt']


def test_interrupted_write_publishes_nothing(tmp_path, monkeypatch):
    def boom(*_): raise OSError('disk full')
    monkeypatch.setattr(bundle, 'open_bundle', boom)
    d = Read()._wire_descriptors[0]
    with pytest.raises(OSError): bundle.write_bundle(tmp_path / 'b', [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())])
    assert not (tmp_path / 'b').exists() and not list(tmp_path.glob('.b.staging-*'))


def test_reader_imports_no_transport_or_authentication():
    source = Path(bundle.__file__).read_text()
    imported = {n.names[0].name if isinstance(n, ast.Import) else (n.module or '') for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert not imported & {'httpx', 'socket', 'urllib.request', 'client', 'auth', 'aio', 'application_transport'}, imported


def test_fresh_environment_reads_plots_and_calculates_offline(tmp_path):
    """E18-A4: only the installed SDK wheel, no credentials, sockets disabled, no server."""
    import subprocess, sys
    python = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python: pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the independently installed SDK wheel interpreter')
    root = written(tmp_path).path
    script = '''
import socket,sys,json
def refuse(*a,**k):raise OSError("network blocked for this check")
socket.socket=refuse;socket.create_connection=refuse;socket.getaddrinfo=refuse
from ophiolite.bundle import open_bundle,plot_svg
b=open_bundle(sys.argv[1]);curve=b.assets[0].curves["GR"]
present=[v for v in curve.values if v is not None]
derived=[None if v is None else 0.5*v+1 for v in curve.values]          # a second calculation
plot_svg(curve,sys.argv[2])
print(json.dumps({"mean":sum(present)/len(present),"missing":curve.values.count(None),"zero_kept":curve.values[0]==0.0,"derived":derived,"unit":curve.unit}))
'''
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path), 'PYTHONNOUSERSITE': '1'}
    done = subprocess.run([python, '-I', '-c', script, str(root), str(tmp_path / 'track.svg')], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    served = json.loads(FIXTURES.joinpath('curve.json').read_bytes())['values']
    assert result['missing'] == served.count(None) and result['zero_kept'] and result['derived'][2] is None and result['derived'][0] == 1.0
    assert (tmp_path / 'track.svg').read_text().startswith('<svg')
    # The installed CLI checks and summarizes the same bundle with sockets unavailable.
    cli = Path(python).parent / 'ophiolite'
    for action in ('check', 'show'):
        wrapped = [python, '-I', '-c', 'import socket,sys;socket.socket=None;socket.create_connection=None;from ophiolite.cli import main;main(sys.argv[1:])', 'bundle', action, str(root)]
        shown = subprocess.run(wrapped, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)
        assert shown.returncode == 0, shown.stderr
    assert 'Bundle verified' in subprocess.run(wrapped[:-2] + ['check', str(root)], capture_output=True, text=True, env=env, cwd=tmp_path).stdout
    assert cli.exists()


def test_selection_binding_and_membership(tmp_path):
    root = written(tmp_path).path
    rewrite(root, lambda m: m['selection'][0].update(revision='0' * 64))
    with pytest.raises(VerificationFailed, match='selected'): bundle.open_bundle(root)
    root = written(tmp_path / 'b').path
    rewrite(root, lambda m: m['selection'][0].update(curves=['GR', 'RHOB']))
    with pytest.raises(VerificationFailed, match='selected curves'): bundle.open_bundle(root)
    root = written(tmp_path / 'c').path
    rewrite(root, lambda m: m['assets'][0].update(parent_visibility='restricted'))
    with pytest.raises(VerificationFailed, match='disagrees'): bundle.open_bundle(root)
    root = written(tmp_path / 'd').path
    rewrite(root, lambda m: m['assets'][0]['files'].append({'path': 'assets/0/second.las', 'role': 'original', 'sha256': m['assets'][0]['files'][0]['sha256'], 'bytes': m['assets'][0]['files'][0]['bytes']}))
    (root / 'assets/0/second.las').write_bytes((root / 'assets/0/original.las').read_bytes())
    with pytest.raises(VerificationFailed, match='exactly one original'): bundle.open_bundle(root)


def test_minor_extensions_are_accepted_and_limits_are_reader_owned(tmp_path):
    root = written(tmp_path).path
    rewrite(root, lambda m: m.update(bundle_version='1.7.0', future={'kept': True}, limits={'max_assets': 10**9, 'max_file_bytes': 10**12, 'max_total_bytes': 10**15}))
    assert bundle.open_bundle(root).manifest['future'] == {'kept': True}
    rewrite(root, lambda m: m['assets'][0]['files'][0].update(bytes=64 * 1024 * 1024))  # declared limits do not raise ours
    with pytest.raises(VerificationFailed): bundle.open_bundle(root)


def test_concurrent_exports_never_overwrite_and_live_staging_survives(tmp_path):
    d = Read()._wire_descriptors[0]; item = [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())]
    live = tmp_path / '.same.staging-live'; live.mkdir(); (live / '.owner').write_text(str(os.getpid()))
    os.utime(live, (0, 0))
    bundle.write_bundle(tmp_path / 'same', item, grace=1)
    assert live.exists()  # an export still running (its owner is alive) is left alone
    with pytest.raises(Refused): bundle.write_bundle(tmp_path / 'same', item)
    (tmp_path / 'claimed').mkdir()  # a concurrent writer claimed the name first
    with pytest.raises(Refused): bundle.write_bundle(tmp_path / 'claimed', item)
    assert not any((tmp_path / 'claimed').iterdir())


# --- E11: bundle 2 carries typed assets --------------------------------------------------

def typed_read(name):
    from ophiolite import _core
    return _core.typed_result(json.loads(FIXTURES.joinpath(f'{name}.json').read_bytes()), FIXTURES.joinpath(f'{name}-data.json').read_bytes(),
                              FIXTURES.joinpath(f'{name}.original').read_bytes())


def typed_items():
    d = Read()._wire_descriptors[0]
    items = [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())]
    for name in ('tops', 'trajectory', 'grid'):
        r = typed_read(name); items.append(({'asset_id': r._wire_descriptor['asset_id'], 'revision': r._wire_descriptor['revision'], 'curves': None}, r))
    return items


def test_bundle_two_round_trips_all_four_types(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', typed_items())
    assert opened.manifest['bundle_version'] == '2.0.0' and opened.manifest['schema'] == 'ophiolite.portable-bundle/2'
    log, tops, trajectory, grid = opened.assets
    assert [a.type for a in opened.assets] == ['well-log', 'well-tops', 'trajectory', 'regular-grid-surface']
    assert log.curves['GR'].values[0] == 0.0 and tops.curves == {} and opened.manifest['selection'][1]['curves'] == []
    assert [t['md'] for t in tops.data.tops] == [100.5, 103.0] and tops.data.tops[0]['tvd'] is None
    assert grid.data.values[1] == 0.0 and grid.data.values[2] is None and grid.data.cell_center(0, 0) == (1012.5, 5037.5)
    assert trajectory.data.stations[2]['inclination'] is None and tops.relationships == {'well_log': None}
    assert (opened.path / 'assets/1/original.csv').read_bytes() == FIXTURES.joinpath('tops.original').read_bytes()
    assert opened.summary()['types'] == ['regular-grid-surface', 'trajectory', 'well-log', 'well-tops']
    # A curve-only export stays 1.0 so released readers keep reading it.
    assert written(tmp_path / 'curves').manifest['bundle_version'] == '1.0.0'


@pytest.mark.parametrize('case', ['type', 'relationships', 'curves', 'data-context', 'schema-version', 'extra-file'])
def test_bundle_two_refusals(tmp_path, case):
    import hashlib as h
    root = bundle.write_bundle(tmp_path / 'b', typed_items()).path
    tops = lambda m: m['assets'][1]
    if case == 'type': rewrite(root, lambda m: tops(m).update(type='trajectory'))
    if case == 'relationships': rewrite(root, lambda m: tops(m).update(relationships={'well_log': 'restricted'}))
    if case == 'curves': rewrite(root, lambda m: m['selection'][1].update(curves=['GR']))
    if case == 'schema-version': rewrite(root, lambda m: m.update(bundle_version='1.0.0'))
    if case == 'data-context':  # consistent data with a different declared context; digests recomputed everywhere
        target = root / 'assets/1/data.json'; payload = json.loads(target.read_text()); payload['context']['depth_basis'] = 'other'
        raw = json.dumps(payload).encode(); target.write_bytes(raw)
        dpath = root / 'assets/1/descriptor.json'; descriptor = json.loads(dpath.read_text())
        rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(raw), h.sha256(raw).hexdigest()
        draw = (json.dumps(descriptor) + '\n').encode(); dpath.write_bytes(draw)
        def fix(m):
            for f in tops(m)['files']:
                data = (root / f['path']).read_bytes(); f['bytes'], f['sha256'] = len(data), h.sha256(data).hexdigest()
        rewrite(root, fix)
    if case == 'extra-file':
        (root / 'assets/1/second.csv').write_bytes(b'name,md\nX,1\n')
        rewrite(root, lambda m: tops(m)['files'].append({'path': 'assets/1/second.csv', 'role': 'normalized', 'sha256': h.sha256(b'name,md\nX,1\n').hexdigest(), 'bytes': 12}))
    with pytest.raises((VerificationFailed, Refused)): bundle.open_bundle(root)


def test_released_reader_refuses_bundle_two_by_its_major(tmp_path):
    """The released E18 reader (SDK 23c0acd, frozen byte for byte in tests/frozen) refuses 2.0
    before reading any content. Its message is the generic "not an Ophiolite portable bundle"
    (it predates schema /2); it never misreads a typed asset as a curve."""
    import importlib.util, subprocess
    frozen_path = Path(__file__).parent / 'frozen/bundle_1_0.py'
    released = subprocess.run(['git', '-C', str(Path(__file__).parents[1]), 'show', '23c0acd:ophiolite/bundle.py'], capture_output=True)
    if released.returncode == 0: assert released.stdout == frozen_path.read_bytes()  # full clones prove the copy is exact
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle', frozen_path); frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    root = bundle.write_bundle(tmp_path / 'b', typed_items()).path
    with pytest.raises(VerificationFailed, match='not an Ophiolite portable bundle'): frozen.open_bundle(root)
    assert frozen.open_bundle(written(tmp_path / 'c').path).assets[0].curves['GR'].values[0] == 0.0


def test_fresh_environment_reads_typed_bundle_offline(tmp_path):
    import subprocess, sys
    python = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python: pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the independently installed SDK wheel interpreter')
    root = bundle.write_bundle(tmp_path / 'b', typed_items()).path
    script = '''
import socket,sys,json
def refuse(*a,**k):raise OSError("network blocked")
socket.socket=refuse;socket.create_connection=refuse;socket.getaddrinfo=refuse
from ophiolite.bundle import open_bundle
from ophiolite.typed import minimum_curvature
b=open_bundle(sys.argv[1]);tops,traj,grid=b.assets[1].data,b.assets[2].data,b.assets[3].data
print(json.dumps({"tops":[t["md"] for t in tops.tops],"grid":grid.values,"corner":grid.cell_center(1,2),"offsets":minimum_curvature(traj.stations[:2])[1]["dtvd"]}))
'''
    done = subprocess.run([python, '-I', '-c', script, str(root)], capture_output=True, text=True, env={'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path)}, timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result['tops'] == [100.5, 103.0] and result['grid'] == [1.0, 0.0, None, 4.0, 5.0, 6.0] and result['corner'] == [1062.5, 5012.5]
    assert abs(result['offsets'] - 99.4931) < 1e-3   # 0→10° over 100: R·sin θ


# --- E18 completion: bundle 2.1 groups ---------------------------------------------------

def grouped(tmp_path, **recommended):
    items = typed_items(); rev = items[0][1]._wire_descriptors[0]['revision']
    group = {'name': 'Corrections', 'observed_at': '2026-09-27T10:00:00Z', 'meaning': 'observation-at-export', 'members': [0, 1],
             'recommended': {'asset_position': 0, 'revision': rev, 'by': 'bob', 'at': 1790000000.0, 'reason': 'Closer to the core', **recommended}}
    return bundle.write_bundle(tmp_path / 'g', items, groups=[group])


def test_groups_are_written_as_observations_and_read_back(tmp_path):
    opened = grouped(tmp_path)
    assert opened.manifest['bundle_version'] == '2.1.0' and opened.groups[0]['meaning'] == 'observation-at-export'
    assert opened.manifest['groups'] is None and opened.manifest['recommendations'] is None
    assert opened.groups[0]['members'] == [0, 1] and opened.groups[0]['recommended']['reason'] == 'Closer to the core'
    assert written(tmp_path / 'plain').groups == []  # no groups: unchanged 1.0


@pytest.mark.parametrize('edit', [
    lambda m: m['observations']['groups'][0].update(members=[0, 9]),
    lambda m: m['observations']['groups'][0].update(members=[0, -1]),
    lambda m: m['observations']['groups'][0].update(meaning='truth'),
    lambda m: m['observations']['groups'][0]['recommended'].update(revision='0' * 64),
    lambda m: m['observations']['groups'][0]['recommended'].update(asset_position=2),
    lambda m: m['observations']['groups'][0]['recommended'].update(asset_position=True),
    lambda m: m.update(groups=m['observations']['groups']),
    lambda m: m.update(recommendations=[]),
])
def test_group_refusals(tmp_path, edit):
    root = grouped(tmp_path).path
    rewrite(root, edit)
    with pytest.raises(VerificationFailed): bundle.open_bundle(root)


def test_released_readers_still_read_grouped_bundles(tmp_path):
    """Observations are an extension: the frozen 1.0 reader reads a grouped curve-only bundle."""
    import importlib.util
    d = Read()._wire_descriptors[0]
    group = {'name': 'G', 'observed_at': 't', 'meaning': 'observation-at-export', 'members': [0], 'recommended': None}
    opened = bundle.write_bundle(tmp_path / 'b', [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())], groups=[group])
    assert opened.manifest['bundle_version'] == '1.1.0' and opened.groups == [group]
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle', Path(__file__).parent / 'frozen/bundle_1_0.py'); frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    assert frozen.open_bundle(opened.path).assets[0].curves['GR'].values[0] == 0.0


def test_older_readers_and_newer_types(tmp_path):
    """2.2 only when a newer type is present; the released 2.1 reader refuses it and still reads older content."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_21', Path(__file__).parent / 'frozen/bundle_2_1.py'); frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    old = bundle.write_bundle(tmp_path / 'old', typed_items())
    assert old.manifest['bundle_version'] == '2.0.0' and [a.type for a in frozen.open_bundle(old.path).assets][1] == 'well-tops'
    mesh = typed_read('mesh'); points = typed_read('points')
    new = bundle.write_bundle(tmp_path / 'new', typed_items() + [({'asset_id': r._wire_descriptor['asset_id'], 'revision': r._wire_descriptor['revision'], 'curves': None}, r) for r in (mesh, points)])
    assert new.manifest['bundle_version'] == '2.2.0' and [a.type for a in new.assets][-2:] == ['triangulated-surface', 'point-set']
    assert new.assets[-2].data.vertices[1] == [10.0, 0.0, None]
    with pytest.raises(VerificationFailed, match='unknown type'): frozen.open_bundle(new.path)


@pytest.mark.parametrize('schema,version', [('ophiolite.portable-bundle/1', '3.0.0'), ('ophiolite.portable-bundle/2', '3.0.0')])
def test_an_unsupported_major_is_refused_for_its_major(tmp_path, schema, version):
    """E17 review: schema and major agree, so only the supported-major rule can refuse it."""
    root = written(tmp_path).path
    rewrite(root, lambda m: m.update(schema=schema, bundle_version=version))
    with pytest.raises(Refused, match='major versions 1 and 2'): bundle.open_bundle(root)
