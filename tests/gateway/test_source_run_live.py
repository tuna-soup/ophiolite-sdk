"""E108 S1, gateway lane: `ophiolite source run` against the real catalogue and upload routes of an in-process gateway,
signed in with access keys. tina registers a source procedure that reads the Westland well headers from a team's REST
service (tests/fixtures/e108/headers_server.py, behind a bearer token kept in a local configuration file); alice enables
it; bob runs it on his computer and its three well locations land in one upload, each recording the version, the system
in words and its role. bob exports one, the bundle verifies offline, and alice imports it: her item keeps the source
procedure as bob's project recorded it (5R-8)."""
import base64
import hashlib
import importlib.util
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
from ophiolite import Client, Credential, bundle, cli

SERVER = Path(__file__).resolve().parents[3] / 'tests/fixtures/e108/headers_server.py'
TOKEN = 'planted-headers-token-91c2'
ROLES = {'hon_gt_01': 'HON-GT-01', 'hon_gt_01_s1': 'HON-GT-01-S1', 'hon_gt_02': 'HON-GT-02'}
SYSTEM = 'Team well headers service'
CODE = '''import json
import urllib.request
from ophiolite import procedure
from ophiolite.writers import write_location

WELLS = %r


@procedure
def fetch(inputs, settings):
    config = inputs['service'].config
    made = {}
    for role, code in WELLS.items():
        request = urllib.request.Request(config['url'] + '/wells/' + code, headers={'Authorization': 'Bearer ' + config['token']})
        with urllib.request.urlopen(request, timeout=10) as answer: row = json.loads(answer.read())
        # the header's reference level is the rotary table, which a well location does not name: unknown
        made[role] = write_location(row['x'], row['y'], crs='EPSG:28992', elevation_reference='unknown', filename=role + '.json')
    return made
'''


def headers():
    spec = importlib.util.spec_from_file_location('e108_headers_server', SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def procedure(tmp_path):
    folder = tmp_path / 'westland-headers'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps({
        'schema': 'ophiolite.procedure/1', 'name': 'westland/headers', 'label': 'Westland headers', 'version': 1, 'version_label': 'Release 1',
        'step': 'source', 'inputs': [{'slot': 'service', 'label': SYSTEM, 'class': 'system', 'config_keys': ['token', 'url']}],
        'outputs': [{'role': role, 'label': code + ' location', 'class': 'version', 'kind': 'well-location/1'} for role, code in ROLES.items()],
        'entry': 'procedure:fetch'}, indent=2))
    (folder / 'procedure.py').write_text(CODE % ROLES)
    return folder


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def sent(world):
    log = []
    def record(request):
        header = request.headers.get('x-ophiolite-upload')
        log.append(base64.b64decode(header) if header else (request.content or b''))
    world.c.event_hooks['request'].append(record)
    return log


def test_a_first_run_lands_three_locations_with_their_source_and_an_import_keeps_it_as_recorded(world, tmp_path):
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    digest = clients['tina'].procedure_register(procedure(tmp_path))['digest']
    clients['alice'].procedure_enable(digest)
    log = sent(world)
    with headers().served(TOKEN) as (url, asked):
        (tmp_path / 'service.json').write_text(json.dumps({'token': TOKEN, 'url': url}))
        result = clients['bob'].source_run('westland/headers', {'service': str(tmp_path / 'service.json')}, yes=True, cache=tmp_path / 'cache',
                                           attribution='NLOG.NL', audience=['alice'], folder=tmp_path / 'run')
    assert [(path, allowed) for path, allowed in asked] == [('/wells/' + code, True) for code in ROLES.values()]
    assert not any(TOKEN.encode() in raw or url.encode() in raw for raw in log)  # D9: the configuration never leaves this computer
    report = result['report']
    assert report.ok and [(i['path'], i['state']) for i in report.items] == [('%s/%s.json' % (SYSTEM, role), 'added') for role in ROLES], report.text()
    assert result['sentence'] == 'Ran Westland headers, version 1, on this computer, reading from %s.' % SYSTEM

    item = report.items[0]
    told = clients['bob'].story(item['asset_id'], item['revision'])['nodes'][0]['read']
    assert told['words'].startswith('Read from %s by Westland headers (version 1) on ' % SYSTEM) and told['words'].endswith(' (reported).')
    assert len({i['asset_id'] for i in report.items}) == 3  # the sidetrack's location equals its well's: its own item by role (B6)


