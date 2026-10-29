"""E120 s0 S0.3, offline: what the SDK sends for an outcome, the routes it may call, how it finds one by name, and that
an outcome refusal keeps the server's sentence and its closed reason (the transport reads `outcome-refused`)."""
import json
from pathlib import Path

import httpx
import pytest

import ophiolite
from ophiolite import application_transport, outcomes
from ophiolite.errors import PermissionRefused, Refused
from ophiolite.publish import operation_path

CONTRACT = Path(ophiolite.__file__).resolve().parent / 'contracts/outcomes/v1'


class Fake(outcomes.OutcomeClient):
    def __init__(self, listed=()):
        self.sent, self.listed = [], list(listed)

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        return {'outcomes': self.listed} if operation == 'list' else {'label': 'x'}


def test_the_residual_declaration_is_the_shared_valid_fixture():
    """Mutation: a changed kind, rule, input or key in `residual_declaration` differs from the contract's fixture."""
    made = outcomes.residual_declaration('Tops within 5 m', 5, 'm', 'tops-to-team-database', 'Team database')
    assert made == json.loads((CONTRACT / 'fixtures/valid/tops-within-5m.json').read_text())
    assert outcomes.residual_declaration('Tops within 1 m', 1, 'm', 'tops-to-team-database', 'Team database') == json.loads(
        (CONTRACT / 'fixtures/valid/tops-within-1m.json').read_text())


@pytest.mark.parametrize('operation', ['declare', 'revise', 'enable', 'disable', 'withdraw', 'list', 'get', 'states', 'evaluate', 'deliver-as', 'claims'])
def test_the_eleven_outcome_operations_have_their_paths(operation):  # E120 s1: states and evaluate; s3: deliver-as and claims
    assert operation_path('p one', 'outcomes', operation) == '/api/v1/projects/p%20one/outcomes/' + operation


def test_no_other_outcome_operation_is_sent():
    """Mutation: a `delete` added to OUTCOME_OPERATIONS is sent instead of refused here (no such route; E120 s3)."""
    with pytest.raises(Refused, match='Unsupported application operation.'):
        operation_path('p', 'outcomes', 'delete')


def test_each_write_sends_a_new_command_id_unless_one_is_given_and_may_be_retried():
    fake = Fake()
    fake.outcome_declare({'label': 'a'})
    fake.outcome_declare({'label': 'a'})
    fake.outcome_withdraw('o1', command_id='mine')
    (_, _, first, r1), (_, _, second, _), third = fake.sent
    assert first['command_id'].startswith('declare-') and len(first['command_id']) == len('declare-') + 32
    assert first['command_id'] != second['command_id'] and r1 is True
    assert third == ('outcomes', 'withdraw', {'command_id': 'mine', 'outcome_id': 'o1'}, True)
    fake.outcome_revise('o1', {'label': 'b'}, command_id='r')
    assert fake.sent[-1] == ('outcomes', 'revise', {'command_id': 'r', 'outcome_id': 'o1', 'declaration': {'label': 'b'}}, True)


def test_an_outcome_is_found_by_its_name_without_case_and_never_a_withdrawn_one():
    fake = Fake([{'outcome_id': 'old', 'label': 'Tops within 5 m', 'state': 'withdrawn'},
                 {'outcome_id': 'new', 'label': 'Tops within 5 m', 'state': 'disabled'}])
    assert fake.outcome_named('TOPS WITHIN 5 M')['outcome_id'] == 'new'
    with pytest.raises(Refused) as caught:
        Fake(fake.listed[:1]).outcome_named('Tops within 5 m')
    assert str(caught.value) == 'This project has no outcome named "Tops within 5 m".'


def test_the_summary_line_is_words():
    o = {'label': 'Tops within 5 m', 'state': 'enabled', 'version': 1,
         'words': {'kind': 'residual results', 'rule': 'every computed residual within 5 m', 'destination': 'Team database'}}
    assert outcomes.summary_line(o) == '"Tops within 5 m" (enabled, version 1): residual results, every computed residual within 5 m; delivered to Team database.'


def answer(status, body):
    return httpx.Response(status, json=body, request=httpx.Request('POST', 'https://example.test/x'))


def test_an_outcome_refusal_keeps_the_servers_sentence_and_reason():
    """Mutation: 'outcome-refused' removed from either transport tuple loses the reason or the sentence."""
    sentence = 'Only a project administrator can declare or change outcomes.'
    with pytest.raises(PermissionRefused) as caught:
        application_transport.status(answer(403, {'code': 'outcome-refused', 'reason': 'permission', 'message': sentence, 'error': sentence}), 'declare')
    assert (str(caught.value), caught.value.details, caught.value.code) == (sentence, {'reason': 'permission'}, 'outcome-refused')
    with pytest.raises(Refused) as caught:
        application_transport.status(answer(400, {'code': 'outcome-refused', 'reason': 'label', 'message': 'A name is words.'}), 'declare')
    assert (str(caught.value), caught.value.details) == ('A name is words.', {'reason': 'label'})
