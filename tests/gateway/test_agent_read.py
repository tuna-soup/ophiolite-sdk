"""E111 s2 (C4, P-10, t10 and t11 against the gateway): an agent reads one file with a read procedure through `AgentRead`.
bob approves `upload-runs/start` once, and its covered steps (the file's head, the declaration, the original, each
output) land under that approval, against the real routes of an in-process gateway. The version is alice's, enabled in
the project; bob's agent trusts it through a plan bob approves (P-10: `AgentRead` never sends procedures/trust). Each test names the mutation that fails it
(the lane's s2-mutations.txt); the unit lane, tests/test_agent_procedures.py, proves the protocol over a recording
transport."""
import base64
import json
import os
import time

import httpx
import pytest
try:
    from project_gateway import agents as gateway_agents, conversions
    from project_gateway.procedure_contract import contract
    from project_gateway.tests.procedure_world import b64
    from project_gateway.tests.test_agents import Agent, register as register_agent
    from project_gateway.tests.test_one_api_matrix import Caller, web  # noqa: F401 (fixture)
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests.test_las_uploads import upload  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite.agents import AgentClient
from ophiolite.errors import IntegrityConflict, Unavailable
from ophiolite.procedures import AgentRead, NotRun
from test_intake_read_live import DEVIATION, PDF, READER, TOPS, manifest

SETTINGS = ['well=HON-GT-01']


class World:
    """bob, his agent (one start charged to publications), and alice's enabled two-output read version."""
    def __init__(self, web, trusted=True):
        self.web = web
        self.bob, self.alice = Caller(web, 'session', 'bob'), Caller(web, 'session', 'alice')
        self.agent = register_agent(web, persona='bob', scopes=['read', 'write'], policy=[], budgets={'runs': 2, 'publications': 2})
        self.helper = Agent(web, self.agent['credential'])
        found = {'procedure.json': json.dumps(manifest(), indent=2).encode(), 'reader.py': (READER % (TOPS, DEVIATION)).encode()}
        self.d = self.alice.ok('procedures', 'register', {'command_id': 'alice-1', 'archive': b64(contract().pack_files(found))})['digest']
        self.alice.ok('procedures', 'enable', {'command_id': 'alice-2', 'digest': self.d})
        if trusted:  # the agent's own trust, proposed and approved by bob (a person's trust is not the agent's)
            request = {'project_id': 'p', 'command_id': 'trust-1', 'digest': self.d}
            plan = self.helper.propose('procedures/trust', request)['hash']
            self.bob.ok('agents', 'approve', {'hash': plan, 'evidence': None, 'evidence_generation': 0})
            assert self.helper.post('procedures', 'trust', request, plan).status_code == 200

    def rows(self, sql, *args):
        with self.web.a.journal.lock: return [tuple(r) for r in self.web.a.journal.db.execute(sql, args).fetchall()]

    def used(self):
        return {k: v['used'] for k, v in self.helper.post('capabilities', 'describe', {}).json()['principal']['agent']['budgets'].items()}


@pytest.fixture
def world(web):
    return World(web)


class Seen:
    """The agent's HTTP client: every operation and request it sends, and (when told) one answer lost after the commit
    or one staged original expired before an output."""
    def __init__(self, world, lose=None, expire=None):
        self.world, self.http, self.sent, self.lose, self.expire = world, world.web.c, [], lose, expire

    def post(self, url, **kw):
        operation = url.split('/projects/p/', 1)[1]
        upload = (kw.get('headers') or {}).get('X-Ophiolite-Upload')
        body = json.loads(base64.b64decode(upload)) if upload else kw.get('json')
        name = operation + (':' + body['role'] if operation == 'upload-runs/convert-output' else '')
        if name == self.expire:
            self.expire = None
            with self.world.web.a.journal.lock, self.world.web.a.journal.db:
                self.world.web.a.journal.db.execute('UPDATE upload_original_stages SET expires_at=?', (1.0,))
        self.sent.append((name, body, kw.get('content')))
        self.http.cookies.clear()
        answer = self.http.post(url, **kw)
        if name == self.lose:
            self.lose = None
            raise httpx.ReadError('the answer was lost')
        return answer

    def steps(self):
        return [(n, b, raw) for n, b, raw in self.sent if n.startswith('upload-runs/') and n != 'upload-runs/start' and n != 'upload-runs/status']


