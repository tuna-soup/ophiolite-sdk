"""E150 s1 C6 (SDK): AgentClient.dry_run sends the request with "dry_run": true to the operation's own route and answers
the gateway's ophiolite.agent-dry-run/1 document as a DryRun, checked against the synced fixtures; a refusal outside
`would` stays the error the real call raises."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from ophiolite.agents import AgentClient, DryRun
from ophiolite.errors import DryRunUnavailable, PermissionRefused, VerificationFailed

VALID = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'agents' / 'v1' / 'fixtures' / 'valid'
PROCEEDS = json.loads((VALID / 'dry-run-proceeds.json').read_text())
REFUSED = json.loads((VALID / 'dry-run-refused.json').read_text())
STREAM = json.loads((VALID / 'dry-run-stream.json').read_text())


def client(answer, seen):
    def handler(request):
        seen.append(request)
        status, body = answer
        return httpx.Response(status, json=body)
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_dry_run_answers_would_and_sends_no_plan():
    """Mutations: `dry_run` not added to the body → the sent JSON differs; the answer returned unchecked → a dict."""
    seen = []
    dry = client((200, PROCEEDS), seen).dry_run('verdicts/record', {'result_id': 'r1', 'verdict': 'accepted', 'command_id': 'v-1'})
    [sent] = seen
    assert sent.url.path == '/api/v1/projects/p/verdicts/record'
    assert json.loads(sent.content) == {'project_id': 'p', 'result_id': 'r1', 'verdict': 'accepted', 'command_id': 'v-1', 'dry_run': True}
    assert 'x-ophiolite-plan' not in sent.headers and sent.headers['authorization'] == 'Bearer oph_agent_test'
    assert isinstance(dry, DryRun)
    assert dry.model_dump(by_alias=True, exclude_none=True) == PROCEEDS
    assert [(e.action, e.count, e.kind, e.label) for e in dry.would.effects] == [('create', 1, 'verdict', 'Accepted'), ('create', 1, 'record', None)]


def test_the_operations_own_refusal_is_inside_would():
    dry = client((200, REFUSED), []).dry_run('procedures/trust', {'version_id': 'v', 'command_id': 't-1'})
    assert (dry.would.outcome, dry.would.effects, dry.would.refusal.code) == ('refused', [], 'PERMISSION_DENIED')


def test_an_octet_stream_dry_run_carries_the_flag_in_the_upload_header():
    seen = []
    client((200, STREAM), seen).dry_run('publications/derive', {'command_id': 'd-1'}, raw=b'synthetic,bytes\n')
    [sent] = seen
    assert sent.content == b'synthetic,bytes\n' and sent.headers['content-type'] == 'application/octet-stream'
    assert json.loads(base64.b64decode(sent.headers['x-ophiolite-upload'])) == {'project_id': 'p', 'command_id': 'd-1', 'dry_run': True}


def test_errors_outside_would_stay_errors():
    unavailable = {'code': 'dry-run-unavailable', 'message': 'A dry run of this operation is not available on this deployment yet.', 'reason': 'not-qualified'}
    with pytest.raises(DryRunUnavailable):
        client((503, unavailable), []).dry_run('results/remake-run', {'id': 'r'})
    with pytest.raises(PermissionRefused):
        client((403, {'code': 'PERMISSION_DENIED', 'message': 'Not a member'}), []).dry_run('applications/start', {'id': 'b'})


def test_an_answer_that_is_not_the_document_is_refused():
    """Mutations: the schema check dropped → a dict without `digest` passes; the operation check dropped → another row's
    answer is accepted."""
    broken = {k: v for k, v in PROCEEDS.items() if k != 'digest'}
    with pytest.raises(VerificationFailed):
        client((200, broken), []).dry_run('verdicts/record', {})
    with pytest.raises(VerificationFailed):
        client((200, PROCEEDS), []).dry_run('procedures/trust', {})


# --- E150 s1b C4: a proposal names its dry run ----------------------------------------------------------------------

EVIDENCE = {'instruction': 'Accept the result.', 'model': {'provider': 'anthropic', 'id': 'claude-sonnet-5-5'},
            'conversation': {'kind': 'notebook', 'reference': 't-1'}, 'client': 'well-tidy/0.3'}
VERDICT = {'result_id': 'r1', 'verdict': 'accepted', 'command_id': 'v-1'}
PROPOSED = {'hash': 'c' * 64, 'state': 'pending', 'evidence': 'e1', 'approved': False, 'review_url': 'https://x.example/r'}


@pytest.mark.parametrize('named', ['dry', 'digest'])
def test_propose_sends_the_dry_runs_digest_in_a_copy_of_the_evidence(named):
    """R1-12. Mutations: the digest not put into the evidence → the sent JSON differs; the caller's dict changed in place
    → EVIDENCE gains dry_run."""
    dry = DryRun.model_validate(PROCEEDS)
    seen, mine = [], json.loads(json.dumps(EVIDENCE))
    client((200, PROPOSED), seen).propose('verdicts/record', VERDICT, evidence=mine, dry_run=dry if named == 'dry' else PROCEEDS['digest'])
    [sent] = seen
    assert json.loads(sent.content)['evidence'] == {**EVIDENCE, 'dry_run': 'a9ee30fa2a2da59ba56a5ab6b6ec96169668290445d47d4bab969c07003ec368'}
    assert mine == EVIDENCE


@pytest.mark.parametrize('evidence,dry_run,message', [
    (None, PROCEEDS['digest'], 'pass evidence'),
    (EVIDENCE, 'A9' * 32, 'a DryRun or its 64-character digest'),
    (EVIDENCE, 'a9' * 31, 'a DryRun or its 64-character digest'),
    (EVIDENCE, 64, 'a DryRun or its 64-character digest'),
    ({**EVIDENCE, 'dry_run': 'b' * 64}, PROCEEDS['digest'], 'another dry run'),
])
def test_propose_refuses_a_dry_run_it_cannot_send(evidence, dry_run, message):
    """R1-12: nothing is sent. Mutation: a check removed → the request reaches the transport."""
    seen = []
    with pytest.raises(ValueError) as refused:
        client((200, PROPOSED), seen).propose('verdicts/record', VERDICT, evidence=evidence, dry_run=dry_run)
    assert message in str(refused.value) and seen == []


def test_propose_refuses_a_dry_run_of_another_operation():
    seen = []
    with pytest.raises(ValueError, match='another operation or project'):
        client((200, PROPOSED), seen).propose('applications/publish', {'id': 'r'}, evidence=EVIDENCE, dry_run=DryRun.model_validate(PROCEEDS))
    assert seen == []


def test_propose_without_a_dry_run_sends_the_evidence_as_given():
    seen = []
    client((200, PROPOSED), seen).propose('verdicts/record', VERDICT, evidence=EVIDENCE)
    assert json.loads(seen[0].content)['evidence'] == EVIDENCE
