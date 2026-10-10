"""E50a: read a connected source from Python.

`client.sources()` lists the source selections you bound in this project (every profile); `client.source(id)` picks one
by its stable id. `describe()` and `read()` are for SQL well-location tables (sql-wells/1) and, from E50b1, any approved
SQL table read as a table (table/1, ADR 0020); any other profile is refused before a request is sent. Both call sources/export once — `describe()` costs one full read —
and verify what came back before anything is returned:

- the returned source is the one selected (authority, key and profile);
- sha256 of the decoded payload equals the manifest's sha256, which equals the reference's revision, and the byte count
  matches (the checksum guards transport and decoding, not authenticity: the server computed both);
- with `expect_revision`, the revision is the one expected (a check on what the server returned, never a request for an
  older revision), otherwise SourceRevisionDiffers and no rows are exposed;
- the rows are consistent (one mapped row per source row, the same identities).

A source row is not a project well: `read()` creates no wells or entities. Wells read through `client.wells()` carry a
*reference* to the source row they were located from (source_asset_id, source_revision, source_row); a source read
returns the *fields* of the table itself.
"""
import base64
import binascii
import hashlib
import json
import re
import warnings

from .errors import (Refused, SourceChecksumMismatch, SourceNotFound, SourceNotSupported, SourceRevisionDiffers, VerificationFailed,
                     SOURCE_GUIDE)
from .models.api import OrgConnectionsPage, SourceExportAnswer, SourceSelectionsPage

SUPPORTED = 'sql-wells/1'
TABLE = 'table/1'  # E50b1: any approved table, read as a table
PROFILES = (SUPPORTED, TABLE)
LOGICAL = ('text', 'integer', 'float', 'decimal', 'boolean', 'date', 'timestamp', 'timestamptz')
CHECKSUM_SCOPE = 'sha256 covers the source payload, not the transformed frame values'
MAPPED = ('well_id', 'name', 'operator', 'x', 'y', 'depth')
OPTIONAL = ('operator', 'depth')  # dropped from the mapped view when the mapping leaves them unmapped


def _checked(model, answer, what):
    from pydantic import ValidationError
    try: model.model_validate(answer)
    except (ValidationError, ValueError, TypeError): raise VerificationFailed('The %s answered outside its documented shape.' % what) from None
    return answer


def _refuse(error_class, message, recovery, anchor, **kwargs):
    return error_class(message, recovery, remedy=recovery, docs=SOURCE_GUIDE + '#' + anchor, **kwargs)


class Source:
    """One source selection you bound in this project: what it names (authority, key, profile), its state and the exact
    revision it holds. `state` is reported, never acted on: the server decides what can be read."""

    def __init__(self, client, document):
        self._client, self.document = client, document
        self.id, self.name, self.profile = document['id'], document['name'], document['profile']
        self.state, self.mode = document['state'], document['mode']
        self.authority, self.key = document['authority'], document['key']
        self.revision = document['reference']['revision']

    def __repr__(self):
        return 'Source(%r, %s, %s, revision %s)' % (self.name, self.profile, self.state, self.revision[:12])

    def _export(self, expect_revision):
        if self.profile not in PROFILES:
            raise _refuse(SourceNotSupported, 'Reading %s sources is not supported for this kind of source yet; only SQL well-location tables (%s) and SQL tables (%s) are.'
                          % (self.profile, SUPPORTED, TABLE), 'List it with client.sources(); read SQL tables with source.read().', 'source-not-supported')
        answer = _checked(SourceExportAnswer, self._client._post('sources', 'export', {'id': self.id}, retry=True), 'source export')
        manifest = answer['manifest']; reference = manifest['reference']
        if (reference['authority'], reference['key'], reference['profile']) != (self.authority, self.key, self.profile):
            raise VerificationFailed('The server returned a different source than the one selected; nothing was read.')
        try: payload = base64.b64decode(answer['payload_base64'], validate=True)
        except (binascii.Error, ValueError): raise _refuse(SourceChecksumMismatch, 'The source payload could not be decoded.', 'Read it again.', 'source-checksum-mismatch') from None
        digest = hashlib.sha256(payload).hexdigest()
        if digest != manifest['sha256'] or len(payload) != manifest['bytes']:
            raise _refuse(SourceChecksumMismatch, 'The source payload does not match its manifest checksum.', 'Read it again; if it repeats, report the request.', 'source-checksum-mismatch')
        if manifest['sha256'] != reference['revision']:
            raise _refuse(SourceChecksumMismatch, 'The source revision does not name the payload that was returned.', 'Read it again; if it repeats, report the request.', 'source-checksum-mismatch')
        if expect_revision is not None and reference['revision'] != expect_revision:
            raise SourceRevisionDiffers(expect_revision, reference['revision'])
        try: data = json.loads(payload)
        except ValueError: raise VerificationFailed('The source payload is not the documented table.') from None
        return manifest, data, digest

    def read(self, expect_revision=None, require_all_columns=False):
        """Every row of this SQL table at the revision the server holds, verified (see the module notes).
        `expect_revision`: refuse (SourceRevisionDiffers, no rows) unless that is the revision returned.
        A table/1 table may hold columns of a type that is not read (listed in `snapshot.not_read`): the revision covers
        only the columns read, every such read warns naming them, and `require_all_columns=True` refuses it instead."""
        manifest, data, digest = self._export(expect_revision)
        snapshot = SourceSnapshot(self, manifest, data, digest)
        if getattr(snapshot, 'not_read', None):
            named = ', '.join('%s (%s)' % (c['name'], c['db_type']) for c in snapshot.not_read)
            if require_all_columns:
                raise _refuse(Refused, 'Some columns of this table are not read: %s; no rows were returned.' % named,
                              'Ask for an approved view without them, or read without require_all_columns to take the columns that are read.', 'not-read-columns')
            warnings.warn('The revision covers only the columns read; not read: %s.' % named, UserWarning, stacklevel=2)
        return snapshot

    def describe(self, expect_revision=None):
        """What this table holds — columns and types, the mapping, CRS, row count, nulls — without keeping its rows.
        It verifies like read() and costs one full read. A table/1 table: its columns, key, declarations, the columns
        not read and the coverage sentence ("The revision covers only the columns read; ...")."""
        return SourceDescription(self.read(expect_revision))


