"""E85 C6, in-process gateway lane (T12): one verb for a file, a folder, a zip or an address. A key created through the
access-key route (not a stub delegate) adds one fixture file per old kind through `client.upload` and `ophiolite upload`;
the counts, outcome words and stored declarations are literals. An address is fetched by the gateway: the SDK sends no
file bytes, and neither the report nor any message carries the address's query string."""
import base64
import csv
import json

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401
from project_gateway.tests.upload_compat import fixture
from project_gateway.tests.test_upload_runs import TUM2
from ophiolite import Client, Credential, cli
from ophiolite.errors import Refused, OphioliteError

ORIGIN = 'https://workspace.example'
SETTINGS = dict(attribution='Synthetic test', audience=['bob'], rights_confirmed=True)
SECRET = 'SENTINEL-SIGNATURE-c6'
ADDRESS = 'https://files.example.org/logs/TUM-02.las?X-Signature=' + SECRET
# per old kind: (what the person declares, the report's words, the declarations stored with the item) - written by hand
KINDS = {
    'las2/1': (None, 'Added', {}),
    'well-tops-csv/1': ({}, 'Added', {}),
    'deviation-csv/1': ({}, 'Added', {}),
    'esri-ascii-grid/1': ({'crs': 'EPSG:28992'}, 'Added', {'crs': 'EPSG:28992'}),
    'mesh-text/1': ({}, 'Added', {}),
    'points-csv/1': ({}, 'Added', {}),
    'opendtect-faultsticks/1': ({}, 'Added', {}),
    'segy/1': ({'crs': 'EPSG:23031', 'z_domain': 'time'}, 'Added', {'crs': 'EPSG:23031', 'z_domain': 'time'}),
    'well-location/1': (None, 'Added', {}),
    'wavelet-text/1': (None, 'Added', {}),
    'model-section-text/1': (None, 'Added', {}),
}


def keyed_client(web):
    return Client(ORIGIN, 'p', Credential.bearer(create(web, 'write')['key']), web.c)


def requests(web):
    log = []
    def record(request):
        if '/upload-runs/' in request.url.path:
            header = request.headers.get('x-ophiolite-upload')
            log.append((request.url.path.rsplit('/', 1)[1], json.loads(base64.b64decode(header)) if header else None, len(request.content)))
    web.c.event_hooks['request'].append(record)
    return log


def stored(web, asset):
    with web.a.journal.lock: row = web.a.journal.db.execute('SELECT metadata FROM retained_assets WHERE id=?', (asset,)).fetchone()
    return json.loads(row[0]).get('declared') or {}


@pytest.mark.parametrize('profile', sorted(KINDS))
def test_one_file_of_each_old_kind_lands_through_client_upload(keyed, tmp_path, profile):
    web = keyed
    declare, words, kept = KINDS[profile]
    path = tmp_path / fixture(profile).name
    path.write_bytes(fixture(profile).read_bytes())
    report = keyed_client(web).upload(path, declare={profile: declare} if declare is not None else None, **SETTINGS)
    assert [r['result'] for r in report.rows()] == [words] and report.ok
    assert report.items[0]['profile'] == profile and report.view['folder_name'] == path.name
    assert stored(web, report.items[0]['asset_id']) == kept


def test_the_command_line_adds_one_file_and_exits_by_outcome(keyed, tmp_path, monkeypatch):
    web = keyed
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', create(web, 'write')['key'])
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c))
    grid = tmp_path / fixture('esri-ascii-grid/1').name
    grid.write_bytes(fixture('esri-ascii-grid/1').read_bytes())
    base = ['--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'), '--attribution', 'Synthetic test', '--rights-confirmed']
    with pytest.raises(SystemExit) as exit_: cli.entrypoint(['upload', str(grid), *base, '--report', str(tmp_path / 'one.csv')])
    assert exit_.value.code == 4  # a grid that says nothing about its system waits for a decision
    assert [r['result'] for r in csv.DictReader((tmp_path / 'one.csv').open())] == ['Needs your decision']
    assert cli.entrypoint(['upload', str(grid), *base, '--declare', 'esri-ascii-grid/1:crs=EPSG:28992']) is None  # the same upload continues: exit 0
    with pytest.raises(SystemExit) as exit_: cli.entrypoint(['upload', str(grid), *base, '--declare', 'esri-ascii-grid/1:depth_unit=m'])
    assert exit_.value.code == 1


