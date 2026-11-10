"""E141 s1 C3 against the in-process gateway: `read_window` and `iter_window`, sync and async, read part of a volume
or 2D line and verify it (D-C, D-S).

Synthetic fixtures only (D75): the Platform's cube.json and line.json uploads and journeys.json's windows, literal
values and `wire_sha256`; the multipiece line and the boundary volume are generated at test time by the Platform's
own test helpers. The document and piece tests replay answers recorded from this gateway through a mock transport,
then break one thing at a time. Each test names the mutation it catches."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from ophiolite import Client, Credential
from ophiolite import volume_windows as vw
from ophiolite.errors import IntegrityConflict, PermissionRefused, Unavailable, VerificationFailed
from ophiolite.volume_windows import WindowRefused

from project_gateway.tests import test_volume_window_contract as contract
from project_gateway.tests.test_volume_window_contract import cube_bytes, line_bytes

ORIGIN = 'https://workspace.example'
MIB = 1024 * 1024
FIXTURES = Path(contract.__file__).parent / 'fixtures/volume_window'
JOURNEYS = json.loads((FIXTURES / 'journeys.json').read_text())
WINDOWS = JOURNEYS['windows']
SLICE_1 = [r for r in JOURNEYS['journeys'] if r['slice'] == 1]
UPLOAD = dict(declared={'crs': 'EPSG:23031', 'z_domain': 'time'}, attribution='Synthetic', audience=[], rights_confirmed=True)
RANGES = {'inline': 'inline', 'crossline': 'crossline', 'trace': 'trace', 'sample': 'sample', 'by': 'by'}


def ranges(window):
    return {RANGES[k]: v for k, v in window['query']}


def land(alice, kind):
    if kind == 'line':
        return alice.upload_data(line_bytes('ieee'), profile='segy-line/1', name='Line', filename='line.sgy', **UPLOAD)
    return alice.upload_data(cube_bytes(kind), profile='segy/1', name='Cube ' + kind, filename='cube-%s.sgy' % kind, **UPLOAD)


@pytest.fixture
def requests(web):
    log = []
    web.c.event_hooks['request'].append(lambda request: log.append(request.url.path))
    return log


@pytest.fixture
def anyio_backend(): return 'asyncio'


# --- 1. the slice-1 journeys, sync and async, read and iterated (R1-19) -------------------------------------------

CASES = [(row['id'], name, kind, mode)
         for row in SLICE_1 if row['surface'] in ('sdk', 'http')
         for name in row['windows']
         for kind in (('ieee',) if WINDOWS[name]['geometry'] == 'line' else ('ibm', 'ieee'))
         for mode in ('read', 'iter', 'async-read', 'async-iter')]


def nest(shape, traces):
    """Iterated traces in C order, nested as the document's shape says (the test's own assembly)."""
    return [traces[i * shape[1]:(i + 1) * shape[1]] for i in range(shape[0])] if len(shape) == 3 else traces


async def async_read(web, info, window, mode):
    from ophiolite.aio import AsyncClient
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url=ORIGIN) as http:
        async with AsyncClient(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            if mode == 'async-read':
                got = await alice.read_window(info.asset_id, info.revision, **ranges(window))
                return got.values, got.window_digest, got
            reader = await alice.iter_window(info.asset_id, info.revision, **ranges(window))
            traces = []
            async with reader:
                async for piece in reader: traces.extend(piece.values)
            return nest(reader.document['shape'], traces), reader.window_digest, None


@pytest.mark.parametrize('row,name,kind,mode', CASES, ids=['%s-%s-%s-%s' % c for c in CASES])
def test_each_slice_1_journey_reads_its_literals(web, requests, row, name, kind, mode):
    """Mutations caught: the IBM exponent bias 64 -> 63 (ibm values); the window digest left uncomputed."""
    alice = client(web, 'alice', 'delegate')
    window = WINDOWS[name]
    info = land(alice, 'line' if window['geometry'] == 'line' else kind)
    requests.clear()
    if mode == 'read':
        got = alice.read_window(info.asset_id, info.revision, **ranges(window))
        values, digest = got.values, got.window_digest
    elif mode == 'iter':
        with alice.iter_window(info.asset_id, info.revision, **ranges(window)) as reader:
            traces = [t for piece in reader for t in piece.values]
            assert reader.complete
        values, digest, got = nest(reader.document['shape'], traces), reader.window_digest, None
    else:
        values, digest, got = asyncio.run(async_read(web, info, window, mode))
    assert digest == window['wire_sha256'][kind]
    if window['at'] == 'all':
        assert hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest() == window['values_sha256']
        if got is not None:
            np = pytest.importorskip('numpy')
            assert got.to_numpy().shape == (5, 7, 11) and isinstance(got.to_numpy(), np.ndarray)
    else:
        assert values == window['values']
    if mode in ('read', 'iter'):  # R1-3: the original is never asked for
        assert not [p for p in requests if p.endswith('/representations/artifact')]
        assert any('/volume-windows/pieces/' in p for p in requests)


def test_every_slice_1_row_has_cases_here():
    """C4 counts these ids: every slice-1 row is executed by this module, no skip."""
    assert {c[0] for c in CASES} == {'http-plain-window', 'sdk-read-window'}
    assert len(CASES) == 2 * (6 * 2 + 1) * 4


def test_a_multipiece_line_is_assembled_in_piece_order(web, monkeypatch):
    """The 9,000 x 1,000 generated line (values n x 1000 + s), whole: two pieces of 8,388 and 612 traces.
    Mutation caught: pieces assembled in reverse."""
    from project_gateway.tests.test_volume_window_line_read import long_line
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * MIB))
    raw = long_line()
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_data(raw, profile='segy-line/1', name='Long line', filename='long.sgy', **UPLOAD)
    got = alice.read_window(info.asset_id, info.revision)
    assert got.document['pieces'] == {'count': 2, 'traces_per_piece': 8388, 'bytes_max': 33554432}
    assert got.shape == [9000, 1000] and len(got.values) == 9000
    for n in (0, 1, 8387, 8388, 8999):
        assert got.values[n] == [float(n * 1000 + s) for s in range(1000)], n
    words = hashlib.sha256()
    for n in range(9000): words.update(raw[3600 + n * 4240 + 240:3600 + (n + 1) * 4240])
    assert got.window_digest == words.hexdigest()


# --- 2. and 3. recorded answers, replayed through a mock transport ------------------------------------------------

PIECE = 12 * 11 * 4  # the recording's piece bound: 12 traces of the 11-sample cube -> the whole window in 3 pieces


@pytest.fixture
def recorded(web, monkeypatch):
    """The answers to a whole-cube window read in 3 pieces, a line window and a slice, recorded from this gateway.
    The piece bound is lowered on both sides for the recording only (the server's layout and its fixed bound, the
    SDK's BYTES_MAX); the replays keep the SDK's bound at the recording's."""
    from project_gateway import volume_windows as server
    layout = server.layout
    monkeypatch.setattr(server, 'RESULT_BYTES', PIECE)
    monkeypatch.setattr(server, 'layout', lambda resolved, *_: layout(resolved, PIECE))
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    alice = client(web, 'alice', 'delegate')
    cube, line = land(alice, 'ibm'), land(alice, 'line')
    answers = {}

    def proxy(request):
        real = web.c.request(request.method, str(request.url), headers=dict(request.headers))
        answers[request.url.raw_path.decode()] = (real.status_code, dict(real.headers), real.content)
        return httpx.Response(real.status_code, headers=real.headers, content=real.content)
    recorder = Client(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), httpx.Client(transport=httpx.MockTransport(proxy)))
    whole = recorder.read_window(cube.asset_id, cube.revision)
    assert whole.document['pieces'] == {'count': 3, 'traces_per_piece': 12, 'bytes_max': PIECE}
    recorder.read_window(line.asset_id, line.revision, trace='1:3')
    recorder.read_slice(cube.asset_id, cube.revision, 'inline', 102)
    return {'answers': answers, 'cube': cube, 'line': line, 'values': whole.values, 'digest': whole.window_digest}


