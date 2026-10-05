"""E50c S1: Wells.with_source against a recording fixture that answers like the gateway (entities/list, releases/list,
get, download-snapshot, download). The kept copies are built as the Platform builds them (canonical sql-wells/1 bytes,
sha256 revision, a zip with assets/NN.json), so each check can be broken on its own: the checksum by a changed value
that keeps valid JSON, a valid table and a valid zip; the row lookup by a valid copy without the row; the join key by
two copies with the same row ids and other values, a copy at ordinal 1, reordered wells and duplicate names."""
import base64
import copy
import hashlib
import io
import json
import zipfile

import httpx
import pytest
from test_sources import SCHEMA, payload
from ophiolite import Client, Credential
from ophiolite.errors import IntegrityConflict, Refused, SourceChecksumMismatch, VerificationFailed
from ophiolite.locations import Well, Wells
from ophiolite.well_sources import NO_ORIGIN_REASON, capture_id

ROWS = [{'id': 'a', 'name': 'Alpha', 'x': 4.3, 'y': 52.0, 'operator': 'NAM'}, {'id': 'b', 'name': 'Beta', 'x': 4.5, 'y': 52.1, 'operator': None}]
OTHER = [{'id': 'a', 'name': 'Alpha', 'x': 4.3, 'y': 52.0, 'operator': 'Other A'}, {'id': 'b', 'name': 'Beta', 'x': 4.5, 'y': 52.1, 'operator': 'Other B'}]


def zipped(*assets):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as bundle:
        bundle.writestr('manifest.json', '{}'); bundle.writestr('receipt.json', '{}')
        for i, raw in enumerate(assets): bundle.writestr('assets/%02d.json' % i, raw)
    return base64.b64encode(out.getvalue()).decode()


def located(entity, name, release, ordinal, raw, row, profile='sql-wells/1'):
    source = {'asset_id': capture_id(release, ordinal), 'revision': hashlib.sha256(raw).hexdigest(), 'profile': profile, **({'row': row} if row else {})}
    return {'entity_id': entity, 'kind': 'well', 'name': name, 'location': {'x': 4.0, 'y': 52.0, 'crs': 'EPSG:4326', 'source': source, 'ambiguous': False}}


class Gateway:
    """The routes with_source reads, counted. `packages`: {release id: (state, [asset bytes])}; `answers` overrides one
    operation's response."""
    def __init__(self, wells, packages, answers=None, served=None):
        self.wells, self.packages, self.answers, self.calls = wells, packages, answers or {}, []
        self.served = served or {}  # release id -> the bytes actually sent instead of the kept ones

    def __call__(self, request):
        operation = request.url.path.rsplit('/', 1)[-1]
        body = json.loads(request.content or b'{}')
        self.calls.append(operation)
        if operation in self.answers:
            answer = self.answers[operation]
            return answer(body) if callable(answer) else answer
        if operation == 'list' and '/entities/' in request.url.path: return httpx.Response(200, json={'entities': self.wells, 'next_cursor': None})
        if operation == 'list':
            return httpx.Response(200, json={'items': [{'id': ident, 'state': state, 'manifest_digest': 'd' * 64, 'name': 'Wells imported', 'assets': len(raws)}
                                                      for ident, (state, raws) in self.packages.items()]})
        if operation in ('download-snapshot', 'download'):
            state, raws = self.packages[body['id']]
            return httpx.Response(200, json={'filename': 'snapshot-%s.zip' % body['id'], 'payload_base64': zipped(*self.served.get(body['id'], raws))})
        if operation == 'get':
            return httpx.Response(200, json={'id': body['id'], 'state': self.packages[body['id']][0], 'manifest': {}, 'manifest_digest': 'd' * 64, 'decisions': {}, 'display': {}})
        return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'unknown'})


def client(gateway):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=httpx.Client(transport=httpx.MockTransport(gateway)))


def frame_of(gateway, columns=None):
    with client(gateway) as c:
        return c.wells().with_source(columns=columns)


def by_id(frame):
    return {r['entity_id']: r for r in frame.to_dict('records')}


def test_the_sdk_names_a_kept_copy_as_the_server_does():
    # retained_assets.capture_id('r1', 0) on Platform c76c004
    assert capture_id('r1', 0) == '626dcc918bbac3e53e1caeb7ea326bda124832a9c4d9caac056789da3f31ccbb'


