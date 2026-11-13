"""E171 s1 C6: `ophiolite data holders` and `Client.holders()`: who holds which version, read whole over the pages of
exchange/holders, in plain words by default (Codex V1: "QGIS", "a script", "current", "2 versions behind") and as the
served ophiolite.held-copies/1 document with --json. The fake gateway serves the contract's member fixture in two pages.
Each test names the mutation it catches."""
import json
from importlib import resources

import httpx
import pytest

from ophiolite import Client, cli
from ophiolite.errors import PermissionRefused, VerificationFailed

SERVED = json.loads(resources.files('ophiolite').joinpath('contracts/exchange/v1/fixtures/valid/held-copies-member.json').read_text())
WORDS = ['Top horizon: a member in QGIS, 2 versions behind (stays on its version)',
         'Top horizon: you in a script, 1 version behind (follows the newest)',
         'Top horizon: a member in OpendTect, current (stays on its version)']


class Gateway:
    """exchange/holders over SERVED: two rows, then the third behind cursor `c1` (or `c1` again when `repeat`)."""
    def __init__(self, repeat=False, member=True):
        self.bodies, self.repeat, self.member = [], repeat, member

    def __call__(self, request):
        assert request.url.path == '/api/v1/projects/p-held/exchange/holders'
        body = json.loads(request.content); self.bodies.append(body)
        if not self.member: return httpx.Response(403, json={'error': 'Project access denied', 'code': 'PERMISSION_DENIED', 'message': 'Project access denied'})
        first = body.get('cursor') is None
        rows = SERVED['rows'][:2] if first else SERVED['rows'][2:]
        return httpx.Response(200, json=dict(SERVED, rows=rows, next='c1' if first or self.repeat else None))


def client(gateway):
    return Client('https://gateway.example', 'p-held', None, httpx.Client(transport=httpx.MockTransport(gateway)))


def run(gateway, *argv):
    return cli._holders(cli.parser().parse_args(['holders', '--project', 'p-held', '--item', 'horizon-top', *argv]), client(gateway))


def test_the_rows_are_said_in_plain_words(capsys):
    """Mutation: the application word printed as served -> 'application:qgis-plugin' in the words; the count without
    its plural -> '2 version behind'."""
    g = Gateway()
    run(g)
    out = capsys.readouterr().out
    assert out.splitlines() == WORDS
    assert not any(token in out for token in ('application:', 'r1', 'r2', 'r3', '7dd1510b9be8581e'))  # only --json carries them
    assert g.bodies == [{'project_id': 'p-held', 'item': 'horizon-top'}, {'project_id': 'p-held', 'item': 'horizon-top', 'cursor': 'c1'}]


def test_json_is_the_served_document_read_whole(capsys):
    """Mutation: only the first page kept -> two rows; `next` left as the last page's cursor -> it differs."""
    shown = run(Gateway(), '--json')
    assert json.loads(capsys.readouterr().out) == shown == SERVED


def test_a_project_you_are_not_in_exits_with_access():
    with pytest.raises(PermissionRefused) as refused: run(Gateway(member=False))
    assert cli.exit_code(refused.value) == cli.EXIT['access'] == 3


def test_a_repeated_cursor_stops_the_read():
    """Mutation: the seen-cursor guard removed -> the read runs to MAX_PAGES."""
    with pytest.raises(VerificationFailed): run(Gateway(repeat=True))


@pytest.mark.parametrize('row, words', [
    ({'person': {'shown': 'named', 'name': 'Ana'}, 'application': None, 'state': 'no-longer-readable', 'mode': None},
     'Top horizon: Ana in an application, can no longer read the version it holds'),
    ({'person': {'shown': 'named'}, 'application': 'application:petrel-bridge', 'state': 'current', 'mode': None},
     'Top horizon: a member in petrel-bridge, current')])
def test_a_named_member_without_a_name_and_other_words(row, words):
    """D9: a member without a usable name is `named` without `name`."""
    assert cli._held_words({'item': {'name': 'Top horizon'}, **row}) == words


def test_the_verb_is_in_the_data_group_and_async():
    parsed = cli.parser().parse_args(['data', 'holders', '--item', 'x', '--project', 'q'])
    assert (parsed.command, parsed.item, parsed.holders_project) == ('holders', 'x', 'q')
    from ophiolite.aio import AsyncClient
    assert callable(AsyncClient.holders) and callable(AsyncClient.holder_pages)
