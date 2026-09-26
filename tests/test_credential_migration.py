import json
from pathlib import Path
import pytest
from ophiolite import auth
from ophiolite.errors import AuthenticationRequired
from test_auth import Provider,cache,envelope


def test_legacy_cache_stays_separate(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    legacy=tmp_path/'.config/ophiolite/application.json';legacy.parent.mkdir(parents=True,mode=0o700)
    raw=json.dumps(envelope()['credential']).encode();legacy.write_bytes(raw);legacy.chmod(0o600)
    project=legacy.with_name('project.json');project.write_bytes(raw);project.chmod(0o600)
    provider=Provider(monkeypatch,errors=['tokens'])
    credential=auth.device_login('http://localhost:8765','test',label='Example',http=provider.http)
    assert credential.path==auth.default_path('http://localhost:8765','test')
    assert legacy.read_bytes()==project.read_bytes()==raw
    assert json.loads(credential.path.read_text())['credential']['refresh_token']=='fresh-refresh'
    for path in (legacy,project):
        with pytest.raises(AuthenticationRequired,match='legacy caches stay separate'):
            auth.device_login('http://localhost:8765','test',path=path,http=provider.http)
    credential.delete();assert legacy.read_bytes()==project.read_bytes()==raw


def test_explicit_flat_destination_refused_before_network(tmp_path):
    path=cache(tmp_path,envelope()['credential']);before=path.read_bytes()
    with pytest.raises(AuthenticationRequired,match='fresh SDK browser login'):
        auth.device_login('http://localhost:8765','test',path=path)
    assert path.read_bytes()==before
