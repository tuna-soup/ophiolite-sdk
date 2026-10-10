"""E39 C4: an organisation's database connections from Python. The listing is projectless (/api/v1/org-connections/list),
names the organisation it answers for, and carries no sign-in or password; an answer outside its shape, for another
organisation, or refused by the gateway is never returned as a listing. The fixture counts requests."""
import json

import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite.errors import PermissionRefused, Refused, VerificationFailed

ACME = 'org-acme'
ROW = {'id': 'managed-1', 'organization_id': ACME, 'name': 'Corporate wells', 'enabled': True, 'generation': 2,
       'you': {'use': True, 'administer': False, 'signed_in': True}}


class Gateway:
    def __init__(self, answer, status=200):
        self.answer, self.status, self.calls = answer, status, []

    def __call__(self, request):
        self.calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(self.status, json=self.answer)


def client(gateway):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=httpx.Client(transport=httpx.MockTransport(gateway)))


def listing(**change):
    return {'organization_id': ACME, 'connections': [ROW], 'scope': 'connections you use or administer', **change}


def test_the_listing_names_no_project_and_answers_the_organisations_connections():
    gateway = Gateway(listing())
    with client(gateway) as c:
        assert c.org_connections(ACME) == [ROW]
    assert gateway.calls == [('/api/v1/org-connections/list', {'organization_id': ACME})]


@pytest.mark.parametrize('answer', [
    listing(connections=[{k: v for k, v in ROW.items() if k != 'you'}]),          # a row without the caller's own access
    listing(connections=[{**ROW, 'generation': '2'}]),                            # a generation that is not a number
    {k: v for k, v in listing().items() if k != 'scope'}])                        # no scope sentence
def test_an_answer_outside_its_shape_is_refused(answer):
    with client(Gateway(answer)) as c, pytest.raises(VerificationFailed) as caught:
        c.org_connections(ACME)
    assert str(caught.value).startswith('The organisation connection listing answered outside its documented shape.')


def test_an_answer_for_another_organisation_is_refused():
    with client(Gateway(listing(organization_id='org-other'))) as c, pytest.raises(VerificationFailed) as caught:
        c.org_connections(ACME)
    assert str(caught.value).startswith('The organisation connection listing answered for another organisation.')


def test_a_gateway_refusal_is_a_permission_refusal():
    gateway = Gateway({'code': 'PERMISSION_DENIED', 'message': 'Organisation membership required'}, status=403)
    with client(gateway) as c, pytest.raises(PermissionRefused):
        c.org_connections(ACME)
    assert [path for path, _ in gateway.calls] == ['/api/v1/org-connections/list']


@pytest.mark.parametrize('organization', ['', None, 7])
def test_an_unnamed_organisation_sends_nothing(organization):
    gateway = Gateway(listing())
    with client(gateway) as c, pytest.raises(Refused) as caught:
        c.org_connections(organization)
    assert str(caught.value).startswith('Name the organisation by its id.') and gateway.calls == []


def test_the_command_line_lists_them_without_a_project_path(tmp_path):
    from test_cli_subprocess import gateway, run
    seen = []
    with gateway({'/api/v1/org-connections/list': lambda body: seen.append(body) or (200, listing())}) as server:
        done = run(tmp_path, 'org-connections', 'list', '--organization', ACME, '--json', url=server.url)
        human = run(tmp_path, 'org-connections', 'list', '--organization', ACME, url=server.url)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {'organization_id': ACME, 'connections': [ROW]} and seen == [{'organization_id': ACME}] * 2
    assert human.stdout.strip() == 'managed-1  Corporate wells: ready'
