"""E50a S3: reading a connected source from Python, against a recording fixture that answers like the gateway.

The fixture builds sources/export the way the Platform does (canonical JSON payload, sha256 revision, base64), so each
verification can be broken on its own: the checksum by a changed value that keeps valid JSON and shape, each of the
three digest equalities separately, the expected revision, the selected identity, the row consistency. Unsupported
profiles are refused before any request (the fixture counts requests).
"""
import base64
import copy
import hashlib
import json
import sys

import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite import application_transport as policy
from ophiolite.errors import (CapacityExceeded, Refused, SourceChecksumMismatch, SourceNeedsReview, SourceNotFound, SourceNotSupported,
                              SourceRevisionDiffers, VerificationFailed)
from ophiolite.sources import Source, SourceSnapshot

SCHEMA = [{'name': 'id', 'type': 'TEXT', 'nullable': True, 'primary_key': False}, {'name': 'name', 'type': 'TEXT', 'nullable': True, 'primary_key': False},
          {'name': 'x', 'type': 'REAL', 'nullable': True, 'primary_key': False}, {'name': 'y', 'type': 'REAL', 'nullable': True, 'primary_key': False},
          {'name': 'operator', 'type': 'TEXT', 'nullable': True, 'primary_key': False}]
ROWS = [{'id': 'a', 'name': 'Alpha', 'x': 4.3, 'y': 52.0, 'operator': 'NAM'}, {'id': 'b', 'name': 'Beta', 'x': 4.5, 'y': 52.1, 'operator': None}]
FIELDS = {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y', 'operator': 'operator', 'depth': ''}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def payload(rows=ROWS, schema=SCHEMA, fields=FIELDS, crs='EPSG:28992'):
    """The sql-wells/1 payload as Connectors writes it: wells and source rows sorted by identity."""
    ident = fields['id']
    ordered = sorted(rows, key=lambda r: str(r[ident]))
    wells = [{'well_id': str(r[ident]), 'name': r[fields['name']], 'operator': r.get(fields['operator']) if fields.get('operator') else None,
              'x': float(r[fields['x']]), 'y': float(r[fields['y']]), 'depth': float(r[fields['depth']]) if fields.get('depth') and r.get(fields['depth']) is not None else None,
              'metadata': {}} for r in ordered]
    mapping = {'entity': 'well', 'fields': fields, 'crs': crs, 'schema_digest': hashlib.sha256(canonical(schema).encode()).hexdigest(), 'version': 1}
    return canonical({'schema': 'ophiolite.sql-wells/1', 'source_schema': schema, 'source_rows': ordered, 'wells': wells, 'mapping': mapping}).encode()


def exported(raw, key='w', authority='sql', profile='sql-wells/1'):
    sha = hashlib.sha256(raw).hexdigest()
    reference = {'authority': authority, 'key': key, 'revision': sha, 'profile': profile}
    manifest = {'schema': 'ophiolite.source-snapshot/1', 'reference': reference, 'metadata': {'kind': 'well', 'name': key, 'null_counts': {'operator': 1}, 'unresolved': []},
                'sha256': sha, 'bytes': len(raw), 'media_type': 'application/json', 'contract': {}, 'losses': [], 'scientific_validation': 'source-declared; review required',
                'reviewed_meaning_digest': 'm' * 64, 'interpretation': None}
    return {'manifest': manifest, 'payload_base64': base64.b64encode(raw).decode()}


def selection(answer, ident='s1', profile='sql-wells/1', state='current', name='Groningen wells'):
    reference = answer['manifest']['reference'] if answer else {'authority': 'files', 'key': 'k', 'revision': 'r' * 64, 'profile': profile}
    return {'id': ident, 'project_id': 'p', 'owner': 'alice', 'connection_id': 'sql', 'key': reference['key'], 'profile': profile, 'authority': reference['authority'],
            'connection_fingerprint': 'f', 'asset_identity': 'i', 'mode': 'follow', 'reference': reference, 'name': name, 'interpretation': None, 'state': state,
            'last_checked': 1.0, 'failures': 0, 'next_check': 2.0, 'generation': 1, 'publication_policy': 'explicit destination required; upstream write unsupported'}


class Gateway:
    """sources/list and sources/export, counted."""
    def __init__(self, selections, export=None):
        self.selections, self.export, self.calls = selections, export, []

    def __call__(self, request):
        operation = request.url.path.rsplit('/', 1)[-1]
        self.calls.append(operation)
        if operation == 'list': return httpx.Response(200, json={'selections': self.selections, 'scope': 'your upstream-authorized selections; not shared credentials'})
        if operation == 'export': return self.export if isinstance(self.export, httpx.Response) else httpx.Response(200, json=self.export)
        return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'unknown'})


