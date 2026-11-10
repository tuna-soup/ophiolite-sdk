"""E153 s1 C4 (2.6): a job's file step from the SDK. `run_job(steps, files={i: bytes})` names the file in the step's
body by size and sha256, waits, then sends the bytes to the step's own route with X-Ophiolite-Plan and
X-Ophiolite-Job-Step; a completed file step replays through jobs/step; a missing file raises before any request."""
import base64
import hashlib
import json
import httpx
import pytest
from ophiolite.agents import FILE_STEPS
from ophiolite.errors import Refused
from test_agent_jobs_sdk import ID1, ID2, PLAN, client

RAW = b'BOREHOLE_CODE,BOREHOLE_NAME,X,Y\r\nALO-01,ALLARDSOOG-01,217009.5,580059.2\r\n'
NAMED = {'bytes': len(RAW), 'sha256': hashlib.sha256(RAW).hexdigest()}
STEPS = [{'operation': 'table-imports/read', 'body': {'name': 'wells.csv'}},
         {'operation': 'table-imports/preview', 'body': {'input_id': {'$step': 1, 'pointer': '/input_id'}, 'target': 'wells'}}]


class Gateway:
    """jobs/propose, agents/status, jobs/status, jobs/step and the read route, recording every request."""

    def __init__(self, done=()):
        self.stored, self.requests, self.proposed = {i: {'step': i} for i in done}, [], None

    def __call__(self, request):
        route = request.url.path.split('/projects/p/')[1]
        if route == 'table-imports/read':
            header = json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))
            self.requests.append((route, header, request.headers.get('x-ophiolite-plan'), request.headers.get('x-ophiolite-job-step'), request.content))
            self.stored[1] = {'input_id': 'in-1'}
            return httpx.Response(200, json=self.stored[1])
        body = json.loads(request.content)
        self.requests.append((route, body))
        if route == 'jobs/propose':
            self.proposed = body
            return httpx.Response(200, json={'hash': PLAN, 'state': 'pending'})
        if route == 'agents/status': return httpx.Response(200, json={'hash': PLAN, 'state': 'consumed', 'evidence_approved': None})
        if route == 'jobs/status':
            return httpx.Response(200, json={'plan': PLAN, 'state': 'running', 'step': len(self.stored) + 1, 'review_url': 'https://w.example/p',
                                             'steps': [{'operation': s['operation'], 'state': 'completed' if i in self.stored else 'pending',
                                                        'answer_sha256': ('%02d' % i) * 32 if i in self.stored else None} for i, s in enumerate(STEPS, 1)]})
        if route == 'jobs/step':
            i = body['step']
            if i == 1 and 1 not in self.stored: return httpx.Response(400, json={'error': 'reads a file', 'code': 'INVALID_ARGUMENT'})
            self.stored.setdefault(i, {'step': i})
            return httpx.Response(200, json=self.stored[i])
        return httpx.Response(404, json={'error': 'not found', 'code': 'not-found'})


def test_run_job_names_the_file_then_sends_it_to_its_route_under_the_step():
    """Mutation: the file step sent through jobs/step (the read route never sees the bytes)."""
    gateway = Gateway()
    answers = client(gateway).run_job(STEPS, files={1: RAW}, sleep=lambda s: None)
    assert gateway.proposed['steps'][0]['body'] == {'name': 'wells.csv', 'project_id': 'p', **NAMED}
    route, header, plan, named, raw = next(r for r in gateway.requests if r[0] == 'table-imports/read')
    assert (header, plan, named, raw) == ({'project_id': 'p', 'name': 'wells.csv', **NAMED}, PLAN, '1 ' + ID1, RAW)
    assert [r[0] for r in gateway.requests] == ['jobs/propose', 'agents/status', 'jobs/status', 'table-imports/read', 'jobs/step']
    assert answers == [{'input_id': 'in-1'}, {'step': 2}] and gateway.requests[-1][1]['command_id'] == ID2


@pytest.mark.parametrize('files', [None, {2: RAW}, {1: b''}, {1: 'text'}], ids=['none', 'other-step', 'empty', 'not-bytes'])
def test_a_missing_file_raises_before_any_request(files):
    gateway = Gateway()
    with pytest.raises(Refused, match='reads a file'): client(gateway).run_job(STEPS, files=files)
    assert gateway.requests == []


def test_a_body_naming_other_bytes_is_refused_before_any_request():
    gateway = Gateway()
    steps = [{'operation': 'table-imports/read', 'body': {'name': 'wells.csv', 'sha256': '0' * 64}}]
    with pytest.raises(Refused, match='other bytes'): client(gateway).run_job(steps, files={1: RAW})
    assert gateway.requests == []


def test_a_completed_file_step_replays_through_jobs_step_on_resume():
    gateway = Gateway(done=(1,))
    agent = client(gateway)
    assert agent.resume(PLAN, sleep=lambda s: None) == [{'step': 1}, {'step': 2}]  # no files needed: nothing is sent again
    assert [r[0] for r in gateway.requests] == ['agents/status', 'jobs/status', 'jobs/step', 'jobs/step']


def test_resume_of_a_file_step_this_process_did_not_propose_raises_before_any_step():
    gateway = Gateway()
    with pytest.raises(Refused, match='did not propose'): client(gateway).resume(PLAN, files={1: RAW}, sleep=lambda s: None)
    assert [r[0] for r in gateway.requests] == ['agents/status', 'jobs/status']


def test_resume_in_the_same_process_sends_the_pending_file():
    gateway = Gateway()
    agent = client(gateway)
    agent.propose_job(STEPS, files={1: RAW})
    assert agent.resume(PLAN, files={1: RAW}, sleep=lambda s: None) == [{'input_id': 'in-1'}, {'step': 2}]
    with pytest.raises(Refused, match='reads a file'): client(Gateway()).propose_job(STEPS)


def test_the_file_steps_are_the_gateways_stream_steps():
    assert FILE_STEPS == {'table-imports/read'}
