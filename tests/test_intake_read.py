"""E107a C6: what this SDK says and reads about files read on your computer, without a server. It says `reads:
['procedures']` (start, every report request and every file step) only to a deployment whose capabilities list
`upload_runs.reads`; to any other it never sends the field. It parses all eleven row states, and `ophiolite intake
read` refuses a wrong file, an unchosen version and a missing setting before anything is sent. The gateway lane
(tests/gateway/test_intake_read_live.py) runs the whole read against the real routes."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path

import httpx
import pytest

from ophiolite import Client, Credential, cli, intake
from ophiolite.models.api import UploadRun
from ophiolite.procedures import NotRun
from ophiolite.upload_runs import RESULT, Report, UploadRuns

ORIGIN = 'https://gateway.example'
STATES = ('waiting', 'reading', 'added', 'already-here', 'needs-decision', 'not-read', 'not-supported', 'cancelled', 'needs-procedure', 'converting', 'converted')
PDF = b'%PDF-1.7\nGroningen\n' + b'0' * 100
SHA = hashlib.sha256(PDF).hexdigest()


def version(n, digest):
    return {'digest': digest, 'label': 'Groningen report reader', 'version_label': 'Release %d' % n, 'version': n, 'added_by_name': 'tina',
            'sentence': 'Groningen report reader, version %d, can read it on your computer.' % n}


def row(state='needs-procedure', ordinal=0, path='HON-GT-01/end of well report.pdf', **more):
    return {'ordinal': ordinal, 'path': path, 'bytes': len(PDF), 'sha256': SHA, 'role': 'primary', 'state': state, 'kind': None,
            'reason_code': {'needs-procedure': 'needs-procedure', 'not-read': 'conversion-refused'}.get(state), 'sentence': RESULT[state], **more}


def view(items, run='r' * 32):
    counts = {k: 0 for k in ('waiting', 'reading', 'added', 'already_here', 'needs_decision', 'not_read', 'not_supported', 'cancelled',
                             'needs_procedure', 'converting', 'converted')}
    for i in items: counts[i['state'].replace('-', '_')] += 1
    return {'run_id': run, 'project_id': 'p', 'folder_name': 'HON-GT-01', 'state': 'closed', 'label': 'Finished', 'files': len(items),
            'counts': counts, 'items': items, 'outputs_added': 0}


class Server:
    """The gateway's answers this SDK needs; every request is kept as (operation, body or upload header)."""
    def __init__(self, advertised, items=None):
        self.advertised, self.items, self.sent = advertised, items or [row(procedures=[version(1, 'e' * 64)])], []

    def __call__(self, request):
        operation = '/'.join(request.url.path.rsplit('/', 2)[-2:])
        header = request.headers.get('x-ophiolite-upload')
        body = json.loads(base64.b64decode(header)) if header else json.loads(request.content or b'{}')
        self.sent.append((operation, body))
        if operation == 'capabilities/describe':
            return httpx.Response(200, json={'limits': {'upload_bytes': 1 << 30, 'file_bytes': 1 << 30},
                                             **({'upload_runs': {'reads': ['procedures']}} if self.advertised else {})})
        if operation in ('upload-runs/status', 'upload-runs/cancel', 'upload-runs/start'): return httpx.Response(200, json=view(self.items))
        if operation == 'upload-runs/list': return httpx.Response(200, json={'runs': [{k: v for k, v in view(self.items).items() if k != 'items'}]})
        if operation == 'upload-runs/file': return httpx.Response(200, json={'run_id': 'r' * 32, 'step': 'next', 'file': self.items[0]})
        if operation == 'upload-runs/check': return httpx.Response(200, json={'reads': 'head', 'kind': None, 'stated': [], 'asks': []})
        return httpx.Response(404, json={'error': {'code': 'not-found', 'message': operation}})


@contextlib.contextmanager
def client(server):
    with httpx.Client(transport=httpx.MockTransport(server)) as http:
        yield Client(ORIGIN, 'p', Credential.bearer('k'), http)


def every_request(c):
    runs = c.upload_runs
    runs.status('r' * 32); runs.list(); runs.cancel('r' * 32)
    runs.check('https://example.org/a.las')
    runs._post_file('r' * 32, 0, 'head', b'%PDF-')
    runs._call('start', {'folder_name': 'HON-GT-01'}, UploadRun)


