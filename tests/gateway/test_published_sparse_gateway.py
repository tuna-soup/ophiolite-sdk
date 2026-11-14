"""E175 s2 C4 against the in-process gateway (strategy D-H3, D-W2; §5 rows 3 and 8): the SDK reads a cube as published
whose grid has positions without a trace, and `exchange get --window` writes a crop of it as SEG-Y when every line of
the crop holds a trace, else refuses `crop-not-segy` before writing.

The cube is the Connectors' 10-trace fixture (cells 4 and 11 without a trace, literal int16 codes) and, for formats 2,
1 and 5, the same positions written at test time by `segy.write` from literal codes (R1-11). The second gate is opened
by `sparse_open` only (C5 opens it). segyio is test-only."""
import asyncio
import math
import struct

import httpx
import pytest
import segyio  # test-only, unguarded: the SDK gateway lane installs it from [dev]
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import Credential
from ophiolite import volume_windows as vw
from ophiolite.exchange import CannotReadHere
from ophiolite.volume_windows import WindowRefused

from asset_connectors import published_form, segy
from project_gateway.tests.test_published_sparse_store import INT16, SPARSE, sparse_open  # noqa: F401 (fixture)
from project_gateway.tests.test_published_sparse_windows import CROSSLINES, GAPS, INLINES, ORDER, generated

ORIGIN = 'https://workspace.example'
DECLARED = {'crs': 'EPSG:23031', 'z_domain': 'time'}
UPLOAD = dict(declared=DECLARED, attribution='Synthetic', audience=[], rights_confirmed=True)
WIDTHS = {1: 4, 2: 4, 3: 2, 5: 4}


def land(alice, raw, name):
    return alice.upload_data(raw, profile='segy/3', name=name, filename=name + '.sgy', **UPLOAD)


def literal(cube):
    """The window's values as the SDK states them: the literal codes as floats, None at cells 4 and 11."""
    return [[None if i * 4 + j in GAPS else [float(v) for v in cube[i][j]] for j in range(4)] for i in range(3)]


