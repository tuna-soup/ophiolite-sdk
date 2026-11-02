"""E132 s2 C3, offline (strategy rev 3, D8 with R1-4, R1-13, R2-1, R2-9, R2-11): `Client.withdraw` and
`ophiolite withdraw ITEM[@N] --reason TEXT`. Literals by hand in the shapes of the Platform's `StageView`; the HTTP side
is the Platform's test_verdict_withdrawal.py and the installed package's gateway/test_withdraw.py.

Mutations (break -> FAIL, restore -> PASS): no command id (so a retry is a new withdrawal) -> the first two cases; a
stages/get after the transition -> the first two cases; the name printed unfiltered -> the unsafe-name case."""
import json

import httpx
import pytest

from ophiolite import Client, cli, verdicts
from ophiolite.errors import Refused

OLD, NEW = 'a' * 64, 'b' * 64
GOT = {'asset_id': 'r1', 'revision': NEW, 'kind': 'derived', 'name': 'Residuals DCC', 'author': 'alice', 'stage': {'semantics': 'draft', 'name': 'Draft'},
       'generation': 2, 'changed_by': None, 'changed_at': None, 'reason': None, 'endorsements': [], 'allowed_actions': ['request-review', 'withdraw']}
DONE = {**GOT, 'stage': {'semantics': 'withdrawn', 'name': 'Withdrawn'}, 'generation': 3, 'changed_by': 'alice', 'changed_at': 1793400000.0,
        'reason': 'wrong well', 'allowed_actions': []}
LOST = object()


def served(answers):
    """A client over a mock transport: `answers[route]` is a list of (status, body) taken in order; LOST is a request
    that reached the server and whose answer never came back."""
    calls = []

    def handle(request):
        route = request.url.path.split('/projects/p/', 1)[1]
        calls.append((route, json.loads(request.content or b'{}')))
        answer = answers[route].pop(0)
        if answer is LOST: raise httpx.ReadError('the connection closed before the answer', request=request)
        status, body = answer
        return httpx.Response(status, json=body)
    return calls, httpx.Client(transport=httpx.MockTransport(handle))


def test_withdraw_reads_the_generation_then_sends_one_transition_and_reads_nothing_after():
    calls, http = served({'stages/get': [(200, GOT)], 'stages/transition': [(200, DONE)]})
    with http:
        answer = Client('http://localhost', 'p', http=http).withdraw('r1', NEW, 'wrong well', command_id='w-1')
    assert [route for route, _ in calls] == ['stages/get', 'stages/transition']
    assert calls[0][1] == {'project_id': 'p', 'asset_id': 'r1', 'revision': NEW}
    assert calls[1][1] == {'project_id': 'p', 'asset_id': 'r1', 'revision': NEW, 'action': 'withdraw', 'expected_generation': 2,
                           'reason': 'wrong well', 'command_id': 'w-1'}
    assert answer == DONE


def test_a_lost_answer_is_sent_again_with_the_same_command_and_reads_as_withdrawn():
    calls, http = served({'stages/get': [(200, GOT)], 'stages/transition': [LOST, (200, DONE)]})
    with http:
        answer = Client('http://localhost', 'p', http=http).withdraw('r1', NEW, 'wrong well')
    sent = [body for route, body in calls if route == 'stages/transition']
    assert len(sent) == 2 and sent[0] == sent[1] and sent[0]['command_id'].startswith('withdraw-')
    assert [route for route, _ in calls] == ['stages/get', 'stages/transition', 'stages/transition']  # nothing read after
    assert answer['stage']['semantics'] == 'withdrawn'


def test_a_refusal_is_the_servers_sentence_and_is_not_a_withdrawal():
    refusal = {'error': 'A reason of up to 500 characters is required', 'code': 'invalid-request', 'message': 'A reason of up to 500 characters is required'}
    calls, http = served({'stages/get': [(200, GOT)], 'stages/transition': [(400, refusal)]})
    with http, pytest.raises(Refused) as caught:
        Client('http://localhost', 'p', http=http).withdraw('r1', NEW, ' ')
    assert caught.value.server_message == 'A reason of up to 500 characters is required'
    assert [route for route, _ in calls] == ['stages/get', 'stages/transition']


def test_the_command_prints_a_stage_refusal_in_the_servers_words_with_exit_1():
    class Refusing(Resolving):
        def withdraw(self, asset_id, revision, reason, *, command_id=None):
            raise Refused('The application request was refused.', status=400, server_message='A reason of up to 500 characters is required')
    with pytest.raises(Refused) as caught:
        cli._withdraw(cli.parser().parse_args(['withdraw', 'Residuals DCC', '--reason', ' ']), Refusing())
    assert (str(caught.value), cli.exit_code(caught.value)) == ('A reason of up to 500 characters is required', 1)


# --- the command line: `ophiolite withdraw ITEM[@N] --reason TEXT` -----------------------------------------------------

class Resolving(verdicts.VerdictClient):
    """result_version as `verdicts` uses it; the stage answer is DONE with the given name."""
    def __init__(self, name='Residuals DCC'):
        self.sent, self.name = [], name

    def result_version(self, text):
        versions = {'Residuals DCC': NEW, 'Residuals DCC@2': NEW, 'Residuals DCC@1': OLD}
        if text not in versions: raise Refused('This project has no item named "%s".' % text)
        return 'r1', versions[text]

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body))
        return GOT if operation == 'get' else {**DONE, 'revision': body['revision'], 'name': self.name}


def command(capsys, *argv, name='Residuals DCC'):
    fake = Resolving(name)
    payload = cli._withdraw(cli.parser().parse_args(['withdraw', *argv]), fake)
    return fake, payload, capsys.readouterr().out


def test_the_command_prints_the_servers_confirmation_without_a_version_or_a_verdict(capsys):
    fake, _, out = command(capsys, 'Residuals DCC', '--reason', 'wrong well')
    assert out == 'Residuals DCC is now Withdrawn: wrong well\n'
    assert [op for _, op, _ in fake.sent] == ['get', 'transition'] and fake.sent[1][2]['revision'] == NEW
    assert 'verdict' not in out.lower() and 'reject' not in out.lower()


def test_a_historical_version_is_the_one_withdrawn_and_no_output_names_it(capsys):
    fake, _, out = command(capsys, 'Residuals DCC@1', '--reason', 'wrong well')
    assert fake.sent[1][2]['revision'] == OLD
    assert out == 'Residuals DCC is now Withdrawn: wrong well\n' and OLD not in out and 'version' not in out


@pytest.mark.parametrize('name', [None, '', 'f' * 64, 'results/r1.json'])
def test_an_unsafe_or_absent_name_reads_this_result(capsys, name):
    _, _, out = command(capsys, 'Residuals DCC@2', '--reason', 'wrong well', name=name)
    assert out == 'This result is now Withdrawn: wrong well\n'


def test_json_prints_the_stage_answer(capsys):
    _, payload, out = command(capsys, 'Residuals DCC@2', '--reason', 'wrong well', '--json')
    assert json.loads(out) == payload and payload['stage']['semantics'] == 'withdrawn'


def test_an_unresolved_item_keeps_its_refusal_and_sends_nothing():
    fake = Resolving()
    with pytest.raises(Refused):
        cli._withdraw(cli.parser().parse_args(['withdraw', 'Unknown', '--reason', 'wrong well']), fake)
    assert fake.sent == []
