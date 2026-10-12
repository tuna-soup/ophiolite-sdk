"""E23b A3: the SDK reads what the Part 1 writer emits (import-recipe/2 interpretation, point-set/2 1.1.0 decisions
chosen by a person's selection) through `validate.typed_pair`, the regenerated models and the typed objects, and the
/1 documents still read on the same path. The /2 invariants beyond the generated models refuse a selection that
disagrees with itself. Payloads are the contract fixture edited in place; digests are recomputed as a tamperer would."""
import json

import pytest
from ophiolite import _core
from ophiolite.errors import VerificationFailed
from ophiolite.typed import PointSet

from test_recipe_points import load, rehash

README, PRIMARY = 'a' * 64, 'b' * 64


def v2(edit=None):
    """The fixture as the /2 writer emits it: z_meaning chosen by a person's selection of the README observation."""
    descriptor, body, original = load(); payload = json.loads(body)
    for interpretation in (payload['interpretation'], descriptor['interpretation']): interpretation['parsing_policy'] = 'import-recipe/2'
    z = next(d for d in payload['context']['fidelity']['decisions'] if d['field'] == 'z_meaning')
    for observation, identity in zip(z['observations'], (README, PRIMARY)): observation['id'] = identity
    z['observations'][1]['rejected'] = True
    z.update(selected_by='selection', selection={'entry': 'e1', 'observation': README}, reason='The README states the vertical axis.')
    if edit: edit(z, payload, descriptor)
    return descriptor, rehash(descriptor, payload), original


def test_a_v2_document_reads_through_typed_pair_and_the_typed_objects():
    points = _core.typed_result(*v2())
    assert isinstance(points, PointSet) and points.status == 'decided'
    z = next(d for d in points.decisions if d.field == 'z_meaning')
    assert (z.selected, z.selected_by) == ('time', 'selection')
    assert repr(z) == "<Decision Values: time because 'The README states the vertical axis.'>"
    assert z.details()['field'] == 'z_meaning' and z.details()['selected_by'] == 'selection'


def test_the_v1_documents_read_on_the_same_path():
    points = _core.typed_result(*load())
    assert points.data['interpretation']['parsing_policy'] == 'import-recipe/1' and points.status == 'decided'


def stale(z, payload, descriptor):
    z.update(selected=None, selected_by=None, selection=None, status='needs-decision')
    payload['context']['z_meaning'] = 'unknown'; payload['context']['fidelity']['unknown_context'] = ['z_meaning']
    payload['context']['fidelity']['execution']['unresolved'] = ['z_meaning']  # status left 'decided'
    descriptor['package']['unresolved'] = ['z_meaning']  # the package record agrees with the stale execution


@pytest.mark.parametrize('edit, match', [
    (lambda z, p, d: z['observations'][0].update(rejected=True), 'chose an observation marked rejected'),
    (lambda z, p, d: z['selection'].update(observation='0' * 64), 'names no observation of its field'),
    (lambda z, p, d: z['selection'].update(observation=PRIMARY) or z['observations'][1].pop('rejected'), 'differs from the value of the observation'),
    (stale, 'execution status and the decisions disagree'),
])
def test_a_v2_selection_that_disagrees_with_itself_is_refused(edit, match):  # the generated models alone accept each
    with pytest.raises(VerificationFailed, match=match): _core.typed_result(*v2(edit))
