"""E150 s0 C5: the SDK reads the try-it-first answers. A choice (C2's fixture, through a fake transport) raises
ChoiceRequired with its five fields under the wire names; a field outside the SDK's bounds is dropped and the exception
says the decision arrived incomplete; the four other words raise their own exceptions by code."""
import base64
import copy
import json
from pathlib import Path

import httpx
import pytest

from ophiolite.agents import AgentClient
from ophiolite.errors import ChoiceRequired, ChoiceRefused, DryRunUnavailable, DryRunRefused, IntegrityConflict, PermissionRefused, Unavailable, Refused

CHOICE = json.loads((Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'agents' / 'v1' / 'fixtures' / 'valid' / 'choice.json').read_text())
FIVE = ('question', 'choices', 'why', 'answered_by', 'choice_token')
TOKEN = 'ct1.' + base64.urlsafe_b64encode(bytes(range(32))).rstrip(b'=').decode()  # the fixture's synthetic token, bytes 00..1f


def refusing(status, body):
    def handler(request): return httpx.Response(status, json=body, headers={'X-Request-Id': 'req_1'})
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(handler)))


def raised(status, body):
    with pytest.raises(Exception) as error: refusing(status, body).read('applications/result-list')
    return error.value


def test_a_choice_raises_choice_required_with_the_five_fields():
    """Mutations: carried() without the choice fields → each attribute is None here; the bound parse without `choices`
    → choices is None."""
    error = raised(409, CHOICE)
    assert type(error) is ChoiceRequired and isinstance(error, IntegrityConflict) and error.complete
    assert (error.code, error.status, error.message, error.request_id) == ('choice-required', 409, 'This step needs a decision from the person the agent acts for', CHOICE['request_id'])
    assert {k: getattr(error, k) for k in FIVE} == {
        'question': 'Which of the two options should this step take?',
        'choices': [{'id': 'c1', 'fragment': {'option': 'first'}}, {'id': 'c2', 'fragment': {'option': 'second'}}],
        'why': {'class': 'example', 'rule': 'example'}, 'answered_by': 'person', 'choice_token': TOKEN}


@pytest.mark.parametrize('field,value', [
    ('question', 'x' * 301),
    ('choices', [{'id': 'c%d' % i, 'fragment': {}} for i in range(1, 10)]),  # a ninth choice
    ('choices', [{'id': 'c2', 'fragment': {}}, {'id': 'c1', 'fragment': {}}]),  # out of order
    ('choices', [{'id': 'c1', 'fragment': {'x': 'y' * 4096}}, {'id': 'c2', 'fragment': {}}]),  # a fragment over 4,096 bytes
    ('why', {'class': 'example'}),
    ('answered_by', 'agent'),
    ('choice_token', 'ct1.short'),
], ids=['question-301', 'ninth-choice', 'order', 'fragment-bytes', 'why-rule', 'answered-by', 'token'])
def test_b_a_field_outside_the_bounds_is_dropped_and_the_answer_is_incomplete(field, value):
    body = copy.deepcopy(CHOICE); body[field] = value
    error = raised(409, body)
    assert type(error) is ChoiceRequired and not error.complete and getattr(error, field) is None
    assert {k: getattr(error, k) for k in FIVE if k != field} == {k: CHOICE[k] for k in FIVE if k != field}
    assert 'arrived incomplete' in str(error)


@pytest.mark.parametrize('status,code,kind', [(403, 'choice-refused', ChoiceRefused), (503, 'dry-run-unavailable', DryRunUnavailable),
                                              (400, 'dry-run-refused', DryRunRefused)])
def test_c_the_other_words_raise_by_code(status, code, kind):
    """Mutation: WORDS without the code → the status's generic exception (PermissionRefused, Busy, Refused) here."""
    body = {'error': 'A sentence', 'code': code, 'message': 'A sentence', 'remedy': 'Do this.', 'docs': '/docs/reference/errors/#' + code, 'request_id': 'req_2',
            **({'reason': 'in-proposal'} if code == 'dry-run-refused' else {})}
    error = raised(status, body)
    assert type(error) is kind and (error.code, error.status, error.message, error.remedy) == (code, status, 'A sentence', 'Do this.')
    assert isinstance(error, {403: PermissionRefused, 503: Unavailable, 400: Refused}[status])
    assert not any(hasattr(error, k) for k in FIVE)
    if code == 'dry-run-refused': assert error.details == {'reason': 'in-proposal'}


def test_d_another_code_carries_no_choice_fields():
    body = {**CHOICE, 'code': 'plan-required', 'error': 'An approved plan is required', 'message': 'An approved plan is required'}
    error = raised(403, body)
    assert type(error) is PermissionRefused and not any(hasattr(error, k) for k in FIVE)
