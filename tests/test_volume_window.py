"""E141 s0 C3: part of a volume in the SDK refuses by name before any request (the syntax half of D98), with the
server's reasons and sentences (literals, the same as the Platform's route tests). E141 s1 C3: Client.read_window and
iter_window read a valid window (tests/gateway/test_volume_window_gateway.py); here a refused window still sends
nothing, IBM and IEEE words decode exactly, and numpy stays optional.

E141 s2 C2 (client half): `exchange get --window` writes a volume window as SEG-Y. Here, on a mock gateway with a request
log over a synthetic original built in the test (the gateway routes and their tests come with C1's held files): the
written file is the original's headers byte for byte but for the three rewritten fields, and the stored words verbatim
(C2 test 2); each refusal comes in its order with its code and literal sentence and asks nothing after (test 3, as far as
it goes without the server); every answer is verified, and a failed get leaves no staging folder, an existing output
folder and the held record unchanged (test 4); the writer crosses answer boundaries of either kind in order (test 5)."""
import json

import pytest

from ophiolite.errors import OphioliteError
from ophiolite.volume_windows import NOT_AVAILABLE, WindowRefused, parse_spec, parse_window

NOTHING = ' Nothing was read.'

SYNTAX = [
    (dict(inline='104:100', by='label'), 'reversed', 'The inline range 104:100 runs backwards: give the first and then the last, both included.' + NOTHING),
    (dict(inline=(104, 100), by='label'), 'reversed', 'The inline range 104:100 runs backwards: give the first and then the last, both included.' + NOTHING),
    (dict(sample='5:3'), 'reversed', 'The sample range 5:3 runs backwards: give the first and then the last, both included.' + NOTHING),
    (dict(inline='100:104'), 'selection-required', 'Say whether inline and crossline are labels or ordinals: add by=label or by=ordinal.' + NOTHING),
    (dict(crossline=300), 'selection-required', 'Say whether inline and crossline are labels or ordinals: add by=label or by=ordinal.' + NOTHING),
    (dict(inline=100, by='sideways'), 'malformed', "by is label or ordinal, not 'sideways'." + NOTHING),
    (dict(inline='100:104:2', by='label'), 'malformed', "The inline range '100:104:2' has a step; decimation is not offered: give first:last, both included." + NOTHING),
    (dict(sample='a:b'), 'malformed', "The sample range 'a:b' is not a number or two numbers joined by a colon (first:last, both included)." + NOTHING),
    (dict(sample=1.5), 'malformed', "The sample range '1.5' is not a number or two numbers joined by a colon (first:last, both included)." + NOTHING),
    (dict(sample=True), 'malformed', "The sample range 'True' is not a number or two numbers joined by a colon (first:last, both included)." + NOTHING),
    (dict(trace='0:4', by='label'), 'line-by-label', 'A 2D line is addressed by trace position in file order, not by trace number: use by=ordinal or leave by out.' + NOTHING),
    (dict(trace=1, inline=100, by='ordinal'), 'unknown-parameter', "A window asks a 2D line by trace or a volume by inline and crossline, not both: leave out 'trace' or 'inline' and 'crossline'." + NOTHING),
]


@pytest.mark.parametrize('ranges,reason,sentence', SYNTAX)
def test_each_syntax_refusal_names_the_servers_reason_and_sentence(ranges, reason, sentence):
    with pytest.raises(WindowRefused) as refused:
        parse_window(**ranges)
    assert (refused.value.code, refused.value.reason, str(refused.value)) == ('window-refused', reason, sentence)
    assert isinstance(refused.value, OphioliteError)


def test_a_valid_window_is_the_query_in_a_fixed_order():
    assert parse_window(sample=(3, 5), by='label', inline=(102, 104), crossline='305:315') == [
        ('inline', '102:104'), ('crossline', '305:315'), ('sample', '3:5'), ('by', 'label')]
    assert parse_window(trace='1:3') == [('trace', '1:3')]
    assert parse_window(sample=7) == [('sample', '7')]
    assert parse_window() == []


