"""E108 S4, gateway lane: the vendor-files example as a person runs it. tina registers `examples/procedures/vendor-files`;
alice enables it; bob points `ophiolite source run` at a folder holding a Petrel-shaped tops file, the 11-ro crop as
ZMAP+ and its IRAP classic twin. The first run lands one tops item and two grids with the declarations bob gave (E119a
D10: elevation, up, NAP; nodes as cell centres); a rerun says nothing changed; an edited pick or an edited ZMAP+ node
makes version 2 of that item only. A rotated grid stops the run before anything is sent. The folder's path, with a
planted marker in it, reaches no request, report, story or run record (commit 5 test 2, S4R2-3); the default text names
no role key, profile, digest or outcome code (commit 5 test 3, S4R2-7 a)."""
import base64
import json
import os
import re
import shutil
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential
from ophiolite.procedures import NotRun

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/procedures/vendor-files'
SHAPES = ROOT / 'tests/fixtures/vendor-shapes'
CROPS = ROOT / 'conformance/fixtures/grids_gis/crops'
MARKER = 'e108-planted-folder-7f3a'
SYSTEM = 'Team export folder'
SETTINGS = {'well': 'HON-GT-01', 'tops_file': 'tops.txt', 'zmap_file': 'surface.zmap', 'irap_file': 'surface.irap', 'crs': 'EPSG:23031',
            'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'}
DECLARED = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'}
REFUSED = 'This grid is rotated or unevenly spaced; this procedure does not read it.'
NAMES = {role: '%s/%s.%s' % (SYSTEM, role, ext) for role, ext in (('tops', 'csv'), ('surface_zmap', 'asc'), ('surface_irap', 'asc'))}  # the runner names a file by its role
SENTINELS = ('surface_zmap', 'surface_irap', 'well-tops-csv/1', 'esri-ascii-grid/1', 'vendor_files', 'raised', 'earlier-version', 'not-supported')


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def sent(world):
    log = []
    def record(request):
        header = request.headers.get('x-ophiolite-upload')
        log.append(str(request.url).encode() + b'\n' + (base64.b64decode(header) if header else b'') + (request.content or b''))
    world.c.event_hooks['request'].append(record)
    return log


@pytest.fixture
def journey(world, tmp_path):
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    digest = clients['tina'].procedure_register(EXAMPLE)['digest']
    clients['alice'].procedure_enable(digest)
    folder = tmp_path / MARKER / 'export'
    folder.mkdir(parents=True)
    shutil.copyfile(SHAPES / 'nlog-tops-petrel.txt', folder / 'tops.txt')
    shutil.copyfile(CROPS / '11-ro-crop.zmap', folder / 'surface.zmap')
    shutil.copyfile(CROPS / '11-ro-crop-synthetic.irap', folder / 'surface.irap')
    config = tmp_path / 'export.json'
    config.write_text(json.dumps({'folder': str(folder)}))
    runs = iter(range(1, 100))
    def run(work=True, **changed):
        settings = ['%s=%s' % kv for kv in {**SETTINGS, **changed}.items()]
        return clients['bob'].source_run('vendor-files', {'folder': str(config)}, settings=settings, yes=True, cache=tmp_path / 'cache',
                                         attribution='NLOG.NL', audience=['alice'], folder=tmp_path / ('run-%d' % next(runs)),
                                         work=tmp_path / 'held' if work else None)
    return clients, digest, folder, run


def served(client, item, tmp_path, name):
    got = client.exchange(tmp_path / ('ex-' + name)).get(item['asset_id'], output=tmp_path / name)
    assert got.outcome == 'got', got.sentence
    return json.loads((tmp_path / name / 'descriptor.json').read_text()), (tmp_path / name / 'original').read_bytes()


def number(client, item):
    """The version number the served descriptor gives the item's revision (as E108 S3's survey test reads it)."""
    from ophiolite.exchange import ClientTransport
    return ClientTransport(client).fetch({'asset_id': item['asset_id'], 'kind': 'uploaded', 'revision': item['revision']}, item['revision'], None)['number']


def words(value):
    """The default-layer text of a served story: every `words`, `sentence` and `title`, outside technical details."""
    if isinstance(value, dict):
        return [t for k, v in value.items() if k not in ('technical', 'details') for t in ([v] if k in ('words', 'sentence', 'title') and isinstance(v, str) else words(v))]
    if isinstance(value, list): return [t for v in value for t in words(v)]
    return []


