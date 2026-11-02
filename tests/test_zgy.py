"""E123 SZ C3: ophiolite.zgy converts a ZGY cube on this computer to SEG-Y rev 1 (IEEE), exactly or not at all.

Oracles, none of them OpenZGY or segyio reading our own output: the twins written beside the OpenZGY test cubes
(`*.sgy`, IBM floats), decoded here by hand; the integer-storage lattice computed from the stated datarange; the E16
SEG-Y fixture, decoded by hand before any cube is written; literal values. segyio (rule 6) reads the outputs back as
a second reader. The settings and refusal matrix runs through a reader stand-in (`Cube`: the header as OpenZGY
states it, and its samples); the real-file cases need openzgy, which the dev extra installs on Linux x86_64 (D7).
Mutations are run here, against copies of zgy.py and writers.py (C3 test 3)."""
import importlib.util
import math
import struct
import sys
from pathlib import Path

import pytest

from ophiolite import zgy
from ophiolite.procedures import Stopped
from test_writers_volume import oracle

import numpy  # the dev install has it (pyzgy requires it); zgy.convert imports it when it reads samples
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'zgy'
SDK = Path(zgy.__file__).resolve().parent
SET = {'crs': 'EPSG:23031', 'z_domain': 'time', 'horizontal_unit': 'm'}


# ---------------------------------------------------------------- hand decoding

def ibm(word):
    sign = -1.0 if word >> 31 else 1.0
    return sign * (word & 0xFFFFFF) / float(1 << 24) * 16.0 ** (((word >> 24) & 0x7F) - 64)


def segy(raw):
    """A SEG-Y rev 1 file as {(inline, crossline): (x, y, scalar, samples)}, decoded at the literal byte offsets."""
    count, code = struct.unpack_from('>H', raw, 3220)[0], struct.unpack_from('>h', raw, 3224)[0]
    size, out = 240 + 4 * count, {}
    for start in range(3600, len(raw), size):
        x, y, il, xl = struct.unpack_from('>iiii', raw, start + 180)
        words = struct.unpack_from('>%dI' % count, raw, start + 240)
        values = [ibm(w) for w in words] if code == 1 else list(struct.unpack_from('>%df' % count, raw, start + 240))
        out[(il, xl)] = (x, y, struct.unpack_from('>h', raw, start + 70)[0], values)
    return out


def axes(raw):
    return struct.unpack_from('>H', raw, 3216)[0], struct.unpack_from('>h', raw, 3600 + 108)[0]


def differences(raw, expected, tolerance=None):
    """Every position where the written cube differs from EXPECTED {(il, xl): samples}: wrong traces, or a sample
    outside TOLERANCE (a function of the expected value; exact when None)."""
    written, out = segy(raw), []
    if sorted(written) != sorted(expected): return ['traces %s, expected %s' % (sorted(written)[:3], sorted(expected)[:3])]
    for key, values in expected.items():
        for k, (a, b) in enumerate(zip(written[key][3], values)):
            if (a != b) if tolerance is None else abs(a - b) > tolerance(b): out.append('inline %d, crossline %d, sample %d' % (key + (k,)))
    return out


def twin(name):
    return {key: value[3] for key, value in segy((FIXTURES / name).read_bytes()).items()}


def ibm_precision(value):
    return abs(value) * 2.0 ** -20


# ---------------------------------------------------------------- the reader stand-in

class Cube:
    """The reader interface zgy.convert uses: `meta` as OpenZGY states it, `read` counting sample reads."""
    def __init__(self, samples=None, **meta):
        self.meta = {'size': (3, 4, 5), 'datatype': 'float', 'datarange': (0.0, 1.0), 'zunitdim': 'time', 'zunitname': 'ms',
                     'zunitfactor': 0.001, 'zstart': 0.0, 'zinc': 4.0, 'hunitdim': 'length', 'hunitname': 'm', 'hunitfactor': 1.0,
                     'annotstart': (1.0, 1.0), 'annotinc': (1.0, 1.0), 'corners': ((0.0, 0.0), (20.0, 0.0), (0.0, 30.0), (20.0, 30.0))}
        self.meta.update(meta)
        self.samples, self.reads = samples, 0

    def read(self, start, buffer):
        self.reads += 1
        buffer[...] = self.samples if self.samples is not None else numpy.arange(buffer.size, dtype=numpy.float32).reshape(buffer.shape)