def test_the_cli_spec_is_the_same_window():
    assert parse_spec('inline=100:104,crossline=300:310,sample=0:5,by=label') == [
        ('inline', '100:104'), ('crossline', '300:310'), ('sample', '0:5'), ('by', 'label')]
    for spec, reason, sentence in [
            ('inline=100:104', 'selection-required', 'Say whether inline and crossline are labels or ordinals: add by=label or by=ordinal.' + NOTHING),
            ('inline=100,inline=102,by=label', 'malformed', 'The parameter inline is given twice; give each at most once.' + NOTHING),
            ('colour=red', 'unknown-parameter', "A window takes no parameter 'colour': ask with inline, crossline, trace, sample and by." + NOTHING),
            ('inline', 'malformed', "The window 'inline' is not name=value pairs joined by commas, e.g. inline=100:104,by=label." + NOTHING)]:
        with pytest.raises(WindowRefused) as refused:
            parse_spec(spec)
        assert (refused.value.reason, str(refused.value)) == (reason, sentence), spec


def silent(calls):
    """A transport that records and fails any request: a valid window must not reach it."""
    import httpx
    def handler(request):
        calls.append(str(request.url)); raise AssertionError('a window sent a request: %s' % request.url)
    return httpx.MockTransport(handler)


def test_read_window_and_iter_window_refuse_a_bad_window_by_name_and_send_nothing():
    """s1: a valid window is read (tests/gateway/test_volume_window_gateway.py); a refused one still sends nothing."""
    import httpx
    from ophiolite import Client
    calls = []
    client = Client('http://localhost', 'p', None, httpx.Client(transport=silent(calls)))
    for ask in (client.read_window, client.iter_window):
        with pytest.raises(WindowRefused) as refused:
            ask('cube', 'r' * 64, inline='104:100', by='label')
        assert refused.value.reason == 'reversed'
        with pytest.raises(WindowRefused) as refused:
            ask('line', 'r' * 64, trace='0:4', by='label')
        assert refused.value.reason == 'line-by-label'
    assert calls == []


def test_the_async_client_refuses_the_same_and_sends_nothing():
    import asyncio
    import httpx
    from ophiolite.aio import AsyncClient
    calls = []
    async def ask(method, **ranges):
        client = AsyncClient('http://localhost', 'p', None, httpx.AsyncClient(transport=silent(calls)))
        try:
            await getattr(client, method)('line', 'r' * 64, **ranges)
        finally:
            await client.http.aclose()
    for method in ('read_window', 'iter_window'):
        for ranges, reason in ((dict(trace='0:4', by='label'), 'line-by-label'), (dict(inline=100), 'selection-required'), (dict(sample='5:3'), 'reversed')):
            with pytest.raises(WindowRefused) as refused:
                asyncio.run(ask(method, **ranges))
            assert refused.value.reason == reason, (method, ranges)
    assert calls == []


# --- s1: decoding (D-S) ---------------------------------------------------------------------------------------------

IBM_WORDS = [  # (word, exact value): zero, negative zero, unnormalized beside normalized, a negative, the smallest and largest
    (0x00000000, 0.0), (0x80000000, -0.0), (0x41080000, 0.5), (0x40800000, 0.5), (0xC2760000, -118.0),
    (0x00100000, 16.0 ** -65), (0x7FFFFFFF, (1 - 2.0 ** -24) * 16.0 ** 63), (0x3F100000, 0.00390625),
]


def test_ibm_words_decode_to_their_exact_values():
    """Mutation caught: the exponent bias 64 -> 63."""
    import math
    import struct
    from ophiolite.volume_windows import decode
    got = decode(struct.pack('>%dI' % len(IBM_WORDS), *[w for w, _ in IBM_WORDS]), 1)
    assert got == [v for _, v in IBM_WORDS]
    assert [math.copysign(1, v) for v in got[:2]] == [1.0, -1.0]


def test_ieee_words_decode_widened():
    import struct
    from ophiolite.volume_windows import decode
    values = [0.0, -0.0, 1.5, -2.25, 8999999.0, 3.4028234663852886e38]
    assert decode(struct.pack('>6f', *values), 5) == values


def test_numpy_is_imported_only_by_to_numpy():
    import subprocess
    import sys
    probe = 'import sys, ophiolite, ophiolite.volume_windows, ophiolite.client, ophiolite.aio; print("numpy" in sys.modules)'
    assert subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True).stdout.strip() == 'False'


