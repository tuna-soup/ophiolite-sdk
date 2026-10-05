"""E50c S1, in-process gateway lane: Wells.with_source against the real routes after a real E42a import. Each well is
joined to the kept row it was located from, under the kept copy's own permission check; no well is dropped or
repeated; the kept values outlive a change to the table; withdrawal, review and a narrowed audience are marked, never
dropped."""
import json
import sqlite3

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from ophiolite import Client, Credential
from ophiolite.well_sources import NO_ORIGIN_REASON

ORIGIN = 'https://workspace.example'
ROWS = [('W-1', 'North 1', 4.1, 52.1, 'Shell', '1971-03-02'), ('W-2', 'North 2', 4.2, 52.2, 'NAM', None),
        ('W-3', 'No x', None, 52.3, 'NAM', None)]


def client(web, persona):
    return Client(ORIGIN, 'p', Credential.bearer('oph_api_%s:read,write' % persona), web.c)


def run_import(web, alice, key, audience, command_id):
    found = web.a.sources.call('schema', {'project_id': 'p', 'connection_id': 'sql', 'key': key, 'profile': 'sql-wells/1'}, 'alice')
    mapping = {'entity': 'well', 'fields': {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y'}, 'crs': 'EPSG:4326', 'schema_digest': found['schema_digest']}
    imports = alice.well_imports()
    review = imports.preview('sql', key, mapping)
    return imports.run(imports.start('sql', key, mapping, preview_digest=review['preview_digest'], audience=audience, command_id=command_id)['id'])


@pytest.fixture
def imported(web, tmp_path):
    """alice imports a SQLite well table (two rows accepted, one skipped) with audience bob, and makes one unlocated well."""
    s = web.a.sources
    path = tmp_path / 'wells.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE wells(id TEXT, name TEXT, x REAL, y REAL, operator TEXT, spud_date TEXT)')
        db.executemany('INSERT INTO wells VALUES(?,?,?,?,?,?)', ROWS)
    s.registry.connections['sql'] = {'id': 'sql', 'type': 'sqlite', 'name': 'SQL', 'namespace': 'sql-e50c', 'path': str(path),
                                     'principals': {'alice': True}, 'tables': {'w': {'table': 'wells', 'name': 'Wells'}},
                                     'identifiers': {'authority': 'nlog'},
                                     'release_policy': {'retention_permitted': True, 'redistribution_permitted': True, 'audience': ['alice', 'bob']}}
    alice = client(web, 'alice')
    done = run_import(web, alice, 'w', ['bob'], 'e50c')
    assert (done['counts']['created'], done['counts']['skipped']) == (2, 1)
    alice.create_entity('well', 'Unlocated', provisional=True, audience=['bob'], command_id='e50c-unlocated')
    release = alice._post('releases', 'list', {})['items'][0]
    return type('Imported', (), {'web': web, 'path': path, 'alice': alice, 'bob': client(web, 'bob'), 'release': release})()


def decide(web, operation, body):
    """A package decision as alice over HTTP (the SDK reads packages; it does not decide them)."""
    answer = web.c.post('/api/v1/projects/p/releases/' + operation, json={'project_id': 'p', **body}, headers={'Authorization': 'Bearer oph_api_alice:read,write'})
    assert answer.status_code == 200, answer.text
    return answer.json()


def by_name(frame):
    return {r['name']: r for r in frame.to_dict('records')}


def test_every_well_is_joined_or_marked_and_none_is_dropped_or_repeated(imported):
    for person in (imported.alice, imported.bob):
        wells = person.wells()
        frame = wells.with_source(columns=['operator', 'spud_date'])
        assert list(frame['entity_id']) == [w.entity_id for w in wells] and frame['entity_id'].is_unique
        rows = by_name(frame)
        assert set(rows) == {'North 1', 'North 2', 'Unlocated'}
        assert (rows['North 1']['source_state'], rows['North 1']['source.operator'], rows['North 1']['source.spud_date']) == ('joined', 'Shell', '1971-03-02')
        assert (rows['North 2']['source_state'], rows['North 2']['source.operator'], rows['North 2']['source.spud_date']) == ('joined', 'NAM', None)
        assert rows['North 1']['source_row'] == 'W-1' and pd_na(rows['North 1']['source_reason'])
        assert (rows['Unlocated']['source_state'], rows['Unlocated']['source_reason']) == ('no origin', NO_ORIGIN_REASON)
    every = imported.alice.wells().with_source()
    assert [c for c in every.columns if c.startswith('source.')] == ['source.id', 'source.name', 'source.x', 'source.y', 'source.operator', 'source.spud_date']


def pd_na(value):
    import pandas as pd
    return pd.isna(value)


def test_the_kept_values_outlive_a_change_to_the_table(imported):
    with sqlite3.connect(imported.path) as db: db.execute("UPDATE wells SET operator='Changed', x=9.9 WHERE id='W-1'")
    rows = by_name(imported.bob.wells().with_source(columns=['operator', 'x']))
    assert (rows['North 1']['source.operator'], rows['North 1']['source.x']) == ('Shell', 4.1)


def test_a_narrowed_audience_lists_every_well_with_no_origin(imported):
    imported.web.a.sources.registry.connections['sql']['release_policy']['audience'] = ['alice']
    frame = imported.bob.wells().with_source(columns=['operator'])
    assert sorted(frame['name']) == ['North 1', 'North 2', 'Unlocated']
    assert set(frame['source_state']) == {'no origin'} and frame['source.operator'].isna().all()
    assert set(by_name(imported.alice.wells().with_source(columns=['operator']))['North 1'].items()) >= {('source_state', 'joined')}


def test_a_copy_withdrawn_after_the_listing_is_not_readable(imported):
    wells = imported.bob.wells()
    decide(imported.web, 'withdraw', {'id': imported.release['id'], 'manifest_digest': imported.release['manifest_digest'], 'reason': 'E50c test'})
    rows = by_name(wells.with_source(columns=['operator']))
    assert (rows['North 1']['source_state'], rows['North 1']['source_reason']) == ('not readable', 'The kept copy was withdrawn.')
    assert rows['Unlocated']['source_state'] == 'no origin'
    assert set(imported.bob.wells().with_source()['source_state']) == {'no origin'}  # listed again: the server no longer shows it


def test_a_copy_under_review_is_not_readable_and_an_approved_one_joins(imported):
    alice, release = imported.alice, imported.release
    wells = imported.bob.wells()
    decide(imported.web, 'request-review', {'id': release['id'], 'manifest_digest': release['manifest_digest']})
    assert set(imported.bob.wells().with_source()['source_state']) == {'no origin'}  # listed again: under review, the server withholds it
    rows = by_name(wells.with_source(columns=['operator']))
    assert (rows['North 1']['source_state'], rows['North 1']['source_reason']) == ('not readable', 'The kept copy is under review; read it again after it is approved.')
    manifest = alice._post('releases', 'get', {'id': release['id']})['manifest']
    decide(imported.web, 'approve', {'id': release['id'], 'manifest_digest': release['manifest_digest'], 'purpose': manifest['purpose'],
                                        'acknowledged_findings': [f['id'] for f in manifest['findings']]})
    rows = by_name(imported.bob.wells().with_source(columns=['operator']))
    assert (rows['North 1']['source_state'], rows['North 1']['source.operator']) == ('joined', 'Shell')


def test_the_sdk_names_the_kept_copy_as_the_server_does(imported):
    from project_gateway.retained_assets import capture_id as server
    from ophiolite.well_sources import capture_id
    location = next(w.location for w in imported.alice.wells() if w.location)
    assert capture_id(imported.release['id'], 0) == server(imported.release['id'], 0) == location['source']['asset_id']


def test_an_audience_narrowed_between_the_listing_and_the_read_is_not_readable(imported):
    wells = imported.bob.wells()
    imported.web.a.sources.registry.connections['sql']['release_policy']['audience'] = ['alice']
    rows = by_name(wells.with_source(columns=['operator']))
    assert [rows[n]['source_state'] for n in ('North 1', 'North 2', 'Unlocated')] == ['not readable', 'not readable', 'no origin']
    assert rows['North 1']['source_reason'] == 'The kept copy is not in a package you can open.' and pd_na(rows['North 1']['source.operator'])


def test_each_well_joins_the_copy_that_supplies_its_location(imported):
    """A second table with the same row ids and other values, imported for alice alone: alice's wells are now located by
    the newer copy and join its values; bob, outside its audience, still sees the first copy and joins those."""
    with sqlite3.connect(imported.path) as db:
        db.execute('CREATE TABLE wells2(id TEXT, name TEXT, x REAL, y REAL, operator TEXT, spud_date TEXT)')
        db.executemany('INSERT INTO wells2 VALUES(?,?,?,?,?,?)', [('W-2', 'North 2', 4.25, 52.25, 'Second W-2', None), ('W-1', 'North 1', 4.15, 52.15, 'Second W-1', None)])
    imported.web.a.sources.registry.connections['sql']['tables']['w2'] = {'table': 'wells2', 'name': 'Wells again'}
    done = run_import(imported.web, imported.alice, 'w2', [], 'e50c-second')
    assert done['counts']['already_here'] == 2
    mine, theirs = imported.alice.wells(), imported.bob.wells()
    assert {w.location['source']['asset_id'] for w in mine if w.location} != {w.location['source']['asset_id'] for w in theirs if w.location}
    for wells, expected in ((mine, {'North 1': 'Second W-1', 'North 2': 'Second W-2'}), (theirs, {'North 1': 'Shell', 'North 2': 'NAM'})):
        rows = by_name(wells.with_source(columns=['operator']))
        assert {n: rows[n]['source.operator'] for n in expected} == expected
        assert all(rows[n]['source_row'] == {'North 1': 'W-1', 'North 2': 'W-2'}[n] for n in expected)


@pytest.fixture
def run(imported, tmp_path, monkeypatch, capsys):
    """run(persona, *argv) -> (exit code, stdout) through cli.entrypoint in this process."""
    from ophiolite import cli
    cli._load()
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, imported.web.c))
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    def call(persona, *argv):
        monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_%s:read,write' % persona)
        capsys.readouterr()
        try: cli.entrypoint(['wells', 'list', *argv, '--configuration', str(tmp_path / 'configuration.json')])
        except SystemExit as stop: code = stop.code
        else: code = 0
        return code, capsys.readouterr().out.strip()
    return call


def test_the_command_line_lists_each_well_with_its_mark_and_row(run):
    code, out = run('bob', '--json')
    assert code == 0 and all('source' not in w for w in json.loads(out)['wells'])  # the shape without --with-source is unchanged
    code, out = run('bob', '--with-source', '--column', 'operator', '--column', 'spud_date', '--json')
    wells = {w['name']: w['source'] for w in json.loads(out)['wells']}
    assert code == 0 and wells == {'North 1': {'state': 'joined', 'reason': None, 'row': {'operator': 'Shell', 'spud_date': '1971-03-02'}},
                                   'North 2': {'state': 'joined', 'reason': None, 'row': {'operator': 'NAM', 'spud_date': None}},
                                   'Unlocated': {'state': 'no origin', 'reason': NO_ORIGIN_REASON, 'row': None}}
    code, out = run('bob', '--with-source')
    assert code == 0 and "Well('Unlocated', unlocated): no origin (%s)" % NO_ORIGIN_REASON in out and "North 1" in out
    code, _ = run('bob', '--column', 'operator')
    assert code != 0
