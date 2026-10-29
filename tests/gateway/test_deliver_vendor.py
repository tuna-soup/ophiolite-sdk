"""E109 S3.2, gateway lane (C5 grid and vendor shapes, D10 b and c; R5-4 to R5-6): `ophiolite deliver` of the two folder
send procedures against the real catalogue, exact-read, activity and story routes of an in-process gateway, signed in
with access keys.

alice uploads the registered 11-ro crop twice: once declared as E119a declares it (elevation, up, NAP), once with the same
bytes declared as depth, down, MSL; and the three HON-GT-01 tops. tina registers `grid-to-surfer-folder` and
`results-to-vendor-files`, and alice enables them. bob delivers each into a folder on his computer. The files written are
the ones whose digests the independent readers' record carries (tests/fixtures/e109/vendor/readers.json, R5-5), so what
GDAL, surfio and petrelpy read is what this delivery wrote. Each declaration file forwards its version's declarations:
the second case changes the declaration file and not one byte of a grid (R5-6). The project records each delivery.
A name already in the folder is refused and nothing is replaced. E108's `vendor-files` source procedure reads the
delivered folder back through `ophiolite source run` (row 6-15, a second check, not the proof)."""
import hashlib
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from test_deliver_journey import kit_examples, sdk, share

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = kit_examples()  # adhoc-e121-examples: the client kit's examples-procedures.zip, unpacked
VENDOR = ROOT / 'tests/fixtures/e109/vendor'
CROP = ROOT / 'conformance/fixtures/grids_gis/crops/11-ro-crop.asc'
DESTINATION = 'Team export folder'
NAP = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'}  # E119a D10
MSL = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'MSL'}  # R5-6
SURFER = ['surface.declaration.json', 'surface.grd']
RESULTS = ['results-tops.txt', 'results.declaration.json', 'results.irap', 'results.zmap']


def record():
    return json.loads((VENDOR / 'readers.json').read_text(encoding='utf-8'))


def digests(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).iterdir())}