def test_a_declaration_the_kind_does_not_take_is_refused_naming_what_it_takes(keyed, tmp_path):
    log = requests(keyed)
    with pytest.raises(Refused) as error: keyed_client(keyed).upload(tmp_path, declare={'well-tops-csv/1': {'crs': 'EPSG:28992'}}, **SETTINGS)
    assert str(error.value) == 'Well tops (CSV) files do not take crs; they take depth_unit, depth_basis.'
    with pytest.raises(Refused, match='No kind of file is named tops'): keyed_client(keyed).upload(tmp_path, declare={'tops': {}}, **SETTINGS)
    assert log == []


def test_link_wellbore_links_only_the_one_wellbore_whose_normalised_name_the_header_names(keyed, tmp_path):
    alice = keyed_client(keyed)
    log = tmp_path / 'tum.las'
    log.write_bytes(TUM2)  # WELL. TUBBERGEN-MANDER- 2
    well = alice.create_entity('well', 'Tubbergen', audience=['bob'], provisional=True, statement='Synthetic test', command_id='c6-w')
    alice.create_entity('wellbore', 'Tubbergen Mander 12', provisional=True, audience=['bob'], part_of=well, statement='Synthetic test', command_id='c6-b12')
    alice.create_entity('wellbore', 'Tubbergen Mander 2A', provisional=True, audience=['bob'], part_of=well, statement='Synthetic test', command_id='c6-b2a')
    bore = alice.create_entity('wellbore', 'tubbergen mander 02', provisional=True, audience=['bob'], part_of=well, statement='Synthetic test', command_id='c6-b02')
    linked = alice.upload(log, link_wellbore=True, **SETTINGS)
    assert [(i['association'] or {}).get('entity_id') for i in linked.items] == [bore.entity_id]  # not 12, not 2A


@pytest.fixture
def fetched(monkeypatch):
    """The gateway's fetch, scripted at the admission boundary (the limits are proven in Platform's test_address_fetch.py)."""
    from project_gateway import address_fetch
    pages, calls = {'https://files.example.org/logs/TUM-02.las': TUM2}, []

    def fetch(self, address):
        calls.append(address)
        found = pages.get(address.split('?')[0])
        if found is None: raise address_fetch.FetchRefused('address-private')
        return found
    monkeypatch.setattr(address_fetch.Fetches, 'fetch', fetch)
    return pages, calls


def test_an_address_is_added_without_sending_a_file_byte_and_its_query_is_in_no_report(keyed, fetched, tmp_path):
    web = keyed
    pages, calls = fetched
    log = requests(web)
    report = keyed_client(web).upload(ADDRESS, **SETTINGS)
    assert [r['result'] for r in report.rows()] == ['Added'] and report.ok
    assert (report.view['folder_name'], report.items[0]['path']) == ('files.example.org', 'TUM-02.las')
    assert calls == [ADDRESS, ADDRESS]  # read, then added; the query travels to the gateway
    assert [op for op, _, _ in log if op in ('check', 'start', 'file')] == ['check', 'start', 'file']
    assert [n for op, _, n in log if op in ('check', 'file')] == [0, 0]  # no file byte leaves the SDK
    assert all(h['address'] == ADDRESS for op, h, _ in log if op in ('check', 'file'))
    report.save(tmp_path / 'r.csv'); report.save(tmp_path / 'r.json')
    assert SECRET not in (tmp_path / 'r.csv').read_text() + (tmp_path / 'r.json').read_text() + report.text()


def test_an_address_the_gateway_refuses_adds_nothing_and_says_why_without_the_query(keyed, fetched, tmp_path, monkeypatch):
    web = keyed
    with pytest.raises(OphioliteError) as error: keyed_client(web).upload('https://intranet.example.org/a.las?token=' + SECRET, **SETTINGS)
    assert 'This address is not on the public internet' in str(error.value) and SECRET not in str(error.value)
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', create(web, 'write')['key'])
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c))
    base = ['--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'), '--attribution', 'Synthetic test', '--rights-confirmed']
    assert cli.entrypoint(['upload', ADDRESS, *base, '--report', str(tmp_path / 'a.csv')]) is None
    assert SECRET not in (tmp_path / 'a.csv').read_text()
    with pytest.raises(SystemExit) as exit_: cli.entrypoint(['upload', 'https://intranet.example.org/a.las', *base])
    assert exit_.value.code == 1