def approve(w):
    """bob approves what waits for him while the agent waits (the agent's `sleep`)."""
    def decide(seconds):
        for plan in w.bob.ok('agents', 'plans', {'state': 'pending'})['plans']:
            w.bob.ok('agents', 'approve', {'hash': plan['hash'], 'evidence': None, 'evidence_generation': 0})
    return decide


@pytest.fixture
def report(tmp_path):
    (tmp_path / 'HON-GT-01').mkdir()
    path = tmp_path / 'HON-GT-01/end of well report.pdf'
    path.write_bytes(PDF)
    return path


def reader(w, seen, report, tmp_path, keep=True):
    agent = AgentClient('https://workspace.example', 'p', w.agent['credential'], http=seen)
    return AgentRead(agent, report, version=w.d, attribution='NLOG.NL', keep_original=keep, settings=SETTINGS,
                     folder=tmp_path / 'state', cache=tmp_path / 'cache')


def runs_of(report):
    log = report.parent / (report.name + '.runs')
    return log.read_text().split() if log.exists() else []


def landed(w, run_id):
    return w.rows('SELECT role,outcome FROM upload_run_conversion_outputs WHERE run_id=? ORDER BY role', run_id)


def test_the_steps_sent_equal_the_steps_the_approval_names(world, report, tmp_path):
    """t10: each step AgentRead sends equals the gateway's expansion of the approved start (through each route's own
    model), in the approval's order, and the start is charged once. Mutation: send the outputs before the original in
    `AgentRead.steps` → the order differs."""
    seen = Seen(world)
    done = reader(world, seen, report, tmp_path).read('Read the end of well report', sleep=approve(world))
    assert done['conversion']['state'] == 'complete' and runs_of(report) == ['HON-GT-01']
    [(_, proposed, _)] = [s for s in seen.sent if s[0] == 'agents/propose']
    expanded = conversions.start_expansion('p', 'bob', {'project_id': 'p', **proposed['request']})
    operation = {'file:head': 'upload-runs/file', 'convert': 'upload-runs/convert', 'convert-original': 'upload-runs/convert-original'}
    sent = seen.steps()
    assert [n.replace('upload-runs/file', 'file:head').replace('upload-runs/', '') for n, _, _ in sent] == list(expanded)
    for (name, body, _), (step, request) in zip(sent, expanded.items()):
        op = operation.get(step, 'upload-runs/convert-output')
        assert gateway_agents.normal(op, body) == gateway_agents.normal(op, request), step
    assert landed(world, done['run_id']) == [('deviation', 'added'), ('tops', 'added')]
    assert [s for (s,) in world.rows('SELECT step FROM agent_covered WHERE plan=? ORDER BY at', done['plan'])] == list(expanded)
    assert world.used()['publications'] == 1
    [run] = world.bob.ok('upload-runs', 'list', {'project_id': 'p'})['runs']
    assert (run['run_id'], run['label']) == (done['run_id'], 'Finished')  # bob's own upload list shows his agent's read


def test_a_file_changed_after_approval_is_refused_before_sending(world, report, tmp_path):
    """t10: the original is read again after approval and must be the approved bytes; the upload receives nothing.
    Mutation: drop the digest check in `AgentRead._bytes` → the changed file is sent."""
    seen = Seen(world)
    run = reader(world, seen, report, tmp_path)
    decide = approve(world)

    def approve_then_change(seconds):
        decide(seconds)
        report.write_bytes(PDF.replace(b'HON-GT-01', b'HON-GT-02'))
    with pytest.raises(NotRun) as refused: run.read(sleep=approve_then_change)
    assert refused.value.code == 'read-file-changed'
    assert not [s for s in seen.sent if s[0].startswith('upload-runs/')], 'nothing of the upload left the computer'
    assert world.rows('SELECT count(*) FROM upload_runs') == [(0,)]


