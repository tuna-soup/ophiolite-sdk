"""E58b C5, in-process gateway lane: a table kept as it is through `client.imports.from_table(path, "table")`, read back
as a `Table` with `client.read_data`, and downloaded as Parquet and CSV through the real export route (`Table.download`,
`ophiolite read-data --format`); a connected SQL table downloaded with `source.read().download()` through the real
`sources/export-file`, where a selection that moved between the read and the download is told apart from one that
can no longer be read (F2). Expected values are literals."""
import hashlib
import io
import json
import sqlite3

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from ophiolite import Client, Credential, cli
from ophiolite.errors import SourceDetached, SourceRevisionDiffers
from ophiolite.typed import Table

pa = pytest.importorskip('pyarrow')
pq = pytest.importorskip('pyarrow.parquet')

ORIGIN = 'https://workspace.example'
CSV = b'well,dbk,porosity,remark\r\nL16-12,4035368835,21.5,-888\r\nL16-12,9007199254740993,-888,4.0\r\n'
REVISION = hashlib.sha256(CSV).hexdigest()


@pytest.fixture
def kept(keyed, tmp_path):
    alice = client(keyed, 'alice', 'delegate')
    (tmp_path / 'input').mkdir(); (tmp_path / 'out').mkdir()
    path = tmp_path / 'input' / 'core.csv'; path.write_bytes(CSV)
    done = alice.imports.from_table(path, 'table', columns={'porosity': {'unit': '%', 'missing': '-888'}})
    assert (done['run']['state'], done['preview']['target']) == ('complete', 'table'), done['run']
    unit = done['run']['units'][0]
    return type('Kept', (), {'web': keyed, 'client': alice, 'asset': unit['asset_id'], 'revision': unit['revision'], 'path': tmp_path / 'out'})()


def opened(raw):
    table = pq.read_table(io.BytesIO(raw))
    return table, json.loads(table.schema.metadata[b'ophiolite.export'])


def test_a_kept_table_reads_back_as_a_table_and_downloads_as_parquet_and_csv(kept):
    pd = pytest.importorskip('pandas')
    table = kept.client.read_data(kept.asset, kept.revision)
    assert isinstance(table, Table) and (table.revision, table.profile, table.not_read) == (REVISION, 'table-csv/1', [])
    assert table.original == CSV and table.units == {'porosity': '%'}
    assert table.rows == [{'well': 'L16-12', 'dbk': 4035368835, 'porosity': 21.5, 'remark': -888.0},
                          {'well': 'L16-12', 'dbk': 9007199254740993, 'porosity': -888.0, 'remark': 4.0}]
    frame = table.to_frame(missing='declared')
    assert [str(t) for t in frame.dtypes] == ['string', 'Int64', 'Float64', 'Float64'] and list(frame['dbk']) == [4035368835, 9007199254740993]
    assert frame['porosity'].isna().tolist() == [False, True] and frame['remark'].tolist() == [-888.0, 4.0]
    saved = table.download(kept.path / 'core.parquet')
    found, record = opened(saved.read_bytes())
    assert (record['revision'], record['asset_id'], record['profile']) == (REVISION, kept.asset, 'table-csv/1')
    assert found.column('dbk').to_pylist() == [4035368835, 9007199254740993] and found.schema.field('porosity').metadata[b'ophiolite.missing'] == b'-888'
    csv = table.download(kept.path / 'core.csv', format='csv')
    assert csv.read_bytes() == b'well,dbk,porosity,remark\r\nL16-12,4035368835,21.5,-888.0\r\nL16-12,9007199254740993,-888.0,4.0\r\n'
    assert sorted(p.name for p in kept.path.iterdir()) == ['core.csv', 'core.parquet']  # no partial file left beside them
    assert pd.read_parquet(saved)['dbk'].tolist() == [4035368835, 9007199254740993]


def test_a_type_without_positions_is_refused_in_the_servers_words_and_nothing_is_saved(kept):
    from ophiolite.errors import Incompatible
    with pytest.raises(Incompatible) as raised:
        kept.client.export_file(kept.asset, kept.revision, kept.path / 'core.geoparquet', format='geoparquet')
    assert raised.value.status == 422 and not (kept.path / 'core.geoparquet').exists()


