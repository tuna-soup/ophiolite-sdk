"""E52 C4: ophiolite.petrophysics held to literals (never to itself): each method's own value at index 0.5, the table's
reference vectors, the HON-GT-01 excerpt cases read by this test's own parser, type 7 percentiles, the halved index at
the ends of the float range, and the method record the server records for the same calculation."""
import io
import math
import random
from importlib.resources import files

import pytest
from ophiolite import petrophysics as pp
from ophiolite.errors import ValidationFailed
from ophiolite.writers import write_curves

AT_HALF = {'linear': 0.5, 'larionov-tertiary': 0.216215, 'larionov-older': 0.33, 'clavier': 0.307161, 'steiber': 0.25}
HON = files('ophiolite').joinpath('contracts/scientific/v1/fixtures/hon-gt-01-gamma-ray-excerpt.las').read_bytes()


def own_rows(raw):
    """This test's own LAS reading: the NULL marker and the ~A rows (depth, GR) of the excerpt."""
    lines = raw.decode('ascii').splitlines()
    null = float(next(line for line in lines if line.split('.')[0].strip() == 'NULL').split(':')[0].split('.', 1)[1])
    start = next(i for i, line in enumerate(lines) if line.startswith('~A'))
    rows = [[float(v) for v in line.split()] for line in lines[start + 1:] if line.strip()]
    return [(round(d, 3), None if g == null else g) for d, g in rows]


@pytest.mark.parametrize('method', sorted(AT_HALF))
def test_each_method_equals_its_own_literal_at_half(method):
    assert round(pp.shale_volume([90], method=method, clean=30, shale=150)[0], 6) == AT_HALF[method]
    reference = next(m['reference'] for m in pp.TABLE['methods'] if m['id'] == method)
    for x, y in reference:
        assert abs(pp.shale_volume([30 + 120 * x], method=method, clean=30, shale=150)[0] - y) < 1e-12, (method, x)


def test_the_constants_and_the_digest_come_from_the_packaged_table():
    assert pp.CONSTANTS == {'linear': {}, 'larionov-tertiary': {'a': 0.083, 'b': 3.7}, 'larionov-older': {'a': 0.33, 'b': 2},
                            'clavier': {'a': 1.7, 'b': 3.38, 'c': 0.7}, 'steiber': {'a': 3, 'b': 2}}
    assert pp.TABLE_DIGEST == 'f8984571cff3e1a55b0ccb0ba5ee532fd4537b73d66fdfa04612379f4f158042'  # the server's digest at Platform fbcb593
    assert pp.INPUT_UNITS == ('gAPI', 'API') and pp.OUTPUT['curve'] == 'VSH'


def test_hon_excerpt_reproduces_the_table_literals():
    rows = own_rows(HON)
    assert len(rows) == pp.TABLE['hon_cases']['rows'] == 1551
    depth, gr = [d for d, _ in rows], [g for _, g in rows]
    for method in pp.METHODS:
        vsh = pp.shale_volume(gr, method=method, clean=30, shale=150)
        for interval in pp.TABLE['hon_cases']['intervals']:
            inside = [v for d, v in zip(depth, vsh) if v is not None and interval['top'] <= d < interval['base']]
            assert len(inside) == interval['n'] and round(math.fsum(inside) / len(inside), 6) == interval['means'][method], (method, interval['name'])
    case = pp.TABLE['hon_cases']['percentile_case']
    picks = pp.picks_from_percentiles(depth, gr, case['top'], case['base'], depth_unit='M')
    assert (picks['samples'], round(picks['clean'], 6), round(picks['shale'], 6)) == (1534, 30.936205, 150.84451)
    for method in ('linear', 'larionov-older'):
        vsh = pp.shale_volume(gr, method=method, clean=picks['clean'], shale=picks['shale'])
        for interval in pp.TABLE['hon_cases']['intervals']:
            inside = [v for d, v in zip(depth, vsh) if v is not None and interval['top'] <= d < interval['base']]
            assert round(math.fsum(inside) / len(inside), 6) == case['means'][interval['name']][method]
    rodenrijs = pp.TABLE['hon_cases']['intervals'][0]
    assert pp.picks_from_percentiles(depth, gr, rodenrijs['top'], rodenrijs['base'])['samples'] == 910  # 911 with the base included


def test_percentiles_are_type_seven_like_numpy():
    numpy = pytest.importorskip('numpy')
    rng = random.Random(52)
    values = [rng.uniform(-50, 300) for _ in range(200)]
    depth = list(range(200))
    for low, high in ((5, 95), (0, 100), (12.5, 87.5), (33, 34)):
        picks = pp.picks_from_percentiles(depth, values, 0, 200, low, high)
        assert abs(picks['clean'] - float(numpy.percentile(values, low))) < 1e-9 and abs(picks['shale'] - float(numpy.percentile(values, high))) < 1e-9


