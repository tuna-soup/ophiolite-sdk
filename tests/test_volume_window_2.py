"""E140 s3 C1: the SDK reads `ophiolite.volume-window/2` (an 8-bit cube's window, one byte per sample) and writes it as
SEG-Y data format 8.

Expected values are literals; the cube is synthetic (D75), its codes a fixed formula over (inline, crossline, sample)
that crosses -128, 0 and 127. `windows=2` is sent only for an item whose descriptor is native (R5): a float request's
URLs are literals equal to today's.
"""
import asyncio
import hashlib
import json
import math
import struct
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from ophiolite import _core
from ophiolite import volume_windows as vw
from ophiolite.errors import VerificationFailed
from test_volume_window import BASE, CROSSLINES, INLINES, POSITIONS, REV, S, Gateway, cells, context, document_for, original, world  # noqa: F401

NATIVE_TRACE = 240 + S


def native_context(undefined=-128):
    ctx = dict(context(code=8), undefined_code=undefined)
    return ctx


def code(i, x, s):
    """A stored one-byte code: (i x 77 + x x 11 + s) mod 256 - 128, so (0, 0, 0) is -128 and the cube holds 0 and 127."""
    return (i * 77 + x * 11 + s) % 256 - 128


def native_original():
    """A synthetic SEG-Y format-8 original (regular order); returns (bytes, {(inline ordinal, crossline ordinal): ordinal})."""
    head = bytearray((o * 7) & 0xFF for o in range(3600))
    struct.pack_into('>H', head, 3216, 2500); struct.pack_into('>H', head, 3220, S); struct.pack_into('>h', head, 3224, 8)
    struct.pack_into('>H', head, 3500, 0x0100); struct.pack_into('>h', head, 3502, 1); struct.pack_into('>h', head, 3504, 0)
    out, where = bytearray(head), {}
    for t, (i, x) in enumerate([(i, x) for i in range(5) for x in range(7)]):
        h = bytearray((o * 7 + t + 1) & 0xFF for o in range(240))
        struct.pack_into('>h', h, 70, -100); struct.pack_into('>h', h, 108, 12); struct.pack_into('>H', h, 114, S); struct.pack_into('>H', h, 116, 2500)
        struct.pack_into('>i', h, 180, 50000000 + i * 2500); struct.pack_into('>i', h, 184, 580000000 + x * 2500)
        struct.pack_into('>i', h, 188, INLINES[i]); struct.pack_into('>i', h, 192, CROSSLINES[x])
        out += h + struct.pack('>%db' % S, *[code(i, x, s) for s in range(S)])
        where[(i, x)] = t
    return bytes(out), where


