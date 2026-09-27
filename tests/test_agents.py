"""The agent client maps gateway answers to stable errors and waits without busy loops."""
import httpx
import pytest
from ophiolite.agents import AgentClient, PlanDeclined, PlanExpired, BudgetExhausted, CommandOwned
from ophiolite.errors import AuthenticationRequired, PermissionRefused, Refused


def client(handler):
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_credential_shape_and_plan_header():
    with pytest.raises(AuthenticationRequired): AgentClient('https://x.example', 'p', 'oph_api_wrong')
    seen = []
    def handler(request):
        seen.append((request.url.path, request.headers.get('authorization'), request.headers.get('x-ophiolite-plan'), request.content))
        return httpx.Response(200, json={'ok': True})
    agent = client(handler)
    agent.execute('applications/start', {'id': 'b'}, 'a' * 64)
    assert seen[0][:3] == ('/api/v1/projects/p/applications/start', 'Bearer oph_agent_test', 'a' * 64)
    assert b'"project_id":"p"' in seen[0][3].replace(b' ', b'')
    with pytest.raises(Refused): agent.propose('las-uploads/upload', {})
    with pytest.raises(Refused): agent.recover()


@pytest.mark.parametrize('status,code,kind', [(429, 'budget-exhausted', BudgetExhausted), (409, 'command-owned', CommandOwned),
                                              (403, 'plan-required', PermissionRefused), (403, 'agent-refused', PermissionRefused)])
def test_errors(status, code, kind):
    agent = client(lambda r: httpx.Response(status, json={'error': 'no', 'code': code}))
    with pytest.raises(kind) as raised: agent.execute('applications/start', {}, 'a' * 64)
    assert raised.value.code == code and raised.value.status == status


def test_wait_returns_on_approval_and_raises_on_decline_expiry_or_timeout():
    states = iter(['pending', 'pending', 'approved'])
    slept = []
    agent = client(lambda r: httpx.Response(200, json={'state': next(states)}))
    assert agent.wait('h', sleep=slept.append, interval=7) == 'approved' and slept == [7, 7]
    for state, error in (('declined', PlanDeclined), ('expired', PlanExpired)):
        with pytest.raises(error): client(lambda r, s=state: httpx.Response(200, json={'state': s})).wait('h', sleep=lambda s: None)
    ticks = iter([0, 5, 11])
    with pytest.raises(PlanExpired) as waited:
        client(lambda r: httpx.Response(200, json={'state': 'pending'})).wait('h', timeout=10, clock=lambda: next(ticks), sleep=lambda s: None)
    assert waited.value.code == 'plan-pending'


def test_runner_jobs_are_agent_changes_and_readable():
    seen = []
    def handler(request):
        seen.append(request.url.path); return httpx.Response(200, json={'id': 'j', 'state': 'queued'})
    agent = client(handler)
    agent.propose('runners/submit', {'run_id': 'r', 'script': 'print(1)', 'command_id': 'c'})
    assert agent.job('j')['state'] == 'queued'
    assert seen == ['/api/v1/projects/p/agents/propose', '/api/v1/projects/p/runners/job']
