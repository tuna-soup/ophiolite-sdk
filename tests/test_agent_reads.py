"""E111 s4a (D-A2, D-A3), tests 7 (the assistant path) and 8 of the s4a strategy: `AgentClient.reads` asks the agent's
credential again on every request, and `agent.well_sets.bind` checks a member through `las-uploads/check-member` and
names it by its own position. The gateway's answers are replayed here; that the gateway gives them to a real agent key
is the Gateway's test_well_set_check_member.py and test_agent_prepare_e2e.py."""
import json

import httpx
import pytest

from ophiolite.agents import AgentClient
from ophiolite.auth import Credential
from ophiolite.errors import PermissionRefused, Refused

URL = 'https://gateway.example'
B = ['wellbore-' + c * 32 for c in 'abc']
T = {'asset_id': 'traj-three', 'revision': '7' * 64}
SET = {'schema': 'ophiolite.well-set/1', 'label': 'Zuidwolde wells', 'members': [
    {'well': 'well-' + '1' * 32, 'wellbore': b, 'trajectory': T if i == 2 else None, 'frame': None} for i, b in enumerate(B)]}


class Refreshing(Credential):
    """An assistant sign-in whose access token is refreshed between two requests."""
    def __init__(self):
        super().__init__('token-1')
        self.issued = 0

    def headers(self, url=None, project=None, *, cancel=None):
        self.issued += 1
        return {'Authorization': 'Bearer token-%d' % self.issued}


def agent(handle, credential='oph_agent_test'):
    seen = []

    def record(request):
        seen.append((request.url.path, request.headers.get('authorization'), json.loads(request.content or b'{}')))
        return handle(request)
    return AgentClient(URL, 'p', credential, http=httpx.Client(transport=httpx.MockTransport(record))), seen


def test_an_assistant_sign_in_is_asked_again_on_every_read():
    """Mutation: `_AgentAuth.headers` keeps the first headers -> the second read carries token-1 -> red."""
    a, seen = agent(lambda r: httpx.Response(200, json={'checked': True}), Refreshing())
    a.reads._post('las-uploads', 'check-member', {'label': 'x', 'member': {}})
    a.reads._post('las-uploads', 'check-member', {'label': 'x', 'member': {}})
    assert [s[1] for s in seen] == ['Bearer token-1', 'Bearer token-2']
    assert a.reads is a.reads  # made once; only the headers are asked again


def test_an_agent_key_reads_with_its_own_key_in_the_agents_project():
    a, seen = agent(lambda r: httpx.Response(200, json={'checked': True}))
    assert a.reads._post('las-uploads', 'check-member', {'label': 'x', 'member': {}}) == {'checked': True}
    assert seen == [('/api/v1/projects/p/las-uploads/check-member', 'Bearer oph_agent_test', {'project_id': 'p', 'label': 'x', 'member': {}})]
    with pytest.raises(Refused, match='^The request belongs to another project.$'):
        a.reads._post('las-uploads', 'check-member', {'project_id': 'q', 'label': 'x', 'member': {}})


def test_a_refused_third_member_is_named_member_3_and_nothing_is_read():
    """Test 8. Mutation: rewrite with the server's index -> "Member 1" -> red."""
    a, seen = agent(lambda r: httpx.Response(400, json={'code': 'INVALID_ARGUMENT', 'message': 'Member 1: The trajectory revision was withdrawn.',
                                                        'request_id': 'r-1', 'reason': 'well-set:withdrawn', 'field': 'members[0]'}))
    with pytest.raises(Refused) as caught: a.well_sets.bind(SET, 2, {'crs': 'EPSG:28992'})
    assert str(caught.value).split('\n')[0] == 'Member 3: The trajectory revision was withdrawn.'
    assert caught.value.details == {'reason': 'well-set:withdrawn', 'field': 'members[2]'}
    assert seen == [('/api/v1/projects/p/las-uploads/check-member', 'Bearer oph_agent_test', {'project_id': 'p', 'label': 'Zuidwolde wells', 'member': SET['members'][2]})]


def test_a_refusal_that_is_not_the_sets_propagates_as_sent():
    a, _ = agent(lambda r: httpx.Response(403, json={'code': 'PERMISSION_DENIED', 'message': 'Outside the agent\'s scopes', 'request_id': 'r-2'}))
    with pytest.raises(PermissionRefused) as caught: a.well_sets.bind(SET, B[2], {'crs': 'EPSG:28992'})
    assert 'Member' not in str(caught.value) and caught.value.status == 403


def test_the_agent_offers_the_reads_prepare_uses_and_no_write():
    a, _ = agent(lambda r: httpx.Response(200, json={}))
    for name in ('project', 'well_sets', 'read_data', '_entities', '_download_version'):
        assert hasattr(a, name), name
    assert a.well_sets.client is a.reads
    for name in ('upload_data', 'create_entity', 'of_entity', 'share', 'procedure_run'):
        assert not hasattr(a, name), name
