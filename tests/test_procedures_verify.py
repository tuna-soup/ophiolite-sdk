"""E165 s1 C4: `procedure_verify` / `procedure_verifications` (and their `tool_` twins) and `ophiolite tools verify` /
`tools verifications`. The route answers are written by hand in the shapes of the Platform's operation models (the
Platform's tests/test_procedures_verify.py proves the route); the lines are the server's, printed as they arrive.
Mutations, each red here: a command id derived from the arguments; the CLI printing `state` instead of `line`."""
import contextlib
import copy
import io

import httpx
import pytest

from ophiolite import application_transport, cli
from ophiolite.procedures import ProcedureClient
from ophiolite.tools import ToolClient

DIGEST = 'a' * 64
LINE = 'Verified by Anna against Tops vs reference well on 5 November 2026'
STATE = {'state': 'verified', 'id': 'verification-' + 'b' * 32, 'by': {'kind': 'person', 'id': 'anna', 'name_at_time': 'Anna'},
         'at': 1793880000.0, 'reference_label': 'Tops vs reference well', 'line': LINE}
RECORD = {'schema': 'ophiolite.tool-verification/1', 'id': STATE['id'], 'project': 'p', 'digest': DIGEST, 'by': STATE['by'], 'at': STATE['at'],
          'statement': None, 'command_id': 'verify-1', 'request_sha256': 'c' * 64, 'kind': 'check',
          'reference': {'check_id': 'check-1', 'label': 'Tops vs reference well'}}
VERSION = {'digest': DIGEST, 'name': 'depth-shift', 'version': 3, 'label': 'Shift tops by a fixed depth', 'state': 'enabled', 'trusted': False}


class Recorded(ProcedureClient, ToolClient):
    """The hand-written methods over a fake `_post`: every call is recorded; an answer is a value or raises."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _post(self, area, op, body, retry=False):
        self.calls.append((area, op, copy.deepcopy(body), retry))
        answer = self.answers[op]
        if isinstance(answer, Exception): raise answer
        return answer(body) if callable(answer) else copy.deepcopy(answer)


def client(**answers):
    return Recorded({'list': {'versions': [VERSION]}, 'verify': {'record': RECORD, 'verification': STATE},
                     'verifications': {'digest': DIGEST, 'verification': STATE, 'records': [{'record': RECORD, 'line': LINE}]}, **answers})


def run(c, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): payload = cli._catalogue(cli.parser().parse_args(['tools', *argv]), c)
    return out.getvalue().strip(), payload


def refusal(reason, message):
    response = httpx.Response(422, json={'code': 'procedure-refused', 'reason': reason, 'message': message, 'request_id': 'r1'})
    try: application_transport.status(response, 'verify')
    except Exception as error: return error
    raise AssertionError('not refused')


def test_verify_sends_exactly_the_request_with_a_new_command_id_per_call():
    c = client()
    assert c.procedure_verify(DIGEST, check='check-1') == {'record': RECORD, 'verification': STATE}
    c.tool_verify(DIGEST, check='check-1')
    (_, op, first, retry), (_, _, second, _) = c.calls
    assert op == 'verify' and retry is True  # the transport's own retry resends this body, this command id
    assert {k: v for k, v in first.items() if k != 'command_id'} == {'digest': DIGEST, 'kind': 'check', 'reference': {'check_id': 'check-1'}}
    assert first['command_id'].startswith('verify-') and first['command_id'] != second['command_id']  # mutation (derived id): one id
    c.procedure_verify(DIGEST, withdraw=STATE['id'], statement='Wrong well', command_id='lost-1')
    assert c.calls[-1][2] == {'command_id': 'lost-1', 'digest': DIGEST, 'kind': 'withdrawn', 'reference': {'withdraws': STATE['id']}, 'statement': 'Wrong well'}
    publication = {'title': 'T', 'authors': ['A'], 'year': 2024, 'link': {'kind': 'url', 'value': 'https://example.org/t'}}
    c.procedure_verify(DIGEST, publication=publication)
    assert (c.calls[-1][2]['kind'], c.calls[-1][2]['reference']) == ('publication', publication)


@pytest.mark.parametrize('given', [{}, {'check': 'check-1', 'withdraw': 'verification-1'}, {'check': 'c', 'publication': {}, 'withdraw': 'w'}])
def test_verify_takes_exactly_one_kind_of_evidence_before_any_request(given):
    c = client()
    with pytest.raises(ValueError, match='Give exactly one of check, publication or withdraw.'): c.procedure_verify(DIGEST, **given)
    assert c.calls == []


def test_verifications_returns_the_servers_answer_unchanged():
    c = client()
    assert c.procedure_verifications(DIGEST) == c.tool_verifications(DIGEST) == c.answers['verifications']
    assert [call[1:] for call in c.calls] == [('verifications', {'digest': DIGEST}, True)] * 2


def test_the_command_line_prints_the_servers_lines_never_a_state_or_an_id():
    c = client()
    text, payload = run(c, 'verify', 'depth-shift', '--check', 'check-1')
    assert text == LINE and payload['verification'] == STATE  # mutation (print state): 'verified'
    assert c.calls[-1][2]['reference'] == {'check_id': 'check-1'}
    text, _ = run(client(), 'verifications', 'depth-shift')
    assert text == LINE + '\n' + LINE and 'verified' not in text and 'verification-' not in text
    run(c, 'verify', 'depth-shift', '--title', 'T', '--author', 'A', '--author', 'B', '--year', '2024', '--doi', '10.1/x', '--command-id', 'again-1')
    assert c.calls[-1][2] == {'command_id': 'again-1', 'digest': DIGEST, 'kind': 'publication',
                              'reference': {'title': 'T', 'authors': ['A', 'B'], 'year': 2024, 'link': {'kind': 'doi', 'value': '10.1/x'}}}


def test_a_refusal_is_the_servers_sentence():
    sentence = 'A check that differed does not verify a tool.'
    c = client(verify=refusal('check-differed', sentence))
    with pytest.raises(Exception) as raised: run(c, 'verify', 'depth-shift', '--check', 'check-2')
    assert str(raised.value) == sentence
