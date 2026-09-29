"""E25a C4 (M1): the real chain — a browser session creates an access key through the gateway route,
the SDK uses it as an ordinary Bearer against the in-process gateway, and removing it stops it. The
access-key service is not patched: its native token is resolved the way native authentication does
(the credential row by hash, unrevoked, unexpired, enabled person)."""
import hashlib
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service
from ophiolite import Client, Credential
from ophiolite.errors import AuthenticationRequired, PermissionRefused

ORIGIN = 'https://workspace.example'


@pytest.fixture
def keyed(web, service):
    from project_gateway import access_keys
    migrations = Path(access_keys.__file__).resolve().parents[2] / 'tools/migrations'
    with service.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS ab_project_access_blocks(project_id text NOT NULL REFERENCES ab_projects(id),
            user_id text NOT NULL REFERENCES ab_users(id), actor text NOT NULL REFERENCES ab_users(id), created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(project_id,user_id))''')
        db.execute((migrations / '20260929-access-keys.sql').read_text())

    def owner(token):
        if not token.startswith('oph_native_key_'): return token
        with service.connect() as db:
            row = db.execute('''SELECT c.user_id FROM ab_credentials c JOIN ab_users u ON u.id=c.user_id
                WHERE c.token_hash=%s AND NOT c.revoked AND c.expires_at>now() AND u.enabled''', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row: raise PermissionError('native authentication failed')
        return row['user_id']
    account, platform = service.account, web.a.sources.platform
    service.account = lambda token: account(owner(token))
    web.a.sources.platform = lambda method, body, token: platform(method, body, owner(token))
    return web


def session(web, person):
    key, csrf = web.app.state.sessions.create(person, None, person)
    web.c.cookies.set('ab_session', key)
    return key, {'X-CSRF-Token': csrf, 'Origin': ORIGIN}


def create(web, scope):
    key, headers = session(web, 'alice')
    made = web.c.post('/api/v1/access-keys/create', json={'project_id': 'p', 'label': 'Notebook ' + scope, 'scope': scope, 'days': 30}, headers=headers)
    assert made.status_code == 200, made.text
    web.app.state.sessions.remove(key); web.c.cookies.clear()  # the browser session ends; the key does not depend on it
    return made.json()


def test_a_key_reads_publishes_only_with_write_and_stops_when_removed(keyed, tmp_path):
    from project_gateway.tests.test_applications import LAS
    web = keyed
    read = create(web, 'read')
    client = Client(ORIGIN, 'p', Credential.bearer(read['key']), web.c)
    assert isinstance(list(client.assets()), list)
    with pytest.raises(PermissionRefused):
        client.work_folder(tmp_path / 'denied').upload_las(LAS.encode(), name='Denied', attribution='Synthetic', audience=['alice'], rights_confirmed=True)
    write = create(web, 'write')
    writer = Client(ORIGIN, 'p', Credential.bearer(write['key']), web.c)
    upload = writer.work_folder(tmp_path / 'allowed').upload_las(LAS.encode(), name='Allowed', attribution='Synthetic', audience=['alice'], rights_confirmed=True)
    assert upload.revision == hashlib.sha256(LAS.encode()).hexdigest()
    _, headers = session(web, 'alice')
    assert web.c.post('/api/v1/access-keys/remove', json={'id': read['id']}, headers=headers).status_code == 200
    web.c.cookies.clear()
    with pytest.raises((PermissionRefused, AuthenticationRequired)): list(client.assets())
    assert isinstance(list(writer.assets()), list)  # removing one key leaves the other
