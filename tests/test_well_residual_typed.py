"""E119b slice 0 test 9 (SDK half; 5-9): the SDK reads a residual result pair from the contract snapshot as a typed
object, and its offline rules refuse payloads whose digests are valid but whose rows disagree with themselves or with
the context. The generated model (the schema) accepts each of them: the generator emits no if/then (E110 7-10).
Publishing a residual result is slice 1; literals written by hand from the strategy's record table."""
import copy
import hashlib
import json
from importlib.resources import files

import pytest

from ophiolite import _core, typed, validate
from ophiolite.errors import VerificationFailed
from ophiolite.models import generated

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load():
    return json.loads(FIXTURES.joinpath('well-residual.json').read_bytes()), FIXTURES.joinpath('well-residual-data.json').read_bytes()


def repinned(descriptor, payload):
    """The descriptor with the normalized representation's digest and size made true for `payload`."""
    body = json.dumps(payload).encode(); descriptor = copy.deepcopy(descriptor)
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized')
    rep.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    descriptor['scientific'] = payload['context']  # the descriptor states the same (inconsistent) context
    return descriptor, body


def test_the_snapshot_pair_reads_as_a_residual_result():
    descriptor, body = load()
    asset, payload = validate.typed_pair(descriptor, body)
    assert payload['schema'] == 'ophiolite.well-residual/1' and payload['context']['count'] == 3
    result = _core.typed_result(descriptor, body, FIXTURES.joinpath('well-residual.original').read_bytes())
    assert isinstance(result, typed.WellResidual) and typed.CLASSES['well-residual'] is typed.WellResidual and 'well-residual' in typed.TYPES
    assert len(result) == 3 and [r['residual'] for r in result.rows] == [2.25, None, None] and [r['reason'] for r in result.rows] == [None, 'grazing', 'no-top']
    assert repr(result) == '<WellResidual DCC: 1 of 3 rows computed, 3 wellbores>'
    assert generated.WellResidual.model_validate(json.loads(body)).context.display_unit == 'm'


def test_the_frame_states_each_row_with_its_top_and_used_crossing():
    pytest.importorskip('pandas')
    descriptor, body = load()
    frame = _core.typed_result(descriptor, body, FIXTURES.joinpath('well-residual.original').read_bytes()).to_frame()
    assert list(frame.columns) == ['wellbore', 'occurrence', 'top_md', 'crossing_md', 'residual', 'reason']
    assert frame['top_md'].tolist()[:2] == [1250.5, 1302.0] and frame['crossing_md'].tolist()[0] == 1248.25 and frame['residual'].tolist()[0] == 2.25


@pytest.mark.parametrize('broken,sentence', [
    (lambda p: p['rows'][0].update(residual=-2.25), "not its top's measured depth minus the used crossing's"),  # the sign: top.md - md
    (lambda p: p['rows'][0].update(used=1), 'names a crossing that is not listed'),
    (lambda p: p['rows'][0].update(reason='grazing'), 'a residual or a reason, not both'),
    (lambda p: p['rows'][0].update(occurrence=0), 'a top exactly when its occurrence is not 0'),
    (lambda p: p['rows'][2].update(between=[1.0, 2.0]), 'exactly for the reasons that carry one'),
    (lambda p: p['rows'][1].update(between=[2.0, 1.0]), 'exactly for the reasons that carry one'),
    (lambda p: p['rows'][0]['crossings'].append({'md': 1200.0, 'low': 1199.9, 'high': 1200.1}), 'increasing measured depth'),
    (lambda p: p['context'].update(computed=2, not_computed=1), 'Rows and their context disagree'),
    (lambda p: p['context'].update(members=2), 'Rows and their context disagree'),
    (lambda p: p['context'].update(members_not_computed=1), 'Rows and their context disagree'),
])
def test_inconsistent_payloads_with_valid_digests_are_refused(broken, sentence):
    descriptor, body = load()
    payload = json.loads(body); broken(payload)
    generated.WellResidual.model_validate(payload)  # the generated model (the schema) cannot state the cross-field rule
    descriptor, body = repinned(descriptor, payload)
    with pytest.raises(VerificationFailed, match=sentence): validate.typed_pair(descriptor, body)


def test_the_tops_context_states_a_depth_datum_or_omits_it():
    tops = json.loads(FIXTURES.joinpath('tops.json').read_bytes())['scientific']
    assert generated.TopsContext.model_validate({**tops, 'depth_datum': 'rotary table'}).depth_datum == 'rotary table'
    assert 'depth_datum' not in generated.TopsContext.model_validate(tops).model_fields_set
