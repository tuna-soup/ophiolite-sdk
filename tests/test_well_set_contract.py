"""E119a slice 0 (test 2, SDK half; 4-10): the SDK reads a well-set pair from the contract snapshot, and its offline
rules refuse payloads whose digests are valid but whose members disagree with each other or with the context. Saving
and reading a set from a deployment is slice 1."""
import copy
import hashlib
import json
from importlib.resources import files

import pytest

from ophiolite import validate
from ophiolite.errors import VerificationFailed
from ophiolite.models import generated

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load():
    return json.loads(FIXTURES.joinpath('well-set.json').read_bytes()), FIXTURES.joinpath('well-set-data.json').read_bytes()


def repinned(descriptor, payload):
    """The descriptor with the normalized representation's digest and size made true for `payload`."""
    body = json.dumps(payload).encode(); descriptor = copy.deepcopy(descriptor)
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized')
    rep.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    descriptor['scientific'] = payload['context']  # the descriptor states the same (inconsistent) context
    return descriptor, body


def test_the_snapshot_pair_reads_as_a_well_set():
    descriptor, body = load()
    asset, payload = validate.typed_pair(descriptor, body)
    assert payload['schema'] == 'ophiolite.well-set/1' and payload['context']['count'] == 3
    assert [m['trajectory'] is not None for m in payload['members']] == [True, True, False]
    assert generated.WellSet.model_validate(json.loads(body)).label == 'Residual wells'


@pytest.mark.parametrize('broken,sentence', [
    (lambda p: p['members'][1].update(wellbore=p['members'][0]['wellbore']), 'A wellbore appears twice in the set'),
    (lambda p: p['members'][0].update(trajectory=None), 'a frame without a trajectory'),
    (lambda p: p['members'][2].update(trajectory={'asset_id': 'synthetic-trajectory-3', 'revision': '3' * 64}), 'a trajectory without a frame'),
    (lambda p: p['context'].update(with_trajectory=3, without_trajectory=0), 'Members and their context disagree'),
    (lambda p: p['context'].update(count=4), 'Members and their context disagree'),
])
def test_inconsistent_payloads_with_valid_digests_are_refused(broken, sentence):
    descriptor, body = load()
    payload = json.loads(body); broken(payload)
    generated.WellSet.model_validate(payload)  # the generated model (the schema) cannot state the cross-field rule
    descriptor, body = repinned(descriptor, payload)
    with pytest.raises(VerificationFailed, match=sentence): validate.typed_pair(descriptor, body)