def verified_table(data):
    """(source_schema, source_rows, wells, mapping) of a decoded sql-wells/1 document, after the table checks: the
    documented schema, one mapped row per source row with the same identities, unique identities. E50c reads kept
    copies of the same document through the same checks."""
    if not isinstance(data, dict) or data.get('schema') != 'ophiolite.sql-wells/1':
        raise VerificationFailed('The source payload is not the documented table.')
    try:
        schema, original, rows, mapping = data['source_schema'], data['source_rows'], data['wells'], data['mapping']
        ident = mapping['fields']['id']
        consistent = len(rows) == len(original) and all(r['well_id'] == str(o[ident]) for r, o in zip(rows, original))
    except (KeyError, TypeError): consistent = False
    if not consistent or len({r['well_id'] for r in rows}) != len(rows):
        raise VerificationFailed('The source rows are inconsistent with their mapping; nothing was read.')
    return schema, original, rows, mapping

INTEGER = re.compile(r'-?(0|[1-9][0-9]*)')
DECIMAL = re.compile(r'-?[0-9]+(\.[0-9]+)?')


def _encoded(logical, value):
    """Whether VALUE is written as table-encoding/1 writes a LOGICAL value (integers and decimals as text)."""
    if value is None: return True
    if logical in ('text', 'date', 'timestamp', 'timestamptz'): return isinstance(value, str)
    if logical == 'integer': return isinstance(value, str) and INTEGER.fullmatch(value) is not None
    if logical == 'decimal': return isinstance(value, str) and DECIMAL.fullmatch(value) is not None
    if logical == 'float': return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, bool)  # boolean


def verified_data_table(data):
    """(columns, read column names, rows as lists) of a decoded table/1 document, after the structural checks: the
    documented schema and encoding, unique column names, a logical type on every column read and none on a column not
    read, a key of columns read, one value per column read in every row, and every value encoded as its column's type."""
    if not isinstance(data, dict) or data.get('schema') != 'ophiolite.table/1':
        raise VerificationFailed('The source payload is not the documented table.')
    if data.get('encoding') != 'table-encoding/1':
        raise VerificationFailed('The table is written in an encoding this SDK does not read (%s); upgrade ophiolite to read it.' % str(data.get('encoding'))[:40])
    columns, key, rows = data.get('columns'), data.get('key'), data.get('rows')
    shaped = isinstance(columns, list) and all(isinstance(c, dict) and isinstance(c.get('name'), str) and isinstance(c.get('read'), bool)
                                                and isinstance(c.get('db_type'), str) and (c.get('logical') in LOGICAL if c['read'] else c.get('logical') is None)
                                                for c in columns)
    if not shaped or not isinstance(rows, list) or not isinstance(data.get('declarations'), dict):
        raise VerificationFailed('The table columns are not the documented shape; nothing was read.')
    names = [c['name'] for c in columns]
    if len(set(names)) != len(names): raise VerificationFailed('The table names a column twice; nothing was read.')
    read = [c for c in columns if c['read']]
    if key is not None and not (isinstance(key, list) and key and set(key) <= {c['name'] for c in read}):
        raise VerificationFailed('The declared key names a column that is not read; nothing was read.')
    for number, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(read):
            raise VerificationFailed('Row %d does not hold one value per column read; nothing was read.' % number)
        for column, value in zip(read, row):
            if not _encoded(column['logical'], value):
                raise VerificationFailed('%s, row %d: the value is not written as a %s; nothing was read.' % (column['name'], number, column['logical']))
    return columns, [c['name'] for c in read], rows


