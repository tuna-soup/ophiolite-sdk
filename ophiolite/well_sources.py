"""E50c: from a project well to the source row it was located from.

A well imported from a SQL well table (E42a) is located by a row of the copy the import kept: its location names
`source = {asset_id, revision, profile: sql-wells/1, row}`. `Wells.with_source(columns)` reads those kept copies under
their own permission check (the package routes: the caller must be in the package audience and the connection's
current audience) and returns one row per well, marked:

- `joined`: the row's original columns are filled;
- `no origin`: no source row you may read locates this well (none was recorded, or the server withholds one you may
  not read: a location is shown only from a source you may read, so the two look the same);
- `not readable`: the well names a kept copy that cannot be read now (withdrawn, under review, or refused); the reason
  says which.

Every copy is checked before a value is used: sha256 of the kept bytes equals the revision the wells name
(SourceChecksumMismatch otherwise, nothing is returned), and the table passes E50a's checks. A reference to a row the
verified copy does not hold raises VerificationFailed. No well is dropped or repeated.
"""
import base64
import binascii
import hashlib
import io
import json
import zipfile

from .errors import OphioliteError, Refused, SourceChecksumMismatch, VerificationFailed
from .models.api import ReleasesDownloadAnswer, ReleasesListAnswer
from .sources import SUPPORTED, _checked, _refuse, verified_table

JOINED, NO_ORIGIN, NOT_READABLE = 'joined', 'no origin', 'not readable'
NO_ORIGIN_REASON = 'No source row you may read locates this well.'
STATE_REASONS = {'withdrawn': 'The kept copy was withdrawn.', 'candidate': 'The kept copy is under review; read it again after it is approved.'}


def capture_id(release, ordinal):
    """The asset id the server gives the copy at `ordinal` in package `release` (canonical JSON, then sha256)."""
    return hashlib.sha256(json.dumps(['capture', release, ordinal], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _mismatch(message):
    return _refuse(SourceChecksumMismatch, message, 'Read it again; if it repeats, report the request.', 'source-checksum-mismatch')


class KeptCopies:
    """The kept copies of one call: the packages are listed once, and each copy is downloaded and verified once."""

    def __init__(self, client):
        self.client, self.listed, self.tables = client, None, {}

    def captures(self):
        if self.listed is None:
            answer = _checked(ReleasesListAnswer, self.client._post('releases', 'list', {}, retry=True), 'package listing')
            self.listed = {capture_id(item['id'], i): (item, i) for item in answer['items'] for i in range(item['assets'])}
        return self.listed

    def table(self, asset_id, revision):
        """({row key: original row}, original column names), or the reason the copy cannot be read now."""
        if (asset_id, revision) not in self.tables: self.tables[(asset_id, revision)] = self._read(asset_id, revision)
        return self.tables[(asset_id, revision)]

    def _read(self, asset_id, revision):
        found = self.captures().get(asset_id)
        if found is None: return 'The kept copy is not in a package you can open.'
        item, ordinal = found
        if item['state'] in STATE_REASONS: return STATE_REASONS[item['state']]
        operation = {'snapshot': 'download-snapshot', 'approved': 'download'}.get(item['state'])
        if operation is None: return 'The kept copy is in a state that cannot be read (%s).' % item['state'][:40]
        try: answer = _checked(ReleasesDownloadAnswer, self.client._post('releases', operation, {'id': item['id']}, retry=True), 'package download')
        except OphioliteError as error:
            if error.status == 404: return error.server_message or error.message  # no longer yours to read
            if error.status == 409:  # withdrawn or sent for review since the listing; integrity and capacity are raised
                state = self.client._post('releases', 'get', {'id': item['id']}, retry=True).get('state')
                if state in STATE_REASONS: return STATE_REASONS[state]
            raise
        try:
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(answer['payload_base64'], validate=True))) as bundle:
                payload = bundle.read('assets/%02d.json' % ordinal)
        except (binascii.Error, ValueError, KeyError, zipfile.BadZipFile): raise _mismatch('The kept copy could not be decoded.') from None
        if hashlib.sha256(payload).hexdigest() != revision: raise _mismatch('The kept copy does not match the revision its wells name.')
        try: data = json.loads(payload)
        except ValueError: raise VerificationFailed('The kept copy is not the documented table.') from None
        schema, original, rows, _ = verified_table(data)
        return {r['well_id']: o for r, o in zip(rows, original)}, [c['name'] for c in schema]


def with_source(wells, client, columns=None):
    """The wells' to_frame() with source_state, source_reason and one `source.<name>` column per original column asked
    for (None: every original column of the copies read, in the order first read)."""
    try: import pandas as pd
    except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
    if columns is not None and (isinstance(columns, str) or not all(isinstance(c, str) for c in columns)):
        raise Refused('Give columns as a list of original column names.')
    copies, marks = KeptCopies(client), []
    for well in wells:
        source = (well.location or {}).get('source') or {}
        if source.get('profile') != SUPPORTED or not source.get('row'):
            marks.append((NO_ORIGIN, NO_ORIGIN_REASON, None)); continue
        got = copies.table(source['asset_id'], source['revision'])
        if isinstance(got, str):
            marks.append((NOT_READABLE, got, None)); continue
        rows, _ = got
        if source['row'] not in rows:
            raise VerificationFailed('The kept copy %s has no row %s; nothing was joined.' % (source['revision'][:12], source['row'][:40]))
        marks.append((JOINED, None, rows[source['row']]))
    available = []
    for got in copies.tables.values():
        if not isinstance(got, str): available += [c for c in got[1] if c not in available]
    if columns is None: wanted = available
    else:
        wanted = list(dict.fromkeys(columns))
        missing = [c for c in wanted if c not in available]
        # Refused only when every referenced copy was read, so the column is known to be absent; otherwise it stays, missing.
        if missing and available and NOT_READABLE not in (m[0] for m in marks):
            raise Refused('No source table read here has the column %s; it has: %s.' % (', '.join(missing), ', '.join(available)))
    frame = wells.to_frame()
    frame['source_state'] = pd.Series([m[0] for m in marks], dtype='string', index=frame.index)
    frame['source_reason'] = pd.Series([m[1] for m in marks], dtype='string', index=frame.index)
    for column in wanted:
        frame['source.' + column] = pd.Series([m[2].get(column) if m[2] is not None else None for m in marks], dtype=object, index=frame.index)
    return frame