def test_an_sdk_on_a_deployment_without_the_member_never_sends_reads():
    server = Server(advertised=False)
    with client(server) as c: every_request(c)
    asked = [(op, b) for op, b in server.sent if op != 'capabilities/describe']
    assert len(asked) == 6 and all('reads' not in body for _, body in asked)


def test_an_sdk_on_a_deployment_that_lists_it_says_it_reads_read_procedures_on_every_request():
    server = Server(advertised=True)
    with client(server) as c: every_request(c)
    asked = [(op, b) for op, b in server.sent if op != 'capabilities/describe']
    assert [op for op, _ in asked] == ['upload-runs/status', 'upload-runs/list', 'upload-runs/cancel', 'upload-runs/check', 'upload-runs/file', 'upload-runs/start']
    assert all(body['reads'] == ['procedures'] for _, body in asked)
    assert [op for op, _ in server.sent].count('capabilities/describe') == 1  # read once per client


def test_every_row_state_parses_and_a_read_row_names_the_command_that_reads_it():
    items = [row(state, ordinal=n, path='HON-GT-01/f%d.pdf' % n) for n, state in enumerate(STATES)]
    items[8]['procedures'] = [version(1, 'e' * 64)]
    items[10]['outputs'] = [{'role': 'tops', 'label': 'Well tops', 'kind': 'Well tops', 'outcome': 'added', 'asset_id': 'a1', 'revision': 'r1'}]
    UploadRun.model_validate(view(items))
    report = Report(view(items))
    assert [r['result'] for r in report.rows()][8:] == ['Can be read on your computer', 'Being read on your computer', 'Read on your computer']
    assert (report.counts['needs-procedure'], report.counts['converting'], report.counts['converted']) == (1, 1, 1)
    assert '    To read it on this computer: ophiolite intake read %s f8.pdf' % ('r' * 32) in report.text().splitlines()
    plain = Report(view([row('added')]))
    assert 'needs-procedure' not in plain.counts and 'intake read' not in plain.text()


def test_a_conversion_answer_parses_with_each_state():
    from ophiolite.models.api import UploadRunConversion
    for state in ('declared', 'partial', 'complete', 'refused', 'cancelled'):
        UploadRunConversion.model_validate({'run_id': 'r', 'file': row('converting'), 'counts': view([row('converting')])['counts'], 'outputs_added': 0,
                                            'conversion': {'id': 'c', 'ordinal': 0, 'state': state, 'sentence': None, 'done': 0, 'of': 1, 'next': 'tops',
                                                           'procedure': {'digest': 'e' * 64}, 'keep_original': False,
                                                           'roles': [{'role': 'tops', 'label': 'Well tops', 'kind': 'Well tops', 'outcome': None}]}})


def refused(server, path, tmp_path, **options):
    with client(server) as c, pytest.raises(NotRun) as caught: intake.read(c, 'r' * 32, path, folder=tmp_path / 'state', **options)
    return caught.value


def test_a_deployment_without_the_member_is_told_before_anything_is_read(tmp_path):
    (tmp_path / 'end of well report.pdf').write_bytes(PDF)
    error = refused(Server(advertised=False), tmp_path / 'end of well report.pdf', tmp_path)
    assert error.code == 'not-served'


@pytest.mark.parametrize('keep', [False, True])
def test_another_file_is_refused_with_and_without_keep_original(tmp_path, keep):
    (tmp_path / 'end of well report.pdf').write_bytes(PDF.replace(b'0', b'1'))
    server = Server(advertised=True)
    error = refused(server, tmp_path / 'end of well report.pdf', tmp_path, keep_original=keep)
    assert error.code == 'other-file' and [op for op, _ in server.sent] == ['capabilities/describe', 'upload-runs/status']


@pytest.mark.parametrize('before', [False, True])
def test_a_resume_that_changes_keep_original_is_refused_before_anything_is_sent(tmp_path, before):
    """C4: --keep-original is part of the declaration saved under its command; a resume cannot change it."""
    (tmp_path / 'end of well report.pdf').write_bytes(PDF)
    state = tmp_path / 'state' / ('%s-0' % ('r' * 32))
    state.mkdir(parents=True)
    (state / 'convert.json').write_text(json.dumps({'schema': intake.STATE, 'body': {'original': {'sha256': SHA, 'bytes': len(PDF)},
                                                                                     'keep_original': before}}))
    server = Server(advertised=True)
    error = refused(server, tmp_path / 'end of well report.pdf', tmp_path, keep_original=not before)
    assert error.code == 'keep-changed' and error.details == {'keep_original': before}
    assert ('Run it again with --keep-original' if before else 'Run it again without --keep-original') in str(error)
    assert [op for op, _ in server.sent] == ['capabilities/describe', 'upload-runs/status']


