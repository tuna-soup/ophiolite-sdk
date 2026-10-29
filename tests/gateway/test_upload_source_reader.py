"""E122 s1b C2, in-process gateway lane: `ophiolite upload --source NAME` of the same file after the deployment's reader
changed (a newer lasio) counts it changed; the client's report gives that file's reason, the server's `READ_AGAIN`
naming version 1, as served (the CLI prints the counts sentence only: `text()` skips Added rows, F1)."""
import json

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from project_gateway import applications
from project_gateway.tests.test_upload_runs import MINI
from ophiolite import cli

ORIGIN = 'https://workspace.example'
NAME = 'Petrel export'
FILE = MINI[3]
READER = {'reader': 'asset_connectors.las_reader/1', 'mapping': 'application-curve/1', 'parsing_policy': 'las2-strict-null/1',
          'null_policy': 'strict declared NULL; nonfinite samples mapped to null; wrapped rows use declared curve count'}
READ_AGAIN = 'Read again with an updated reader: the file and its settings are those of version 1.'


def folder(tmp_path, name='Survey'):
    root = tmp_path / name
    (root / FILE[0]).parent.mkdir(parents=True, exist_ok=True); (root / FILE[0]).write_bytes(FILE[1])
    return root


def read_by(monkeypatch, lasio):
    monkeypatch.setattr(applications, 'live_interpretation', lambda: {**READER, 'lasio_version': lasio})


def upload(web, tmp_path, monkeypatch, capsys, root):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: __import__('ophiolite').Client(url, project, credential, web.c))
    capsys.readouterr()
    assert cli.entrypoint(['upload', str(root), '--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'),
                           '--attribution', 'NLOG.NL', '--audience', 'me', '--rights-confirmed', '--new', '--source', NAME]) is None
    lines = capsys.readouterr().out.strip().splitlines()
    return [l for l in lines if 'Run: ophiolite wells from-run' not in l]  # the wells hint is an earlier slice's line, unchanged here


def test_the_same_file_read_by_a_newer_reader_prints_one_changed(web, tmp_path, monkeypatch, capsys):
    root = folder(tmp_path)
    read_by(monkeypatch, '0.97')
    assert upload(web, tmp_path, monkeypatch, capsys, root)[-2:] == ['Compared with the last send of Petrel export: 0 unchanged, 0 changed, 1 new.',
                                                                     '1 item from 1 file: 0 unchanged, 0 changed, 1 new.']  # E122 s3a: the items, as served
    read_by(monkeypatch, '0.98')
    assert upload(web, tmp_path, monkeypatch, capsys, root) == [
        'Survey - 1 files - Finished. 1 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported',
        'Compared with the last send of Petrel export: 0 unchanged, 1 changed, 0 new.',
        '1 item from 1 file: 0 unchanged, 1 changed, 0 new.']
    assert upload(web, tmp_path, monkeypatch, capsys, root)[-2:] == ['Compared with the last send of Petrel export: 1 unchanged, 0 changed, 0 new.',
                                                                     '1 item from 1 file: 1 unchanged, 0 changed, 0 new.']


def test_the_report_gives_the_reason_the_server_said(web, tmp_path, monkeypatch):
    alice = client(web, 'alice', 'delegate')
    root = folder(tmp_path)
    read_by(monkeypatch, '0.97')
    assert alice.upload_runs.upload(root, attribution='NLOG.NL', rights_confirmed=True, source_name=NAME).counts['added'] == 1
    read_by(monkeypatch, '0.98')
    report = alice.upload_runs.upload(root, attribution='NLOG.NL', rights_confirmed=True, source_name=NAME)
    assert report.view['changes']['sentence'] == 'Compared with the last send of Petrel export: 0 unchanged, 1 changed, 0 new.'
    assert [(r['result'], r['reason']) for r in report.rows()] == [('Added', READ_AGAIN)]
