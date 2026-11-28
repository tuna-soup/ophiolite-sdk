"""E217 s0 C1 (acceptance 4 and 5): catalogue items stay the plain dicts the server sent, with or without type annotations.

The answer is literal and served over two pages; the expected items are written out here, never derived from the client.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from ophiolite import Client, Credential
from ophiolite.testing import synthetic_server

PREFIX = '/api/v1/projects/p/scientific-assets'
FIRST = {'asset_id': 'a1', 'revision': 'r-a1', 'name': 'Main log', 'origin': 'retained-capture', 'authority': 'fixture',
         'profile': 'las2/1', 'custodian': 'ophiolite:managed', 'curves': ['GR', 'RHOB'], 'sample_count': 500,
         'allowed_operations': ['read', 'export', 'use-as-input'],
         'display': {'type': 'Well log', 'source': 'Uploaded file', 'status': 'Ready'}}
SECOND = {'asset_id': 'a2', 'revision': 'r-a2', 'name': 'Tops', 'origin': 'retained-capture', 'authority': 'fixture',
          'profile': 'well-tops-csv/1', 'custodian': 'ophiolite:managed', 'curves': [], 'sample_count': None,
          'allowed_operations': ['read'], 'osdu_kind': None, 'osdu_kind_reason': 'no OSDU kind for this profile'}


@pytest.fixture
def client():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        inner = server.handler
        def handler(method, path, body, headers):
            parts = urlsplit(path)
            if method == 'GET' and parts.path == PREFIX:
                second = parse_qs(parts.query).get('cursor') == ['next']
                return 200, {'items': [SECOND] if second else [FIRST], 'next_cursor': None if second else 'next'}
            return inner(method, path, body, headers)
        server.handler = handler
        yield alice


def test_assets_yields_the_served_dicts_unchanged(client):
    items = list(client.assets())
    assert items == [FIRST, SECOND]
    assert [type(item) for item in items] == [dict, dict]


def test_find_log_returns_the_served_dict_unchanged(client):
    item = client.find_log(curves=['GR'])
    assert item == FIRST and type(item) is dict
