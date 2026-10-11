"""E25b C7: an SDK program runs under a service account's key, end to end.

The deployment is the Platform's real-credential one (`real_credentials.project` with the service-account schema,
`test_service_accounts.p`): a session makes the account and its key through the gateway routes, and every call the SDK
makes with the key is resolved by native authentication over the real tables (the credential row by hash, unrevoked,
unexpired, enabled account, its member row). Nothing stands in for that resolution (unlike the E25a chain).
Chain: create, key_login, read, publish, the creator leaves while Bob administers it, read again, disable, refused."""
import json
import os
import uuid

import pytest

try:
    from project_gateway.tests.real_credentials import LAS, ORIGIN, project as credentials  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests.test_service_accounts import p  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, auth, cli
from ophiolite.errors import AuthenticationRequired, PermissionRefused


def private(tmp_path, name):
    folder = tmp_path / 'private'; folder.mkdir(mode=0o700, exist_ok=True)
    return folder / name


def test_a_program_runs_under_the_accounts_key_after_its_creator_leaves_and_stops_when_it_is_disabled(p, tmp_path):
    p.sql("INSERT INTO ab_project_administrators VALUES('p','bob')")
    account = p.ok('alice', 'service-accounts', 'create', {'command_id': 'sdk-nightly', 'name': 'Nightly import', 'scope': 'write'})['account']['id']
    made = p.ok('alice', 'service-accounts', 'key-create', {'account_id': account, 'command_id': 'sdk-key', 'label': 'Nightly import server',
                                                            'scope': 'write', 'days': 30})
    credential = auth.key_login(ORIGIN, 'p', made['key'], path=private(tmp_path, 'nightly.json'), label=made['label'], scope='write')
    job = Client(ORIGIN, 'p', credential, p.c)
    p.c.cookies.clear()

    assert isinstance(list(job.assets()), list)  # read
    upload = job.work_folder(tmp_path / 'first').upload_las(LAS.encode(), name='Nightly gamma', attribution='Synthetic', audience=['alice'],
                                                          rights_confirmed=True)  # publish
    event = next(e for e in p.ok('alice', 'activity', 'list', {})['events'] if e['kind'] == 'action' and e['data'].get('operation') == 'las-uploads/upload'
                 and e['actor_id'] == account)
    assert event['data']['record']['actor']['kind'] == 'workload' and event['data']['record']['on_behalf_of']['kind'] == 'project'
    assert upload.revision

    p.ok('alice', 'service-accounts', 'administrators', {'account_id': account, 'user_id': 'bob', 'action': 'add'})
    p.ok('bob', 'access', 'block', {'user_id': 'alice', 'blocked': True})  # the creator leaves the project; Bob stays
    p.c.cookies.clear()
    assert isinstance(list(job.assets()), list)  # the job keeps running

    p.ok('bob', 'service-accounts', 'disable', {'account_id': account})
    p.c.cookies.clear()
    with pytest.raises((PermissionRefused, AuthenticationRequired)):
        list(job.assets())


def test_login_key_saves_a_service_account_key_without_printing_it(p, tmp_path, capsys):
    account = p.ok('alice', 'service-accounts', 'create', {'command_id': 'sdk-' + uuid.uuid4().hex[:8], 'name': 'Morning report', 'scope': 'read'})['account']['id']
    made = p.ok('alice', 'service-accounts', 'key-create', {'account_id': account, 'command_id': 'sdk-key', 'label': 'Morning report server',
                                                            'scope': 'read', 'days': 30})
    config = tmp_path / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    path = private(tmp_path, 'sdk.json')
    cli.main(['login', '--configuration', str(config), '--credentials', str(path), '--key', made['key']])
    out = capsys.readouterr()
    assert 'Project access key saved' in out.out and made['key'] not in out.out + out.err
    p.c.cookies.clear()
    assert isinstance(list(Client(ORIGIN, 'p', auth.Credential.from_file(path), p.c).assets()), list)
