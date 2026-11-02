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
    (lambda p: p['members'][0].update(trajectory=None), '^A member has a frame without a trajectory No files were saved'),  # E119a s6: the literal, the old "or ..." gone
    (lambda p: p['context'].update(with_trajectory=3, without_trajectory=0), 'Members and their context disagree'),
    (lambda p: p['context'].update(count=4), 'Members and their context disagree'),
])
def test_inconsistent_payloads_with_valid_digests_are_refused(broken, sentence):
    descriptor, body = load()
    payload = json.loads(body); broken(payload)
    generated.WellSet.model_validate(payload)  # the generated model (the schema) cannot state the cross-field rule
    descriptor, body = repinned(descriptor, payload)
    with pytest.raises(VerificationFailed, match=sentence): validate.typed_pair(descriptor, body)


def frameless():
    """The snapshot pair with member 0 saved without a frame (E119a s6), its digest made true."""
    descriptor, body = load()
    payload = json.loads(body); payload['members'][0]['frame'] = None
    return (*repinned(descriptor, payload), payload)


def test_a_trajectory_without_a_frame_reads_with_a_valid_digest():
    """E119a s6 (D1, R1-5, A1): the invariant admits (trajectory, null); the counts still count it as with a trajectory."""
    descriptor, body, payload = frameless()
    asset, read = validate.typed_pair(descriptor, body)
    assert read['members'] == payload['members'] and read['members'][0]['frame'] is None
    assert (read['context']['count'], read['context']['with_trajectory'], read['context']['without_trajectory']) == (3, 2, 1)


def test_client_well_sets_read_reads_a_frameless_set_back():
    """R1-5: a stored frameless set read back through `client.well_sets.read`, as the server answers it."""
    import httpx
    from ophiolite import Client, Credential
    descriptor, body, payload = frameless()
    original = FIXTURES.joinpath('well-set.original').read_bytes()
    asset, revision, project = descriptor['asset_id'], descriptor['revision'], descriptor['project_id']

    def handle(request):
        path = request.url.path
        if path.endswith('/representations/data'): return httpx.Response(200, content=body)
        if path.endswith('/representations/artifact'): return httpx.Response(200, content=original)
        assert path.endswith('/revisions/' + revision), path
        return httpx.Response(200, json=descriptor)
    c = Client('https://gateway.example', project, Credential.bearer('t'), httpx.Client(transport=httpx.MockTransport(handle)))
    well_set = c.well_sets.read(asset, revision)
    assert well_set.members == payload['members'] and well_set.members[0]['frame'] is None
    assert well_set.members[0]['trajectory'] == payload['members'][0]['trajectory']
