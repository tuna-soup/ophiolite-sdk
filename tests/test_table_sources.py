"""E50b1 C6: reading a table/1 source in Python and on the command line (ADR 0020 §3, D2, D3, D11, 5a, 5b).

5a and 5b run verbatim on the answers the Platform gave for the ADR's tables (recorded by
`tests/fixtures/table-sources/record.py`: a PostgreSQL cluster, the gateway's own Sources). The other cases are payloads
written as Connectors writes them, with their checksums computed again after each change, so only the structural check
under test can refuse them. Expected values are literals.
"""
import base64
import copy
import hashlib
import json
import warnings
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from ophiolite.errors import Refused, SourceSignInRowsDiffer, VerificationFailed
from test_sources import Gateway, client, selection

RECORDED = Path(__file__).parent / 'fixtures' / 'table-sources'


def recorded(name):
    answer = json.loads((RECORDED / (name + '.json')).read_text())
    return Gateway([answer['selection']], answer['export']), answer


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def column(name, logical, db_type=None, read=True, nullable=True, comment=None):
    return {'name': name, 'db_type': db_type or logical, 'logical': logical if read else None, 'nullable': nullable, 'comment': comment, 'read': read}


def table(columns, rows, key=None, notes=None, coordinates=None, **change):
    return {'schema': 'ophiolite.table/1', 'encoding': 'table-encoding/1', 'columns': columns, 'key': key,
            'declarations': {'columns': notes or {}, 'coordinates': coordinates}, 'rows': rows, **change}


def exported(document, raw=None):
    """sources/export as the gateway answers it, its sha256, byte count and revision computed from RAW."""
    raw = raw if raw is not None else canonical(document).encode()
    sha = hashlib.sha256(raw).hexdigest()
    reference = {'authority': 'sql', 'key': 't', 'revision': sha, 'profile': 'table/1'}
    manifest = {'schema': 'ophiolite.source-snapshot/1', 'reference': reference, 'metadata': {'kind': 'table', 'name': 't'}, 'sha256': sha,
                'bytes': len(raw), 'media_type': 'application/json', 'contract': {}, 'losses': [], 'scientific_validation': 'source-declared; review required',
                'reviewed_meaning_digest': 'm' * 64, 'interpretation': None}
    return {'manifest': manifest, 'payload_base64': base64.b64encode(raw).decode()}


def reading(document):
    answer = exported(document)
    gateway = Gateway([selection(answer, profile='table/1', name='t')], answer)
    return gateway, client(gateway)


def read(document, **options):
    _, c = reading(document)
    with c: return c.source('s1').read(**options)


# ---- 5a and 5b, verbatim ---------------------------------------------------------------------------------------------

def test_5a_a_keyed_table_reads_as_the_adr_states():
    gateway, _ = recorded('5a')
    with client(gateway) as c, warnings.catch_warnings():
        warnings.simplefilter('error')  # nothing is left unread, so nothing warns
        snap = c.source(c.sources()[0].id).read()
    assert (snap.profile, snap.key, snap.crs) == ('table/1', ('well_code', 'month'), None)
    assert snap.rows[2] == {'well_code': 'NL-002', 'month': '2026-01-01', 'oil_m3': '87.125', 'gas_km3': None, 'remarks': None}
    df = snap.to_frame()
    assert [str(df[c].dtype) for c in df.columns] == ['string', 'datetime64[s]', 'object', 'object', 'string']
    assert df.loc[0, 'oil_m3'] == Decimal('1520.250') and str(df.loc[0, 'oil_m3']) == '1520.250'
    assert df.attrs['columns'][2]['unit'] == 'm3' and df.attrs['revision'] == snap.revision and df.attrs['not_read'] == []
    assert gateway.calls == ['list', 'list', 'export']


def test_5b_an_unkeyed_table_with_duplicate_rows():
    gateway, _ = recorded('5b')
    with client(gateway) as c: snap = c.source(c.sources()[0].id).read()
    assert snap.key is None and len(snap.rows) == 3
    assert [r['lithology'] for r in snap.rows] == ['sand', 'clay', 'clay']
    df = snap.to_frame()
    assert [str(df[c].dtype) for c in df.columns] == ['string', 'Float64', 'Float64', 'string', 'string']
    assert list(df.index) == [0, 1, 2]
    assert snap.mapping is None and snap.original is None


# ---- exact values --------------------------------------------------------------------------------------------------------

LIMITS = ['-9223372036854775808', '9007199254740993', '9223372036854775807']


def test_integers_decode_exactly_in_rows_and_frames():
    snap = read(table([column('n', 'integer', 'bigint')], [[v] for v in LIMITS] + [[None]]))
    assert [r['n'] for r in snap.rows] == [-2 ** 63, 2 ** 53 + 1, 2 ** 63 - 1, None]
    frame = snap.to_frame()
    assert str(frame['n'].dtype) == 'Int64' and frame['n'].tolist()[:3] == [-2 ** 63, 2 ** 53 + 1, 2 ** 63 - 1] and frame['n'].isna().tolist()[3]


