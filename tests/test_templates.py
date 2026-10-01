"""Versioned source templates and their separately provisioned, required CI lane."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import pytest
from ophiolite import __version__
ROOT=Path(__file__).resolve().parents[1]
NAMES=('agent-workflow','notebook','derive-and-publish','map-application','sync-worker')


def test_template_versions_follow_sdk_and_have_real_commands():
    source_version=re.search(r'^version = "([^"]+)"',(ROOT/'pyproject.toml').read_text(),re.M).group(1)
    assert source_version==__version__
    for name in NAMES:
        directory=ROOT/'ophiolite/templates'/name;metadata=json.loads((directory/'template.json').read_text())
        assert metadata['template_version']==metadata['sdk_version']==source_version
        assert metadata['test_command']==(['python','tools/test.py'] if name=='map-application' else ['python','-m','pytest','-q','tests'])
        assert 'template_version' in (directory/'README.md').read_text()
        assert 'file://' not in (directory/'requirements.lock').read_text()


def test_notebook_is_generated_from_paired_script():
    subprocess.run([sys.executable,str(ROOT/'tools/build_notebook.py'),'--check'],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('name',NAMES)
def test_template_command(name):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES')!='1':pytest.skip('Provision locked template dependencies and run the required template lane')
    directory=ROOT/'ophiolite/templates'/name;command=json.loads((directory/'template.json').read_text())['test_command']
    result=subprocess.run([sys.executable,*command[1:]],cwd=directory,env=dict(os.environ,OPHIOLITE_PYTHON=sys.executable),capture_output=True,text=True,timeout=240)
    assert result.returncode==0,result.stdout+result.stderr


def test_the_template_client_uses_the_access_key_the_readme_names(tmp_path, monkeypatch):
    """H4 (E32 F8): with OPHIOLITE_ACCESS_KEY set and no credential file named or saved, support.client_for uses the
    key, as the sync-worker and map-application READMEs and the command line say; a saved or named file still wins."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ophiolite/templates'))
    import support
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path)); monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('OPHIOLITE_CREDENTIAL', raising=False)
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_key_' + 'k' * 40)
    with support.client_for('https://ophiolite.example', 'p') as client:
        assert client.credential.kind == 'bearer'
    monkeypatch.setenv('OPHIOLITE_CREDENTIAL', str(tmp_path / 'named.json'))
    with pytest.raises(Exception): support.client_for('https://ophiolite.example', 'p')  # a named file is used, not the key


def test_history_explains_that_uploaded_originals_have_no_listed_versions():
    """H4 (E32 F4): refused in plain words before any request, instead of the server's misleading refusal."""
    from ophiolite import Client, Credential
    from ophiolite.errors import Refused
    client = Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_' + 'k' * 40))
    with pytest.raises(Refused, match='uploaded original'):
        client.history({'asset_id': 'a', 'revision': 'r', 'authority': 'ophiolite:uploaded'})
