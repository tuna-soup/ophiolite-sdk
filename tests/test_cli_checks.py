"""E96 C6: `ophiolite checks` offline. The route answers are written by hand in the shapes of the Platform's operation
models (tests/gateway/test_checks_client.py proves the same verbs against the real routes); the words are literals.
`ophiolite check` (E70a's exchange command) is unchanged."""
import base64
import copy
import hashlib
import json

import httpx
import pytest

from ophiolite import application_transport, checks, cli
from ophiolite.checks import CheckClient
from ophiolite.errors import PermissionRefused, Refused
from ophiolite.publish import operation_path

AT = 1791367200.0  # 7 October 2026 10:00 UTC
LAS = (b'~Version\n VERS. 2.0 :\n~Well\n NULL. -999.25 :\n~Curve\n DEPT.M : depth\n VSH.V/V : shale volume\n~A\n'
       b'100 0.1\n101 0.2\n')


def record(witness='server', outcome='passed', at=AT, **more):
    found = {'id': 'check-' + witness + str(at), 'schema': 'ophiolite.check/1', 'witness': witness, 'at': at, 'command_id': 'c',
             'recorded_by': {'id': 'marit', 'kind': 'person'}, 'server_output_digest': None,
             'subject': {'kind': 'implementation', 'id': 'ophiolite.shale-volume', 'version': '1', 'script_sha256': 'a' * 64,
                         'release_number': '2026.10.60', 'release_digest': 'b' * 64},
             'fixture': {'digest': 'c' * 64, 'display_name': 'HON-GT-01 gamma-ray excerpt'},
             'reference': {'kind': 'independent-computation', 'name': 'Larionov', 'version': '1', 'digest': 'd' * 64, 'rights': {'licence': 'x', 'source': 'y'}},
             'output_digest': 'e' * 64, 'rules_id': 'series-compare/1', 'tolerance': {'kind': 'absolute', 'value': 0.000001, 'unit': 'V/V'},
             'request_digest': 'f' * 64, 'interpretation_digest': None, 'outcome': outcome, 'reason': None,
             'differences': {'count': 0, 'total': 1551, 'largest': None, 'value_to_missing': 0, 'missing_to_value': 0, 'first': [], 'changed_range': None}}
    found.update(more)
    return found


class Recorded(CheckClient):
    """The hand-written methods over a fake `_post`: every call is recorded; an answer is a value or raises."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _post(self, area, op, body, retry=False):
        self.calls.append((area, op, copy.deepcopy(body), retry))
        answer = self.answers[op]
        if isinstance(answer, Exception): raise answer
        return answer(body) if callable(answer) else copy.deepcopy(answer)

    def members(self):
        return {'members': ['marit'], 'display': {'member_names': {'marit': 'Marit Jansen'}}}


def run(client, *argv):
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out): payload = cli._checks(cli.parser().parse_args(['checks', *argv]), client)
    return out.getvalue().strip(), payload


def refusal(status, field, message='server words'):
    """The error the transport raises for the server's check-refused envelope."""
    response = httpx.Response(status, json={'code': 'check-refused', 'message': message, 'field': field, 'request_id': 'r1'})
    try: application_transport.status(response, 'publish')
    except Exception as error: return error
    raise AssertionError('not refused')


def check_folder(tmp_path, name='one'):
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'check.json').write_text(json.dumps({k: v for k, v in record().items() if k not in ('id', 'witness', 'at', 'command_id', 'recorded_by', 'server_output_digest')}))
    (folder / 'fixture.las').write_bytes(b'fixture'); (folder / 'reference.las').write_bytes(b'reference'); (folder / 'output.json').write_bytes(b'{}')
    (folder / 'request.json').write_text('{"curve": "GR"}')
    return folder


# --- `check` stays E70a's ---------------------------------------------------------------------------------------------

def test_check_is_still_the_exchange_command_and_checks_is_not_its_abbreviation(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, '_exchange', lambda args, client: seen.append(('exchange', args.command)))
    monkeypatch.setattr(cli, '_checks', lambda args, client: seen.append(('checks', args.command)))
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': 'https://workspace.example', 'project': 'p'}))
    monkeypatch.chdir(tmp_path); monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_key_' + 'k' * 40)
    cli._main(['check'])
    cli._main(['checks', 'publishers', 'list'])
    assert seen == [('exchange', 'check'), ('checks', 'checks')]
    with pytest.raises(SystemExit): cli.parser().parse_args(['chec'])


