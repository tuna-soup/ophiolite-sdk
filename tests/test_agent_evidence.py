"""E95 C6: the library sends the evidence an agent reports, names the record when it executes, waits for the approval
that names it, and accepts E94's recalculation; nothing extra travels without evidence and nothing is retried."""
import json
import threading
import time
from pathlib import Path
import httpx
import pytest
from ophiolite.agents import AgentClient, CHANGES
from ophiolite.errors import Refused, IntegrityConflict

EVIDENCE_16 = {'instruction': 'Tidy the gamma ray of HON-GT-01 and publish the corrected curve.',
               'model': {'provider': 'anthropic', 'id': 'claude-sonnet-5-5'},
               'conversation': {'kind': 'notebook', 'reference': 'thread-4471'}, 'client': 'well-tidy/0.3'}
ROOT = Path(__file__).resolve().parents[1]


def recording(answers):
    seen = []
    def handler(request):
        seen.append(request)
        return answers(request) if callable(answers) else httpx.Response(200, json=answers)
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler))), seen


def test_propose_posts_the_five_fields_and_execute_names_the_record():
    agent, seen = recording({'hash': 'h' * 64, 'state': 'pending', 'evidence': 'ev-1', 'approved': False})
    answer = agent.propose('applications/publish', {'id': 'run-1'}, 'Publish', evidence=EVIDENCE_16)
    body = json.loads(seen[0].content)
    assert body['evidence'] == {'instruction': 'Tidy the gamma ray of HON-GT-01 and publish the corrected curve.',
                                'model': {'provider': 'anthropic', 'id': 'claude-sonnet-5-5'},
                                'conversation': {'kind': 'notebook', 'reference': 'thread-4471'}, 'client': 'well-tidy/0.3'}
    agent.execute('applications/publish', {'id': 'run-1'}, answer['hash'], answer['evidence'])
    assert seen[1].headers['x-ophiolite-evidence'] == 'ev-1' and seen[1].headers['x-ophiolite-plan'] == 'h' * 64


def test_label_fields_travel_when_given():
    agent, seen = recording({'hash': 'h' * 64, 'state': 'pending', 'evidence': 'ev-1'})
    labelled = {**EVIDENCE_16, 'model': {**EVIDENCE_16['model'], 'label': 'Claude Sonnet 5.5'},
                'conversation': {**EVIDENCE_16['conversation'], 'label': 'Gamma ray tidy'}}
    agent.propose('applications/publish', {'id': 'run-1'}, evidence=labelled)
    sent = json.loads(seen[0].content)['evidence']
    assert sent['model']['label'] == 'Claude Sonnet 5.5' and sent['conversation']['label'] == 'Gamma ray tidy'


def test_without_evidence_nothing_extra_is_sent(monkeypatch):
    monkeypatch.setenv('OPHIOLITE_INSTRUCTION', 'Read from the environment')
    agent, seen = recording({'hash': 'h' * 64, 'state': 'pending'})
    agent.propose('applications/publish', {'id': 'run-1'})
    agent.execute('applications/publish', {'id': 'run-1'}, 'h' * 64)
    assert 'evidence' not in json.loads(seen[0].content) and b'environment' not in seen[0].content
    assert 'x-ophiolite-evidence' not in seen[0].headers and 'x-ophiolite-evidence' not in seen[1].headers


def test_changes_accept_the_recalculation_and_still_refuse_an_upload():
    assert 'results/remake-run' in CHANGES and 'results/remake-save' not in CHANGES
    agent, seen = recording({'hash': 'h' * 64, 'state': 'pending'})
    agent.propose('results/remake-run', {'step': 'run', 'command_id': 'c-1', 'inputs': []})
    assert json.loads(seen[0].content)['operation'] == 'results/remake-run'
    for refused in ('las-uploads/upload', 'results/remake-save'):
        with pytest.raises(Refused): agent.propose(refused, {})
    assert len(seen) == 1


def test_status_sends_the_hash_only():
    agent, seen = recording({'hash': 'h' * 64, 'state': 'approved', 'evidence_approved': 'ev-1'})
    assert agent.status('h' * 64) == 'approved'
    assert json.loads(seen[0].content) == {'project_id': 'p', 'hash': 'h' * 64}


def test_an_evidence_field_refused_by_an_older_gateway_raises_and_is_not_retried():
    agent, seen = recording(lambda r: httpx.Response(400, json={'error': 'Expected operation, request and summary', 'code': 'invalid-request'}))
    with pytest.raises(Refused) as raised: agent.propose('applications/publish', {'id': 'run-1'}, evidence=EVIDENCE_16)
    assert 'Expected operation, request and summary' in str(raised.value) and raised.value.status == 400 and len(seen) == 1


def test_wait_for_a_record_blocks_until_the_approval_names_it():
    """Approved with A; B proposed; the person approves B from another thread after a delay."""
    approved = {'evidence': 'ev-A'}
    def answers(request):
        return httpx.Response(200, json={'hash': 'h' * 64, 'state': 'approved', 'evidence_approved': approved['evidence']})
    agent, seen = recording(answers)
    decided = []
    def person():
        time.sleep(0.3); decided.append(time.monotonic()); approved['evidence'] = 'ev-B'
    threading.Thread(target=person).start()
    assert agent.wait('h' * 64, evidence_id='ev-B', interval=0.05) == 'approved'
    returned = time.monotonic()
    assert decided and returned >= decided[0] and len(seen) > 2


def test_wait_without_a_record_keeps_todays_behaviour_and_a_plan_run_with_other_evidence_raises():
    agent, seen = recording({'hash': 'h' * 64, 'state': 'approved', 'evidence_approved': 'ev-A'})
    assert agent.wait('h' * 64, sleep=lambda s: None) == 'approved' and len(seen) == 1
    agent, _ = recording({'hash': 'h' * 64, 'state': 'consumed', 'evidence_approved': 'ev-A'})
    with pytest.raises(IntegrityConflict) as raised: agent.wait('h' * 64, evidence_id='ev-B', sleep=lambda s: None)
    assert raised.value.code == 'evidence-superseded'


def test_run_proposes_waits_for_its_record_and_executes_with_it():
    calls = []
    def answers(request):
        calls.append(request.url.path.rsplit('/', 2)[-2:])
        if request.url.path.endswith('/agents/propose'): return httpx.Response(200, json={'hash': 'h' * 64, 'state': 'approved', 'evidence': 'ev-1'})
        if request.url.path.endswith('/agents/status'): return httpx.Response(200, json={'hash': 'h' * 64, 'state': 'approved', 'evidence_approved': 'ev-1'})
        return httpx.Response(200, json={'id': 'run-1'})
    agent, seen = recording(answers)
    assert agent.run('applications/start', {'id': 'b', 'command_id': 'c'}, evidence=EVIDENCE_16, sleep=lambda s: None) == {'id': 'run-1'}
    assert calls == [['agents', 'propose'], ['agents', 'status'], ['applications', 'start']] and seen[2].headers['x-ophiolite-evidence'] == 'ev-1'


def test_the_release_notes_say_the_pin_advances_and_legacy_approve_is_refused():
    changes = (ROOT / 'CHANGELOG.md').read_text()
    assert 'The SDK pin advances with the release' in changes and 'agents/approve' in changes and '`evidence_generation`' in changes
