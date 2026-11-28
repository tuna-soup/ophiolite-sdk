"""adhoc-async-client-find (D133 item 4): every public name of Client is accounted for on AsyncClient. It is AsyncClient's
own (asynchronous), an inherited method that only returns its request (awaited as it is), or refused at once with a
TypeError naming Client. find, find_log and find_all are asynchronous. Each case runs over an httpx.MockTransport that
records every request; full parity is E218's."""
import ast
import asyncio
import inspect
import json
import textwrap
from pathlib import Path

import httpx
import pytest

from ophiolite import Client, cli
from ophiolite import aio
from ophiolite.aio import AsyncClient
from ophiolite.auth import Credential
from ophiolite.errors import Busy, PermissionRefused, Refused

URL = 'http://localhost:8765'
FIXTURES = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'search' / 'v1' / 'fixtures'
WORDS = {v['name']: v for v in json.loads((FIXTURES / 'answers.json').read_text())['valid']}
MEANING = {v['name']: v for v in json.loads((FIXTURES / 'answers-meaning.json').read_text())['valid']}

# Inherited methods whose every request is the value they return (directly, or through a wrapper that only rewords a
# refusal), so `await client.<name>(...)` already gives the answer.
PASS_THROUGH = {
    'accepted_results', 'ai_use', 'answer', 'attach_rights', 'check_compare', 'check_list', 'check_publish', 'check_publishers',
    'dependents', 'dissociate', 'grant_ai_use', 'grant_own_ai_use', 'lineage', 'outcome_declare', 'outcome_disable', 'outcome_enable',
    'outcome_evaluate', 'outcome_get', 'outcome_revise', 'outcome_states', 'outcome_withdraw', 'procedure_enable', 'procedure_get',
    'procedure_register', 'procedure_run_get', 'procedure_sandbox_enable', 'procedure_trust', 'procedure_verifications',
    'procedure_verify', 'procedure_withdraw', 'record_verdict', 'reference_cases_declare', 'reference_cases_get',
    'reference_cases_withdraw', 'reference_run_get', 'reference_run_list', 'reference_run_start', 'renew_rights', 'rights',
    'rule_results', 'search', 'story', 'tool_enable', 'tool_get', 'tool_register', 'tool_run_get', 'tool_sandbox_enable', 'tool_trust',
    'tool_verifications', 'tool_verify', 'tool_withdraw', 'try_output', 'verdicts', 'what_changed'}
# Wrapped in _in_its_words / _reported: awaited as they are, but a refusal is not reworded (E218).
PASS_THROUGH_WRAPPED = {'preview_change', 'remake', 'remake_save', 'procedure_prepare_again', 'tool_prepare_again'}
WRAPPERS = {'_in_its_words', '_reported'}
REFUSED = set(aio._SYNC_ONLY) | set(aio._SYNC_ONLY_PROPERTIES)
CONSTRUCTORS = {'from_configuration'}


def public_names():
    return {n for n in dir(Client) if not n.startswith('_')}


def own_names():
    """AsyncClient's own definitions, not counting the refusals."""
    return {n for n in public_names() if n in vars(AsyncClient) and n not in REFUSED}


def gateway(*answers):
    """Each request gets the next (status, body); every request is recorded as (method, path, body)."""
    seen, left = [], list(answers)
    def handle(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        status, body = left.pop(0)
        return httpx.Response(status, json=body)
    return AsyncClient(URL, 'p', Credential.bearer('oph_key_example'), httpx.AsyncClient(transport=httpx.MockTransport(handle))), seen


def run(coroutine):
    return asyncio.run(coroutine)


# ---- the lists are exact -------------------------------------------------------------------------------------------

def test_every_public_name_of_client_is_accounted_for_once():
    """Mutation: a new public Client method with no entry, or a name in two lists → this fails and names it."""
    lists = [own_names(), PASS_THROUGH, PASS_THROUGH_WRAPPED, REFUSED, CONSTRUCTORS]
    assert set().union(*lists) == public_names(), sorted(public_names() - set().union(*lists))
    assert sum(len(x) for x in lists) == len(public_names())
    assert {'find', 'find_log', 'find_all'} <= own_names()


def _source(name):
    found = inspect.getattr_static(Client, name)
    function = found.fget if isinstance(found, property) else found
    tree = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    return tree, parents


ASYNC_ON_THIS_CLIENT = {n for n, v in vars(AsyncClient).items() if inspect.iscoroutinefunction(v)}


def _returned(node, parents):
    """The call is the value of a return, or of a lambda handed to a wrapper whose call is returned."""
    up = parents.get(node)
    if isinstance(up, ast.Return): return True
    if isinstance(up, ast.Lambda):
        call = parents.get(up)
        name = getattr(getattr(call, 'func', None), 'id', None) or getattr(getattr(call, 'func', None), 'attr', None)
        return isinstance(call, ast.Call) and name in WRAPPERS and isinstance(parents.get(call), ast.Return)
    return False


def passes_through(name, seen=()):
    """True when every use of this client in Client.<name> is a request (or another pass-through) that is returned."""
    tree, parents = _source(name)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id == 'self'): continue
        attribute = parents.get(node)
        if not isinstance(attribute, ast.Attribute) or attribute.attr == 'http': return False  # handed on, or the transport itself
        target = attribute.attr
        if target in REFUSED: return False  # it uses a refused method or facade
        if target in ASYNC_ON_THIS_CLIENT or (callable(getattr(Client, target, None)) and target not in seen and target not in vars(AsyncClient)
                                               and not isinstance(inspect.getattr_static(Client, target), (staticmethod, classmethod))
                                               and _makes_requests(target, seen + (name,))):
            call = parents.get(attribute)
            if not (isinstance(call, ast.Call) and _returned(call, parents)): return False
            if target not in ASYNC_ON_THIS_CLIENT and not passes_through(target, seen + (name,)): return False  # a helper's own body
    return True


