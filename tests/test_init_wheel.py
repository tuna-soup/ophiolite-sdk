"""E31 S4: `ophiolite init` scaffolds every packaged template from an installed wheel, outside this checkout, and an
initialised template passes its own tests there (the templates lane)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('agent-workflow', 'derive-and-publish', 'map-application', 'notebook', 'sync-worker')
WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH',) and not k.startswith('OPHIOLITE_')}


def init(python, name, folder):
    done = subprocess.run([python, '-m', 'ophiolite', 'init', name, '--output', str(folder), '--json'], cwd=folder.parent, env=clean_env(),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def installed_outside(python, cwd):
    where = subprocess.run([python, '-c', 'import ophiolite;print(ophiolite.__file__)'], cwd=cwd, env=clean_env(), capture_output=True, text=True).stdout.strip()
    return where and not where.startswith(str(ROOT))


def test_init_scaffolds_every_template_from_the_installed_wheel(tmp_path):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    assert installed_outside(WHEEL, tmp_path)
    listed = json.loads(subprocess.run([WHEEL, '-m', 'ophiolite', 'init', '--list', '--json'], cwd=tmp_path, env=clean_env(), capture_output=True, text=True).stdout)
    assert sorted(t['name'] for t in listed['templates']) == sorted(NAMES)
    for name in NAMES:
        made = init(WHEEL, name, tmp_path / ('app-' + name))
        folder = Path(made['path'])
        assert (folder / 'template.json').is_file() and (folder / 'README.md').is_file() and Path(made['support']).is_file()
        assert json.loads((folder / 'template.json').read_text())['name'] == name
        assert not any(part in ('node_modules', 'dist', '__pycache__') for p in folder.rglob('*') for part in p.relative_to(folder).parts)
    again = subprocess.run([WHEEL, '-m', 'ophiolite', 'init', 'sync-worker', '--output', str(tmp_path / 'app-sync-worker')], cwd=tmp_path, env=clean_env(), capture_output=True, text=True)
    assert again.returncode == 1 and 'not empty' in again.stderr  # never over an existing project


@pytest.mark.parametrize('name', ['agent-workflow', 'derive-and-publish', 'sync-worker', 'map-application'])
def test_an_initialised_template_passes_its_own_tests(tmp_path, name):
    """Runs where the templates' locked dependencies and a non-editable SDK install are provisioned (the templates lane)."""
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES') != '1': pytest.skip('Provision locked template dependencies and run the required template lane')
    assert installed_outside(sys.executable, tmp_path), 'the templates lane installs the SDK itself, not this checkout'
    folder = Path(init(sys.executable, name, tmp_path / 'project')['path'])
    command = [sys.executable, '-m', 'pytest', '-q', 'tests/test_server.py'] if name == 'map-application' else [sys.executable, *json.loads((folder / 'template.json').read_text())['test_command'][1:]]
    done = subprocess.run(command, cwd=folder, env=clean_env(), capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
