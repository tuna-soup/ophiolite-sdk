"""E42a: wells from an approved table in one journey — import a copy.

`client.well_imports()` previews an import of a table you may read through an approved database connection (nothing
is kept), starts it (the accepted rows are kept as a copy shared with the audience you name, and every row is planned),
runs it step by step to the end, and reads, lists or cancels imports. Every answer is checked against its documented
shape before it is returned.

An import is finished only when the server has read its wells back through the project's wells and its map feed; an
interrupted import resumes where its committed rows end, from any process, with `run(id)`. Each skipped row comes with
its reason in words (`words(row)`); identifiers and column names are the table's own.
"""
import uuid

from .errors import Refused, VerificationFailed
from .models.api import WellImport, WellImportsListAnswer, WellImportsPreviewAnswer

FINAL = ('complete', 'complete-with-skipped', 'cancelled')
PAUSED = ('resumable', 'needs-review')
CODES = {'id-missing': 'it has no identifier', 'id-repeated': 'its identifier appears on more than one row', 'name-missing': 'it has no name',
         'coordinate-missing': 'a coordinate is missing', 'not-numeric': 'a coordinate is not a number', 'non-finite': 'a coordinate is not a finite number',
         'longitude-out-of-range': 'the longitude is outside -180 to 180', 'latitude-out-of-range': 'the latitude is outside -90 to 90',
         'name-too-long': 'the name is longer than 160 characters', 'name-not-text': 'the name is not text',
         'identifier-not-accepted': 'the identifier is not one a well can have', 'identifier-in-use': 'its identifier is used by a well you cannot read',
         'no-longer-visible': 'the well it matched is no longer visible to you'}


def _checked(model, answer, what):
    from pydantic import ValidationError
    try: model.model_validate(answer)
    except (ValidationError, ValueError, TypeError): raise VerificationFailed('The %s answered outside its documented shape.' % what) from None
    return answer


def words(row):
    """Why a row was skipped, in words: the server's own sentence when it gave one, otherwise each code's words."""
    if row.get('reason'): return row['reason']
    said = [CODES.get(code, code) for code in row.get('codes', [])]
    return ('; '.join(said) or 'skipped').capitalize()


class WellImports:
    def __init__(self, client):
        self.client = client

    def _call(self, operation, body, model):
        # Every operation is safe to repeat after a lost answer: start by its command id, step by its lease and committed rows.
        return _checked(model, self.client._post('well-imports', operation, body, retry=True), 'well import ' + operation)

    def preview(self, connection_id, key, mapping):
        """What a start would do with this table and mapping (counts, skipped rows, possible duplicates, wells already
        here); nothing is kept."""
        return self._call('preview', {'connection_id': connection_id, 'key': key, 'mapping': mapping}, WellImportsPreviewAnswer)

    def start(self, connection_id, key, mapping, *, preview_digest, audience=(), command_id=None):
        """Keep the accepted rows and plan every row; the same command id returns the same import. Run it with `run`."""
        if not preview_digest: raise Refused('Start the import you reviewed: give the preview_digest of its preview.')
        body = {'connection_id': connection_id, 'key': key, 'mapping': mapping, 'preview_digest': preview_digest, 'audience': list(audience),
                'command_id': command_id or uuid.uuid4().hex}
        return self._call('start', body, WellImport)

    def step(self, ident):
        return self._call('step', {'id': ident}, WellImport)

    def status(self, ident):
        return self._call('status', {'id': ident}, WellImport)

    def list(self):
        return self._call('list', {}, WellImportsListAnswer)['imports']

    def cancel(self, ident):
        """Stop an unfinished import (any project administrator); the wells already created stay."""
        return self._call('cancel', {'id': ident}, WellImport)

    def run(self, ident, *, progress=None, max_steps=100000):
        """Step until the import is finished, cancelled or paused, and return its last answer. `progress(answer)` is
        called after every step. Safe to call again after an interruption, from any process."""
        answer = self.step(ident)
        for _ in range(max_steps):
            if progress: progress(answer)
            if answer['state'] in FINAL or answer['state'] in PAUSED: return answer
            answer = self.step(ident)
        raise VerificationFailed('The import did not finish in %d steps; run it again to continue.' % max_steps)