def _makes_requests(name, seen):
    try: tree, parents = _source(name)
    except (TypeError, OSError): return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == 'self':
            attribute = parents.get(node)
            if not isinstance(attribute, ast.Attribute) or attribute.attr == 'http' or attribute.attr in ASYNC_ON_THIS_CLIENT: return True
            target = attribute.attr
            if target in REFUSED: return True
            if (target not in seen and callable(getattr(Client, target, None)) and target not in vars(AsyncClient)
                    and not isinstance(inspect.getattr_static(Client, target), (staticmethod, classmethod)) and _makes_requests(target, seen + (name,))):
                return True
    return False


@pytest.mark.parametrize('name', sorted(PASS_THROUGH | PASS_THROUGH_WRAPPED))
def test_a_pass_through_returns_its_request(name):
    """Mutation: Client.<name> reads its answer before returning (e.g. ['versions']) → on AsyncClient it would subscript a
    coroutine; this fails until the name moves to aio._SYNC_ONLY or gets an asynchronous version."""
    assert passes_through(name) and _makes_requests(name, ())


@pytest.mark.parametrize('name', sorted(aio._SYNC_ONLY))
def test_a_refused_method_cannot_pass_through(name):
    """Mutation: a working pass-through added to aio._SYNC_ONLY → a method that awaits today is refused; this fails."""
    assert not passes_through(name)


# ---- each refusal, over the transport -------------------------------------------------------------------------------

@pytest.mark.parametrize('name', sorted(aio._SYNC_ONLY))
def test_a_sync_only_method_refuses_before_any_request_and_names_client(name):
    """Mutation: drop a name from aio._SYNC_ONLY → its inherited body runs and fails on a coroutine, or a request is sent."""
    client, seen = gateway()
    with pytest.raises(TypeError, match=rf'^AsyncClient\.{name} is not asynchronous yet; use Client\.{name} \(ophiolite\.Client\)\.$'):
        getattr(client, name)('any', 'argument', keyword='any')
    assert seen == []


@pytest.mark.parametrize('name', sorted(aio._SYNC_ONLY_PROPERTIES))
def test_a_sync_only_property_refuses_and_names_client(name):
    client, seen = gateway()
    with pytest.raises(TypeError, match=rf'^AsyncClient\.{name} is not asynchronous yet; use Client\.{name} \(ophiolite\.Client\)\.$'):
        getattr(client, name)
    assert seen == []


def test_the_synchronous_client_is_unchanged_by_the_refusals():
    """Mutation: the refusals set on Client instead of AsyncClient → Client.wells would refuse."""
    for name in REFUSED:
        assert inspect.getattr_static(Client, name) is not inspect.getattr_static(AsyncClient, name), name
        assert 'is not asynchronous yet' not in inspect.getsource(getattr(inspect.getattr_static(Client, name), 'fget', None) or getattr(Client, name)), name


# ---- pass-throughs, awaited over the transport ------------------------------------------------------------------------

def test_an_awaited_pass_through_gives_the_answer_from_one_request():
    """search and lineage, as two samples of the pass-through list."""
    client, seen = gateway((200, {'results': [{'asset_id': 'a'}]}), (200, {'parents': [], 'derivations': []}))
    async def both():
        return await client.search('gamma ray', limit=3), await client.lineage('a', 'r')
    assert run(both()) == ({'results': [{'asset_id': 'a'}]}, {'parents': [], 'derivations': []})
    assert [s[1] for s in seen] == ['/api/v1/projects/p/search/query', '/api/v1/projects/p/entities/lineage']
    assert seen[0][2] == {'project_id': 'p', 'text': 'gamma ray', 'limit': 3}


