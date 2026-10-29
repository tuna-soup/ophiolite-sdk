"""E119a slice 2 (C3 test 1, frozen): the SDK's vertical depth and minimum curvature give the numbers they gave before they
were re-pointed to the one geometry module (contracts/geometry/v1/trajectory.py), within 1e-9 m, and everything else
(refusal sentences, None outside the survey, `beyond`, `notes`, measured depths) exactly.

The oracle was computed by the SDK code at the parent commit and committed before the re-point:
`tests/fixtures/frozen_positions.json` holds every `test_transform.py` case on synthetic surveys, the dogleg cases at
179.89, 179.9 and 179.95 degrees (4-13: the old APIs keep today's behaviour, no new refusal), and
`minimum_curvature` cases. HON-GT-01 (NLOG data, `fixtures/e64`) is frozen below as literals, as `test_transform.py`
keeps its own literals, so the fixture carries no third-party numbers."""
import json
import math
from pathlib import Path

import pytest

from ophiolite.errors import Refused
from ophiolite.transform import vertical_depth
from ophiolite.typed import Trajectory, minimum_curvature

HERE = Path(__file__).parent
FROZEN = json.loads((HERE / 'fixtures/frozen_positions.json').read_text())
TOLERANCE = 1e-9


def same(found, expected, where='result'):
    """Numbers within TOLERANCE metres, everything else (structure, None, text, counts) exactly."""
    if isinstance(expected, float) and not isinstance(found, bool) and isinstance(found, (int, float)):
        assert math.isfinite(found) and abs(found - expected) <= TOLERANCE, (where, found, expected)
    elif isinstance(expected, dict):
        assert isinstance(found, dict) and set(found) == set(expected), (where, found, expected)
        for key in expected: same(found[key], expected[key], where + '.' + key)
    elif isinstance(expected, list):
        assert isinstance(found, (list, tuple)) and len(found) == len(expected), (where, found, expected)
        for n, (a, b) in enumerate(zip(found, expected)): same(a, b, where + '[' + str(n) + ']')
    else:
        assert found == expected and type(found) is type(expected), (where, found, expected)


def run(case):
    try:
        if case['call'] == 'vertical_depth': return {'result': vertical_depth(case['stations'], case['mds'], **case['options'])}
        return {'result': minimum_curvature(case['stations'])}
    except Refused as error: return {'refused': str(error)}


@pytest.mark.parametrize('case', FROZEN['cases'], ids=[c['call'] + ': ' + c['name'] for c in FROZEN['cases']])
def test_every_frozen_case_gives_the_parent_commit_answer(case):
    expected = {k: case[k] for k in ('result', 'refused') if k in case}
    same(run(case), expected)


def test_the_fixture_covers_the_transform_cases_and_the_three_doglegs():
    names = {c['name'] for c in FROZEN['cases']}
    assert {'dogleg 179.89 degrees', 'dogleg 179.9 degrees', 'dogleg 179.95 degrees'} <= names
    assert sum(c['call'] == 'vertical_depth' for c in FROZEN['cases']) == 14 and sum('refused' in c for c in FROZEN['cases']) == 6


