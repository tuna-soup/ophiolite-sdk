"""E111 C4 (slice 1), gateway lane: an agent reports a run made on its computer and publishes the outputs under the one
approval bob gives the report (`AgentRun`), and registers a procedure through a plan (`agent_register`), against the
real routes of an in-process gateway. The four closed C4 tests; each names the mutation that fails it (the lane's
s1-mutations.txt). The world (bob's agent, alice's enabled two-output procedure, bob's tops) is the Platform's
`test_agents_covered.World`."""
import base64
import hashlib
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest
try:
    from project_gateway import agents as gateway_agents, procedure_runs
    from project_gateway.tests.test_agents_covered import World, MOVED_RAW, SHIFTED_RAW, count, executed  # noqa: F401 (fixture)
    from project_gateway.tests.test_one_api_matrix import web  # noqa: F401 (fixture)
    from project_gateway.tests.test_procedure_publish import DECLARED
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
import ophiolite
from ophiolite.agents import AgentClient, PlanExpired
from ophiolite.errors import Unavailable
from ophiolite.procedures import LOCAL_RUN, AgentRun, NotRun, agent_register

BUNDLE = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift'
RAWS = {'shifted': SHIFTED_RAW, 'moved': MOVED_RAW}


class Seen:
    """The agent's HTTP client: every path it sends to, and (when told) the answer to one derive lost after the commit."""
    def __init__(self, http, lose=0):
        self.http, self.paths, self.steps, self.lose = http, [], [], lose

    def post(self, url, **kw):
        self.paths.append(url.split('/projects/p/', 1)[1])
        upload = (kw.get('headers') or {}).get('X-Ophiolite-Upload')
        if upload: self.steps.append(json.loads(base64.b64decode(upload)))
        answer = self.http.post(url, **kw)
        if url.endswith('/publications/derive') and self.lose:
            self.lose -= 1
            raise httpx.ReadError('the answer was lost')
        return answer


def folder(tmp_path, w):
    """A run of alice's procedure made on the agent's computer, as `procedures.run` leaves it."""
    out = tmp_path / 'run'
    out.mkdir()
    outputs = {}
    for role, raw in RAWS.items():
        (out / (role + '.csv')).write_bytes(raw)
        outputs[role] = {'file': role + '.csv', 'sha256': hashlib.sha256(raw).hexdigest(), 'declared': DECLARED, 'profile': 'well-tops-csv/1'}
    record = {'schema': LOCAL_RUN, 'procedure': {'name': 'depth-shift', 'version': 2, 'digest': w.d}, 'settings': {},
              'inputs': {'tops': [{**w.a, 'kind': 'well-tops-csv/1', 'declared': DECLARED}]}, 'systems': {}, 'outputs': outputs,
              'runner': 'this computer'}
    (out / 'run.json').write_text(json.dumps(record))
    return out


def approve(w, then=None):
    """bob approves what waits for him while the agent waits (the agent's `sleep`)."""
    def decide(seconds):
        for plan in w.bob.ok('agents', 'plans', {'state': 'pending'})['plans']:
            w.bob.ok('agents', 'approve', {'hash': plan['hash'], 'evidence': None, 'evidence_generation': 0})
        if then: then()
    return decide


@pytest.fixture
def two(web):
    return World(web, two=True, budgets={'runs': 2, 'publications': 3})


def agent(w, http):
    return AgentClient('https://workspace.example', 'p', w.agent['credential'], http=http)