def client(gateway):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=httpx.Client(transport=httpx.MockTransport(gateway)))


def reading(answer=None, **selected):
    answer = answer or exported(payload())
    gateway = Gateway([selection(answer, **selected)], answer)
    return gateway, client(gateway)


def test_a_source_is_listed_selected_by_id_and_read_verified():
    gateway, c = reading()
    with c:
        listed = c.sources()
        assert [type(s) for s in listed] == [Source] and listed[0].name == 'Groningen wells'
        snapshot = c.source('s1').read()
    assert type(snapshot) is SourceSnapshot and not hasattr(snapshot, 'entity_id')  # never a Well
    assert [r['well_id'] for r in snapshot.rows] == ['a', 'b'] and snapshot.crs == 'EPSG:28992' and snapshot.revision == snapshot.sha256
    assert snapshot.original == sorted(ROWS, key=lambda r: r['id']) and snapshot.columns == ['id', 'name', 'x', 'y', 'operator']
    assert gateway.calls == ['list', 'list', 'export']  # nothing else is called


def test_a_name_never_selects_and_an_unknown_id_is_not_found_without_an_export():
    gateway, c = reading()
    with c:
        for wrong in ('Groningen wells', 'nope'):
            with pytest.raises(SourceNotFound) as raised: c.source(wrong)
            assert raised.value.docs.endswith('#source-not-found') and raised.value.remedy
    assert 'export' not in gateway.calls


@pytest.mark.parametrize('profile', ['geotiff/1', 'las2/1', 'osdu-record/1', 'osdu-welllog-parquet/1', 'edited-wells/1'])
def test_other_profiles_are_listed_but_refused_before_any_request(profile):
    gateway = Gateway([selection(None, profile=profile)])
    with client(gateway) as c:
        source = c.sources()[0]
        assert source.profile == profile
        for call in (source.read, source.describe):
            with pytest.raises(SourceNotSupported, match='not supported for this kind of source yet') as raised: call()
            assert profile in raised.value.message
    assert gateway.calls == ['list']


def test_a_changed_value_with_valid_json_is_a_checksum_mismatch():
    good = exported(payload())
    changed = payload().replace(b'"x":4.3', b'"x":4.4')  # same shape, still valid JSON
    assert changed != payload() and json.loads(changed)
    tampered = {**good, 'payload_base64': base64.b64encode(changed).decode()}
    _, c = reading(tampered)
    with c, pytest.raises(SourceChecksumMismatch): c.source('s1').read()


def test_each_digest_equality_is_checked_on_its_own():
    raw = payload(); good = exported(raw)
    other = hashlib.sha256(b'other').hexdigest()
    revision = copy.deepcopy(good); revision['manifest']['reference']['revision'] = other  # sha256 matches the payload; the revision does not
    sha = copy.deepcopy(good); sha['manifest']['sha256'] = other; sha['manifest']['reference']['revision'] = other  # manifest agrees with itself, not with the payload
    size = copy.deepcopy(good); size['manifest']['bytes'] += 1
    for broken in (revision, sha, size):
        gateway = Gateway([selection(good)], broken)
        with client(gateway) as c, pytest.raises(SourceChecksumMismatch): c.source('s1').read()


def test_an_expected_revision_is_checked_and_a_difference_exposes_no_rows():
    answer = exported(payload())
    actual = answer['manifest']['reference']['revision']
    _, c = reading(answer)
    with c:
        assert len(c.source('s1').read(expect_revision=actual)) == 2
        with pytest.raises(SourceRevisionDiffers) as raised: c.source('s1').read(expect_revision='0' * 64)
    assert (raised.value.expected, raised.value.actual, raised.value.code) == ('0' * 64, actual, 'source-revision-differs')
    assert raised.value.docs.endswith('#source-revision-differs')