class Body(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A body sent in steps: `cut` bytes, then a ReadError (`fail`) or a wait that never ends (`block`); closes counted."""
    def __init__(self, raw, cut=None, fail=False, block=False, closed=None):
        self.raw, self.cut, self.fail, self.block, self.closed = raw, cut, fail, block, closed if closed is not None else []

    def __iter__(self):
        yield self.raw[:self.cut]
        if self.fail: raise httpx.ReadError('cut mid-body')
        if self.cut is not None: yield self.raw[self.cut:]

    async def __aiter__(self):
        yield self.raw[:self.cut]
        if self.fail: raise httpx.ReadError('cut mid-body')
        if self.block: await asyncio.Event().wait()
        if self.cut is not None: yield self.raw[self.cut:]

    def close(self): self.closed.append('close')
    async def aclose(self): self.closed.append('aclose')


class Replay:
    """A mock transport over the recorded answers; `change(path, status, headers, body)` may alter one answer (return
    None to keep it, an exception to raise, or a replacement). Every asked path is logged."""
    def __init__(self, answers, change=None):
        self.answers, self.change, self.asked = answers, change, []

    def __call__(self, request):
        path = request.url.raw_path.decode()
        self.asked.append(path)
        status, headers, body = self.answers[path]
        headers = {k: v for k, v in headers.items() if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')}
        changed = self.change(path, status, dict(headers), body, self.asked.count(path)) if self.change else None
        if isinstance(changed, BaseException): raise changed
        if changed is not None: status, headers, body = changed
        if isinstance(body, Body): return httpx.Response(status, headers=headers, stream=body)
        return httpx.Response(status, headers=headers, content=body)

    def pieces(self): return [p for p in self.asked if '/pieces/' in p]


def replayed(recorded, change=None):
    replay = Replay(recorded['answers'], change)
    return Client(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), httpx.Client(transport=httpx.MockTransport(replay))), replay


def replayed_async(recorded, change=None):
    from ophiolite.aio import AsyncClient
    replay = Replay(recorded['answers'], change)
    return AsyncClient(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), httpx.AsyncClient(transport=httpx.MockTransport(replay))), replay


def test_the_replay_reads_the_recorded_window(recorded, monkeypatch):
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    alice, replay = replayed(recorded)
    got = alice.read_window(recorded['cube'].asset_id, recorded['cube'].revision)
    assert (got.values, got.window_digest) == (recorded['values'], recorded['digest']) and len(replay.pieces()) == 3


# --- 2. document checks (acceptance 4): one broken document per D-C row, no piece asked ----------------------------

def rehash(d):
    """The window_id recomputed for a changed document, so that check does not catch the defect first."""
    d['window_id'] = hashlib.sha256(vw.canonical(d['asset_id'], d['revision'], d['geometry'], d['axes'], d['samples']['format_code'],
                                                 d['pieces']['traces_per_piece'])).hexdigest()


def other_shape(d):  # shape and bytes both changed, consistently with each other
    d['shape'] = [5, 7, 10]; d['bytes'] = 5 * 7 * 10 * 4


BROKEN = {  # name -> (geometry, change, check named)
    'structure: an extra field': ('volume', lambda d: d.update(extra=1), 'identity'),
    'structure: a wrong type': ('volume', lambda d: d.update(bytes='1540'), 'identity'),
    'source_is_revision': ('volume', lambda d: d.update(source_sha256='0' * 64), 'identity'),
    'asset': ('volume', lambda d: d.update(asset_id='another'), 'identity'),
    'interpretation_matches_geometry': ('volume', lambda d: d['interpretation'].update(mapping='seismic-line/1'), 'axes'),
    'axes_match_geometry': ('volume', lambda d: d['axes'].reverse(), 'axes'),
    'line_is_ordinal': ('line', lambda d: (d.update(selection='label'), rehash(d)), 'axes'),
    'counts_span': ('volume', lambda d: (d['axes'][0].update(last=3), rehash(d)), 'shape'),
    'labels_count': ('volume', lambda d: d['axes'][0]['labels'].pop(), 'shape'),
    'shape_matches_axes': ('volume', other_shape, 'shape'),
    'bytes_is_product': ('volume', lambda d: d.update(bytes=d['bytes'] + 4), 'shape'),
    'format_matches_code': ('volume', lambda d: d['samples'].update(format='ieee-float32'), 'shape'),
    'bytes_max_fixed': ('volume', lambda d: d['pieces'].update(bytes_max=d['pieces']['bytes_max'] + 4), 'shape'),
    'pieces_arithmetic': ('volume', lambda d: (d['pieces'].update(traces_per_piece=11, count=4), rehash(d)), 'shape'),
    'window_id_canonical': ('volume', lambda d: d.update(window_id='f' * 64), 'identity'),
    'verification closed': ('volume', lambda d: d['verification']['client'].reverse(), 'identity'),
    'axes against the volume': ('volume', lambda d: d['axes'][0].update(labels=[l + 1 for l in d['axes'][0]['labels']]), 'axes'),
    'sample start against the volume': ('volume', lambda d: d['axes'][2].update(start=d['axes'][2]['start'] + 2.5), 'axes'),
    'trace numbers against the line': ('line', lambda d: d['axes'][0].update(labels=[1002, 1003, 1010]), 'axes'),
}
RECOMPUTED = 'the axes are not the ones the request names on this asset'
WHY = {  # the sentence each row's own check states (a later check catching the defect names another)
    'structure: an extra field': 'is not an ophiolite.volume-window/1 document', 'structure: a wrong type': 'does not satisfy',
    'source_is_revision': 'names another asset or revision', 'asset': 'names another asset or revision',
    'interpretation_matches_geometry': "not of the asset's geometry", 'axes_match_geometry': "the axes are not the geometry's",
    'line_is_ordinal': 'addressed by ordinal', 'counts_span': 'axis count is not', 'labels_count': 'one label per trace',
    'shape_matches_axes': 'the shape is not the axis counts', 'bytes_is_product': 'the byte count', 'format_matches_code': 'sample format',
    'bytes_max_fixed': '/1 partition', 'pieces_arithmetic': '/1 partition', 'window_id_canonical': 'window_id is not the digest',
    'verification closed': 'closed lists', 'axes against the volume': RECOMPUTED, 'sample start against the volume': RECOMPUTED,
    'trace numbers against the line': RECOMPUTED,
}


def broken(name):
    geometry, change, _ = BROKEN[name]

    def apply(path, status, headers, body, n):
        if path.split('?')[0].endswith('/volume-windows'):
            d = json.loads(body); change(d)
            return status, headers, json.dumps(d).encode()
    return geometry, apply


@pytest.mark.parametrize('name', list(BROKEN))
def test_a_broken_document_is_refused_by_name_and_no_piece_is_asked(recorded, monkeypatch, name):
    """Mutation caught, per row: that check turned off in check_document."""
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    geometry, apply = broken(name)
    alice, replay = replayed(recorded, apply)
    info = recorded['cube'] if geometry == 'volume' else recorded['line']
    with pytest.raises(VerificationFailed) as failed:
        alice.read_window(info.asset_id, info.revision, **({} if geometry == 'volume' else {'trace': '1:3'}))
    assert failed.value.details == {'check': BROKEN[name][2]} and WHY[name] in str(failed.value), str(failed.value)
    assert replay.pieces() == []


# --- 3. pieces (acceptance 5) --------------------------------------------------------------------------------------

def piece_1(alter):
    """Alter piece 1's recorded answer only."""
    def apply(path, status, headers, body, n):
        if '/pieces/1?' in path: return alter(status, headers, body, n)
    return apply


def header(name, value):
    def alter(status, headers, body, n):
        headers = {k: v for k, v in headers.items() if k.lower() != name}
        if value is not None: headers[name] = value
        return status, headers, body
    return alter


FAILED = {  # name -> (alteration of piece 1, error raised, check named or None)
    'missing (404)': (lambda s, h, b, n: (404, {'content-type': 'application/json'}, b'{"code":"not-found","error":"No such piece"}'), Unavailable, None),
    'transport error twice': (lambda s, h, b, n: httpx.ConnectError('down'), Unavailable, None),
    'another window': (header('x-ophiolite-window', 'e' * 64), VerificationFailed, 'piece-identity'),
    'another revision': (header('x-ophiolite-revision', 'd' * 64), VerificationFailed, 'piece-identity'),
    'another index': (header('x-ophiolite-piece', '2/3'), VerificationFailed, 'piece-identity'),
    'window absent': (header('x-ophiolite-window', None), VerificationFailed, 'piece-identity'),
    'revision absent': (header('x-ophiolite-revision', None), VerificationFailed, 'piece-identity'),
    'index absent': (header('x-ophiolite-piece', None), VerificationFailed, 'piece-identity'),
    'stale digest': (header('x-content-sha256', hashlib.sha256(b'stale').hexdigest()), IntegrityConflict, 'piece-digest'),
    'truncated body': (lambda s, h, b, n: (s, {**h, 'x-content-sha256': hashlib.sha256(b[:-4]).hexdigest()}, b[:-4]), VerificationFailed, 'completeness'),
}


@pytest.mark.parametrize('name', list(FAILED))
def test_a_failed_piece_raises_and_the_window_is_not_complete(recorded, monkeypatch, name):
    """Mutations caught: each piece check turned off in verify_piece; the retry made unbounded (transport error twice)."""
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    alter, error, check = FAILED[name]
    alice, replay = replayed(recorded, piece_1(alter))
    reader = alice.iter_window(recorded['cube'].asset_id, recorded['cube'].revision)
    assert next(reader).index == 0
    with pytest.raises(error) as raised:
        next(reader)
    if check: assert raised.value.details == {'check': check}
    assert (reader.complete, reader.window_digest) == (False, None)
    assert sum('/pieces/1?' in p for p in replay.pieces()) == (2 if name == 'transport error twice' else 1)
    with pytest.raises(error):
        alice.read_window(recorded['cube'].asset_id, recorded['cube'].revision)


@pytest.mark.parametrize('name', list(FAILED))
def test_the_async_reader_fails_the_same(recorded, monkeypatch, name):
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    alter, error, check = FAILED[name]

    async def run():
        alice, replay = replayed_async(recorded, piece_1(alter))
        async with alice:
            reader = await alice.iter_window(recorded['cube'].asset_id, recorded['cube'].revision)
            assert (await reader.__anext__()).index == 0
            with pytest.raises(error) as raised:
                await reader.__anext__()
            if check: assert raised.value.details == {'check': check}
            assert (reader.complete, reader.window_digest) == (False, None)
            assert sum('/pieces/1?' in p for p in replay.pieces()) == (2 if name == 'transport error twice' else 1)
    asyncio.run(run())


def test_self_consistent_substitution_is_trusted_server_behaviour(recorded, monkeypatch):
    """R1-15, the documented limit of `verification.client`: piece 1 answered with piece 0's body (equal length, its own
    correct digest, piece 1's identity headers) is accepted; only the server's chunk digests at read stand behind it."""
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    cube = recorded['cube']
    first = next(v for p, v in recorded['answers'].items() if '/pieces/0?' in p)[2]
    alice, _ = replayed(recorded, piece_1(lambda s, h, b, n: (s, {**h, 'x-content-sha256': hashlib.sha256(first).hexdigest()}, first)))
    got = alice.read_window(cube.asset_id, cube.revision)
    assert got.window_digest != recorded['digest'] and got.values != recorded['values']
    flat = [t for inline in got.values for t in inline]
    assert flat[12:24] == flat[0:12] and flat[24:] == [t for inline in recorded['values'] for t in inline][24:]  # piece 1 holds piece 0's traces


def test_a_body_cut_mid_read_is_asked_once_more_and_read_slice_is_unchanged(recorded, monkeypatch):
    """R1-1: piece 1's first answer raises ReadError mid-body; the window reader asks again and gets the same values
    and digest. read_slice over the same kind of transport still raises on its first ReadError.
    Mutation caught: the window retry removed."""
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    cube = recorded['cube']
    cut = piece_1(lambda s, h, b, n: (s, h, Body(b, cut=100, fail=True)) if n == 1 else None)
    alice, replay = replayed(recorded, cut)
    got = alice.read_window(cube.asset_id, cube.revision)
    assert (got.values, got.window_digest) == (recorded['values'], recorded['digest'])
    assert sum('/pieces/1?' in p for p in replay.pieces()) == 2

    def slice_cut(path, status, headers, body, n):
        if '/slices/inline/102' in path: return status, headers, Body(body, cut=100, fail=True)
    slicer, replay = replayed(recorded, slice_cut)
    with pytest.raises(Unavailable) as failed:
        slicer.read_slice(cube.asset_id, cube.revision, 'inline', 102)
    assert failed.value.code == 'unreachable' and sum('/slices/' in p for p in replay.asked) == 1


def test_the_async_reader_retries_the_same(recorded, monkeypatch):
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    cube = recorded['cube']

    async def run():
        alice, replay = replayed_async(recorded, piece_1(lambda s, h, b, n: (s, h, Body(b, cut=100, fail=True)) if n == 1 else None))
        async with alice:
            got = await alice.read_window(cube.asset_id, cube.revision)
        return got, replay
    got, replay = asyncio.run(run())
    assert (got.values, got.window_digest) == (recorded['values'], recorded['digest'])
    assert sum('/pieces/1?' in p for p in replay.pieces()) == 2


def test_cancelling_during_a_piece_body_closes_its_stream(recorded, monkeypatch):
    """R1-16: piece 1's body sends 100 bytes and then waits; cancelling the read there closes the response stream."""
    import anyio
    monkeypatch.setattr(vw, 'BYTES_MAX', PIECE)
    cube, closed = recorded['cube'], []

    async def run():
        alice, _ = replayed_async(recorded, piece_1(lambda s, h, b, n: (s, h, Body(b, cut=100, block=True, closed=closed))))
        async with alice:
            reader = await alice.iter_window(cube.asset_id, cube.revision)
            await reader.__anext__()
            with anyio.move_on_after(0.5) as scope:
                await reader.__anext__()
            assert scope.cancelled_caught
            assert (reader.complete, reader.window_digest) == (False, None)
    asyncio.run(run())
    assert closed == ['aclose']


# --- 4. the server's refusal, by name ------------------------------------------------------------------------------

OFF_GRID = "Inline 101 is not on this volume's grid: inlines run from 100 to 108 in steps of 2. Nothing was read."


def test_an_off_grid_window_raises_window_refused_with_the_servers_sentence(web):
    """Mutation caught: the window-refused mapping removed (Incompatible raised instead)."""
    alice = client(web, 'alice', 'delegate')
    cube = land(alice, 'ibm')
    with pytest.raises(WindowRefused) as refused:
        alice.read_window(cube.asset_id, cube.revision, inline=101, by='label')
    assert (refused.value.reason, str(refused.value), refused.value.status) == ('off-grid', OFF_GRID, 422)

    async def run():
        from ophiolite.aio import AsyncClient
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url=ORIGIN) as http:
            async with AsyncClient(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), http) as a:
                await a.read_window(cube.asset_id, cube.revision, inline=101, by='label')
    with pytest.raises(WindowRefused) as refused:
        asyncio.run(run())
    assert (refused.value.reason, str(refused.value)) == ('off-grid', OFF_GRID)


