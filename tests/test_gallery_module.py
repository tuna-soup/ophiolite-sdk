"""E52 C4: ophiolite.gallery.connect() in its three modes, and the sentence when none applies."""
import json

import pytest
from ophiolite import gallery
from ophiolite.errors import Refused


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    for name in ('OPHIOLITE_URL', 'OPHIOLITE_PROJECT', 'OPHIOLITE_CREDENTIAL', 'OPHIOLITE_ACCESS_KEY', 'OPHIOLITE_TEMPLATE_FIXTURE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))  # no saved sign-in from the machine running the tests
    gallery.use(None)
    yield
    gallery.use(None)
    gallery._stop()


def test_without_an_address_it_is_the_synthetic_server():
    assert gallery.synthetic()
    client = gallery.connect()
    assert client is gallery.connect()  # one synthetic server per process
    assert client.url.startswith('http://127.0.0.1:') and client.project == 'p'
    assert [a['curves'] for a in client.assets()] == [['GR']]


def test_the_fixture_switch_wins_over_an_address(monkeypatch):
    monkeypatch.setenv('OPHIOLITE_URL', 'https://ophiolite.example'); monkeypatch.setenv('OPHIOLITE_TEMPLATE_FIXTURE', '1')
    assert gallery.connect().url.startswith('http://127.0.0.1:')


def test_use_binds_the_client_a_harness_chose(monkeypatch):
    monkeypatch.setenv('OPHIOLITE_URL', 'https://ophiolite.example')
    marker = object()
    assert gallery.use(marker) is marker and gallery.connect() is marker and not gallery.synthetic()


def test_an_address_uses_the_access_key_or_the_saved_credential(monkeypatch, tmp_path):
    monkeypatch.setenv('OPHIOLITE_URL', 'https://ophiolite.example')
    with pytest.raises(Refused, match='Set OPHIOLITE_PROJECT'): gallery.connect()
    monkeypatch.setenv('OPHIOLITE_PROJECT', 'p1')
    with pytest.raises(Refused, match='No saved sign-in for p1 at https://ophiolite.example.') as refused: gallery.connect()
    assert 'configuration.json from Connect → Use Python' in refused.value.recovery and 'ophiolite login --key-stdin' in refused.value.recovery
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_k\n')
    client = gallery.connect()
    assert (client.url, client.project) == ('https://ophiolite.example', 'p1')
    monkeypatch.setenv('OPHIOLITE_CREDENTIAL', str(tmp_path / 'missing.json'))  # an explicit file wins and must exist
    with pytest.raises(Exception) as missing: gallery.connect()
    assert 'oph_api_k' not in str(missing.value)