def test_the_check_help_is_unchanged(monkeypatch):
    monkeypatch.setenv('COLUMNS', '100')
    check = next(a for a in cli.parser()._actions if a.dest == 'command').choices['check']
    text = check.format_help()
    assert text[text.index('options:'):] == ('options:\n  -h, --help            show this help message and exit\n'
                                             '  --json                Print the documented JSON result (errors as {"error": {...}})\n'
                                             '  --configuration CONFIGURATION\n  --credentials CREDENTIALS\n'
                                             '  --work WORK           The folder that remembers what you hold (default .ophiolite-held)\n')


def test_checks_help_lists_its_verbs_and_the_publishers_three():
    checks_parser = next(a for a in cli.parser()._actions if a.dest == 'command').choices['checks']
    verbs = next(a for a in checks_parser._actions if a.dest == 'action').choices
    assert list(verbs) == ['publish', 'list', 'compare', 'publishers']
    assert list(next(a for a in verbs['publishers']._actions if a.dest == 'change').choices) == ['list', 'add', 'remove']


def test_the_four_routes_are_allowed_and_no_other():
    for op in ('publish', 'list', 'compare', 'publishers'): assert operation_path('p', 'checks', op) == '/api/v1/projects/p/checks/' + op
    with pytest.raises(Refused): operation_path('p', 'checks', 'delete')


# --- publish -----------------------------------------------------------------------------------------------------------

