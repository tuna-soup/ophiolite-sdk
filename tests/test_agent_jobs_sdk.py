"""E151 s2 C1: AgentClient proposes, runs and resumes a job. A recording fake of the gateway's job routes answers as
GW/agent_jobs.py does: a completed step called again with its command id answers its stored answer and runs nothing;
another id is command-owned; a step whose decision is open answers choice-required."""
import copy
import inspect
import json
from pathlib import Path
import httpx
import pytest
from ophiolite import agents
from ophiolite.agents import AgentClient, CommandOwned, PlanDeclined, PlanExpired
from ophiolite.errors import ChoiceRequired, IntegrityConflict, PermissionRefused, Refused, VerificationFailed

V1 = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'agents' / 'v1'
CHOICE = json.loads((V1 / 'fixtures' / 'valid' / 'choice.json').read_text())
PLAN, OTHER = 'a1' * 32, 'b2' * 32
ID1, ID2 = '271c5d91-4307-57c1-aa7d-532a186d3f49', '5c96cb90-0090-5eca-a86c-f46b539b71a5'  # uuid5(NAMESPACE, PLAN:1), PLAN:2
STEPS = [{'operation': 'applications/configure', 'body': {'id': 'binding-1', 'settings': {'mode': 'quick'}}},
         {'operation': 'applications/start', 'body': {'id': 'binding-1', 'generation': 1, 'input': {'$step': 1, 'pointer': '/id'}}}]


class Gateway:
    """The job routes of one project `p`. `plan_state` is agents/status's; `choice` the step whose decision is open."""

    def __init__(self, steps=2, *, plan_state='consumed', evidence=None, choice=None):
        self.n, self.plan_state, self.evidence, self.choice = steps, plan_state, evidence, choice
        self.stored, self.executed, self.requests, self.job, self.word = {}, [], [], None, None
        self.lose = set()  # steps whose answer is lost on the way back once (the step still completes)

    def status(self):
        done = [i for i in range(1, self.n + 1) if i in self.stored]
        if self.job is not None: state, step = self.job
        elif len(done) == self.n: state, step = 'completed', self.n
        elif self.choice == len(done) + 1: state, step = 'waiting', self.choice
        else: state, step = 'running', len(done) + 1
        return {'plan': PLAN, 'state': state, 'step': step, **({'word': self.word} if self.job else {}),
                'steps': [{'operation': 'applications/configure', 'state': 'completed' if i in self.stored else 'pending',
                           'answer_sha256': ('%02d' % i) * 32 if i in self.stored else None} for i in range(1, self.n + 1)],
                'review_url': 'https://workspace.example/project/p/settings?proposal=%s#agents' % PLAN}

    def __call__(self, request):
        route, body = request.url.path.split('/projects/p/')[1], json.loads(request.content)
        evidence = request.headers.get('x-ophiolite-evidence')
        if route == 'jobs/step':
            self.requests.append((route, body['step'], body['command_id'], evidence))
            i, command = body['step'], body['command_id']
            if i in self.stored:
                if self.stored[i][0] != command: return refusal(409, 'command-owned')
                if self.stored[i][1] is None: return refusal(409, 'command-owned')
                return httpx.Response(200, json=self.stored[i][1])
            if self.choice == i: return httpx.Response(409, json=CHOICE)
            if self.status()['state'] != 'running' or self.status()['step'] != i: return refusal(400, 'INVALID_ARGUMENT')
            self.executed.append(i)
            self.stored[i] = (command, {'step': i, 'ran': True})
            if i in self.lose:
                self.lose.discard(i)
                raise httpx.ReadTimeout('lost')
            return httpx.Response(200, json=self.stored[i][1])
        self.requests.append((route, body, evidence))
        if route == 'jobs/propose': return httpx.Response(200, json={'hash': PLAN, 'state': 'pending', **({'evidence': 'ev-1', 'approved': True} if 'evidence' in body else {})})
        if route == 'agents/status': return httpx.Response(200, json={'hash': PLAN, 'state': self.plan_state, 'evidence_approved': self.evidence})
        if route == 'jobs/status': return httpx.Response(200, json=self.status())
        return refusal(404, 'not-found')


def refusal(status, code):
    return httpx.Response(status, json={'error': code, 'code': code, 'message': 'Refused by the gateway: ' + code})


def client(handler):
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))


def steps_sent(gateway):
    return [(r[1], r[2]) for r in gateway.requests if r[0] == 'jobs/step']


