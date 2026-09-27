"""E16: fault sticks and seismic volumes; slices verified against their volume; bundle 2.3."""
import copy
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path
import httpx
import pytest
from ophiolite import _core, bundle
from ophiolite.client import Client
from ophiolite.errors import VerificationFailed, Refused
from ophiolite.typed import PolylineSet, SeismicVolume, SeismicSlice

FIX = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
INLINES, CROSSLINES, Z = [10, 12], [100, 101, 102], [0, 4, 8, 12]


def load(name):
    return json.loads(FIX.joinpath(f'{name}.json').read_bytes()), FIX.joinpath(f'{name}-data.json').read_bytes(), FIX.joinpath(f'{name}.original').read_bytes()


def amplitude(il, xl, k):
    """The fixture generator's cube, authored independently here: i*100 + j*10 + k + 0.5."""
    return INLINES.index(il) * 100 + CROSSLINES.index(xl) * 10 + k + 0.5


def volume():
    descriptor, body, _ = load('seismic')
    return _core.typed_result(descriptor, body, None)


def served(v, axis, label):
    """A slice document as the server serves it, with values from the independent formula."""
    d = v.data
    if axis == 'inline':
        rows, columns, values, chunks = ('crossline', CROSSLINES), ('sample', Z), [[amplitude(label, x, k) for k in range(4)] for x in CROSSLINES], [d['chunks'][INLINES.index(label)]['sha256']]
    elif axis == 'crossline':
        rows, columns, values, chunks = ('inline', INLINES), ('sample', Z), [[amplitude(i, label, k) for k in range(4)] for i in INLINES], [c['sha256'] for c in d['chunks']]
    else:
        rows, columns, values, chunks = ('inline', INLINES), ('crossline', CROSSLINES), [[amplitude(i, x, label) for x in CROSSLINES] for i in INLINES], [c['sha256'] for c in d['chunks']]
    return {'schema': 'ophiolite.seismic-slice/1', 'representation': 'slice', 'asset_id': v.descriptor.asset_id, 'revision': v.descriptor.revision,
            'source': d['source'], 'source_sha256': d['source_sha256'], 'interpretation': d['interpretation'], 'axis': axis, 'label': label,
            'scope': 'One %s of a seismic volume at an exact revision; not the complete volume' % axis,
            'rows': {'name': rows[0], 'values': rows[1]}, 'columns': {'name': columns[0], 'values': columns[1]},
            'sample': {'domain': 'time', 'unit': 'ms', 'first': 0, 'interval': 4.0}, 'values': values, 'chunks': chunks}


def encode(value): return json.dumps(value).encode()


def test_fault_sticks_and_volume_descriptions_read_as_typed_objects():
    faults = _core.typed_result(*load('faults'))
    assert isinstance(faults, PolylineSet) and [s['index'] for s in faults.sticks] == [3, 1]
    assert faults.sticks[1]['points'][1] == {'x': 500310.0, 'y': 5800410.0, 'z': 1250.125}
    frame = faults.to_frame(); assert list(frame['stick']) == [3, 3, 1, 1] and list(frame['point']) == [0, 1, 0, 1]
    v = volume()
    assert isinstance(v, SeismicVolume) and v.original is None and v.inlines == INLINES and v.crosslines == CROSSLINES and v.sample_values == Z
    assert v.decisions and v.data['positions']['inline_byte'] == 189
    # With the original, its bytes are still checked; a wrong original is refused.
    descriptor, body, original = load('seismic')
    assert _core.typed_result(descriptor, body, original).original == original
    with pytest.raises(VerificationFailed): _core.typed_result(descriptor, body, original + b'x')


