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

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    import os
    outcome=yield
    report=outcome.get_result()
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1' and 'gateway' in item.path.parts and report.skipped:
        report.outcome='failed'
        report.longrepr='Required gateway case skipped; configure its prerequisites instead.'
