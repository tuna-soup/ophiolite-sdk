"""E182 s1 C1: a client names its application and the host it runs in once, at construction, and every request it makes
says so in X-Ophiolite-Client; an unnamed client sends this library's own report, as before. Each gateway call below is
answered with a refusal: what is checked is the header the request carried, recorded by the transport."""
import ast
import asyncio
from pathlib import Path

import anyio
import httpx
import pytest

import ophiolite
from ophiolite import Client, _client_header
from ophiolite.aio import AsyncClient
from ophiolite.errors import Refused

SDK = Path(ophiolite.__file__).resolve().parent
NAMED = 'ophiolite-opendtect/0.1.0; host=opendtect/7.0.10'
OWN = 'ophiolite-python/' + ophiolite.__version__
OPENDTECT = dict(application=('ophiolite-opendtect', '0.1.0'), host=('opendtect', '7.0.10'))


@pytest.fixture
def anyio_backend(): return 'asyncio'


class Key:
    kind = 'delegate'
    def headers(self, url, project): return {'Authorization': 'Bearer key'}
    def discovery_headers(self, url): return {'Authorization': 'Bearer key'}


def recorder(seen):
    def handle(request):
        seen.append((request.url.path, request.headers.get('X-Ophiolite-Client')))
        return httpx.Response(404, json={'error': 'Not here.', 'code': 'not-found'})
    return handle


def attempt(call):
    try: call()
    except Exception: pass


def sync_paths(client):
    """Every way the synchronous client builds its headers (client.py: _headers, _post_bytes with and without the
    caller's headers, _post_file, organisation search through access_history._headers, the project's access history,
    and the grant status)."""
    attempt(lambda: client.describe('a', 'r', 'GR'))
    attempt(lambda: client.inspect('a', 'r', curve='GR', name='GR'))
    attempt(lambda: client._post_bytes('applications', 'inspect', b'{}', headers={'Authorization': 'Bearer key'}))
    attempt(lambda: client._post_file('applications', 'inspect', {'asset_id': 'a'}, None))
    attempt(lambda: client.find('org'))
    attempt(lambda: client.access_history())
    attempt(lambda: client._grant_status({'X-Ophiolite-Application-Grant': 'g', 'Authorization': 'Bearer key'}))


def test_t1_every_request_of_a_named_client_says_what_sent_it():
    seen = []
    with Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen))), **OPENDTECT) as client:
        sync_paths(client)
    paths = {path for path, _ in seen}
    assert {'/api/v1/organizations/search', '/api/v1/application-access/status'} <= paths and any('/access/' in p for p in paths)
    assert len(seen) >= 7 and {said for _, said in seen} == {NAMED}


def test_t1_an_unnamed_client_sends_this_librarys_own_report():
    seen = []
    with Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen)))) as client:
        sync_paths(client)
    assert len(seen) >= 7 and {said for _, said in seen} == {OWN}


def test_t1_from_configuration_names_the_application(tmp_path):
    configuration = tmp_path / 'configuration.json'
    configuration.write_text('{"schema": "ophiolite.read-configuration/1", "url": "http://localhost", "project": "p"}')
    seen = []
    client = Client.from_configuration(configuration, credential=Key(), http=httpx.Client(transport=httpx.MockTransport(recorder(seen))), **OPENDTECT)
    attempt(lambda: client.describe('a', 'r', 'GR'))
    assert seen and {said for _, said in seen} == {NAMED}


def test_t1_an_exchange_send_says_what_sent_it(tmp_path):
    """The OpendTect connector's path: Exchange over ClientTransport (sync only; there is no async exchange)."""
    from ophiolite.exchange import ClientTransport
    seen = []
    with Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen))), **OPENDTECT) as client:
        transport = ClientTransport(client)
        attempt(lambda: transport.identity())
        attempt(lambda: client.holders())
    assert seen and {said for _, said in seen} == {NAMED}


@pytest.mark.anyio
@pytest.mark.parametrize('named', [True, False])
async def test_t2_the_async_client_and_its_application_driver_say_the_same(named):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder(seen))) as http:
        async with AsyncClient('http://localhost', 'p', Key(), http, **(OPENDTECT if named else {})) as client:
            for call in (lambda: client.describe('a', 'r', 'GR'), lambda: client.inspect('a', 'r', curve='GR', name='GR'), lambda: client.holders()):
                try: await call()
                except Exception: pass
    paths = [path for path, _ in seen]
    assert any(p.endswith('/applications/inspect') for p in paths), paths  # through _ApplicationDriver
    assert len(seen) >= 3 and {said for _, said in seen} == {NAMED if named else OWN}


