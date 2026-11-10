"""E141 s2 C2 against the real gateway routes: `get --window` writes part of a stored volume as SEG-Y, and segyio
(the external client, test-only) reads it back as the literals of the synthetic cube (D75: built at test time, not
observed data). The cube and its windows are the s0/s1 fixture's (tests/fixtures/volume_window)."""
import json
import struct
from pathlib import Path

import pytest
import segyio  # test-only, unguarded: the SDK gateway lane installs it from [dev]; never a runtime dependency
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite.exchange import CannotReadHere

from project_gateway.tests import test_volume_window_contract as contract
from project_gateway.tests.test_volume_window_contract import cube_bytes, line_bytes, CUBE

FIXTURES = Path(contract.__file__).parent / 'fixtures/volume_window'
JOURNEYS = json.loads((FIXTURES / 'journeys.json').read_text())
SLICE_2 = [r for r in JOURNEYS['journeys'] if r['slice'] == 2]
UPLOAD = dict(declared={'crs': 'EPSG:23031', 'z_domain': 'time'}, attribution='Synthetic', audience=[], rights_confirmed=True)
TRACE = 240 + CUBE['samples'] * 4
SHUFFLED = [x * 5 + i for x in (3, 0, 6, 1, 5, 2, 4) for i in (4, 1, 3, 0, 2)]  # file order of C-order trace t: crossline-major, both permuted
STARTS = {'block-exact': 17.0, 'corner': 37.0, 'whole': 12.0}  # first sample in ms: 12 + 2.5 x the first sample position
CODES = {'ibm': 1, 'ieee': 5}


def window(name):
    """(spec, inline ordinals, crossline ordinals, sample positions) of a journeys.json window."""
    w = JOURNEYS['windows'][name]
    at = w['at'] if w['at'] != 'all' else {'inline': list(range(5)), 'crossline': list(range(7)), 'sample': list(range(11))}
    return ','.join('%s=%s' % (k, v) for k, v in w['query']) or 'sample=0:10', at['inline'], at['crossline'], at['sample']


def shuffled(raw):
    """The same cube with its traces stored in another order (the reader indexes by the header labels)."""
    traces = [raw[3600 + t * TRACE:3600 + (t + 1) * TRACE] for t in range(len(SHUFFLED))]
    return raw[:3600] + b''.join(traces[t] for t in SHUFFLED)


@pytest.fixture
def world(web, tmp_path):
    """(land(kind, order) -> info, alice, requests): the cube uploaded through the gateway; `requests` logs every path."""
    alice, requests = client(web, 'alice', 'delegate'), []
    web.c.event_hooks['request'].append(lambda request: requests.append(request.url.path))

    def land(kind, order='regular'):
        raw = cube_bytes(kind) if order == 'regular' else shuffled(cube_bytes(kind))
        return alice.upload_data(raw, profile='segy/1', name='Cube %s %s' % (kind, order), filename='cube-%s-%s.sgy' % (kind, order), **UPLOAD)
    return land, alice, requests, tmp_path


# --- 1. segyio reads the literals --------------------------------------------------------------------------------

CASES = [(row['id'], name, kind, order)
         for row in SLICE_2
         for name in row['windows']
         for kind in CODES for order in ('regular', 'shuffled')]


