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