# --- 5. a long read stops when its key is removed (acceptance 5, client half) --------------------------------------

def test_a_removed_access_key_stops_a_long_read_after_its_first_piece(keyed, monkeypatch):
    """E25 personal access key (read), removed between piece 0 and piece 1 of the boundary 65 volume: iter_window yields
    piece 0, then raises the SDK's existing category for the server's 403 credential refusal (PermissionRefused);
    the window is not complete (supervisor ruling: no change to the auth path or the status mapping)."""
    from project_gateway.tests.test_volume_window_read import boundary
    from test_access_key_chain import session
    web = keyed
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * MIB))
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_data(boundary(65), profile='segy/1', name='Boundary', filename='boundary.sgy', **UPLOAD)
    key = create(web, 'read')
    reader = Client(ORIGIN, 'p', Credential.bearer(key['key']), web.c).iter_window(info.asset_id, info.revision)
    first = next(reader)
    assert (first.index, first.count, first.traces, len(first.values)) == (0, 2, (0, 4095), 4096)
    del first
    _, headers = session(web, 'alice')
    assert web.c.post('/api/v1/access-keys/remove', json={'id': key['id']}, headers=headers).status_code == 200
    web.c.cookies.clear()
    with pytest.raises(PermissionRefused) as refused:
        next(reader)
    assert refused.value.status == 403
    assert (reader.complete, reader.window_digest) == (False, None)