def converted(cube=None, **settings):
    return zgy.convert(cube or Cube(), **{**SET, **settings})


def stopped(call):
    with pytest.raises(Stopped) as stop: call()
    return stop.value


def refused(cube, *words, **settings):
    stop = stopped(lambda: converted(cube, **settings))
    assert not stop.asks and cube.reads == 0, (stop.sentence, cube.reads)
    for word in words: assert word in stop.sentence, (word, stop.sentence)
    return stop.sentence


def coordinates(raw):
    return {key: (x, y, scalar) for key, (x, y, scalar, _) in segy(raw).items()}


# ---------------------------------------------------------------- 1, 2: the real cubes

def api():
    return oracle('openzgy.api')


def test_the_real_cube_lands_with_its_axes_and_the_three_literals():
    if api() is None: return
    written = zgy.read(FIXTURES / 'small-32bit.zgy', **SET)
    raw = written.bytes
    assert (written.profile, written.filename, written.declared) == ('segy/1', 'small-32bit.sgy', {'crs': 'EPSG:23031', 'z_domain': 'time'})
    assert len(raw) == 3600 + 25 * (240 + 200) and axes(raw) == (4000, 0) and struct.unpack_from('>h', raw, 3224)[0] == 5
    traces = segy(raw)
    assert sorted({il for il, _ in traces}) == [1, 2, 3, 4, 5] and sorted({xl for _, xl in traces}) == [20, 21, 22, 23, 24]
    assert [round(v, 7) for v in traces[(1, 20)][3][:3]] == [1.1999998, 1.2000093, 1.2000198]
    assert round(traces[(5, 24)][3][49], 5) == 5.24049 and round(traces[(3, 23)][3][17], 7) == 3.2301693
    text = raw[:3200].decode('ascii')
    assert 'zunitfactor 1.0' in text and 'SHA-256 fdde06a818d1ae5c077f8d361cdb175cc4279be93ec1b39f892d265fc47d471e' in text
    assert text.startswith('C 1 CONVERTED FROM ZGY BY OPHIOLITE ')


def test_every_sample_equals_the_hand_decoded_twin():
    if api() is None: return
    assert differences(zgy.read(FIXTURES / 'small-32bit.zgy', **SET).bytes, twin('small-32bit.sgy')) == []


@pytest.mark.parametrize('name, low, high', [('small-8bit', -128, 127), ('small-16bit', -32768, 32767)])
def test_integer_storage_is_scaled_by_the_stated_datarange(name, low, high):
    if api() is None: return
    raw = zgy.read(FIXTURES / (name + '.zgy'), **SET).bytes
    assert differences(raw, twin(name + '.sgy'), ibm_precision) == []
    lo, hi = 1.1999998092651367, 5.240489959716797  # the stated datarange (both cubes)
    step = (hi - lo) / (high - low)
    for _, _, _, values in segy(raw).values():
        for v in values:
            k = round((v - lo) / step) + low
            lattice = numpy.float32(lo + (k - low) * step)
            assert low <= k <= high and abs(v - float(lattice)) <= float(numpy.spacing(lattice)), (v, k, lattice)


def test_a_changed_byte_is_named_by_position():
    if api() is None: return
    raw = bytearray(zgy.read(FIXTURES / 'small-32bit.zgy', **SET).bytes)
    raw[3600 + 13 * 440 + 240 + 4 * 17] ^= 0x01  # trace 13 is inline 3, crossline 23; sample 17
    assert differences(bytes(raw), twin('small-32bit.sgy')) == ['inline 3, crossline 23, sample 17']


# ---------------------------------------------------------------- 3: mutations against the fixed oracles