def test_a_different_source_with_valid_checksums_is_refused():
    selected = exported(payload())
    substituted = exported(payload(), key='other-table')  # every checksum is valid; it is not the selected source
    gateway = Gateway([selection(selected)], substituted)
    with client(gateway) as c, pytest.raises(VerificationFailed, match='different source'): c.source('s1').read()


@pytest.mark.parametrize('damage', ['drop-well', 'rename-well'])
def test_rows_inconsistent_with_their_mapping_are_refused(damage):
    data = json.loads(payload())
    if damage == 'drop-well': data['wells'].pop()
    else: data['wells'][0]['well_id'] = 'zzz'
    _, c = reading(exported(canonical(data).encode()))
    with c, pytest.raises(VerificationFailed, match='inconsistent'): c.source('s1').read()


def test_over_the_sdk_bound_states_the_bound(monkeypatch):
    monkeypatch.setattr(policy, 'MAX_RESPONSE', 2048)
    big = [{'id': 'w%04d' % i, 'name': 'Well %d' % i, 'x': 4.0, 'y': 52.0, 'operator': None} for i in range(200)]
    _, c = reading(exported(payload(big)))
    with c, pytest.raises(CapacityExceeded) as raised: c.source('s1').read()
    assert '2,048 bytes' in raised.value.message


def test_the_servers_needs_review_message_is_passed_on_verbatim():
    refusal = httpx.Response(409, json={'error': 'SQL snapshot exceeds 64 MiB', 'code': 'SOURCE_NEEDS_REVIEW', 'message': 'SQL snapshot exceeds 64 MiB',
                                        'remedy': 'Review the source\'s mapping or selection in the Workspace, then try again.', 'docs': '/docs/reference/errors/#source_needs_review',
                                        'request_id': 'req_1'})
    answer = exported(payload())
    gateway = Gateway([selection(answer)], refusal)
    with client(gateway) as c, pytest.raises(SourceNeedsReview) as raised: c.source('s1').read()
    assert raised.value.message == 'SQL snapshot exceeds 64 MiB' and gateway.calls.count('export') == 1


def test_no_refusal_by_state():
    _, c = reading(state='paused')
    with c:
        source = c.source('s1')
        assert source.state == 'paused' and len(source.read()) == 2


def test_a_location_only_table_has_no_depth_or_operator_column_and_attrs_carry_the_context():
    schema = SCHEMA[:4]; rows = [{k: v for k, v in r.items() if k != 'operator'} for r in ROWS]
    fields = {**FIELDS, 'operator': ''}
    _, c = reading(exported(payload(rows, schema, fields, crs='EPSG:4326')))
    with c: snapshot = c.source('s1').read()
    frame = snapshot.to_frame()
    assert list(frame.columns) == ['well_id', 'name', 'x', 'y'] and str(frame['x'].dtype) == 'Float64'
    assert frame.attrs == {'crs': 'EPSG:4326', 'revision': snapshot.revision, 'sha256': snapshot.sha256, 'profile': 'sql-wells/1', 'source_id': 's1'}
    assert list(snapshot.to_frame(original=True).columns) == ['id', 'name', 'x', 'y']


def test_original_values_are_kept_exactly():
    """Disposition 11: explicit expected source values — nulls, a large integer, decimal and date strings, an unmapped column."""
    schema = SCHEMA + [{'name': 'spud', 'type': 'DATE', 'nullable': True, 'primary_key': False}, {'name': 'license', 'type': 'INTEGER', 'nullable': True, 'primary_key': False},
                       {'name': 'depth_text', 'type': 'NUMERIC', 'nullable': True, 'primary_key': False}]
    rows = [{**ROWS[0], 'spud': '1963-07-01', 'license': 2 ** 63 + 7, 'depth_text': '2950.125'}, {**ROWS[1], 'spud': None, 'license': None, 'depth_text': None}]
    _, c = reading(exported(payload(rows, schema)))
    with c: snapshot = c.source('s1').read()
    frame = snapshot.to_frame(original=True)
    assert frame.loc[0, 'license'] == 2 ** 63 + 7 and type(frame.loc[0, 'license']) is int  # not a float
    assert frame.loc[0, 'spud'] == '1963-07-01' and frame.loc[0, 'depth_text'] == '2950.125'
    assert frame.loc[1, 'spud'] is None and frame.loc[1, 'operator'] is None
    assert snapshot.records(original=True)[0] == rows[0]
    assert list(snapshot.to_frame().columns) == ['well_id', 'name', 'operator', 'x', 'y']  # depth unmapped; operator mapped


