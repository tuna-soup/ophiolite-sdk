"""E58b C5: a table kept as it is, read in Python (`Table`), and the verified file downloads (`Client.export_file`,
`Table.download`, `SourceSnapshot.download`). The payloads are written as Platform writes `ophiolite.table-file/1`;
the downloads answer through an httpx transport that plays the server, so the digest, revision and partial-file rules
are tested on the bytes the SDK receives. The real routes are in tests/gateway/test_tables.py. Expected values are
literals."""
import builtins
import copy
import hashlib
import json
import warnings
from decimal import Decimal

import httpx
import pytest
from ophiolite import client as client_module, sources, typed
from ophiolite.client import Client
from ophiolite.auth import Credential
from ophiolite.errors import IntegrityConflict, Refused, SourceRevisionDiffers, VerificationFailed
from ophiolite.models import invariants

REVISION = 'd442a98c304649256914cc9a6cd39e4aba76688bcbacba5702c053170944fb31'
PARQUET = b'PAR1' + b'\x00' * 64 + b'PAR1'


def column(name, logical, db_type=None, read=True):
    return {'name': name, 'db_type': db_type or logical, 'logical': logical if read else None, 'nullable': True, 'comment': None, 'read': read}


COLUMNS = [column('well', 'text'), column('dbk', 'integer', 'int64'), column('porosity', 'float', 'double'), column('oil', 'decimal', 'decimal128(9,3)'),
           column('sampled', 'date', 'date32'), column('remark', 'float', 'double'), column('tags', None, 'list<string>', read=False)]
ROWS = [['L16-12', '4035368835', 21.5, '8161.000', '2012-03-01', -888.0],
        ['L16-12', str(2 ** 53 + 1), -888.0, '-888.000', None, 4.0]]
NOTES = {'porosity': {'description': None, 'unit': '%', 'missing': '-888'}, 'oil': {'description': None, 'unit': 'm3', 'missing': '-888'}}


def payload(columns=COLUMNS, rows=ROWS, notes=NOTES):
    columns, rows, notes = copy.deepcopy((columns, rows, notes))
    read = [c['name'] for c in columns if c['read']]
    return {'schema': 'ophiolite.table-file/1', 'representation': 'normalized', 'encoding': 'table-encoding/1', 'columns': columns, 'key': None,
            'declarations': {'columns': notes, 'coordinates': None}, 'rows': rows, 'source_rows': list(range(2, 2 + len(rows))),
            'context': {'type': 'table', 'format': 'csv', 'profile': 'table-csv/1', 'rows': len(rows), 'columns': len(columns),
                        'coverage': {'read': read, 'not_read': [{'name': c['name'], 'db_type': c['db_type'], 'reason': 'type not read'} for c in columns if not c['read']]}}}


def kept(value=None, **options):
    value = value or payload()
    wire = {'asset_id': 'asset-1', 'revision': REVISION, 'representations': [{'kind': 'normalized', 'sha256': 'n' * 64}]}
    with warnings.catch_warnings(record=True) as said:
        warnings.simplefilter('always')
        table = typed.Table(None, value, b'original', wire_descriptor=wire, **options)
    return table, [str(w.message) for w in said]


# --- the frame code is the one of tables read as tables ------------------------------------------------------------

def test_the_frame_is_the_frame_code_of_tables_read_as_tables():
    assert typed.Table._frame is sources._table_frame
    assert typed.CLASSES['table'] is typed.Table and 'table' in typed.TYPES


