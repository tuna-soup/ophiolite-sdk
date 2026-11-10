"""E145 s3 C1 (P1, P2, P4): client.find and client.find_all are thin callers of organizations/search. The answers are the
contract's own fixtures (ophiolite/contracts/search/v1/fixtures), served by a MockTransport that records each request."""
import json
from pathlib import Path

import httpx
import pytest

from ophiolite import Client, cli
from ophiolite.auth import Credential
from ophiolite.errors import Busy, PermissionRefused, Refused

URL = 'http://localhost:8765'
FIXTURES = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'search' / 'v1' / 'fixtures'
WORDS = {v['name']: v for v in json.loads((FIXTURES / 'answers.json').read_text())['valid']}
MEANING = {v['name']: v for v in json.loads((FIXTURES / 'answers-meaning.json').read_text())['valid']}
NO_MODEL = 'Search by words, or by meaning when the deployment has a local model'  # E14's sentence (org_search_index.NO_MODEL)


def gateway(*answers):
    """Each request gets the next (status, body); every request is recorded as (path, authorization, body)."""
    seen, left = [], list(answers)
    def handle(request):
        seen.append((request.url.path, request.headers.get('authorization'), json.loads(request.content)))
        status, body = left.pop(0)
        return httpx.Response(status, json=body)
    return Client(URL, 'test', Credential.bearer('oph_key_example'), httpx.Client(transport=httpx.MockTransport(handle))), seen


def test_find_sends_exactly_the_given_fields_to_the_organisation_route_and_parses_the_answer():
    """P1. Mutation: send include_archived always, or a project_id → the recorded body differs."""
    client, seen = gateway((200, WORDS['q1-first-page']['answer']), (200, WORDS['filter-only']['answer']), (200, WORDS['ties']['answer']))
    page = client.find('org-e145', 'gamma ray', limit=3)
    assert page.schema_ == 'ophiolite.search/2' and page.matched == 56 and page.next_cursor == 'opaque-cursor-1'
    assert [r.asset for r in page.results] == [r['asset'] for r in WORDS['q1-first-page']['answer']['results']]
    client.find('org-e145', kinds=('well-tops-csv/1', 'deviation-csv/1'))
    client.find('org-e145', 'caliper', include_archived=True, bbox={'minx': 2.0, 'miny': 60.0, 'maxx': 3.0, 'maxy': 61.0}, since='2026-03-01T00:00:00Z')
    assert [s[0] for s in seen] == ['/api/v1/organizations/search'] * 3 and {s[1] for s in seen} == {'Bearer oph_key_example'}
    assert [s[2] for s in seen] == [
        {'organization_id': 'org-e145', 'text': 'gamma ray', 'limit': 3},
        {'organization_id': 'org-e145', 'kinds': ['well-tops-csv/1', 'deviation-csv/1'], 'limit': 20},
        {'organization_id': 'org-e145', 'text': 'caliper', 'bbox': {'minx': 2.0, 'miny': 60.0, 'maxx': 3.0, 'maxy': 61.0}, 'since': '2026-03-01T00:00:00Z',
         'include_archived': True, 'limit': 20}]


def test_an_answer_by_meaning_is_the_by_meaning_model_with_its_not_searched_count():
    client, seen = gateway((200, MEANING['meaning-first-page']['answer']))
    page = client.find('org-e145', 'shale near the top', method='embedding', limit=3)
    assert page.schema_ == 'ophiolite.search/3' and page.method == 'embedding' and page.results[0].why == []
    assert page.not_searched_by_meaning == MEANING['meaning-first-page']['answer']['not_searched_by_meaning']
    assert seen[0][2] == {'organization_id': 'org-e145', 'text': 'shale near the top', 'method': 'embedding', 'limit': 3}


def test_find_all_follows_the_cursor_to_its_end_yielding_each_row_once_in_order():
    """P2. Mutation: stop after the first page → 3 rows, not 5."""
    first, last = WORDS['q1-first-page']['answer'], WORDS['last-page']['answer']
    client, seen = gateway((200, first), (200, last))
    rows = client.find_all('org-e145', 'gamma ray', limit=3)
    assert next(rows).asset == first['results'][0]['asset'] and len(seen) == 1  # one page held at a time
    rest = list(rows)
    assert [r.asset for r in rest] == [r['asset'] for r in first['results'][1:] + last['results']]
    assert [s[2].get('cursor') for s in seen] == [None, 'opaque-cursor-1'] and {s[2]['limit'] for s in seen} == {3}


@pytest.mark.parametrize('status, body, kind, words, exit', [
    (400, {'code': 'unknown-filter', 'message': 'organizations/search has no filter "colour".', 'reason': 'unknown-filter'}, Refused,
     'organizations/search has no filter "colour".', 1),
    (503, {'code': 'embedding-unavailable', 'message': NO_MODEL}, Busy, NO_MODEL, 5),
    (403, {'code': 'PERMISSION_DENIED', 'message': 'This credential cannot read the organisation.'}, PermissionRefused,
     'This credential cannot read the organisation.', 3)])
def test_a_refusal_carries_the_servers_sentence_and_the_documented_exit_code(status, body, kind, words, exit):
    """P4. Mutation: drop the re-raise in find → the 503 says "The service is busy." and the test fails."""
    client, _ = gateway((status, body))
    with pytest.raises(kind) as refused: client.find('org-e145', 'gamma ray', method='embedding' if status == 503 else None)
    assert refused.value.message == words and refused.value.status == status and cli.exit_code(refused.value) == exit
