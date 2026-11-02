"""E123 SZ C2: writers.write_volume writes SEG-Y rev 1 with IEEE samples. Two oracles: struct at literal SEG-Y byte
offsets (this file's own reading), and segyio 1.9.14 (rule 6; a dev-only test dependency on Linux x86_64, D7).
Mutations: format code 1 (the header test RED), the scalar's sign (RED), crossline-major trace order (RED)."""
import importlib
import importlib.util
import platform
import struct
import sys

import pytest

from ophiolite import writers
from ophiolite.errors import ValidationFailed

DECODES_HERE = sys.platform == 'linux' and platform.machine() == 'x86_64'  # the dev extra's marker (pyproject.toml)


def oracle(name):
    """The module NAME where the dev extra installs it (Linux x86_64: required, so a failed install fails the test);
    elsewhere the module if importable, else None after asserting it is absent (never a skip)."""
    if DECODES_HERE: return importlib.import_module(name)
    if importlib.util.find_spec(name) is None: return None
    return importlib.import_module(name)


INLINES, CROSSLINES = [10, 12], [7, 8, 9]
CUBE = [[[i * 100 + j * 10 + k + 0.5 for k in range(4)] for j in range(3)] for i in range(2)]
XY = [(1000 + 25 * i, -2000 + 5 * j) for i in range(2) for j in range(3)]  # whole tenths of a metre, scalar -10


def volume(samples=CUBE, **changes):
    args = dict(inlines=INLINES, crosslines=CROSSLINES, sample_interval=2000, first_sample=100, cdp_xy=XY, scalar=-10,
                text_lines=['CONVERTED FOR A TEST', 'SECOND LINE'], declared={'z_domain': 'time', 'crs': 'EPSG:23031'})
    args.update(changes)
    return writers.write_volume(samples, **args)


def at(raw, offset, fmt):
    return struct.unpack_from(fmt, raw, offset)[0]


def trace(raw, n, samples=4):
    return 3600 + n * (240 + 4 * samples)


def test_the_headers_and_samples_are_where_seg_y_puts_them():
    written = volume()
    raw = written.bytes
    assert (written.profile, written.filename, written.declared) == ('segy/1', 'volume.sgy', {'z_domain': 'time', 'crs': 'EPSG:23031'})
    assert len(raw) == 3600 + 6 * (240 + 16)
    assert raw[:80].decode('ascii') == 'C 1 CONVERTED FOR A TEST'.ljust(80) and raw[80:84] == b'C 2 '
    assert (at(raw, 3216, '>H'), at(raw, 3220, '>H'), at(raw, 3224, '>h'), at(raw, 3500, '>H'), at(raw, 3502, '>h')) == (2000, 4, 5, 0x0100, 1)
    headers = [(at(raw, trace(raw, n) + 188, '>i'), at(raw, trace(raw, n) + 192, '>i'), at(raw, trace(raw, n) + 180, '>i'),
                at(raw, trace(raw, n) + 184, '>i'), at(raw, trace(raw, n) + 70, '>h'), at(raw, trace(raw, n) + 108, '>h'),
                at(raw, trace(raw, n) + 114, '>H'), at(raw, trace(raw, n) + 116, '>H')) for n in range(6)]
    assert headers[0] == (10, 7, 1000, -2000, -10, 100, 4, 2000)
    assert headers[2] == (10, 9, 1000, -1990, -10, 100, 4, 2000)  # inline-major: the third trace is still inline 10
    assert headers[5] == (12, 9, 1025, -1990, -10, 100, 4, 2000)
    # three asymmetric samples, as IEEE bit patterns
    assert raw[trace(raw, 0) + 240:trace(raw, 0) + 244] == struct.pack('>f', 0.5) == bytes.fromhex('3f000000')
    assert raw[trace(raw, 4) + 248:trace(raw, 4) + 252] == bytes.fromhex('42e10000')  # inline 12, crossline 8, sample 2: 112.5
    assert raw[trace(raw, 5) + 252:trace(raw, 5) + 256] == bytes.fromhex('42f70000')  # inline 12, crossline 9, sample 3: 123.5


def test_segyio_reads_the_same_volume(tmp_path):
    segyio = oracle('segyio')
    if segyio is None: return
    path = tmp_path / 'v.sgy'
    path.write_bytes(volume().bytes)
    with segyio.open(str(path), iline=189, xline=193) as f:
        assert list(f.ilines) == INLINES and list(f.xlines) == CROSSLINES
        assert list(f.samples) == [100.0, 102.0, 104.0, 106.0]  # delay and dt, in ms
        assert [(h[segyio.TraceField.CDP_X], h[segyio.TraceField.CDP_Y], h[segyio.TraceField.SourceGroupScalar]) for h in f.header][4] == (1025, -1995, -10)
        assert [list(map(float, t)) for t in f.trace] == [trace for row in CUBE for trace in row]
        # by geometry, not file order: each header owns its trace's samples
        assert [[list(map(float, t)) for t in f.iline[il]] for il in INLINES] == CUBE
        assert [list(map(float, t)) for t in f.xline[8]] == [CUBE[0][1], CUBE[1][1]]


@pytest.mark.parametrize('changes, words', [
    ({'samples': [[[1.0], [2.0, 3.0], [4.0]], [[1.0], [2.0], [3.0]]]}, 'has 2 samples'),
    ({'samples': [[[], [], []], [[], [], []]]}, 'at least one sample'),
    ({'samples': [[[1.0], [2.0], [float('nan')]], [[1.0], [2.0], [3.0]]]}, 'Inline 10, crossline 9, sample 0 is not a finite number'),
    ({'samples': [[[1.0], [2.0], [3.0]], [[1.0], [1e39], [3.0]]]}, 'Inline 12, crossline 8, sample 0 is not a finite number'),
    ({'sample_interval': 0}, 'from 1 to 65535; it is 0'),
    ({'sample_interval': 65536}, 'from 1 to 65535; it is 65536'),
    ({'first_sample': -32769}, 'from -32768 to 32767; it is -32769'),
    ({'first_sample': 32768}, 'from -32768 to 32767; it is 32768'),
    ({'scalar': -100000}, 'one of -1, -10, -100, -1000'),
    ({'cdp_xy': XY[:5] + [(2**31, 0)]}, 'CDP X'),
    ({'inlines': [10, 10]}, 'repeated'),
])
def test_a_volume_the_format_cannot_carry_is_refused(changes, words):
    with pytest.raises(ValidationFailed) as refused: volume(**changes)
    assert words in str(refused.value)


@pytest.mark.parametrize('changes', [{'sample_interval': 1}, {'sample_interval': 65535}, {'first_sample': -32768}, {'first_sample': 32767}, {'scalar': -1}])
def test_the_boundaries_are_accepted(changes):
    assert volume(**changes).profile == 'segy/1'


def test_numpy_samples_write_the_same_bytes():
    import numpy
    assert volume(samples=numpy.array(CUBE, dtype=numpy.float32)).bytes == volume().bytes
    with pytest.raises(ValidationFailed) as refused: volume(samples=numpy.array([[[1, 2, 3, 4]] * 3, [[1, 2, numpy.inf, 4]] * 3], dtype=numpy.float32))
    assert 'Inline 12, crossline 7, sample 2' in str(refused.value)
