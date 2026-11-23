"""E151 s2 C2: the person's side of an agent's job. `Client.proposals()` lists what the person's agents wait on, checked
against the synced ophiolite.agent-proposals/1 envelope; `Client.answer(token, choice)` answers a waiting job's question.
A recording mock transport answers as GW/agent_jobs.py does; the gateway's own refusals are pinned by class and code."""
import copy
import json
from pathlib import Path
import httpx
import pytest
from ophiolite import Client, Credential, publish
from ophiolite.errors import ChoiceRefused, PermissionRefused, Refused, VerificationFailed
from ophiolite.publish import JOB_OPERATIONS, Proposal, ProposalChoice, ProposalEvidence, Proposals, ProposalTrial, ProposalTrialInput, operation_path

V1 = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'agents' / 'v1'
SCHEMA = json.loads((V1 / 'proposals-schema.json').read_text())
FIXTURE = json.loads((V1 / 'fixtures' / 'valid' / 'proposals.json').read_text())
CHOICE = json.loads((V1 / 'fixtures' / 'valid' / 'choice.json').read_text())
TOKEN = CHOICE['choice_token']
PLAN = FIXTURE['proposals'][0]['plan']
WAITING = {**FIXTURE['proposals'][0], 'choice_token': TOKEN}


class Recorder:
    """Answers every request with `answer` (a dict for 200, or an httpx.Response); records (path, body)."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def __call__(self, request):
        self.requests.append((request.url.path, json.loads(request.content)))
        return self.answer if isinstance(self.answer, httpx.Response) else httpx.Response(200, json=self.answer)


def person(recorder):
    return Client('https://x.example', 'p', Credential.bearer('oph_api_alice:read,write'), httpx.Client(transport=httpx.MockTransport(recorder)))


def refusal(status, code, reason=None):
    return httpx.Response(status, json={'error': code, 'code': code, 'message': 'Refused by the gateway: ' + code, **({'reason': reason} if reason else {})})


# --- publish.JOB_OPERATIONS ----------------------------------------------------------------------------------------

def test_the_job_operations_are_the_persons_two_and_no_more():
    """Mutation: 'answer' dropped from JOB_OPERATIONS → Client.answer refused locally (also the answer tests below)."""
    assert JOB_OPERATIONS == {'agents': {'proposals'}, 'jobs': {'answer'}}
    assert operation_path('p', 'agents', 'proposals') == '/api/v1/projects/p/agents/proposals'
    assert operation_path('p', 'jobs', 'answer') == '/api/v1/projects/p/jobs/answer'
    for area, op in (('agents', 'approve'), ('agents', 'propose'), ('jobs', 'step'), ('jobs', 'propose'), ('jobs', 'status'), ('jobs', 'proposals')):
        with pytest.raises(Refused) as refused: operation_path('p', area, op)
        assert type(refused.value) is Refused and refused.value.code == 'INVALID_ARGUMENT'


# --- Client.proposals ----------------------------------------------------------------------------------------------

def test_proposals_posts_the_project_and_returns_the_list():
    gateway = Recorder(FIXTURE)
    listed = person(gateway).proposals()
    assert listed == FIXTURE['proposals'] and listed[0]['question'] == CHOICE['question']
    assert gateway.requests == [('/api/v1/projects/p/agents/proposals', {'project_id': 'p'})]
    assert person(Recorder({'proposals': []})).proposals() == []
    assert person(Recorder({'proposals': [WAITING]})).proposals() == [WAITING]
    # E176 s2a: a proposal whose newest evidence record came with a trial (the gateway's words; "not tried" alike)
    trial = {'state': 'tried', 'as_of': 1.5, 'current': False, 'inputs': [{'slot': 'tops', 'name': 'Tops A', 'version': 2}],
             'lines': ['Tops within 5 m: would be rejected: 1 row over 5 m']}
    for shown in (trial, {'state': 'not_tried', 'as_of': None, 'current': False, 'inputs': [], 'lines': ['Not tried: the attached trial could not be confirmed.']}):
        entry = {**FIXTURE['proposals'][1], 'trial': shown}
        assert person(Recorder({'proposals': [entry]})).proposals() == [entry]
    # E187 s0 (was the 'extra-key' refusal): a field this release does not know is kept, at the top and in an entry
    added = {**FIXTURE['proposals'][1], 'later': {'x': 1}}
    assert person(Recorder({'proposals': [added], 'more': True})).proposals() == [added]


@pytest.mark.parametrize('envelope', [
    [], 'proposals', None, {}, {'proposals': None}, {'proposals': {}}, {'proposals': FIXTURE['proposals'][0]},
    {'proposals': [FIXTURE['proposals'][1]] * 201},
], ids=['list', 'string', 'null', 'empty', 'null-list', 'object-list', 'entry-not-in-list', 'over-200'])
def test_a_malformed_envelope_is_verification_failed(envelope):
    """Mutation: proposals not validated → each of these passes (or fails with another class)."""
    with pytest.raises(VerificationFailed) as failed: person(Recorder(envelope)).proposals()
    assert type(failed.value) is VerificationFailed and failed.value.code == 'verification-failed'


def changed(**fields):
    entry = copy.deepcopy(WAITING)
    for key, value in fields.items():
        if value is KeyError: entry.pop(key)
        else: entry[key] = value
    return entry


@pytest.mark.parametrize('entry', [
    changed(review_url=KeyError), changed(evidence=KeyError), changed(plan='A1' * 32), changed(operation='Jobs/run'),
    changed(summary='x' * 2001), changed(budget={'runs': -1}), changed(budget={'runs': True}), changed(expires_at='soon'),
    changed(question=None), changed(question=''), changed(choices=[WAITING['choices'][0]]), changed(choices=[{'id': 'c9', 'fragment': {}}] * 2),
    changed(choice_token='ct1.' + 'short'), changed(evidence={'id': 'ev', 'generation': 0, 'digest': '0' * 64}), 'entry',
], ids=['no-review-url', 'no-evidence', 'plan-case', 'operation-case', 'long-summary', 'negative-budget', 'bool-budget', 'expiry-text',
        'null-question', 'empty-question', 'one-choice', 'choice-id', 'token', 'evidence-generation', 'not-an-object'])  # E187 s0: 'extra-field' is read now (test above)
def test_a_malformed_entry_is_verification_failed(entry):
    with pytest.raises(VerificationFailed) as failed: person(Recorder({'proposals': [FIXTURE['proposals'][1], entry]})).proposals()
    assert type(failed.value) is VerificationFailed and failed.value.code == 'verification-failed'


@pytest.mark.parametrize('model,where', [(Proposals, None), (Proposal, 'proposal'), (ProposalChoice, 'choice'),
                                         (ProposalEvidence, 'evidence'), (ProposalTrial, 'trial'), (ProposalTrialInput, 'trial-input')])
def test_the_proposals_model_mirrors_the_synced_schema(model, where):
    """Mutation: a field dropped from Proposal (or made optional) → red. The check needs no `validation` extra."""
    if where == 'evidence': schema = SCHEMA['$defs']['proposal']['properties']['evidence']['anyOf'][0]
    elif where == 'trial-input': schema = SCHEMA['$defs']['trial']['properties']['inputs']['items']
    else: schema = SCHEMA['$defs'][where] if where else SCHEMA
    fields = set(model.model_fields)
    required = {name for name, f in model.model_fields.items() if f.is_required()}
    assert fields == set(schema['properties']), fields ^ set(schema['properties'])
    assert required == set(schema.get('required', [])), required ^ set(schema.get('required', []))


def test_proposals_works_without_the_validation_extra(monkeypatch):
    import builtins
    real = builtins.__import__
    def no_jsonschema(name, *args, **kwargs):
        if name == 'jsonschema' or name.startswith('jsonschema.'): raise ImportError(name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_jsonschema)
    assert person(Recorder(FIXTURE)).proposals() == FIXTURE['proposals']


def test_an_agent_credential_on_proposals_is_the_gateways_refusal():
    """The SDK classifies no credential (D3); the gateway's 403 propagates with its code."""
    gateway = Recorder(refusal(403, 'agent-refused'))
    with pytest.raises(PermissionRefused) as refused: person(gateway).proposals()
    assert type(refused.value) is PermissionRefused and refused.value.code == 'agent-refused' and refused.value.status == 403
    assert len(gateway.requests) == 1  # a read may retry on 429/503 only