def _decoded(logical, value):
    """A payload value as snapshot.rows holds it: integers as int; everything else as written (decimals and dates as text)."""
    return int(value) if logical == 'integer' and value is not None else value


class SourceSnapshot:
    """One verified read of a source table. Never a Well. A wells table (sql-wells/1): `rows` are the mapped rows
    (well_id, name, operator, x, y, depth, metadata) and `original` the source rows with every original column, as the
    server returned them. A table (table/1): `rows` are dicts by column name (integers as int, None for NULL, decimals
    and dates as their exact text), `columns` the column list, `key` a tuple or None, `crs` only when declared,
    `not_read` the columns not read; `mapping` and `original` are None."""

    def __init__(self, source, manifest, data, digest):
        self.id, self.name, self.profile = source.id, source.name, manifest['reference']['profile']
        self.authority, self.key = manifest['reference']['authority'], manifest['reference']['key']
        self.revision, self.sha256, self.bytes = manifest['reference']['revision'], digest, manifest['bytes']
        self.manifest = manifest
        if self.profile == TABLE: return self._table(data)
        schema, original, rows, mapping = verified_table(data)
        self.mapping, self.crs = mapping, mapping.get('crs')
        self.schema, self.rows, self.original = schema, rows, original
        self.columns = [c['name'] for c in schema]

    def _table(self, data):
        columns, read, rows = verified_data_table(data)
        logical = [c['logical'] for c in columns if c['read']]
        self.columns, self.read_columns = [dict(c) for c in columns], read
        self.key = tuple(data['key']) if data['key'] is not None else None
        coordinates = data['declarations'].get('coordinates')
        self.crs = coordinates['crs'] if coordinates else None
        self.declarations = data['declarations']
        self.not_read = [{'name': c['name'], 'db_type': c['db_type']} for c in columns if not c['read']]
        self.rows = [{name: _decoded(kind, value) for name, kind, value in zip(read, logical, row)} for row in rows]
        self.mapping = self.original = self.schema = None

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return 'SourceSnapshot(%r, %d rows, %s, revision %s)' % (self.name, len(self.rows), self.crs, self.revision[:12])

    def mapped_columns(self):
        """The mapped view's columns: unmapped optional ones (depth, operator) are left out, so a location-only table has
        no all-null depth column. A table/1 table: the columns read, in table order."""
        if self.profile == TABLE: return list(self.read_columns)
        fields = self.mapping.get('fields') or {}
        return [c for c in MAPPED if c not in OPTIONAL or fields.get(c)]

    def records(self, original=False):
        """Plain rows (no pandas): the mapped view, or with `original` every source column exactly as returned. A table/1
        table has one view: its rows as read."""
        if self.profile == TABLE:
            if original: raise Refused('A table read as a table has no mapped view; its rows are the original columns read.')
            return [dict(row) for row in self.rows]
        if original:
            return [{c: row.get(c) for c in self.columns} for row in self.original]
        columns = self.mapped_columns()
        return [{c: row.get(c) for c in columns} for row in self.rows]

    def to_frame(self, original=False, missing=None, decimal='exact'):
        """A DataFrame of the rows. Mapped view: x, y and depth as nullable floats. `original=True`: every source column
        with its values unchanged (object columns: large integers, decimal and date strings are kept as given). The
        declared CRS, revision, sha256 and profile are in `frame.attrs`; coordinates are never converted.
        A table/1 table (ADR 0020 D2, D3): one column per column read, typed by its logical type; `missing="declared"`
        sets the values equal to a column's declared missing marker to NA and `decimal="float"` turns decimals into
        floats (lossy); both are recorded in `frame.attrs["transformations"]`, and `snapshot.rows` never changes."""
        try: import pandas as pd
        except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
        if missing not in (None, 'declared') or decimal not in ('exact', 'float'):
            raise Refused('Use missing=None or "declared", and decimal="exact" or "float".')
        if self.profile == TABLE:
            if original: raise Refused('A table read as a table has no mapped view; call to_frame() for its columns as read.')
            return _table_frame(self, pd, missing, decimal)
        if missing is not None or decimal != 'exact': raise Refused('missing= and decimal= apply to tables read as tables (table/1).')
        columns = self.columns if original else self.mapped_columns()
        frame = pd.DataFrame(self.records(original), columns=columns, dtype=object)
        if not original:
            for column in ('x', 'y', 'depth'):
                if column in frame: frame[column] = frame[column].astype('Float64')
            for column in ('well_id', 'name', 'operator'):
                if column in frame: frame[column] = frame[column].astype('string')
        frame.attrs.update({'crs': self.crs, 'revision': self.revision, 'sha256': self.sha256, 'profile': self.profile, 'source_id': self.id})
        return frame


