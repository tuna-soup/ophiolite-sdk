"""E177 s1 C4 (strategy D-8; Codex F7, F9, F12, F20, F21): `ophiolite results affected` and `Client.affected()`, over
a fake gateway serving the contract's fixtures. The default output is plain words (no id, revision or code); --json is
the list of served pages; the whole answer follows D-8's table key by key over pages whose counts, `restricted` and
`complete` differ. Each test names the mutation it catches."""
import json
from importlib import resources

import httpx
import pytest

from ophiolite import Client, cli
from ophiolite.errors import PermissionRefused, VerificationFailed

VALID = resources.files('ophiolite').joinpath('contracts/changes/v1/fixtures/valid')
AFTER = json.loads(VALID.joinpath('affected-after-tops-v2.json').read_text())
WORDS = ['Horizon Top rests on version 1 (1 step)',
         'Residual Top rests on version 1 (1 step)',
         'Accepted as Residual within 2 m on version 1; version 2 exists',
         'Tops North: you in qgis, 1 version behind (stays on its version)',
         'Tops North: Ben in a script, 1 version behind',
         '2 results, 1 accepted outcome, 2 held copies',
         '1 item in this project has no recorded inputs']


class Gateway:
    """changes/affected over PAGES, one per request: the first without a cursor, then the cursor each page names."""
    def __init__(self, pages, member=True):
        self.pages, self.bodies, self.member = list(pages), [], member

    def __call__(self, request):
        assert request.url.path == '/api/v1/projects/%s/changes/affected' % self.pages[0]['project']
        body = json.loads(request.content); self.bodies.append(body)
        if not self.member: return httpx.Response(403, json={'error': 'Project access denied', 'code': 'PERMISSION_DENIED', 'message': 'Project access denied'})
        return httpx.Response(200, json=self.pages[len(self.bodies) - 1])


def client(gateway, project='p-affected'):
    return Client('https://gateway.example', project, None, httpx.Client(transport=httpx.MockTransport(gateway)))


def run(gateway, *argv):
    return cli._affected(cli.parser().parse_args(['affected', 'tops-north', *argv]), client(gateway))


def test_the_after_tops_v2_answer_in_plain_words(capsys):
    """Mutation: the distance printed without its plural rule -> '1 steps'; the outcome id in place of its label ->
    'residual-within-2m' in the words."""
    g = Gateway([AFTER])
    run(g)
    out = capsys.readouterr().out
    assert out.splitlines() == WORDS
    assert not any(token in out for token in ('rev-', 'residual-within-2m', 'check-', 'tops-north', '1b1551c5c1086015', 'application:'))
    assert g.bodies == [{'project_id': 'p-affected', 'asset_id': 'tops-north', 'against': 'head'}]


def test_next_asks_against_next_and_json_is_the_served_pages(capsys):
    g = Gateway([dict(AFTER, against='next')])
    shown = run(g, '--next', '--json')
    assert json.loads(capsys.readouterr().out) == shown == [dict(AFTER, against='next')]
    assert g.bodies[0]['against'] == 'next'


def test_restricted_and_the_read_limit_are_said(capsys):
    """Mutation: either closing line dropped."""
    run(Gateway([dict(AFTER, restricted=True, complete=False)]))
    assert capsys.readouterr().out.splitlines()[-2:] == ['Some results you cannot open are not listed.', 'At least: this answer reached its read limit.']


def test_an_item_you_may_not_open_is_said_once(capsys):
    empty = dict(AFTER, item=None, rows=[], counts={'results': 0, 'acceptances': 0, 'held': 0})
    run(Gateway([empty]))
    assert capsys.readouterr().out.splitlines() == ['No item you may open has this id.']


def test_a_page_naming_another_item_or_a_repeated_cursor_stops_the_read():
    """Mutations: the item check removed; the seen-cursor guard removed (the read runs to MAX_PAGES)."""
    with pytest.raises(VerificationFailed): run(Gateway([dict(AFTER, asked='horizon-top')]))
    with pytest.raises(VerificationFailed): run(Gateway([dict(AFTER, against='next')]))
    looping = [dict(AFTER, next='c1')] * 3
    with pytest.raises(VerificationFailed): run(Gateway(looping))


def result(n):
    return {'kind': 'result', 'item': {'asset_id': 'item-%04d' % n, 'name': 'Result %d' % n, 'kind': 'grids'},
            'head': {'revision': 'rev-%d' % n, 'version': 1}, 'distance': 1, 'rests_on': {'revision': 'rev-tops-1', 'version': 1}}


def test_the_whole_answer_follows_the_table_key_by_key_over_pages_that_change():
    """F7, F12: 200 + 200 + 101 rows; counts grow between pages, the second page is restricted, the third incomplete.
    Mutations: counts from the first page; `restricted` from the last page only; `complete` from the last page only;
    rows of the last page only."""
    def page(rows, n, results, restricted, complete, after):
        return dict(AFTER, rows=[result(i) for i in rows], counts={'results': results, 'acceptances': 0, 'held': 0}, as_of='2026-11-19T09:3%d:00Z' % n,
                    without_inputs=n, restricted=restricted, complete=complete, next=after)
    pages = [page(range(0, 200), 1, 500, False, True, 'c1'), page(range(200, 400), 2, 501, True, True, 'c2'),
             page(range(400, 501), 3, 501, False, False, None)]
    g = Gateway(pages)
    whole = client(g).affected('tops-north')
    assert whole == {'rows': [result(i) for i in range(501)], 'item': AFTER['item'], 'as_of': '2026-11-19T09:33:00Z',
                     'counts': {'results': 501, 'acceptances': 0, 'held': 0}, 'without_inputs': 3, 'restricted': True,
                     'complete': False, 'pages': 3}
    assert [b.get('cursor') for b in g.bodies] == [None, 'c1', 'c2']
    assert Client.affected.__doc__ and 'not an ophiolite.affected/1 document' in ' '.join(Client.affected.__doc__.split())


def test_a_project_you_are_not_in_exits_with_access():
    with pytest.raises(PermissionRefused) as refused: run(Gateway([AFTER], member=False))
    assert cli.exit_code(refused.value) == cli.EXIT['access'] == 3


def test_the_verb_is_in_the_results_group_and_async():
    parsed = cli.parser().parse_args(['results', 'affected', 'x', '--next'])
    assert (parsed.command, parsed.item, parsed.next) == ('affected', 'x', True)
    from ophiolite.aio import AsyncClient
    assert callable(AsyncClient.affected) and callable(AsyncClient.affected_pages)