def test_to_frame_types_each_column_and_keeps_large_integers_exact():
    pd = pytest.importorskip('pandas')
    table, _ = kept()
    frame = table.to_frame()
    assert [str(t) for t in frame.dtypes] == ['string', 'Int64', 'Float64', 'object', 'datetime64[s]', 'Float64']
    assert list(frame['dbk']) == [4035368835, 9007199254740993]  # 2**53+1 is not a float
    assert frame['oil'][0] == Decimal('8161.000') and isinstance(frame['oil'][0], Decimal)
    assert frame['sampled'][0] == pd.Timestamp('2012-03-01') and frame['sampled'].isna()[1]
    assert (frame.attrs['revision'], frame.attrs['profile'], frame.attrs['not_read']) == (REVISION, 'table-csv/1', [{'name': 'tags', 'db_type': 'list<string>'}])
    assert table.rows[1] == {'well': 'L16-12', 'dbk': 9007199254740993, 'porosity': -888.0, 'oil': '-888.000', 'sampled': None, 'remark': 4.0}
    assert table.units == {'porosity': '%', 'oil': 'm3'} and len(table) == 2


def test_missing_declared_nulls_only_the_declared_marker():
    pytest.importorskip('pandas')
    table, _ = kept()
    frame = table.to_frame(missing='declared')
    assert frame['porosity'].isna().tolist() == [False, True] and frame['oil'].isna().tolist() == [False, True]
    assert frame['remark'].tolist() == [-888.0, 4.0]  # -888 without a declared marker stays a value
    assert frame.attrs['transformations'] == [{'missing_applied': {'porosity': '-888', 'oil': '-888'}}]
    assert table.rows[1]['porosity'] == -888.0  # the rows never change
    with pytest.raises(Refused): table.to_frame(missing='all')


def test_a_column_not_read_warns_once_naming_it():
    pytest.importorskip('pandas')
    table, said = kept()
    assert said == ['Not read: tags (list<string>); their type is not supported yet.']
    with warnings.catch_warnings(record=True) as again:
        warnings.simplefilter('always'); table.to_frame(); table.to_frame()
    assert again == []
    whole, said = kept(payload(columns=COLUMNS[:-1]))
    assert said == [] and whole.not_read == []


@pytest.mark.parametrize('damage, said', [
    (lambda v: v['rows'][0].__setitem__(1, 4035368835), 'dbk, row 1: the value is not written as a integer'),
    (lambda v: v['rows'][1].pop(), 'Row 2 does not hold one value per column read'),
    (lambda v: v.__setitem__('schema', 'ophiolite.table/1'), 'not the documented table'),
])
def test_a_malformed_kept_table_is_refused(damage, said):
    value = payload(); damage(value)
    with pytest.raises(VerificationFailed, match=said): kept(value)


def test_rows_columns_and_coverage_must_agree_with_the_context():
    invariants.typed_payload(payload())
    for change in (lambda v: v['source_rows'].pop(), lambda v: v['context'].__setitem__('rows', 3),
                   lambda v: v['context']['coverage']['read'].pop(), lambda v: v['context']['coverage']['not_read'].clear()):
        value = payload(); change(value)
        with pytest.raises(VerificationFailed): invariants.typed_payload(value)


# --- downloads: verified, atomic, no pyarrow ------------------------------------------------------------------------

def server(body=PARQUET, digest=None, revision=REVISION, status=200, seen=None):
    def handle(request):
        if seen is not None: seen.append(str(request.url))
        if status != 200:
            return httpx.Response(status, json={'code': 'INCOMPATIBLE_CONTEXT', 'message': 'This type has no positions; download as Parquet.'})
        return httpx.Response(200, content=body, headers={'Content-Type': 'application/vnd.apache.parquet', 'X-Ophiolite-Revision': revision,
                                                           'X-Content-SHA256': digest or hashlib.sha256(body).hexdigest(),
                                                           'Content-Disposition': 'attachment; filename="core.parquet"'})
    return Client('https://x.example', 'p', Credential.bearer('oph_api_alice'), httpx.Client(transport=httpx.MockTransport(handle)))


def test_a_download_is_saved_only_when_it_is_the_file_the_server_holds(tmp_path):
    seen = []
    saved = server(seen=seen).export_file('asset-1', REVISION, tmp_path / 'core.parquet', format='parquet', curves=['GR', 'RHOB'])
    assert saved == tmp_path / 'core.parquet' and saved.read_bytes() == PARQUET and [p.name for p in tmp_path.iterdir()] == ['core.parquet']
    assert seen == ['https://x.example/api/v1/projects/p/scientific-assets/asset-1/revisions/%s/export?format=parquet&curves=GR&curves=RHOB' % REVISION]


