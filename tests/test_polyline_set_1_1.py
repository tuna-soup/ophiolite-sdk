"""E123 S1f-a (D3, A-d): the SDK's polyline-set 1.1.0 model and schema read a stick's stated fault name and number, a stick
of one point and the Petrel package reader's identity; null and unknown stay refused. The released SDK's refusal is
proved against the last released wheel in the Validation Record."""
import copy

import jsonschema
import pytest

from ophiolite import validate
from ophiolite.errors import VerificationFailed
from ophiolite.models import generated
from test_resqml_contracts import FIDELITY, SOURCE, SPATIAL, schema

PETREL = {'reader': 'asset_connectors.petrel_faults/1', 'mapping': 'polyline-set/1', 'parsing_policy': 'package-strict/1',
          'null_policy': 'no value of a row is missing; a row that is not whole refuses'}
POLYLINES = {'schema': 'ophiolite.polyline-set/1', 'representation': 'normalized', 'source': SOURCE, 'source_sha256': 'c' * 64,
             'interpretation': PETREL,
             'context': {'type': 'polyline-set', **SPATIAL, 'sticks': 2, 'points': 3, 'x_range': [0.0, 1.0], 'y_range': [0.0, 10.0],
                         'z_range': [2000.0, 2100.0], 'fidelity': FIDELITY},
             'sticks': [{'index': 1, 'fault': 'Øst_B', 'stick': 2, 'points': [{'x': 1.0, 'y': 1.0, 'z': 2050.0}]},
                        {'index': 2, 'fault': 'F2', 'stick': 1, 'points': [{'x': 0.0, 'y': 0.0, 'z': 2000.0}, {'x': 0.0, 'y': 10.0, 'z': 2100.0}]}]}


def test_the_sdk_reads_a_petrel_polyline_set_with_a_one_point_stick():
    read = validate.model(generated.PolylineSet, POLYLINES)
    assert read.model_dump(by_alias=True, exclude_unset=True)['sticks'] == POLYLINES['sticks']
    assert (read.sticks[0].fault, read.sticks[0].stick, len(read.sticks[0].points)) == ('Øst_B', 2, 1)
    jsonschema.Draft202012Validator(schema('polyline-set-schema.json')).validate(POLYLINES)


@pytest.mark.parametrize('stick', [{'fault': None}, {'stick': None}, {'name': 'F1'}, {'points': []}],
                         ids=['null fault', 'null stick', 'unknown field', 'no point'])
def test_null_unknown_and_empty_stay_refused(stick):
    changed = copy.deepcopy(POLYLINES); changed['sticks'][1].update(stick)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema('polyline-set-schema.json')).validate(changed)
    if 'name' not in stick:  # the SDK models allow extras (tolerant reading); the schema refuses them
        with pytest.raises(VerificationFailed):
            validate.model(generated.PolylineSet, changed)