def mutant(path, name, replacements, **extra):
    source = path.read_text()
    for old, new in replacements:
        assert source.count(old) == 1, old
        source = source.replace(old, new)
    spec = importlib.util.spec_from_loader('ophiolite.' + name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__package__, module.__file__ = 'ophiolite', str(path)
    module.__dict__.update(extra)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


READ = 'reader.read((0, 0, 0), samples)'
MUTANTS = {
    'extraction': [(READ, READ + '; samples = samples.transpose(1, 0, 2).copy()')],
    'indexing': [('        first, last = int(start),', '        start = Decimal(0); first, last = int(start),')],
    'association': [(READ, READ + '; samples[2, 2] = samples[2, 3]')],
}


def read_with(module, name):
    with api().ZgyReader(str(FIXTURES / name)) as reader:
        return module.convert(reader, **SET).bytes


@pytest.mark.parametrize('kind', sorted(MUTANTS))
def test_the_twin_oracle_catches_each_converter_mutation(kind):
    if api() is None: return
    module = mutant(SDK / 'zgy.py', '_zgy_' + kind, MUTANTS[kind])
    assert differences(read_with(module, 'small-32bit.zgy'), twin('small-32bit.sgy')) != []


def test_the_datarange_oracle_catches_raw_integers():
    if api() is None: return
    module = mutant(SDK / 'zgy.py', '_zgy_raw', [(READ, 'raw = numpy.zeros(size, dtype=numpy.int16); reader.read((0, 0, 0), raw); samples = raw.astype(numpy.float32)')])
    assert differences(read_with(module, 'small-16bit.zgy'), twin('small-16bit.sgy'), ibm_precision) != []


def ibm_word(value):
    if value == 0: return 0
    sign, value, exponent = (0x80000000 if value < 0 else 0), abs(value), 64
    while value >= 1: value, exponent = value / 16, exponent + 1
    while value < 1 / 16: value, exponent = value * 16, exponent - 1
    return sign | exponent << 24 | int(value * (1 << 24))


def test_the_twin_oracle_catches_ibm_words_under_format_5():
    if api() is None: return
    writers = mutant(SDK / 'writers.py', '_writers_ibm', [("words = array[i, j].astype('>f4')",
                                                           "words = __import__('numpy').array([ibm_word(float(v)) for v in array[i, j]], dtype='>u4').view('>f4')")],
                     ibm_word=ibm_word)
    module = mutant(SDK / 'zgy.py', '_zgy_ibm', [('from .writers import write_volume', 'write_volume = WRITE')], WRITE=writers.write_volume)
    assert differences(read_with(module, 'small-32bit.zgy'), twin('small-32bit.sgy')) != []


# ---------------------------------------------------------------- 4: lines, coordinates, horizontal units

def test_the_translated_cube_lands_at_whole_metres():
    if api() is None: return
    xy = coordinates(zgy.read(FIXTURES / 'small-32bit_translated.zgy', **SET).bytes)
    assert xy[(3, 22)] == (7500, 10000, -1)
    assert [xy[k] for k in ((1, 20), (5, 20), (1, 24), (5, 24))] == [(2500, 5000, -1), (12500, 5000, -1), (2500, 15000, -1), (12500, 15000, -1)]


def test_the_rotated_cube_is_refused_naming_its_coordinate():
    if api() is None: return
    stop = stopped(lambda: zgy.read(FIXTURES / 'small-32bit_rotated.zgy', **SET))
    assert not stop.asks and '-13.435028842544401' in stop.sentence and 'cannot be written exactly' in stop.sentence


@pytest.mark.parametrize('corners, scalar, second', [
    (((0.0, 0.0), (1.0, 0.0), (0.0, 1.5), (1.0, 1.5)), -10, (5, 0)),  # 0.5 m steps
    (((0.0, 0.0), (0.5, 0.0), (0.0, 0.75), (0.5, 0.75)), -100, (25, 0)),  # 0.25 m steps
    (((0.0, 0.0), (20.0, 0.0), (0.0, 30.0), (20.0, 30.0)), -1, (10, 0)),
])
def test_the_coarsest_exact_scalar_is_chosen(corners, scalar, second):
    xy = coordinates(converted(Cube(corners=corners)).bytes)
    assert xy[(2, 1)] == second + (scalar,) and {s for _, _, s in xy.values()} == {scalar}


def test_coordinates_on_thirds_are_refused_naming_the_trace():
    refused(Cube(corners=((0.0, 0.0), (2.0, 0.0), (0.0, 1.0), (2.0, 1.0))), '1/3', 'y of inline 1, crossline 2')


@pytest.mark.parametrize('size, corners, expected', [
    ((1, 4, 5), ((10.0, 20.0), (10.0, 20.0), (10.0, 50.0), (10.0, 50.0)), {(1, 1): (10, 20), (1, 2): (10, 30), (1, 3): (10, 40), (1, 4): (10, 50)}),
    ((3, 1, 5), ((10.0, 20.0), (30.0, 20.0), (10.0, 20.0), (30.0, 20.0)), {(1, 1): (10, 20), (2, 1): (20, 20), (3, 1): (30, 20)}),
])
def test_a_singleton_dimension_lands_with_each_coordinate(size, corners, expected):
    xy = coordinates(converted(Cube(size=size, corners=corners)).bytes)
    assert {key: (x, y) for key, (x, y, _) in xy.items()} == expected


@pytest.mark.parametrize('changes, words', [
    ({'corners': ((30000000.25, 0.0), (30000001.25, 0.0), (30000000.25, 3.0), (30000001.25, 3.0))}, ('30000000.25', 'scalar -100', '32-bit')),
    ({'corners': ((0.0, 0.0), (20.0, 0.0), (0.0, float('nan')), (20.0, 30.0))}, ('Corner 3', 'nan', 'not a finite number')),
    ({'corners': ((0.0, 0.0), (20.0, 0.0), (0.0, 30.0), (21.0, 30.0))}, ('parallelogram', 'x of corner 4 is 21.0')),
    ({'annotinc': (0.0, 1.0)}, ('inline increment 0.0', 'positive whole number')),
    ({'annotinc': (1.0, -1.0)}, ('crossline increment -1.0', 'positive whole number')),
    ({'annotstart': (1.5, 1.0)}, ('first inline number 1.5', 'not a whole number')),
    ({'annotstart': (2147483646.0, 1.0)}, ('inline number 2147483648', '32-bit')),
    ({'annotstart': (1.0, -2147483649.0)}, ('crossline number -2147483649', '32-bit')),
])
def test_lines_and_corners_the_format_cannot_carry_are_refused(changes, words):
    refused(Cube(**changes), *words)


@pytest.mark.parametrize('dim, name, factor, words', [
    ('length', 'ft', 0.3048, ('feet', 'length, factor 0.3048')),
    ('arcangle', 'deg', 1.0, ('deg', 'arcangle, factor 1.0')),
    ('unknown', '', 0.3048, ('unknown, factor 0.3048',)),
])
def test_horizontal_units_other_than_metres_are_refused(dim, name, factor, words):
    refused(Cube(hunitdim=dim, hunitname=name, hunitfactor=factor), 'only metres', *words)


def test_an_unstated_horizontal_unit_is_asked_with_the_question():
    cube = Cube(hunitdim='unknown', hunitname='')
    stop = stopped(lambda: converted(cube, horizontal_unit=None))
    assert stop.asks and cube.reads == 0
    assert stop.sentence.startswith('Choose the coordinate system and confirm whether the samples represent time or depth.')
    assert 'does not state the unit of its horizontal coordinates' in stop.sentence and 'horizontal_unit=m' in stop.sentence
    assert converted(Cube(hunitdim='unknown', hunitname='')).profile == 'segy/1'
    assert converted(Cube(), horizontal_unit=None).profile == 'segy/1'  # a stated metre needs no confirmation


# ---------------------------------------------------------------- 5: the vertical axis

def test_the_question_comes_before_any_sample_and_names_what_the_file_states():
    cube = Cube(zunitdim='unknown', zunitname='', zunitfactor=1.0)
    stop = stopped(lambda: zgy.convert(cube))
    assert stop.asks and cube.reads == 0
    assert stop.sentence.startswith('Choose the coordinate system and confirm whether the samples represent time or depth.')
    assert 'no vertical unit, start 0.0, step 4.0' in stop.sentence and 'Technical details: run again with settings crs=' in stop.sentence
    for settings in ({'crs': ''}, {'crs': '  '}, {'z_domain': None}, {'z_domain': 'not_confirmed'}):
        assert stopped(lambda: converted(Cube(), **settings)).asks


@pytest.mark.parametrize('changes, settings, expected', [
    ({'zstart': 100.0, 'zinc': 2.0}, {}, (2000, 100)),
    ({'zinc': 0.25}, {}, (250, 0)),
    ({'zinc': 65.535}, {}, (65535, 0)),
    ({'zinc': 0.001}, {}, (1, 0)),
    ({'zstart': -32768.0}, {}, (4000, -32768)),
    ({'zstart': 32767.0}, {}, (4000, 32767)),
    ({'zunitdim': 'length', 'zunitname': 'm', 'zunitfactor': 1.0, 'zinc': 5.0}, {'z_domain': 'depth'}, (5000, 0)),
    ({'zunitdim': 'unknown', 'zunitname': '', 'zunitfactor': 1.0, 'zinc': 5.0}, {'z_domain': 'depth'}, (5000, 0)),
    ({'zunitdim': 'unknown', 'zunitname': '', 'zunitfactor': 0.3048, 'zstart': 8.0}, {}, (4000, 8)),  # unknown: the factor is not evidence
])
def test_the_vertical_axis_is_mapped_exactly(changes, settings, expected):
    assert axes(converted(Cube(**changes), **settings).bytes) == expected


@pytest.mark.parametrize('changes, settings, words', [
    ({'zstart': 2.5}, {}, ('first sample time 2.5 ms',)),
    ({'zinc': 0.0004}, {}, ('sample interval 0.0004 ms', 'microseconds')),
    ({'zinc': 65.536}, {}, ('sample interval 65.536 ms',)),
    ({'zinc': 0.0}, {}, ('sample interval 0.0 ms',)),
    ({'zstart': -32769.0}, {}, ('-32769.0 ms',)),
    ({'zstart': 32768.0}, {}, ('32768.0 ms',)),
    ({'zunitfactor': 1.0, 'zunitname': 's', 'zinc': 0.004}, {}, ('seconds', 'factor 1.0', 'only milliseconds')),
    ({'zunitdim': 'length', 'zunitname': 'm', 'zunitfactor': 1.0, 'zstart': 1000.0}, {'z_domain': 'depth'}, ('starts at 1000.0 m',)),
    ({'zunitdim': 'length', 'zunitname': 'ft', 'zunitfactor': 0.3048}, {'z_domain': 'depth'}, ('feet', 'factor 0.3048', 'only metres')),
    ({'zunitdim': 'arcangle', 'zunitname': 'deg', 'zunitfactor': 1.0}, {}, ('arcangle',)),
    ({}, {'z_domain': 'depth'}, ('states vertical time', 'z_domain=depth')),
    ({'zunitdim': 'length', 'zunitname': 'm', 'zunitfactor': 1.0}, {}, ('states vertical depth', 'z_domain=time')),
])
def test_a_vertical_axis_that_cannot_be_carried_exactly_is_refused(changes, settings, words):
    refused(Cube(**changes), *words, **settings)


def test_real_files_state_their_units_as_the_stand_in_does(tmp_path):
    zgy_api = api()
    if zgy_api is None: return
    def write(name, **meta):
        path = tmp_path / name
        with zgy_api.ZgyWriter(str(path), size=(3, 4, 5), datatype=zgy_api.SampleDataType.float, annotstart=(1, 1), annotinc=(1, 1),
                               corners=((0, 0), (20, 0), (0, 30), (20, 30)), **meta) as writer:
            writer.write((0, 0, 0), numpy.arange(60, dtype=numpy.float32).reshape(3, 4, 5))
        return path
    time = write('time.zgy', zunitdim=zgy_api.UnitDimension.time, zunitname='ms', zunitfactor=0.001, zstart=100.0, zinc=2.0,
                 hunitdim=zgy_api.UnitDimension.length, hunitname='m', hunitfactor=1.0)
    assert axes(zgy.read(time, crs='EPSG:23031', z_domain='time').bytes) == (2000, 100)
    depth = write('depth.zgy', zunitdim=zgy_api.UnitDimension.length, zunitname='m', zunitfactor=1.0, zstart=0.0, zinc=5.0,
                  hunitdim=zgy_api.UnitDimension.length, hunitname='m', hunitfactor=1.0)
    assert axes(zgy.read(depth, crs='EPSG:23031', z_domain='depth').bytes) == (5000, 0)
    feet = write('feet.zgy', zunitdim=zgy_api.UnitDimension.time, zunitname='ms', zunitfactor=0.001, zstart=0.0, zinc=4.0,
                 hunitdim=zgy_api.UnitDimension.length, hunitname='ft', hunitfactor=0.3048)
    stop = stopped(lambda: zgy.read(feet, **SET))
    assert not stop.asks and 'feet' in stop.sentence and 'factor 0.3048' in stop.sentence


# ---------------------------------------------------------------- 6: the E16 cube, through OpenZGY and back

E16 = segy((FIXTURES / 'e16-volume.sgy').read_bytes())  # decoded once, before any cube is written (C7)


def e16_zgy(path, cube):
    zgy_api = api()
    ils, xls = sorted({il for il, _ in E16}), sorted({xl for _, xl in E16})
    corner = lambda il, xl: tuple(v / 100 for v in E16[(il, xl)][:2])  # the fixture's scalar is -100
    with zgy_api.ZgyWriter(str(path), size=cube.shape, datatype=zgy_api.SampleDataType.float, zunitdim=zgy_api.UnitDimension.time,
                           zunitname='ms', zunitfactor=0.001, zstart=0.0, zinc=4.0, hunitdim=zgy_api.UnitDimension.length, hunitname='m',
                           hunitfactor=1.0, annotstart=(ils[0], xls[0]), annotinc=(ils[1] - ils[0], 1),
                           corners=(corner(ils[0], xls[0]), corner(ils[-1], xls[0]), corner(ils[0], xls[-1]), corner(ils[-1], xls[-1]))) as writer:
        writer.write((0, 0, 0), cube)


def test_the_e16_cube_round_trips_through_zgy(tmp_path):
    if api() is None: return
    assert sorted({il for il, _ in E16}) == [100, 102, 104] and sorted({xl for _, xl in E16}) == [10, 11, 12, 13]
    expected = {key: [float(numpy.float32(v)) for v in value[3]] for key, value in E16.items()}
    cube = numpy.array([[expected[(il, xl)] for xl in (10, 11, 12, 13)] for il in (100, 102, 104)], dtype=numpy.float32)
    e16_zgy(tmp_path / 'e16.zgy', cube)
    raw = zgy.read(tmp_path / 'e16.zgy', **SET).bytes
    assert axes(raw) == (4000, 0) and differences(raw, expected) == []
    assert {key: (x * 100, y * 100) for key, (x, y, s) in coordinates(raw).items()} == {key: tuple(v[:2]) for key, v in E16.items()}
    changed = cube.copy(); changed[1, 2, 1] += 1.0  # the expected values stay as decoded
    e16_zgy(tmp_path / 'changed.zgy', changed)
    assert differences(zgy.read(tmp_path / 'changed.zgy', **SET).bytes, expected) == ['inline 102, crossline 12, sample 1']


# ---------------------------------------------------------------- 7: bounds, before any sample

@pytest.mark.parametrize('size, words', [
    ((1_000_001, 1, 1), ('1000001 traces', 'at most 1000000')),
    ((1, 1, 20_001), ('20001 samples per trace', 'at most 20000')),
    ((31_655, 1, 1000), ('134220800 bytes', '128 MiB')),
])
def test_a_cube_beyond_the_bounds_is_refused_before_its_samples(size, words):
    refused(Cube(size=size), *words)


def test_the_output_bound_accepts_its_last_shape():
    assert zgy.output_bytes((31_654, 1, 1000)) == 134_216_560 <= zgy.MAX_OUTPUT_BYTES < zgy.output_bytes((31_655, 1, 1000)) == 134_220_800
    zgy._bounds((31_654, 1, 1000)); zgy._bounds((1, 1, 20_000))  # (a million traces is already over 128 MiB: 244 bytes each at least)


def test_a_file_over_32_mib_is_refused_before_its_header(tmp_path, monkeypatch):
    path = tmp_path / 'big.zgy'
    with open(path, 'wb') as handle: handle.truncate(32 * 1024 * 1024 + 1)  # sparse
    def opened(): raise LookupError('the header was opened')
    monkeypatch.setattr(zgy, '_api', opened)
    for call in (lambda: zgy.read(path, **SET), lambda: zgy.header(path)):
        stop = stopped(call)
        assert not stop.asks and '33554433 bytes' in stop.sentence and '32 MiB' in stop.sentence
    with open(path, 'wb') as handle: handle.truncate(32 * 1024 * 1024)
    with pytest.raises(LookupError): zgy.read(path, **SET)  # exactly 32 MiB passes the bound and goes on to the header


def test_without_pyzgy_the_sentence_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, 'openzgy', None); monkeypatch.setitem(sys.modules, 'openzgy.api', None)
    stop = stopped(lambda: zgy.read(FIXTURES / 'small-32bit.zgy', **SET))
    assert stop.sentence == zgy.MISSING and "pip install 'ophiolite[zgy]'" in stop.sentence and not stop.asks