def routes(gateway):
    return [r[0] for r in gateway.requests]


def test_the_propose_body_names_the_project_and_keeps_the_callers_dicts():
    gateway = Gateway()
    mine = copy.deepcopy(STEPS)
    mine[1]['body']['project_id'] = 'p'
    before = copy.deepcopy(mine)
    proposed = client(gateway).propose_job(mine, evidence={'instruction': 'Configure and start binding-1.', 'client': 'example/1'})
    route, body, _ = gateway.requests[0]
    assert route == 'jobs/propose' and proposed['hash'] == PLAN
    assert body == {'project_id': 'p', 'evidence': {'instruction': 'Configure and start binding-1.', 'client': 'example/1'},
                    'steps': [{'operation': 'applications/configure', 'body': {'id': 'binding-1', 'settings': {'mode': 'quick'}, 'project_id': 'p'}},
                              {'operation': 'applications/start', 'body': {'id': 'binding-1', 'generation': 1, 'input': {'$step': 1, 'pointer': '/id'}, 'project_id': 'p'}}]}
    assert mine == before and 'project_id' not in mine[0]['body']  # the caller's dicts are never changed


@pytest.mark.parametrize('steps', [[], [STEPS[0]] * 9, 'applications/start', [{'operation': 'applications/start'}],
                                   [{'operation': 'applications/start', 'body': []}], [{'body': {}}],
                                   [STEPS[0], {'operation': 'applications/start', 'body': {'project_id': 'other'}}]],
                         ids=['none', 'nine', 'not-a-list', 'no-body', 'body-not-object', 'no-operation', 'another-project'])
def test_local_refusals_send_no_request(steps):
    """Mutation: the project check dropped → 'another-project' sends jobs/propose."""
    gateway = Gateway()
    with pytest.raises(Refused) as refused: client(gateway).propose_job(steps)
    assert isinstance(refused.value, ValueError) and gateway.requests == []
    with pytest.raises(Refused): client(gateway).run_job(steps)
    assert gateway.requests == []


def test_eligibility_is_the_gateways_word():
    """With the local check passed (an operation the SDK does not judge), the gateway's own refusal arrives unchanged."""
    agent = client(lambda r: refusal(403, 'agent-refused'))
    with pytest.raises(PermissionRefused) as refused: agent.propose_job([{'operation': 'las-uploads/upload', 'body': {}}])
    assert refused.value.code == 'agent-refused' and refused.value.status == 403


def test_command_ids_are_literal_stable_and_distinct():
    """Mutation: a random command id → the literal ids differ."""
    seen = []
    def handler(request):
        seen.append(json.loads(request.content)['command_id']); return httpx.Response(200, json={})
    for _ in range(2):
        agent = client(handler)
        agent.step(PLAN, 1); agent.step(PLAN, 1); agent.step(PLAN, 2); agent.step(OTHER, 1)
    assert seen == [ID1, ID1, ID2, '897d501d-820d-5551-bc2d-e99056d21fae'] * 2
    assert str(agents.NAMESPACE) == 'f527b633-0784-5370-8bbf-06ac165826a8'
    client(handler).step(PLAN, 1, command_id='mine-1')
    assert seen[-1] == 'mine-1'


def test_a_fresh_run_proposes_waits_and_runs_each_step_in_order():
    gateway = Gateway()
    answers = client(gateway).run_job(STEPS, sleep=lambda s: None)
    assert answers == [{'step': 1, 'ran': True}, {'step': 2, 'ran': True}] and gateway.executed == [1, 2]
    assert routes(gateway) == ['jobs/propose', 'agents/status', 'jobs/status', 'jobs/step', 'jobs/step']
    assert steps_sent(gateway) == [(1, ID1), (2, ID2)]


def test_a_choice_raises_with_plan_and_step_then_resume_replays_and_runs_on():
    """Mutations: plan and step not set on ChoiceRequired → the attributes are missing; resume re-running completed steps
    under new ids from step 1 → the exact sequence differs (and the gateway answers command-owned)."""
    gateway = Gateway(choice=2)
    with pytest.raises(ChoiceRequired) as asked: client(gateway).run_job(STEPS, sleep=lambda s: None)
    error = asked.value
    assert (error.plan, error.step) == (PLAN, 2) and error.complete and isinstance(error, IntegrityConflict)
    assert error.choice_token == CHOICE['choice_token'] and error.question == CHOICE['question'] and error.why == CHOICE['why']
    assert gateway.executed == [1]
    gateway.choice, gateway.requests = None, []  # the person answered in Workspace
    answers = client(gateway).resume(PLAN)  # a new client: a restarted process
    assert answers == [{'step': 1, 'ran': True}, {'step': 2, 'ran': True}]
    assert routes(gateway) == ['agents/status', 'jobs/status', 'jobs/step', 'jobs/step']
    assert steps_sent(gateway) == [(1, ID1), (2, ID2)] and gateway.executed == [1, 2]  # step 1 replayed, step 2 ran once