def test_cli_get_window_refuses_a_bad_window_writes_nothing_and_contacts_nothing(tmp_path, monkeypatch, capsys):
    import httpx
    from ophiolite import Client, cli
    calls, opened = [], []
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, httpx.Client(transport=silent(calls))), raising=False)
    monkeypatch.setattr(Client, 'exchange', lambda self, work: opened.append(work) or pytest.fail('the exchange was opened'))
    config = tmp_path / 'configuration.json'
    config.write_text('{"schema": "ophiolite.read-configuration/1", "url": "http://localhost", "project": "p"}')
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice')
    def run(*rest):
        capsys.readouterr()
        try: cli.entrypoint(['get', '--configuration', str(config), '--credentials', str(tmp_path / 'not-saved.json'), '--work', str(tmp_path / 'w'),
                             '--item', 'cube', '--output', str(tmp_path / 'out'), *rest])
        except SystemExit as stop: code = stop.code
        else: code = 0
        out = capsys.readouterr()
        return code, out.out.strip(), out.err.strip()
    assert run('--window', 'inline=100:104') == (1, '', 'Say whether inline and crossline are labels or ordinals: add by=label or by=ordinal.' + NOTHING)
    code, out, err = run('--window', 'sample=5:0', '--json')
    assert (code, err) == (1, '') and json.loads(out)['error']['code'] == 'window-refused'
    assert not (tmp_path / 'out').exists() and not (tmp_path / 'w').exists()
    assert (calls, opened) == ([], [])


def test_the_not_available_sentence_is_the_sdks_own():
    assert NOT_AVAILABLE == ('Reading part of a volume is not available in this SDK yet. Nothing was sent. '
                             'Read one slice (Client.read_slice) or the whole original (Client.download_original).')
    with pytest.raises(ValueError):
        WindowRefused('sideways', 'x')


# --- s2: a window comes to disk (C2 tests 2-5 on a mock gateway; the gateway versions come with C1's routes) -----------

import hashlib  # noqa: E402
import math  # noqa: E402
import struct  # noqa: E402
from urllib.parse import parse_qsl, urlsplit  # noqa: E402

from ophiolite import volume_windows as vw  # noqa: E402

REV = 'a' * 64
INLINES, CROSSLINES, S = [100, 102, 104, 106, 108], [300, 305, 310, 315, 320, 325, 330], 11
TRACE = 240 + S * 4
POSITIONS = 'inline=189,crossline=193,cdp_x=181,cdp_y=185'
SHUFFLED = [(i, x) for x in (3, 0, 6, 1, 5, 2, 4) for i in (4, 1, 3, 0, 2)]  # file order: crossline-major, both permuted
BLOCK_EXACT = 'inline=102:104,crossline=305:315,sample=2:4,by=label'  # starts at 12 + 2 x 2.5 = 17 ms
BASE = '/api/v1/projects/p/scientific-assets/cube/revisions/' + REV


def context(domain='time', first=12.0, code=1, kind='seismic-volume'):
    return {'type': kind, 'inline': {'first': 100, 'step': 2, 'count': 5}, 'crossline': {'first': 300, 'step': 5, 'count': 7}, 'samples': S,
            'sample_interval': 2.5, 'first_sample': first, 'sample_unit': 'ms', 'z_domain': domain, 'format_code': code}


def word(i, x, s):
    """A stored word, never decoded: distinct per (inline, crossline, sample), not a normalized IBM or IEEE value."""
    return 0x00800000 | (i << 16) | (x << 8) | s


def original(order=None, code=1, revision=0x0100):
    """A synthetic SEG-Y original: every byte the fields leave free holds a sentinel ((offset x 7 + trace) & 0xFF, R1-12).
    Returns (bytes, {(inline ordinal, crossline ordinal): file ordinal})."""
    head = bytearray((o * 7) & 0xFF for o in range(3600))
    struct.pack_into('>H', head, 3216, 2500); struct.pack_into('>H', head, 3220, S); struct.pack_into('>h', head, 3224, code)
    struct.pack_into('>H', head, 3500, revision); struct.pack_into('>h', head, 3502, 1); struct.pack_into('>h', head, 3504, 0)
    out, where = bytearray(head), {}
    for t, (i, x) in enumerate([(i, x) for i in range(5) for x in range(7)] if order is None else order):
        h = bytearray((o * 7 + t + 1) & 0xFF for o in range(240))
        struct.pack_into('>h', h, 70, -100); struct.pack_into('>h', h, 108, 12); struct.pack_into('>H', h, 114, S); struct.pack_into('>H', h, 116, 2500)
        struct.pack_into('>i', h, 180, 50000000 + i * 2500); struct.pack_into('>i', h, 184, 580000000 + x * 2500)
        struct.pack_into('>i', h, 188, INLINES[i]); struct.pack_into('>i', h, 192, CROSSLINES[x])
        out += h + struct.pack('>%dI' % S, *[word(i, x, s) for s in range(S)])
        where[(i, x)] = t
    return bytes(out), where


