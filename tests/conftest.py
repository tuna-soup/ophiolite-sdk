import copy
import json
from pathlib import Path
import pytest

FIX=Path(__file__).resolve().parents[1]/'ophiolite/contracts/assets/v1/fixtures'

@pytest.fixture
def fixture():
    def load(origin='source',frozen=False):
        root=FIX/'frozen/pre-e1' if frozen else FIX
        return (json.loads((root/(origin+'.json')).read_text()),
                (root/('derived-curve.json' if origin=='derived' else 'curve.json')).read_bytes(),
                (root/('derived.las' if origin=='derived' else 'original.las')).read_bytes())
    return load

@pytest.fixture(scope='session', autouse=True)
def session_config_home(tmp_path_factory):
    """E142 s2a C3: the session's own XDG_CONFIG_HOME, set before any module or session fixture runs the real export."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('XDG_CONFIG_HOME', str(tmp_path_factory.mktemp('config')))
        yield

@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    """E142 s2a C3: every test keeps the OpendTect connector's installation id (ophiolite/opendtect-instance) under its
    own XDG_CONFIG_HOME, so no test that runs the real export writes the runner's ~/.config; subprocesses inherit it."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    return tmp_path / 'config'

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    import os
    outcome=yield
    report=outcome.get_result()
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1' and 'gateway' in item.path.parts and report.skipped:
        report.outcome='failed'
        report.longrepr='Required gateway case skipped; configure its prerequisites instead.'