def test_a_non_finite_sample_is_refused_with_its_position():
    samples = numpy.zeros((3, 4, 5), dtype=numpy.float32); samples[2, 1, 3] = numpy.nan
    stop = stopped(lambda: converted(Cube(samples=samples)))
    assert 'Inline 3, crossline 2, sample 3 is not a finite number' in stop.sentence and not stop.asks


# ---------------------------------------------------------------- 9: the packaged procedure, run here

def run_packaged(tmp_path, cube, settings=(), folder=None, output='out'):
    from ophiolite import procedures
    return procedures.run(folder or zgy.PROCEDURE, tmp_path / output, {'file': [str(cube)]}, settings=list(settings))


def test_the_packaged_procedure_asks_then_lands_the_cube(tmp_path):
    from ophiolite import procedures
    assert procedures.validate(zgy.PROCEDURE) is not None
    if api() is None: return
    with pytest.raises(procedures.NotRun) as stop: run_packaged(tmp_path, FIXTURES / 'small-32bit.zgy')
    assert stop.value.code == 'asked' and str(stop.value).startswith('Not run yet: Choose the coordinate system and confirm whether')
    assert not (tmp_path / 'out').exists()
    run_packaged(tmp_path, FIXTURES / 'small-32bit.zgy', ['crs=EPSG:23031', 'z_domain=time', 'horizontal_unit=m'])
    import json
    record = json.loads((tmp_path / 'out/run.json').read_text())
    assert list(record['outputs']) == ['volume'] and record['outputs']['volume']['profile'] == 'segy/1'
    assert record['outputs']['volume']['declared'] == {'crs': 'EPSG:23031', 'z_domain': 'time'}
    made = (tmp_path / 'out' / record['outputs']['volume']['file']).read_bytes()
    assert made == zgy.read(FIXTURES / 'small-32bit.zgy', **SET).bytes