def test_several_versions_without_version_are_listed_and_an_unlisted_one_is_refused(tmp_path):
    (tmp_path / 'end of well report.pdf').write_bytes(PDF)
    server = Server(advertised=True, items=[row(procedures=[version(1, 'e' * 64), version(2, 'f' * 64)])])
    error = refused(server, tmp_path / 'end of well report.pdf', tmp_path)
    assert error.code == 'several-versions' and str(error) == (
        'Not run: several read procedure versions can read this file. Choose one with --version: Groningen report reader, version 1 (%s); '
        'Groningen report reader, version 2 (%s).' % ('e' * 64, 'f' * 64))
    error = refused(server, tmp_path / 'end of well report.pdf', tmp_path, version='a' * 64)
    assert error.code == 'not-listed'
    assert not any(op.startswith('procedures/') or op.startswith('upload-runs/convert') for op, _ in server.sent)


def test_a_file_not_waiting_to_be_read_is_named(tmp_path):
    (tmp_path / 'other.pdf').write_bytes(PDF)
    assert refused(Server(advertised=True), tmp_path / 'other.pdf', tmp_path).code == 'no-file'


def test_a_temporary_convert_json_a_kill_left_is_no_state(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'convert.json.partial').write_text('{"schema": "ophiolite.intake-read/1", "bo')
    assert intake._load(state / 'convert.json') is None
    (state / 'convert.json').write_text('{"schema": "ophiolite.intake-read/1", "bo')  # torn by hand: no state either
    assert intake._load(state / 'convert.json') is None
    (state / 'convert.json').write_text(json.dumps({'schema': 'other/1'}))
    assert intake._load(state / 'convert.json') is None


def test_a_saved_output_that_changed_is_refused_and_nothing_is_sent(tmp_path):
    state = tmp_path / 'state'
    (state / 'attempt-1').mkdir(parents=True)
    (state / 'attempt-1/tops.csv').write_bytes(b'name,md\nTop,1\n')
    saved = {'attempt': 'attempt-1', 'outputs': {'tops': 'tops.csv'},
             'body': {'roles': [{'role': 'tops', 'sha256': 'a' * 64, 'bytes': 14, 'name': 'tops.csv', 'declared': {}}]}}
    with pytest.raises(NotRun) as caught: intake._saved_outputs(state, saved)
    assert caught.value.code == 'saved-output-changed'


HELP = Path(__file__).resolve().parent / 'fixtures/cli-help-e107a.json'


def test_older_commands_help_is_unchanged_and_intake_read_has_its_own(monkeypatch):
    """The help of every command that was there reads exactly as before E107a C6 (tests/fixtures/cli-help-e107a.json,
    recorded from the SDK at b3c56c475, before C6, at 100 columns; `repositories` from main 47a96b3a1, merged with E100d1; `upload` re-recorded by E122 s1 C4, whose only difference is `--source NAME`, by E122 s2 C4 (`--complete | --incremental`, `--scope DIR`), by E17p s1, which drops the dataset name from its example, by E127 s2, whose only difference is `--fidelity FIDELITY`, and by E123 S3b, whose only difference is `--share-basis | --own-basis` and `--basis ITEM=VALUE`)."""
    import argparse
    import sys
    frozen = json.loads(HELP.read_text())
    monkeypatch.setenv('COLUMNS', str(frozen['columns'])); monkeypatch.setattr(sys, 'argv', ['ophiolite'])
    def helped(*argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), pytest.raises(SystemExit): cli.parser().parse_args([*argv, '--help'])
        return out.getvalue()
    sub = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert {name: helped(name) for name in frozen['help']} == frozen['help'] and set(sub.choices) - set(frozen['help']) == {'intake', 'source', 'access-history', 'teams', 'rights', 'deliver', 'outcomes', 'residuals', 'recipes', 'starter'}  # E129 Sa: starter; E112 s2: recipes; E119b: residuals; E108: source; E67b: the two read verbs; E35a: rights; E109: deliver; E120: outcomes
    text = helped('intake', 'read')
    for flag in ('RUN', 'FILE', '--keep-original', '--version DIGEST', '--folder FOLDER', '--setting NAME=VALUE', '--yes'): assert flag in text
