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
NAMES=('agent-workflow','notebook','python-application','react-application')


def test_template_versions_follow_sdk_and_have_real_commands():
    source_version=re.search(r'^version = "([^"]+)"',(ROOT/'pyproject.toml').read_text(),re.M).group(1)
    assert source_version==__version__
    for name in NAMES:
        directory=ROOT/'templates'/name;metadata=json.loads((directory/'template.json').read_text())
        assert metadata['template_version']==metadata['sdk_version']==source_version
        assert metadata['test_command']==(['python','tools/test.py'] if name=='react-application' else ['python','-m','pytest','-q','tests'])
        assert 'template_version' in (directory/'README.md').read_text()
        assert 'file://' not in (directory/'requirements.lock').read_text()


def test_notebook_is_generated_from_paired_script():
    subprocess.run([sys.executable,str(ROOT/'tools/build_notebook.py'),'--check'],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('name',NAMES)
def test_template_command(name):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES')!='1':pytest.skip('Provision locked template dependencies and run the required template lane')
    directory=ROOT/'templates'/name;command=json.loads((directory/'template.json').read_text())['test_command']
    result=subprocess.run([sys.executable,*command[1:]],cwd=directory,env=dict(os.environ,OPHIOLITE_PYTHON=sys.executable),capture_output=True,text=True,timeout=240)
    assert result.returncode==0,result.stdout+result.stderr