def test_the_packaged_procedure_shows_a_refusal_sentence(tmp_path):
    from ophiolite import procedures
    zgy_api = api()
    if zgy_api is None: return
    feet = tmp_path / 'feet.zgy'
    with zgy_api.ZgyWriter(str(feet), size=(3, 4, 5), datatype=zgy_api.SampleDataType.float, zunitdim=zgy_api.UnitDimension.time, zunitname='ms',
                           zunitfactor=0.001, zstart=0.0, zinc=4.0, hunitdim=zgy_api.UnitDimension.length, hunitname='ft', hunitfactor=0.3048,
                           annotstart=(1, 1), annotinc=(1, 1), corners=((0, 0), (20, 0), (0, 30), (20, 30))) as writer:
        writer.write((0, 0, 0), numpy.zeros((3, 4, 5), dtype=numpy.float32))
    with pytest.raises(procedures.NotRun) as stop: run_packaged(tmp_path, feet, ['crs=EPSG:23031', 'z_domain=time', 'horizontal_unit=m'])
    assert stop.value.code == 'procedure-stopped' and 'feet' in str(stop.value) and 'factor 0.3048' in str(stop.value)


def test_the_packaged_procedure_requires_pyzgy(tmp_path, monkeypatch):
    import json
    import shutil
    from ophiolite import _requires, procedures
    unmet = _requires.unmet
    monkeypatch.setattr(_requires, 'unmet', lambda texts: [m for m in unmet(['pyzgy>=999']) if texts])  # pyzgy reported missing
    with pytest.raises(procedures.NotRun) as stop: run_packaged(tmp_path, FIXTURES / 'small-32bit.zgy')
    assert stop.value.code == 'requires-missing' and 'pyzgy' in str(stop.value)
    copy = tmp_path / 'read-zgy'
    shutil.copytree(zgy.PROCEDURE, copy, ignore=shutil.ignore_patterns('__pycache__'))
    manifest = json.loads((copy / 'procedure.json').read_text()); manifest['requires'] = []
    (copy / 'procedure.json').write_text(json.dumps(manifest))
    with pytest.raises(procedures.NotRun) as started: run_packaged(tmp_path, FIXTURES / 'small-32bit.zgy', folder=copy, output='copy')
    assert started.value.code != 'requires-missing'  # the mutation: without `requires`, the run starts


