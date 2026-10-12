"""E59 C5, in-process gateway lane: a storage folder browsed and imported through `client.browse`,
`client.import_storage` and `ophiolite sources browse|import`. The gateway reads every object with the person's own
sign-in to the storage (the Connectors fake on loopback); the SDK and the command line send the connection and the keys,
never a file byte, and take no storage key. The report is E55's report; its rows are literals written by hand."""
import base64
import csv
import json

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401
from project_gateway.tests.test_connection_admin_bucket import ACCESS, SECRET, fakes
from project_gateway.tests.test_upload_runs import MINI
from project_gateway.upload_runs import COPY_REFUSED, READ_IN_PLACE
from ophiolite import Client, Credential, cli

ORIGIN = 'https://workspace.example'
FOLDER = 'nlog/'
COPY = {'retention_permitted': True, 'redistribution_permitted': True, 'audience': ['alice', 'bob']}
SETTINGS = dict(attribution='NLOG.NL', rights_confirmed=True)
# E55's outcomes for the same six files (Platform test_upload_runs MINI), in path order, written by hand
OTHER = ('Other/notes.txt', 'Not supported', '', '', 'No reader recognises this file.')
ROWS = [('TUM-02/TUBBERGEN_MANDER__2_RUN_06_RAW_CH_NOV_1991_06R_1.las', 'Added', 'Well log (LAS)', '617 rows, 2 curves, 0 missing samples'),
        ('TUM-02/TUBBERGEN_MANDER__2_RUN_06_RAW_CH_NOV_1991_06R_1_copy.las', 'Already here', 'Well log (LAS)', ''),
        ('TUM-03-S2/TUBBERGEN_MANDER__3B_RUN_04_RAW_OH_5_7_8__04R_1.las', 'Added', 'Well log (LAS)', '394 rows, 3 curves, 2 missing samples'),
        ('TUM-03-S2/TUBBERGEN_MANDER__3B_RUN_06_RAW_OH_5_7_8__06R_1.las', 'Added', 'Well log (LAS)', '702 rows, 5 curves, 144 missing samples'),
        ('TUM-03-S2/TUBBERGEN_MANDER__3B_RUN_06_RAW_OH_5_7_8__06R_1_damaged.las', 'Not read', 'Well log (LAS)', '')]


@pytest.fixture
def storage(keyed):
    web = keyed
    f = fakes.Fake()
    f.listener = fakes.Listener(f.port)
    for path, raw in MINI:
        f.store.put(FOLDER + path, raw)
    web.a.sources.registry.connections['logs'] = {
        'id': 'logs', 'name': 'Well logs', 'type': 'bucket', 'namespace': 'storage.example/e59', 'principals': {'alice': True},
        'endpoint': 'http://127.0.0.1:%d' % f.port, 'region': 'us-east-1', 'bucket': fakes.BUCKET, 'folder': FOLDER, 'release_policy': dict(COPY),
        '_credential_resolver': lambda principal: (ACCESS, SECRET), '_destination_policy': fakes.policy}
    yield web, f
    f.listener.close(); f.close()


def keyed_client(web):
    return Client(ORIGIN, 'p', Credential.bearer(create(web, 'write')['key']), web.c)


def requests(web):
    log = []
    def record(request):
        if '/upload-runs/' in request.url.path or '/sources/' in request.url.path:
            header = request.headers.get('x-ophiolite-upload')
            log.append((request.url.path.rsplit('/', 1)[1], json.loads(base64.b64decode(header)) if header else None, request.content))
    web.c.event_hooks['request'].append(record)
    return log


def command(web, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', create(web, 'write')['key'])
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c))
    base = ['--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json')]
    def run(*argv):
        try: return 0, cli.entrypoint(['sources', *argv, *base])
        except SystemExit as exit_: return exit_.code, None
    return run


def rows(path):
    return [(r['path'][len(FOLDER):], r['result'], r['kind'], r['read'], r['reason']) for r in csv.DictReader(path.open())]


