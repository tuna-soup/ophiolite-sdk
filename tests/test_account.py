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
            {'id': 'q', 'name': 'Shared', 'role': 'viewer', 'can_administer': False, 'organization_id': None}]


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
    assert capsys.readouterr().out.splitlines() == ['Pilot - can edit and administer', 'Shared - can view']
    cli.main(['orgs', '--url', URL, '--credential', str(credential), '--json'])
    assert json.loads(capsys.readouterr().out) == {'organizations': [{'id': 'o', 'name': 'Operator'}]}
    broken = tmp_path / 'private' / 'broken.json'; broken.write_text('{not json'); broken.chmod(0o600)
    with pytest.raises(SystemExit) as refused: cli.main(['projects', '--url', URL, '--credential', str(broken)])
    assert 'Cannot read private SDK credentials' in str(refused.value) and 'Traceback' not in str(refused.value)
    with pytest.raises(SystemExit, match='--limit is 1 to 100'): cli.main(['projects', '--url', URL, '--credential', str(credential), '--limit', '0'])