def test_each_well_joins_its_own_copy_and_row_without_dropping_or_repeating():
    first, second = payload(ROWS), payload(OTHER)
    wells = [located('e1', 'Same', 'r2', 1, second, 'b'), located('e2', 'Same', 'r1', 0, first, 'b'), located('e3', 'Alpha', 'r1', 0, first, 'a'),
             located('e4', 'Alpha again', 'r2', 1, second, 'a'), {'entity_id': 'e5', 'kind': 'well', 'name': 'Unlocated'},
             located('e6', 'Uploaded', 'r3', 0, b'{}', None, profile='well-location/1')]
    gateway = Gateway(wells, {'r1': ('snapshot', [first]), 'r2': ('approved', [payload([]), second])})
    frame = frame_of(gateway, ['operator', 'operator'])
    assert list(frame['entity_id']) == ['e1', 'e2', 'e3', 'e4', 'e5', 'e6'] and [c for c in frame.columns if c.startswith('source.')] == ['source.operator']
    rows = by_id(frame)
    assert {e: rows[e]['source.operator'] for e in ('e1', 'e2', 'e3', 'e4')} == {'e1': 'Other B', 'e2': None, 'e3': 'NAM', 'e4': 'Other A'}
    assert {e: rows[e]['source_state'] for e in rows} == {'e1': 'joined', 'e2': 'joined', 'e3': 'joined', 'e4': 'joined', 'e5': 'no origin', 'e6': 'no origin'}
    assert rows['e5']['source_reason'] == rows['e6']['source_reason'] == NO_ORIGIN_REASON
    # one listing of the packages, one download per package, whatever the number of wells
    assert sorted(gateway.calls) == sorted(['list', 'list', 'download-snapshot', 'download'])


def test_original_values_keep_their_types_and_every_column_is_offered_by_default():
    schema = SCHEMA + [{'name': 'big', 'type': 'INTEGER', 'nullable': True, 'primary_key': False}, {'name': 'depth_txt', 'type': 'NUMERIC', 'nullable': True, 'primary_key': False},
                       {'name': 'spud', 'type': 'DATE', 'nullable': True, 'primary_key': False}]
    rows = [{**ROWS[0], 'big': 2 ** 63 + 1, 'depth_txt': '12.50', 'spud': '1971-03-02'}, {**ROWS[1], 'big': None, 'depth_txt': None, 'spud': None}]
    raw = payload(rows, schema)
    frame = frame_of(Gateway([located('e1', 'A', 'r1', 0, raw, 'a'), located('e2', 'B', 'r1', 0, raw, 'b')], {'r1': ('snapshot', [raw])}))
    assert [c for c in frame.columns if c.startswith('source.')] == ['source.' + c['name'] for c in schema]
    a, b = by_id(frame)['e1'], by_id(frame)['e2']
    assert (a['source.big'], type(a['source.big'])) == (2 ** 63 + 1, int) and a['source.depth_txt'] == '12.50' and a['source.spud'] == '1971-03-02'
    assert b['source.big'] is None and b['source.operator'] is None


def test_columns_are_refused_only_when_known_to_be_absent():
    raw = payload(ROWS)
    every = Gateway([located('e1', 'A', 'r1', 0, raw, 'a')], {'r1': ('snapshot', [raw])})
    with pytest.raises(Refused, match='nope'): frame_of(every, ['operator', 'nope'])
    with pytest.raises(Refused, match='list of original column names'): frame_of(every, 'operator')
    # a copy that could not be read may hold the column: it is kept, missing
    mixed = Gateway([located('e1', 'A', 'r1', 0, raw, 'a'), located('e2', 'B', 'r2', 0, raw, 'b')], {'r1': ('snapshot', [raw]), 'r2': ('withdrawn', [raw])})
    rows = by_id(frame_of(mixed, ['nope']))
    assert rows['e1']['source.nope'] is None and rows['e2']['source_state'] == 'not readable'
    # nothing read at all: every well is still listed, with the column
    nothing = frame_of(Gateway([{'entity_id': 'e1', 'kind': 'well', 'name': 'U'}], {}), ['operator'])
    assert list(nothing['source_state']) == ['no origin'] and list(nothing.columns)[-1] == 'source.operator'
    empty = frame_of(Gateway([], {}), ['operator'])
    assert len(empty) == 0 and list(empty.columns)[-3:] == ['source_state', 'source_reason', 'source.operator']


