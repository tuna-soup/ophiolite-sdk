"""S7 ruling (26 Oct 2026, addendum 23:09): an agent's confirmed `get` keeps its confirmation, and the project records
no delivery observation from it (`activity/report` refuses agents with 403 `agent-refused`).

test_exchange_report's world (in-process gateway with maps, alice's points item); alice registers her agent through her
session, and the agent gets the item through `AgentClient.reads`."""
import json

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from test_exchange_map import mapped  # noqa: F401
from test_exchange_report import world, owner_view  # noqa: F401
from ophiolite.agents import AgentClient


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
