"""E148 s1 C3: a server's Deprecation header becomes one OphioliteDeprecationWarning per route per client.

Every SDK path that reads an Ophiolite answer passes it to its owner's notifier; nothing is installed on an httpx
client. Each owner is tested behaviourally with a mock that adds the headers; the CLI tests run the real command
against a loopback server and freeze standard output, exit status and standard error. Every test records under
`simplefilter('always')`, so the count is the notifier's, never a warnings filter's.
"""
import json
import socket
import threading
import warnings
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anyio
import httpx
import pytest

from ophiolite import Client, Credential, OphioliteDeprecationWarning, _deprecation, doctor
from ophiolite.account import Account
from ophiolite.agents import AgentClient
from ophiolite.aio import AsyncClient
from ophiolite.oauth_app import OAuthApp
from ophiolite.sync import Sync

URL = 'https://ophiolite.example'
HEADERS = {'Deprecation': '@1798761600', 'Sunset': 'Fri, 01 Jan 2028 00:00:00 GMT', 'Link': '</api/v1/next>; rel="successor-version"'}


def said(method, template):
    return '%s %s is deprecated (since 2027-01-01); sunset Fri, 01 Jan 2028 00:00:00 GMT; successor /api/v1/next' % (method, template)


def gateway(bodies=None, headers=HEADERS, seen=None):
    """Answers 200 with the body named by the longest matching path suffix (else {}), plus HEADERS."""
    def answer(request):
        if seen is not None: seen.append(request.url.path)
        path = request.url.path
        body = next((b for suffix, b in sorted((bodies or {}).items(), key=lambda kv: -len(kv[0])) if path.endswith(suffix)), {})
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(200, content=content, headers=[('Content-Type', 'application/json'), *(headers.items() if isinstance(headers, dict) else headers)])
    return answer


def http(bodies=None, headers=HEADERS, **options):
    return httpx.Client(transport=httpx.MockTransport(gateway(bodies, headers)), **options)


def client(bodies=None, headers=HEADERS, transport=None):
    return Client(URL, 'p', Credential.bearer('oph_api_alice'), http=transport or http(bodies, headers))


@contextmanager
def recorded():
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        yield seen


def notices(seen):
    return [str(w.message) for w in seen if issubclass(w.category, OphioliteDeprecationWarning)]


# --- the once-rule --------------------------------------------------------------------------------------------------

def test_a_route_warns_once_and_another_route_warns_again():
    c = client({'/sources/list': {'selections': []}})
    with recorded() as seen:
        assert c._post('sources', 'list', {}) == {'selections': []}
        c._post('sources', 'list', {})
        c._post('sources', 'export', {})
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/sources/list'), said('POST', '/api/v1/projects/{project}/sources/export')]
    assert all(w.category is OphioliteDeprecationWarning and issubclass(w.category, UserWarning) for w in seen)


def test_the_same_route_in_two_projects_and_with_a_query_is_one_route():
    notifier = _deprecation.Notifier(); answer = httpx.Response(200, headers=HEADERS)
    with recorded() as seen:
        notifier.note('POST', URL + '/api/v1/projects/p/sources/list', answer)
        notifier.note('post', URL + '/api/v1/projects/q/sources/list?limit=3', answer)
        notifier.note('GET', URL + '/api/v1/projects/q/sources/list', answer)
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/sources/list'), said('GET', '/api/v1/projects/{project}/sources/list')]


def test_no_header_no_warning():
    c = client(headers={})
    with recorded() as seen: c._post('sources', 'list', {})
    assert notices(seen) == []


def test_clients_sharing_one_transport_each_warn_once_and_the_transport_is_untouched():
    hooked = []
    shared = http(event_hooks={'response': [lambda response: hooked.append(response.url.path)]})
    hooks = {k: list(v) for k, v in shared.event_hooks.items()}
    first, second = client(transport=shared), client(transport=shared)
    with recorded() as seen:
        for c in (first, second, first, second): c._post('sources', 'list', {})
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/sources/list')] * 2
    assert {k: list(v) for k, v in shared.event_hooks.items()} == hooks and len(hooks['response']) == 1
    assert hooked == ['/api/v1/projects/p/sources/list'] * 4  # the person's own hook ran once per response


