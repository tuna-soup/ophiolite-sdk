"""E124 s1 (A1-3, R6, R7a): the three contracts A1 widens, as the SDK reads them. The released models (frozen verbatim in
`frozen/models_before_e124s1.py`) refuse a payload read from a RESQML package with the SDK's contract refusal, and the
regenerated models accept it. The generated models and the JSON schemas carry structure only: the reader/context pairing
and the mapping per contract are refused by the Platform model, not here."""
import copy
import importlib.util
import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from ophiolite import validate
from ophiolite.errors import VerificationFailed
from ophiolite.models import generated

_spec = importlib.util.spec_from_file_location('models_before_e124s1', Path(__file__).with_name('frozen') / 'models_before_e124s1.py')
before = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(before)

READER = {'reader': 'asset_connectors.resqml_package/1', 'parsing_policy': 'resqml-exact/1',
          'null_policy': 'NaN in the package is a missing value (null); nothing is filled in'}
SOURCE = {'authority': 'ophiolite:uploaded', 'key': 'a' * 64, 'revision': 'b' * 64, 'profile': 'resqml-epc/1'}
FIDELITY = {'status': 'assessed', 'preserved': ['Stations in package order'], 'losses': [], 'unknown_context': []}
TRAJECTORY = {'schema': 'ophiolite.trajectory/1', 'representation': 'normalized', 'source': SOURCE, 'source_sha256': 'c' * 64,
              'interpretation': {**READER, 'mapping': 'trajectory/1'},
              'context': {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'MSL',
                          'count': 2, 'missing_angle_count': 0, 'tvd_provided': True, 'md_range': [0.0, 109.0], 'fidelity': FIDELITY},
              'stations': [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': 0.0}, {'md': 109.0, 'inclination': 0.003868237062547547, 'azimuth': 180.0, 'tvd': 84.0}]}
WELL_PATH = {'schema': 'ophiolite.well-path/1', 'representation': 'normalized', 'source': SOURCE, 'source_sha256': 'c' * 64,
             'interpretation': {**READER, 'mapping': 'well-path/1'},
             'context': {'type': 'well-path', 'crs': 'EPSG:23031', 'xy_unit': 'm', 'depth_unit': 'm', 'md_reference': 'unknown', 'tvdss_datum': 'MSL',
                         'count': 2, 'md_range': [0.0, 109.0], 'tvdss_range': [0.0, 84.0], 'fidelity': FIDELITY},
             'stations': [{'md': 0.0, 'x': 437506.85546875, 'y': 6477887.470703125, 'tvdss': 0.0}, {'md': 109.0, 'x': 437506.85546875, 'y': 6477887.470703125, 'tvdss': 84.0}]}
HEADER = {'schema': 'ophiolite.curve-columns/1', 'representation': 'normalized', 'curve': 'KLOGH', 'unit': 'mD', 'source': SOURCE, 'source_sha256': 'c' * 64,
          'interpretation': {**READER, 'mapping': 'well-log/1'},
          'context': {'depth_index': 'md', 'depth_unit': 'm', 'depth_reference': 'not stated by the package; not inferred', 'depth_stored_as': 'hdf5',
                      'missing_value_policy': READER['null_policy']},
          'count': 7013, 'encoding': 'f64le'}
CASES = [('Trajectory', 'trajectory-schema.json', TRAJECTORY), ('WellPath', 'well-path-schema.json', WELL_PATH),
         ('CurveColumnsHeader', 'curve-columns-header-schema.json', HEADER)]
REFUSED = 'Scientific data does not satisfy the declared contract.'


def schema(name):
    return json.loads(files('ophiolite').joinpath('contracts/assets/v1/' + name).read_text())


@pytest.mark.parametrize('model,_,payload', CASES, ids=[c[0] for c in CASES])
def test_the_released_models_refuse_a_payload_read_from_a_resqml_package(model, _, payload):
    with pytest.raises(VerificationFailed) as refused:
        validate.model(getattr(before, model), payload)
    assert (str(refused.value), refused.value.code) == (REFUSED + ' No files were saved.', 'verification-failed')


@pytest.mark.parametrize('model,name,payload', CASES, ids=[c[0] for c in CASES])
def test_the_regenerated_models_and_the_schemas_accept_it(model, name, payload):
    assert validate.model(getattr(generated, model), payload).model_dump(by_alias=True, exclude_unset=True)['interpretation'] == payload['interpretation']
    jsonschema.Draft202012Validator(schema(name)).validate(payload)


def structural(payload):
    """Changes the structure itself states, each refused by the generated model and by the schema."""
    unknown = copy.deepcopy(payload); unknown['interpretation']['reader'] = 'asset_connectors.resqml_package/2'
    policy = copy.deepcopy(payload); policy['interpretation']['parsing_policy'] = 'typed-strict/1'
    mapping = copy.deepcopy(payload); mapping['interpretation']['mapping'] = 'well-tops/1'
    out = [('unknown reader', unknown), ('typed policy with the RESQML reader', policy), ('a mapping the RESQML reader has not', mapping)]
    if 'depth_stored_as' in payload.get('context', {}):
        stored = copy.deepcopy(payload); del stored['context']['depth_stored_as']
        out.append(('a RESQML context without depth_stored_as', stored))
    return out


@pytest.mark.parametrize('model,name,payload', CASES, ids=[c[0] for c in CASES])
def test_the_structure_refuses_what_it_states(model, name, payload):
    for why, changed in structural(payload):
        with pytest.raises(VerificationFailed):
            validate.model(getattr(generated, model), changed)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema(name)).validate(changed)


# E124 s2a (D4, R14): triangulated-surface and polyline-set 1.1.0 take the package reader's spatial interpretation. The
# released SDK's refusal is proved against the tree at main 58bc80e6f installed alone (the Validation Record).
SPATIAL = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'MSL', 'attributes': []}
SURFACE = {'schema': 'ophiolite.triangulated-surface/1', 'representation': 'normalized', 'source': SOURCE, 'source_sha256': 'c' * 64,
           'interpretation': {**READER, 'mapping': 'triangulated-surface/1'},
           'context': {'type': 'triangulated-surface', **SPATIAL, 'vertex_count': 4, 'triangle_count': 2, 'missing_z_count': 0,
                       'x_range': [0.0, 10.0], 'y_range': [0.0, 10.0], 'z_range': [2000.0, 2010.0], 'fidelity': FIDELITY},
           'vertices': [[0.0, 0.0, 2000.0], [10.0, 0.0, 2005.0], [10.0, 10.0, 2010.0], [0.0, 10.0, 2005.0]], 'triangles': [[0, 1, 2], [0, 2, 3]], 'attributes': []}
