"""E109 S1.2, gateway lane (C3 first journey with C5 tops): `ophiolite deliver` against the real catalogue, exact-read,
activity and story routes of an in-process gateway, signed in with access keys, writing into a throwaway PostgreSQL
cluster (tests/fixtures/e109/pg.py; it fails, never skips, without initdb, 6-18).

alice keeps two versions of the HON-GT-01 tops and lets bob read them; tina registers the tops-to-team-db example and
alice enables it; bob delivers version 1, not the head. The three tops land in `team.tops`, the command says so, and the
project records it: the deliveries page and the story of version 1 name the delivery (the Workspace renders them as
"Sent to Team tops database by Tops to team DB on Bob's computer (reported)", S1.3); version 2 has none. Record side of
C3 test 15: two deliveries of the same version are two records; a reporter whose access is revoked after the
destination's commit is refused by the project and the confirmed outcome stays on this computer."""
import atexit
import functools
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, procedures
from test_deliver_tops import THREE, pg

ROOT = Path(__file__).resolve().parents[3]


@functools.cache
def kit_examples():
    """adhoc-e121-examples (E121 O7, O10): examples/procedures as the client kit carries them, unpacked once from the
    examples-procedures.zip tools/package/examples_kit.py builds, so a delivery here registers what a person gets."""
    sys.path.insert(0, str(ROOT / 'tools/package')); import examples_kit
    unpacked = Path(tempfile.mkdtemp(prefix='kit-examples-')); atexit.register(shutil.rmtree, unpacked, True)
    examples_kit.into(unpacked)
    with zipfile.ZipFile(unpacked / examples_kit.NAME) as z: z.extractall(unpacked)
    return unpacked / 'examples/procedures'


EXAMPLE = kit_examples() / 'tops-to-team-db'
DESTINATION = 'Team tops database'
ONE = ('name,md\n' + ''.join('%s,%s\n' % (surface, md) for _, surface, md in THREE)).encode()  # the three workbook tops
TWO = b'name,md\nNU,0\nNM,221.5\nNL,241\nNS,300\n'  # synthetic: a later reading of the same well
DECLARED = {'depth_unit': 'm', 'depth_basis': 'same-as-log'}
NAME = 'HON-GT-01 tops'


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def share(world, asset, audience, generation):
    """alice sets who reads her upload, in her browser session (an access key does not share), at the generation she saw."""
    r = world.call('alice', 'las-uploads', 'share', {'asset_id': asset, 'audience': audience, 'reuse_audience': [], 'expected_generation': generation})
    assert r.status_code == 200, r.text


