"""E50a: read a connected source from Python.

`client.sources()` lists the source selections you bound in this project (every profile); `client.source(id)` picks one
by its stable id. `describe()` and `read()` are for SQL well-location tables (sql-wells/1) only in this release; any
other profile is refused before a request is sent. Both call sources/export once — `describe()` costs one full read —
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

from .errors import (Refused, SourceChecksumMismatch, SourceNotFound, SourceNotSupported, SourceRevisionDiffers, VerificationFailed,
                     SOURCE_GUIDE)
from .models.api import OrgConnectionsPage, SourceExportAnswer, SourceSelectionsPage

SUPPORTED = 'sql-wells/1'
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
        if self.profile != SUPPORTED:
            raise _refuse(SourceNotSupported, 'Reading %s sources is not supported for this kind of source yet; only SQL well-location tables (%s) are.'
                          % (self.profile, SUPPORTED), 'List it with client.sources(); read SQL well-location tables with source.read().', 'source-not-supported')
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

    def read(self, expect_revision=None):
        """Every row of this SQL well-location table at the revision the server holds, verified (see the module notes).
        `expect_revision`: refuse (SourceRevisionDiffers, no rows) unless that is the revision returned."""
        manifest, data, digest = self._export(expect_revision)
        return SourceSnapshot(self, manifest, data, digest)

    def describe(self, expect_revision=None):
        """What this table holds — columns and types, the mapping, CRS, row count, nulls — without keeping its rows.
        It verifies like read() and costs one full read."""
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

class SourceSnapshot:
    """One verified read of a source table. Never a Well: `rows` are the mapped rows (well_id, name, operator, x, y,
    depth, metadata) and `original` the source rows with every original column, as the server returned them."""

    def __init__(self, source, manifest, data, digest):
        schema, original, rows, mapping = verified_table(data)
        self.id, self.name, self.profile = source.id, source.name, manifest['reference']['profile']
        self.authority, self.key = manifest['reference']['authority'], manifest['reference']['key']
        self.revision, self.sha256, self.bytes = manifest['reference']['revision'], digest, manifest['bytes']
        self.manifest, self.mapping, self.crs = manifest, mapping, mapping.get('crs')
        self.schema, self.rows, self.original = schema, rows, original
        self.columns = [c['name'] for c in schema]

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return 'SourceSnapshot(%r, %d rows, %s, revision %s)' % (self.name, len(self.rows), self.crs, self.revision[:12])

    def mapped_columns(self):
        """The mapped view's columns: unmapped optional ones (depth, operator) are left out, so a location-only table has
        no all-null depth column."""
        fields = self.mapping.get('fields') or {}
        return [c for c in MAPPED if c not in OPTIONAL or fields.get(c)]

    def records(self, original=False):
        """Plain rows (no pandas): the mapped view, or with `original` every source column exactly as returned."""
        if original:
            return [{c: row.get(c) for c in self.columns} for row in self.original]
        columns = self.mapped_columns()
        return [{c: row.get(c) for c in columns} for row in self.rows]

    def to_frame(self, original=False):
        """A DataFrame of the rows. Mapped view: x, y and depth as nullable floats. `original=True`: every source column
        with its values unchanged (object columns: large integers, decimal and date strings are kept as given). The
        declared CRS, revision, sha256 and profile are in `frame.attrs`; coordinates are never converted."""
        try: import pandas as pd
        except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
        columns = self.columns if original else self.mapped_columns()
        frame = pd.DataFrame(self.records(original), columns=columns, dtype=object)
        if not original:
            for column in ('x', 'y', 'depth'):
                if column in frame: frame[column] = frame[column].astype('Float64')
            for column in ('well_id', 'name', 'operator'):
                if column in frame: frame[column] = frame[column].astype('string')
        frame.attrs.update({'crs': self.crs, 'revision': self.revision, 'sha256': self.sha256, 'profile': self.profile, 'source_id': self.id})
        return frame


class SourceDescription:
    """A source table's shape at one verified revision: columns with their types, the reviewed mapping, the declared
    CRS, the row count and nulls per mapped field. No rows are kept."""

    def __init__(self, snapshot):
        self.id, self.name, self.profile = snapshot.id, snapshot.name, snapshot.profile
        self.revision, self.sha256, self.bytes, self.crs = snapshot.revision, snapshot.sha256, snapshot.bytes, snapshot.crs
        self.columns = [dict(c) for c in snapshot.schema]
        self.mapping, self.row_count = snapshot.mapping, len(snapshot.rows)
        self.mapped_columns = snapshot.mapped_columns()
        metadata = snapshot.manifest.get('metadata') or {}
        self.null_counts, self.unresolved = metadata.get('null_counts'), metadata.get('unresolved', [])

    def to_dict(self):
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