def native_document(query, ctx):
    """The `/2` document the gateway states (D-W), from the SDK's own resolution of the request."""
    selection, axes = vw.resolve(vw.WindowDescription('cube', REV, 'volume', ctx), query)
    shape = [a['count'] for a in axes]
    per = vw.BYTES_MAX // shape[-1]
    traces = math.prod(shape[:-1])
    return {'schema': 'ophiolite.volume-window/2', 'asset_id': 'cube', 'revision': REV, 'source_sha256': REV,
            'interpretation': {'reader': 'asset_connectors.typed_reader/1', 'mapping': 'seismic-volume/2', 'parsing_policy': 'typed-strict/1', 'null_policy': 'none'},
            'window_id': hashlib.sha256(vw.canonical('cube', REV, 'volume', axes, 8, per, 'ophiolite.volume-window/2')).hexdigest(),
            'geometry': 'volume', 'selection': selection, 'axes': axes, 'shape': shape,
            'samples': {'format': 'int8-code', 'format_code': 8, 'byte_order': 'big', 'width': 1, 'undefined_code': ctx['undefined_code']},
            'bytes': math.prod(shape), 'pieces': {'count': -(-traces // per), 'traces_per_piece': per, 'bytes_max': vw.BYTES_MAX},
            'verification': {'client': vw.CLIENT_CHECKS, 'trusted': vw.TRUSTED}}


class NativeGateway(Gateway):
    """The mock window routes over a format-8 original; it answers `/2` only when asked windows=2, else 422. `urls`
    holds every request's path and query, in order."""
    def __init__(self, raw, where, ctx):
        super().__init__(raw, where, ctx)
        self.urls = []

    def headers_answer(self, document, n, per=None):
        per = per or vw.HEADERS_PER_ANSWER
        traces = cells(document)
        body = b''.join(self.raw[3600 + self.where[c] * NATIVE_TRACE:3600 + self.where[c] * NATIVE_TRACE + 240] for c in traces[n * per:(n + 1) * per])
        return body, {'x-ophiolite-piece': '%d/%d' % (n, -(-len(traces) // per))}

    def piece_answer(self, document, n):
        per, sample = document['pieces']['traces_per_piece'], document['axes'][-1]
        at = lambda c: 3600 + self.where[c] * NATIVE_TRACE + 240  # noqa: E731
        body = b''.join(self.raw[at(c) + sample['first']:at(c) + sample['last'] + 1] for c in cells(document)[n * per:(n + 1) * per])
        return body, {'x-ophiolite-piece': '%d/%d' % (n, document['pieces']['count'])}

    def handler(self, request):
        url = urlsplit(str(request.url))
        self.urls.append(url.path + ('?' + url.query if url.query else ''))
        if not url.path.startswith(BASE): return httpx.Response(404, json={})
        rest = url.path[len(BASE):]
        self.log.append(rest or 'describe')
        if rest == '': return httpx.Response(200, json={'scientific': self.ctx})
        pairs = parse_qsl(url.query)
        if ('windows', '2') not in pairs: return httpx.Response(422, json={'code': 'native-form'})
        document = native_document([(k, v) for k, v in pairs if k not in ('window', 'windows')], self.ctx)
        if rest == '/volume-windows': return httpx.Response(200, json=document)
        body, headers = self.answer(document, rest)
        return httpx.Response(200, content=body, headers=headers)


def bits(value):
    return struct.unpack('>I', struct.pack('>f', value))[0]


# --- decode ---------------------------------------------------------------------------------------------------------

def test_codes_decode_to_their_values_and_the_undefined_code_to_the_quiet_nan():
    body = b'\x80\x00\x7f'
    assert [bits(v) for v in vw.decode(body, 8, -128)] == [0x7fc00000, 0x00000000, 0x42fe0000]  # NaN, 0.0, 127.0
    assert vw.decode(body, 8, None) == [-128.0, 0.0, 127.0]
    assert vw.codes(body) == [-128, 0, 127]


# --- the document ---------------------------------------------------------------------------------------------------

def described(ctx):
    return vw.WindowDescription('cube', REV, 'volume', ctx)


QUERY = [('inline', '100:102'), ('sample', '2:4'), ('by', 'label')]


@pytest.mark.parametrize('undefined', [-128, None])
def test_a_native_document_is_checked_as_volume_window_2(undefined):
    ctx = native_context(undefined)
    doc = native_document(QUERY, ctx)
    assert (doc['bytes'], doc['pieces']['traces_per_piece']) == (42, 11184810)  # inlines 100 and 102 (step 2) x 7 crosslines x 3 samples, one byte each
    assert vw.check_document(doc, asset='cube', revision=REV, query=QUERY, description=described(ctx)) is doc


BROKEN = [  # (name, change, description context): each refused by name before any piece
    ('a /1 document for a native cube', lambda d: d.update(document_for(QUERY, context(code=1))), native_context()),
    ('the code for no value not the asset\'s', lambda d: d['samples'].update(undefined_code=None), native_context(-128)),
    ('the bytes at four a sample', lambda d: d.update(bytes=252), native_context()),
    ('the /1 window id', lambda d: d.update(window_id=hashlib.sha256(vw.canonical('cube', REV, 'volume', d['axes'], 8, 11184810)).hexdigest()), native_context()),
    ('a /2 document for a float cube', lambda d: None, context(code=1)),
]


@pytest.mark.parametrize('name,change,ctx', BROKEN, ids=[b[0] for b in BROKEN])
def test_a_broken_native_document_is_refused_by_name(name, change, ctx):
    doc = native_document(QUERY, native_context())
    change(doc)
    with pytest.raises(VerificationFailed):
        vw.check_document(doc, asset='cube', revision=REV, query=QUERY, description=described(ctx))


# --- the requests (R5) ----------------------------------------------------------------------------------------------

DESCRIBE = '/api/v1/projects/p/scientific-assets/cube/revisions/' + REV + '?profiles=%2F1%2C%2F2%2C%2F3%2C%2F4'
FLOAT_DOCUMENT = BASE + '/volume-windows?inline=100%3A102&sample=2%3A4&by=label'
NATIVE_DOCUMENT = BASE + '/volume-windows?inline=100%3A102&sample=2%3A4&by=label&windows=2'


@pytest.fixture
def unchecked_descriptor(monkeypatch):
    monkeypatch.setattr(_core, 'verify_typed_descriptor', lambda value, project, asset, revision: value)  # the descriptor is not under test


def float_gateway():
    raw, where = original(None, 1)
    gateway = Gateway(raw, where, context(code=1))
    gateway.urls = []
    handler = gateway.handler
    def recording(request):
        url = urlsplit(str(request.url)); gateway.urls.append(url.path + ('?' + url.query if url.query else ''))
        return handler(request)
    return gateway, recording


def native_gateway(undefined=-128):
    raw, where = native_original()
    gateway = NativeGateway(raw, where, native_context(undefined))
    return gateway, gateway.handler


def read_sync(handler):
    from ophiolite import Client
    return Client('http://localhost', 'p', None, httpx.Client(transport=httpx.MockTransport(handler))).read_window('cube', REV, inline='100:102', sample='2:4', by='label')


def read_async(handler):
    from ophiolite.aio import AsyncClient
    async def go():
        client = AsyncClient('http://localhost', 'p', None, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try: return await client.read_window('cube', REV, inline='100:102', sample='2:4', by='label')
        finally: await client.http.aclose()
    return asyncio.run(go())


@pytest.mark.parametrize('read', [read_sync, read_async], ids=['client', 'aio'])
def test_a_float_cube_is_asked_as_today(unchecked_descriptor, read):
    gateway, handler = float_gateway()
    result = read(handler)
    piece = BASE + '/volume-windows/pieces/0?inline=100%3A102&sample=2%3A4&by=label&window=' + result.document['window_id']
    assert gateway.urls == [DESCRIBE, FLOAT_DOCUMENT, piece]
    assert result.document['schema'] == 'ophiolite.volume-window/1'


@pytest.mark.parametrize('read', [read_sync, read_async], ids=['client', 'aio'])
@pytest.mark.parametrize('undefined', [-128, None])
def test_a_native_cube_is_asked_windows_2_and_read_at_native_size(unchecked_descriptor, read, undefined):
    gateway, handler = native_gateway(undefined)
    result = read(handler)
    piece = BASE + '/volume-windows/pieces/0?inline=100%3A102&sample=2%3A4&by=label&windows=2&window=' + result.document['window_id']
    assert gateway.urls == [DESCRIBE, NATIVE_DOCUMENT, piece]
    assert result.document['schema'] == 'ophiolite.volume-window/2' and result.shape == [2, 7, 3]
    # literal codes, samples 2..4: inline 100 (ordinal 0) at crosslines 300 and 305, inline 102 (ordinal 1) at 330
    assert result.values[0][0] == [-126.0, -125.0, -124.0] and result.values[0][1] == [-115.0, -114.0, -113.0]
    assert result.values[1][6] == [17.0, 18.0, 19.0]


def test_the_iterator_holds_the_verbatim_codes(unchecked_descriptor):
    from ophiolite import Client
    gateway, handler = native_gateway()
    client = Client('http://localhost', 'p', None, httpx.Client(transport=httpx.MockTransport(handler)))
    pieces = list(client.iter_window('cube', REV, by='ordinal', inline='0', crossline='0:1'))
    assert len(pieces) == 1
    assert pieces[0].codes() == [[-128, -127, -126, -125, -124, -123, -122, -121, -120, -119, -118],
                                 [-117, -116, -115, -114, -113, -112, -111, -110, -109, -108, -107]]
    assert bits(pieces[0].values[0][0]) == 0x7fc00000 and pieces[0].values[0][1] == -127.0
    raw, where = original(None, 1)
    float_pieces = list(Client('http://localhost', 'p', None, httpx.Client(transport=httpx.MockTransport(Gateway(raw, where, context(code=1)).handler)))
                        .iter_window('cube', REV, by='ordinal', inline='0'))
    with pytest.raises(ValueError):
        float_pieces[0].codes()


# --- exchange get: the window file, read by segyio ----------------------------------------------------------------

def test_exchange_asks_a_float_cube_as_today(world):
    make, tmp = world
    gateway, handler = float_gateway()
    gateway.handler = handler
    make(gateway).get('cube', output=tmp / 'out', window='inline=100:102,sample=2:4,by=label')
    assert gateway.urls[1] == FLOAT_DOCUMENT and not any('windows=2' in u for u in gateway.urls)


def test_a_native_window_is_written_as_segy_format_8_and_segyio_reads_the_literals(world):
    segyio = pytest.importorskip('segyio')
    make, tmp = world
    raw, where = native_original()
    gateway = NativeGateway(raw, where, native_context())
    outcome = make(gateway).get('cube', output=tmp / 'out', window='inline=102:104,crossline=305:310,sample=0:3,by=label')
    assert outcome.outcome == 'got'
    assert gateway.urls[1] == BASE + '/volume-windows?inline=102%3A104&crossline=305%3A310&sample=0%3A3&by=label&windows=2'
    windows = [u for u in gateway.urls if u.startswith(BASE + '/volume-windows')]
    assert len(windows) == 4 and all('windows=2' in u for u in windows)  # document, file header, headers and pieces
    path = tmp / 'out' / 'window.sgy'
    data = path.read_bytes()
    assert len(data) == 3600 + 4 * (240 + 4)
    with segyio.open(str(path), ignore_geometry=True) as f:
        assert int(f.format) == 8 and f.tracecount == 4 and len(f.samples) == 4
        assert [list(map(int, f.trace[k])) for k in range(4)] == [[-40, -39, -38, -37], [-29, -28, -27, -26], [37, 38, 39, 40], [48, 49, 50, 51]]
        heads = [(h[segyio.TraceField.INLINE_3D], h[segyio.TraceField.CROSSLINE_3D], h[segyio.TraceField.TRACE_SAMPLE_COUNT],
                  h[segyio.TraceField.DelayRecordingTime]) for h in f.header]
        assert heads == [(102, 305, 4, 12), (102, 310, 4, 12), (104, 305, 4, 12), (104, 310, 4, 12)]
        assert f.bin[segyio.BinField.Format] == 8 and f.bin[segyio.BinField.Samples] == 4
    record = json.loads((tmp / 'out' / 'window.json').read_text())
    assert record['document']['schema'] == 'ophiolite.volume-window/2'