HON = json.loads((HERE / 'fixtures/e64/HON-GT-01_dirsurvey.json').read_text())['dirSurveys'][0]['dirSurveyPoints']
TOPS = [1831.00, 2435.95, 2557.90, 3135.60, 3240, 3241]
HON_CALCULATED = [1759.01667522013, 2261.491016983244, 2364.170757533128, 2855.6626168821344, 2943.9606663077902, None]
HON_FILE = [1759.0113090909092, 2261.458605660377, 2364.1826171234247, 2855.6488892026937, 2943.961, None]
HON_MINIMUM_CURVATURE = [  # (md, dtvd, dnorth, deast) per station, at the parent commit
    (0, 0.0, 0.0, 0.0),
    (1082.1, 1082.060307911213, -0.5598997169783781, -8.006938989735218),
    (1121, 1120.9589768958056, -0.6868389993369263, -8.190367411407127),
    (1148.5, 1148.4575688112366, -0.5240276015201338, -8.250892999042994),
    (1175.5, 1175.4313632876826, 0.4576431777801311, -8.825674737488448),
    (1202.5, 1202.3238049261024, 2.5019053827623403, -10.042087981467212),
    (1230, 1229.543305685909, 5.934573846456319, -11.867400622201988),
    (1257, 1256.0258134188093, 10.59375595753314, -14.281643863652077),
    (1284, 1282.2746819599045, 16.041345860230443, -17.481017096978558),
    (1311.5, 1308.7711443691228, 22.135596148746092, -21.598439413746462),
    (1339, 1334.958583845314, 28.9192462937012, -26.53129522410793),
    (1366, 1360.270304106961, 36.54528961290307, -32.01025491716073),
    (1393, 1385.131225184881, 45.16545486517427, -38.053043350127666),
    (1420.5, 1409.9960908332794, 54.817323749237865, -44.74156312181282),
    (1447.5, 1433.958278766974, 65.00519490734338, -51.878422044786525),
    (1474.5, 1457.4249556038615, 75.84600167972678, -59.66906462513932),
    (1502, 1480.8657776855553, 87.56312647491681, -68.00209490578845),
    (1528.5, 1503.2503976259768, 99.2200149052907, -76.08257607846818),
    (1556, 1526.4913592340588, 111.26948030844137, -84.50352848031602),
    (1583, 1549.3209752165926, 123.00901823935475, -92.86959871843834),
    (1610, 1572.1719412305802, 134.68307513989743, -101.2688152077696),
    (1637.5, 1595.5136096030587, 146.49152198084923, -109.75265198694893),
    (1667.5, 1621.0379261560915, 159.3149947361281, -118.92140786101704),
    (1694.5, 1644.085067153666, 170.69408126685116, -127.18826663632014),
    (1722, 1667.5702673910282, 182.2689148349498, -135.59747313109872),
    (1749, 1690.443383114633, 193.94519163597386, -143.93154701957596),
    (1776, 1713.082350009941, 205.9984367084072, -152.3687218086804),
    (1803, 1735.619347781132, 218.25081378739768, -160.7926324642977),
    (1830, 1758.1796468905027, 230.50024024440438, -169.15815741402452),
    (1857.5, 1781.0406268164693, 243.14817179894743, -177.73872906343087),
    (1884.5, 1803.3360019319991, 255.7889477432793, -186.23144128707014),
    (1911, 1825.1833969596964, 268.17962870178366, -194.6814486757124),
    (1924.5, 1836.2594690225887, 274.5026731433554, -199.10736539021943),
    (1952, 1858.7614382304157, 287.48852224272736, -208.12268548346609),
    (1979, 1880.8907149449044, 300.2156668884798, -216.9154311418632),
    (2020, 1914.6210114542305, 319.39179518729156, -230.1644048290132),
    (2047, 1936.927046499984, 331.9933157377973, -238.68715876875174),
    (2074, 1959.3255750248445, 344.48884267807705, -247.12299378875477),
    (2101, 1981.805382027932, 356.8898959310601, -255.48170327782424),
    (2128, 2004.3656811373025, 369.2534990756642, -263.6775420691167),
    (2155.5, 2027.4239060571194, 381.7252288634596, -271.9854791351563),
    (2182.5, 2050.051279060745, 393.95349933810706, -280.19943830426115),
    (2209.5, 2072.4849019901135, 406.39196396456094, -288.62511344551666),
    (2237, 2095.1687621271917, 419.25700648364307, -297.3533585836087),
    (2263.5, 2117.049985256972, 431.60758686832156, -305.7748699053388),
    (2291, 2139.851194972741, 444.22268970746217, -314.5617167234058),
    (2318, 2162.319176070133, 456.4757937474007, -323.1669843423268),
    (2345, 2184.8677921185345, 468.635184841804, -331.6937386988075),
    (2372, 2207.506744929545, 480.6881976955593, -340.13183097644446),
    (2399.5, 2230.65603125386, 492.8812036214379, -348.59863364237265),
    (2426.5, 2253.495674324508, 504.70910408633915, -356.81126096799625),
    (2453, 2275.8252769149685, 516.4050474854829, -364.9856471337942),
    (2500.12, 2315.359045608542, 537.4444575088502, -379.63864820718163),
    (2550.11, 2357.564359600712, 559.4532809036743, -394.91240284463845),
    (2600.1, 2400.0369102133036, 581.2420846226918, -409.75500312885924),
    (2650.08, 2442.5259895238187, 603.120155977478, -424.3845346739496),
    (2700.07, 2484.9937855526446, 624.9759233464804, -439.14277967512453),
    (2750.06, 2527.5281846414837, 646.6160421343278, -454.02650052644174),
    (2800.05, 2570.126675377919, 668.0271195582402, -469.0573469829961),
    (2850.03, 2612.7257775805056, 689.2576689593569, -484.3076987371203),
    (2900.02, 2655.3380942192557, 710.281005872203, -499.83813472891177),
    (2950.01, 2697.9687556411664, 731.0073078251415, -515.7134889920577),
    (3000.15, 2740.692884710105, 751.568739159549, -532.0193979815015),
    (3050.13, 2783.166155674409, 771.9377155961066, -548.7256128987244),
    (3100.12, 2825.5832430390537, 792.1696824963104, -565.7683036643115),
    (3146.15, 2864.5891102408723, 810.8809001996106, -581.4902869114267),
    (3240, 2943.9606663077902, 849.3954614213228, -613.499772402685),
]


