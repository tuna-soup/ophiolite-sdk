"""E55 C5, in-process gateway lane: a folder upload through client.upload_runs and `ophiolite upload`, against the real
gateway routes. The mini-folder (three real NLOG logs, a copy, a damaged copy and a note) gives one outcome per file;
an interrupted upload continues with the files not yet added, and only their bytes are sent again."""
import csv
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from project_gateway.tests.test_upload_runs import MINI
from ophiolite import cli
from ophiolite.errors import PermissionRefused

ORIGIN = 'https://workspace.example'
SETTINGS = dict(attribution='NLOG.NL', audience=['bob'], rights_confirmed=True)


def folder(tmp_path, files=MINI, name='Tubbergen-Mander-2'):
    root = tmp_path / name
    for path, raw in files:
        (root / path).parent.mkdir(parents=True, exist_ok=True); (root / path).write_bytes(raw)
    return root


def sent(web):
    """The upload-runs/file requests: (mode, ordinal) of each, from the request header."""
    import base64
    log = []
    def record(request):
        if request.url.path.endswith('/upload-runs/file'):
            header = json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))
            log.append((header['mode'], header['ordinal'], len(request.content)))
    web.c.event_hooks['request'].append(record)
    return log


def test_the_mini_folder_gives_one_outcome_per_file_and_a_clean_folder_is_ok(web, tmp_path):
    alice = client(web, 'alice', 'delegate')
    report = alice.upload_runs.upload(folder(tmp_path), **SETTINGS)
    assert report.counts == {'added': 3, 'already-here': 1, 'needs-decision': 0, 'not-read': 1, 'not-supported': 1}
    assert (report.label, report.ok) == ('Finished with files not added', False)
    rows = report.rows()
    assert [r['result'] for r in rows] == ['Not supported', 'Added', 'Already here', 'Added', 'Added', 'Not read']  # in path order
    assert rows[3]['read'] == '394 rows, 3 curves, 2 missing samples' and rows[3]['kind'] == 'Well log (LAS 2.0)'
    assert rows[5]['reason'] == 'The file is damaged or is not plain text (UTF-8). Nothing was repaired; export a UTF-8 LAS 2.0 copy.'
    clean = alice.upload_runs.upload(folder(tmp_path, MINI[:1], 'Clean'), **SETTINGS)
    assert (clean.counts['already-here'], clean.ok, clean.label) == (1, True, 'Finished')


def test_an_interrupted_upload_sends_only_the_files_not_yet_added(web, tmp_path, monkeypatch):
    alice = client(web, 'alice', 'delegate')
    root = folder(tmp_path, MINI[2:])  # the note, RUN04, RUN06 and the damaged copy, in path order: four rows, each sent
    log = sent(web)
    real, calls = alice.upload_runs.__class__._file, []
    def stop_after_two(self, run_id, ordinal, files):
        if len(calls) == 2: raise KeyboardInterrupt
        calls.append(ordinal); return real(self, run_id, ordinal, files)
    monkeypatch.setattr(alice.upload_runs.__class__, '_file', stop_after_two)
    with pytest.raises(KeyboardInterrupt): alice.upload_runs.upload(root, **SETTINGS)
    monkeypatch.setattr(alice.upload_runs.__class__, '_file', real)
    first = list(log); log.clear()
    runs = alice.upload_runs
    report = runs.upload(root, **SETTINGS)
    assert sorted({o for _, o, _ in first}) == [0, 1] and sorted({o for _, o, _ in log}) == [2, 3]
    order = [MINI[2:][i] for i in (3, 0, 1, 2)]  # Other/ first, then TUM-03-S2/ sorted
    s2, s3 = len(order[2][1]), len(order[3][1])
    assert [(m, o) for m, o, _ in log] == [('head', 2), ('body', 2), ('head', 3), ('body', 3)]
    assert runs.sent_bytes == sum(n for _, _, n in log) == min(s2, 65536) + s2 + min(s3, 65536) + s3  # never a byte of files 0 and 1
    assert report.counts == {'added': 2, 'already-here': 0, 'needs-decision': 0, 'not-read': 1, 'not-supported': 1}
    assert len(runs.list()) == 1  # continued, not started again
    again = runs.upload(root, new=True, **SETTINGS)
    assert again.counts['already-here'] == 2 and len(runs.list()) == 2