def test_a_closed_client_shares_nothing_with_a_new_one():
    with client() as c, recorded() as seen: c._post('sources', 'list', {})
    with client() as c, recorded() as again: c._post('sources', 'list', {}); c._post('sources', 'list', {})
    assert notices(seen) == notices(again) == [said('POST', '/api/v1/projects/{project}/sources/list')]


# --- every owner ------------------------------------------------------------------------------------------------------

def test_client_get_post_bytes_post_file_and_post_json():
    c = client()
    with recorded() as seen:
        assert c._get('/api/v1/projects/p/scientific-assets/a/r', 100) == b'{}'
        assert c._post_bytes('sources', 'list', b'{"project_id": "p"}') == {}
        assert c._post_file('sources', 'export-file', {}, {}) == b'{}'
        assert c._post('sources', 'export', {}) == {}
        c._grant_status({'X-Ophiolite-Application-Grant': 'g1'})
    assert notices(seen) == [said('GET', '/api/v1/projects/{project}/scientific-assets/a/r'), said('POST', '/api/v1/projects/{project}/sources/list'),
                             said('POST', '/api/v1/projects/{project}/sources/export-file'), said('POST', '/api/v1/projects/{project}/sources/export'),
                             said('POST', '/api/v1/application-access/status')]


def test_the_asynchronous_client_follows_the_same_rule():
    async def main():
        transport = httpx.AsyncClient(transport=httpx.MockTransport(gateway()))
        async with AsyncClient(URL, 'p', Credential.bearer('oph_api_alice'), http=transport) as c:
            assert await c._get('/api/v1/projects/p/scientific-assets/a/r', 100) == b'{}'
            await c._get('/api/v1/projects/p/scientific-assets/a/r', 100)
            assert await c._post_bytes('sources', 'list', b'{}') == {}
            await c._post_bytes('sources', 'list', b'{}')
            await c._grant_status({'X-Ophiolite-Application-Grant': 'g1'})
        await transport.aclose()
    with recorded() as seen: anyio.run(main)
    assert notices(seen) == [said('GET', '/api/v1/projects/{project}/scientific-assets/a/r'), said('POST', '/api/v1/projects/{project}/sources/list'),
                             said('POST', '/api/v1/application-access/status')]


def test_account_discovery_and_organisation_reads():
    projects = {'projects': [{'id': 'p', 'name': 'P', 'role': 'viewer', 'can_administer': False, 'organization_id': None}], 'next_cursor': None}
    with Account(URL, Credential.bearer('oph_api_alice'), http({'/projects/list': projects, '/organizations/teams': {'teams': []}})) as account, recorded() as seen:
        assert [p['id'] for p in account.projects()] == ['p']
        account.projects()
        assert account.teams('o') == []
    assert notices(seen) == [said('POST', '/api/v1/projects/list'), said('POST', '/api/v1/organizations/teams')]


def test_an_agent_and_its_reads_share_one_warning_per_route():
    agent = AgentClient(URL, 'p', 'oph_agent_test', http=http())
    with recorded() as seen: assert agent._post('entities', 'list', {}) == {}
    with recorded() as reads:
        assert agent.reads._post('entities', 'list', {}) == {}
        agent.reads._post('entities', 'get', {})
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/entities/list')]
    assert notices(reads) == [said('POST', '/api/v1/projects/{project}/entities/get')]


EXCHANGED = 'oph_app_provider-refresh-0'  # a name, not a token key, so the release audit's secret-assignment rule does not read it as one


class Store:
    def __init__(self): self.records = {}
    def get(self, person): return self.records.get(person)
    def put(self, person, record): self.records[person] = record


