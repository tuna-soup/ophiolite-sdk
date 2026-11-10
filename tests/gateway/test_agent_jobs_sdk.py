"""E151 s2 C2: a job's choice journey through the SDK against the in-process gateway. The agent's `run_job` raises
`ChoiceRequired`; the person's `Client.proposals()` lists the waiting job with its frozen question; `Client.answer`
resolves it; the agent's `resume(plan)` completes the job. The choice source is the test-only `harness/choose` step,
registered by GW/tests/test_agent_jobs_choice.py's `harness` fixture (never a route of the gateway, D5/F4)."""
import os
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web, shared, app, service, Caller  # noqa: F401 (fixtures)
    from project_gateway.tests.test_agents import register
    from project_gateway.tests.test_agent_jobs_choice import harness, three, OFFERED, HARNESS  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential
from ophiolite.agents import AgentClient
from ophiolite.errors import ChoiceRefused, ChoiceRequired, PermissionRefused

URL = 'https://workspace.example'
AGENT_REFUSED = 'agent-refused'  # the gateway's word for an agent credential on a person's operation (R-A2)


def person(web, persona='alice'):
    return Client(URL, 'p', Credential.bearer('oph_api_' + persona + ':read,write'), web.c)


def waiting(web, suffix):
    """An agent's run_job that the person approves while it waits, stopped at the harness step: (agent, credential,
    steps, the ChoiceRequired)."""
    issued = register(web, policy=[])
    agent = AgentClient(URL, 'p', issued['credential'], http=web.c)
    alice = person(web)
    approved = []
    def approve_once(seconds):  # the person finds the plan in proposals() and approves it while the agent waits
        if approved: return
        [pending] = [p for p in alice.proposals() if p['operation'] == 'jobs/run']
        assert 'question' not in pending and pending['evidence'] is None
        Caller(web, 'session', 'alice').ok('agents', 'approve', {'hash': pending['plan'], 'evidence': None, 'evidence_generation': 0})
        approved.append(pending['plan'])
    steps = three(web, suffix)
    with pytest.raises(ChoiceRequired) as asked: agent.run_job(steps, sleep=approve_once)
    assert approved == [asked.value.plan]
    return agent, issued['credential'], steps, asked.value


def test_the_agent_asks_the_person_answers_and_the_agent_resumes(web, harness):
    agent, _, steps, asked = waiting(web, 'sdk1')
    plan = asked.plan
    assert (asked.step, asked.code, asked.status, asked.complete) == (2, 'choice-required', 409, True)
    assert (asked.question, asked.choices, asked.why, asked.answered_by) == (OFFERED['question'], OFFERED['choices'], OFFERED['why'], OFFERED['answered_by'])
    alice = person(web)
    [listed] = [p for p in alice.proposals() if p['plan'] == plan]
    assert (listed['operation'], listed['question'], listed['choices'], listed['choice_token']) == ('jobs/run', OFFERED['question'], OFFERED['choices'], asked.choice_token)
    assert listed['review_url'].endswith('proposal=%s#agents' % plan)
    assert alice.answer(asked.choice_token, 'c2') == {'plan': plan, 'step': 2, 'state': 'running', 'choice': 'c2'}
    assert [p for p in alice.proposals() if p['plan'] == plan] == []  # running: nothing waits on the person
    answers = agent.resume(plan)
    assert len(answers) == 3 and answers[1] == {'option': 'second', 'note': 'as approved sdk1'}
    status = agent.job_status(plan)
    assert (status['state'], status['step'], [s['state'] for s in status['steps']]) == ('completed', 3, ['completed'] * 3)
    assert agent.resume(plan) == answers  # a completed job replays every step
    assert [spec['note'] for spec, _ in harness] == ['as approved sdk1'] * 2  # asked once, ran once after the answer
    with pytest.raises(ChoiceRefused) as used: alice.answer(asked.choice_token, 'c1')
    assert (used.value.code, used.value.status, used.value.details['reason']) == ('choice-refused', 403, 'token-used')


def test_another_person_and_the_agent_cannot_answer(web, harness):
    """R-A2: only the job's delegator answers, and an agent's credential reaches neither person operation."""
    agent, credential, _, asked = waiting(web, 'sdk2')
    with pytest.raises(ChoiceRefused) as foreign: person(web, 'bob').answer(asked.choice_token, 'c1')
    assert (foreign.value.code, foreign.value.status, foreign.value.details['reason']) == ('choice-refused', 403, 'not-the-delegator')
    as_agent = Client(URL, 'p', Credential.bearer(credential), web.c)
    with pytest.raises(PermissionRefused) as refused: as_agent.answer(asked.choice_token, 'c1')
    assert type(refused.value) is PermissionRefused and (refused.value.code, refused.value.status) == (AGENT_REFUSED, 403)
    with pytest.raises(PermissionRefused) as unread: as_agent.proposals()
    assert type(unread.value) is PermissionRefused and (unread.value.code, unread.value.status) == (AGENT_REFUSED, 403)
    status = agent.job_status(asked.plan)
    assert (status['state'], status['step'], status['choice_token']) == ('waiting', 2, asked.choice_token)  # nothing was taken