def test_a_file_whose_bytes_were_lost_after_its_head_is_sent_when_its_claim_ends(web, tmp_path, monkeypatch):
    """Codex round 3: the head was accepted (the row is reading, claimed for 120 s) and the body never arrived. Sending
    again waits for the claim to end instead of returning an unfinished report; the deployment lets the file wait
    again and it is sent (mutation: status not releasing expired claims leaves the row reading)."""
    import base64, types, time as real
    import httpx
    import ophiolite.upload_runs as sdk_runs
    import project_gateway.upload_runs as gateway_runs
    alice = client(web, 'alice', 'delegate')
    root = folder(tmp_path, MINI[2:3], 'Lost')
    log = sent(web)
    lose = [True]
    def drop(request):
        if request.url.path.endswith('/upload-runs/file') and json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))['mode'] == 'body' and lose:
            lose.clear(); raise httpx.ConnectError('lost', request=request)
    web.c.event_hooks['request'].append(drop)
    with pytest.raises(Exception): alice.upload_runs.upload(root, **SETTINGS)
    run = alice.upload_runs.list()[0]
    assert alice.upload_runs.status(run['run_id']).items[0]['state'] == 'reading'
    offset, slept = [0.0], []
    monkeypatch.setattr(gateway_runs, 'time', types.SimpleNamespace(time=lambda: real.time() + offset[0]))
    monkeypatch.setattr(sdk_runs, 'time', types.SimpleNamespace(monotonic=lambda: real.monotonic() + offset[0], sleep=lambda s: (slept.append(s), offset.__setitem__(0, 200.0))))
    log.clear()
    report = alice.upload_runs.upload(root, **SETTINGS)
    assert report.run_id == run['run_id'] and report.counts['added'] == 1 and slept == [5.0]
    assert [(m, o) for m, o, _ in log] == [('head', 0), ('body', 0)]


def test_the_command_line_writes_the_report_and_exits_by_outcome(web, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: __import__('ophiolite').Client(url, project, credential, web.c))
    root = folder(tmp_path)
    argv = ['upload', str(root), '--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'),
            '--attribution', 'NLOG.NL', '--rights-confirmed', '--report', str(tmp_path / 'report.csv')]
    with pytest.raises(SystemExit) as exit_: cli.entrypoint(argv)
    assert exit_.value.code == 4
    rows = list(csv.DictReader((tmp_path / 'report.csv').open()))
    assert list(rows[0]) == ['path', 'result', 'kind', 'read', 'reason', 'asset']
    assert [r['result'] for r in rows] == ['Not supported', 'Added', 'Already here', 'Added', 'Added', 'Not read']
    assert rows[1]['path'] == 'Tubbergen-Mander-2/TUM-02/TUBBERGEN_MANDER__2_RUN_06_RAW_CH_NOV_1991_06R_1.las' and rows[1]['asset']
    clean = folder(tmp_path, MINI[2:4], 'Clean')
    assert cli.entrypoint(argv[:1] + [str(clean)] + argv[2:-2]) is None  # every file already here: exit 0
    with pytest.raises(SystemExit) as exit_: cli.entrypoint(argv[:-3])
    assert exit_.value.code == 1  # no --rights-confirmed: refused before anything is sent


def test_a_decision_answered_for_one_kind_leaves_the_others(web, tmp_path):
    from project_gateway.tests.upload_compat import fixture
    grid = fixture('esri-ascii-grid/1').read_bytes()
    alice = client(web, 'alice', 'delegate')
    points = fixture('points-csv/1')
    root = folder(tmp_path, [('g/one.asc', grid), ('g/two.asc', grid.replace(b'\n', b' \n', 1)), ('p/' + points.name, points.read_bytes())], 'Grids')
    first = alice.upload_runs.upload(root, **SETTINGS)
    assert first.counts['needs-decision'] == 3
    report = alice.upload_runs.upload(root, declare={'esri-ascii-grid/1': {'crs': 'EPSG:28992'}}, **SETTINGS)
    assert [(i['state'], i['declared']) for i in report.items] == [('added', {'crs': 'EPSG:28992'})] * 2 + [('needs-decision', None)]  # the points keep theirs
    other = alice.upload_runs.upload(folder(tmp_path, [('h/three.asc', grid.replace(b'\n', b'  \n', 1))], 'More'), declare={'las2/1': {'x': 'y'}}, **SETTINGS)
    assert other.counts['needs-decision'] == 1  # a declaration for another kind is not applied
    skipped = alice.upload_runs.upload(folder(tmp_path, [('h/three.asc', grid.replace(b'\n', b'  \n', 1))], 'More'), skip_decisions=True, **SETTINGS)
    assert skipped.counts.get('cancelled') == 1 and skipped.items[0]['sentence'] == 'Skipped by you.'


def test_a_viewer_is_refused_before_any_file_is_sent(web, tmp_path):
    viewer = client(web, 'viewer', 'delegate')
    log = sent(web)
    with pytest.raises(PermissionRefused): viewer.upload_runs.upload(folder(tmp_path), **SETTINGS)
    assert log == []


def test_a_file_above_the_request_limit_goes_in_parts_and_the_run_adds_it(web, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', str(32768))
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * 1024 * 1024))
    alice = client(web, 'alice', 'delegate')
    paths = []
    web.c.event_hooks['request'].append(lambda request: paths.append(request.url.path.rsplit('/', 2)[-2] + '/' + request.url.path.rsplit('/', 1)[-1]))
    big = MINI[3]  # RUN06 (41,814 bytes), above 32 KiB
    assert len(big[1]) > 32768
    report = alice.upload_runs.upload(folder(tmp_path, [big], 'Parts'), **SETTINGS)
    assert report.counts['added'] == 1 and report.items[0]['read'] == '702 rows, 5 curves, 144 missing samples'
    assert 'las-uploads/part' in paths and 'las-uploads/begin' not in paths and 'las-uploads/publish' not in paths
    assert paths.count('upload-runs/file-parts') >= 2 and ('upload-runs/file' in paths)