def test_the_command_line_saves_one_verified_file(kept, monkeypatch, capsys):
    cli._load()
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, kept.web.c))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (kept.path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    out = kept.path / 'out.csv'
    capsys.readouterr()
    cli.entrypoint(['read-data', '--configuration', str(kept.path / 'configuration.json'), '--asset', kept.asset, '--revision', kept.revision,
                    '--format', 'csv', '--out', str(out)])
    assert capsys.readouterr().out.strip() == 'Saved %s as CSV - written from revision %s and checked against the file the server holds.' % (out, REVISION)
    assert out.read_bytes().startswith(b'well,dbk,porosity,remark\r\n')
    with pytest.raises(SystemExit) as stopped:
        cli.entrypoint(['read-data', '--configuration', str(kept.path / 'configuration.json'), '--asset', kept.asset, '--revision', kept.revision,
                        '--format', 'csv', '--out', str(out)])
    assert stopped.value.code != 0 and 'already exists' in capsys.readouterr().err


# --- a connected table ----------------------------------------------------------------------------------------------

@pytest.fixture
def connected(keyed, tmp_path):
    web = keyed; s = web.a.sources
    path = tmp_path / 'wells.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE wells(id TEXT, name TEXT, x REAL, y REAL)')
        db.executemany('INSERT INTO wells VALUES(?,?,?,?)', [('a', 'Alpha', 4.3, 52.0), ('b', 'Beta', 4.5, 52.1), ('c', 'Gamma', 4.7, 52.2)])
    s.registry.connections['sql'] = {'id': 'sql', 'name': 'SQL', 'namespace': 'sql', 'type': 'sqlite', 'path': str(path),
                                     'tables': {'w': {'table': 'wells', 'name': 'Wells'}}, 'principals': {'alice': True}}
    body = {'project_id': 'p', 'connection_id': 'sql', 'key': 'w', 'profile': 'table/1'}
    schema = s.call('schema', body, 'alice')
    s.call('mapping-save', {**body, 'mapping': {'profile': 'table/1', 'key': ['id'], 'columns': {}, 'coordinates': None, 'schema_digest': schema['schema_digest']},
                            'expected_generation': 0}, 'alice')
    preview = s.call('preview', body, 'alice')
    selected = s.call('bind', {**body, 'mode': 'follow', 'preview_digest': preview['preview_digest'], 'acknowledge_unknowns': True}, 'alice')
    key = create(web, 'read')['key']
    return type('Connected', (), {'web': web, 's': s, 'path': path, 'selected': selected, 'out': tmp_path / 'out',
                                  'client': Client(ORIGIN, 'p', Credential.bearer(key), web.c)})()


def due(s, ident):
    """The selection's next check is due: the next read reconciles the follow selection to the new head."""
    item = s._load(ident, 'p', 'alice'); item.update({'next_check': 0})
    return s._save(item, item['generation'])


def test_a_connected_table_downloads_the_rows_it_read(connected):
    connected.out.mkdir()
    snapshot = connected.client.source(connected.selected['id']).read()
    saved = snapshot.download(connected.out / 'wells.parquet')
    found, record = opened(saved.read_bytes())
    assert record['revision'] == snapshot.revision and found.to_pylist()[0] == {'id': 'a', 'name': 'Alpha', 'x': 4.3, 'y': 52.0}
    assert snapshot.download(connected.out / 'wells.csv', format='csv').read_bytes() == b'id,name,x,y\r\na,Alpha,4.3,52.0\r\nb,Beta,4.5,52.1\r\nc,Gamma,4.7,52.2\r\n'


def test_a_selection_that_moved_after_the_read_is_told_apart_from_one_that_is_gone(connected):
    connected.out.mkdir()
    source = connected.client.source(connected.selected['id'])
    snapshot = source.read()
    with sqlite3.connect(connected.path) as db: db.execute("UPDATE wells SET x=4.4 WHERE id='a'")
    due(connected.s, connected.selected['id'])
    with pytest.raises(SourceRevisionDiffers) as moved:
        snapshot.download(connected.out / 'wells.parquet')
    assert moved.value.expected == snapshot.revision and moved.value.actual != snapshot.revision
    assert list(connected.out.iterdir()) == []
    item = connected.s._load(connected.selected['id'], 'p', 'alice')
    connected.s.call('remove', {'project_id': 'p', 'id': item['id'], 'expected_generation': item['generation']}, 'alice')
    with pytest.raises(SourceDetached) as gone:
        snapshot.download(connected.out / 'wells.parquet')
    assert gone.value.code == 'SOURCE_DETACHED' and not isinstance(gone.value, SourceRevisionDiffers)
    assert list(connected.out.iterdir()) == []