TOPS = [{'name': 'Top North Sea Group', 'md': 0}, {'name': 'Top Chalk', 'md': 812.5}]  # synthetic
SHARE = '''from ophiolite import procedure
import json
from ophiolite.writers import write_tops


@procedure
def fetch(inputs, settings):
    with open(inputs['share'].config['folder'] + '/tops.json') as handle: rows = json.load(handle)
    with open(inputs['share'].config['folder'] + '/runs.txt', 'a') as counter: counter.write('ran\\n')
    return {'tops': write_tops(rows, depth_unit='m', depth_basis='same-as-log')}
'''


def share_procedure(tmp_path):
    folder = tmp_path / 'survey-share'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps({
        'schema': 'ophiolite.procedure/1', 'name': 'team/survey-share', 'label': 'Survey share', 'version': 2, 'version_label': 'Release 2',
        'step': 'source', 'inputs': [{'slot': 'share', 'label': 'Team survey share', 'class': 'system', 'config_keys': ['folder']}],
        'outputs': [{'role': 'tops', 'label': 'Well tops', 'class': 'version', 'kind': 'well-tops-csv/1'}], 'entry': 'procedure:fetch'}, indent=2))
    (folder / 'procedure.py').write_text(SHARE)
    return folder


def test_a_source_made_version_exported_verified_offline_and_imported_keeps_its_source_as_recorded(world, tmp_path):
    """5R-8: bob's source-made tops travel in a bundle; alice's import records bob's `sourced_by` in its origin, her story
    says "as recorded", and her re-export carries the same record (never a new one)."""
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    digest = clients['tina'].procedure_register(share_procedure(tmp_path))['digest']
    clients['alice'].procedure_enable(digest)
    (tmp_path / 'share').mkdir()
    (tmp_path / 'share/tops.json').write_text(json.dumps(TOPS))
    (tmp_path / 'share.json').write_text(json.dumps({'folder': str(tmp_path / 'share')}))
    result = clients['bob'].source_run('team/survey-share', {'share': str(tmp_path / 'share.json')}, yes=True, cache=tmp_path / 'cache',
                                       attribution='Synthetic test', audience=['alice'])
    [item] = result['report'].items
    assert item['state'] == 'added', result['report'].text()
    first = clients['bob'].export([(item['asset_id'], item['revision'], None)], tmp_path / 'first', groups=False, entities=False)
    opened = bundle.open_bundle(tmp_path / 'first')  # offline
    recorded = bundle.recorded_source(opened.assets[0].data._wire_descriptor)
    assert recorded == {'digest': digest, 'label': 'Survey share', 'version_label': 'Release 2', 'version': 2, 'rules_version': '1.3.0',  # E120 s3: rules 1.3.0
                        'runner': 'bob', 'system': 'Team survey share', 'role': 'tops'}
    assert first.manifest['bundle_version'] == opened.manifest['bundle_version'] and 'read_by' not in opened.manifest['assets'][0]
    [step] = clients['alice'].import_bundle(opened, audience=[], attribution='Synthetic test', rights_confirmed=True)
    assert step['state'] == 'imported', step
    mine = step['destination']
    words = clients['alice'].story(mine['asset_id'], mine['revision'])['nodes'][0]['read']['words']
    assert words == 'Read from Team survey share by Survey share (version 2), as recorded in the exporting project.'
    again = clients['alice'].export([(mine['asset_id'], mine['revision'], None)], tmp_path / 'again', groups=False, entities=False)
    assert bundle.recorded_source(again.assets[0].data._wire_descriptor) == recorded


