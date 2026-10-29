"""E111 C4 (slice 1), unit lane: how a covered step travels. The end-to-end tests (steps equal the approval's, a file
changed after approval, a lost answer, register through a plan) are in tests/gateway/test_agent_procedures.py."""
import base64
import json

import httpx
import pytest
from ophiolite.agents import CHANGES, AgentClient
from ophiolite.errors import Refused
from ophiolite.procedures import AgentRun


def test_a_step_travels_as_octet_stream_with_its_request_whole_in_the_upload_header():
    """Mutation: post the step as JSON (ignore `raw`) → no file bytes and no upload header reach the gateway."""
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'asset_id': 'a', 'revision': 'r'})
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))
    header = {'command_id': 'c' * 64, 'name': 'Shifted tops', 'run': {'id': 'run-1', 'role': 'shifted'}}
    assert agent.execute_step('publications/derive', header, 'a' * 64, 'ev-1', raw=b'name,md\n') == {'asset_id': 'a', 'revision': 'r'}
    [sent] = seen
    assert sent.url.path == '/api/v1/projects/p/publications/derive' and sent.content == b'name,md\n'
    assert sent.headers['content-type'] == 'application/octet-stream'
    assert (sent.headers['x-ophiolite-plan'], sent.headers['x-ophiolite-evidence']) == ('a' * 64, 'ev-1')
    assert json.loads(base64.b64decode(sent.headers['x-ophiolite-upload'])) == {'project_id': 'p', **header}
    assert {'procedures/register', 'procedure-runs/report'} <= set(CHANGES)


def test_a_run_needs_the_name_the_person_approves(tmp_path):
    with pytest.raises(Refused): AgentRun(None, tmp_path, name=' ')


def test_an_agent_proposes_an_upload_start_but_never_one_of_its_covered_steps():
    """E111 s2 (P-10): `upload-runs/start` is proposed; its file, convert and output steps are covered by that approval and
    never proposed alone. Mutation: drop 'upload-runs/start' from CHANGES → the start is refused before sending."""
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'hash': 'h' * 64, 'state': 'pending'})
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert agent.propose('upload-runs/start', {'command_id': 'c' * 64, 'reads': ['procedures']}, 'Read the report') == {'hash': 'h' * 64, 'state': 'pending'}
    [sent] = seen
    assert sent['operation'] == 'upload-runs/start' and sent['request'] == {'project_id': 'p', 'command_id': 'c' * 64, 'reads': ['procedures']}
    for covered in ('upload-runs/convert', 'upload-runs/file', 'upload-runs/convert-output', 'upload-runs/convert-original'):
        with pytest.raises(Refused): agent.propose(covered, {'run_id': 'r'})
    assert len(seen) == 1, 'a covered-only step never reaches the gateway as a proposal'


ONLY = ('Agents change application configurations, runs, publications, recipients, runner jobs, recalculations, procedure runs, '
        'deliveries as an outcome and trust in a procedure version only.')


@pytest.mark.parametrize('operation, request_', [
    ('outcomes/deliver-as', {'outcome_id': 'o-1', 'asset_id': 'a', 'revision': 'r', 'send': {'procedure_digest': 'd' * 64, 'label': 'Team database'},
                             'command_id': 'c-1'}),
    ('procedures/trust', {'command_id': 'trust-1', 'digest': 'd' * 64})])
def test_an_agent_proposes_a_delivery_as_an_outcome_and_trust_in_a_version(operation, request_):
    """E111 s4b t1 (R4-10). Mutation: drop the operation from CHANGES → refused before sending."""
    seen = []
    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={'hash': 'h' * 64, 'state': 'pending'})
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert agent.propose(operation, request_, 'Deliver or trust') == {'hash': 'h' * 64, 'state': 'pending'}
    assert seen == [('/api/v1/projects/p/agents/propose', {'project_id': 'p', 'operation': operation, 'request': {'project_id': 'p', **request_}, 'summary': 'Deliver or trust'})]


