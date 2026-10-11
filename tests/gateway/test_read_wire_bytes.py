"""H44 item 5: a read keeps the curve bodies exactly as served, through Client and AsyncClient alike.

Public `read` only, through tests/helpers/async_read_adapter.py; no reader internals and no assumption about how the
artifact is fetched: the transport answers by path (the representation id) and by the requested curve, never by request
count, and honours a Range header, so the scenario holds whether the artifact comes whole or in ranges (E100d1 A4)."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import httpx
import pytest
from ophiolite import Client, _core
from ophiolite.bundle import write_bundle

HELPERS = Path(__file__).resolve().parents[1] / 'helpers'
CURVES = ('GR', 'RHOB')


def noncanonical(view):
    """Valid JSON that no json.dumps of the parsed value reproduces: keys reversed, padded separators, numbers spelled
    with an exponent."""
    def spell(value):
        if isinstance(value, dict):
            return '{\n  ' + ' ,\n  '.join('%s :  %s' % (json.dumps(k), spell(v)) for k, v in reversed(list(value.items()))) + '\n}'
        if isinstance(value, list):
            return '[ ' + ' ,  '.join(spell(v) for v in value) + ' ]'
        if isinstance(value, float):
            return repr(value / 100) + 'e2' if value else '0.0e0'
        return json.dumps(value)
    return (spell(view) + '\n\n').encode()


@pytest.fixture
def served(fixture):
    """Per curve: its descriptor and its noncanonical normalized body (its own representation id), digests rewritten to
    match; one artifact."""
    first, raw, artifact = fixture()
    descriptors, bodies = {}, {}
    for curve in CURVES:
        d, v = json.loads(json.dumps(first)), json.loads(raw)
        d['scientific']['curve'] = curve; v['curve'] = curve
        body = noncanonical(v)
        rep = next(r for r in d['representations'] if r['kind'] == 'normalized')
        rep['id'] = 'curve-' + curve; rep['bytes'] = len(body); rep['sha256'] = hashlib.sha256(body).hexdigest()
        _core.verify_pair(d, body, artifact, curve)  # precondition: the sync reader's checks accept the rewritten pair
        assert json.dumps(json.loads(body)).encode() != body and json.loads(body) == v
        descriptors[curve], bodies['curve-' + curve] = d, body
    bodies['las'] = artifact

    def handler(request):
        if '/representations/' in request.url.path:
            body = bodies[request.url.path.rsplit('/', 1)[1]]
            wanted = request.headers.get('range')
            if wanted:  # bytes=a-b
                start, end = (int(x) for x in wanted.split('=', 1)[1].split('-'))
                return httpx.Response(206, content=body[start:end + 1], headers={'content-range': 'bytes %d-%d/%d' % (start, min(end, len(body) - 1), len(body))})
            return httpx.Response(200, content=body)
        return httpx.Response(200, json=descriptors[request.url.params['curve']])
    return first, bodies, descriptors, httpx.MockTransport(handler)


@pytest.fixture(params=['sync', 'async'])
def reader(request):
    """The Client class for the scenario: Client itself, or AsyncClient driven through the adapter."""
    if request.param == 'sync':
        yield Client; return
    spec = importlib.util.spec_from_file_location('async_read_adapter', HELPERS / 'async_read_adapter.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    loop = asyncio.new_event_loop(); instances = []
    try:
        yield module.adapter(loop, instances)
    finally:
        for client in instances: loop.run_until_complete(client.http.aclose())
        loop.close()


def test_the_served_bodies_are_kept_byte_for_byte(served, reader):
    first, bodies, descriptors, transport = served
    with httpx.Client(transport=transport) as http:
        data = reader('http://localhost', first['project_id'], http=http).read(first['asset_id'], first['revision'], list(CURVES))
    assert data._wire_curve_bytes == [bodies['curve-' + c] for c in CURVES]  # red before (async): None
    for curve, body in zip(CURVES, data._wire_curve_bytes):
        rep = next(r for r in descriptors[curve]['representations'] if r['kind'] == 'normalized')
        assert hashlib.sha256(body).hexdigest() == rep['sha256']


def test_a_second_read_on_the_same_client_is_its_own(served, reader):
    first, bodies, _, transport = served
    with httpx.Client(transport=transport) as http:
        client = reader('http://localhost', first['project_id'], http=http)
        both = client.read(first['asset_id'], first['revision'], ['GR', 'RHOB'])
        one = client.read(first['asset_id'], first['revision'], ['GR'])
    assert one._wire_curve_bytes == [bodies['curve-GR']]
    assert both._wire_curve_bytes == [bodies['curve-GR'], bodies['curve-RHOB']]


def test_the_bundle_carries_the_served_bytes_as_the_sync_read_does(served, reader, tmp_path):
    first, bodies, _, transport = served
    folders = {}
    for name, cls in (('sync', Client), ('this', reader)):
        with httpx.Client(transport=transport) as http:
            data = cls('http://localhost', first['project_id'], http=http).read(first['asset_id'], first['revision'], list(CURVES))
        write_bundle(tmp_path / name, [({'asset_id': first['asset_id'], 'revision': first['revision'], 'curves': list(CURVES)}, data)])
        folders[name] = {p.relative_to(tmp_path / name).as_posix(): p.read_bytes() for p in (tmp_path / name).rglob('curve-*.json')}
    assert sorted(folders['this']) == sorted(folders['sync']) and len(folders['sync']) == len(CURVES)
    assert folders['this'] == folders['sync']
    assert sorted(folders['sync'].values()) == sorted(bodies['curve-' + c] for c in CURVES)
