"""E27 C8: Account/connect and the projects/orgs commands over a synthetic gateway (httpx
MockTransport). The discovery path keeps the saved-credential checks (gateway, refresh, replacement)
and never relaxes an ordinary project-bound call."""
import json
import time

import httpx
import pytest
from ophiolite import auth, cli
from ophiolite.account import Account, connect
from ophiolite.auth import Credential
from ophiolite.errors import AuthenticationRequired, PermissionRefused, Refused
from test_auth import envelope, cache

URL = 'http://localhost:8765'
REAL_CLIENT = httpx.Client
PROJECTS = [{'id': 'p', 'name': 'Pilot', 'role': 'member', 'can_administer': True, 'organization_id': 'o'},
            {'id': 'q', 'name': 'Shared', 'role': 'viewer', 'can_administer': False, 'organization_id': None, 'access_ends_at': '2026-11-15T00:00:00Z'}]


def gateway(state=None):
    state = state if state is not None else {}
    def handle(request):
        state.setdefault('seen', []).append((request.url.path, dict(request.headers)))
        if state.get('refuse'): return httpx.Response(403, json={'error': 'no', 'code': 'PERMISSION_DENIED'})
        if request.url.path == '/token':
            state['refreshed'] = state.get('refreshed', 0) + 1
            return httpx.Response(200, json={'access_token': 'fresh-access', 'refresh_token': 'fresh-refresh', 'expires_in': 300})
        body = json.loads(request.content or b'{}')
        if request.url.path == '/api/v1/projects/list':
            limit, after = body.get('limit', 50), json.loads(body['cursor'])['after'] if body.get('cursor') else None
            rows = [p for p in PROJECTS if after is None or p['id'] > after]
            page = rows[:limit]
            return httpx.Response(200, json={'projects': page, 'next_cursor': json.dumps({'after': page[-1]['id']}) if len(rows) > limit else None})
        if request.url.path == '/api/v1/projects/organizations':
            return httpx.Response(200, json={'organizations': [{'id': 'o', 'name': 'Operator'}]})
        return httpx.Response(404, json={})
    return REAL_CLIENT(transport=httpx.MockTransport(handle)), state


def test_an_account_lists_every_page_once_and_its_organisations():
    http, state = gateway()
    account = connect(URL, Credential.bearer('oph_key_example'), http)
    assert [p['id'] for p in account.projects(limit=1)] == ['p', 'q'] and account.organizations() == [{'id': 'o', 'name': 'Operator'}]
    assert all(h['authorization'] == 'Bearer oph_key_example' for _, h in state['seen'])
    state['refuse'] = True
    with pytest.raises(PermissionRefused): account.projects()  # a revoked credential refuses on the next call


def test_discovery_keeps_the_saved_credential_checks(tmp_path):
    path = cache(tmp_path)
    http, state = gateway()
    saved = Credential.from_file(path, http=http)
    assert saved.discovery_headers(URL)['Authorization'] == 'Bearer synthetic-access'  # no project is named, the gateway is
    with pytest.raises(AuthenticationRequired, match='another gateway'): saved.discovery_headers('http://localhost:9999')
    value = json.loads(path.read_text()); value['credential']['expires_at'] = time.time() + 5; path.write_text(json.dumps(value))
    assert saved.discovery_headers(URL)['Authorization'] == 'Bearer fresh-access' and state['refreshed'] == 1  # refreshed as headers() would
    value = json.loads(path.read_text()); value['family'] = 'replaced-by-a-new-login'; path.write_text(json.dumps(value))
    with pytest.raises(AuthenticationRequired, match='replaced'): saved.discovery_headers(URL)


def test_discovery_never_relaxes_an_ordinary_project_bound_call(tmp_path):
    path = cache(tmp_path)  # saved for project 'test'
    http, _ = gateway()
    account = Account(URL, Credential.from_file(path, http=http), http)
    account.projects()
    with pytest.raises(AuthenticationRequired, match='another gateway or project'): account.client('other').credential.headers(URL, 'other')


def write_credential(tmp_path, key='oph_key_' + 'k' * 40):
    folder = tmp_path / 'private'; folder.mkdir(mode=0o700)
    return auth.key_login(URL, 'p', key, path=folder / 'key.json').path