def test_publish_sends_the_folder_and_says_how_many_the_server_checked(tmp_path):
    folder = check_folder(tmp_path)
    client = Recorded({'publish': lambda body: {**body['record'], 'id': 'check-1', 'witness': 'server'}})
    text, payload = run(client, 'publish', str(tmp_path))
    assert text == 'Published 1 check for Ophiolite 2026.10.60: 1 checked by the server.'
    (_, op, body, retry), = client.calls
    assert op == 'publish' and retry and body['request'] == {'curve': 'GR'} and 'interpretation' not in body
    assert {k: base64.b64decode(v) for k, v in body['files'].items()} == {'fixture': b'fixture', 'reference': b'reference', 'output': b'{}'}
    sent = {k: v for k, v in body.items() if k != 'command_id'}
    assert body['command_id'] == 'check-' + hashlib.sha256(json.dumps(sent, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:58]
    assert checks.publish_body(folder)['command_id'] == body['command_id']  # the same folder, the same command id (a retry)
    two = Recorded({'publish': lambda body: {**body['record'], 'id': 'x', 'witness': 'server' if body['request'] == {'curve': 'GR'} else 'claimed'}})
    (check_folder(tmp_path, 'two') / 'request.json').write_text('{"curve": "GR2"}')
    assert run(two, 'publish', str(tmp_path))[0] == 'Published 2 checks for Ophiolite 2026.10.60: 1 checked by the server, 1 reported, not repeated by the server.'


@pytest.mark.parametrize('status,field,sentence', [
    (400, 'reference.digest', 'Not published: the reference file does not match the recorded file.'),
    (400, 'release.digest', 'Not published: the check was made for release 2026.10.60, not the release this server runs.'),
    (503, 'timeout', 'Not published: the server did not finish the check in time. Nothing was saved.'),
    (503, 'capacity', 'Not published: the server is busy. Try again.'),
    (403, 'permission', 'Publishing checks needs permission. Ask a project administrator.'),
])
def test_a_refused_publish_says_the_sentence_and_the_field_is_only_in_json(tmp_path, status, field, sentence):
    check_folder(tmp_path)
    error = refusal(status, field)
    with pytest.raises(type(error)) as refused: run(Recorded({'publish': error}), 'publish', str(tmp_path))
    assert str(refused.value) == sentence and (field == 'permission' or field not in str(refused.value))  # the word, not a field path
    document = cli.error_document(refused.value)['error']
    assert (document['field'], document['code'], document['request_id']) == (field, 'check-refused', 'r1')


def test_a_refusal_without_a_field_keeps_its_own_sentence(tmp_path):
    check_folder(tmp_path)
    response = httpx.Response(403, json={'code': 'PERMISSION_DENIED', 'message': 'The key is not accepted.', 'stage': 'credential-refused'})
    try: application_transport.status(response, 'publish')
    except PermissionRefused as error: refused = error
    with pytest.raises(PermissionRefused) as raised: run(Recorded({'publish': refused}), 'publish', str(tmp_path))
    assert str(raised.value) == str(refused) and 'field' not in cli.error_document(raised.value)['error']


def test_the_envelope_reads_only_a_closed_field_name():
    assert application_transport.envelope(httpx.Response(400, json={'field': 'reference.digest'}))['field'] == 'reference.digest'
    for wrong in ('Reference', 'a b', 'x' * 65, 7, '../etc'):
        assert 'field' not in application_transport.envelope(httpx.Response(400, json={'field': wrong})), wrong


def test_publish_refuses_a_folder_without_a_check():
    with pytest.raises(Refused, match='No check.json'): checks.folders('/nonexistent-e96')


# --- list --------------------------------------------------------------------------------------------------------------

def test_list_words_checked_reported_disagreement_earlier_and_compared():
    server, claimed = record(), record('claimed', at=AT + 3600)
    earlier = record(outcome='differed', at=AT - 86400, differences={**record()['differences'], 'count': 1, 'largest': 0.03, 'changed_range': [101.0, 101.0]})
    personal = record('personal', at=AT, subject={'kind': 'result', 'asset_id': 'a', 'revision': 'r'}, fixture=None, tolerance=None)
    answer = {'records': [server, earlier, claimed, personal],
              'groups': [{'key': 'k1', 'latest': server, 'earlier': [earlier], 'disagreement': True},
                         {'key': 'k2', 'latest': claimed, 'earlier': [], 'disagreement': False}]}
    client = Recorded({'list': answer})
    text, payload = run(client, 'list', '--asset', 'a', '--revision', 'r', '--earlier')
    assert payload == answer and client.calls[0][2] == {'subject': {'kind': 'result', 'asset_id': 'a', 'revision': 'r'}}
    assert text.splitlines() == [
        'Checks disagree: differed on 6 October 10:00, passed on 7 October 10:00.',
        'Checked against an independent calculation (version 1) on HON-GT-01 gamma-ray excerpt, 7 October 2026: passed.',
        'Within 0.000001 V/V.', 'This shows these numbers on this data only.',
        'Earlier checks:',
        '  Checked against an independent calculation (version 1) on HON-GT-01 gamma-ray excerpt, 6 October 2026: differed.',
        '  Largest difference 0.03 V/V, at 1 of 1551 depths.', '  Allowed: within 0.000001 V/V.',
        'Reported check by Marit Jansen: passed on HON-GT-01 gamma-ray excerpt.', 'Ophiolite did not repeat this check.',
        'Compared with files:',
        '  Compared with a file on 7 October 2026: passed.', '  Exactly equal.', '  Saved on this result only.']
    assert 'Checked against' not in '\n'.join(checks.record_lines(claimed))  # mutation: a reported record read as checked


def test_list_of_an_implementation_and_nothing_recorded():
    client = Recorded({'list': {'records': [], 'groups': []}})
    assert run(client, 'list', '--implementation', 'ophiolite.shale-volume', '--version', '1')[0] == 'Not checked against a reference.'
    assert client.calls[0][2] == {'subject': {'kind': 'implementation', 'id': 'ophiolite.shale-volume', 'version': '1'}}
    with pytest.raises(Refused): run(client, 'list', '--asset', 'a')


# --- compare -----------------------------------------------------------------------------------------------------------

def differed(**more):
    return record('personal', outcome='differed', subject={'kind': 'result', 'asset_id': 'a', 'revision': 'r'}, fixture=None,
                  tolerance={'kind': 'absolute', 'value': 0.0001, 'unit': 'V/V'}, bound='Within 0.0001 V/V',
                  differences={'count': 12, 'total': 1551, 'largest': 0.00039999999999995595, 'value_to_missing': 0, 'missing_to_value': 0,
                               'first': [], 'changed_range': [2480.2, 2601.0]}, **more)


def test_compare_sends_the_file_and_the_tolerance_in_the_files_unit_and_says_how_far_it_differs(tmp_path):
    (tmp_path / 'ref.las').write_bytes(LAS)
    client = Recorded({'compare': differed()})
    text, _ = run(client, 'compare', '--asset', 'a', '--revision', 'r', '--file', str(tmp_path / 'ref.las'), '--tolerance', '0.0001')
    assert text.splitlines() == ['Differs by at most 0.0004 V/V, at 12 of 1551 depths (between 2480.2 and 2601).', 'Saved on this result only.',
                                 'This is not a check of the method that made this result.']
    (_, op, body, retry), = client.calls
    assert (body['curve'], body['file_name'], body['tolerance']) == ('VSH', 'ref.las', {'kind': 'absolute', 'value': 0.0001, 'unit': 'V/V'})
    assert base64.b64decode(body['files']['file']) == LAS and body['command_id'].startswith('compare-') and len(body['command_id']) == 64


def test_compare_outcomes_in_words(tmp_path):
    (tmp_path / 'ref.las').write_bytes(LAS)
    argv = ('compare', '--asset', 'a', '--revision', 'r', '--file', str(tmp_path / 'ref.las'))
    passed = record('personal', tolerance=None)
    assert run(Recorded({'compare': passed}), *argv)[0].splitlines()[0] == 'The values match exactly.'
    for reason, words in (('axis_mismatch', 'Not compared: the depth samples differ; nothing is resampled.'),
                          ('no_such_curve', 'Not compared: the file has no curve called VSH.'),
                          ('unreadable', 'Not compared: the file could not be read as a well log.')):
        found = record('personal', outcome='not_compared', reason=reason, differences=None)
        assert run(Recorded({'compare': found}), *argv)[0].splitlines()[0] == words, reason
    kind = record('personal', outcome='not_compared', reason='another_kind', differences=None,
                  sentence='Not compared: the file is a gridded surface, and this result needs a well log.')
    assert run(Recorded({'compare': kind}), *argv)[0].splitlines()[0] == kind['sentence']


def test_compare_asks_for_the_curve_of_a_file_with_several_and_says_the_limit(tmp_path):
    (tmp_path / 'two.las').write_bytes(LAS.replace(b' VSH.V/V : shale volume\n', b' VSH.V/V : shale volume\n PHI.V/V : porosity\n VCL.V/V : clay\n'))
    client = Recorded({'compare': record('personal')})
    with pytest.raises(Refused, match='^This file has 3 curves. Choose the one to compare with --curve.$'):
        run(client, 'compare', '--asset', 'a', '--revision', 'r', '--file', str(tmp_path / 'two.las'))
    assert client.calls == []
    (tmp_path / 'ref.las').write_bytes(LAS)
    with pytest.raises(Exception) as limit:
        run(Recorded({'compare': refusal(409, 'limit')}), 'compare', '--asset', 'a', '--revision', 'r', '--file', str(tmp_path / 'ref.las'))
    assert str(limit.value) == 'You have saved 20 comparisons on this result. Ask a project administrator to review them.'


# --- publishers --------------------------------------------------------------------------------------------------------

def test_publishers_add_remove_and_list_in_words():
    granted = {'publishers': [{'principal': 'marit', 'kind': 'person', 'granted_by': 'alice', 'at': AT}]}
    client = Recorded({'publishers': granted})
    assert run(client, 'publishers', 'add', 'marit')[0] == 'Marit Jansen can publish checks for this project.'
    assert run(client, 'publishers', 'remove', 'svc-ci', '--workload')[0] == 'svc-ci can no longer publish checks for this project.'
    assert run(client, 'publishers', 'list')[0] == 'Marit Jansen can publish checks for this project.'
    assert [c[2] for c in client.calls] == [{'action': 'grant', 'principal': 'marit', 'kind': 'person'},
                                            {'action': 'revoke', 'principal': 'svc-ci', 'kind': 'workload'}, {'action': 'list'}]
    assert run(Recorded({'publishers': {'publishers': []}}), 'publishers', 'list')[0] == 'Only the project administrators can publish checks for this project.'
    with pytest.raises(PermissionRefused, match='^Only a project administrator can change who may publish checks.$'):
        run(Recorded({'publishers': PermissionRefused('Check project access and the approved grant.', status=403)}), 'publishers', 'add', 'marit')