def test_an_application_notes_ophiolite_but_not_the_provider():
    provider = 'https://id.example'
    bodies = {'/.well-known/oauth-authorization-server': {'issuer': provider, 'authorization_endpoint': provider + '/authorize', 'token_endpoint': provider + '/token'},
              '/applications/exchange': {'access_token': EXCHANGED, 'expires_in': 60}}
    app = OAuthApp(URL, 'a1', 'c1', 'https://app.example/back', store=Store(), http=http(bodies))
    with recorded() as seen:
        assert app.metadata()['token_endpoint'] == provider + '/token'
        assert app._exchange('person', {'access_token': 't', 'handle': 'h'}) == EXCHANGED
        assert app._token({'grant_type': 'refresh_token', 'refresh_token': 'r'}) == {}  # the provider's answer carries the header too
    assert notices(seen) == [said('GET', '/.well-known/oauth-authorization-server'), said('POST', '/api/v1/applications/exchange')]


def test_sync_changes_and_its_stream():
    bodies = {'/changes/head': {'epoch': 'e1', 'cursor': 3}, '/changes/list': {'epoch': 'e1', 'changes': [], 'cursor': 3, 'has_more': False}, '/changes/stream': b''}
    sync = Sync(client(bodies))
    with recorded() as seen:
        assert sync.head() == {'epoch': 'e1', 'cursor': 3}
        assert list(sync.changes('e1', 3)) == [{'epoch': 'e1', 'changes': [], 'cursor': 3, 'has_more': False}]
        assert list(sync.follow(epoch='e1', after=3, reconnect=False)) == []
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/changes/head'), said('POST', '/api/v1/projects/{project}/changes/list'),
                             said('POST', '/api/v1/projects/{project}/changes/stream')]


def test_access_history():
    c = client({'/access/teams': {'teams': []}, '/access/history': {'entries': [], 'next_cursor': None}})
    with recorded() as seen:
        assert c.access_teams() == [] and c.access_history() == []
        c.access_teams()
    assert notices(seen) == [said('POST', '/api/v1/projects/{project}/access/teams'), said('POST', '/api/v1/projects/{project}/access/history')]


DOCTOR = {'/api/v1/contracts': {'version': '1.84.0'},
          '/api/v1/projects/list': {'projects': [{'id': 'p', 'name': 'P', 'role': 'viewer', 'can_administer': False, 'organization_id': None}], 'next_cursor': None},
          '/api/v1/projects/p/features': {'title': 'P', 'links': []},
          '/api/v1/projects/p/capabilities/describe': {'scopes': ['read']},
          '/api/v1/projects/p/features/collections': {'collections': [{'id': 'wells', 'title': 'Wells'}]},
          '/api/v1/projects/p/features/collections/wells/items': {'type': 'FeatureCollection', 'features': [{'id': 'w1'}], 'numberReturned': 1, 'numberMatched': 206}}
DOCTOR_SAID = [said('GET', '/api/v1/contracts'), said('POST', '/api/v1/projects/list'), said('GET', '/api/v1/projects/{project}/features'),
               said('POST', '/api/v1/projects/{project}/capabilities/describe'), said('GET', '/api/v1/projects/{project}/features/collections'),
               said('GET', '/api/v1/projects/{project}/features/collections/wells/items')]


def test_doctor_online_notes_every_stage(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [])
    with recorded() as seen: report = doctor.run(URL, 'p', Credential.bearer('oph_api_alice'), http=http(DOCTOR))
    assert report.exit_code == 0 and report['stages'][-1]['detail'] == '206 wells'
    assert notices(seen) == DOCTOR_SAID


# --- the headers ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('headers, expected', [
    ({'Deprecation': '@1798761600'}, 'POST /api/v1/projects/{project}/sources/list is deprecated (since 2027-01-01); sunset not stated; successor none named'),
    ([('Deprecation', '@1798761600'), ('Link', '</api/v1/projects/p/sources/list?cursor=2>; rel="next"'), ('Link', '</api/v1/next>; rel="successor-version"')],
     'POST /api/v1/projects/{project}/sources/list is deprecated (since 2027-01-01); sunset not stated; successor /api/v1/next'),
    ({'Deprecation': '@1798761600', 'Link': '</a>; rel="next", </b>; rel="latest-version successor-version"'},
     'POST /api/v1/projects/{project}/sources/list is deprecated (since 2027-01-01); sunset not stated; successor /b'),
    ({'Deprecation': 'soon', 'Sunset': 'later'}, 'POST /api/v1/projects/{project}/sources/list is deprecated (since "soon"); sunset later; successor none named'),
])
def test_header_edge_cases_and_the_answer_is_unchanged(headers, expected):
    c = client({'/sources/list': {'selections': [{'id': 's1'}]}}, headers)
    with recorded() as seen: assert c._post('sources', 'list', {}) == {'selections': [{'id': 's1'}]}
    assert notices(seen) == [expected]