def test_resuming_a_completed_job_replays_every_step_and_runs_nothing():
    gateway = Gateway()
    first = client(gateway).run_job(STEPS, sleep=lambda s: None)
    gateway.requests = []
    assert client(gateway).resume(PLAN) == first and client(gateway).run_job(STEPS, sleep=lambda s: None) == first
    assert steps_sent(gateway) == [(1, ID1), (2, ID2)] * 2 and gateway.executed == [1, 2]
    assert routes(gateway) == ['agents/status', 'jobs/status', 'jobs/step', 'jobs/step',
                               'jobs/propose', 'agents/status', 'jobs/status', 'jobs/step', 'jobs/step']


def test_evidence_travels_on_every_step_and_resume_reads_the_approvals():
    gateway = Gateway(evidence='ev-1')
    client(gateway).run_job(STEPS, evidence={'instruction': 'Configure and start binding-1.'}, sleep=lambda s: None)
    assert [r[3] for r in gateway.requests if r[0] == 'jobs/step'] == ['ev-1', 'ev-1']
    gateway.requests = []
    client(gateway).resume(PLAN)
    assert [r[3] for r in gateway.requests if r[0] == 'jobs/step'] == ['ev-1', 'ev-1']


def test_a_changed_evidence_generation_is_the_gateways_word():
    def handler(request):
        if request.url.path.endswith('jobs/step'): return refusal(403, 'plan-required')
        return Gateway(evidence='ev-1')(request)
    with pytest.raises(PermissionRefused) as refused: client(handler).resume(PLAN)
    assert refused.value.code == 'plan-required'


def test_a_timeout_then_resume():
    gateway = Gateway(plan_state='pending')
    ticks = iter([0, 5, 11])
    with pytest.raises(PlanExpired) as waited: client(gateway).run_job(STEPS, timeout=10, clock=lambda: next(ticks), sleep=lambda s: None)
    assert waited.value.code == 'plan-pending' and gateway.executed == []
    gateway.plan_state, gateway.requests = 'consumed', []
    assert len(client(gateway).resume(PLAN, sleep=lambda s: None)) == 2 and steps_sent(gateway) == [(1, ID1), (2, ID2)]


@pytest.mark.parametrize('state,word,kind,code', [('declined', None, PlanDeclined, 'plan-declined'), ('expired', None, PlanExpired, 'plan-expired'),
                                                  ('released', 'declined', PlanDeclined, 'plan-declined'), ('released', 'expired', PlanExpired, 'plan-expired'),
                                                  ('released', 'cancelled', Refused, 'cancelled'), ('failed', 'command-owned', CommandOwned, 'command-owned'),
                                                  ('failed', 'step-failed', Refused, 'step-failed')])
def test_a_released_or_failed_job_raises_and_runs_nothing(state, word, kind, code):
    gateway = Gateway()
    gateway.job, gateway.word = (state, 2), word
    if word is None: gateway.job = None; gateway.status = lambda: {**Gateway.status(gateway), 'state': state, 'step': 1}
    with pytest.raises(kind) as raised: client(gateway).resume(PLAN)
    assert type(raised.value) is kind and raised.value.code == code and steps_sent(gateway) == []


def test_a_release_between_status_and_step_is_the_gateways_refusal():
    gateway = Gateway()
    real = gateway.__call__
    def handler(request):
        if request.url.path.endswith('jobs/status'):
            answer = real(request); gateway.job, gateway.word = ('released', 1), 'declined'; return answer
        return real(request)
    with pytest.raises(Refused) as refused: client(handler).resume(PLAN)
    assert refused.value.code == 'INVALID_ARGUMENT' and steps_sent(gateway) == [(1, ID1)] and gateway.executed == []