def test_volume_description_cross_checks():
    descriptor, body, _ = load('seismic')
    def refused(mutate):
        d, value = copy.deepcopy(descriptor), json.loads(body); mutate(d, value); raw = encode(value)
        rep = next(r for r in d['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(raw), hashlib.sha256(raw).hexdigest()
        with pytest.raises(VerificationFailed): _core.typed_result(d, raw, None)
    refused(lambda d, v: v['chunks'].reverse())
    refused(lambda d, v: v['chunks'][0].update(bytes=44))
    refused(lambda d, v: v['decisions'].pop())
    def grid(d, v):
        for c in (v['context'], d['scientific']): c['inline']['count'] = 3
    refused(grid)


@pytest.mark.parametrize('axis,label', [('inline', 12), ('crossline', 101), ('sample', 2)])
def test_slices_are_exact_and_checked_against_the_volume(axis, label):
    v = volume(); s = _core.slice_result(v, encode(served(v, axis, label)), v.descriptor.asset_id, v.descriptor.revision, axis, label)
    assert isinstance(s, SeismicSlice) and s.original_sha256 == v.descriptor.revision and 'not the complete volume' in s.scope
    assert s.to_numpy().shape == (len(s.rows[1]), len(s.columns[1]))
    if axis == 'inline': assert s.value_at(101, 8) == amplitude(12, 101, 2) == 112.5
    if axis == 'sample': assert s.value_at(10, 102) == amplitude(10, 102, 2) == 22.5


@pytest.mark.parametrize('mutation', ['axis', 'label', 'revision', 'digest', 'rows', 'transpose', 'shape', 'sample', 'scope', 'chunk', 'source'])
def test_changed_slices_are_refused(mutation):
    v = volume(); good = served(v, 'inline', 12); bad = copy.deepcopy(good)
    change = {'axis': lambda: bad.update(axis='crossline'), 'label': lambda: bad.update(label=10),
              'revision': lambda: bad.update(revision='0' * 64), 'digest': lambda: bad.update(source_sha256='0' * 64),
              'rows': lambda: bad['rows']['values'].reverse(), 'transpose': lambda: bad.update(rows=good['columns'], columns=good['rows']),
              'shape': lambda: bad['values'].pop(), 'sample': lambda: bad['sample'].update(domain='depth'),
              'scope': lambda: bad.update(scope='The volume'), 'chunk': lambda: bad.update(chunks=[v.data['chunks'][0]['sha256']]),
              'source': lambda: bad['source'].update(key='other')}
    change[mutation]()
    with pytest.raises(VerificationFailed): _core.slice_result(v, encode(bad), v.descriptor.asset_id, v.descriptor.revision, 'inline', 12)


def mock(v, slice_bytes, calls):
    descriptor = v._wire_descriptor; base = '/api/v1/projects/%s/scientific-assets/%s/revisions/%s' % (descriptor['project_id'], descriptor['asset_id'], descriptor['revision'])
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == base: return httpx.Response(200, json=descriptor)
        if request.url.path == base + '/representations/data': return httpx.Response(200, content=v._wire_data_bytes)
        if request.url.path.startswith(base + '/slices/'):
            axis, label = request.url.path.rsplit('/', 2)[1:]; return httpx.Response(200, content=slice_bytes(axis, int(label)))
        return httpx.Response(404, json={'error': {'code': 'unavailable'}})
    return httpx.MockTransport(handler), base


def test_client_reads_slices_without_downloading_the_volume(tmp_path):
    v = volume(); calls = []
    transport, base = mock(v, lambda axis, label: encode(served(v, axis, label)), calls)
    with httpx.Client(transport=transport) as http:
        client = Client('http://localhost', v.descriptor.project_id, http=http)
        s = client.read_slice(v.descriptor.asset_id, v.descriptor.revision, 'crossline', 102)
        assert s.values == [[amplitude(i, 102, k) for k in range(4)] for i in INLINES]
        assert base + '/representations/artifact' not in calls and calls[-1] == base + '/slices/crossline/102'
        with pytest.raises(Refused): client.read_slice(v.descriptor.asset_id, v.descriptor.revision, 'depth', 1)
        with pytest.raises(Refused, match='chosen slices'): client.export([(v.descriptor.asset_id, v.descriptor.revision, None)], tmp_path / 'volume')
        opened = client.export_slices(v.descriptor.asset_id, v.descriptor.revision, [('inline', 10), ('sample', 3)], tmp_path / 'slices')
    assert opened.manifest['bundle_version'] == '2.3.0' and not (tmp_path / 'volume').exists()
    asset = opened.assets[0]
    assert asset.type == 'seismic-slice' and asset.original is None and [s.axis for s in asset.slices] == ['inline', 'sample']
    assert asset.slices[1].values == [[amplitude(i, x, 3) for x in CROSSLINES] for i in INLINES]
    assert asset.entry['original'] == {'sha256': v.descriptor.revision, 'bytes': next(r for r in v._wire_descriptor['representations'] if r['kind'] != 'normalized')['bytes'], 'included': False}
    assert not any(p.name.startswith('original') for p in (opened.path / 'assets/0').iterdir())


def test_a_server_slice_that_disagrees_is_refused():
    v = volume(); calls = []
    transport, _ = mock(v, lambda axis, label: encode({**served(v, axis, label), 'label': label + 1}), calls)
    with httpx.Client(transport=transport) as http:
        with pytest.raises(VerificationFailed): Client('http://localhost', v.descriptor.project_id, http=http).read_slice(v.descriptor.asset_id, v.descriptor.revision, 'inline', 10)


def test_async_client_has_the_same_slice_reads(tmp_path):
    import anyio
    from ophiolite.aio import AsyncClient
    v = volume(); calls = []
    transport, _ = mock(v, lambda axis, label: encode(served(v, axis, label)), calls)
    async def main():
        async with httpx.AsyncClient(transport=transport) as http:
            client = AsyncClient('http://localhost', v.descriptor.project_id, http=http)
            s = await client.read_slice(v.descriptor.asset_id, v.descriptor.revision, 'inline', 12)
            opened = await client.export_slices(v.descriptor.asset_id, v.descriptor.revision, [('crossline', 100)], tmp_path / 'async')
            return s, opened
    s, opened = anyio.run(main)
    assert s.values[0] == [amplitude(12, 100, k) for k in range(4)] and opened.assets[0].slices[0].label == 100


def slices_bundle(tmp_path, name='b'):
    v = volume()
    read = [_core.slice_result(v, encode(served(v, a, l)), v.descriptor.asset_id, v.descriptor.revision, a, l) for a, l in (('inline', 12), ('crossline', 101))]
    chosen = {'asset_id': v.descriptor.asset_id, 'revision': v.descriptor.revision, 'curves': [], 'slices': [{'axis': 'inline', 'label': 12}, {'axis': 'crossline', 'label': 101}]}
    return bundle.write_bundle(tmp_path / name, [(chosen, (v, read))])


def rewrite_file(root, relative, mutate):
    """Change a slice file and recompute its checksum, so only meaning can fail."""
    manifest = json.loads((root / 'manifest.json').read_text()); target = root / relative
    value = json.loads(target.read_bytes()); mutate(value); raw = encode(value); target.write_bytes(raw)
    item = next(i for a in manifest['assets'] for i in a['files'] if i['path'] == relative); item['sha256'], item['bytes'] = hashlib.sha256(raw).hexdigest(), len(raw)
    (root / 'manifest.json').write_text(json.dumps(manifest))


@pytest.mark.parametrize('mutation', ['axis', 'label', 'revision', 'shape', 'scope', 'sample', 'values-transposed'])
def test_bundle_semantic_changes_are_refused_even_with_valid_checksums(tmp_path, mutation):
    root = slices_bundle(tmp_path).path
    change = {'axis': lambda s: s.update(axis='sample'), 'label': lambda s: s.update(label=10), 'revision': lambda s: s.update(revision='0' * 64),
              'shape': lambda s: s['values'].pop(), 'scope': lambda s: s.update(scope='The whole volume'), 'sample': lambda s: s['sample'].update(unit='m'),
              'values-transposed': lambda s: s.update(rows=s['columns'], columns=s['rows'])}
    rewrite_file(root, 'assets/0/slice-inline-12.json', change[mutation])
    with pytest.raises(VerificationFailed): bundle.open_bundle(root)


def test_manifest_changes_are_refused(tmp_path):
    root = slices_bundle(tmp_path).path
    def refused(mutate):
        manifest = json.loads((root / 'manifest.json').read_text()); original = json.dumps(manifest)
        mutate(manifest); (root / 'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(VerificationFailed): bundle.open_bundle(root)
        (root / 'manifest.json').write_text(original)
    refused(lambda m: m['assets'][0]['original'].update(included=True))
    refused(lambda m: m['assets'][0]['slices'][0].update(scope='all'))
    refused(lambda m: m['selection'][0]['slices'].reverse())
    refused(lambda m: m['assets'][0].update(type='point-set'))
    assert bundle.open_bundle(root).assets[0].slices[0].label == 12


def test_older_readers_refuse_slices_and_older_content_keeps_its_version(tmp_path):
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_22', Path(__file__).parent / 'frozen/bundle_2_2.py'); frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    with pytest.raises(VerificationFailed): frozen.open_bundle(slices_bundle(tmp_path).path)
    faults = _core.typed_result(*load('faults'))
    opened = bundle.write_bundle(tmp_path / 'faults', [({'asset_id': faults._wire_descriptor['asset_id'], 'revision': faults._wire_descriptor['revision'], 'curves': None}, faults)])
    assert opened.manifest['bundle_version'] == '2.3.0' and opened.assets[0].data.sticks == faults.sticks
    with pytest.raises(VerificationFailed, match='unknown type'): frozen.open_bundle(opened.path)
    mesh = _core.typed_result(*load('mesh'))
    older = bundle.write_bundle(tmp_path / 'mesh', [({'asset_id': mesh._wire_descriptor['asset_id'], 'revision': mesh._wire_descriptor['revision'], 'curves': None}, mesh)])
    assert older.manifest['bundle_version'] == '2.2.0' and frozen.open_bundle(older.path).assets[0].type == 'triangulated-surface'


EXPORTER = '''
import json, os, sys, time
sys.path.insert(0, {tests!r}); sys.path.insert(0, {root!r})
import test_seismic as t
from ophiolite import bundle
real = bundle.os.fdopen
def slow(fd, mode):  # hold the export mid-write so the parent can kill it there
    handle = real(fd, mode)
    if os.path.exists({marker!r}): time.sleep(60)
    open({marker!r}, 'w').close(); return handle
bundle.os.fdopen = slow
t.slices_bundle(__import__('pathlib').Path({parent!r}), {name!r})
'''


def exporter(tmp_path, name, tag):
    marker = tmp_path / ('.marker-' + tag); before = set(tmp_path.glob('.' + name + '.staging-*'))
    code = EXPORTER.format(tests=str(Path(__file__).parent), root=str(Path(__file__).parents[1]), marker=str(marker), parent=str(tmp_path), name=name)
    process = subprocess.Popen([sys.executable, '-c', code], env={**os.environ})
    for _ in range(600):
        stage = set(tmp_path.glob('.' + name + '.staging-*')) - before
        if marker.exists() and stage: return process, stage.pop()
        time.sleep(0.05)
    process.kill(); pytest.fail('the exporter did not start')


def test_a_killed_export_leaves_nothing_visible_and_a_restart_cleans_it_up(tmp_path):
    process, stale = exporter(tmp_path, 'out', 'killed'); process.send_signal(signal.SIGKILL); process.wait()
    assert stale.exists() and not (tmp_path / 'out').exists()  # nothing half-written is ever at the destination
    live, writing = exporter(tmp_path, 'out', 'live')  # another exporter still writing the same destination
    try:
        v = volume(); read = [_core.slice_result(v, encode(served(v, 'inline', 10)), v.descriptor.asset_id, v.descriptor.revision, 'inline', 10)]
        chosen = {'asset_id': v.descriptor.asset_id, 'revision': v.descriptor.revision, 'curves': [], 'slices': [{'axis': 'inline', 'label': 10}]}
        opened = bundle.write_bundle(tmp_path / 'out', [(chosen, (v, read))], grace=0)  # a restart, not a resume: it writes afresh
        assert opened.assets[0].slices[0].label == 10
        assert not stale.exists() and writing.exists()  # the dead stage is removed; the live exporter's stage is left alone
    finally:
        live.kill(); live.wait()


def test_other_types_cannot_claim_an_absent_original(tmp_path):
    faults = _core.typed_result(*load('faults'))
    root = bundle.write_bundle(tmp_path / 'f', [({'asset_id': faults._wire_descriptor['asset_id'], 'revision': faults._wire_descriptor['revision'], 'curves': None}, faults)]).path
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['assets'][0]['original'] = {'sha256': manifest['assets'][0]['revision'], 'bytes': 1, 'included': False}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed, match='Only seismic slices'): bundle.open_bundle(root)