def test_an_operation_agents_do_not_change_is_refused_before_sending_in_the_listed_words():
    """E111 s4b t2: enabling a version stays a person's. Mutation: the old sentence → red."""
    seen = []
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r))))
    with pytest.raises(Refused) as caught: agent.propose('procedures/enable', {'command_id': 'e-1', 'digest': 'd' * 64})
    assert str(caught.value) == ONLY and seen == []


# E111 s2 (P-10, t10, t11): AgentRead over a recording fake transport. The procedure's local run (`intake._run`) is a
# stand-in that writes two outputs into an attempt folder; the live start is tests/gateway/test_agent_read.py (part 2).
import hashlib

import ophiolite.intake as intake
from ophiolite.errors import IntegrityConflict, Unavailable
from ophiolite.procedures import HEAD, AgentRead, NotRun

VERSION, RUN, PLAN = 'd' * 64, 'e' * 64, 'f' * 64
OUTPUTS = {'tops': b'name,md\nChalk,1200\n', 'deviation': b'md,inc,azi\n0,0,0\n'}


def sha(raw): return hashlib.sha256(raw).hexdigest()


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))


def expansion(project, request, run_id):
    """The gateway's closed step set for an approved start (Platform conversions.start_expansion and start_bytes), written
    out here: step → (its request in full, the bytes it names)."""
    at, c = {'project_id': project, 'run_id': run_id, 'ordinal': 0}, request['conversion']
    steps = {'file:head': ({**at, 'mode': 'head', 'reads': ['procedures']}, c['head']),
             'convert': ({**at, **{k: v for k, v in c.items() if k != 'head'}}, None)}
    if c['keep_original']: steps['convert-original'] = (dict(at), c['original'])
    for r in c['roles']: steps['convert-output:' + r['role']] = ({**at, 'role': r['role']}, {'bytes': r['bytes'], 'sha256': r['sha256']})
    return steps


class Gateway:
    """Records every request; `lose` names a step whose first answer is lost, `expire` the output step whose first try
    answers original-expired."""

    def __init__(self, lose=None, expire=None):
        self.sent, self.lose, self.expire = [], lose, expire

    def __call__(self, request):
        op = '/'.join(request.url.path.split('/')[-2:])
        if request.headers.get('content-type') == 'application/octet-stream':
            body, raw = json.loads(base64.b64decode(request.headers['x-ophiolite-upload'])), request.content
        else: body, raw = json.loads(request.content), None
        self.sent.append({'op': op, 'body': body, 'raw': raw, 'plan': request.headers.get('x-ophiolite-plan')})
        step = op + (':' + body['role'] if op == 'upload-runs/convert-output' else '')
        if step == self.lose: self.lose = None; raise httpx.ReadError('lost', request=request)
        if step == self.expire:
            self.expire = None
            return httpx.Response(409, json={'error': 'The original file sent to be kept was removed after a long wait.', 'code': 'conversion-refused', 'reason': 'original-expired'})
        if op == 'agents/propose': return httpx.Response(200, json={'hash': PLAN, 'state': 'pending'})
        if op == 'agents/status': return httpx.Response(200, json={'state': 'approved'})
        if op == 'upload-runs/start': return httpx.Response(200, json={'run_id': RUN, 'state': 'running'})
        return httpx.Response(200, json={'run_id': RUN, 'conversion': {'state': 'declared', 'roles': []}})

    def steps(self): return [s for s in self.sent if s['op'].startswith('upload-runs/') and s['op'] != 'upload-runs/start']


