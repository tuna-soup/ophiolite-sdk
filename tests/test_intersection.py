"""E119a slice 3 (C4): `ophiolite.intersection` finds every crossing of a bound member's trajectory with a grid surface
that it can prove, or names why not, through the one geometry module's snapshot.

The hand values come from `fixtures/well_geometry/closed_forms.py` (standard library, independent of the product: each
case states its closed form). The fixture files beside it and the contract's `fixtures/crossings.json` in the SDK's
snapshot are exactly what that file writes, so neither can drift from the closed forms. Every case runs here through
`intersection.crossings` with a `Bound` and the surface as `client.read_data` gives it; the contract's own tests 1 to
18, with their mutations, are the Platform's `test_trajectory_geometry.py`."""
import copy
import json
import sys
from pathlib import Path

import pytest

from ophiolite import geometry, intersection
from ophiolite.errors import Refused
from ophiolite.typed import GridSurface, Trajectory
from ophiolite.well_sets import Bound

HERE = Path(__file__).parent / 'fixtures' / 'well_geometry'
sys.path.insert(0, str(HERE))
_write, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # nothing is written into the fixtures (each file has a provenance row)
import closed_forms  # noqa: E402
sys.dont_write_bytecode = _write

CASES = json.loads((HERE / 'cases.json').read_text(encoding='utf-8'))['cases']
SNAPSHOT = geometry.CONTRACT.parent / 'fixtures' / 'crossings.json'
SEVEN = ['grazing', 'along-surface', 'uncertain', 'no-surface-data', 'ends-above', 'starts-below', 'no-trajectory']


def surface(name):
    data = json.loads((HERE / (name + '.json')).read_text(encoding='utf-8'))
    return GridSurface({}, data, None)


def bound(case, grid):
    trajectory = Trajectory({}, copy.deepcopy(case['trajectory']), None)
    member = {'well': 'w', 'wellbore': 'b', 'trajectory': {'asset_id': 't', 'revision': '0' * 64}, 'frame': case['frame']}
    placed = geometry.place(case['trajectory'], case['frame'], grid.context)
    assert placed['reason'] is None
    return Bound(0, member, trajectory, grid.context, placed)


def test_the_fixtures_are_what_the_closed_forms_write():
    texts = {path.name: text for path, text in closed_forms.files().items()}
    assert SNAPSHOT.read_text(encoding='utf-8') == texts.pop('crossings.json')
    for name, text in texts.items():
        assert (HERE / name).read_text(encoding='utf-8') == text, name
    assert sorted(p.name for p in HERE.glob('*.json')) == sorted(texts)


def test_the_closed_forms_are_literal():
    by = {c['name']: c for c in CASES}
    assert by['vertical, 30 m east of a node']['crossings'] == pytest.approx([1202.6246599057777], abs=1e-9)
    assert by['slant 30 degrees, azimuth 60']['crossings'] == pytest.approx([1449.0273805222844], abs=1e-9)
    assert by['build 10 degrees per 30 m, azimuth 120']['crossings'] == pytest.approx([1200.9535554759364], abs=1e-9)
    assert by['root at a grid corner on a first-interval end']['crossings'] == [1200.0]
    assert by['smooth near miss with its band edge at md 1203.37']['between'] == pytest.approx([1203.37, 1204.2644279363553], abs=1e-9)


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_every_analytic_case_through_the_sdk(case):
    grid = surface(case['surface'])
    result = intersection.crossings(bound(case, grid), grid)
    found = [c['md'] for c in result['crossings']]
    reasons = [r['reason'] for r in result['rows']]
    if case['name'] == 'roots 0.005 m apart':  # two crossings, or a row over both roots; never exactly one
        assert len(found) == 2 or any(r in ('grazing', 'uncertain') for r in reasons)
        return
    assert len(found) == len(case['crossings']) and all(abs(a - b) <= 0.01 for a, b in zip(found, case['crossings'])), (found, case['crossings'])
    assert all(c['high'] - c['low'] <= 0.01 for c in result['crossings'])
    assert reasons == case['reasons']
    if case['between'] is not None:
        assert result['rows'][0]['between'] == pytest.approx(case['between'], abs=0.001)


def test_nearest_picks_only_with_full_coverage():
    by = {c['name']: c for c in CASES}
    fold = by['fold: a slant through a crest']
    result = intersection.crossings(bound(fold, surface('fold')), surface('fold'))
    assert intersection.nearest(result, fold['crest_md'])['index'] == 0
    hole = by['path enters a hole']
    result = intersection.crossings(bound(hole, surface('hole')), surface('hole'))
    assert len(result['crossings']) == 1 and intersection.nearest(result, 1445) == {'index': None, 'crossing': None, 'reason': 'no-surface-data'}


def test_the_seven_reasons_and_a_member_without_a_trajectory():
    assert list(intersection.reasons()) == SEVEN
    result = intersection.crossings(None, surface('slope-5deg'))
    assert [r['reason'] for r in result['rows']] == ['no-trajectory'] and intersection.nearest(result, 0)['reason'] == 'no-trajectory'


def test_a_surface_the_member_cannot_be_placed_against_is_refused_in_a_sentence():
    case = CASES[0]
    grid = surface(case['surface'])
    other = copy.deepcopy(grid.data)
    other['context']['crs'] = 'EPSG:28992'
    with pytest.raises(Refused) as caught:
        intersection.crossings(bound(case, grid), other)
    assert caught.value.details == {'reason': 'geometry:crs_mismatch'} and "coordinate system is not the frame's" in str(caught.value)
    with pytest.raises(Refused, match='regular grid surface'):
        intersection.crossings(bound(case, grid), {'context': {'type': 'triangulated-surface'}, 'values': []})
    with pytest.raises(Refused, match='client.read_data'):
        intersection.crossings(bound(case, grid), [1, 2])
