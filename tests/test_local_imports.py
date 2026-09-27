"""Exercise an installed wheel, with traps installed before package import."""
import os
from pathlib import Path
import subprocess
import pytest

PROBE=r'''
import builtins, io, json, os, socket, sys
from pathlib import Path
home=Path(os.environ['HOME'])
if os.environ['CANARIES']=='1':
 for relative in ('.config/ophiolite/sdk/v1/projects/canary.json','.config/ophiolite/projects/canary.json','.config/ophiolite/application.json'):
  path=home/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('credential-read-must-fail')
before=sorted((str(p.relative_to(home)),p.read_bytes()) for p in home.rglob('*') if p.is_file())
def audit(event,args):
 if event.startswith('socket.'):
  raise AssertionError('Local import/validation attempted network: '+event)
 if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  path=Path(os.fsdecode(args[0])).absolute()
  if home==path or home in path.parents:raise AssertionError('Local import read/created a credential/cache')
sys.addaudithook(audit)
import ophiolite
from ophiolite import validate, Descriptor
from ophiolite.models.generated import ScientificAsset, ApplicationCurve
from importlib.resources import files
root=files('ophiolite').joinpath('contracts/assets/v1/fixtures')
d=json.loads(root.joinpath('source.json').read_text());raw=root.joinpath('curve.json').read_bytes()
asset,curve=validate.pair(d,raw)
assert curve.values==[0,10,None,30,40]
assert ophiolite.__contracts__['registry_version']=='1.8.0'
assert not any(x in sys.modules for x in ('ophiolite.client','ophiolite.auth','httpx','project_gateway'))
assert '/site-packages/' in ophiolite.__file__,ophiolite.__file__
print('installed local validation PASS')
'''

@pytest.mark.parametrize('populated',[False,True])
def test_installed_local_imports(tmp_path,populated):
    python=os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python:
        pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the independently installed SDK wheel interpreter')
    home=tmp_path/'home';home.mkdir();cwd=tmp_path/'empty';cwd.mkdir()
    env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('TOKEN','CREDENTIAL','SECRET','PYTHONPATH'))}
    env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),XDG_CACHE_HOME=str(home/'.cache'),CANARIES=str(int(populated)),PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([python,'-I','-c',PROBE],cwd=cwd,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