@pytest.fixture
def local(tmp_path, monkeypatch):
    """A PDF to read and a stand-in for the procedure's run on this computer (counted)."""
    pdf = tmp_path / 'end of well report.pdf'
    pdf.write_bytes(b'%PDF-1.7\n' + b'%' * (HEAD + 100))
    runs = []
    def run(client, row, path, state, version, settings, prompt, yes, cache, keep_original=False):
        runs.append(row)
        attempt = state / ('attempt-%d' % len(runs)); attempt.mkdir(parents=True)
        for role, raw in OUTPUTS.items(): (attempt / (role + '.csv')).write_bytes(raw)
        roles = [{'role': role, 'sha256': sha(raw), 'bytes': len(raw), 'name': role + '.csv', 'declared': {}} for role, raw in OUTPUTS.items()]
        return {'attempt': attempt.name, 'outputs': {role: role + '.csv' for role in OUTPUTS},
                'body': {'project_id': client.project, 'run_id': None, 'ordinal': 0, 'command_id': 'c' * 32, 'procedure': {'digest': row['procedures'][0]['digest']},
                         'original': {'sha256': row['sha256'], 'bytes': row['bytes']}, 'roles': roles, 'keep_original': bool(keep_original), 'settings': {}}}
    monkeypatch.setattr(intake, '_run', run)
    return {'pdf': pdf, 'runs': runs, 'state': tmp_path / 'state'}


def reader(local, gateway, keep=True):
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(gateway)))
    return AgentRead(agent, local['pdf'], version=VERSION, attribution='NLOG.NL', keep_original=keep, folder=local['state'])


@pytest.mark.parametrize('keep', [True, False])
def test_t10_the_steps_sent_equal_the_steps_the_approval_names(local, keep):
    """Mutations: send the outputs before the original; put the head into the convert step → a sent step differs from
    the approval's (the gateway would refuse it as not covered)."""
    gateway = Gateway()
    done = reader(local, gateway, keep).read('Read the end of well report', sleep=lambda _: None)
    [proposed] = [s['body'] for s in gateway.sent if s['op'] == 'agents/propose']
    request = proposed['request']
    assert proposed['operation'] == 'upload-runs/start' and request['rights_confirmed'] is True and request['reads'] == ['procedures']
    pdf = local['pdf'].read_bytes()
    assert request['files'] == [{'path': 'end of well report.pdf', 'bytes': len(pdf), 'sha256': sha(pdf)}]
    assert request['conversion']['head'] == {'bytes': HEAD, 'sha256': sha(pdf[:HEAD])}
    assert request['conversion']['original'] == {'bytes': len(pdf), 'sha256': sha(pdf)}
    expected = expansion('p', request, RUN)
    sent = gateway.steps()
    assert [canonical(s['body']) for s in sent] == [canonical(body) for body, _ in expected.values()]  # in the approval's order
    for s, (_, named) in zip(sent, expected.values()):
        assert s['plan'] == PLAN
        assert (s['raw'] is None) == (named is None)
        if named is not None: assert {'bytes': len(s['raw']), 'sha256': sha(s['raw'])} == named
    [start] = [s for s in gateway.sent if s['op'] == 'upload-runs/start']
    assert canonical(start['body']) == canonical(request) and start['plan'] == PLAN
    assert done['plan'] == PLAN and done['run_id'] == RUN


@pytest.mark.parametrize('changed', ['original', 'output'])
def test_t10_a_file_changed_after_approval_is_refused_before_sending(local, changed):
    """Mutation: drop the original's digest check in `AgentRead._bytes` → the changed file is sent."""
    gateway = Gateway()
    def approve_then_change(_):
        if changed == 'original': local['pdf'].write_bytes(b'%PDF-1.7\nanother report')
        else: (local['state'].glob('*/attempt-1/tops.csv').__next__()).write_bytes(b'name,md\nChalk,9999\n')
    run = reader(local, gateway)
    original_wait = run.agent.wait
    run.agent.wait = lambda plan, **kw: (approve_then_change(None), original_wait(plan, **kw))[1]
    with pytest.raises(NotRun) as refused: run.read(sleep=lambda _: None)
    assert refused.value.code == ('read-file-changed' if changed == 'original' else 'saved-output-changed')
    assert not [s for s in gateway.sent if s['op'].startswith('upload-runs/')], 'nothing of the upload left the computer'


