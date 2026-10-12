"""E66 C9: `Entity.assets(include_wellbores=True)` reads a well's data together with its readable wellbores' in one
paged read (`entities/assets` with `include_parts`); the default call sends the request it sent before, byte for byte."""
import json

import httpx

from ophiolite import Client, Credential

URL = 'https://gateway.example'
WELL = {'entity_id': 'w1', 'kind': 'well', 'name': 'HON-GT-01', 'identity': {'provisional': False, 'authority': 'nlog', 'key': 'HON-GT-01'}, 'generation': 1,
        'parts': [{'entity_id': 'b1', 'kind': 'wellbore', 'name': 'HON-GT-01 main'}, {'entity_id': 'b2', 'kind': 'wellbore', 'name': 'HON-GT-01-S1'}]}
# The association table of Evidence 7 for HON-GT-01: its location, four files on main, three on S1 (8 in all).
OWNERS = [('w1', 'well', 'HON-GT-01')] + [('b1', 'wellbore', 'HON-GT-01 main')] * 4 + [('b2', 'wellbore', 'HON-GT-01-S1')] * 3


def item(n, owner, parts):
    return {'asset_id': 'a%d' % n, 'revision': '%064x' % n, 'profile': 'las2/1', 'name': 'f%d' % n,
            'association': {'assertion_id': '%04d' % n, 'predicate': 'of-entity', 'evidence': {}, 'asserted_by': 'alice', 'asserted_at': '2026-10-11T00:00:00Z'},
            **({'entity': {'entity_id': owner[0], 'kind': owner[1], 'name': owner[2]}} if parts else {})}


def client():
    sent = []
    def handle(request):
        body = json.loads(request.content); sent.append((request.url.path.rsplit('/', 2)[-2:], request.content))
        if request.url.path.endswith('/entities/get'): return httpx.Response(200, json=WELL)
        parts = body.get('include_parts') is True
        rows = [item(n, o, parts) for n, o in enumerate(OWNERS if parts else OWNERS[:1])]
        start = int(body.get('cursor') or 0); page = rows[start:start + 5]  # the server pages at 5 here, so two pages are read
        return httpx.Response(200, json={'schema': 'ophiolite.entity-assets/1', 'entity': {'entity_id': 'w1', 'kind': 'well', 'name': 'HON-GT-01'}, 'items': page,
                                         'next_cursor': str(start + 5) if start + 5 < len(rows) else None})
    return Client(URL, 'p', Credential.bearer('t'), httpx.Client(transport=httpx.MockTransport(handle))), sent


def test_a_well_with_its_wellbores_reads_eight_items_each_naming_its_entity():
    c, sent = client()
    items = c.entity('w1').assets(include_wellbores=True)
    assert len(items) == 8
    assert [i['entity']['name'] for i in items] == ['HON-GT-01'] + ['HON-GT-01 main'] * 4 + ['HON-GT-01-S1'] * 3
    reads = [json.loads(raw) for path, raw in sent if path == ['entities', 'assets']]
    assert [r.get('include_parts') for r in reads] == [True, True] and [r.get('cursor') for r in reads] == [None, '5']


def test_the_default_call_sends_the_same_bytes_as_before():
    c, sent = client()
    items = c.entity('w1').assets()
    assert [i['asset_id'] for i in items] == ['a0'] and 'entity' not in items[0]
    assert [raw for path, raw in sent if path == ['entities', 'assets']] == [b'{"project_id":"p","entity_id":"w1","limit":100}']
    c, sent = client()
    c.entity('w1').assets(profile='las2/1')
    assert [raw for path, raw in sent if path == ['entities', 'assets']] == [b'{"project_id":"p","entity_id":"w1","profile":"las2/1","limit":100}']


def test_the_synthetic_server_files_its_log_on_the_wellbore():
    """The gallery's synthetic mode: Synthetic well 1's log is on its wellbore, so only include_wellbores finds it."""
    from ophiolite.testing import synthetic_server
    with synthetic_server() as server:
        c = Client(server.url, 'p', Credential.bearer('oph_api_alice'))
        well = c.entity('well-synthetic-1')
        assert [p['name'] for p in well.document['parts']] == ['Synthetic well 1 main'] and well.assets() == []
        assert [(i['name'], i['entity']['name']) for i in well.assets(include_wellbores=True)] == [('Synthetic gamma ray', 'Synthetic well 1 main')]
        assert c.entity('well-synthetic-2').assets(include_wellbores=True) == []
