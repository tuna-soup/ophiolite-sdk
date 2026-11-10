"""E142 s1 C3, gateway lane: a script creates and reads the generated 286-line survey through the real survey routes.

a. `client.survey` gathers all 286 members, each the landed revision of its line, in asset-id order (the oracle's
   ids are written from the upload rule, never read back); bob, who reads 200 lines, gets the access oracle's 200;
b. the async client answers what the client answers;
c. a create whose answer is lost is retried with the same command id: one survey, the same receipt."""
import hashlib
import json

import anyio
import httpx
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import Client, Credential
from ophiolite.aio import AsyncClient
from project_gateway.las_uploads import LASUploads, Upload
from project_gateway.tests.survey_fixtures import FIXTURES, LINE_DECLARED, asset_id, land, line_bytes

ACCESS = json.loads((FIXTURES / 'access.json').read_text())['bob']


@pytest.fixture
def lines(web, monkeypatch):  # noqa: F811
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOADS_PER_PROJECT', '1000')
    u = LASUploads(web.a)
    q = Upload(project_id='p', command_id='one', filename='test.las', name='Uploaded LAS', attribution='Synthetic test',
               audience=['bob'], rights_confirmed=True)
    return [{'role': 'line', **land(u, q, 'syn-line-%04d' % i, 'segy-line/1', line_bytes(i), LINE_DECLARED, ['bob'] if i <= 200 else [])}
            for i in range(1, 287)]


class Lose(httpx.BaseTransport):
    """The gateway's transport; the first answer to a survey command is read and then lost on the way back."""
    def __init__(self, inner):
        self.inner, self.sent = inner, []

    def handle_request(self, request):
        answer = self.inner.handle_request(request)
        answer = httpx.Response(answer.status_code, headers=answer.headers, content=answer.read())
        if request.url.path.startswith('/api/v1/projects/p/surveys/') and request.url.path.split('/')[-1] not in ('get', 'list', 'history'):
            self.sent.append(json.loads(request.content))
            if len(self.sent) == 1: raise httpx.ReadError('lost')
        return answer


def test_the_286_survey_is_read_whole_and_as_bob_may_read_it(web, lines):  # noqa: F811
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    made = alice.create_survey('Synthetic survey LINES', lines, context={'z_domain': 'time'}, command_id='lines')
    found = alice.survey(made['survey_id'])
    expected = sorted(asset_id('syn-line-%04d' % i) for i in range(1, 287))
    assert found.count == 286 and found.revision == 1 and [m.asset_id for m in found.members] == expected
    landed = {m['asset_id']: m['revision'] for m in lines}
    assert all(m.revision == landed[m.asset_id] for m in found.members) and found.relations == []
    theirs = [m.asset_id for m in bob.survey(made['survey_id']).members]
    assert [len(theirs), theirs[0], theirs[-1], hashlib.sha256(''.join(i + '\n' for i in theirs).encode()).hexdigest()] == \
        [ACCESS[f] for f in ('count', 'first', 'last', 'digest')]

    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example') as http:
            async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as a:
                return await a.survey(made['survey_id']), await a.surveys(), await a.survey_history(made['survey_id'])
    got, listed, events = anyio.run(read)
    assert got == found and listed == list(alice.surveys()) and events == list(alice.survey_history(made['survey_id']))
    assert [e['kind'] for e in events] == ['create']


def test_a_lost_create_answer_is_retried_with_the_same_command_id(web, lines):  # noqa: F811
    lose = Lose(web.c._transport)
    alice = Client('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), httpx.Client(transport=lose))
    made = alice.create_survey('Synthetic survey LINES', lines[:3])
    assert len(lose.sent) == 2 and lose.sent[0] == lose.sent[1] and len(lose.sent[0]['command_id']) == 32
    again = alice.create_survey('Synthetic survey LINES', lines[:3], command_id=lose.sent[0]['command_id'])
    assert again == made and [s['survey_id'] for s in alice.surveys()] == [made['survey_id']]
