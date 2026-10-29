"""E122 s1 C4, in-process gateway lane: `ophiolite upload --source NAME` twice on the C2 folder (the three distinct NLOG
logs, `COUNTS.md`) prints the hand counts, the second time with one file changed; without `--source` the output is the
report line alone, as before. E122 s2 C4: `--complete` twice with one file removed prints the served gone line, then
`--incremental` prints none; `Provenance.gone` is the served object; without `--new` only the same send resumes (R13)."""
import json

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from project_gateway.tests.test_upload_runs import MINI, RUN06
from ophiolite import cli

ORIGIN = 'https://workspace.example'
FOLDER = [MINI[0], MINI[2], MINI[3]]
NAME = 'Petrel export'


def folder(tmp_path, files, name='Survey'):
    root = tmp_path / name
    for path, raw in files:
        (root / path).parent.mkdir(parents=True, exist_ok=True); (root / path).write_bytes(raw)
    return root


def upload(web, tmp_path, monkeypatch, capsys, root, *extra, new=True):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: __import__('ophiolite').Client(url, project, credential, web.c))
    capsys.readouterr()
    assert cli.entrypoint(['upload', str(root), '--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'),
                           '--attribution', 'NLOG.NL', '--audience', 'me', '--rights-confirmed', *(['--new'] if new else []), *extra]) is None
    lines = capsys.readouterr().out.strip().splitlines()
    return [l for l in lines if 'Run: ophiolite wells from-run' not in l]  # the wells hint is an earlier slice's line, unchanged here


def test_a_named_folder_sent_twice_prints_the_counts(web, tmp_path, monkeypatch, capsys):
    root = folder(tmp_path, FOLDER)
    first = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME)
    assert first == ['Survey - 3 files - Finished. 3 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported',
                     'Compared with the last send of Petrel export: 0 unchanged, 0 changed, 3 new.',
                     '3 items from 3 files: 0 unchanged, 0 changed, 3 new.']  # E122 s3a: the items, as served
    (root / FOLDER[2][0]).write_bytes(RUN06.replace(b'0.0000', b'0.0001', 1))
    second = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME)
    assert second == ['Survey - 3 files - Finished. 1 Added, 2 Already here, 0 Needs your decision, 0 Not read, 0 Not supported',
                      'Compared with the last send of Petrel export: 2 unchanged, 1 changed, 0 new.',
                      '3 items from 3 files: 2 unchanged, 1 changed, 0 new.']


def test_without_a_source_the_report_is_the_line_it_was(web, tmp_path, monkeypatch, capsys):
    out = upload(web, tmp_path, monkeypatch, capsys, folder(tmp_path, FOLDER[:1]))
    assert out == ['Survey - 1 files - Finished. 1 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported']


GONE = 'Not in this complete send of Petrel export, so marked gone from the source: `Survey/%s`. Nothing was removed.' % FOLDER[2][0]  # the folder's name leads its paths


def test_a_complete_send_with_a_file_removed_prints_what_is_gone_and_an_incremental_one_does_not(web, tmp_path, monkeypatch, capsys):
    """D7. Mutation M14: `--complete` not sent -> the second send marks nothing -> no gone line -> FAIL."""
    root = folder(tmp_path, FOLDER)
    first = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME, '--complete')
    assert first[1:] == ['Compared with the last send of Petrel export: 0 unchanged, 0 changed, 3 new.',
                         '3 items from 3 files: 0 unchanged, 0 changed, 3 new.',
                         'This complete send of Petrel export finished: nothing is gone from the source.']
    (root / FOLDER[2][0]).unlink()
    second = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME, '--complete')
    assert second == ['Survey - 2 files - Finished. 0 Added, 2 Already here, 0 Needs your decision, 0 Not read, 0 Not supported',
                      'Compared with the last send of Petrel export: 2 unchanged, 0 changed, 0 new.',
                      '2 items from 2 files: 2 unchanged, 0 changed, 0 new.', GONE]
    third = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME, '--incremental')
    assert third == second[:3]
    item, revision = web.a.journal.db.execute("SELECT g.asset_id,r.revision FROM source_gone g JOIN retained_assets r ON r.id=g.asset_id").fetchone()
    served = web.c.get('/api/v1/projects/p/scientific-assets/%s/revisions/%s/provenance' % (item, revision),
                       headers={'Authorization': 'Bearer oph_api_alice:read'}).json()['gone']
    found = __import__('ophiolite').Client(ORIGIN, 'p', __import__('ophiolite').Credential.bearer('oph_api_alice:read'), web.c).provenance(item, revision)
    assert found.gone == served and served['sentence'] == 'Gone from Petrel export: file `Survey/%s` was not in its last complete send. Nothing was removed.' % FOLDER[2][0]


def started(web, files, **declared):
    """A run of folder Survey started (and left open) by a client that declared `declared`; its id."""
    import hashlib
    from project_gateway.tests.test_upload_runs import SETTINGS
    body = {'project_id': 'p', 'command_id': 'open-' + hashlib.sha256(repr(sorted(declared.items())).encode()).hexdigest()[:8], 'folder_name': 'Survey',
            **SETTINGS, 'audience': [], 'files': [{'path': 'Survey/' + p, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in files], **declared}
    r = web.c.post('/api/v1/projects/p/upload-runs/start', json=body, headers={'Authorization': 'Bearer oph_api_alice:read,write'})
    assert r.status_code == 200, r.text
    return r.json()['run_id']


def test_without_new_only_the_same_send_resumes(web, tmp_path, monkeypatch, capsys):
    """R13, D7: the CLI without `--new` resumes the open run of the same folder only when its source name, send and scope
    are the ones it declares. Mutation M20: resume by listing only -> the other-name upload resumes it -> FAIL."""
    root = folder(tmp_path, FOLDER[:1])
    waiting = started(web, FOLDER[:1], source_name=NAME, send='complete')
    out = upload(web, tmp_path, monkeypatch, capsys, root, '--source', 'Other export', '--complete', '--json', new=False)
    assert json.loads('\n'.join(out))['upload']['run_id'] != waiting
    out = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME, '--json', new=False)  # incremental by default
    assert json.loads('\n'.join(out))['upload']['run_id'] != waiting
    out = upload(web, tmp_path, monkeypatch, capsys, root, '--source', NAME, '--complete', '--json', new=False)
    assert json.loads('\n'.join(out))['upload']['run_id'] == waiting