async def async_read(web, info, mode, **window):
    from ophiolite.aio import AsyncClient
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url=ORIGIN) as http:
        async with AsyncClient(ORIGIN, 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            if mode == 'async-read': return (await alice.read_window(info.asset_id, info.revision, **window)).values
            reader = await alice.iter_window(info.asset_id, info.revision, **window)
            async with reader: return [t for piece in [p async for p in reader] for t in piece.values]


# --- 1. delivery (row 3) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('mode', ['read', 'iter', 'async-read', 'async-iter'])
def test_the_sparse_cube_reads_none_nan_and_masked_at_cells_4_and_11(web, sparse_open, mode):
    """Mutations: zero-fill at an absent position (RED: 0 is a literal elsewhere, so the None and the mask catch it);
    ordinals shifted after the first gap (RED: values); `codes()` answering with None (RED: no refusal)."""
    numpy = pytest.importorskip('numpy')
    alice = client(web, 'alice', 'delegate')
    info = land(alice, SPARSE, 'sparse')
    if mode == 'read':
        got = alice.read_window(info.asset_id, info.revision, sample='0:2')
        values = got.values
        masked, array = got.to_masked(), got.to_numpy()
        assert masked.dtype == numpy.int16 and masked.mask.tolist() == [[[n in GAPS] * 3 for n in range(i * 4, i * 4 + 4)] for i in range(3)]
        assert masked.compressed().tolist() == [v for i in range(3) for j in range(4) if i * 4 + j not in GAPS for v in INT16[i][j]]
        assert [math.isnan(array[i][j][0]) for i in range(3) for j in range(4)] == [n in GAPS for n in range(12)]
        assert array[0][0].tolist() == [-32768.0, -1.0, 0.0] and array[2][2].tolist() == [float(v) for v in INT16[2][2]]
        with pytest.raises(WindowRefused) as refused: got.codes()
        assert (refused.value.reason, str(refused.value)) == ('masked', vw.MASKED)
    elif mode == 'iter':
        with alice.iter_window(info.asset_id, info.revision, sample='0:2') as reader:
            traces = [t for piece in reader for t in piece.values]
            assert reader.complete
        values = [traces[i * 4:(i + 1) * 4] for i in range(3)]
    else:
        flat = asyncio.run(async_read(web, info, mode, sample='0:2'))
        values = flat if mode == 'async-read' else [flat[i * 4:(i + 1) * 4] for i in range(3)]
    assert values == literal(INT16)


@pytest.mark.parametrize('code', [2, 1, 5])
def test_sparse_int32_ibm_and_ieee_cubes_deliver_their_literals(web, sparse_open, code):
    """R1-11: to_masked() int32 with the extremes for format 2, float64 NaN for 1 and 5."""
    numpy = pytest.importorskip('numpy')
    alice = client(web, 'alice', 'delegate')
    cube, raw = generated(code)
    info = land(alice, raw, 'sparse-%d' % code)
    got = alice.read_window(info.asset_id, info.revision, sample='0:2')
    assert got.values == literal(cube)
    masked = got.to_masked()
    assert masked.dtype == (numpy.int32 if code == 2 else numpy.float64) and masked.mask[1][0].all() and masked.mask.sum() == 6
    if code == 2: assert masked[0][0][:2].tolist() == [-2147483648, 2147483647]
    assert numpy.isnan(got.to_numpy()).sum() == 6


def test_an_all_absent_window_reads_as_mask_80_and_nan(web, sparse_open):
    """R1-12: the one position at cell 4 (inline 13, crossline 21)."""
    numpy = pytest.importorskip('numpy')
    alice = client(web, 'alice', 'delegate')
    info = land(alice, SPARSE, 'sparse-one')
    got = alice.read_window(info.asset_id, info.revision, inline='13', crossline='21', by='label')
    assert got.document['absent']['count'] == 1 and got.values == [[None]]
    assert numpy.isnan(got.to_numpy()).all() and got.to_masked().mask.all()


# --- 3. exchange get --window (row 8) ---------------------------------------------------------------------------

@pytest.fixture
def world(web, tmp_path):
    alice, requests = client(web, 'alice', 'delegate'), []
    web.c.event_hooks['request'].append(lambda request: requests.append(request.url.path))
    return alice, requests, tmp_path


@pytest.mark.parametrize('code', [3, 2, 1, 5])
def test_the_whole_crop_writes_the_present_traces_and_reads_back_sparse(world, sparse_open, code):
    """The 3 x 4 crop: every inline and crossline holds a trace, so `window.sgy` holds the 10 present traces, each with
    its original header (but 109-110 and 115-116) and its words; segyio reads the literals; the Connectors read it back
    as published with traces 10, cells 12, absent 2. Mutations: absent positions written as zero traces (RED: length,
    tracecount); headers taken by position rather than by present rank (RED: labels)."""
    alice, requests, tmp = world
    cube, raw = (INT16, SPARSE) if code == 3 else generated(code)
    info = land(alice, raw, 'sparse-get-%d' % code)
    got = alice.exchange(tmp / 'work').get(info.asset_id, output=tmp / 'out', window='sample=0:2')
    assert got.outcome == 'got'
    written = (tmp / 'out' / 'window.sgy').read_bytes()
    trace = 240 + 3 * WIDTHS[code]
    assert len(written) == 3600 + 10 * trace
    present = [(i, j) for i in range(3) for j in range(4) if i * 4 + j not in GAPS]
    original = lambda i, j: raw[3600 + ORDER.index((INLINES[i], CROSSLINES[j])) * trace:][:240]  # noqa: E731
    for k, (i, j) in enumerate(present):
        head = written[3600 + k * trace:3600 + k * trace + 240]
        assert head[:108] + head[110:114] + head[116:] == original(i, j)[:108] + original(i, j)[110:114] + original(i, j)[116:], k
    with segyio.open(str(tmp / 'out' / 'window.sgy'), ignore_geometry=True) as f:
        assert (int(f.format), f.tracecount, len(f.samples)) == (code, 10, 3)
        assert [[float(v) for v in f.trace[k]] for k in range(10)] == [[float(v) for v in cube[i][j]] for i, j in present]
        assert [(h[segyio.TraceField.INLINE_3D], h[segyio.TraceField.CROSSLINE_3D]) for h in f.header] == [(INLINES[i], CROSSLINES[j]) for i, j in present]
    context, index, _ = segy.scan(written, DECLARED, published=True)
    assert (context['traces'], context['cells'], context['absent']) == (10, 12, 2) and index.grid.tolist()[4] == published_form.ABSENT


def test_an_all_absent_crop_refuses_with_no_answer_asked(world, sparse_open):
    """D-W2 case 1 (R1-8): the one position at cell 4. Mutation: the case-1 check removed (RED: a headers answer asked)."""
    alice, requests, tmp = world
    info = land(alice, SPARSE, 'sparse-crop-one')
    requests.clear()
    with pytest.raises(CannotReadHere) as refused:
        alice.exchange(tmp / 'work').get(info.asset_id, output=tmp / 'out', window='inline=13,crossline=21,by=label')
    assert refused.value.technical['reason'] == 'crop-not-segy' and refused.value.facts['sentence'] == vw.CROP_NOT_SEGY
    assert [p for p in requests if '/headers/' in p or '/pieces/' in p] == [] and not (tmp / 'out').exists()


# --- C5 t4: a portable bundle (row 15), the gate open as shipped ----------------------------------------------------

def test_a_bundle_of_slices_of_the_sparse_cube_refuses_before_writing(web, monkeypatch, tmp_path):
    """No `sparse_open`: the cube lands with the second gate open as shipped; `export_slices` asks one slice, which the
    gateway refuses with PUBLISHED_PART; traps on `write_bundle` and the staging folder record nothing. Mutation: the
    staging made before the slices are read (RED: a staging call)."""
    import tempfile
    from ophiolite import bundle
    from ophiolite.errors import Incompatible
    from test_published_bundle import PUBLISHED_PART
    assert published_form.SPARSE_ADMITTED is True
    requests, calls = [], []
    web.c.event_hooks['request'].append(lambda request: requests.append(request.url.path))
    monkeypatch.setattr(bundle, 'write_bundle', lambda *a, **k: calls.append('write_bundle'))
    made = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, 'mkdtemp', lambda *a, **k: calls.append('staging') or made(*a, **k))
    alice = client(web, 'alice', 'delegate')
    info = land(alice, SPARSE, 'sparse-bundle')
    out = tmp_path / 'out'
    out.mkdir()
    requests.clear()
    with pytest.raises(Incompatible) as refused: alice.export_slices(info.asset_id, info.revision, [('inline', 13)], out / 'slices')
    assert (str(refused.value), refused.value.status) == (PUBLISHED_PART, 422)
    assert len([r for r in requests if '/slices/' in r]) == 1 and calls == [] and list(out.iterdir()) == []
