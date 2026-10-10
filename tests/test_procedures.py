"""E105a C4: the SDK validates a procedure with the contract's own packaged file, exactly as the Platform does."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ophiolite
from ophiolite import procedures

PACKAGE = Path(ophiolite.__file__).resolve().parent
CONTRACTS = PACKAGE / 'contracts'
HERE = CONTRACTS / 'procedures/v1'
FIXTURES = HERE / 'fixtures'
EXPECTED = json.loads((FIXTURES / 'expected.json').read_text())
REPO = PACKAGE.parent


def folder_with(tmp_path, name, raw, members):
    folder = tmp_path / name
    for member in members:
        target = folder / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw if member == 'procedure.json' else b'')
    return folder


@pytest.mark.parametrize('name', sorted(EXPECTED['cases']))
def test_the_shared_invalid_fixtures_give_the_platform_sentences_through_the_sdk(tmp_path, name):
    case = EXPECTED['cases'][name]
    raw = (FIXTURES / 'invalid' / f'{name}.json').read_bytes()
    verdict = procedures.validate(folder_with(tmp_path, name, raw, EXPECTED['members'][case['base']]))
    assert (verdict['valid'], verdict['code'], verdict['field'], verdict['sentence'], verdict['rules_version']) == (
        False, case['code'], case['field'], case['sentence'], '1.0.0')


@pytest.mark.parametrize('step', sorted(EXPECTED['members']))
def test_the_shared_valid_fixtures_are_valid_through_the_sdk(tmp_path, step):
    raw = (FIXTURES / 'valid' / f'{step}.json').read_bytes()
    assert procedures.validate(folder_with(tmp_path, step, raw, EXPECTED['members'][step]))['valid']


def test_the_sample_bundles_have_their_literal_digests():
    assert procedures.digest(FIXTURES / 'bundles/depth-shift') == '560a8af5fd9a7206b9af0bc04006c36daab12576eecf9eb96396ec3d6ef475bf'
    assert procedures.digest(FIXTURES / 'bundles/team-las') == '81cb03b2aa046fd8eb5e8176b859059fb027061d42ad5a35c1c70e2848a18f17'
    verdict = procedures.validate(FIXTURES / 'bundles/depth-shift')
    assert verdict['sentence'] == 'Valid: Shift tops by a fixed depth, version 1. It reads Well tops (CSV) and makes Well tops (CSV).'


def test_the_loaded_validator_is_the_packaged_file():
    """M1: the functions in use were compiled from the packaged contract file, which SOURCE.json pins."""
    module = procedures.contract()
    assert module.check_manifest.__code__.co_filename == str(HERE / 'procedure.py')
    assert module.labels.__file__ == str(CONTRACTS / 'vocabulary/v1/labels.py')
    source = json.loads((CONTRACTS / 'SOURCE.json').read_text())['files']
    import hashlib
    for path in ('procedures/v1/procedure.py', 'procedures/v1/rules.json', 'vocabulary/v1/labels.py'):
        assert hashlib.sha256((CONTRACTS / path).read_bytes()).hexdigest() == source[path], path


def test_a_changed_packaged_sentence_changes_what_the_sdk_says(tmp_path):
    """M1: a copy of the package with one sentence changed in its rules.json says the changed sentence."""
    copy = tmp_path / 'site' / 'ophiolite'
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns('__pycache__'))
    rules = copy / 'contracts/procedures/v1/rules.json'
    rules.write_text(rules.read_text().replace('needs a readable label, for example', 'needs words a person reads, for example'))
    raw = (FIXTURES / 'invalid/setting-label-snake.json').read_bytes()
    folder = folder_with(tmp_path, 'p', raw, ['procedure.json', 'procedure.py'])
    probe = 'import sys; from ophiolite import procedures; print(procedures.validate(sys.argv[1])["sentence"])'
    env = {**os.environ, 'PYTHONPATH': str(copy.parent), 'PYTHONDONTWRITEBYTECODE': '1'}
    out = subprocess.run([sys.executable, '-c', probe, str(folder)], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert out.stdout.strip() == 'Not valid: setting 1 needs words a person reads, for example "Depth shift".', out.stderr


def test_loading_writes_nothing_into_the_snapshot_and_it_stays_exact(tmp_path):
    """D3: after loading and validating, the snapshot check still passes and no cache folder exists in it."""
    probe = 'import sys; from ophiolite import procedures; print(procedures.validate(sys.argv[1])["valid"])'
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONDONTWRITEBYTECODE'}
    env['PYTHONPATH'] = str(REPO)
    out = subprocess.run([sys.executable, '-c', probe, str(FIXTURES / 'bundles/team-las')], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert out.stdout.strip() == 'True', out.stderr
    assert not list(CONTRACTS.rglob('__pycache__')) and not list(CONTRACTS.rglob('*.pyc'))
    platform = REPO.parent / 'ophiolite-platform'
    if not (platform / 'contracts').is_dir(): pytest.skip('no Platform checkout beside the SDK to check the snapshot against')
    check = subprocess.run([sys.executable, 'tools/sync_contracts.py', '--check', '--source', str(platform)], cwd=REPO, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


PROBE = r'''
import sys
def audit(event, args):
    if event.startswith('socket.'): raise AssertionError('procedures attempted network: ' + event)
sys.addaudithook(audit)
from ophiolite import procedures
folder, out = sys.argv[1], sys.argv[2]
assert procedures.validate(folder)['valid']
procedures.unpack(procedures.pack(folder), out)
print(procedures.digest(out))
'''


def test_validation_digest_and_archive_contact_nothing(tmp_path):
    env = {**os.environ, 'PYTHONPATH': str(REPO), 'PYTHONDONTWRITEBYTECODE': '1'}
    out = subprocess.run([sys.executable, '-c', PROBE, str(FIXTURES / 'bundles/team-las'), str(tmp_path / 'out')], env=env,
                         capture_output=True, text=True, cwd=tmp_path)
    assert out.stdout.strip() == '81cb03b2aa046fd8eb5e8176b859059fb027061d42ad5a35c1c70e2848a18f17', out.stderr


def test_r29_the_sdk_validator_never_imports_the_procedure(tmp_path):
    sentinel = tmp_path / 'SENTINEL'
    code = f'open({str(sentinel)!r}, "w").write("imported")\n'
    folder = tmp_path / 'p'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', folder)
    (folder / 'procedure.py').write_text(code + (folder / 'procedure.py').read_text())
    (folder / '__init__.py').write_text(code)
    before = set(sys.modules)
    assert procedures.validate(folder)['valid']
    procedures.digest(folder); procedures.unpack(procedures.pack(folder), tmp_path / 'out')
    assert not sentinel.exists() and set(sys.modules) == before