TIMES = [column('i', 'integer'), column('day', 'date'), column('ms', 'timestamp'), column('ns', 'timestamp'), column('utc', 'timestamptz'),
         column('far', 'timestamp')]


def test_each_datetime_column_takes_its_smallest_exact_resolution_and_infinity_stays_text():
    rows = [['1', 'infinity', '2026-01-01T00:00:00.5', '2026-01-01T00:00:00.000000001', '2026-01-01T10:00:00.12Z', '1500-01-01T00:00:00.000000001'],
            ['2', '2024-02-29', '2026-01-01T00:00:00.125', '2026-01-01T00:00:00', '2000-01-01T01:00:00Z', '2026-01-01T00:00:00']]
    snap = read(table(TIMES, rows, key=['i']))
    frame = snap.to_frame()
    assert {c: str(frame[c].dtype) for c in ('day', 'ms', 'ns', 'utc', 'far')} == {
        'day': 'string', 'ms': 'datetime64[ms]', 'ns': 'datetime64[ns]', 'utc': 'datetime64[ms, UTC]', 'far': 'string'}
    assert frame.loc[0, 'day'] == 'infinity' and not frame['day'].isna().any()  # never NaT
    assert str(frame.loc[0, 'ns']) == '2026-01-01 00:00:00.000000001'
    assert frame.attrs['text_fallbacks'] == {'day': 'holds infinity, which a pandas datetime cannot hold; kept as text',
                                             'far': 'holds a value outside the range pandas holds at nanosecond resolution; kept as text'}
    assert snap.rows[0]['day'] == 'infinity'


DECLARED = {'oil': {'description': 'Oil produced', 'unit': 'm3', 'missing': '-999.250'}, 'n': {'description': None, 'unit': None, 'missing': '-1'}}


def test_declared_missing_values_and_float_decimals_are_explicit_and_recorded():
    rows = [['1', '-999.250'], ['-1', '1520.250'], ['2', None]]
    snap = read(table([column('n', 'integer'), column('oil', 'decimal', 'numeric(12,3)')], rows, notes=DECLARED))
    before = copy.deepcopy(snap.rows)
    plain = snap.to_frame()
    assert plain.attrs['transformations'] == [] and plain.loc[0, 'oil'] == Decimal('-999.250') and plain.loc[1, 'n'] == -1
    marked = snap.to_frame(missing='declared')
    assert marked['oil'].isna().tolist() == [True, False, True] and marked['n'].isna().tolist() == [False, True, False]
    assert marked.attrs['transformations'] == [{'missing_applied': {'n': '-1', 'oil': '-999.250'}}]
    floated = snap.to_frame(decimal='float')
    assert str(floated['oil'].dtype) == 'Float64' and floated.loc[1, 'oil'] == 1520.25 and floated.attrs['transformations'] == [{'decimal': 'float'}]
    both = snap.to_frame(missing='declared', decimal='float')
    assert both.attrs['transformations'] == [{'missing_applied': {'n': '-1', 'oil': '-999.250'}}, {'decimal': 'float'}]
    assert both.attrs['checksum_scope'] == 'sha256 covers the source payload, not the transformed frame values'
    assert snap.rows == before and snap.rows[0]['oil'] == '-999.250'  # the rows never change
    with pytest.raises(Refused, match='decimal="exact" or "float"'): snap.to_frame(decimal='rounded')


# ---- columns not read ------------------------------------------------------------------------------------------------------

PARTIAL = table([column('well', 'text'), column('notes', None, 'jsonb', read=False), column('depth', 'integer')], [['A-1', '900'], ['A-2', '1000']])


def test_every_partial_read_warns_and_all_columns_can_be_required():
    gateway, c = reading(PARTIAL)
    with c:
        source = c.source('s1')
        for _ in range(2):
            with pytest.warns(UserWarning, match=r'^The revision covers only the columns read; not read: notes \(jsonb\)\.$'):
                snap = source.read()
        assert snap.not_read == [{'name': 'notes', 'db_type': 'jsonb'}] and snap.rows[0] == {'well': 'A-1', 'depth': 900}
        assert snap.to_frame().attrs['not_read'] == [{'name': 'notes', 'db_type': 'jsonb'}] and list(snap.to_frame().columns) == ['well', 'depth']
        with pytest.raises(Refused, match=r'not read: notes \(jsonb\); no rows were returned') as refused: source.read(require_all_columns=True)
        assert refused.value.docs.endswith('#not-read-columns')
        with pytest.warns(UserWarning):
            described = source.describe().to_dict()
    assert described['coverage'] == 'The revision covers only the columns read; not read: notes (jsonb).' and described['row_count'] == 2
    assert gateway.calls.count('export') == 4


