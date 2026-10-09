"""E57: a time-depth table read, framed and written offline. The expected values are the literals of the contract
fixture (`contracts/assets/v1/fixtures/time-depth.original`, the first three pairs of PRW-06's NLOG workbook), not this
module's output; PRW-06 whole (1,906 pairs) is read through the gateway in gateway/test_time_depth.py."""
import json
import math
from importlib.resources import files

import pytest

from ophiolite import _core
from ophiolite.errors import ValidationFailed
from ophiolite.typed import CLASSES, TYPES, TimeDepth
from ophiolite.writers import write_time_depth

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
ORIGINAL = FIXTURES.joinpath('time-depth.original').read_bytes()
DECLARED = dict(depth_type='tvd', depth_unit='m', time_kind='two-way', time_unit='ms')
PAIRS = [(0, 0, 0), (0.96, 1, 1913.18), (1.91, 2, 1913.18)]


def fixture():
    return _core.typed_result(json.loads(FIXTURES.joinpath('time-depth.json').read_bytes()), FIXTURES.joinpath('time-depth-data.json').read_bytes(), ORIGINAL)


def refused(call):
    with pytest.raises(ValidationFailed) as error: call()
    return error.value.violations[0]


def test_read_offline_and_registered():
    table = fixture()
    assert isinstance(table, TimeDepth) and 'time-depth' in TYPES and CLASSES['time-depth'] is TimeDepth
    assert table.pairs == [(0, 0, 0), (0.96, 1, 1913.18), (1.91, 2, 1913.18)] and len(table) == 3 and table.original == ORIGINAL
    assert repr(table) == '<TimeDepth 3 pairs, tvd m depth, two-way ms time>'
    assert (table.context['datum'], table.context['seismic_reference_elevation']) == ('unknown', None)


def test_to_frame_literal():
    pytest.importorskip('pandas')
    frame = fixture().to_frame()
    assert frame.shape == (3, 3) and list(frame.columns) == ['depth', 'time', 'velocity'] and str(frame['velocity'].dtype) == 'Float64'
    assert frame.iloc[1].tolist() == [0.96, 1.0, 1913.18]
    table = fixture()
    gaps = TimeDepth(table.descriptor, {**table.data, 'velocity': [None, 1913.18, 1913.18]}, table.original)
    assert str(gaps.to_frame()['velocity'].iloc[0]) == '<NA>'  # a missing velocity stays missing, never zero
    without = TimeDepth(table.descriptor, {**table.data, 'velocity': None}, table.original)
    assert without.to_frame()['velocity'].isna().all() and without.pairs[2] == (1.91, 2, None)


def test_write_round_trip():
    written = write_time_depth(PAIRS, **DECLARED, filename='prw06.csv')
    assert written.bytes == ORIGINAL and (written.profile, written.filename) == ('time-depth-csv/1', 'prw06.csv')
    assert written.declared == DECLARED
    # the Connectors reader reads a written table back through the gateway: gateway/test_time_depth.py (the unit lane has no Connectors)
    unknown = write_time_depth(PAIRS, depth_type='unknown', depth_unit='unknown', time_kind='two-way', time_unit='ms', datum='MSL')
    assert unknown.declared == {'time_kind': 'two-way', 'time_unit': 'ms', 'datum': 'MSL'}  # "unknown" stays unknown: not declared
    assert write_time_depth([(0, 0), (1.5, 2)], **DECLARED).bytes == b'depth,time\r\n0,0\r\n1.5,2\r\n'  # no velocity column


def test_write_refusals():
    assert refused(lambda: write_time_depth(PAIRS, **{**DECLARED, 'time_unit': None})) == 'Declare the time unit (write "unknown" when it is not known); nothing is inferred.'
    assert refused(lambda: write_time_depth(PAIRS, **{**DECLARED, 'depth_type': 'kb'})) == 'Choose the depth type from: md, tvd, tvdss, unknown.'
    assert refused(lambda: write_time_depth([(0, 0), (1, math.nan)], **DECLARED)) == 'A time must be finite.'
    assert refused(lambda: write_time_depth([(0, 0), (1, 2), (2, 2)], **DECLARED)) == 'Time of pair 3 does not increase; pairs must be in strictly increasing time.'
    assert refused(lambda: write_time_depth([(0, 0), (0, 2)], **DECLARED)) == 'Depth of pair 2 does not increase; pairs must be in strictly increasing depth.'
    assert refused(lambda: write_time_depth([(0, 0)], **DECLARED)) == 'Write at least two pairs.'
    assert refused(lambda: write_time_depth(PAIRS, **DECLARED, datum='MSL, approx')) == 'The datum cannot contain commas, quotes or line breaks.'


def test_numeric_declaration_is_canonical_decimal_text():
    for value, text in ((12.5, '12.5'), (12, '12'), (-0.0, '0'), (1e-05, '0.00001'), (1.5e16, '15000000000000000')):
        assert write_time_depth(PAIRS, **DECLARED, seismic_reference_elevation=value).declared['seismic_reference_elevation'] == text
    assert refused(lambda: write_time_depth(PAIRS, **DECLARED, seismic_reference_elevation=math.inf)) == 'The seismic reference elevation must be finite.'
