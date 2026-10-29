"""D-29: a map's revision number from the server is ASCII [0-9]+ (ruling of 25 Oct 2026). '²' passed `str.isdigit()` and
int() raised ValueError; '٣' was read as 3. Both are now no number: left out of a map's history, None on a map read."""
import base64
import hashlib
from types import SimpleNamespace

import pytest

from ophiolite.exchange import ClientTransport

DIGITS = ['²', '٣']


def transport(reply):
    t = ClientTransport(SimpleNamespace(url='https://o.example', project='p'))
    t._exact = lambda area, operation, body: reply(body)
    return t


@pytest.mark.parametrize('digit', DIGITS)
def test_a_map_history_keeps_only_ascii_revision_numbers(digit):
    t = transport(lambda body: {'revisions': [{'revision': '2'}, {'revision': digit}, {'revision': '1' + digit}, {'revision': 1}]})
    assert [r['number'] for r in t.history({'kind': 'external-scalar-map', 'asset_id': 'a'})] == [1, 2]


def exported(revision):
    raw, source = b'II*\x00tif', b'source'
    files = {'map.tif': hashlib.sha256(raw).hexdigest(), 'source.txt': hashlib.sha256(source).hexdigest()}
    return lambda body: {'asset': 'a', 'revision': revision, 'representation': 'source', 'reference': {'project_id': 'p', 'asset_id': 'a', 'revision': revision},
                         'raster': base64.b64encode(raw).decode(), 'source_text': source.decode(), 'manifest': {'files': files}}


@pytest.mark.parametrize('digit', DIGITS)
def test_a_map_read_names_no_number_for_a_non_ascii_revision(digit):
    assert transport(exported('3'))._map('a', '3', None)['number'] == 3
    assert transport(exported(digit))._map('a', digit, None)['number'] is None