def test_a_table_has_no_mapped_or_original_view():
    snap = read(table([column('well', 'text')], [['A-1']]))
    with pytest.raises(Refused): snap.to_frame(original=True)
    with pytest.raises(Refused): snap.records(original=True)
    assert snap.records() == [{'well': 'A-1'}] and snap.mapped_columns() == ['well']


# ---- malformed payloads (checksums computed again, so only the structure can refuse them) -----------------------------------

GOOD = table([column('well', 'text'), column('n', 'integer')], [['A-1', '1']], key=['well'])
MALFORMED = {
    'duplicate column names': (dict(GOOD, columns=[column('well', 'text'), column('well', 'integer')]), 'names a column twice'),
    'row width': (dict(GOOD, rows=[['A-1']]), 'Row 1 does not hold one value per column read'),
    'wrong encoded type': (dict(GOOD, rows=[['A-1', 1]]), 'n, row 1: the value is not written as a integer'),
    'unknown encoding': (dict(GOOD, encoding='table-encoding/2'), 'encoding this SDK does not read'),
    'not-read values present': (dict(GOOD, columns=[column('well', 'text'), column('n', 'integer'), column('raw', None, 'bytea', read=False)],
                                     rows=[['A-1', '1', '\\x00']]), 'Row 1 does not hold one value per column read'),
    'key of a column not read': (dict(GOOD, key=['raw'], columns=GOOD['columns'] + [column('raw', None, 'bytea', read=False)]), 'key names a column that is not read'),
}


@pytest.mark.parametrize('damage', sorted(MALFORMED))
def test_a_malformed_table_is_refused_with_its_checksum_intact(damage):
    document, message = MALFORMED[damage]
    with pytest.raises(VerificationFailed, match=message): read(document)
    read(GOOD)  # the control reads


def test_another_sign_in_is_named_as_the_server_names_it():
    refusal = httpx.Response(409, json={'error': 'x', 'code': 'SOURCE_SIGN_IN_ROWS_DIFFER',
                                        'message': 'Your database sign-in returns different rows than the reviewed revision. Review the source with this sign-in to read it.',
                                        'remedy': 'Review the source with the database sign-in you use now, or sign in as the person who reviewed it.',
                                        'docs': '/docs/reference/errors/#source_sign_in_rows_differ', 'request_id': 'req_1'})
    answer = exported(GOOD)
    gateway = Gateway([selection(answer, profile='table/1')], refusal)
    with client(gateway) as c, pytest.raises(SourceSignInRowsDiffer) as raised: c.source('s1').read()
    assert raised.value.message.startswith('Your database sign-in returns different rows') and gateway.calls.count('export') == 1


def test_the_asynchronous_client_forwards_both_options():
    import anyio
    from ophiolite import Credential
    from ophiolite.aio import AsyncClient
    answer = exported(PARTIAL)
    gateway = Gateway([selection(answer, profile='table/1')], answer)
    async def main():
        http = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
        async with AsyncClient('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=http) as c:
            source = await c.source('s1')
            revision = answer['manifest']['reference']['revision']
            with pytest.warns(UserWarning, match='not read: notes'):
                assert (await source.read(revision)).revision == revision
            with pytest.raises(Refused, match='not read: notes'):
                await source.read(require_all_columns=True)
    anyio.run(main)


# ---- the command line --------------------------------------------------------------------------------------------------------

def test_the_command_line_prints_the_not_read_line_and_refuses_on_request(tmp_path):
    from test_cli_subprocess import gateway, run
    answer = exported(PARTIAL)
    routes = {'/sources/list': (200, {'selections': [selection(answer, profile='table/1')], 'scope': 's'}), '/sources/export': (200, answer)}
    with gateway(routes) as server:
        read_ = run(tmp_path, 'sources', 'read', 's1', url=server.url)
        refused = run(tmp_path, 'sources', 'read', 's1', '--require-all-columns', '--out', str(tmp_path / 'rows.csv'), url=server.url)
        described = run(tmp_path, 'sources', 'describe', 's1', url=server.url)
    assert read_.returncode == 0 and read_.stdout.splitlines() == ['well,depth', 'A-1,900', 'A-2,1000']
    assert 'The revision covers only the columns read; not read: notes (jsonb).' in read_.stderr
    assert refused.returncode != 0 and 'not read: notes (jsonb); no rows were returned' in refused.stderr + refused.stdout and not (tmp_path / 'rows.csv').exists()
    assert described.returncode == 0 and described.stdout.splitlines()[-1] == 'The revision covers only the columns read; not read: notes (jsonb).'