def test_a_lost_response_is_retried_by_its_id():
    gateway = Gateway()
    gateway.lose = {1}
    with pytest.raises(Exception) as lost: client(gateway).run_job(STEPS, sleep=lambda s: None)
    assert lost.value.code == 'unreachable' and gateway.executed == [1]
    assert client(gateway).resume(PLAN) == [{'step': 1, 'ran': True}, {'step': 2, 'ran': True}]
    assert steps_sent(gateway) == [(1, ID1), (1, ID1), (2, ID2)] and gateway.executed == [1, 2]


def test_a_completed_step_whose_answer_was_never_stored_is_command_owned():
    gateway = Gateway()
    gateway.stored[1] = (ID1, None)
    with pytest.raises(CommandOwned) as owned: client(gateway).resume(PLAN)
    assert owned.value.code == 'command-owned' and gateway.executed == []


@pytest.mark.parametrize('change', [lambda s: s.pop('review_url'), lambda s: s.update(state='finished'), lambda s: s.update(step=9),
                                    lambda s: s['steps'][0].update(state='done'), lambda s: s.update(plan=OTHER)],
                         ids=['no-review-url', 'state', 'step', 'step-state', 'other-plan'])
def test_a_malformed_status_is_verification_failed(change):
    """Mutation: the status validation removed → the malformed answer passes. (E187 s0: an added field is no longer
    malformed; tests/test_answer_models.py reads it.)"""
    gateway = Gateway()
    def handler(request):
        if request.url.path.endswith('jobs/status'):
            answer = gateway.status(); change(answer); return httpx.Response(200, json=answer)
        return gateway(request)
    with pytest.raises(VerificationFailed): client(handler).job_status(PLAN)
    with pytest.raises(VerificationFailed): client(handler).resume(PLAN)
    assert steps_sent(gateway) == []


@pytest.mark.parametrize('model,where', [(agents.JobStatus, None), (agents.JobStep, 'step'), (agents.JobChoice, 'choice')])
def test_the_status_model_mirrors_the_synced_schema(model, where):
    """Mutation: a field dropped from JobStatus or JobStep → red. The check needs no `validation` extra."""
    document = json.loads((V1 / 'job-schema.json').read_text())
    schema = document['$defs'][where] if where else document
    fields = {f.alias or name for name, f in model.model_fields.items()}
    required = {f.alias or name for name, f in model.model_fields.items() if f.is_required()}
    assert fields == set(schema['properties']), fields ^ set(schema['properties'])
    assert required == set(schema.get('required', [])), required ^ set(schema.get('required', []))
    assert set(model.model_fields['state'].annotation.__args__) == set(schema['properties']['state']['enum']) if 'state' in schema['properties'] else True


def test_the_status_fixture_is_valid():
    fixture = json.loads((V1 / 'fixtures' / 'valid' / 'job.json').read_text())
    assert client(lambda r: httpx.Response(200, json=fixture)).job_status(fixture['plan']) == fixture
    waiting = {**fixture, 'state': 'waiting', 'question': CHOICE['question'], 'choices': CHOICE['choices'], 'choice_token': CHOICE['choice_token']}
    assert client(lambda r: httpx.Response(200, json=waiting)).job_status(fixture['plan']) == waiting
    for null in ('word', 'question'):  # absent, never null
        with pytest.raises(VerificationFailed): client(lambda r: httpx.Response(200, json={**fixture, null: None})).job_status(fixture['plan'])


def test_a_choice_keeps_its_bounded_fields_and_complete_when_plan_and_step_are_added():
    incomplete = {**CHOICE, 'question': 'x' * 301}
    with pytest.raises(ChoiceRequired) as asked: client(lambda r: httpx.Response(409, json=incomplete)).step(PLAN, 3)
    error = asked.value
    assert (error.plan, error.step) == (PLAN, 3) and error.question is None and not error.complete
    assert error.choices == CHOICE['choices'] and error.answered_by == 'person'


def test_the_runner_reader_and_changes_are_unchanged():
    seen = []
    def handler(request):
        seen.append((request.url.path, json.loads(request.content))); return httpx.Response(200, json={'id': 'j', 'state': 'queued'})
    assert client(handler).job('j') == {'id': 'j', 'state': 'queued'}
    assert seen == [('/api/v1/projects/p/runners/job', {'project_id': 'p', 'id': 'j'})]
    assert list(inspect.signature(AgentClient.job).parameters) == ['self', 'job_id']
    assert len(agents.CHANGES) == 33 and not any(c.startswith('jobs/') for c in agents.CHANGES)  # E191 s0: attachments/add; E222 s0: documents/add
