"""E51a C5 against the real in-process gateway: doctor --online names the stage the gateway refused at, with the
gateway's own sentence, stage and remedy; the SDK's categories for 401 and 403 do not move."""
import pytest
from test_access_key_chain import keyed, create, session, web, shared, app, service, ORIGIN  # noqa: F401
from ophiolite import Credential, doctor
from ophiolite.errors import AuthenticationRequired, PermissionRefused


@pytest.fixture
def local(monkeypatch):
    """The in-process gateway has no DNS name: the address stage resolves it as loopback."""
    monkeypatch.setattr(doctor.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])


class Lost(Credential):
    """A credential whose header is lost on the way, as QGIS loses a value ending in a line break."""
    def headers(self, url=None, project=None, *, cancel=None): return {}
    def discovery_headers(self, url, *, cancel=None): return {}


def stages(report): return [(s['stage'], s['ok']) for s in report['stages']]


def test_a_key_passes_the_credential_and_project_stages(keyed, local):
    made = create(keyed, 'read')
    report = doctor.run(ORIGIN, 'p', Credential.bearer(made['key'] + '\n'), http=keyed.c)
    assert stages(report)[:5] == [(s, True) for s in ('address', 'tls', 'credential-arrived', 'credential-accepted', 'project-readable')]
    assert made['key'] not in str(report)


def test_no_credential_arrived_is_named_by_the_gateway(keyed, local):
    report = doctor.run(ORIGIN, 'p', Lost('x'), http=keyed.c)
    last = report['stages'][-1]
    assert (last['stage'], last['ok'], last['server_stage']) == ('credential-arrived', False, 'no-credential')
    assert "No credential reached Ophiolite" in last['detail'] and last['remedy'] and report.exit_code == 3


def test_a_removed_key_is_refused_at_credential_accepted(keyed, local):
    made = create(keyed, 'read')
    _, headers = session(keyed, 'alice')
    assert keyed.c.post('/api/v1/access-keys/remove', json={'id': made['id']}, headers=headers).status_code == 200
    keyed.c.cookies.clear()
    report = doctor.run(ORIGIN, 'p', Credential.bearer(made['key']), http=keyed.c)
    last = report['stages'][-1]
    assert (last['stage'], last['ok'], last['server_stage']) == ('credential-accepted', False, 'credential-refused')
    assert 'revoked or expired' in last['detail']


def test_sdk_categories_do_not_move(keyed):
    from ophiolite.account import Account
    with Account(ORIGIN, Lost('x'), keyed.c) as account, pytest.raises(AuthenticationRequired) as refused: account.projects()
    assert refused.value.status == 401 and refused.value.stage == 'no-credential'
    with Account(ORIGIN, Credential.bearer('oph_key_' + 'U' * 54), keyed.c) as account, pytest.raises(PermissionRefused) as refused: account.projects()
    assert refused.value.status == 403 and refused.value.stage == 'credential-refused'