def test_browse_answers_one_page_with_literal_keys(storage, tmp_path, monkeypatch, capsys):
    web, fake = storage
    run = command(web, tmp_path, monkeypatch)
    capsys.readouterr()
    assert run('browse', 'logs', '--prefix', FOLDER + 'TUM-02/', '--json')[0] == 0
    answer = json.loads(capsys.readouterr().out)
    assert set(answer) == {'connection_id', 'prefix', 'page'} and (answer['connection_id'], answer['prefix']) == ('logs', FOLDER + 'TUM-02/')
    assert set(answer['page']) == {'items', 'folders', 'next_cursor', 'next_offset', 'left_out', 'left_out_sentence'}
    first = answer['page']['items'][0]
    assert set(first) == {'key', 'name', 'folder', 'size', 'modified', 'etag', 'profile', 'read_in_place'}
    assert (first['key'], first['folder'], first['size'], first['profile'], first['read_in_place']) == (
        FOLDER + ROWS[0][0], FOLDER + 'TUM-02/', len(MINI[0][1]), 'las2/1', True)
    assert answer['page']['next_cursor'] is None
    page = keyed_client(web).browse('logs', FOLDER + 'Other/')
    assert [(i['name'], i['profile'], i['read_in_place']) for i in page['items']] == [('notes.txt', None, False)]


def test_an_import_read_in_place_gives_e55s_report_and_sends_no_file_byte(storage, tmp_path, monkeypatch, capsys):
    web, fake = storage
    log = requests(web)
    run = command(web, tmp_path, monkeypatch)
    code, _ = run('import', 'logs', '--attribution', 'NLOG.NL', '--rights-confirmed', '--report', str(tmp_path / 'r.csv'))
    assert code == 4  # a damaged file and a kind Ophiolite does not read, as for an upload of the same folder
    got = rows(tmp_path / 'r.csv')
    in_place = [OTHER[:3]] + [r[:3] for r in ROWS]
    in_place[2] = (ROWS[1][0], 'Added', 'Well log (LAS)')  # another object of the same bytes is another selection: read in place, it is added too
    assert [(p, result, kind) for p, result, kind, *_ in got] == in_place
    assert [read for p, result, kind, read, _ in got if result == 'Added'] == ['', '', '', '']  # nothing was copied, so nothing was read into the project
    assert {reason for p, result, kind, read, reason in got if result == 'Added'} == {READ_IN_PLACE}
    assert [reason for p, *_, reason in got if p.endswith('_damaged.las')] == ['The file is damaged or is not plain text (UTF-8). Nothing was repaired; export a UTF-8 LAS 2.0 copy.']
    assert got[0][4].startswith(OTHER[4] + ' Supported kinds: Well log (LAS), ')  # notes.txt: no reader, worded as for an upload
    assert {n for op, h, body in log if op in ('check', 'file') for n in [len(body)]} == {0}  # no file byte leaves the SDK
    assert all(h['bucket'] for op, h, _ in log if op == 'file') and [op for op, *_ in log].count('check') == len(MINI)
    sent = b''.join(body for *_, body in log) + json.dumps([h for _, h, _ in log]).encode()
    assert SECRET.encode() not in sent and ACCESS.encode() not in sent


def test_an_import_kept_as_a_copy_ends_each_file_as_an_upload_of_it_does(storage, tmp_path):
    web, fake = storage
    report = keyed_client(web).import_storage('logs', keep_copy=True, audience=['bob'], **SETTINGS)
    report.save(tmp_path / 'r.csv'); report.save(tmp_path / 'r.json')
    assert (report.view['folder_name'], report.left_out) == ('logs', [])
    assert [r[:4] for r in rows(tmp_path / 'r.csv')] == [OTHER[:4]] + ROWS
    assert rows(tmp_path / 'r.csv')[0][4].startswith(OTHER[4] + ' Supported kinds: Well log (LAS), ')
    assert json.loads((tmp_path / 'r.json').read_text())['settings']['source'] == {'bucket': 'logs', 'custody': 'copy', 'keys': [FOLDER + p for p, _ in sorted(MINI)]}
    again = keyed_client(web).import_storage('logs', keep_copy=True, new=True, **SETTINGS)
    assert again.counts == {'added': 0, 'already-here': 4, 'needs-decision': 0, 'not-read': 1, 'not-supported': 1}