def test_a_failing_notice_never_breaks_an_answer():
    class Broken:
        @property
        def headers(self): raise RuntimeError('no headers')
    with recorded() as seen: _deprecation.Notifier().note('GET', URL + '/x', Broken())
    assert notices(seen) == []


# --- the command line -------------------------------------------------------------------------------------------------

class Server:
    """A loopback gateway: path suffix -> JSON body; every answer is 200 and carries HEADERS when deprecated."""
    def __init__(self, bodies, deprecated=True):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def answer(self):
                length = int(self.headers.get('Content-Length') or 0)
                if length: self.rfile.read(length)
                path = self.path.split('?')[0]
                body = next((b for suffix, b in sorted(bodies.items(), key=lambda kv: -len(kv[0])) if path.endswith(suffix)), None)
                data = json.dumps(body if body is not None else {'code': 'NOT_FOUND', 'message': 'Unknown', 'error': 'Unknown'}).encode()
                self.send_response(200 if body is not None else 404); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
                for k, v in (HEADERS.items() if deprecated else ()): self.send_header(k, v)
                self.end_headers(); self.wfile.write(data)
            do_GET = do_POST = answer
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
    def __enter__(self): threading.Thread(target=self.server.serve_forever, daemon=True).start(); return self
    def __exit__(self, *a): self.server.shutdown(); self.server.server_close()


def sources():
    from test_sources import exported, payload, selection
    answer = exported(payload())
    return {'/sources/list': {'selections': [selection(answer)], 'scope': 's'}, '/sources/export': answer}


LIST = said('POST', '/api/v1/projects/{project}/sources/list')
EXPORT = said('POST', '/api/v1/projects/{project}/sources/export')


@pytest.mark.parametrize('argv, stdout, stderr', [
    (('sources', 'list'), 's1  Groningen wells (sql-wells/1): current\n', ['warning: ' + LIST]),
    (('sources', 'describe', 's1'), 'Groningen wells: 2 rows, 5 columns (id, name, x, y, operator), EPSG:28992, revision '
                                    '4bb839cd49d5d6a2cb8b36284da5b0ea8043e7a233353ca7ce28173bf77b8569\n', ['warning: ' + LIST, 'warning: ' + EXPORT]),
    (('sources', 'read', 's1'), 'well_id,name,operator,x,y\na,Alpha,NAM,4.3,52.0\nb,Beta,,4.5,52.1\n', ['warning: ' + LIST, 'warning: ' + EXPORT]),
])
def test_the_cli_says_it_once_on_standard_error(tmp_path, argv, stdout, stderr):
    from test_cli_subprocess import run
    with Server(sources(), deprecated=False) as before: quiet = run(tmp_path, *argv, url=before.url)
    with Server(sources()) as server: done = run(tmp_path, *argv, url=server.url)
    assert quiet.returncode == done.returncode == 0 and quiet.stderr == '', quiet.stderr
    assert done.stdout == quiet.stdout == stdout
    assert done.stderr == ''.join(line + '\n' for line in stderr)


def test_doctor_online_says_each_route_once(tmp_path):
    from test_cli_subprocess import run
    with Server(DOCTOR, deprecated=False) as before: quiet = run(tmp_path, 'doctor', '--online', '--project', 'p', key='oph_api_alice', url=before.url)
    with Server(DOCTOR) as server: done = run(tmp_path, 'doctor', '--online', '--project', 'p', key='oph_api_alice', url=server.url)
    assert quiet.returncode == done.returncode == 0 and quiet.stderr == '', quiet.stderr
    assert done.stdout.replace(server.url, 'URL') == quiet.stdout.replace(before.url, 'URL') and 'Stage features: ok - 206 wells' in done.stdout
    assert done.stderr.splitlines() == ['warning: ' + text for text in DOCTOR_SAID]