def test_a_step_whose_answer_was_lost_is_recovered_by_reading_again(world, report, tmp_path):
    """t10: the answer to the first output is lost after the gateway committed it. Reading again is the same plan (the
    saved start), every completed step is answered from agent_covered, and the procedure does not run again.
    Mutation: do not save agent-read.json → reading again runs the procedure and proposes another start."""
    lossy = Seen(world, lose='upload-runs/convert-output:tops')
    with pytest.raises(Unavailable): reader(world, lossy, report, tmp_path).read(sleep=approve(world))
    first = world.rows('SELECT step,answer FROM agent_covered ORDER BY at')
    assert [s for s, _ in first] == ['file:head', 'convert', 'convert-original', 'convert-output:tops']
    again = Seen(world)
    done = reader(world, again, report, tmp_path).read(sleep=approve(world))
    [(_, a, _)] = [s for s in lossy.sent if s[0] == 'agents/propose']
    [(_, b, _)] = [s for s in again.sent if s[0] == 'agents/propose']
    starts = [p for p in world.bob.ok('agents', 'plans', {})['plans'] if p['operation'] == 'upload-runs/start']
    assert a == b and len(starts) == 1, 'the same request: the same plan'
    assert runs_of(report) == ['HON-GT-01'], 'the procedure ran once; its saved outputs are sent again'
    assert world.rows('SELECT step,answer FROM agent_covered ORDER BY at')[:4] == first  # the done steps' rows and answers unchanged
    assert done['conversion']['state'] == 'complete' and landed(world, done['run_id']) == [('deviation', 'added'), ('tops', 'added')]
    assert world.used()['publications'] == 1


def test_an_expired_original_is_sent_again_once_and_the_rest_lands(world, report, tmp_path):
    """t11: the staged original expires before the second output; the gateway refuses it `original-expired`, AgentRead
    sends the original again once (answered with its stored first answer), and the output lands. Mutation: no re-send
    on original-expired → the read stops with the refusal."""
    seen = Seen(world, expire='upload-runs/convert-output:deviation')
    done = reader(world, seen, report, tmp_path).read(sleep=approve(world))
    assert [n for n, _, _ in seen.steps()] == ['upload-runs/file', 'upload-runs/convert', 'upload-runs/convert-original',
                                              'upload-runs/convert-output:tops', 'upload-runs/convert-output:deviation',
                                              'upload-runs/convert-original', 'upload-runs/convert-output:deviation']
    assert [raw for n, _, raw in seen.steps() if n == 'upload-runs/convert-original'] == [PDF, PDF]
    assert done['conversion']['state'] == 'complete' and landed(world, done['run_id']) == [('deviation', 'added'), ('tops', 'added')]
    assert world.rows('SELECT count(*) FROM upload_original_stages WHERE expires_at>?', time.time()) == [(0,)]  # complete: released
    assert world.rows("SELECT count(*) FROM agent_covered WHERE step='convert-original'") == [(1,)]


def test_a_version_neither_trusted_nor_the_agents_own_is_refused_before_anything_runs(web, report, tmp_path):
    """P-10: the trust check is unchanged (`intake._run`). The agent never sends procedures/trust; it gets trust-needed
    and nothing is proposed or uploaded. Mutation: trust from `_AgentCatalogue` (prompt answered yes) → the version is
    trusted by the agent and the read proceeds."""
    w = World(web, trusted=False)
    seen = Seen(w)
    with pytest.raises(NotRun) as refused: reader(w, seen, report, tmp_path).read(sleep=approve(w))
    assert refused.value.code == 'trust-needed' and refused.value.details == {'digest': w.d}
    assert [n for n, _, _ in seen.sent if not n.startswith('procedures/get') and not n.startswith('procedures/bundle')] == []
    assert runs_of(report) == [] and w.rows('SELECT count(*) FROM agent_plans') == [(0,)] and w.rows('SELECT count(*) FROM upload_runs') == [(0,)]
    assert w.rows("SELECT count(*) FROM procedure_trust") == [(0,)]