def test_t3_every_stamp_in_the_client_modules_passes_the_clients_name():
    """Supplementary to T1 and T2: a new stamp( call in these modules names the sender too (Account's calls are out of
    scope: no project, nothing a version records)."""
    bare = []
    for name in ('client.py', 'aio.py', 'access_history.py'):
        for node in ast.walk(ast.parse((SDK / name).read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'stamp' and len(node.args) + len(node.keywords) < 2:
                bare.append((name, node.lineno))
    assert bare == []


@pytest.mark.parametrize('options, sentence', [
    (dict(application=('ophiolite opendtect', '0.1.0')), _client_header.NAMED),
    (dict(application=('', '0.1.0')), _client_header.NAMED),
    (dict(application=('a' * 41, '0.1.0')), _client_header.NAMED),
    (dict(application=('ophiolite-opendtect', 1)), _client_header.NAMED),
    (dict(application=('ophiolite-opendtect', '0.1.0', 'x')), _client_header.NAMED),
    (dict(application='ophiolite-opendtect/0.1.0'), _client_header.NAMED),
    (dict(application=('ophiolite-opendtect', '0.1.0é')), _client_header.NAMED),
    (dict(host=('opendtect', '7.0.10')), _client_header.HOSTED),
    (dict(application=('ophiolite-opendtect', '0.1.0'), host=('opendtect', '7.0 10')), _client_header.NAMED),
    (dict(application=('a' * 40, 'b' * 40), host=('c' * 26, 'd' * 14)), _client_header.NAMED),  # 81 + 7 + 41 = 129 characters
])
@pytest.mark.parametrize('kind', ['sync', 'async'])
def test_t4_a_name_the_gateway_would_not_keep_is_refused_before_any_request(options, sentence, kind):
    seen = []
    with pytest.raises(Refused) as refused:
        if kind == 'sync': Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen))), **options)
        else: AsyncClient('http://localhost', 'p', Key(), httpx.AsyncClient(transport=httpx.MockTransport(recorder(seen))), **options)
    assert str(refused.value) == sentence and seen == []


def test_t4_the_longest_name_the_gateway_keeps_is_sent_whole():
    application, host = ('a' * 40, 'b' * 40), ('c' * 38, 'd')  # 81 + 7 + 40 = 128 characters
    said = '%s/%s; host=%s/%s' % (*application, *host)
    assert len(said) == 128
    seen = []
    with Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen))), application=application, host=host) as client:
        attempt(lambda: client.describe('a', 'r', 'GR'))
    assert seen and {s for _, s in seen} == {said}


def test_t5_the_libraries_grammar_is_the_gateways():
    """The gateway's own test (test_version_senders, E182 s1 T5) pins record._TOKEN and CLIENT_LIMIT to these literals."""
    assert _client_header.TOKEN.pattern == r'[A-Za-z0-9][A-Za-z0-9._+-]{0,39}' and _client_header.LIMIT == 128


def test_t6_the_command_lines_name_applies_to_an_unnamed_client_and_a_named_client_wins():
    seen = []
    token = _client_header._NAME.set('ophiolite-cli')
    try:
        for options in ({}, OPENDTECT):
            with Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(recorder(seen))), **options) as client:
                attempt(lambda: client.describe('a', 'r', 'GR'))
    finally: _client_header._NAME.reset(token)
    assert [said for _, said in seen] == ['ophiolite-cli/' + ophiolite.__version__, NAMED]


def test_t6b_interleaved_clients_keep_their_own_names():
    seen = []
    transport = httpx.MockTransport(recorder(seen))
    od = Client('http://localhost', 'p', Key(), httpx.Client(transport=transport), **OPENDTECT)
    other = Client('http://localhost', 'p', Key(), httpx.Client(transport=transport), application=('other-app', '2.0'))
    plain = Client('http://localhost', 'p', Key(), httpx.Client(transport=transport))
    for client in (od, other, plain, od, plain, other):
        attempt(lambda: client.describe('a', 'r', 'GR'))
    assert [said for _, said in seen] == [NAMED, 'other-app/2.0', OWN, NAMED, OWN, 'other-app/2.0']


@pytest.mark.anyio
async def test_t6b_concurrent_async_clients_keep_their_own_names():
    seen = []
    async def handle(request):
        await anyio.sleep(0.01)
        seen.append(request.headers.get('X-Ophiolite-Client'))
        return httpx.Response(404, json={'error': 'Not here.'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        clients = [AsyncClient('http://localhost', 'p', Key(), http, **OPENDTECT), AsyncClient('http://localhost', 'p', Key(), http, application=('other-app', '2.0')),
                   AsyncClient('http://localhost', 'p', Key(), http)]
        async def read(client):
            try: await client.describe('a', 'r', 'GR')
            except Exception: pass
        await asyncio.gather(*[read(c) for c in clients * 3])
    assert sorted(seen) == sorted([NAMED, 'other-app/2.0', OWN] * 3)