def test_first_run_lands_tops_and_two_node_registered_grids_with_the_declared_meaning(world, journey, tmp_path):
    clients, digest, folder, run = journey
    log = sent(world)
    result = run()
    report = result['report']

    # privacy (commit 5 test 2, S4R2-3), before anything else is asserted: the artefacts exist, and none holds the
    # folder's path or its planted marker
    kept = tmp_path / 'run-1'
    assert (kept / 'run.json').exists() and log and report.text()
    for text in [raw.decode('utf-8', 'replace') for raw in log] + [(kept / 'run.json').read_text(), json.dumps(result['run']), report.text(),
                                                                    json.dumps(report.view, default=str)]:
        assert MARKER not in text and str(folder) not in text
    assert report.ok and sorted((i['path'], i['state']) for i in report.items) == sorted((p, 'added') for p in NAMES.values()), report.text()
    by = {next(r for r, p in NAMES.items() if p == i['path']): i for i in report.items}
    story = clients['bob'].story(by['tops']['asset_id'], by['tops']['revision'])
    activity = world.ok('bob', 'activity', 'list', {})['events']
    assert activity and any(e['kind'] == 'action' for e in activity)
    for text in (json.dumps(story), json.dumps(activity, default=str)):
        assert MARKER not in text and str(folder) not in text
    # the default text (commit 5 test 3, S4R2-7 a): no role key, profile, digest or outcome code
    shown = '\n'.join([report.text(), result['sentence']] + words(story))
    for sentinel in SENTINELS + (digest,):
        assert not re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(sentinel), shown), (sentinel, shown)

    # what was served: the tops' rows, each grid's node-registered header and the declarations bob gave
    descriptor, tops = served(clients['bob'], by['tops'], tmp_path, 'tops')
    assert tops.decode().splitlines()[:3] == ['name,md', 'NU,0', 'NM,220'] and len(tops.decode().splitlines()) == 1 + 24
    for role in ('surface_zmap', 'surface_irap'):
        descriptor, grid = served(clients['bob'], by[role], tmp_path, role)
        assert grid.decode().splitlines()[:6] == ['ncols 30', 'nrows 40', 'xllcenter 538750', 'yllcenter 6159500', 'cellsize 250', 'NODATA_value -99999']
        assert {k: descriptor['scientific'][k] for k in DECLARED} == DECLARED, descriptor['scientific']
        assert MARKER not in json.dumps(descriptor) and str(folder) not in json.dumps(descriptor)
    zmap_rows = served(clients['bob'], by['surface_zmap'], tmp_path, 'again')[1].decode().splitlines()[6:]
    crop = [[None if t == '-99999' else float(t) for t in r.split()] for r in (CROPS / '11-ro-crop.asc').read_text().splitlines()[6:]]
    assert [[None if t == '-99999' else float(t) for t in r.split()] for r in zmap_rows] == crop  # node for node, as numbers


def test_a_rerun_says_nothing_changed_and_an_edit_makes_version_two_of_that_item_only(world, journey, tmp_path):
    clients, digest, folder, run = journey
    first = run()
    ids = {i['path']: i['asset_id'] for i in first['report'].items}
    again = run()
    assert again['outcome'] == 'nothing-changed' and again['report'] is None, again
    tops = (folder / 'tops.txt').read_text()
    (folder / 'tops.txt').write_text(tops.replace('"HON-GT-01" "NM" 220\n', '"HON-GT-01" "NM" 221\n'))
    edited = run()
    changed = [(i['path'], i['state']) for i in edited['report'].items if i['state'] != 'already-here']
    assert changed == [(NAMES['tops'], 'added')], edited['report'].text()
    [item] = [i for i in edited['report'].items if i['path'] == NAMES['tops']]
    assert item['asset_id'] == ids[NAMES['tops']] and number(clients['bob'], item) == 2
    zmap = (folder / 'surface.zmap').read_text()
    assert zmap.count('     -3944.5833') == 1
    (folder / 'surface.zmap').write_text(zmap.replace('     -3944.5833', '     -3944.5000'))
    node = run()
    changed = [(i['path'], i['state']) for i in node['report'].items if i['state'] != 'already-here']
    assert changed == [(NAMES['surface_zmap'], 'added')], node['report'].text()
    [item] = [i for i in node['report'].items if i['path'] == NAMES['surface_zmap']]
    assert item['asset_id'] == ids[NAMES['surface_zmap']] and number(clients['bob'], item) == 2


def test_a_rotated_grid_stops_the_run_before_anything_is_sent(world, journey, tmp_path):
    clients, digest, folder, run = journey
    shutil.copyfile(SHAPES / 'refuse-rotated.irap', folder / 'rotated.irap')
    log = sent(world)
    with pytest.raises(NotRun) as stopped: run(irap_file='rotated.irap')
    assert stopped.value.code == 'raised' and stopped.value.details['message'] == REFUSED
    assert str(stopped.value) == 'Not run: the procedure stopped with an error. Its details are under --json.'
    assert MARKER not in str(stopped.value) and MARKER not in stopped.value.details['message']
    assert not [raw for raw in log if b'/upload' in raw.split(b'\n', 1)[0]]  # nothing was sent
    assert not (tmp_path / 'run-1').exists()


def test_a_second_upload_of_the_same_files_without_the_held_record_is_shown_without_identifiers(world, journey, tmp_path):
    """A report that is not all `added` (the same bytes sent again by hand, no held record): its default text names
    no role key, profile, digest or outcome code either (S4R2-7 a)."""
    clients, digest, folder, run = journey
    run()
    again = run(work=False)
    report = again['report']
    assert {i['state'] for i in report.items} != {'added'}, report.text()
    shown = report.text()
    for sentinel in SENTINELS + (digest,):
        assert not re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(sentinel), shown), (sentinel, shown)