SHARED = ('Someone in this project already added the same file from this system and shared it with you. Use that file; adding '
          'your own copy from this procedure is not available on this deployment yet.')


def test_case_6_refuses_keeps_the_outputs_and_the_printed_fallback_adds_them_once_bob_stops_sharing(world, tmp_path, capsys, monkeypatch):
    """B6 rev 5 (R2-4, R2-7, R3-1), the real command against the real routes: bob's run of the source is shared with
    alice; alice's `ophiolite source run` of the same source exits 4 with the case-6 sentence and prints where the
    outputs are kept (only the outputs: no log.txt, no run.json). Once bob stops sharing, the printed fallback,
    `ophiolite upload <kept>`, adds them as alice's own file; the procedure ran once for alice. Mutation: the outputs
    are not kept on refusal (red)."""
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    digest = clients['tina'].procedure_register(share_procedure(tmp_path))['digest']
    clients['alice'].procedure_enable(digest)
    (tmp_path / 'share').mkdir()
    (tmp_path / 'share/tops.json').write_text(json.dumps(TOPS))
    (tmp_path / 'share.json').write_text(json.dumps({'folder': str(tmp_path / 'share')}))
    bobs = clients['bob'].source_run('team/survey-share', {'share': str(tmp_path / 'share.json')}, yes=True, cache=tmp_path / 'bob-cache',
                                     attribution='Synthetic test', audience=['alice'])
    [item] = bobs['report'].items
    assert item['state'] == 'added', bobs['report'].text()
    target = {'asset_id': item['asset_id'], 'revision': item['revision'], 'authority': 'ophiolite:uploaded'}
    clients['bob'].share(target, read=['alice'], expected_generation=clients['bob'].grants(target).generation)
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'alice-cache'))
    monkeypatch.chdir(tmp_path)  # the held run's folder lands in the cwd, never in the source tree
    capsys.readouterr()
    args = cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + str(tmp_path / 'share.json'), '--yes',
                                    '--attribution', 'Synthetic test', '--audience', 'me'])
    with pytest.raises(SystemExit) as stopped: cli._source(args, clients['alice'])
    printed = capsys.readouterr().out
    assert stopped.value.code == cli.EXIT['conflict'] and '  Well tops: Not supported - ' + SHARED in printed, printed
    [line] = [l for l in printed.splitlines() if l.startswith('The files the procedure made are kept in ')]
    kept = Path(line.split(' To add them by hand: ophiolite upload ')[1])
    assert sorted(p.name for p in kept.iterdir()) == ['tops.csv'] and (tmp_path / 'share/runs.txt').read_text() == 'ran\n' * 2  # bob's run, alice's
    clients['bob'].share(target, read=[], expected_generation=clients['bob'].grants(target).generation)  # bob stops sharing
    upload = cli.parser().parse_args(['upload', str(kept), '--attribution', 'Synthetic test', '--audience', 'me', '--rights-confirmed',
                                      '--declare', 'well-tops-csv/1:depth_unit=m', '--declare', 'well-tops-csv/1:depth_basis=same-as-log'])
    report = cli._upload(upload, clients['alice'])
    [mine] = report.items
    assert report.ok and mine['state'] == 'added' and mine['asset_id'] != item['asset_id'], report.text()
    assert (tmp_path / 'share/runs.txt').read_text() == 'ran\n' * 2  # the procedure did not run again


SURVEY = '''import json
from ophiolite import procedure
from ophiolite.writers import write_survey


@procedure
def fetch(inputs, settings):
    with open(inputs['share'].config['data']) as given: data = json.load(given)
    return {'survey': write_survey(data['stations'], depth_unit='m', azimuth_reference=data['azimuth_reference'], depth_datum='KB')}
'''
STATIONS = [{'md': 100, 'inclination': 0, 'azimuth': 0}, {'md': 200, 'inclination': 10, 'azimuth': 45}]  # synthetic