@pytest.mark.parametrize('body, digest', [(PARQUET[:40], hashlib.sha256(PARQUET).hexdigest()),            # truncated, the whole file's header
                                          (PARQUET[:-1] + b'X', hashlib.sha256(PARQUET).hexdigest())])    # corrupted, the same length
def test_truncated_or_corrupted_bytes_with_correct_headers_leave_no_file(tmp_path, body, digest):
    with pytest.raises(IntegrityConflict, match='The download did not match the file the server holds; nothing was saved.'):
        server(body, digest).export_file('asset-1', REVISION, tmp_path / 'core.parquet')
    assert list(tmp_path.iterdir()) == []


def test_another_revision_in_the_answer_refuses_and_leaves_no_file(tmp_path):
    with pytest.raises(VerificationFailed, match='another revision'):
        server(revision='e' * 64).export_file('asset-1', REVISION, tmp_path / 'core.parquet')
    assert list(tmp_path.iterdir()) == []


def test_a_refusal_keeps_the_servers_sentence_and_leaves_no_file(tmp_path):
    with pytest.raises(Exception, match='') as raised:
        server(status=422).export_file('asset-1', REVISION, tmp_path / 'core.geoparquet', format='geoparquet')
    assert raised.value.status == 422 and list(tmp_path.iterdir()) == []
    with pytest.raises(Refused): server().export_file('asset-1', REVISION, tmp_path / 'x', format='xlsx')
    with pytest.raises(Refused): server().export_file('asset-1', REVISION, tmp_path / 'x', curves='GR')


def test_download_needs_no_pyarrow(tmp_path, monkeypatch):
    real = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in ('pyarrow', 'pandas'): raise ImportError('blocked: ' + name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    table, _ = kept()
    table._client = server()
    assert table.download(tmp_path / 'core.parquet').read_bytes() == PARQUET


def test_every_download_goes_through_the_one_verified_save(tmp_path, monkeypatch):
    calls = []
    real = client_module.save_verified
    monkeypatch.setattr(client_module, 'save_verified', lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    table, _ = kept(); table._client = server()
    table.download(tmp_path / 'a.parquet')
    snapshot = type('S', (), {'revision': REVISION, '_source': None})()
    source = sources.Source(server(), {'id': 's1', 'name': 'w', 'profile': 'table/1', 'state': 'current', 'mode': 'follow', 'authority': 'sql',
                                       'key': 'w', 'reference': {'revision': REVISION}})
    snapshot._source = source
    sources.SourceSnapshot.download(snapshot, tmp_path / 'b.parquet')
    assert calls == [tmp_path / 'a.parquet', tmp_path / 'b.parquet']


def test_a_connected_table_whose_revision_moved_is_told_apart_and_leaves_no_file(tmp_path):
    source = sources.Source(server(revision='e' * 64), {'id': 's1', 'name': 'w', 'profile': 'table/1', 'state': 'current', 'mode': 'follow',
                                                        'authority': 'sql', 'key': 'w', 'reference': {'revision': REVISION}})
    with pytest.raises(SourceRevisionDiffers) as raised: source.download(tmp_path / 'w.parquet', expect_revision=REVISION)
    assert (raised.value.expected, raised.value.actual) == (REVISION, 'e' * 64) and list(tmp_path.iterdir()) == []
    wells = sources.Source(server(), {'id': 's2', 'name': 'w', 'profile': 'sql-wells/1', 'state': 'current', 'mode': 'follow',
                                      'authority': 'sql', 'key': 'w', 'reference': {'revision': REVISION}})
    with pytest.raises(Refused, match='Only a SQL table read as a table'): wells.download(tmp_path / 'w.parquet')


def test_a_table_not_read_from_a_server_says_how_to_read_it(tmp_path):
    table, _ = kept()
    with pytest.raises(Refused, match='client.read_data'): table.download(tmp_path / 'x.parquet')
