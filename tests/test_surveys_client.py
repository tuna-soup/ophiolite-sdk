"""E142 s1 C3: a script reads a survey as one unit and its commands keep one command id across the SDK's retry.

a. `survey` gathers pages of 2 into the seven members and their relations, in served order; `surveys` and
   `survey_history` follow their cursors;
b. a repeated cursor, or a page of another survey revision, stops the read (VerificationFailed);
c. a lost answer to a command is retried with the same command id, and a fresh id is made for each new command;
d. `AsyncClient` answers what `Client` answers.
The command line is `tests/test_cli_surveys.py`; the gateway side (the same calls against the real routes) is `tests/gateway/test_surveys.py`."""
import json

import anyio
import httpx
import pytest

from ophiolite.aio import AsyncClient
from ophiolite.client import Client
from ophiolite.errors import VerificationFailed

SID = '0f8fad5b-d9cb-469f-a165-70867728950e'
ROLES = ['cube', 'horizon', 'fault-set', 'well', 'well', 'time-depth', 'pickset']
MEMBERS = [{'role': r, 'asset_id': 'a%d' % i, 'revision': 'r%d' % i, 'label': 'syn-%d' % i} for i, r in enumerate(ROLES)]
RELATIONS = [{'predicate': 'horizon-of', 'subject': {'asset_id': 'a1', 'revision': 'r1'}, 'object': {'asset_id': 'a0', 'revision': 'r0'}}]


def page(members, relations, cursor, revision=3):
    return {'schema': 'ophiolite.survey/1', 'survey_id': SID, 'name': 'Seven', 'identity': {'provisional': True}, 'source': None,
            'context': {}, 'revision': revision, 'view': 'revision', 'members': members, 'relations': relations, 'count': 7,
            'next_cursor': cursor}


class Gateway:
    def __init__(self, repeat=False, other=False, lose=0):
        self.bodies, self.repeat, self.other, self.lose = [], repeat, other, lose

    def __call__(self, request):
        area, op = request.url.path.split('/')[-2:]
        assert area == 'surveys'
        body = json.loads(request.content); self.bodies.append((op, body))
        if op == 'get':
            at = int(body.get('cursor') or 0)
            cut = MEMBERS[at:at + 2]
            nxt = None if at + 2 >= len(MEMBERS) else ('0' if self.repeat else str(at + 2))
            return httpx.Response(200, json=page(cut, RELATIONS if at == 0 else [], nxt, revision=4 if self.other and at else 3))
        if op == 'list':
            first = body.get('cursor') is None
            return httpx.Response(200, json={'surveys': [{'survey_id': SID if first else 'other', 'name': 'Seven', 'identity': {'provisional': True},
                                                          'revision': 3, 'count': 7}], 'next_cursor': 'c' if first else None})
        if op == 'history':
            return httpx.Response(200, json={'events': [{'revision': 3, 'kind': 'add'}, {'revision': 1, 'kind': 'create'}], 'next_cursor': None})
        if self.lose:
            self.lose -= 1
            raise httpx.ReadError('lost')
        return httpx.Response(200, json={'survey_id': SID, 'revision': 1, 'kind': op, 'members': [], 'relations': []})


def client(gateway):
    return Client('https://gateway.example', 'p', None, httpx.Client(transport=httpx.MockTransport(gateway)))


def test_a_survey_is_gathered_from_its_pages_and_lists_follow_their_cursors():
    g = Gateway()
    found = client(g).survey(SID)
    assert [m.label for m in found.members] == ['syn-%d' % i for i in range(7)] and found.count == 7 and found.revision == 3
    assert [(r.subject.asset_id, r.object.asset_id) for r in found.relations] == [('a1', 'a0')] and found.member('a3').role == 'well'
    assert [b.get('cursor') for op, b in g.bodies] == [None, '2', '4', '6'] and {b['view'] for _, b in g.bodies} == {'revision'}
    assert [s['survey_id'] for s in client(g).surveys()] == [SID, 'other']
    assert [e['kind'] for e in client(g).survey_history(SID)] == ['add', 'create']
    assert next(iter(client(g).survey_pages(SID, 2, view='latest', limit=2))).count == 7 and g.bodies[-1][1] == {
        'project_id': 'p', 'survey_id': SID, 'view': 'latest', 'revision': 2, 'limit': 2}


@pytest.mark.parametrize('gateway', [Gateway(repeat=True), Gateway(other=True)], ids=['repeated-cursor', 'other-revision'])
def test_a_repeated_cursor_or_a_page_of_another_revision_stops_the_read(gateway):
    with pytest.raises(VerificationFailed): client(gateway).survey(SID)


def test_a_lost_answer_is_retried_with_the_same_command_id_and_each_command_gets_its_own():
    g = Gateway(lose=1)
    c = client(g)
    assert c.add_survey_members(SID, 2, [MEMBERS[0]])['kind'] == 'add'
    sent = [b for op, b in g.bodies if op == 'add']
    assert len(sent) == 2 and sent[0] == sent[1] and len(sent[0]['command_id']) == 32
    c.rename_survey(SID, 3, 'Renamed'); c.rename_survey(SID, 4, 'Again', command_id='mine')
    ids = [b['command_id'] for op, b in g.bodies if op == 'rename']
    assert ids[0] not in (sent[0]['command_id'], 'mine') and ids[1] == 'mine'
    c.replace_survey_member(SID, 5, ('a0', 'r0'), {'role': 'cube', 'asset_id': 'a9', 'revision': 'r9'})
    c.withdraw_survey(SID, 6)
    assert [(op, {k: v for k, v in b.items() if k not in ('command_id', 'project_id')}) for op, b in g.bodies[-2:]] == [
        ('replace', {'survey_id': SID, 'expected_revision': 5, 'from': {'asset_id': 'a0', 'revision': 'r0'}, 'to': {'role': 'cube', 'asset_id': 'a9', 'revision': 'r9'}}),
        ('withdraw', {'survey_id': SID, 'expected_revision': 6})]


def test_the_async_client_answers_what_the_client_answers():
    async def read():
        async with httpx.AsyncClient(transport=httpx.MockTransport(Gateway())) as http:
            async with AsyncClient('https://gateway.example', 'p', None, http) as a:
                return await a.survey(SID), await a.surveys(), await a.survey_history(SID), await a.create_survey('Seven', MEMBERS[:1], command_id='x')
    found, listed, events, made = anyio.run(read)
    assert found == client(Gateway()).survey(SID)
    assert listed == list(client(Gateway()).surveys()) and events == list(client(Gateway()).survey_history(SID)) and made['kind'] == 'create'