def test_package_states_and_refusals_are_marked_and_everything_else_is_raised():
    raw = payload(ROWS)
    well = [located('e1', 'A', 'r1', 0, raw, 'a')]
    def mark(state='snapshot', **answers):
        row = by_id(frame_of(Gateway(well, {'r1': (state, [raw])}, answers)))['e1']
        return row['source_state'], row['source_reason']
    assert mark('withdrawn') == ('not readable', 'The kept copy was withdrawn.')
    assert mark('candidate') == ('not readable', 'The kept copy is under review; read it again after it is approved.')
    assert mark(**{'download-snapshot': httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'Release unavailable'})}) == ('not readable', 'Release unavailable')
    assert by_id(frame_of(Gateway([located('e1', 'A', 'gone', 0, raw, 'a')], {})))['e1']['source_state'] == 'not readable'
    # a 409 is a state change only when the package says so; otherwise (integrity, capacity) it is raised
    conflict = httpx.Response(409, json={'code': 'CONFLICT', 'message': 'This package was withdrawn; its contents are no longer available'})
    withdrawn_since = Gateway(well, {'r1': ('snapshot', [raw])}, {'download-snapshot': conflict,
                              'get': httpx.Response(200, json={'id': 'r1', 'state': 'withdrawn', 'manifest': {}, 'manifest_digest': 'd', 'decisions': {}, 'display': {}})})
    assert by_id(frame_of(withdrawn_since))['e1']['source_reason'] == 'The kept copy was withdrawn.'
    integrity = httpx.Response(409, json={'code': 'CONFLICT', 'message': 'Retained payload integrity check failed'})
    with pytest.raises(IntegrityConflict): frame_of(Gateway(well, {'r1': ('snapshot', [raw])}, {'download-snapshot': integrity}))
    with pytest.raises(Exception) as raised: frame_of(Gateway(well, {'r1': ('snapshot', [raw])}, {'download-snapshot': httpx.Response(500, json={'code': 'INTERNAL', 'message': 'boom'})}))
    assert not isinstance(raised.value, (AssertionError, KeyError))
    with pytest.raises(VerificationFailed, match='documented shape'): frame_of(Gateway(well, {'r1': ('snapshot', [raw])}, {'download-snapshot': httpx.Response(200, json={'filename': 'x'})}))
    with pytest.raises(SourceChecksumMismatch, match='could not be decoded'):
        frame_of(Gateway(well, {'r1': ('snapshot', [raw])}, {'download-snapshot': httpx.Response(200, json={'filename': 'x', 'payload_base64': base64.b64encode(b'not a zip').decode()})}))


def test_a_changed_value_in_a_valid_copy_is_a_checksum_mismatch():
    raw = payload(ROWS)
    changed = payload([{**ROWS[0], 'operator': 'Changed'}, ROWS[1]])  # valid JSON, a valid table, a valid zip
    gateway = Gateway([located('e1', 'A', 'r1', 0, raw, 'a')], {'r1': ('snapshot', [raw])}, served={'r1': [changed]})
    with pytest.raises(SourceChecksumMismatch, match='does not match the revision'): frame_of(gateway)


def test_a_reference_to_a_row_the_verified_copy_lacks_is_refused():
    without = payload(ROWS[1:])  # row 'a' removed from both lists; the reference names this copy's own digest
    with pytest.raises(VerificationFailed, match='has no row a'):
        frame_of(Gateway([located('e1', 'A', 'r1', 0, without, 'a')], {'r1': ('snapshot', [without])}))


def test_an_inconsistent_copy_is_refused_by_the_e50a_table_checks():
    data = json.loads(payload(ROWS)); data['wells'][0]['well_id'] = 'z'
    raw = json.dumps(data).encode()
    with pytest.raises(VerificationFailed, match='inconsistent with their mapping'):
        frame_of(Gateway([located('e1', 'A', 'r1', 0, raw, 'a')], {'r1': ('snapshot', [raw])}))


def test_wells_built_by_hand_have_no_client_to_read_with():
    with pytest.raises(Refused, match='client.wells'): Wells([Well({'entity_id': 'e', 'name': 'n'})], None, 0).with_source()