# ---- find, find_all, find_log ---------------------------------------------------------------------------------------

def test_async_find_sends_the_same_body_as_client_find_and_parses_the_answer():
    """Mutation: AsyncClient.find inherited again → TypeError ('_AsyncGeneratorContextManager' ... context manager)."""
    client, seen = gateway((200, WORDS['q1-first-page']['answer']), (200, MEANING['meaning-first-page']['answer']))
    async def both():
        return (await client.find('org-e145', 'gamma ray', limit=3),
                await client.find('org-e145', 'shale near the top', method='embedding', limit=3))
    page, meaning = run(both())
    assert page.schema_ == 'ophiolite.search/2' and page.matched == 56 and page.next_cursor == 'opaque-cursor-1'
    assert [r.asset for r in page.results] == [r['asset'] for r in WORDS['q1-first-page']['answer']['results']]
    assert meaning.schema_ == 'ophiolite.search/3' and meaning.method == 'embedding'
    assert [s[:2] for s in seen] == [('POST', '/api/v1/organizations/search')] * 2
    assert [s[2] for s in seen] == [{'organization_id': 'org-e145', 'text': 'gamma ray', 'limit': 3},
                                    {'organization_id': 'org-e145', 'text': 'shale near the top', 'method': 'embedding', 'limit': 3}]


@pytest.mark.parametrize('status, body, kind, words, exit', [
    (400, {'code': 'unknown-filter', 'message': 'organizations/search has no filter "colour".', 'reason': 'unknown-filter'}, Refused,
     'organizations/search has no filter "colour".', 1),
    (503, {'code': 'embedding-unavailable', 'message': 'Search by words, or by meaning when the deployment has a local model'}, Busy,
     'Search by words, or by meaning when the deployment has a local model', 5),
    (403, {'code': 'PERMISSION_DENIED', 'message': 'This credential cannot read the organisation.'}, PermissionRefused,
     'This credential cannot read the organisation.', 3)])
def test_an_async_find_refusal_carries_the_servers_sentence(status, body, kind, words, exit):
    """Mutation: AsyncClient._organization_post skips the 403 envelope or the status check → the sentence or category differs."""
    client, _ = gateway((status, body))
    with pytest.raises(kind) as refused: run(client.find('org-e145', 'gamma ray'))
    assert refused.value.message == words and refused.value.status == status and cli.exit_code(refused.value) == exit


def test_async_find_all_follows_the_cursor_to_its_end_as_a_list():
    """Mutation: stop after the first page → 3 rows, not 5."""
    first, last = WORDS['q1-first-page']['answer'], WORDS['last-page']['answer']
    client, seen = gateway((200, first), (200, last))
    rows = run(client.find_all('org-e145', 'gamma ray', limit=3))
    assert [r.asset for r in rows] == [r['asset'] for r in first['results'] + last['results']]
    assert [s[2].get('cursor') for s in seen] == [None, 'opaque-cursor-1']


def _log(ident, name, curves, count):
    return {'asset_id': ident, 'revision': 'r-' + ident, 'name': name, 'origin': 'retained-capture', 'authority': 'fixture', 'profile': 'las2/1',
            'custodian': 'ophiolite:managed', 'curves': list(curves), 'sample_count': count, 'allowed_operations': ['read', 'export', 'use-as-input']}


def test_async_find_log_reads_every_catalogue_page_and_picks_the_largest():
    """Mutation: AsyncClient.find_log inherited again → TypeError ('async_generator' object is not iterable)."""
    pages = {'': {'items': [_log('small', 'Small', ['GR'], 5)], 'next_cursor': 'next'},
             'next': {'items': [_log('large', 'Large', ['gr', 'DT'], 900), _log('other', 'Other', ['RHOB'], 9000)], 'next_cursor': None}}
    seen = []
    def handle(request):
        seen.append(request.url.params.get('cursor'))
        return httpx.Response(200, json=pages[request.url.params.get('cursor')])
    client = AsyncClient(URL, 'p', Credential.bearer('oph_key_example'), httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert run(client.find_log(curves=['GR']))['asset_id'] == 'large'
    assert seen == ['', 'next']
    seen.clear()
    with pytest.raises(Refused, match=r"No log you may use-as-input matches curves \['NPHI'\]\."): run(client.find_log(curves=['NPHI']))
