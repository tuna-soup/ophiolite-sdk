"""E95 C6 against the in-process gateway (C2-C5): the library proposes with evidence, the person approves naming the
record and its generation, the agent waits for that approval and executes with X-Ophiolite-Evidence; a lost answer
recovers with the evidence block and never its text; a later record holds the agent's wait until it is approved."""
import json
import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401
from ophiolite.agents import AgentClient
from ophiolite.errors import Refused
from project_gateway.tests.test_one_api_matrix import Caller
from test_agent_evidence import EVIDENCE_16


def issue(web, policy=('applications/configure', 'applications/start')):
    alice = Caller(web, 'session', 'alice')
    issued = alice.ok('agents', 'register', {'name': 'Notebook agent', 'scopes': ['read', 'write'], 'budgets': {'runs': 3, 'publications': 2},
                                             'expires_in_days': 3, 'policy': list(policy)})
    return alice, AgentClient('https://workspace.example', 'p', issued['credential'], http=web.c)


def started(web, agent, suffix):
    binding = agent.run('applications/configure', {'name': 'Agent correction ' + suffix, 'release_id': web.r['id'], 'asset_index': 0, 'curve': 'GR',
                                                    'runners': ['alice'], 'command_id': 'cfg-' + suffix}, evidence=EVIDENCE_16)
    return agent.run('applications/start', {'id': binding['id'], 'generation': binding['generation'], 'command_id': 'run-' + suffix,
                                            'application_version': 'agent-script/1'}, evidence=EVIDENCE_16)


def pending(alice, plan):
    [found] = [p for p in alice.ok('agents', 'plans', {'state': 'pending'})['plans'] if p['hash'] == plan] or [None]
    return found


def test_propose_approve_with_the_record_execute_with_the_header_and_recover_without_text(web):
    alice, agent = issue(web)
    run = started(web, agent, 'a')  # the policy approves configure and start naming the record each proposal carried
    publish = {'id': run['id'], 'changes': [{'index': 0, 'value': 2}]}
    proposed = agent.propose('applications/publish', publish, 'Publish the corrected gamma ray', evidence=EVIDENCE_16)
    plan = pending(alice, proposed['hash'])
    assert proposed['evidence'] and plan['evidence'][0]['id'] == proposed['evidence'] and plan['evidence_generation'] == 1
    assert plan['evidence'][0]['instruction'] == EVIDENCE_16['instruction'] and plan['evidence'][0]['model']['id'] == 'claude-sonnet-5-5'
    alice.ok('agents', 'approve', {'hash': proposed['hash'], 'evidence': proposed['evidence'], 'evidence_generation': 1})
    assert agent.wait(proposed['hash'], evidence_id=proposed['evidence'], sleep=lambda s: None) == 'approved'
    agent.execute('applications/publish', publish, proposed['hash'], proposed['evidence'])  # the answer is "lost"
    recovered = agent.recover(plan=proposed['hash'])
    assert recovered['state'] == 'completed' and recovered['evidence']['id'] == proposed['evidence'] and recovered['evidence']['kept'] is True
    assert 'instruction' not in recovered['evidence'] and EVIDENCE_16['instruction'] not in json.dumps(recovered)


def test_the_legacy_approve_body_is_refused_naming_the_field(web):
    alice, agent = issue(web)
    run = started(web, agent, 'b')
    proposed = agent.propose('applications/publish', {'id': run['id'], 'changes': []}, evidence=EVIDENCE_16)
    refused = alice.post('agents', 'approve', {'hash': proposed['hash']})
    assert refused.status_code == 400 and 'evidence' in refused.text


def test_a_later_record_holds_the_wait_until_the_person_approves_it(web):
    alice, agent = issue(web)
    run = started(web, agent, 'c')
    publish = {'id': run['id'], 'changes': [{'index': 0, 'value': 2}]}
    first = agent.propose('applications/publish', publish, evidence=EVIDENCE_16)
    alice.ok('agents', 'approve', {'hash': first['hash'], 'evidence': first['evidence'], 'evidence_generation': 1})
    second = agent.propose('applications/publish', publish, evidence={**EVIDENCE_16, 'instruction': 'Publish it now, with the same change.'})
    assert second['hash'] == first['hash'] and second['evidence'] != first['evidence'] and second['approved'] is False
    polls = []
    def person(seconds):  # the agent's wait sleeps; the person approves B on the third poll (one client: no second thread)
        polls.append(seconds)
        if len(polls) == 3:
            alice.ok('agents', 'approve', {'hash': second['hash'], 'evidence': second['evidence'], 'evidence_generation': 2})
    assert agent.wait(second['hash'], evidence_id=second['evidence'], sleep=person) == 'approved' and len(polls) == 3
    agent.execute('applications/publish', publish, second['hash'], second['evidence'])
    assert agent.recover(plan=second['hash'])['evidence']['id'] == second['evidence']


def test_executing_with_a_record_the_approval_does_not_name_is_refused(web):
    alice, agent = issue(web)
    run = started(web, agent, 'd')
    publish = {'id': run['id'], 'changes': []}
    first = agent.propose('applications/publish', publish, evidence=EVIDENCE_16)
    alice.ok('agents', 'approve', {'hash': first['hash'], 'evidence': first['evidence'], 'evidence_generation': 1})
    second = agent.propose('applications/publish', publish, evidence={**EVIDENCE_16, 'instruction': 'Something else.'})
    with pytest.raises(Exception) as raised: agent.execute('applications/publish', publish, first['hash'], second['evidence'])
    assert getattr(raised.value, 'status', None) in (403, 409)
    with pytest.raises(Refused): agent.propose('las-uploads/upload', {}, evidence=EVIDENCE_16)