def test_the_projects_and_orgs_commands(tmp_path, monkeypatch, capsys):
    http, _ = gateway()
    monkeypatch.setattr('ophiolite.account.httpx.Client', lambda **k: gateway()[0])  # a fresh client per command (Account closes its own)
    credential = write_credential(tmp_path)
    cli.main(['projects', '--url', URL, '--credential', str(credential), '--limit', '1'])
    assert capsys.readouterr().out.splitlines() == ['Pilot - can edit and administer', 'Shared - can view, ends 14 Nov 2026']
    cli.main(['projects', '--url', URL, '--credential', str(credential), '--json'])  # E67a: the field is always there
    assert [(p['id'], p['access_ends_at']) for p in json.loads(capsys.readouterr().out)['projects']] == [('p', None), ('q', '2026-11-15T00:00:00Z')]
    cli.main(['orgs', '--url', URL, '--credential', str(credential), '--json'])
    assert json.loads(capsys.readouterr().out) == {'organizations': [{'id': 'o', 'name': 'Operator'}]}
    broken = tmp_path / 'private' / 'broken.json'; broken.write_text('{not json'); broken.chmod(0o600)
    capsys.readouterr()
    with pytest.raises(SystemExit) as refused: cli.entrypoint(['projects', '--url', URL, '--credential', str(broken)])  # E31: main raises, entrypoint exits
    err = capsys.readouterr().err
    assert refused.value.code == 3 and 'Cannot read private SDK credentials' in err and 'Traceback' not in err  # a sign-in problem
    with pytest.raises(SystemExit) as refused: cli.entrypoint(['projects', '--url', URL, '--credential', str(credential), '--limit', '0'])
    assert refused.value.code == 1 and '--limit is 1 to 100' in capsys.readouterr().err


def test_a_row_without_an_end_comes_back_with_an_explicit_none():
    """E67a C6 (F4, M5): an answer that omits the field (an older gateway, an undated grant) yields the key with None,
    and the other keys come back unchanged."""
    http, _ = gateway()
    rows = connect(URL, Credential.bearer('oph_key_example'), http).projects()
    assert rows == [{**PROJECTS[0], 'access_ends_at': None}, PROJECTS[1]] and 'access_ends_at' not in PROJECTS[0]


# --- E67b C8: teams and the access history read with an access key --------------------------------------------------

def history_gateway():
    seen = []
    def handle(request):
        seen.append((request.url.path, dict(request.headers), json.loads(request.content or b'{}')))
        if request.url.path.endswith('/teams'): return httpx.Response(200, json={'teams': []})
        return httpx.Response(200, json={'entries': [], 'next_cursor': None, 'as_of': '2026-10-20T00:00:00Z', 'earlier_changes_may_be_incomplete': None,
                                         'not_inspectable': 0})
    return REAL_CLIENT(transport=httpx.MockTransport(handle)), seen


def test_a_saved_sign_in_is_not_used_for_teams_or_the_access_history_and_nothing_is_sent(tmp_path):
    """The saved sign-in (bearer plus X-Ophiolite-Application-Grant) is refused by the server on these reads; the SDK says
    so before sending it. An access key is what they take."""
    from ophiolite import Client
    from ophiolite.access_history import ACCESS_KEY_NEEDED
    http, seen = history_gateway()
    saved = Credential.from_file(cache(tmp_path), http=http)  # a saved sign-in for project 'test'
    client, account = Client(URL, 'test', saved, http), Account(URL, saved, http)
    for call in (client.access_history, client.access_teams, lambda: client.export_access_history('csv', tmp_path / 'h.csv'),
                 lambda: account.teams('o'), lambda: account.team('o', 't'), lambda: account.person_history('o', 'bob'),
                 lambda: account.export_person_history('o', 'bob', 'csv', tmp_path / 'b.csv')):
        with pytest.raises(Refused) as refused: call()
        assert (refused.value.code, refused.value.message) == ('access-key-required', ACCESS_KEY_NEEDED)
    assert seen == [] and not (tmp_path / 'h.csv').exists() and not (tmp_path / 'b.csv').exists()


def test_the_person_history_names_the_organisation_and_never_a_project():
    http, seen = history_gateway()
    connect(URL, Credential.bearer('oph_key_example'), http).person_history('o', 'bob', kinds=['key_created'], since='2026-10-01', until='2026-11-01', project='p')
    [(path, headers, body)] = seen
    assert path == '/api/v1/organizations/person-history' and headers['authorization'] == 'Bearer oph_key_example'
    assert body == {'organization_id': 'o', 'user_id': 'bob', 'limit': 100,
                    'filters': {'kinds': ['key_created'], 'from': '2026-10-01', 'to': '2026-11-01', 'project': 'p'}}


def test_the_cli_page_documents_reading_access_history_and_teams():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'docs/cli.md').read_text()
    section = text.split('## Reading access history and teams', 1)[1].split('\n## ', 1)[0]
    for words in ('ophiolite access-history', 'ophiolite teams', '--project', '--person', '--export', 'Client.access_history', 'Client.access_teams',
                  'Client.export_access_history', 'Account.teams', 'Account.team', 'Account.person_history', 'access key',
                  'a saved sign-in is refused', 'HISTORY_GRANT_REFUSED', 'HISTORY_AGENT_REFUSED'):
        assert words in section, words