def document_for(query, ctx):
    """The window document the gateway states (s0/s1 rules), from the SDK's own resolution of the request."""
    selection, axes = vw.resolve(vw.WindowDescription('cube', REV, 'volume', ctx), query)
    shape = [a['count'] for a in axes]
    per = vw.BYTES_MAX // (shape[-1] * 4)
    traces = math.prod(shape[:-1])
    return {'schema': vw.WINDOW, 'asset_id': 'cube', 'revision': REV, 'source_sha256': REV,
            'interpretation': {'reader': 'asset_connectors.typed_reader/1', 'mapping': 'seismic-volume/1', 'parsing_policy': 'typed-strict/1', 'null_policy': 'none'},
            'window_id': hashlib.sha256(vw.canonical('cube', REV, 'volume', axes, ctx['format_code'], per)).hexdigest(),
            'geometry': 'volume', 'selection': selection, 'axes': axes, 'shape': shape,
            'samples': {'format': vw.FORMATS[ctx['format_code']], 'format_code': ctx['format_code'], 'byte_order': 'big', 'width': 4},
            'bytes': math.prod(shape) * 4, 'pieces': {'count': -(-traces // per), 'traces_per_piece': per, 'bytes_max': vw.BYTES_MAX},
            'verification': {'client': vw.CLIENT_CHECKS, 'trusted': vw.TRUSTED}}


def cells(document):
    inline, crossline = document['axes'][0], document['axes'][1]
    return [(inline['first'] + k // crossline['count'], crossline['first'] + k % crossline['count']) for k in range(inline['count'] * crossline['count'])]


class Gateway:
    """A mock of the window routes over one original; `log` holds every request path below the revision, in order;
    `tamper[path](status, body, headers)` changes one answer."""
    def __init__(self, raw, where, ctx, positions=POSITIONS):
        self.raw, self.where, self.ctx, self.positions = raw, where, ctx, positions
        self.log, self.tamper = [], {}

    def headers_answer(self, document, n, per=None):
        per = per or vw.HEADERS_PER_ANSWER
        traces = cells(document)
        body = b''.join(self.raw[3600 + self.where[c] * TRACE:3600 + self.where[c] * TRACE + 240] for c in traces[n * per:(n + 1) * per])
        return body, {'x-ophiolite-piece': '%d/%d' % (n, -(-len(traces) // per))}

    def piece_answer(self, document, n):
        per, sample = document['pieces']['traces_per_piece'], document['axes'][-1]
        body = b''.join(self.raw[3600 + self.where[c] * TRACE + 240 + sample['first'] * 4:3600 + self.where[c] * TRACE + 240 + (sample['last'] + 1) * 4]
                        for c in cells(document)[n * per:(n + 1) * per])
        return body, {'x-ophiolite-piece': '%d/%d' % (n, document['pieces']['count'])}

    def answer(self, document, rest):
        if rest == '/volume-windows/file-header': body, extra = self.raw[:3600], {'x-ophiolite-header-positions': self.positions}
        elif rest.startswith('/volume-windows/headers/'): body, extra = self.headers_answer(document, int(rest.rsplit('/', 1)[1]))
        else: body, extra = self.piece_answer(document, int(rest.rsplit('/', 1)[1]))
        return body, {'x-ophiolite-window': document['window_id'], 'x-ophiolite-revision': REV, 'x-content-sha256': hashlib.sha256(body).hexdigest(), **extra}

    def handler(self, request):
        import httpx
        url = urlsplit(str(request.url))
        if not url.path.startswith(BASE): return httpx.Response(404, json={})
        rest = url.path[len(BASE):]
        self.log.append(rest or 'describe')
        if rest == '': return httpx.Response(200, json={'scientific': self.ctx})
        document = document_for([(k, v) for k, v in parse_qsl(url.query) if k != 'window'], self.ctx)
        if rest == '/volume-windows': return httpx.Response(200, json=document)
        body, headers = self.answer(document, rest)
        status, body, headers = self.tamper.get(rest, lambda s, b, h: (s, b, h))(200, body, headers)
        return httpx.Response(status, content=body, headers=headers)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """(make(gateway) -> Exchange, tmp_path): Exchange over a Client whose HTTP is the mock gateway."""
    import httpx
    from ophiolite import Client, _core
    from ophiolite.exchange import ClientTransport, Exchange
    monkeypatch.setattr(_core, 'verify_typed_descriptor', lambda value, project, asset, revision: value)  # the descriptor is not under test
    monkeypatch.setattr(ClientTransport, 'inventory', lambda self: [{'asset_id': 'cube', 'kind': 'uploaded', 'authority': 'project', 'revision': REV, 'name': 'Cube'}])
    monkeypatch.setattr(ClientTransport, 'history', lambda self, item: [])
    def make(gateway):
        return Exchange(ClientTransport(Client('http://localhost', 'p', None, httpx.Client(transport=httpx.MockTransport(gateway.handler)))), tmp_path / 'work')
    return make, tmp_path


def expected_file(raw, where, document, delay):
    """The window file the writer must produce: the original's headers, only 3221-3222, 109-110 and 115-116 rewritten
    (to literals the caller states), and the stored words verbatim."""
    count, sample = document['shape'][-1], document['axes'][-1]
    head = bytearray(raw[:3600]); struct.pack_into('>H', head, 3220, count)
    out = bytearray(head)
    for c in cells(document):
        at = 3600 + where[c] * TRACE
        h = bytearray(raw[at:at + 240]); struct.pack_into('>H', h, 114, count)
        if delay is not None: struct.pack_into('>h', h, 108, delay)
        out += h + raw[at + 240 + sample['first'] * 4:at + 240 + (sample['last'] + 1) * 4]
    return bytes(out)


VERBATIM = [('ibm shuffled', 1, SHUFFLED), ('ieee shuffled', 5, SHUFFLED), ('ibm regular', 1, None), ('ieee regular', 5, None)]


@pytest.mark.parametrize('name,code,order', VERBATIM, ids=[v[0] for v in VERBATIM])
def test_the_window_file_is_the_originals_headers_and_words_verbatim(world, name, code, order):
    """C2 test 2: block-exact (start 17 ms), corner and whole; masked at the three rewritten fields only."""
    make, tmp = world
    raw, where = original(order, code)
    gateway = Gateway(raw, where, context(code=code))
    exchange = make(gateway)
    for window, delay, count, traces in ((BLOCK_EXACT, 17, 3, 6), ('inline=108,crossline=325:330,sample=8:10,by=label', 32, 3, 2), ('sample=0:10', None, 11, 35)):
        out = tmp / ('out-' + window.replace(',', '_').replace(':', '-').replace('=', ''))
        outcome = exchange.get('cube', output=out, window=window)
        assert outcome.outcome == 'got'
        document = document_for(vw.parse_spec(window), context(code=code))
        data = (out / 'window.sgy').read_bytes()
        assert len(data) == 3600 + traces * (240 + count * 4)
        assert data == expected_file(raw, where, document, delay)
        assert struct.unpack_from('>H', data, 3220)[0] == count and struct.unpack_from('>H', data, 3500)[0] == 0x0100
        for k in range(traces):
            at = 3600 + k * (240 + count * 4)
            assert struct.unpack_from('>hH', data, at + 108)[0] == (12 if delay is None else delay)
            assert struct.unpack_from('>H', data, at + 114)[0] == count
        record = json.loads((out / 'window.json').read_text())
        assert record['document'] == document and record['window_digest'] == hashlib.sha256(
            b''.join(gateway.piece_answer(document, n)[0] for n in range(document['pieces']['count']))).hexdigest()
        assert record['headers_digest'] == hashlib.sha256(gateway.headers_answer(document, 0)[0]).hexdigest()
        assert json.loads((out / 'descriptor.json').read_text()) == {'scientific': context(code=code)}
        assert sorted(p.name for p in out.iterdir()) == ['descriptor.json', 'window.json', 'window.sgy']
        held = json.loads((tmp / 'work' / 'held.json').read_text())['items']['cube']
        assert held['output']['selection'] == {'window': window}
    assert not any(p.name.startswith('.out') for p in tmp.iterdir())
    assert all(not path.startswith('/representations') and 'artifact' not in path for path in gateway.log)  # no original asked


def test_the_requests_of_a_window_get_in_order(world):
    make, tmp = world
    raw, where = original(SHUFFLED)
    gateway = Gateway(raw, where, context())
    make(gateway).get('cube', output=tmp / 'out', window=BLOCK_EXACT)
    assert gateway.log == ['describe', '/volume-windows', '/volume-windows/file-header', '/volume-windows/headers/0', '/volume-windows/pieces/0']


LINE = 'A 2D line has no window file; get writes its original.'
REFUSALS = [  # (name, gateway arguments, window, code, sentence, the requests made)
    ('block', {}, 'inline=102:104,crossline=305:315,sample=3:5,by=label', 'inexact-crop',
     'This window starts at 19.5 ms; this file format holds whole milliseconds. Start at sample 2 or 4.', ['describe', '/volume-windows']),
    ('depth', {'ctx': context(domain='depth')}, 'sample=1:3', 'inexact-crop',
     'This window starts at sample 1 of a depth volume; this file format cannot state a cropped depth start. Start at sample 0.', ['describe', '/volume-windows']),
    ('int16', {'ctx': context(first=32760.0)}, 'sample=4:5', 'inexact-crop',
     'This window starts at 32770 ms; this file format holds starts from -32,768 to 32,767 ms. Start at an earlier sample.', ['describe', '/volume-windows']),
    ('revision 2', {'revision': 0x0200}, BLOCK_EXACT, 'revision-unsupported',
     "This volume's file states SEG-Y revision 2.0; a window file is written from revision 0 or 1 files only.",
     ['describe', '/volume-windows', '/volume-windows/file-header']),
    ('cdp_x at 109', {'positions': 'inline=189,crossline=193,cdp_x=109,cdp_y=185'}, BLOCK_EXACT, 'header-positions-overlap',
     'This volume keeps its x coordinate where a window file states its start time or sample count, so its window cannot be written as a file.',
     ['describe', '/volume-windows', '/volume-windows/file-header']),
    ('crossline at 113', {'positions': 'inline=189,crossline=113,cdp_x=181,cdp_y=185'}, BLOCK_EXACT, 'header-positions-overlap',
     'This volume keeps its crossline number where a window file states its start time or sample count, so its window cannot be written as a file.',
     ['describe', '/volume-windows', '/volume-windows/file-header']),
    ('line window', {}, 'trace=0:4', 'window-volume-only', LINE, []),
    ('line item', {'ctx': context(kind='seismic-line')}, 'sample=0:2', 'window-volume-only', LINE, ['describe']),
    ('a well log', {'ctx': {'type': None}}, 'sample=0:2', 'window-volume-only',
     'Only a seismic volume is written as a window file; get this item without --window.', ['describe']),
]


def refusing_gateway(args):
    raw, where = original(SHUFFLED, revision=args.get('revision', 0x0100))
    return Gateway(raw, where, args.get('ctx', context()), args.get('positions', POSITIONS))


@pytest.mark.parametrize('name,args,window,code,sentence,asked', REFUSALS, ids=[r[0] for r in REFUSALS])
def test_each_refusal_comes_in_its_order_and_asks_nothing_after(world, name, args, window, code, sentence, asked):
    """C2 test 3 (R1-5, R1-13), through Exchange.get: the code, the literal sentence, and the requests made."""
    from ophiolite.exchange import CannotReadHere
    make, tmp = world
    gateway = refusing_gateway(args)
    with pytest.raises(CannotReadHere) as refused:
        make(gateway).get('cube', output=tmp / 'out', window=window)
    assert (refused.value.technical['reason'], str(refused.value)) == (code, sentence)
    assert gateway.log == asked
    assert not any(p.name.startswith(('out', '.out')) for p in tmp.iterdir())


def test_the_cli_writes_a_window_and_prints_a_refusal_with_its_code(world, monkeypatch, capsys):
    import httpx
    from ophiolite import Client, cli
    make, tmp = world
    raw, where = original(SHUFFLED)
    gateway = Gateway(raw, where, context())
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, httpx.Client(transport=httpx.MockTransport(gateway.handler))), raising=False)
    config = tmp / 'configuration.json'
    config.write_text('{"schema": "ophiolite.read-configuration/1", "url": "http://localhost", "project": "p"}')
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice')
    def run(output, window):
        capsys.readouterr()
        try: cli.entrypoint(['get', '--configuration', str(config), '--credentials', str(tmp / 'not-saved.json'), '--work', str(tmp / 'w'),
                             '--item', 'cube', '--output', str(output), '--window', window])
        except SystemExit as stop: code = stop.code
        else: code = 0
        captured = capsys.readouterr()
        return code, captured.err.strip()
    assert run(tmp / 'got', BLOCK_EXACT) == (0, '')
    assert (tmp / 'got' / 'window.sgy').read_bytes() == expected_file(raw, where, document_for(vw.parse_spec(BLOCK_EXACT), context()), 17)
    assert run(tmp / 'refused', 'inline=102:104,crossline=305:315,sample=3:5,by=label') == (
        1, 'This window starts at 19.5 ms; this file format holds whole milliseconds. Start at sample 2 or 4. (inexact-crop)')
    assert not (tmp / 'refused').exists()


def test_a_volume_without_a_window_names_the_window(world):
    from types import SimpleNamespace
    from ophiolite.exchange import CannotReadHere
    make, tmp = world
    exchange = make(Gateway(*original(), context()))
    exchange.transport.client.read_data = lambda asset, revision: SimpleNamespace(type='seismic-volume', _wire_descriptor={})
    with pytest.raises(CannotReadHere) as refused:
        exchange.get('cube', output=tmp / 'out')
    assert (refused.value.technical['reason'], str(refused.value)) == (
        'volume-needs-window', 'Give a window, for example --window inline=100:104,by=label, or call Client.download_original for the whole file.')


def test_a_window_needs_an_output_folder_and_an_s1_refusal_keeps_its_reason(world):
    from ophiolite.exchange import CannotReadHere
    make, tmp = world
    gateway = Gateway(*original(), context())
    with pytest.raises(CannotReadHere) as refused:
        make(gateway).get('cube', window=BLOCK_EXACT)
    assert refused.value.technical['reason'] == 'window-needs-output' and gateway.log == []
    with pytest.raises(CannotReadHere) as refused:
        make(gateway).get('cube', output=tmp / 'out', window={'sample': '5:3'})
    assert (refused.value.technical['reason'], str(refused.value)) == ('reversed', 'The sample range 5:3 runs backwards: give the first and then the last, both included.' + NOTHING)


def replaced(**changes):
    def apply(status, body, headers):
        headers = dict(headers)
        for key, value in changes.items():
            if key == 'status': status = value
            elif key == 'body': body = value(body); headers['x-content-sha256'] = hashlib.sha256(body).hexdigest()
            elif key == 'raw': body = value(body)  # the digest left stale
            else: headers[key.replace('_', '-')] = value
        return status, body, headers
    return apply


def swapped(body):
    return body[240:480] + body[:240] + body[480:]


TAMPER = {  # (path, change): each must fail the get
    'headers missing': ('/volume-windows/headers/1', replaced(status=404)),
    'headers repeated': ('/volume-windows/headers/1', 'repeat'),
    'another window': ('/volume-windows/headers/1', replaced(x_ophiolite_window='b' * 64)),
    'another revision': ('/volume-windows/headers/1', replaced(x_ophiolite_revision='c' * 64)),
    'another index': ('/volume-windows/headers/1', replaced(x_ophiolite_piece='2/3')),
    'no index': ('/volume-windows/headers/1', replaced(x_ophiolite_piece='')),
    'stale digest': ('/volume-windows/headers/1', replaced(raw=lambda b: b[:-1] + bytes([b[-1] ^ 1]))),
    'truncated': ('/volume-windows/headers/1', replaced(body=lambda b: b[:-240])),
    'oversized': ('/volume-windows/headers/1', replaced(body=lambda b: b + b[:240])),
    'two headers swapped': ('/volume-windows/headers/1', replaced(body=swapped)),
    'file header changed': ('/volume-windows/file-header', replaced(raw=lambda b: b[:10] + bytes([b[10] ^ 1]) + b[11:])),
    'file header truncated': ('/volume-windows/file-header', replaced(body=lambda b: b[:-1])),
    'file header positions missing': ('/volume-windows/file-header', replaced(x_ophiolite_header_positions='')),
    'piece stale digest': ('/volume-windows/pieces/0', replaced(raw=lambda b: b[:-1] + bytes([b[-1] ^ 1]))),
}


@pytest.mark.parametrize('case', sorted(TAMPER))
def test_every_answer_is_verified_and_a_failed_get_changes_nothing(world, monkeypatch, case):
    """C2 test 4 (R1-14): headers H = 16 (test only), so the whole volume (35 traces) is three headers answers."""
    from ophiolite.errors import OphioliteError
    from ophiolite.exchange import folder_digest
    monkeypatch.setattr(vw, 'HEADERS_PER_ANSWER', 16)
    make, tmp = world
    raw, where = original(SHUFFLED)
    gateway = Gateway(raw, where, context())
    exchange = make(gateway)
    exchange.get('cube', output=tmp / 'out', window=BLOCK_EXACT)
    before, held = folder_digest(tmp / 'out'), (tmp / 'work' / 'held.json').read_bytes()
    path, change = TAMPER[case]
    if change == 'repeat':
        document = document_for(vw.parse_spec('sample=0:10'), context())
        first = gateway.answer(document, '/volume-windows/headers/0')
        change = lambda status, body, headers: (status, first[0], first[1])
    gateway.tamper[path] = change
    with pytest.raises(OphioliteError):
        exchange.get('cube', output=tmp / 'out', window='sample=0:10')
    assert folder_digest(tmp / 'out') == before and (tmp / 'work' / 'held.json').read_bytes() == held
    assert sorted(p.name for p in tmp.iterdir()) == ['out', 'work']


def run_writer(tmp_path, per_headers, per_piece, window='sample=0:10'):
    tmp_path.mkdir(parents=True)
    raw, where = original(SHUFFLED)
    gateway = Gateway(raw, where, context())
    document = document_for(vw.parse_spec(window), context())
    traces = math.prod(document['shape'][:-1])
    document['pieces'] = {**document['pieces'], 'traces_per_piece': per_piece, 'count': -(-traces // per_piece)}  # test-only samples bound
    def ask(kind):
        def answer(n):
            body, extra = gateway.headers_answer(document, n, per_headers) if kind == 'headers' else gateway.piece_answer(document, n)
            return body, {'x-ophiolite-window': document['window_id'], 'x-ophiolite-revision': REV, 'x-content-sha256': hashlib.sha256(body).hexdigest(), **extra}
        return answer
    file_header, _ = gateway.answer(document, '/volume-windows/file-header')
    writer = vw.SegyWindowWriter(tmp_path / 'staging', document, file_header, vw.parse_positions(POSITIONS), None, headers_per=per_headers)
    written = writer.write(ask('headers'), ask('pieces'))
    assert (tmp_path / 'staging' / 'window.sgy').read_bytes() == expected_file(raw, where, document, None)
    return writer.asked, written


def test_the_writer_crosses_boundaries_of_either_kind_in_order(tmp_path):
    """C2 test 5 (R1-10): test-only H and samples bound over the 35-trace volume."""
    asked, written = run_writer(tmp_path / 'a', per_headers=4, per_piece=6)  # headers advance first; both finals short (3 and 5)
    assert asked[:8] == [('headers', 0), ('pieces', 0), ('headers', 1), ('pieces', 1), ('headers', 2), ('headers', 3), ('pieces', 2), ('headers', 4)]
    assert asked == [(kind, n) for _, rank, kind, n in sorted([(n * 4, 0, 'headers', n) for n in range(9)] + [(n * 6, 1, 'pieces', n) for n in range(6)])]
    assert (written['traces'], written['bytes']) == (35, 3600 + 35 * 284)
    asked, _ = run_writer(tmp_path / 'b', per_headers=6, per_piece=4)  # samples advance first
    assert asked[:5] == [('headers', 0), ('pieces', 0), ('pieces', 1), ('headers', 1), ('pieces', 2)]
    assert len(asked) == 6 + 9
    asked, written = run_writer(tmp_path / 'c', per_headers=35, per_piece=35)
    assert asked == [('headers', 0), ('pieces', 0)] and written['bytes'] == 13540


def test_exact_crop_on_metadata_alone():
    document = document_for(vw.parse_spec('sample=0:2'), context())
    assert vw.exact_crop(document) is None
    assert vw.exact_crop(document_for(vw.parse_spec('sample=2:4'), context())) == 17
    assert vw.exact_crop(document_for(vw.parse_spec('sample=4:5'), context(first=-30.0))) == -20
    with pytest.raises(Exception) as refused: vw.exact_crop(document_for(vw.parse_spec('sample=9:10'), context()), S)
    assert str(refused.value) == 'This window starts at 34.5 ms; this file format holds whole milliseconds. Start at sample 8 or 10.'
    with pytest.raises(Exception) as refused: vw.exact_crop(document_for(vw.parse_spec('sample=1:3'), context(domain='unknown')))
    assert refused.value.technical == {'reason': 'inexact-crop', 'field': 'bytes 109-110', 'domain': 'unknown'}
