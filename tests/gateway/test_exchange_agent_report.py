"""S7 ruling (26 Oct 2026, addendum 23:09): an agent's confirmed `get` keeps its confirmation, and the project records
no delivery observation from it (`activity/report` refuses agents with 403 `agent-refused`).

test_exchange_report's world (in-process gateway with maps, alice's points item); alice registers her agent through her
session, and the agent gets the item through `AgentClient.reads`."""
import json

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from test_exchange_map import mapped  # noqa: F401
from test_exchange_report import world, owner_view  # noqa: F401
from test_agent_procedures import agent as covered_agent, approve, folder, two, executed  # noqa: F401 (fixtures)
import pytest
from project_gateway import procedure_store
from project_gateway.tests.test_agents_covered import DOI, count, rows
from project_gateway.tests.test_agent_report_of_entity import entity
from ophiolite import exchange
from ophiolite.agent_exchange import ToolRunRefused
from ophiolite.agents import AgentClient
from ophiolite.exchange import AccessRefused


def registered(gateway):
    token, csrf = gateway.app.state.sessions.create('alice', None, 'alice')
    gateway.c.cookies.set('ab_session', token)
    made = gateway.c.post('/api/v1/projects/p/agents/register', json={'project_id': 'p', 'name': 'Exchange helper', 'scopes': ['read', 'write'],
                          'budgets': {'runs': 1, 'publications': 1}, 'expires_in_days': 7, 'policy': []}, headers={'X-CSRF-Token': csrf, 'Origin': ORIGIN})
    gateway.app.state.sessions.remove(token); gateway.c.cookies.clear()
    assert made.status_code == 200, made.text
    return AgentClient(ORIGIN, 'p', made.json()['credential'], http=gateway.c)


def test_an_agents_get_is_confirmed_and_its_report_refused_and_not_recorded(world, tmp_path):
    gateway, _, item, _, sent = world
    answers = []
    gateway.c.event_hooks['response'].append(lambda r: answers.append((r.status_code, json.loads(r.read()).get('code'))) if r.url.path.endswith('/activity/report') else None)
    agent = registered(gateway)
    got = agent.reads.exchange(tmp_path / 'work').get(item.asset_id, output=tmp_path / 'out')
    assert (got.outcome, got.technical['reported']) == ('got', False)
    entry = json.loads((tmp_path / 'work/held.json').read_text())['items'][item.asset_id]
    assert entry['revision'] == item.revision  # the confirmation stands
    assert len(sent) == 1 and answers == [(403, 'agent-refused')]  # sent once, refused
    assert owner_view(gateway) == []  # nothing on the record


# E155 s2 C2: `send_run(of_entity=...)` against the Platform's covered-run world (`test_agent_procedures.two`: bob's
# assistant, alice's enabled, verified two-output depth-shift that bob trusts, bob's tops). The wellbore is a synthetic
# one alice creates and shares with bob (the E60w import fixture is not needed for the assertion; recorded in the VR).

def holding(tmp_path, w):
    """The assistant's exchange folder, holding the run's input at the version the run read."""
    work = tmp_path / 'work'
    work.mkdir()
    entry = {'asset_id': w.a['asset_id'], 'name': 'Tops to shift', 'kind': 'derived', 'revision': w.a['revision'], 'number': 1, 'output': None}
    (work / 'held.json').write_text(json.dumps({'schema': exchange.SCHEMA, 'url': 'https://workspace.example', 'project': 'p', 'holder_id': 'h' * 32,
                                                'items': {entry['asset_id']: entry}, 'seen': [entry['asset_id']], 'pending': None}))
    return work


def asserted(w, ident):
    return rows(w.web, "SELECT subject_id,object_kind FROM assertions WHERE predicate='of-entity' AND revoked_at IS NULL AND object_id=?", ident)


def unverify(w, command):
    with w.web.a.journal.lock: record = procedure_store.verifications(w.web.a.journal.db, 'p', w.d)[-1]
    w.alice.ok('procedures', 'verify', {'command_id': command, 'digest': w.d, 'kind': 'withdrawn', 'reference': {'withdraws': record['id']}})


def send(w, tmp_path, bore, **kw):
    return covered_agent(w, w.web.c).exchange(holding(tmp_path, w)).send_run(folder(tmp_path, w), name='Shifted Chalk tops',
                                                                             of_entity={'shifted': bore['id']}, **kw)


def test_an_approved_send_about_a_wellbore_asserts_it_and_the_wellbore_lists_the_result(two, tmp_path):
    """The shifted output is about the wellbore, the moved one about nothing. Mutation: leave `of_entity` out of
    `publish` in send_run → no assertion and the wellbore lists nothing."""
    bore = entity(two, 'wellbore', 'HON-GT-02')
    done = send(two, tmp_path, bore, sleep=approve(two))
    assert done.outcome == 'sent-run'
    landed = {o['role']: o['asset_id'] for o in done.technical['outputs']}
    assert asserted(two, bore['id']) == [(landed['shifted'], 'wellbore')]
    items = two.bob.ok('entities', 'assets', {'entity_id': bore['id']})['items']
    assert [(i['asset_id'], i['revision'], i['association']['evidence']['statement']) for i in items] == \
           [(landed['shifted'], done.technical['outputs'][0]['revision'], 'Declared when this result was published')]


def test_a_wellbore_lost_after_approval_publishes_nothing_and_asserts_nothing(two, tmp_path, executed):
    """M7: alice takes bob's grant back between the approval and the derive. Mutation: write the assertion before the
    derive's entity check → an assertion row stays."""
    bore = entity(two, 'wellbore', 'HON-GT-02')
    revoke = lambda: two.alice.ok('entities', 'share', {'entity_id': bore['id'], 'audience': [], 'expected_generation': bore['generation'],
                                                        'command_id': 'e155s2-gw-revoke'})
    with pytest.raises(AccessRefused) as raised:
        send(two, tmp_path, bore, sleep=approve(two, then=revoke))
    assert (raised.value.technical['status'], raised.value.technical['server_message']) == (404, 'Entity unavailable')
    assert asserted(two, bore['id']) == [] and count(two.web, 'agent_covered') == 0


def test_the_tool_run_gate_holds_for_a_send_about_a_wellbore(two, tmp_path):
    """Not verified at proposal: refused, no plan. Verification withdrawn after the approval: the covered derive is
    refused and nothing is asserted. Mutation: the assertion before the gate in the derive → a row stays."""
    bore = entity(two, 'wellbore', 'HON-GT-02')
    unverify(two, 'e155s2-gw-unverify-1')
    with pytest.raises(ToolRunRefused) as raised:
        send(two, tmp_path, bore, sleep=approve(two))
    assert raised.value.facts['reason'] == 'not-verified' and two.bob.ok('agents', 'plans', {})['plans'] == []
    two.alice.ok('procedures', 'verify', {'command_id': 'e155s2-gw-verify', 'digest': two.d, 'kind': 'publication', 'reference': DOI})
    (tmp_path / 'again').mkdir()
    with pytest.raises(ToolRunRefused) as raised:
        send(two, tmp_path / 'again', bore, sleep=approve(two, then=lambda: unverify(two, 'e155s2-gw-unverify-2')))
    assert raised.value.facts['reason'] == 'not-verified'
    assert asserted(two, bore['id']) == [] and count(two.web, 'agent_covered') == 0