def survey_procedure(tmp_path):
    folder = tmp_path / 'survey-source'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps({
        'schema': 'ophiolite.procedure/1', 'name': 'team/survey-share', 'label': 'Survey share', 'version': 1, 'version_label': 'Release 1',
        'step': 'source', 'inputs': [{'slot': 'share', 'label': 'Team survey share', 'class': 'system', 'config_keys': ['data']}],
        'outputs': [{'role': 'survey', 'label': 'Survey', 'class': 'version', 'kind': 'deviation-csv/1'}], 'entry': 'procedure:fetch'}, indent=2))
    (folder / 'procedure.py').write_text(SURVEY)
    return folder


def test_colleague_receives_declaration_only_version_two(world, tmp_path):
    """E108 C4 test 6 (B3, D8', 8-5): bob's team system keeps one survey item; alice's folder holds version 1. bob's next run
    changes only the azimuth reference, so version 2 has version 1's bytes and its own revision (S2's declared-version/1).
    alice's check names version 2 and her get receives it; the transport itself numbers it 2 (S3R-4). Mutations: the
    successor refusal restored (red); `_number` ignoring `history` (the transport assertion, red)."""
    from ophiolite.exchange import ClientTransport
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    digest = clients['tina'].procedure_register(survey_procedure(tmp_path))['digest']
    clients['alice'].procedure_enable(digest)
    data, config = tmp_path / 'survey.json', tmp_path / 'share.json'
    config.write_text(json.dumps({'data': str(data)}))
    def run(reference):
        data.write_text(json.dumps({'stations': STATIONS, 'azimuth_reference': reference}))
        result = clients['bob'].source_run('team/survey-share', {'share': str(config)}, yes=True, cache=tmp_path / 'cache', attribution='Synthetic test',
                                           audience=['alice'], work=tmp_path / 'bob-held')
        [item] = result['report'].items
        assert item['state'] == 'added', result['report'].text()
        return item
    one = run('true-north')
    target = {'asset_id': one['asset_id'], 'revision': one['revision'], 'authority': 'ophiolite:uploaded'}
    clients['bob'].share(target, read=['alice'], expected_generation=clients['bob'].grants(target).generation)
    alice = clients['alice'].exchange(tmp_path / 'alice')
    alice.check()
    got = alice.get(one['asset_id'], output=tmp_path / 'survey')
    assert got.outcome == 'got' and got.sentence.startswith('Got Team survey share/survey.csv, version 1 by ')
    first_original = (tmp_path / 'survey/original').read_bytes()
    two = run('grid-north')
    assert two['asset_id'] == one['asset_id'] and two['revision'] != one['revision']
    assert two['revision'] != hashlib.sha256(first_original).hexdigest()  # declared-version/1: the same bytes, a revision of its own
    newer = alice.check()
    assert newer.outcome == 'updates' and newer.sentence.startswith('1 newer: Team survey share/survey.csv, version 2 by '), newer.sentence
    got = alice.get(one['asset_id'], output=tmp_path / 'survey')
    assert got.outcome == 'got' and got.sentence.startswith('Got Team survey share/survey.csv, version 2 by ') and got.sentence.endswith('saved in %s.' % (tmp_path / 'survey'))
    assert (tmp_path / 'survey/original').read_bytes() == first_original  # the same file
    described = json.loads((tmp_path / 'survey/descriptor.json').read_text())
    assert described['revision'] == two['revision'] and 'grid-north' in json.dumps(described) and 'true-north' not in json.dumps(described)
    assert alice.held()[one['asset_id']]['revision'] == two['revision']
    assert alice.get(one['asset_id'], output=tmp_path / 'survey').outcome == 'already-latest'
    item = {'asset_id': one['asset_id'], 'kind': 'uploaded', 'revision': two['revision']}
    assert ClientTransport(clients['alice']).fetch(item, two['revision'], None)['number'] == 2  # from the descriptor, not history (S3R-4)