@pytest.fixture
def journey(world, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.chdir(tmp_path)
    people = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    alice = people['alice']
    crop = CROP.read_bytes()
    nap = alice.upload_data(crop, profile='esri-ascii-grid/1', name='11-ro surface', attribution='NLOG.NL', audience=['bob'], rights_confirmed=True,
                            declared=NAP, filename='11-ro.asc', command_id='e109-grid-nap')
    msl = alice.upload_data(crop, profile='esri-ascii-grid/1', name='11-ro depth', attribution='NLOG.NL', audience=['bob'], rights_confirmed=True,
                            declared=MSL, filename='11-ro-depth.asc', command_id='e109-grid-msl')
    tops = alice.upload_data((VENDOR / 'hon-gt-01-tops.csv').read_bytes(), profile='well-tops-csv/1', name='HON-GT-01 tops', attribution='NLOG.NL',
                             audience=['bob'], rights_confirmed=True, declared={'depth_unit': 'm'}, filename='tops.csv', command_id='e109-vendor-tops')
    for upload in (nap, msl, tops): share(world, upload.asset_id, ['bob'], 1)
    for name in ('grid-to-surfer-folder', 'results-to-vendor-files'):
        alice.procedure_enable(people['tina'].procedure_register(EXAMPLES / name)['digest'])
    folders = {}
    for case in ('nap', 'msl', 'again'):
        folder = tmp_path / ('export-' + case)
        folder.mkdir()
        config = tmp_path / ('export-%s.json' % case)
        config.write_text(json.dumps({'folder': str(folder)}))
        folders[case] = (folder, config)
    yield {**people, 'world': world, 'tmp': tmp_path, 'folders': folders, 'nap': nap, 'msl': msl, 'tops': tops, 'work': tmp_path / '.ophiolite-held'}


def to_surfer(j, case, grid='11-ro surface'):
    return j['bob'].deliver('grid-to-surfer-folder', systems={'folder': str(j['folders'][case][1])}, items=['grid=%s@1' % grid],
                            settings=['name=surface'], work=j['work'], wait=0, yes=True)


def to_vendor(j, case, grid='11-ro surface'):
    return j['bob'].deliver('results-to-vendor-files', systems={'folder': str(j['folders'][case][1])},
                            items=['tops=HON-GT-01 tops@1', 'surface=%s@1' % grid], settings=['well=HON-GT-01', 'name=results'],
                            work=j['work'], wait=0, yes=True)


def test_anna_delivers_the_surface_as_a_surfer_grid_the_readers_read(journey):
    j = journey
    answer = to_surfer(j, 'nap')
    assert answer['sentence'] == 'Sent to %s by Grid to Surfer folder on this computer: 2 items. Recorded in the project.' % DESTINATION
    assert (answer['state'], answer['items'], answer['reported'], answer['destination']) == ('confirmed', 2, True, DESTINATION)
    made = digests(j['folders']['nap'][0])
    assert sorted(made) == SURFER  # no temporary file is left
    assert made == {k: record()['outputs']['nap'][k] for k in SURFER}  # R5-5: the bytes GDAL GSAG read
    told = json.loads((j['folders']['nap'][0] / 'surface.declaration.json').read_text())
    assert told == {'files': ['surface.grd'], **NAP}
    head = (j['folders']['nap'][0] / 'surface.grd').read_text().split('\n')[:6]
    assert head == ['DSAA', '30 40', '538750.0 546000.0', '6159500.0 6169250.0', '-4802.8569 -3916.9795', head[5]]
    assert head[5].split()[0] == '-4136.8589'  # the south row first, the value as stored (elevation above NAP)


def test_anna_delivers_tops_and_the_surface_as_vendor_shaped_files(journey):
    j = journey
    answer = to_vendor(j, 'nap')
    assert answer['sentence'] == 'Sent to %s by Results to vendor files on this computer: 4 items. Recorded in the project.' % DESTINATION
    made = digests(j['folders']['nap'][0])
    assert sorted(made) == RESULTS
    assert made == {k: record()['outputs']['nap'][k] for k in RESULTS}  # R5-5: the bytes GDAL ZMap, surfio and petrelpy read
    assert (j['folders']['nap'][0] / 'results-tops.txt').read_text().split('\n')[7:10] == [
        '"HON-GT-01" "NU" 0', '"HON-GT-01" "NM" 220', '"HON-GT-01" "NL" 240']
    attempt = json.loads((Path(answer['folder']) / 'attempt.json').read_text())
    assert attempt['refs'] == [{'project_id': 'p', 'asset_id': j['tops'].asset_id, 'revision': j['tops'].revision},
                               {'project_id': 'p', 'asset_id': j['nap'].asset_id, 'revision': j['nap'].revision}]
    assert str(j['folders']['nap'][0]) not in json.dumps(attempt)  # the folder stays in its configuration file


def test_a_depth_declaration_is_forwarded_and_the_numbers_do_not_change(journey):
    """R5-6: the same bytes declared depth, down, MSL. The declaration files say so; the grids and the tops file are byte
    for byte those of the elevation case."""
    j = journey
    assert to_surfer(j, 'msl', grid='11-ro depth')['state'] == 'confirmed'
    assert to_vendor(j, 'msl', grid='11-ro depth')['state'] == 'confirmed'
    made = digests(j['folders']['msl'][0])
    assert made == record()['outputs']['msl']
    assert json.loads((j['folders']['msl'][0] / 'results.declaration.json').read_text()) == {'files': ['results.zmap', 'results.irap'], **MSL}
    assert json.loads((j['folders']['msl'][0] / 'surface.declaration.json').read_text()) == {'files': ['surface.grd'], **MSL}
    for name in ('surface.grd', 'results.zmap', 'results.irap', 'results-tops.txt'):
        assert made[name] == record()['outputs']['nap'][name], name


def test_activity_and_the_story_say_sent_to_the_team_export_folder(journey):
    j = journey
    answer = to_surfer(j, 'nap')
    [row] = j['alice']._post('activity', 'deliveries', {})['deliveries']
    assert {k: row[k] for k in ('delivery_id', 'state', 'items', 'destination', 'reporter')} == {
        'delivery_id': answer['delivery_id'], 'state': 'confirmed', 'items': 2, 'destination': DESTINATION, 'reporter': 'bob'}
    assert row['procedure']['label'] == 'Grid to Surfer folder'
    told = j['alice'].story(j['nap'].asset_id, j['nap'].revision)
    [entry] = next(n for n in told['nodes'] if (n['asset_id'], n['revision']) == (j['nap'].asset_id, j['nap'].revision))['deliveries']
    assert (entry['state'], entry['destination'], entry['procedure']) == ('confirmed', DESTINATION, 'Grid to Surfer folder')
    assert str(j['folders']['nap'][0]) not in json.dumps(row) + json.dumps(told)  # D9: no configuration


def test_a_name_already_in_the_folder_is_refused_and_nothing_is_replaced(journey):
    j = journey
    to_surfer(j, 'again')
    before = digests(j['folders']['again'][0])
    again = to_surfer(j, 'again')
    assert (again['state'], again['sentence']) == ('not-sent', 'Not sent to %s by Grid to Surfer folder on this computer. Recorded in the project.' % DESTINATION)
    reason = 'The export folder already has a file named surface.grd; nothing was written. Choose another name.'
    assert reason in (Path(again['folder']) / 'log.txt').read_text()  # the reason stays on this computer
    assert reason not in json.dumps(j['alice']._post('activity', 'deliveries', {}))
    assert digests(j['folders']['again'][0]) == before


def test_the_vendor_files_source_procedure_reads_the_delivered_folder_back(journey):
    """Row 6-15, E108's second check: `ophiolite source run` of `vendor-files` on the delivered folder adds the three tops
    of the chosen well and the two grids, which equal the registered crop node for node."""
    j = journey
    to_vendor(j, 'nap')
    j['alice'].procedure_enable(j['tina'].procedure_register(EXAMPLES / 'vendor-files')['digest'])
    settings = ['well=HON-GT-01', 'tops_file=results-tops.txt', 'zmap_file=results.zmap', 'irap_file=results.irap'] + ['%s=%s' % kv for kv in NAP.items()]
    result = j['bob'].source_run('vendor-files', {'folder': str(j['folders']['nap'][1])}, settings=settings, yes=True, attribution='NLOG.NL',
                                 audience='me', folder=j['tmp'] / 'read-back')
    report = result['report']
    assert report.ok and [i['state'] for i in report.items] == ['added'] * 3, report.text()
    made = j['tmp'] / 'read-back'
    outputs = json.loads(next(made.rglob('run.json')).read_text())['outputs']
    files = {role: next(made.rglob(o['file'])).read_bytes() for role, o in outputs.items()}
    assert files['tops'].decode() == 'name,md\nNU,0\nNM,220\nNL,240\n'  # the three picks of the chosen well, read back
    def nodes(text): return [[float(t) for t in line.split()] for line in text.splitlines()[6:]]
    for role in ('surface_zmap', 'surface_irap'):
        assert [l.split() for l in files[role].decode().splitlines()[:6]] == [l.split() for l in CROP.read_text().splitlines()[:6]], role
        assert nodes(files[role].decode()) == nodes(CROP.read_text()), role  # node for node, nulls included