POLYLINES = {'schema': 'ophiolite.polyline-set/1', 'representation': 'normalized', 'source': SOURCE, 'source_sha256': 'c' * 64,
             'interpretation': {**READER, 'mapping': 'polyline-set/1'},
             'context': {'type': 'polyline-set', **SPATIAL, 'sticks': 1, 'points': 2, 'x_range': [0.0, 0.0], 'y_range': [0.0, 10.0], 'z_range': [2000.0, 2100.0],
                         'fidelity': FIDELITY},
             'sticks': [{'index': 0, 'points': [{'x': 0.0, 'y': 0.0, 'z': 2000.0}, {'x': 0.0, 'y': 10.0, 'z': 2100.0}]}]}
SPATIAL_CASES = [('TriangulatedSurface', 'triangulated-surface-schema.json', SURFACE), ('PolylineSet', 'polyline-set-schema.json', POLYLINES)]


@pytest.mark.parametrize('model,name,payload', SPATIAL_CASES, ids=[c[0] for c in SPATIAL_CASES])
def test_the_spatial_models_and_schemas_accept_a_surface_read_from_a_package(model, name, payload):
    assert validate.model(getattr(generated, model), payload).model_dump(by_alias=True, exclude_unset=True)['interpretation'] == payload['interpretation']
    jsonschema.Draft202012Validator(schema(name)).validate(payload)


@pytest.mark.parametrize('model,name,payload', SPATIAL_CASES, ids=[c[0] for c in SPATIAL_CASES])
def test_the_spatial_structure_refuses_what_it_states(model, name, payload):
    """Reader, policy and S1's mappings are structure; the pairing of mapping and context type is the Platform's."""
    trajectory = copy.deepcopy(payload); trajectory['interpretation']['mapping'] = 'trajectory/1'
    for why, changed in structural(payload) + [('S1 mapping on a spatial model', trajectory)]:
        with pytest.raises(VerificationFailed):
            validate.model(getattr(generated, model), changed)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema(name)).validate(changed)
