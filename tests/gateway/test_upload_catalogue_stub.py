"""E127 s0 C4, as slice a (E127 s1a C5) replaced its expectations: the installed SDK's `ophiolite upload` on the
in-process gateway reads a pinned OSD manifest's listed files (the transport scripted through `Fetcher`, as the
gateway's own tests script it). The CSV has a row per listed file after the manifest's; the text lists a file not
added; the run exits 0 when every file was added or is already here and 4 otherwise (cli.py `_upload`: the manifest's
row carries the aggregate, A9). An unrelated JSON file still reads as no reader's.

Mutations (recorded in the E127 slice a Validation Record): the server's A9 as rev 2 (`added` when one landed) -> the
mixed case exits 0; `rows` without catalogue outputs -> the CSV assertions fail."""
import csv
import json
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import cli

ORIGIN = 'https://workspace.example'
OSD = Path(__file__).resolve().parents[3] / 'conformance/fixtures/osd'
MANIFEST = (OSD / 'manifest-two-wells.json').read_bytes()
WELL_A, WELL_B = (OSD / 'well-a.las').read_bytes(), (OSD / 'well-b.las').read_bytes()
R2 = "This file's bytes do not match the checksum the manifest states. Nothing was added."
REFUSED = 'This file needs a sign-in, a request or a purchase at its publisher; nothing was fetched.'
CONTROL = 'No reader recognises this file. Supported kinds: '
NAME = 'manifest-two-wells.json'


@pytest.fixture
def scripted(monkeypatch):
    """Both listed files at their `href`; requested before `web`, so the gateway's fetcher is this one."""
    from project_gateway import address_fetch
    from project_gateway.tests.test_address_fetch import PUBLIC, Script, ok
    monkeypatch.setenv(address_fetch.SWITCH, 'on')
    script = Script({'/two-wells/well-a.las': ok(WELL_A), '/two-wells/well-b.las': ok(WELL_B)}, names={'acme.example': [PUBLIC]})
    monkeypatch.setattr(address_fetch, 'Fetcher', lambda: script.fetcher())
    return script, ok


def upload(web, tmp_path, monkeypatch, folder, files):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: __import__('ophiolite').Client(url, project, credential, web.c))
    root = tmp_path / folder
    root.mkdir()
    for name, raw in files.items(): (root / name).write_bytes(raw)
    report = tmp_path / ('%s.csv' % folder)
    argv = ['upload', str(root), '--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'),
            '--attribution', 'Synthetic test', '--rights-confirmed', '--report', str(report)]
    try: cli.entrypoint(argv); code = 0  # cli.entrypoint returns on exit code 0
    except SystemExit as exit_: code = exit_.code
    return code, {r['path']: r for r in csv.DictReader(report.open())}


def results(rows, folder):
    return [(path, r['result'], r['reason'], bool(r['asset'])) for path, r in rows.items() if path.startswith('%s/%s' % (folder, NAME))]


def test_every_listed_file_added_exits_0_and_a_second_folder_finds_them_already_here(scripted, web, tmp_path, monkeypatch):
    code, rows = upload(web, tmp_path, monkeypatch, 'catalogue', {NAME: MANIFEST, 'other.json': json.dumps({'format': 'geojson'}).encode()})
    assert code == 4  # other.json is no reader's
    assert results(rows, 'catalogue') == [('catalogue/%s' % NAME, 'Added', '', False), ('catalogue/%s: Listed file 1' % NAME, 'Added', '', True),
                                          ('catalogue/%s: Listed file 2' % NAME, 'Added', '', True)]
    assert rows['catalogue/other.json']['result'] == 'Not supported' and rows['catalogue/other.json']['reason'].startswith(CONTROL)
    code, rows = upload(web, tmp_path, monkeypatch, 'again', {NAME: MANIFEST})
    assert code == 0 and [r[1] for r in results(rows, 'again')] == ['Already here', 'Already here', 'Already here']


def test_a_file_not_added_exits_4_with_its_row_and_its_line(scripted, web, tmp_path, monkeypatch, capsys):
    script, ok = scripted
    script.pages['/two-wells/well-b.las'] = ok(WELL_B.replace(b'1500.5    91.40', b'1500.5    91.50'))
    code, rows = upload(web, tmp_path, monkeypatch, 'catalogue', {NAME: MANIFEST})
    assert code == 4
    assert results(rows, 'catalogue') == [('catalogue/%s' % NAME, 'Not read', '1 of the 2 files this manifest lists were not added.', False),
                                          ('catalogue/%s: Listed file 1' % NAME, 'Added', '', True), ('catalogue/%s: Listed file 2' % NAME, 'Not added', R2, False)]
    assert '  catalogue/%s: Listed file 2: Not added - %s' % (NAME, R2) in capsys.readouterr().out.split('\n')


def test_a_manifest_whose_files_are_all_refused_exits_4(scripted, web, tmp_path, monkeypatch):
    four = json.loads((OSD / 'manifest-two-wells-v4.json').read_bytes())
    four['entries'][0]['access'] = 'purchase'
    code, rows = upload(web, tmp_path, monkeypatch, 'catalogue', {NAME: json.dumps(four).encode()})
    assert code == 4
    assert [(r[1], r[2]) for r in results(rows, 'catalogue')[1:]] == [('Not added', REFUSED), ('Not added', REFUSED)]
    assert scripted[0].gets == []