# --- Client.answer -------------------------------------------------------------------------------------------------

def test_answer_posts_the_token_and_choice_and_returns_the_gateways_answer():
    """Mutation: 'answer' dropped from JOB_OPERATIONS → Refused before any request, so this is red."""
    answered = {'plan': PLAN, 'step': 2, 'state': 'running', 'choice': 'c2'}
    gateway = Recorder(answered)
    assert person(gateway).answer(TOKEN, 'c2') == answered
    assert gateway.requests == [('/api/v1/projects/p/jobs/answer', {'project_id': 'p', 'choice_token': TOKEN, 'choice': 'c2'})]


@pytest.mark.parametrize('reason', ['token-used', 'token-foreign', 'token-stale', 'not-the-delegator'])
def test_each_token_word_is_choice_refused_with_its_reason(reason):
    gateway = Recorder(refusal(403, 'choice-refused', reason))
    with pytest.raises(ChoiceRefused) as refused: person(gateway).answer(TOKEN, 'c1')
    error = refused.value
    assert type(error) is ChoiceRefused and isinstance(error, PermissionRefused)
    assert (error.code, error.status, error.details['reason']) == ('choice-refused', 403, reason)
    assert len(gateway.requests) == 1  # an answer is a write: never sent twice


def test_a_choice_not_offered_is_the_gateways_agent_refused():
    with pytest.raises(PermissionRefused) as refused: person(Recorder(refusal(403, 'agent-refused'))).answer(TOKEN, 'c7')
    assert type(refused.value) is PermissionRefused and (refused.value.code, refused.value.status) == ('agent-refused', 403)


def test_answer_belongs_to_the_person_only():
    """The agent's client has no proposals or answer (D3); Client keeps its runner reader names apart."""
    from ophiolite.agents import AgentClient
    assert not hasattr(AgentClient, 'answer') and not hasattr(AgentClient, 'proposals')
    assert callable(Client.proposals) and callable(Client.answer)
    assert publish.parse_proposals(FIXTURE) is FIXTURE['proposals']
