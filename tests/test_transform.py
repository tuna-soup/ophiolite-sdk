"""E64 C5: vertical depth by minimum curvature with a stated origin. Expected values are geometry written as literals:
a quarter circle of radius 1000 m (minimum curvature is exact on a circular arc), a vertical hole, a slant at 60
degrees. The HON-GT-01 survey literals travel with the gateway test once its fixture is registered."""
import math

import pytest

from ophiolite.errors import Refused
from ophiolite.transform import vertical_depth

ARC = 1000 * math.pi / 2  # a quarter circle of radius 1000 m: inclination 0 at MD 0, 90 degrees at its end


def test_a_circular_build_is_exact_between_and_at_stations():
    stations = [{'md': 0, 'inclination': 0, 'azimuth': 45}, {'md': ARC, 'inclination': 90, 'azimuth': 45}]
    out = vertical_depth(stations, [0, 1000 * math.pi / 6, 1000 * math.pi / 4, ARC])
    assert out['calculated'] == pytest.approx([0.0, 500.0, 707.1067812, 1000.0], abs=1e-6)  # 1000 sin(theta)
    assert out['from_file'] == [None, None, None, None] and out['beyond'] == 0


def test_supplied_and_calculated_are_returned_apart():
    stations = [{'md': 0, 'inclination': 60, 'azimuth': 0, 'tvd': 0}, {'md': 100, 'inclination': 60, 'azimuth': 0, 'tvd': 49},
                {'md': 200, 'inclination': 60, 'azimuth': 0}]
    out = vertical_depth(stations, [50, 150, 250])
    assert out['calculated'][:2] == pytest.approx([25.0, 75.0]) and out['calculated'][2] is None  # never extrapolated
    assert out['from_file'] == [24.5, None, None]  # a station without its own depth is a gap
    assert out['beyond'] == 1


def test_the_origin_is_stated_never_assumed():
    deep = [{'md': 500, 'inclination': 0, 'azimuth': 0}, {'md': 600, 'inclination': 0, 'azimuth': 0}]
    with pytest.raises(Refused) as refused:
        vertical_depth(deep, [550])
    assert str(refused.value) == 'The survey starts at 500 m and gives no vertical depth there, so its starting depth is not known.'
    assert vertical_depth([dict(deep[0], tvd=480.0), deep[1]], [550])['calculated'] == pytest.approx([530.0])
    assert vertical_depth(deep, [550], origin_tvd=470.0)['calculated'] == pytest.approx([520.0])


def test_a_plateau_reversal_units_and_single_station():
    flat = [{'md': 0, 'inclination': 90, 'azimuth': 10, 'tvd': 10}, {'md': 50, 'inclination': 90, 'azimuth': 10, 'tvd': 9.5}]
    out = vertical_depth(flat, [0, 25, 50])
    assert out['calculated'] == pytest.approx([10.0, 10.0, 10.0])
    assert out['notes'] == ["The survey's vertical depth decreases between measured depth 0 and 50."]
    with pytest.raises(Refused) as refused:
        vertical_depth(flat, [10], survey_unit='m', log_unit='ft')
    assert str(refused.value) == 'The survey is in m and the log in ft; change one to match first.'
    with pytest.raises(Refused, match='^The survey has one station'):
        vertical_depth(flat[:1], [0])
    with pytest.raises(Refused, match='do not increase'):
        vertical_depth([flat[1], flat[0]], [0])
