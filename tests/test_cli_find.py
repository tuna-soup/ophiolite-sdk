"""E145 s3 C1 (P3, P4): `ophiolite data find` (E163's data group) prints the server's rows in its order; --json prints each page's answer, one per
line; --all follows the cursor. The client is the real SDK client on test_find's recording gateway."""
import contextlib
import io
import json

import pytest

from ophiolite import cli
from ophiolite.errors import Refused
from test_find import MEANING, WORDS, gateway


def run(client, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = cli._find(cli.parser().parse_args(['data', 'find', *argv]), client)
    return out.getvalue(), code


def test_the_table_is_the_answer_in_its_order_with_the_count_and_the_next_cursor():
    """P3. Mutation: sort the rows by name → the asset column differs from the answer's order."""
    answer = WORDS['q1-first-page']['answer']
    client, seen = gateway((200, answer))
    text, code = run(client, 'gamma ray', '--org', 'org-e145', '--limit', '3')
    lines = text.splitlines()
    assert code == 0 and lines[0].split() == ['PROJECT', 'KIND', 'NAME', 'WELL', 'SCORE', 'REVISION']
    assert [line.split()[-1] for line in lines[1:4]] == [r['revision'] for r in answer['results']]
    assert [r['name'] in line and r['project'] in line and '%.3f' % r['score'] in line for line, r in zip(lines[1:4], answer['results'])] == [True] * 3
    assert lines[4:] == ['matched 56', 'more: --cursor opaque-cursor-1 (or --all)']
    assert seen[0][2] == {'organization_id': 'org-e145', 'text': 'gamma ray', 'limit': 3}


def test_json_with_all_prints_every_page_as_received_one_per_line():
    """P3. Mutation: print only the last page → one line, not two."""
    first, last = WORDS['q1-first-page']['answer'], WORDS['last-page']['answer']
    client, seen = gateway((200, first), (200, last))
    text, code = run(client, 'gamma ray', '--org', 'org-e145', '--limit', '3', '--all', '--json')
    assert code == 0 and [json.loads(line) for line in text.splitlines()] == [first, last]
    assert [s[2].get('cursor') for s in seen] == [None, 'opaque-cursor-1']


def test_the_filters_and_by_meaning_reach_the_request_and_the_not_searched_count_is_printed():
    answer = MEANING['meaning-first-page']['answer']
    client, seen = gateway((200, answer))
    text, _ = run(client, 'shale near the top', '--org', 'org-e145', '--by-meaning', '--kind', 'las2/1', '--project', 'proj-a', '--project', 'proj-b',
                  '--well', '34/10-A-3', '--bbox', '2,60,3,61', '--since', '2026-03-01T00:00:00Z', '--published-by', 'alice', '--include-archived', '--limit', '3')
    assert seen[0][2] == {'organization_id': 'org-e145', 'text': 'shale near the top', 'method': 'embedding', 'kinds': ['las2/1'], 'projects': ['proj-a', 'proj-b'],
                          'well': '34/10-A-3', 'bbox': {'minx': 2.0, 'miny': 60.0, 'maxx': 3.0, 'maxy': 61.0}, 'since': '2026-03-01T00:00:00Z',
                          'published_by': 'alice', 'include_archived': True, 'limit': 3}
    assert '%d not searched by meaning' % answer['not_searched_by_meaning'] in text.splitlines()


def test_no_match_says_so_and_a_filter_alone_is_a_question():
    client, seen = gateway((200, WORDS['q6-empty']['answer']), (200, WORDS['filter-only']['answer']))
    assert run(client, 'obsolete', '--org', 'org-e145')[0].splitlines() == ['No version matches.', 'matched 0']
    run(client, '--org', 'org-e145', '--kind', 'well-tops-csv/1')
    assert seen[1][2] == {'organization_id': 'org-e145', 'kinds': ['well-tops-csv/1'], 'limit': 20}


@pytest.mark.parametrize('bbox', ['2,60,3', '2,60,3,x', '2,60,3,61,5'])
def test_a_box_that_is_not_four_numbers_is_refused_before_anything_is_sent(bbox):
    client, seen = gateway()
    with pytest.raises(Refused) as refused: run(client, 'gamma', '--org', 'org-e145', '--bbox', bbox)
    assert refused.value.message == 'Give --bbox as four numbers: MINX,MINY,MAXX,MAXY.' and seen == []
