"""E173 s0b C3: `upload_data(..., represents='horizon')` sends the mark on both transfer paths, only when given, so an
upload without it keeps its exact request (and retry fingerprint)."""
import base64
import json

import pytest

from ophiolite.errors import ValidationFailed
from ophiolite.publish import upload_metadata

COMMON = dict(filename='tops.csv', name='Top', attribution='Synthetic test', audience=['alice'], rights_confirmed=True, profile='points-csv/1')
PLAIN = {'project_id': 'p', 'command_id': 'plain', 'filename': 'tops.csv', 'name': 'Top', 'attribution': 'Synthetic test', 'audience': ['alice'],
         'rights_confirmed': True, 'well_notes': '', 'profile': 'points-csv/1'}


def header(extra):
    return json.loads(base64.b64decode(extra['X-Ophiolite-Upload']))


def test_the_mark_is_sent_only_when_given():
    """Mutation: `represents` always sent (the plain request gains a null)."""
    value, extra = upload_metadata('p', 'plain', **COMMON)
    assert value == PLAIN and header(extra) == PLAIN
    value, extra = upload_metadata('p', 'plain', represents='horizon', **COMMON)
    assert value == {**PLAIN, 'represents': 'horizon'} and header(extra) == {**PLAIN, 'represents': 'horizon'}


def test_a_word_outside_the_closed_list_is_refused_before_anything_is_sent():
    with pytest.raises(ValidationFailed): upload_metadata('p', 'plain', represents='fault', **COMMON)


def test_begin_carries_the_mark_and_nothing_else_new():
    """Mutation: `_upload_parts` not passing `represents` to begin."""
    from ophiolite.client import Client
    sent = []
    class Parts(Client):
        def __init__(self): pass
        def _post(self, area, operation, body, retry=False):
            sent.append((operation, body))
            return {'upload_id': 'u', 'state': 'checked'} if operation == 'begin' else {'asset_id': 'a'}
        def _transfer_parts(self, file, view): return view
    file = type('File', (), {'size': 2048})()
    for body in (PLAIN, {**PLAIN, 'represents': 'horizon'}):
        Parts()._upload_parts(file, '0' * 64, body)
    begins = [b for operation, b in sent if operation == 'begin']
    assert begins == [{'command_id': 'plain', 'filename': 'tops.csv', 'profile': 'points-csv/1', 'declared': {}, 'bytes': 2048, 'sha256': '0' * 64},
                      {'command_id': 'plain', 'filename': 'tops.csv', 'profile': 'points-csv/1', 'declared': {}, 'bytes': 2048, 'sha256': '0' * 64,
                       'represents': 'horizon'}]
    assert all('represents' not in b for operation, b in sent if operation == 'publish')