def test_an_empty_table_reads_as_no_rows_with_its_columns():
    _, c = reading(exported(payload([])))
    with c: snapshot = c.source('s1').read()
    assert len(snapshot) == 0 and list(snapshot.to_frame(original=True).columns) == ['id', 'name', 'x', 'y', 'operator']
    assert list(snapshot.to_frame().columns) == ['well_id', 'name', 'operator', 'x', 'y']


def test_describe_reads_once_and_keeps_no_rows():
    gateway, c = reading()
    with c: description = c.source('s1').describe()
    assert gateway.calls.count('export') == 1 and not hasattr(description, 'rows')
    document = description.to_dict()
    assert document['row_count'] == 2 and [col['name'] for col in document['columns']] == ['id', 'name', 'x', 'y', 'operator']
    assert document['crs'] == 'EPSG:28992' and document['mapped_columns'] == ['well_id', 'name', 'operator', 'x', 'y']


def test_without_pandas_to_frame_is_refused_and_records_still_work(monkeypatch):
    _, c = reading()
    with c: snapshot = c.source('s1').read()
    monkeypatch.setitem(sys.modules, 'pandas', None)
    with pytest.raises(Refused, match='ophiolite\\[pandas\\]'): snapshot.to_frame()
    assert snapshot.records()[0] == {'well_id': 'a', 'name': 'Alpha', 'operator': 'NAM', 'x': 4.3, 'y': 52.0}


def test_the_classes_read_only_fields_the_contract_declares():
    """Disposition 2: recorded list and export answers validate against the resolved OpenAPI schemas of the pinned
    contracts, and every field the SDK models read is a required property there."""
    import jsonschema
    from importlib.resources import files
    from ophiolite.models.api import SourceExportAnswer, SourceExportManifestDoc, SourceReferenceDoc, SourceSelectionDoc, SourceSelectionsPage
    doc = json.loads(files('ophiolite.contracts').joinpath('openapi/v1/openapi.json').read_text())
    def schema_of(op):
        return doc['paths']['/api/v1/projects/{project}/sources/' + op]['post']['responses']['200']['content']['application/json']['schema']
    def resolve(schema):
        while '$ref' in schema: schema = doc['components']['schemas'][schema['$ref'].rsplit('/', 1)[1]]
        if 'anyOf' in schema:
            options = [s for s in schema['anyOf'] if s.get('type') != 'null']
            if len(options) == 1: return resolve(options[0])
        if schema.get('type') == 'array': return resolve(schema['items'])
        return schema
    answer = exported(payload())
    validator = lambda op, value: jsonschema.validate(value, {**schema_of(op), 'components': doc['components']},
                                                     resolver=jsonschema.RefResolver('', {'components': doc['components']}))
    validator('export', answer)
    validator('list', {'selections': [selection(answer)], 'scope': 's'})
    pairs = [(SourceSelectionsPage, resolve(schema_of('list'))), (SourceExportAnswer, resolve(schema_of('export')))]
    selection_schema = resolve(resolve(schema_of('list'))['properties']['selections'])
    manifest_schema = resolve(resolve(schema_of('export'))['properties']['manifest'])
    pairs += [(SourceSelectionDoc, selection_schema), (SourceExportManifestDoc, manifest_schema), (SourceReferenceDoc, resolve(manifest_schema['properties']['reference'])),
              (SourceReferenceDoc, resolve(selection_schema['properties']['reference']))]
    for model, schema in pairs:
        read = {f.alias or name for name, f in model.model_fields.items()}
        assert read <= set(schema['required']), (model.__name__, read - set(schema['required']))