FALLBACK_INFINITY = 'holds infinity, which a pandas datetime cannot hold; kept as text'
FALLBACK_RANGE = 'holds a value outside the range pandas holds at %s resolution; kept as text'
UNITS = {'s': 0, 'ms': 3, 'us': 6, 'ns': 9}


def _year(text):
    return int(text[:text.index('-', 1)])


def _datetimes(pd, kind, values):
    """(series, None) typed at the smallest exact resolution, or (text series, reason) when a value is infinite or
    outside pandas' range: nothing is clamped, rounded or turned into NaT."""
    import numpy as np
    present = [v.rstrip('Z') for v in values if v is not None]
    if any(v in ('infinity', '-infinity') for v in present): return pd.Series(values, dtype='string'), FALLBACK_INFINITY
    digits = max([len(v.split('.', 1)[1]) for v in present if '.' in v] or [0])
    unit = 's' if kind == 'date' else next(u for u, n in UNITS.items() if digits <= n)
    if unit == 'ns' and not all(1678 <= _year(v) <= 2261 for v in present): return pd.Series(values, dtype='string'), FALLBACK_RANGE % 'nanosecond'
    array = np.array([np.datetime64(v.rstrip('Z'), unit) if v is not None else np.datetime64('NaT', unit) for v in values], dtype='datetime64[%s]' % unit)
    series = pd.Series(array)
    return (series.dt.tz_localize('UTC') if kind == 'timestamptz' else series), None


def _column(pd, kind, values, decimal):
    from decimal import Decimal
    if kind == 'decimal' and decimal == 'exact': return pd.Series([Decimal(v) if v is not None else pd.NA for v in values], dtype=object), None
    if kind == 'decimal': return pd.Series([float(v) if v is not None else None for v in values], dtype='Float64'), None
    if kind in ('date', 'timestamp', 'timestamptz'): return _datetimes(pd, kind, values)
    return pd.Series(values, dtype={'text': 'string', 'integer': 'Int64', 'float': 'Float64', 'boolean': 'boolean'}[kind]), None


def _same(kind, value, marker):
    """A value equals a declared missing marker, compared in the column's own encoding after decoding (D3)."""
    from decimal import Decimal, InvalidOperation
    try:
        if kind == 'integer': return int(value) == int(marker)
        if kind == 'float': return float(value) == float(marker)
        if kind == 'decimal': return Decimal(value) == Decimal(marker)
    except (ValueError, InvalidOperation): return False
    if kind == 'boolean': return str(value).lower() == str(marker).lower()
    return value == marker