def test_the_steps_sent_equal_the_steps_the_approval_names(two, tmp_path, executed):
    """Each derive the SDK sends equals the gateway's expansion of the approved report, field for field (canonical), and
    both outputs land under one charge. Mutation: name each output by the agent's `name` instead of the approved
    `publish` entry → the steps differ and the gateway refuses them."""
    seen = Seen(two.web.c)
    run = AgentRun(agent(two, seen), folder(tmp_path, two), name='Shifted Chalk tops', publish={'moved': {'name': 'Moved Chalk tops'}})
    done = run.report('Publish the shifted tops', sleep=approve(two))
    assert [o['role'] for o in done['outputs']] == ['shifted', 'moved'] and len(executed) == 2
    assert all(o['receipt']['asset_id'] for o in done['outputs'])
    request = run.request()
    assert request['publish'] == {'shifted': {'name': 'Shifted Chalk tops: shifted'}, 'moved': {'name': 'Moved Chalk tops'}}
    with two.web.a.journal.lock:
        expanded = procedure_runs.expansion_locked(two.web.a.journal.db, 'p', two.agent['id'], {'project_id': 'p', **request})
    assert {'derive:' + h['run']['role']: gateway_agents.normal('publications/derive', h) for h in seen.steps} == \
           {s: gateway_agents.normal('publications/derive', h) for s, h in expanded.items()}
    assert [p for p in seen.paths if p != 'agents/status'] == ['agents/propose', 'procedure-runs/report', 'procedures/get', 'publications/derive', 'publications/derive']
    assert two.used()['publications'] == 1


def test_a_file_changed_after_approval_is_refused_before_sending(two, tmp_path, executed):
    """The output is read again before its step is sent and must be the approved bytes. Mutation: drop the digest
    check in `AgentRun._raw` → the changed file is sent (the gateway refuses it, but it left the computer)."""
    seen, out = Seen(two.web.c), folder(tmp_path, two)
    run = AgentRun(agent(two, seen), out, name='Shifted Chalk tops')
    with pytest.raises(NotRun) as raised:
        run.report(sleep=approve(two, then=lambda: (out / 'shifted.csv').write_bytes(SHIFTED_RAW + b'Late pick,1300\n')))
    assert raised.value.code == 'output-changed'
    assert 'publications/derive' not in seen.paths and not executed and count(two.web, 'agent_covered') == 0


def test_a_step_whose_answer_was_lost_is_recovered_by_reporting_again(two, tmp_path, executed):
    """The answer to the first derive is lost after the gateway committed it. Reporting again is the same plan and the
    same run (agent-run.json keeps the command id), the landed output answers its recorded receipt and nothing runs
    twice. Mutation: do not save the report's command id → reporting again proposes another plan."""
    out = folder(tmp_path, two)
    lossy = Seen(two.web.c, lose=1)
    with pytest.raises(Unavailable):
        AgentRun(agent(two, lossy), out, name='Shifted Chalk tops').report(sleep=approve(two))
    assert len(executed) == 1
    command = json.loads((out / 'agent-run.json').read_text())['command_id']
    again = AgentRun(agent(two, Seen(two.web.c)), out, name='Shifted Chalk tops').report(sleep=approve(two))
    assert json.loads((out / 'agent-run.json').read_text())['command_id'] == command
    assert len(executed) == 2  # the moved output, once; the shifted output was answered from its row
    assert count(two.web, 'agent_covered') == 2 and len(two.bob.ok('agents', 'plans', {})['plans']) == 1
    landed = {o['role']: o['receipt'] for o in again['outputs']}
    with two.web.a.journal.lock:
        stored = dict(two.web.a.journal.db.execute('SELECT step,ref FROM agent_covered WHERE plan=?', (again['plan'],)).fetchall())
    assert landed['shifted']['asset_id'] in stored['derive:shifted']


def test_register_goes_through_a_plan(two, tmp_path):
    """Registering a procedure is proposed, approved by bob, then executed; with no decision it does not run.
    Mutation: leave `procedures/register` out of CHANGES → the agent cannot propose it."""
    bundle = tmp_path / 'depth-shift'
    shutil.copytree(BUNDLE, bundle, ignore=shutil.ignore_patterns('__pycache__'))
    manifest = json.loads((bundle / 'procedure.json').read_text())
    manifest['version'] = 7
    (bundle / 'procedure.json').write_text(json.dumps(manifest, indent=2))
    helper = agent(two, two.web.c)
    with pytest.raises(PlanExpired):
        agent_register(helper, bundle, 'Register depth-shift 7', timeout=0, sleep=lambda s: None)
    [plan] = [p for p in two.bob.ok('agents', 'plans', {'state': 'pending'})['plans'] if p['operation'] == 'procedures/register']
    registered = agent_register(helper, bundle, 'Register depth-shift 7', sleep=approve(two))
    assert registered['digest']
    assert two.helper.post('agents', 'status', {'hash': plan['hash']}).json()['state'] == 'consumed'