def hon_gt_01():
    stations = [{'md': p['ahDepth'], 'inclination': p['devAngle'], 'azimuth': p['azimuth'], 'tvd': p['tvDepth']} for p in HON]
    return Trajectory({}, {'context': {'type': 'trajectory', 'depth_unit': 'm', 'depth_datum': 'Rotary Table'}, 'stations': stations}, None)


def test_hon_gt_01_through_the_trajectory_is_unchanged():
    survey = hon_gt_01()
    same(survey.vertical_depth(TOPS), HON_CALCULATED)
    same(survey.vertical_depth(TOPS, source='file'), HON_FILE)
    same([[r['md'], r['dtvd'], r['dnorth'], r['deast']] for r in survey.minimum_curvature()], [list(r) for r in HON_MINIMUM_CURVATURE])


# C3 test 2 (delegation, 3-16): the module's functions substituted with ones returning distinctive literals; the SDK's
# results must be those literals, at stations and at an interior depth (mutation: keep a local computation, and the
# numbers are the survey's own instead of the substitutes').

STATIONS = [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0}, {'md': 100.0, 'inclination': 30.0, 'azimuth': 40.0},
            {'md': 200.0, 'inclination': 45.0, 'azimuth': 80.0}]
KNOTS = [(0.0, 0.0, 0.0), (1.234567, 2.345678, 91.111111), (7.654321, 8.765432, 177.777777)]


def substitute(monkeypatch):
    from ophiolite import geometry
    calls = []

    def minimum_curvature(stations):
        calls.append(('minimum_curvature', [s['md'] for s in stations])); return list(KNOTS)

    def interpolate(stations, mds, limit=True):
        calls.append(('interpolate', [s['md'] for s in stations], list(mds), limit))
        return [None if m < 0 or m > 200 else (0.0, 0.0, 1000.0 + m / 1000) for m in mds]
    monkeypatch.setattr(geometry, 'minimum_curvature', minimum_curvature)
    monkeypatch.setattr(geometry, 'interpolate', interpolate)
    return calls


def test_minimum_curvature_returns_the_modules_answer(monkeypatch):
    calls = substitute(monkeypatch)
    survey = Trajectory({}, {'context': {'type': 'trajectory', 'depth_unit': 'm'}, 'stations': STATIONS}, None)
    assert survey.minimum_curvature() == [{'md': s['md'], 'dtvd': v, 'dnorth': n, 'deast': e} for s, (e, n, v) in zip(STATIONS, KNOTS)]
    assert calls == [('minimum_curvature', [0.0, 100.0, 200.0])]


def test_vertical_depth_returns_the_modules_answer_at_stations_and_between(monkeypatch):
    calls = substitute(monkeypatch)
    out = vertical_depth(STATIONS, [0, 50, 137.5, 200, 250], origin_tvd=10.0)
    assert out['calculated'] == [1010.0, 1010.05, 1010.1375, 1010.2, None] and out['beyond'] == 1
    assert calls == [('interpolate', [0.0, 100.0, 200.0], [0, 50, 137.5, 200, 250], False)]  # no dogleg limit on the old API (4-13)
    survey = Trajectory({}, {'context': {'type': 'trajectory', 'depth_unit': 'm'}, 'stations': STATIONS}, None)
    assert survey.vertical_depth([50]) == [1000.05]