# ---------------------------------------------------------------- 10: rule 6, and the rights record

def test_segyio_reads_every_output_back(tmp_path):
    segyio = oracle('segyio')
    if segyio is None or api() is None: return
    outputs = {'real': zgy.read(FIXTURES / 'small-32bit.zgy', **SET), 'translated': zgy.read(FIXTURES / 'small-32bit_translated.zgy', **SET),
               'depth': converted(Cube(zunitdim='length', zunitname='m', zunitfactor=1.0, zinc=5.0), z_domain='depth'),
               'scaled': converted(Cube(corners=((0.0, 0.0), (0.5, 0.0), (0.0, 0.75), (0.5, 0.75))))}
    for name, written in outputs.items():
        path = tmp_path / (name + '.sgy'); path.write_bytes(written.bytes)
        expected = segy(written.bytes)
        with segyio.open(str(path), iline=189, xline=193) as f:
            assert sorted((il, xl) for il in f.ilines for xl in f.xlines) == sorted(expected), name
            for il in f.ilines:
                for xl, trace in zip(f.xlines, f.iline[il]):
                    assert list(map(float, trace)) == expected[(il, xl)][3], (name, il, xl)
            headers = {(h[segyio.TraceField.INLINE_3D], h[segyio.TraceField.CROSSLINE_3D]): (h[segyio.TraceField.CDP_X], h[segyio.TraceField.CDP_Y], h[segyio.TraceField.SourceGroupScalar]) for h in f.header}
            assert headers == {key: value[:3] for key, value in expected.items()}, name
# The rights record (Integration docs/release/rights/e123sz-pyzgy-test-cubes-2026-10.json) is not read here: SDK tests
# stay inside the SDK (tools/test_sdk_tests_stay_in_tree.py). Its hashes reach the release through the inventory, and
# every cube's bytes are pinned by its PROVENANCE row (tests/test_public_inputs.py).