def test_keep_copy_without_the_organisations_declaration_is_refused_with_the_browsers_sentence(storage, tmp_path, monkeypatch, capsys):
    web, fake = storage
    web.a.sources.registry.connections['logs']['release_policy'] = {'retention_permitted': False, 'redistribution_permitted': False, 'audience': []}
    count = lambda: web.a.journal.db.execute('SELECT count(*) FROM retained_assets').fetchone()
    with web.a.journal.lock: before = count()
    run = command(web, tmp_path, monkeypatch)
    capsys.readouterr()
    assert run('import', 'logs', '--keep-copy', '--attribution', 'NLOG.NL', '--rights-confirmed', '--json')[0] == 3
    error = json.loads(capsys.readouterr().out)['error']
    assert (error['code'], error['message']) == ('copy-not-allowed', COPY_REFUSED + " Retry once; if it fails again, report the request id to the deployment's operator.")
    with web.a.journal.lock: assert count() == before


def test_the_command_line_takes_no_storage_key():
    sources = cli.parser()._subparsers._group_actions[0].choices['sources']
    options = sorted(o for action in sources._actions for o in action.option_strings)
    assert options == ['--attribution', '--audience', '--configuration', '--credentials', '--cursor', '--expect-revision', '--force', '--help', '--json',
                       '--keep-copy', '--original', '--out', '--prefix', '--report', '--require-all-columns', '--rights-confirmed', '-h']


def test_an_object_above_the_request_limit_is_left_out_with_the_deployments_sentence(storage, tmp_path, monkeypatch):
    import tracemalloc
    web, fake = storage
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', str(32 * 2**20))
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * 2**20))
    fake.store.put(FOLDER + 'big/forty.las', b'~V' + b'x' * (40 * 2**20 - 2))
    fake.store.put(FOLDER + 'big/large.las', b'~V' + b'y' * (32 * 2**20 - 2))
    log = requests(web)
    client = keyed_client(web)
    tracemalloc.start()
    try:
        report = client.import_storage('logs', FOLDER + 'big/', keep_copy=True, **SETTINGS)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    print('E59 C5 import of a 32 MiB object (gateway in process): peak %.1f MiB' % (peak / 2**20))
    assert report.left_out == [(FOLDER + 'big/forty.las', 'This file is larger than 32 MiB and cannot be read in place.')]
    assert [(i['path'], i['state']) for i in report.items] == [(FOLDER + 'big/large.las', 'not-read')]
    assert {len(body) for op, h, body in log if op in ('check', 'file')} == {0} and client.upload_runs.sent_bytes == 0
    assert peak < 4 * 32 * 2**20  # the gateway's read buffer and body (the SDK holds no file byte)


def test_an_import_lists_every_subfolder_and_every_page_before_it_starts(monkeypatch):
    """The fake storage ignores the delimiter, so the walk over folders and cursors is scripted here."""
    from ophiolite.upload_runs import UploadRuns
    pages = {(None, None): {'items': [{'key': 'nlog/a.las', 'size': 3}], 'folders': ['nlog/', 'nlog/b/'], 'next_cursor': None},
             ('nlog/', None): {'items': [{'key': 'nlog/a.las', 'size': 3}], 'folders': ['nlog/', 'nlog/b/'], 'next_cursor': None},
             ('nlog/b/', None): {'items': [{'key': 'nlog/b/c.las', 'size': 4}], 'folders': [], 'next_cursor': 'next'},
             ('nlog/b/', 'next'): {'items': [{'key': 'nlog/b/d.las', 'size': 0}], 'folders': [], 'next_cursor': None}}
    class Stub:
        project = 'p'
        def browse(self, connection, prefix, cursor): return pages[(prefix, cursor)]
    runs = UploadRuns(Stub())
    monkeypatch.setattr(runs, 'check_object', lambda connection, key: {'fetched': {'bytes': {'nlog/a.las': 3, 'nlog/b/c.las': 4}[key], 'sha256': 'f' * 64}})
    folder = runs.stored('logs')
    assert [(f.path, f.size, f.stored) for f in folder.files] == [('nlog/a.las', 3, True), ('nlog/b/c.las', 4, True), ('nlog/b/d.las', 0, True)]
    assert folder.files[2].sha256 == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'  # an empty object is not checked
    assert (folder.name, folder.connection, folder.left_out) == ('logs', 'logs', [])