def test_missing_and_zero_and_the_refusals():
    assert pp.shale_volume([None, 0, 30, 150, 200], method='linear', clean=30, shale=150) == [None, 0.0, 0.0, 1.0, 1.0]
    assert pp.shale_volume([None, 0.0], method='steiber', clean=-10, shale=10) == [None, 0.5 / 2]
    for clean, shale in ((150, 30), (30, 30)):
        with pytest.raises(ValidationFailed, match='The shale value must be higher than the clean value.'): pp.shale_volume([1], method='linear', clean=clean, shale=shale)
    for bad in (math.nan, math.inf, 'x'):
        with pytest.raises(ValidationFailed, match='The clean and shale values must be numbers.'): pp.typed_picks(bad, 150)
    with pytest.raises(ValidationFailed, match='is not a shale-volume method'): pp.shale_volume([1], method='tertiary', clean=0, shale=1)
    with pytest.raises(ValidationFailed, match='The base depth must be below the top depth.'): pp.picks_from_percentiles([1, 2], [1, 2], 2, 2)
    with pytest.raises(ValidationFailed, match='The low percentile must be below the high percentile'): pp.picks_from_percentiles([1, 2], [1, 2], 0, 3, 95, 5)
    with pytest.raises(ValidationFailed, match='There are no gamma-ray samples between 5 and 6 M. Choose a range inside the log.'):
        pp.picks_from_percentiles([1, 2], [1, 2], 5, 6, depth_unit='M')
    with pytest.raises(ValidationFailed, match='The shale value must be higher'): pp.picks_from_percentiles([1, 2], [7, 7], 0, 3)


def test_extreme_picks_do_not_overflow():
    huge = 1e308
    assert pp.gamma_ray_index(0.0, -huge, huge) == 0.5
    assert min(1.0, max(0.0, (0 - -huge) / (huge - -huge))) == 0.0  # the plain form overflows to inf, so 0.0
    assert {m: round(pp.shale_volume([0.0], method=m, clean=-huge, shale=huge)[0], 6) for m in AT_HALF} == AT_HALF


def test_the_method_record_is_the_servers():
    picks = pp.picks_from_percentiles([100, 101, 102, 103, 104], [0, 10, None, 30, 40], 100, 105)
    assert pp.shale_volume_method(method='linear', picks=picks) == {
        'name': 'ophiolite.shale-volume', 'declared': True, 'library': 'ophiolite', 'version': 'ophiolite.shale-volume-methods/1',
        'parameters': {'method': 'linear', 'picks': {'how': 'percentile', 'clean': 1.5, 'shale': 38.5, 'top': 100.0, 'base': 105.0, 'low': 5.0, 'high': 95.0, 'samples': 4},
                       'clip': [0, 1], 'table': 'f8984571cff3e1a55b0ccb0ba5ee532fd4537b73d66fdfa04612379f4f158042',
                       'inputs': {'GR': {'unit': 'gAPI', 'quantity': 'Gamma Ray', 'basis': 'confirmed'}},
                       'outputs': {'VSH': {'unit': 'V/V', 'quantity': 'Shale Volume Fraction'}}}}
    with pytest.raises(ValidationFailed, match='Porosity is not a quantity Ophiolite lists.'): pp.shale_volume_method(method='linear', picks=picks, quantity='Porosity')
    with pytest.raises(ValidationFailed, match='Shale volume is calculated from a gamma-ray curve.'): pp.shale_volume_method(method='linear', picks=picks, quantity='Bulk Density')
    with pytest.raises(ValidationFailed, match='Confirm that this curve is a gamma ray.'): pp.shale_volume_method(method='linear', picks=picks, quantity=None)
    with pytest.raises(ValidationFailed, match="unit is not stated as gAPI"): pp.shale_volume_method(method='linear', picks=picks, unit='us/ft')
    with pytest.raises(ValidationFailed, match='VCL is not a curve of the calculated file.'):
        pp.shale_volume_method(method='linear', picks=picks, outputs={'VCL': {'unit': 'V/V', 'quantity': 'Shale Volume Fraction'}})
    with pytest.raises(ValidationFailed, match='Clay is not a quantity Ophiolite lists.'):
        pp.shale_volume_method(method='linear', picks=picks, outputs={'VSH': {'unit': 'V/V', 'quantity': 'Clay'}})


def test_the_record_is_the_servers_sentence_and_lasio_reads_the_file():
    typed = pp.typed_picks(30, 150)
    assert pp.calculation_record('larionov-older', typed, 'gAPI') == ('Shale volume from gamma ray: Larionov, older rocks; clean 30 gAPI and shale 150 gAPI, '
                                                                     'typed; clipped to 0-1; method table f8984571cff3.')
    percentile = pp.picks_from_percentiles([100, 101, 102, 103, 104], [0, 10, None, 30, 40], 100, 105)
    assert pp.calculation_record('linear', percentile, 'gAPI', 'M') == ('Shale volume from gamma ray: Linear (simple); clean 1.5 gAPI and shale 38.5 gAPI, '
                                                                       'the 5th and 95th percentile between 100 and 105 M; clipped to 0-1; method table f8984571cff3.')
    lasio = pytest.importorskip('lasio')
    values = pp.shale_volume([0, 10, None, 30, 40], method='linear', clean=1.5, shale=38.5)
    record = pp.calculation_record('linear', percentile, 'gAPI', 'M')
    written = write_curves([100, 101, 102, 103, 104], {'VSH': ('V/V', values)}, depth_unit='M', notes=[record])
    read = lasio.read(io.StringIO(written.bytes.decode('ascii')))
    assert [None if math.isnan(v) else v for v in read['VSH']] == values and read.curves['VSH'].unit == 'V/V'
    assert read.other.strip() == record and (' ' + record + '\n').encode() in written.bytes
    for bad in ('two\nlines', '~A injected', '', 'naïve'):
        with pytest.raises(ValidationFailed, match='Each note is one line'): write_curves([1], {'VSH': ('V/V', [0.5])}, depth_unit='M', notes=[bad])
