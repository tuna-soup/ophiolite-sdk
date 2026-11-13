"""adhoc-first-run-fixes-2a (demo defect 9): Client.from_configuration finds the credential where gallery.connect does.

Without an explicit credential it takes, in gallery.connect's order, the file OPHIOLITE_CREDENTIAL names or the sign-in
`ophiolite account login` saved for the configuration's address and project, else OPHIOLITE_ACCESS_KEY. An explicit
credential still wins, and with none of them the client sends no credential, as before. No test prints the key."""
import json

import httpx
import pytest

from ophiolite import Client
from ophiolite.auth import Credential, default_path

KEY = 'oph_api_configuration_test'  # synthetic; never a real key


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))  # no saved sign-in unless a test writes one
    for name in ('OPHIOLITE_CREDENTIAL', 'OPHIOLITE_ACCESS_KEY'): monkeypatch.delenv(name, raising=False)
    path = tmp_path / 'configuration.json'
    path.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': 'http://localhost', 'project': 'p'}))
    return path


def sent(client):
    """The Authorization header the client sends on a request (None when it sends none)."""
    seen = []
    def handle(request):
        seen.append(request.headers.get('authorization'))
        return httpx.Response(200, json={'items': [], 'next_cursor': None})
    client.http = httpx.Client(transport=httpx.MockTransport(handle))
    client.http.get(client.url + '/api/v1/ping', headers=client._headers())
    return seen[0]


def test_the_access_key_in_the_environment_is_used(configured, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', KEY)
    assert sent(Client.from_configuration(configured)) == 'Bearer ' + KEY


def test_an_explicit_credential_wins_over_the_environment(configured, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', KEY)
    assert sent(Client.from_configuration(configured, credential=Credential.bearer('oph_api_explicit_test'))) == 'Bearer oph_api_explicit_test'


def test_without_any_credential_nothing_is_sent(configured):
    assert Client.from_configuration(configured).credential is None


@pytest.mark.parametrize('where', ['named', 'saved'])
def test_a_credential_file_comes_before_the_access_key(configured, monkeypatch, tmp_path, where):
    file = tmp_path / 'credential.json' if where == 'named' else default_path('http://localhost', 'p')
    file.parent.mkdir(parents=True, exist_ok=True); file.write_text('{}')
    if where == 'named': monkeypatch.setenv('OPHIOLITE_CREDENTIAL', str(file))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', KEY)
    opened = []
    monkeypatch.setattr(Credential, 'from_file', classmethod(lambda cls, path, **kw: opened.append(str(path)) or 'from-file'))
    assert Client.from_configuration(configured).credential == 'from-file'
    assert opened == [str(file)]
