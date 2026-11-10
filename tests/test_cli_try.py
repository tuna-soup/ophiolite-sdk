"""E150 s1b C4: the CLI prints a choice's question and every choice id and fragment, never its token, and exits 4
(conflict); `ophiolite results try OPERATION --body FILE` prints what one request would do, or the document with --json."""
import json
from types import SimpleNamespace

import pytest

from ophiolite import cli
from ophiolite.errors import ChoiceRequired, Refused, VerificationFailed

TOKEN = 'ct1.' + 'A' * 43
CHOICES = [{'id': 'c1', 'fragment': {'crs': 'EPSG:23031'}}, {'id': 'c2', 'fragment': {'crs': 'EPSG:25831'}}]
DIGEST = 'd7' * 32
ANSWER = {'schema': 'ophiolite.agent-dry-run/1', 'dry_run': True, 'operation': 'applications/configure', 'project_id': 'p',
          'would': {'outcome': 'proceeds', 'effects': [{'action': 'create', 'kind': 'record', 'count': 1}]}, 'digest': DIGEST}


class Gateway:
    project = 'p'

    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def _post(self, area, name, body):
        self.sent.append((area, name, body))
        return self.answer


def trying(tmp_path, body, json_=False, operation='applications/configure'):
    path = tmp_path / 'body.json'
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return SimpleNamespace(operation=operation, body=path, json=json_)


def test_try_is_a_results_verb_with_an_operation_and_a_body():
    args = cli.parser().parse_args(['results', 'try', 'applications/configure', '--body', 'b.json'])
    assert (args.command, args.operation, str(args.body)) == ('try', 'applications/configure', 'b.json')


def test_try_prints_what_the_request_would_do(tmp_path, capsys):
    """Mutations: dry_run not sent → the sent body differs; the effects left out → the literal differs."""
    gateway = Gateway(ANSWER)
    cli._try(trying(tmp_path, {'name': 'x'}), gateway)
    assert gateway.sent == [('applications', 'configure', {'name': 'x', 'dry_run': True})]
    assert capsys.readouterr().out == 'applications/configure would proceed; nothing was kept.\n  create 1 record\ndigest %s\n' % DIGEST


def test_try_prints_the_operations_own_refusal_and_the_document_with_json(tmp_path, capsys):
    refused = {**ANSWER, 'would': {'outcome': 'refused', 'effects': [], 'refusal': {'code': 'INVALID_ARGUMENT', 'message': 'No such curve.'}}}
    cli._try(trying(tmp_path, {'name': 'x'}), Gateway(refused))
    assert capsys.readouterr().out == 'applications/configure would be refused; nothing was kept.\n  No such curve.\ndigest %s\n' % DIGEST
    cli._try(trying(tmp_path, {'name': 'x'}, json_=True), Gateway(ANSWER))
    assert json.loads(capsys.readouterr().out) == ANSWER


@pytest.mark.parametrize('body, operation, error', [
    ('[1]', 'applications/configure', Refused), ('{', 'applications/configure', Refused),
    ({'dry_run': True}, 'applications/configure', Refused), ({}, 'configure', Refused)])
def test_try_refuses_before_sending(tmp_path, body, operation, error):
    gateway = Gateway(ANSWER)
    with pytest.raises(error): cli._try(trying(tmp_path, body, operation=operation), gateway)
    assert gateway.sent == []


@pytest.mark.parametrize('answer', [{**ANSWER, 'operation': 'applications/start'}, {**ANSWER, 'project_id': 'q'}, {**ANSWER, 'digest': 'x'}])
def test_try_checks_the_answer_it_prints(tmp_path, answer):
    with pytest.raises(VerificationFailed): cli._try(trying(tmp_path, {}), Gateway(answer))


def asking(monkeypatch):
    def main(argv=None):
        raise ChoiceRequired('This step needs your decision.', question='Which coordinate system do the positions use?', choices=CHOICES,
                             why={'class': 'crs', 'rule': 'two-candidates'}, answered_by='person', choice_token=TOKEN, status=409)
    monkeypatch.setattr(cli, 'main', main)


def test_the_choice_is_printed_for_people_without_its_token(monkeypatch, capsys):
    """Mutations: the token printed → the literal differs; the choices left out → the literal differs."""
    asking(monkeypatch)
    with pytest.raises(SystemExit) as ended: cli.entrypoint(['jobs', 'step'])
    out, err = capsys.readouterr()
    assert ended.value.code == 4 and out == ''
    assert err == ('This step needs your decision.\nWhich coordinate system do the positions use?\n'
                   '  c1: {"crs": "EPSG:23031"}\n  c2: {"crs": "EPSG:25831"}\n')


def test_the_choice_is_in_the_json_error_without_its_token(monkeypatch, capsys):
    asking(monkeypatch)
    with pytest.raises(SystemExit) as ended: cli.entrypoint(['jobs', 'step', '--json'])
    out, _ = capsys.readouterr()
    assert ended.value.code == 4 and TOKEN not in out
    assert json.loads(out) == {'error': {'code': 'choice-required', 'message': 'This step needs your decision.', 'status': 409,
                                         'question': 'Which coordinate system do the positions use?', 'choices': CHOICES}}
