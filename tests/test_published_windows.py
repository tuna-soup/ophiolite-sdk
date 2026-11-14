"""E175 s1 C4: the SDK reads `ophiolite.volume-window/3` (a cube as published, at its own sample size, each piece and
headers answer led by its positions' mask) and writes it as SEG-Y in the cube's own format.

Expected values are literals or packed here from a fixed formula over (inline, crossline, sample) whose int16 and
int32 cubes hold both extremes; the cube is synthetic (D75). `windows=3` is sent only for an item described as a cube
as published (its context counts `cells`). Multi-piece reads lower `BYTES_MAX` and `HEADERS_PER_ANSWER3` (test only),
on both sides of the mock, so the 35 positions are pieces of four and headers answers of sixteen, the last ones short.
"""
import asyncio
import hashlib
import math
import struct
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from ophiolite import volume_windows as vw
from ophiolite.errors import OphioliteError, VerificationFailed
from test_volume_window import BASE, CROSSLINES, INLINES, POSITIONS, REV, S, Gateway, cells, context, world  # noqa: F401
from test_volume_window_2 import DESCRIBE, unchecked_descriptor  # noqa: F401

WIDTHS = {1: 4, 2: 4, 3: 2, 5: 4}
FORMATS = {1: 'ibm-float32', 2: 'int32', 3: 'int16', 5: 'ieee-float32'}
QUERY = 'inline=100:102&sample=2:4&by=label'


def value(code, i, x, s):
    """The stored value: integers spread over the format's range, the extremes at (0, 0, 0) and (0, 0, 1); floats are
    halves (exact in IBM and IEEE single)."""
    if code in (1, 5): return 0.5 * (i * 77 + x * 11 + s) - 7.0
    bits = 16 if code == 3 else 32
    if (i, x, s) == (0, 0, 0): return -(1 << bits - 1)
    if (i, x, s) == (0, 0, 1): return (1 << bits - 1) - 1
    return (i * 7919 + x * 1543 + s * 31) * (1 if bits == 16 else 65537) % (1 << bits) - (1 << bits - 1)


def ibm(v):
    """An IBM single word, by hand (sign, base-16 exponent biased by 64, 24-bit fraction)."""
    if v == 0: return 0
    sign, a, e = (0x80000000 if v < 0 else 0), abs(v), 64
    while a >= 1: a /= 16; e += 1
    while a < 1 / 16: a *= 16; e -= 1
    return sign | e << 24 | int(a * (1 << 24))


def pack(code, values):
    if code == 1: return struct.pack('>%dI' % len(values), *[ibm(v) for v in values])
    return struct.pack('>%d%s' % (len(values), {2: 'i', 3: 'h', 5: 'f'}[code]), *values)


def published_context(code):
    return dict(context(code=code), cells=35, absent=0)


def published_original(code):
    """A synthetic SEG-Y original of the cube as published (regular order), every free byte a sentinel."""
    head = bytearray((o * 7) & 0xFF for o in range(3600))
    struct.pack_into('>H', head, 3216, 2500); struct.pack_into('>H', head, 3220, S); struct.pack_into('>h', head, 3224, code)
    struct.pack_into('>H', head, 3500, 0x0100); struct.pack_into('>h', head, 3502, 1); struct.pack_into('>h', head, 3504, 0)
    out, where = bytearray(head), {}
    for t, (i, x) in enumerate([(i, x) for i in range(5) for x in range(7)]):
        h = bytearray((o * 7 + t + 1) & 0xFF for o in range(240))
        struct.pack_into('>h', h, 70, -100); struct.pack_into('>h', h, 108, 12); struct.pack_into('>H', h, 114, S); struct.pack_into('>H', h, 116, 2500)
        struct.pack_into('>i', h, 180, 50000000 + i * 2500); struct.pack_into('>i', h, 184, 580000000 + x * 2500)
        struct.pack_into('>i', h, 188, INLINES[i]); struct.pack_into('>i', h, 192, CROSSLINES[x])
        out += h + pack(code, [value(code, i, x, s) for s in range(S)])
        where[(i, x)] = t
    return bytes(out), where