def _table_frame(snapshot, pd, missing, decimal):
    kinds = {c['name']: c for c in snapshot.columns if c['read']}
    notes = snapshot.declarations.get('columns') or {}
    data, applied, fallbacks, transformations = {}, {}, {}, []
    for name in snapshot.read_columns:
        kind = kinds[name]['logical']; values = [row[name] for row in snapshot.rows]
        marker = (notes.get(name) or {}).get('missing')
        if missing == 'declared' and marker is not None:
            values = [None if v is not None and _same(kind, v, marker) else v for v in values]
            applied[name] = marker
        data[name], reason = _column(pd, kind, values, decimal)
        if reason: fallbacks[name] = reason
    if applied: transformations.append({'missing_applied': applied})
    if decimal == 'float' and any(c['logical'] == 'decimal' for c in kinds.values()): transformations.append({'decimal': 'float'})
    frame = pd.DataFrame(data, columns=snapshot.read_columns)
    frame.attrs.update({'profile': snapshot.profile, 'revision': snapshot.revision, 'sha256': snapshot.sha256, 'key': snapshot.key, 'crs': snapshot.crs,
                        'columns': [{**{k: c[k] for k in ('name', 'db_type', 'logical', 'nullable', 'comment')},
                                     **{k: (notes.get(c['name']) or {}).get(k) for k in ('description', 'unit', 'missing')}} for c in kinds.values()],
                        'not_read': [dict(c) for c in snapshot.not_read], 'text_fallbacks': fallbacks, 'transformations': transformations,
                        'checksum_scope': CHECKSUM_SCOPE})
    return frame


class SourceDescription:
    """A source table's shape at one verified revision: columns with their types, the reviewed mapping, the declared
    CRS, the row count and nulls per mapped field. No rows are kept."""

    def __init__(self, snapshot):
        self.id, self.name, self.profile = snapshot.id, snapshot.name, snapshot.profile
        self.revision, self.sha256, self.bytes, self.crs = snapshot.revision, snapshot.sha256, snapshot.bytes, snapshot.crs
        if self.profile == TABLE:
            self.columns, self.row_count, self.key = [dict(c) for c in snapshot.columns], len(snapshot.rows), snapshot.key
            self.declarations, self.not_read = snapshot.declarations, [dict(c) for c in snapshot.not_read]
            named = ', '.join('%s (%s)' % (c['name'], c['db_type']) for c in self.not_read)
            self.coverage = ('The revision covers only the columns read; not read: %s.' % named) if named else 'The revision covers every column.'
            return
        self.columns = [dict(c) for c in snapshot.schema]
        self.mapping, self.row_count = snapshot.mapping, len(snapshot.rows)
        self.mapped_columns = snapshot.mapped_columns()
        metadata = snapshot.manifest.get('metadata') or {}
        self.null_counts, self.unresolved = metadata.get('null_counts'), metadata.get('unresolved', [])

    def to_dict(self):
        if self.profile == TABLE:
            return {'id': self.id, 'name': self.name, 'profile': self.profile, 'revision': self.revision, 'sha256': self.sha256, 'bytes': self.bytes,
                    'crs': self.crs, 'row_count': self.row_count, 'columns': self.columns, 'key': list(self.key) if self.key else None,
                    'declarations': self.declarations, 'not_read': self.not_read, 'coverage': self.coverage}
        return {'id': self.id, 'name': self.name, 'profile': self.profile, 'revision': self.revision, 'sha256': self.sha256, 'bytes': self.bytes,
                'crs': self.crs, 'row_count': self.row_count, 'columns': self.columns, 'mapped_columns': self.mapped_columns,
                'mapping': self.mapping, 'null_counts': self.null_counts, 'unresolved': self.unresolved}

    def __repr__(self):
        return 'SourceDescription(%r, %d rows, %d columns, %s)' % (self.name, self.row_count, len(self.columns), self.crs)


class SourceClient:
    def org_connections(self, organization):
        """E39: the organisation's database connections you use or administer, each with your own readiness (with an
        access key, only those you use, in the organisation of its project). Sign-ins and passwords are never answered."""
        from .publish import json_bytes
        if not isinstance(organization, str) or not organization: raise Refused('Name the organisation by its id.')
        answer = self._post_bytes('org-connections', 'list', json_bytes({'organization_id': organization}), retry=True)
        page = _checked(OrgConnectionsPage, answer, 'organisation connection listing')
        if page['organization_id'] != organization: raise VerificationFailed('The organisation connection listing answered for another organisation.')
        return page['connections']

    def sources(self):
        """The source selections you bound in this project (every profile), each with its state and exact revision.
        Selections other members bound are not listed."""
        page = _checked(SourceSelectionsPage, self._post('sources', 'list', {}), 'source listing')
        return [Source(self, document) for document in page['selections']]

    def source(self, id):
        """The selection with this stable id (a name never matches); SourceNotFound when you have none with it."""
        if not isinstance(id, str) or not id: raise Refused('Give the source selection id (see client.sources()).')
        found = [s for s in self.sources() if s.id == id]
        if not found:
            raise _refuse(SourceNotFound, 'No source selection with this id is yours in this project.',
                          'List yours with client.sources(); a selection another member bound is not listed.', 'source-not-found')
        return found[0]
