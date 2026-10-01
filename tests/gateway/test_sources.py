"""E50a S3, in-process gateway lane: a real access key (created through the session route, resolved to its owner the way
native authentication does) reads a SQL source selection with client.sources()/source(id).read().

Answers here are the Platform's own, so they are also the recorded answers the contract-parity check validates.
"""
import json
import sqlite3

import pytest
from test_access_key_chain import keyed, create, web, shared, app, service  # noqa: F401  (fixtures)
from ophiolite import Client, Credential
from ophiolite.errors import PermissionRefused, SourceDetached, SourceRevisionDiffers, SourceRevisionUnavailable

ORIGIN = 'https://workspace.example'


@pytest.fixture
def table(keyed, tmp_path):
    """A SQLite well table connected for alice, mapped and bound as a followed selection."""
    web = keyed; s = web.a.sources
    path = tmp_path / 'wells.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE wells(id TEXT, name TEXT, x REAL, y REAL)')
        db.executemany('INSERT INTO wells VALUES(?,?,?,?)', [('a', 'Alpha', 4.3, 52.0), ('b', 'Beta', 4.5, 52.1), ('c', 'Gamma', 4.7, 52.2)])
    config = {'id': 'sql', 'name': 'SQL', 'namespace': 'sql', 'type': 'sqlite', 'path': str(path), 'tables': {'w': {'table': 'wells', 'name': 'Wells'}}, 'principals': {'alice': True}}
    s.registry.connections['sql'] = config
    body = {'project_id': 'p', 'connection_id': 'sql', 'key': 'w', 'profile': 'sql-wells/1'}
    schema = s.call('schema', body, 'alice')
    s.call('mapping-save', {**body, 'mapping': {'entity': 'well', 'fields': schema['suggested_fields'], 'crs': 'EPSG:4326', 'schema_digest': schema['schema_digest']}}, 'alice')
    preview = s.call('preview', body, 'alice')
    selected = s.call('bind', {**body, 'mode': 'follow', 'preview_digest': preview['preview_digest'], 'acknowledge_unknowns': True}, 'alice')
    key = create(web, 'read')['key']
    return type('Table', (), {'web': web, 's': s, 'path': path, 'config': config, 'selected': selected, 'client': Client(ORIGIN, 'p', Credential.bearer(key), web.c)})()


def hold(s, ident, **fields):
    item = s._load(ident, 'p', 'alice'); item.update({'next_check': 4102444800, **fields})
    return s._save(item, item['generation'])


def test_a_key_reads_the_table_verified_and_creates_nothing(table):
    c = table.client
    before = len(list(c.entities()))
    source = c.source(table.selected['id'])
    snapshot = source.read(expect_revision=source.revision)
    assert [r['well_id'] for r in snapshot.rows] == ['a', 'b', 'c'] and snapshot.crs == 'EPSG:4326' and snapshot.revision == source.revision
    assert snapshot.columns == ['id', 'name', 'x', 'y'] and list(snapshot.to_frame().columns) == ['well_id', 'name', 'x', 'y']
    assert source.describe().row_count == 3
    assert len(list(c.entities())) == before  # a source read creates no wells or entities


def test_the_live_answers_validate_against_the_pinned_contract(table):
    import jsonschema
    from importlib.resources import files
    doc = json.loads(files('ophiolite.contracts').joinpath('openapi/v1/openapi.json').read_text())
    def check(op, value):
        schema = doc['paths']['/api/v1/projects/{project}/sources/' + op]['post']['responses']['200']['content']['application/json']['schema']
        jsonschema.validate(value, {**schema, 'components': doc['components']}, resolver=jsonschema.RefResolver('', {'components': doc['components']}))
    c = table.client
    check('list', c._post('sources', 'list', {}))
    check('export', c._post('sources', 'export', {'id': table.selected['id']}, retry=True))


def test_a_refreshed_selection_read_with_the_old_revision_differs(table):
    old = table.selected['reference']['revision']
    with sqlite3.connect(table.path) as db: db.execute("UPDATE wells SET x=4.4 WHERE id='a'")
    hold(table.s, table.selected['id'], next_check=0)  # due: the export reconciles the follow selection first
    with pytest.raises(SourceRevisionDiffers) as raised:
        table.client.source(table.selected['id']).read(expect_revision=old)
    assert raised.value.code == 'source-revision-differs' and raised.value.expected == old and raised.value.actual != old


def test_an_unrefreshed_selection_whose_row_changed_upstream_is_unavailable_and_gives_no_rows(table):
    hold(table.s, table.selected['id'])
    with sqlite3.connect(table.path) as db: db.execute("UPDATE wells SET x=4.4 WHERE id='a'")
    with pytest.raises(SourceRevisionUnavailable) as raised:
        table.client.source(table.selected['id']).read()
    assert raised.value.code == 'SOURCE_REVISION_UNAVAILABLE' and raised.value.status == 410


def test_the_owner_losing_membership_or_the_database_sign_in_is_refused(table):
    source = table.client.source(table.selected['id'])
    hold(table.s, table.selected['id'])
    del table.config['principals']['alice']
    with pytest.raises(PermissionRefused) as raised: source.read()
    assert raised.value.code == 'SOURCE_ACCESS_DENIED'
    table.config['principals']['alice'] = True
    del table.web.permissions['alice']
    with pytest.raises(PermissionRefused): source.read()


def test_a_detached_selection_is_answered_once(table):
    source = table.client.source(table.selected['id'])
    item = table.s._load(table.selected['id'], 'p', 'alice')
    table.s.call('remove', {'project_id': 'p', 'id': item['id'], 'expected_generation': item['generation']}, 'alice')
    sent = []; table.web.c.event_hooks['request'].append(lambda r: sent.append(r.url.path))
    with pytest.raises(SourceDetached) as raised: source.read()
    assert sent == ['/api/v1/projects/p/sources/export'] and raised.value.remedy.startswith('This source was removed from the project')
