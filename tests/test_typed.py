"""E11: typed reads verify exactly and compute only on request."""
import copy
import hashlib
import json
import math
from importlib.resources import files
import pytest
from ophiolite import _core, validate
from ophiolite.errors import VerificationFailed, Refused
from ophiolite.typed import WellTops, Trajectory, GridSurface, minimum_curvature

FIX = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load(name):
    return json.loads(FIX.joinpath(f'{name}.json').read_bytes()), FIX.joinpath(f'{name}-data.json').read_bytes(), FIX.joinpath(f'{name}.original').read_bytes()


@pytest.mark.parametrize('name,kind', [('tops', WellTops), ('trajectory', Trajectory), ('grid', GridSurface)])
def test_fixtures_read_as_typed_objects(name, kind):
    descriptor, body, original = load(name)
    result = _core.typed_result(descriptor, body, original)
    assert isinstance(result, kind) and result.original == original and result._wire_data_bytes == body
    assert result.relationships == {'well_log': None}


def test_values_nulls_and_cell_coordinates():
    tops = _core.typed_result(*load('tops'))
    assert [(t['name'], t['md'], t['tvd']) for t in tops.tops] == [('Top Chalk', 100.5, None), ('Base Chalk', 103.0, 102.9)]
    grid = _core.typed_result(*load('grid'))
    assert grid.values == [1.0, 0.0, None, 4.0, 5.0, 6.0]
    assert grid.cell_center(0, 0) == (1012.5, 5037.5) and grid.cell_center(1, 2) == (1062.5, 5012.5)
    array = grid.to_numpy(); assert array.shape == (2, 3) and array[0, 1] == 0.0 and math.isnan(array[0, 2])
    frame = grid.to_frame(); assert frame['value'].isna().sum() == 1 and list(frame['x'][:3]) == [1012.5, 1037.5, 1062.5]
    with pytest.raises(Refused): grid.cell_center(2, 0)


def test_minimum_curvature_is_explicit_and_refuses_missing_angles():
    trajectory = _core.typed_result(*load('trajectory'))
    with pytest.raises(Refused, match='every angle'): trajectory.minimum_curvature()  # the fixture's last station has no angles
    out = minimum_curvature(trajectory.stations[:2])
    theta = math.radians(10); radius = 100 / theta   # circular arc, 0→10° over 100
    assert out[1]['dtvd'] == pytest.approx(radius * math.sin(theta), abs=1e-9) and out[1]['dnorth'] == pytest.approx(radius * (1 - math.cos(theta)), abs=1e-9)
    stations = [{'md': 0, 'inclination': 10, 'azimuth': 0}, {'md': 100, 'inclination': 10, 'azimuth': 90}]
    assert minimum_curvature(stations)[1]['dtvd'] == pytest.approx(98.9812, abs=1e-3)  # same value as the Connectors reader test
    assert trajectory.to_frame()['tvd'].isna().all()  # the provided TVD column is not filled by the calculation


def rehash(descriptor, body):
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(body), hashlib.sha256(body).hexdigest()


def test_tampering_and_mixing_are_refused():
    descriptor, body, original = load('trajectory')
    with pytest.raises(VerificationFailed): _core.typed_result(descriptor, body[:-1] + b' ', original)          # digest
    with pytest.raises(VerificationFailed): _core.typed_result(descriptor, body, original + b'x')                # artifact
    payload = json.loads(body); payload['context']['azimuth_reference'] = 'true-north'
    edited = json.dumps(payload).encode(); d = copy.deepcopy(descriptor); rehash(d, edited)
    with pytest.raises(VerificationFailed, match='disagrees'): _core.typed_result(d, edited, original)             # context
    tops, _, _ = load('tops'); mixed = copy.deepcopy(descriptor); mixed['scientific'] = tops['scientific']
    with pytest.raises(VerificationFailed): validate.typed_pair(mixed, body)
    with pytest.raises(VerificationFailed, match='read_data'):
        _core.verify_descriptor(descriptor, descriptor['project_id'], descriptor['asset_id'], descriptor['revision'], 'GR')
    las = json.loads(FIX.joinpath('source.json').read_bytes())
    with pytest.raises(VerificationFailed, match='curves with read'):
        _core.verify_typed_descriptor(las, las['project_id'], las['asset_id'], las['revision'])