def test_t10_a_step_whose_answer_was_lost_is_recovered_by_reading_again(local):
    """Mutation: agent-read.json not saved → reading again runs the procedure again and proposes another command."""
    lossy = Gateway(lose='upload-runs/convert-output:tops')
    with pytest.raises(Unavailable): reader(local, lossy).read(sleep=lambda _: None)
    again = Gateway()
    done = reader(local, again).read(sleep=lambda _: None)
    [first] = [s['body'] for s in lossy.sent if s['op'] == 'agents/propose']
    [second] = [s['body'] for s in again.sent if s['op'] == 'agents/propose']
    assert canonical(first) == canonical(second), 'the same request: the same plan'
    assert len(local['runs']) == 1, 'the procedure ran once; its saved outputs are sent again'
    assert [s['body'] for s in again.steps()][:len(lossy.steps())] == [s['body'] for s in lossy.steps()], 'each step is sent again as it was'
    assert done['run_id'] == RUN and again.steps()[-1]['body']['role'] == 'deviation'


def test_t11_an_expired_original_is_sent_again_once_and_the_rest_lands(local):
    """Mutations: no re-send on original-expired → the read stops; re-send before every later output → three originals."""
    gateway = Gateway(expire='upload-runs/convert-output:tops')
    reader(local, gateway).read(sleep=lambda _: None)
    ops = [s['op'] + (':' + s['body']['role'] if 'role' in s['body'] else '') for s in gateway.steps()]
    assert ops == ['upload-runs/file', 'upload-runs/convert', 'upload-runs/convert-original', 'upload-runs/convert-output:tops',
                   'upload-runs/convert-original', 'upload-runs/convert-output:tops', 'upload-runs/convert-output:deviation']
    pdf = local['pdf'].read_bytes()
    assert [s['raw'] for s in gateway.steps() if s['op'] == 'upload-runs/convert-original'] == [pdf, pdf]


def test_t11_a_second_expiry_is_not_sent_again(local):
    """The original is sent again once per read; a second expiry is the deployment's refusal."""
    gateway = Gateway(expire='upload-runs/convert-output:tops')
    real = gateway.__call__
    def twice(request):
        answer = real(request)
        if '/convert-output' in request.url.path and json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))['role'] == 'deviation':
            return httpx.Response(409, json={'error': 'expired', 'code': 'conversion-refused', 'reason': 'original-expired'})
        return answer
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(twice)))
    with pytest.raises(IntegrityConflict): AgentRead(agent, local['pdf'], version=VERSION, attribution='NLOG.NL', keep_original=True, folder=local['state']).read(sleep=lambda _: None)
    assert [s['op'] for s in gateway.sent].count('upload-runs/convert-original') == 2


def test_a_read_names_its_version():
    with pytest.raises(NotRun) as refused: AgentRead(None, 'x.pdf', version='latest')
    assert refused.value.code == 'read-version'


@pytest.mark.parametrize('settings,code', [({}, 'read-attribution'), ({'attribution': ' '}, 'read-attribution'),
                                           ({'attribution': 'NLOG.NL', 'audience': 'alice'}, 'read-audience')])
def test_a_read_names_its_attribution_and_audience(settings, code):
    """An agent's start never takes the project's defaults (a person checks those, E90). Mutation: drop the attribution
    check → the read is built and the gateway refuses the start (defaults-changed)."""
    with pytest.raises(NotRun) as refused: AgentRead(None, 'x.pdf', version=VERSION, **settings)
    assert refused.value.code == code


def test_the_start_names_the_attribution_and_audience_given(local):
    agent = AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(Gateway())))
    request, _, _ = AgentRead(agent, local['pdf'], version=VERSION, attribution='NLOG.NL', audience=['alice'], folder=local['state']).request()
    assert (request['attribution'], request['audience']) == ('NLOG.NL', ['alice'])