def document3(query, ctx):
    """The `/3` document the gateway states (D-M, D-H3), from the SDK's own resolution of the request."""
    code = ctx['format_code']
    selection, axes = vw.resolve(vw.WindowDescription('cube', REV, 'volume', ctx), query)
    shape = [a['count'] for a in axes]
    width, positions = WIDTHS[code], math.prod(shape[:-1])
    per = 8 * vw.BYTES_MAX // (8 * shape[-1] * width + 1)
    full, rest = divmod(positions, per)
    return {'schema': 'ophiolite.volume-window/3', 'asset_id': 'cube', 'revision': REV, 'source_sha256': REV,
            'interpretation': {'reader': 'asset_connectors.typed_reader/1', 'mapping': 'seismic-volume/3', 'parsing_policy': 'typed-strict/1', 'null_policy': 'none'},
            'window_id': hashlib.sha256(vw.canonical('cube', REV, 'volume', axes, code, per, 'ophiolite.volume-window/3')).hexdigest(),
            'geometry': 'volume', 'selection': selection, 'axes': axes, 'shape': shape,
            'samples': {'format': FORMATS[code], 'format_code': code, 'byte_order': 'big', 'width': width},
            'absent': {'count': 0, 'encoding': 'bitmap-msb', 'sha256': hashlib.sha256(b'\x00' * -(-positions // 8)).hexdigest()},
            'headers': {'count': -(-positions // vw.HEADERS_PER_ANSWER3), 'traces_per_answer': vw.HEADERS_PER_ANSWER3},
            'bytes': full * -(-per // 8) + -(-rest // 8) + positions * shape[-1] * width,
            'pieces': {'count': -(-positions // per), 'traces_per_piece': per, 'bytes_max': vw.BYTES_MAX},
            'verification': {'client': ['identity', 'axes', 'shape', 'piece-identity', 'piece-digest', 'completeness', 'mask'],
                             'trusted': ['chunk-digests-at-read', 'trace-positions']}}


class PublishedGateway(Gateway):
    """The mock window routes over a cube as published: `/3` only when asked windows=3, else 422; `urls` holds every
    request's path and query; `document_change(d)` changes the document it states."""
    def __init__(self, code):
        raw, where = published_original(code)
        super().__init__(raw, where, published_context(code))
        self.code, self.trace, self.urls, self.document_change = code, 240 + S * WIDTHS[code], [], None

    def headers_answer(self, document, n, per=None):
        per = vw.HEADERS_PER_ANSWER3
        chosen = cells(document)[n * per:(n + 1) * per]
        body = b'\x00' * -(-len(chosen) // 8) + b''.join(self.raw[3600 + self.where[c] * self.trace:3600 + self.where[c] * self.trace + 240] for c in chosen)
        return body, {'x-ophiolite-piece': '%d/%d' % (n, document['headers']['count'])}

    def piece_answer(self, document, n):
        per, sample, w = document['pieces']['traces_per_piece'], document['axes'][-1], WIDTHS[self.code]
        at = lambda c: 3600 + self.where[c] * self.trace + 240  # noqa: E731
        chosen = cells(document)[n * per:(n + 1) * per]
        body = b'\x00' * -(-len(chosen) // 8) + b''.join(self.raw[at(c) + sample['first'] * w:at(c) + (sample['last'] + 1) * w] for c in chosen)
        return body, {'x-ophiolite-piece': '%d/%d' % (n, document['pieces']['count'])}

    def handler(self, request):
        url = urlsplit(str(request.url))
        self.urls.append(url.path + ('?' + url.query if url.query else ''))
        if not url.path.startswith(BASE): return httpx.Response(404, json={})
        rest = url.path[len(BASE):]
        self.log.append(rest or 'describe')
        if rest == '': return httpx.Response(200, json={'scientific': self.ctx})
        pairs = parse_qsl(url.query)
        if ('windows', '3') not in pairs: return httpx.Response(422, json={'code': 'native-form'})
        document = document3([(k, v) for k, v in pairs if k not in ('window', 'windows')], self.ctx)
        if self.document_change: self.document_change(document)
        if rest == '/volume-windows': return httpx.Response(200, json=document)
        body, headers = self.answer(document, rest)
        status, body, headers = self.tamper.get(rest, lambda s, b, h: (s, b, h))(200, body, headers)
        return httpx.Response(status, content=body, headers=headers)


def rehashed(change):
    """A tamper that changes a body and states its new digest (s0 R1-13: only the check under test can catch it)."""
    def tamper(status, body, headers):
        body = change(bytearray(body))
        return status, bytes(body), {**headers, 'x-content-sha256': hashlib.sha256(bytes(body)).hexdigest()}
    return tamper


def client(handler):
    from ophiolite import Client
    return Client('http://localhost', 'p', None, httpx.Client(transport=httpx.MockTransport(handler)))


def read_sync(handler, **window):
    return client(handler).read_window('cube', REV, **(window or {'inline': '100:102', 'sample': '2:4', 'by': 'label'}))


def read_async(handler, **window):
    from ophiolite.aio import AsyncClient
    async def go():
        c = AsyncClient('http://localhost', 'p', None, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try: return await c.read_window('cube', REV, **(window or {'inline': '100:102', 'sample': '2:4', 'by': 'label'}))
        finally: await c.http.aclose()
    return asyncio.run(go())


def expected(code, inlines, crosslines, samples):
    return [[[value(code, i, x, s) for s in samples] for x in crosslines] for i in inlines]


# --- the document and the requests ---------------------------------------------------------------------------------

def test_a_published_document_is_checked_as_volume_window_3_and_its_partition_is_the_literal():
    """D-M at the production bound: S = 11 int16 samples, 1,516,584 positions a piece; int32, 760,440. Mutations: the
    `/1` partition (RED: 1,525,201); a document whose absent count exceeds its positions (RED: mask)."""
    for code, per in ((3, 1516584), (2, 760440)):
        ctx = published_context(code)
        query = vw.parse_spec('inline=100:102,by=label')  # every one of the 11 samples
        doc = document3(query, ctx)
        assert (vw.published_per(S, WIDTHS[code]), doc['pieces']['traces_per_piece']) == (per, per)
        assert vw.check_document(doc, asset='cube', revision=REV, query=query, description=vw.WindowDescription('cube', REV, 'volume', ctx)) is doc
        broken = dict(doc, absent=dict(doc['absent'], count=15))
        with pytest.raises(VerificationFailed) as no:
            vw.check_document(broken, asset='cube', revision=REV, query=query, description=vw.WindowDescription('cube', REV, 'volume', ctx))
        assert no.value.details['check'] == 'mask'


@pytest.mark.parametrize('read', [read_sync, read_async], ids=['client', 'aio'])
def test_a_cube_as_published_is_asked_windows_3(unchecked_descriptor, read):
    """D-5 requests: the document and every piece carry windows=3 (a float cube's stay as today:
    test_volume_window_2). Mutation: `asked` keyed on format code (RED: no windows=3, 422)."""
    gateway = PublishedGateway(3)
    result = read(gateway.handler)
    document = BASE + '/volume-windows?inline=100%3A102&sample=2%3A4&by=label&windows=3'
    piece = BASE + '/volume-windows/pieces/0?inline=100%3A102&sample=2%3A4&by=label&windows=3&window=' + result.document['window_id']
    assert gateway.urls == [DESCRIBE, document, piece]


# --- values -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('read', [read_sync, read_async], ids=['client', 'aio'])
@pytest.mark.parametrize('code', [3, 2, 1, 5])
def test_each_format_reads_its_literal_values_and_integers_keep_their_codes(unchecked_descriptor, monkeypatch, read, code):
    """Test 1: the whole cube in pieces of four positions; values equal the literals as floats (int32 extremes
    survive), `codes()` the integers, `to_masked()` int16 or int32 with an all-false mask, `to_numpy()` float64.
    Mutations: unsigned decode (RED: -32768); float32 in `to_masked` or `to_numpy` (RED: dtype, 2147483647)."""
    numpy = pytest.importorskip('numpy')
    monkeypatch.setattr(vw, 'BYTES_MAX', 100)  # 8 x 100 // (8 x 11 x 2 + 1) = 4 int16 positions a piece; 2 at width 4
    gateway = PublishedGateway(code)
    result = read(gateway.handler, sample='0:10')
    literal = expected(code, range(5), range(7), range(S))
    assert result.document['pieces']['count'] > 1 and result.values == literal
    masked = result.to_masked()
    assert masked.dtype == {2: numpy.int32, 3: numpy.int16}.get(code, numpy.float64) and not masked.mask.any()
    assert result.to_numpy().dtype == numpy.float64 and result.to_numpy().tolist() == literal
    if code in (2, 3):
        assert result.codes() == literal and masked.tolist() == literal
        assert result.codes()[0][0][:2] == ([-2147483648, 2147483647] if code == 2 else [-32768, 32767])
    else:
        with pytest.raises(ValueError): result.codes()


def test_the_iterator_gives_codes_per_piece(unchecked_descriptor, monkeypatch):
    monkeypatch.setattr(vw, 'BYTES_MAX', 100)
    pieces = list(client(PublishedGateway(3).handler).iter_window('cube', REV, by='ordinal', inline='0', crossline='0:6'))
    assert [p.traces for p in pieces] == [(0, 3), (4, 6)]
    assert pieces[0].codes() == [[value(3, 0, x, s) for s in range(S)] for x in range(4)]


# --- the mask checks ------------------------------------------------------------------------------------------------

ATTACKS = {  # name: (path below the revision, tamper, the check that names it)
    'padding bit set': ('/volume-windows/pieces/8', rehashed(lambda b: b.__setitem__(0, b[0] | 1) or b), 'mask'),
    'mask truncated': ('/volume-windows/pieces/0', rehashed(lambda b: b[:0]), 'completeness'),
    'a bit flipped': ('/volume-windows/pieces/0', rehashed(lambda b: b.__setitem__(0, b[0] | 0x80) or b), 'completeness'),
    'coherently shortened': ('/volume-windows/pieces/0', rehashed(lambda b: bytearray([b[0] | 0x80]) + b[1 + S * 2:]), 'mask'),
    'absent digest changed': (None, None, 'mask'),
}


def attack(gateway, name):
    path, change, _ = ATTACKS[name]
    if path is None: gateway.document_change = lambda d: d['absent'].update(sha256='f' * 64)
    else: gateway.tamper[path] = change


@pytest.mark.parametrize('name', sorted(ATTACKS))
def test_each_mask_attack_fails_its_named_check(unchecked_descriptor, monkeypatch, name):
    """Test 2 (R1-9): each corruption with its digest recomputed; a coherently shortened piece (one bit set, its
    trace's words removed) passes its length and fails only the final mask check, as does a changed `absent.sha256`.
    35 positions in pieces of 4: the last piece holds 3 (5 padding bits). Mutations: each check removed in turn."""
    monkeypatch.setattr(vw, 'BYTES_MAX', 100)
    gateway = PublishedGateway(3)
    attack(gateway, name)
    with pytest.raises(VerificationFailed) as no: read_sync(gateway.handler, sample='0:10')
    assert no.value.details['check'] == ATTACKS[name][2]


def test_the_window_mask_digest_is_one_bit_string_padded_once():
    """D-M: 35 positions in pieces of 4 digest as 5 bytes, not 9 padded piece masks. Mutation: each piece's padded
    mask fed to the digest (RED)."""
    mask = vw.MaskDigest({'absent': {'count': 0, 'sha256': hashlib.sha256(b'\x00' * 5).hexdigest()}})
    for n in [4] * 8 + [3]: mask.add(0, n)
    mask.close()
    ones = vw.MaskDigest({'absent': {'count': 2, 'sha256': hashlib.sha256(bytes([0b10000000, 0, 0, 0, 0b00100000])).hexdigest()}})
    for bits, n in [(0b1000, 4)] + [(0, 4)] * 7 + [(0b001, 3)]: ones.add(bits, n)
    ones.close()


# --- exchange get: the window file, read by segyio ----------------------------------------------------------------

@pytest.mark.parametrize('code', [3, 2, 1, 5])
def test_a_published_window_is_written_in_its_own_format_and_segyio_reads_the_literals(world, monkeypatch, code):
    """Test 4: `window.sgy` in format 3 or 2 (1 or 5 for published float cubes, R1-10), pieces of four and headers
    answers of sixteen positions (both short at the end); segyio 1.9.14 (test only) reads the literals and the
    cropped original headers. Mutations: headers bound at 240 x k (RED: the mask byte over the bound); words at width 4
    for code 3 (RED: values)."""
    segyio = pytest.importorskip('segyio')
    monkeypatch.setattr(vw, 'BYTES_MAX', 100); monkeypatch.setattr(vw, 'HEADERS_PER_ANSWER3', 16)
    make, tmp = world
    gateway = PublishedGateway(code)
    outcome = make(gateway).get('cube', output=tmp / 'out', window='sample=0:3')
    assert outcome.outcome == 'got'
    windows = [u for u in gateway.urls if u.startswith(BASE + '/volume-windows')]
    assert all('windows=3' in u for u in windows) and sum('/headers/' in u for u in windows) == 3
    path = tmp / 'out' / 'window.sgy'
    assert len(path.read_bytes()) == 3600 + 35 * (240 + 4 * WIDTHS[code])
    with segyio.open(str(path), ignore_geometry=True) as f:
        assert int(f.format) == code and f.tracecount == 35 and len(f.samples) == 4
        got = [[float(v) for v in f.trace[k]] for k in range(35)]
        assert got == [[value(code, i, x, s) for s in range(4)] for i in range(5) for x in range(7)]
        heads = [(h[segyio.TraceField.INLINE_3D], h[segyio.TraceField.CROSSLINE_3D], h[segyio.TraceField.TRACE_SAMPLE_COUNT]) for h in f.header]
        assert heads == [(il, xl, 4) for il in INLINES for xl in CROSSLINES]


@pytest.mark.parametrize('name', sorted(ATTACKS))
def test_each_mask_attack_fails_exchange_get_before_the_output_changes(world, monkeypatch, name):
    """R1-9: `SegyWindowWriter` checks pieces itself, so the attacks run through `exchange get --window` too."""
    monkeypatch.setattr(vw, 'BYTES_MAX', 100); monkeypatch.setattr(vw, 'HEADERS_PER_ANSWER3', 16)
    make, tmp = world
    gateway = PublishedGateway(3)
    attack(gateway, name)
    with pytest.raises(OphioliteError):
        make(gateway).get('cube', output=tmp / 'out', window='sample=0:10')
    assert not (tmp / 'out').exists()


@pytest.mark.parametrize('extra,ok', [(0, True), (1, False)], ids=['at-the-bound', 'one-byte-over'])
def test_a_headers_answer_is_bounded_by_its_mask_and_records(world, monkeypatch, extra, ok):
    """R1-4: the headers callback's bound is ceil(k/8) + 240 k from the document's partition: an answer at the bound
    is written, one byte over is refused."""
    monkeypatch.setattr(vw, 'BYTES_MAX', 100); monkeypatch.setattr(vw, 'HEADERS_PER_ANSWER3', 16)
    make, tmp = world
    gateway = PublishedGateway(3)
    gateway.tamper['/volume-windows/headers/2'] = rehashed(lambda b: b + b'\x00' * extra)
    if ok: assert make(gateway).get('cube', output=tmp / 'out', window='sample=0:10').outcome == 'got'
    else:
        with pytest.raises(OphioliteError): make(gateway).get('cube', output=tmp / 'out', window='sample=0:10')