@pytest.mark.parametrize('row,name,kind,order', CASES, ids=['%s-%s-%s-%s' % c for c in CASES])
def test_each_slice_2_journey_writes_a_file_segyio_reads_as_the_literals(world, row, name, kind, order):
    """C2 test 1 (both slice-2 rows: the exchange writes it, segyio reads it). Mutations caught: the delay left
    unrewritten (f.samples), the binary sample count left (open fails or wrong shape), IBM words re-encoded as IEEE
    (f.format, values and the window digest), headers taken in file order (labels)."""
    land, alice, requests, tmp = world
    spec, inlines, crosslines, samples = window(name)
    info = land(kind, order)
    requests.clear()
    got = alice.exchange(tmp / 'work').get(info.asset_id, output=tmp / 'out', window=spec)
    assert got.outcome == 'got'
    assert json.loads((tmp / 'out' / 'window.json').read_text())['window_digest'] == JOURNEYS['windows'][name]['wire_sha256'][kind]
    with segyio.open(str(tmp / 'out' / 'window.sgy'), iline=189, xline=193, strict=len(inlines) * len(crosslines) > 1) as f:
        assert int(f.format) == CODES[kind]
        assert list(f.samples) == [STARTS[name] + 2.5 * k for k in range(len(samples))]
        assert f.tracecount == len(inlines) * len(crosslines)
        for t in range(f.tracecount):
            i, x = inlines[t // len(crosslines)], crosslines[t % len(crosslines)]
            h = f.header[t]
            assert (h[segyio.TraceField.INLINE_3D], h[segyio.TraceField.CROSSLINE_3D]) == (CUBE['inlines'][i], CUBE['crosslines'][x])
            assert (h[segyio.TraceField.CDP_X], h[segyio.TraceField.CDP_Y], h[segyio.TraceField.SourceGroupScalar]) == (
                50000000 + i * 2500, 580000000 + x * 2500, -100)
            assert h[segyio.TraceField.TRACE_SAMPLE_COUNT] == len(samples)
            assert [float(v) for v in f.trace[t]] == [CUBE['values'][i][x][s] for s in samples]
    assert sorted(p.name for p in (tmp / 'out').iterdir()) == ['descriptor.json', 'window.json', 'window.sgy']
    assert not [p for p in requests if p.endswith('/representations/artifact')]  # the original is never asked for (s1 C4 trap)
    asked = [p.rsplit('/volume-windows', 1)[1] for p in requests if '/volume-windows' in p]
    assert asked == ['', '/file-header', '/headers/0', '/pieces/0']


def test_the_window_file_keeps_the_originals_headers_but_three_fields(world):
    """C2 test 2 over the gateway: every header byte but 3221-3222 (binary count), 109-110 (delay) and 115-116 (trace
    count) equals the original's; the samples are the stored words. Mutation caught: words decoded and re-encoded."""
    land, alice, requests, tmp = world
    raw = shuffled(cube_bytes('ibm'))
    info = land('ibm', 'shuffled')
    alice.exchange(tmp / 'work').get(info.asset_id, output=tmp / 'out', window=window('block-exact')[0])
    data = (tmp / 'out' / 'window.sgy').read_bytes()
    assert data[:3220] == raw[:3220] and data[3222:3600] == raw[3222:3600] and struct.unpack_from('>H', data, 3220)[0] == 3
    size = 240 + 3 * 4
    for t, (i, x) in enumerate((i, x) for i in (1, 2) for x in (1, 2, 3)):
        at = 3600 + SHUFFLED.index(i * 7 + x) * TRACE
        header, words = data[3600 + t * size:3600 + t * size + 240], data[3600 + t * size + 240:3600 + (t + 1) * size]
        assert header[:108] == raw[at:at + 108] and header[110:114] == raw[at + 110:at + 114] and header[116:] == raw[at + 116:at + 240]
        assert struct.unpack_from('>h', header, 108)[0] == 17 and struct.unpack_from('>H', header, 114)[0] == 3
        assert words == raw[at + 240 + 2 * 4:at + 240 + 5 * 4]


# --- 3. refusals in order, over the gateway -------------------------------------------------------------------------

REFUSED = [(row['id'], name, code) for row in SLICE_2 for name, code in sorted(row['refused'].items())]
SENTENCES = {'block': 'This window starts at 19.5 ms; this file format holds whole milliseconds. Start at sample 2 or 4.'}


@pytest.mark.parametrize('row,name,code', REFUSED, ids=['%s-%s' % c[:2] for c in REFUSED])
def test_each_slice_2_refused_window_is_refused_before_any_window_byte_is_asked(world, row, name, code):
    land, alice, requests, tmp = world
    info = land('ieee')
    requests.clear()
    with pytest.raises(CannotReadHere) as refused:
        alice.exchange(tmp / 'work').get(info.asset_id, output=tmp / 'out', window=window(name)[0])
    assert (refused.value.technical['reason'], str(refused.value)) == (code, SENTENCES[name])
    assert not [p for p in requests if p.endswith(('/file-header',)) or '/volume-windows/headers/' in p or '/volume-windows/pieces/' in p]
    assert not (tmp / 'out').exists()


def test_a_line_with_a_window_and_a_volume_without_one_are_refused_by_name(web, world):
    land, alice, requests, tmp = world
    line = alice.upload_data(line_bytes('ieee'), profile='segy-line/1', name='Line', filename='line.sgy', **UPLOAD)
    exchange = alice.exchange(tmp / 'work')
    requests.clear()
    with pytest.raises(CannotReadHere) as refused:
        exchange.get(line.asset_id, output=tmp / 'line', window='trace=1:3')
    assert refused.value.technical['reason'] == 'window-volume-only'
    assert not [p for p in requests if '/volume-windows' in p]
    with pytest.raises(CannotReadHere) as refused:
        exchange.get(land('ieee').asset_id, output=tmp / 'cube')
    assert (refused.value.technical['reason'], str(refused.value)) == (
        'volume-needs-window', 'Give a window, for example --window inline=100:104,by=label, or call Client.download_original for the whole file.')
    assert exchange.held() == {} and not (tmp / 'line').exists() and not (tmp / 'cube').exists()


# --- 6. the CLI writes the window and never asks for the original ----------------------------------------------------

def test_the_cli_gets_a_window_from_the_gateway(web, world, monkeypatch, capsys):
    """Mutation caught: the CLI keeps s1's not_available for a volume (no file, exit 1)."""
    from ophiolite import Client, cli
    land, alice, requests, tmp = world
    info = land('ibm', 'shuffled')
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c), raising=False)
    config = tmp / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': 'https://workspace.example', 'project': 'p'}))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    requests.clear(); capsys.readouterr()
    try:
        cli.entrypoint(['get', '--configuration', str(config), '--credentials', str(tmp / 'not-saved.json'), '--work', str(tmp / 'w'),
                        '--item', info.asset_id, '--output', str(tmp / 'got'), '--window', window('corner')[0]])
    except SystemExit as stop: code = stop.code
    else: code = 0
    assert (code, capsys.readouterr().err.strip()) == (0, '')
    with segyio.open(str(tmp / 'got' / 'window.sgy'), iline=189, xline=193, strict=False) as f:
        assert [float(v) for v in f.trace[0]] == [CUBE['values'][4][6][10]] and list(f.samples) == [37.0]
    assert not [p for p in requests if p.endswith('/representations/artifact')]
