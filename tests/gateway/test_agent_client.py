"""E5 scripted scenario through the SDK against the in-process gateway: an agent proposes,
its policy approves configure and start, the person approves publication, the response is
lost and recovered by command id, a replay changes nothing, revocation ends the agent."""
import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401
from ophiolite.agents import AgentClient, CommandOwned, BudgetExhausted, PlanDeclined
from ophiolite.errors import PermissionRefused
from project_gateway.tests.test_one_api_matrix import Caller


def test_propose_approve_publish_lose_the_response_and_recover(web):
    alice = Caller(web, 'session', 'alice')
    issued = alice.ok('agents', 'register', {'name': 'Notebook agent', 'scopes': ['read', 'write'], 'budgets': {'runs': 3, 'publications': 1},
                                             'expires_in_days': 3, 'policy': ['applications/configure', 'applications/start']})
    agent = AgentClient('https://workspace.example', 'p', issued['credential'], http=web.c)
    binding = agent.run('applications/configure', {'name': 'Agent correction', 'release_id': web.r['id'], 'asset_index': 0, 'curve': 'GR',
                                                    'runners': ['alice'], 'command_id': 'agent-cfg'})
    run = agent.run('applications/start', {'id': binding['id'], 'generation': binding['generation'], 'command_id': 'agent-run',
                                            'application_version': 'agent-script/1'})
    assert run['agent']['id'] == issued['id']
    publish = {'id': run['id'], 'changes': [{'index': 0, 'value': 2}]}
    decided = []
    def approve_once(seconds):  # the person approves while the agent waits
        if not decided:
            [plan] = alice.ok('agents', 'plans', {'state': 'pending'})['plans']
            alice.ok('agents', 'approve', {'hash': plan['hash']}); decided.append(plan['hash'])
    plan = agent.propose('applications/publish', publish, 'Publish the corrected gamma ray')['hash']
    assert agent.wait(plan, sleep=approve_once) == 'approved' and decided == [plan]
    agent.execute('applications/publish', publish, plan)  # the agent stops before using the answer
    recovered = agent.recover(plan=plan)
    assert recovered['state'] == 'completed' and recovered['response']['receipt']['identity'] == 'alice'
    assert agent.execute('applications/publish', publish, plan) == recovered['response']  # a replay, not a second publication
    assert agent.recover(command_id='agent-run')['run_id'] == run['id']
    with pytest.raises(BudgetExhausted):
        second = agent.run('applications/start', {'id': binding['id'], 'generation': binding['generation'], 'command_id': 'agent-run-2',
                                                   'application_version': 'agent-script/1'})
        pending = agent.propose('applications/publish', {'id': second['id'], 'changes': []})['hash']
        alice.ok('agents', 'approve', {'hash': pending})
        agent.execute('applications/publish', {'id': second['id'], 'changes': []}, pending)
    other = AgentClient('https://workspace.example', 'p', alice.ok('agents', 'register', {'name': 'Other', 'scopes': ['read', 'write'], 'budgets': {},
                                                                                        'expires_in_days': 1, 'policy': []})['credential'], http=web.c)
    with pytest.raises(CommandOwned): other.propose('applications/share', {'id': run['id'], 'audience': [], 'expected_generation': 1})
    declined = other.propose('applications/configure', {'name': 'x', 'release_id': web.r['id'], 'asset_index': 0, 'curve': 'GR', 'runners': ['alice'],
                                                         'command_id': 'other-cfg'})['hash']
    alice.ok('agents', 'decline', {'hash': declined})
    with pytest.raises(PlanDeclined): other.wait(declined, sleep=lambda s: None)
    alice.ok('agents', 'revoke', {'id': issued['id']})
    with pytest.raises(PermissionRefused): agent.read('applications/result-list')
