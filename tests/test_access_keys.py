"""E25a C4: an access key is saved as its own credential kind, sent as a bare Bearer, and the CLI
treats it by kind: login --key saves it for later processes, OPHIOLITE_ACCESS_KEY alone stays in
one process, status is local, logout removes only the local copy. The key is never printed."""
import json
import subprocess
import sys

import pytest
from ophiolite import auth, cli
from ophiolite.auth import Credential
from ophiolite.errors import AuthenticationRequired, Refused

KEY = 'oph_key_MARKER' + 'x' * 40


def configuration(tmp_path):
    path = tmp_path / 'configuration.json'
    path.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': 'http://localhost', 'project': 'p'}))
    return path


def store(tmp_path):
    folder = tmp_path / 'private'; folder.mkdir(mode=0o700, exist_ok=True)
    return folder / 'sdk.json'


def test_a_saved_key_round_trips_and_is_sent_as_a_bare_bearer(tmp_path):
    path = store(tmp_path)
    credential = auth.key_login('http://localhost', 'p', KEY, path=path, label='Notebook', scope='read', expires_at='2026-12-01T00:00:00+00:00')
    again = Credential.from_file(path)
    assert again.kind == 'access_key' and 'MARKER' not in repr(again)
    assert again.headers('http://localhost', 'p') == {'Authorization': 'Bearer ' + KEY}  # no grant, nothing to refresh
    assert again.summary() == {'kind': 'access_key', 'url': 'http://localhost', 'project': 'p', 'label': 'Notebook', 'scope': 'read', 'expires_at': '2026-12-01T00:00:00+00:00'}
    with pytest.raises(AuthenticationRequired, match='another gateway or project'): again.headers('http://localhost', 'other')
    with pytest.raises(AuthenticationRequired, match='account page'): again.revoke()
    assert credential.kind == 'access_key'


@pytest.mark.parametrize('url,project,key', [('ftp://host', 'p', KEY), ('http://localhost', '', KEY), ('http://localhost', 'p', 'oph_api_notakey'),
                                              ('http://localhost', 'p', 'oph_key_with space')])
def test_malformed_keys_are_refused_before_anything_is_saved(tmp_path, url, project, key):
    path = store(tmp_path)
    with pytest.raises((Refused, AuthenticationRequired)): auth.key_login(url, project, key, path=path)
    assert not path.exists()


def test_a_tampered_saved_key_is_refused(tmp_path):
    path = store(tmp_path)
    auth.key_login('http://localhost', 'p', KEY, path=path)
    value = json.loads(path.read_text()); value['credential']['access_key'] = 'oph_api_other'
    path.write_text(json.dumps(value))
    with pytest.raises(AuthenticationRequired, match='Invalid saved project access key'): Credential.from_file(path)


def test_login_key_saves_for_a_second_process_without_a_browser(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(auth, 'device_login', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no browser flow')))
    config, path = configuration(tmp_path), store(tmp_path)
    cli.main(['login', '--configuration', str(config), '--credentials', str(path), '--key', KEY])
    code = 'from ophiolite.auth import Credential; import sys; c = Credential.from_file(sys.argv[1]); print(c.kind, c.headers("http://localhost", "p")["Authorization"] == "Bearer " + sys.argv[2])'
    other = subprocess.run([sys.executable, '-c', code, str(path), KEY], capture_output=True, text=True, check=True)
    assert other.stdout.split() == ['access_key', 'True']
    cli.main(['status', '--configuration', str(config), '--credentials', str(path)])  # local: no Client, no network
    cli.main(['logout', '--configuration', str(config), '--credentials', str(path)])
    assert not path.exists()
    out = capsys.readouterr()
    assert 'Project access key saved' in out.out and 'Local project access key removed' in out.out and 'MARKER' not in out.out + out.err


def test_the_environment_key_stays_in_one_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', KEY)
    config, path = configuration(tmp_path), store(tmp_path)
    cli.main(['status', '--configuration', str(config), '--credentials', str(path)])
    cli.main(['logout', '--configuration', str(config), '--credentials', str(path)])
    assert not path.exists()
    seen = []
    class Fake:
        def __init__(self, url, project, credential): seen.append(credential.headers(url, project))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def assets(self): return [{'asset_id': 'a'}]
    monkeypatch.setattr(cli, 'Client', Fake)
    cli.main(['list', '--configuration', str(config), '--credentials', str(path)])
    out = capsys.readouterr()
    assert seen == [{'Authorization': 'Bearer ' + KEY}] and 'not saved' in out.out and 'Nothing saved to remove' in out.out and 'MARKER' not in out.out + out.err