@pytest.fixture
def journey(world, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.chdir(tmp_path)
    people = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    alice = people['alice']
    first = alice.upload_data(ONE, profile='well-tops-csv/1', name=NAME, attribution='NLOG.NL', audience=['bob'], rights_confirmed=True,
                              declared=DECLARED, filename='tops.csv', command_id='e109-tops-1')
    second = alice.upload_data(TWO, profile='well-tops-csv/1', name=NAME, attribution='Synthetic', audience=['bob'], rights_confirmed=True,
                               declared=DECLARED, filename='tops.csv', command_id='e109-tops-2', append_to=first.asset_id, expected_parent=first.revision)
    assert second.asset_id == first.asset_id and second.revision != first.revision
    share(world, first.asset_id, ['bob'], 1)
    digest = people['tina'].procedure_register(EXAMPLE)['digest']
    alice.procedure_enable(digest)
    with pg.team_db(tmp_path) as db:  # fails, never skips, without initdb
        config = tmp_path / 'team-db.json'
        config.write_text(json.dumps({k: str(v) for k, v in db.config.items()}))  # a configuration file holds text
        yield {**people, 'world': world, 'db': db, 'config': config, 'v1': first.revision, 'v2': second.revision, 'asset': first.asset_id,
               'work': tmp_path / '.ophiolite-held'}


def deliver(j):
    return j['bob'].deliver('tops-to-team-db', systems={'db': str(j['config'])}, items=['tops=%s@1' % NAME], settings=['well=HON-GT-01'],
                            work=j['work'], wait=0, yes=True)


def deliveries(client):
    return client._post('activity', 'deliveries', {})['deliveries']


def story_deliveries(client, asset, revision):
    told = client.story(asset, revision)
    return next(n for n in told['nodes'] if (n['asset_id'], n['revision']) == (asset, revision)).get('deliveries')


def test_anna_delivers_version_one_not_the_head_to_the_team_schema(journey):
    j = journey
    answer = deliver(j)
    assert answer['sentence'] == 'Sent to %s by Tops to team DB on this computer: 3 items. Recorded in the project.' % DESTINATION
    assert (answer['state'], answer['items'], answer['reported'], answer['destination']) == ('confirmed', 3, True, DESTINATION)
    assert j['db'].rows('SELECT well, surface, md FROM team.tops ORDER BY md') == THREE  # version 1's tops, not version 2's four
    assert j['db'].rows('SELECT delivery_id, state FROM team.deliveries') == [(answer['delivery_id'], 'delivered')]
    attempt = json.loads((Path(answer['folder']) / 'attempt.json').read_text())
    assert attempt['refs'] == [{'project_id': 'p', 'asset_id': j['asset'], 'revision': j['v1']}] and attempt['finished'] is True
    raw = (Path(answer['folder']) / 'attempt.json').read_text()
    assert pg.WRITER not in raw and 'team_tops' not in raw  # the configuration stays in its file (fingerprint only)
    assert not (j['work'] / 'held.json').exists()  # an exact read holds nothing (M3)


def test_activity_and_the_story_say_sent_to_the_team_database(journey):
    j = journey
    answer = deliver(j)
    for who in ('alice', 'bob'):  # the reporter, and a person who can read the delivered version
        [row] = deliveries(j[who])
        assert {k: row[k] for k in ('delivery_id', 'state', 'items', 'destination', 'reporter')} == {
            'delivery_id': answer['delivery_id'], 'state': 'confirmed', 'items': 3, 'destination': DESTINATION, 'reporter': 'bob'}
        assert row['procedure']['label'] == 'Tops to team DB' and row['refs'] == [{'project_id': 'p', 'asset_id': j['asset'], 'revision': j['v1']}]
    [entry] = story_deliveries(j['alice'], j['asset'], j['v1'])
    assert {k: entry[k] for k in ('state', 'destination', 'procedure', 'person')} == {
        'state': 'confirmed', 'destination': DESTINATION, 'procedure': 'Tops to team DB', 'person': 'bob'}
    assert not story_deliveries(j['alice'], j['asset'], j['v2'])  # the head was not delivered
    listed = j['world'].call('alice', 'activity', 'list', {})  # the Activity page, as alice's browser reads it
    assert listed.status_code == 200, listed.text
    events = listed.json()['events']
    assert [(e['kind'], e['coverage_profile']) for e in events if e['kind'] == 'delivery.reported'] == [('delivery.reported', 'procedure-delivery/1')]
    assert pg.WRITER not in json.dumps(events) and 'team_tops' not in json.dumps(events)  # D9: no configuration (user, database)


def test_two_deliveries_of_one_version_are_two_records(journey):
    j = journey
    one, two = deliver(j), deliver(j)
    assert one['delivery_id'] != two['delivery_id'] and one['state'] == two['state'] == 'confirmed'
    assert [r['delivery_id'] for r in deliveries(j['alice'])] == [one['delivery_id'], two['delivery_id']]
    assert len(story_deliveries(j['alice'], j['asset'], j['v1'])) == 2
    assert j['db'].rows('SELECT count(*) FROM team.tops') == [(6,)]


def test_access_revoked_after_the_destination_commit_is_refused_by_the_project_and_the_outcome_stays_here(journey, monkeypatch):
    j = journey
    def revoke(process, folder):  # the writer commits; then alice takes bob's read away before the report
        process.wait()
        share(j['world'], j['asset'], [], 2)
    monkeypatch.setattr(procedures, '_launched', revoke)
    answer = deliver(j)
    assert j['db'].rows('SELECT count(*) FROM team.tops') == [(3,)]  # the team's database holds the tops
    assert (answer['state'], answer['reported']) == ('confirmed', False)
    assert answer['sentence'].startswith('Sent to %s by Tops to team DB on this computer: 3 items. Not recorded in the project yet: ' % DESTINATION)
    assert 'You can no longer read every version this delivery names' in answer['sentence']
    attempt = json.loads((Path(answer['folder']) / 'attempt.json').read_text())
    assert (attempt['result']['state'], attempt['reported'], attempt['finished']) == ('confirmed', False, False)
    assert deliveries(j['alice']) == []  # nothing recorded
