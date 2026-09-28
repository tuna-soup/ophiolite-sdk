"""Installed SDK doctor, and opt-in private kit migration qualification."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from ophiolite.testing import fixture_server


def test_installed_doctor_stays_offline(tmp_path):
    python=os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python:pytest.skip('Supply the independently installed SDK wheel interpreter')
    config=tmp_path/'configuration.json';config.write_text(json.dumps({'schema':'ophiolite.read-configuration/1','url':'https://workspace.example','project':'p'}))
    code='''
import socket,sys
from pathlib import Path
import httpx

def forbidden(*a,**k):raise AssertionError('Offline doctor accessed network or credentials')
socket.socket=forbidden;socket.getaddrinfo=forbidden;httpx.Client.send=forbidden
from ophiolite import cli,auth
original=Path.read_text
def read(path,*a,**k):
 if '/sdk/v1/projects/' in str(path) or str(path).endswith('application.json'):forbidden()
 return original(path,*a,**k)
Path.read_text=read;auth._read=forbidden;auth.request=forbidden
cli.main(['doctor','--configuration',sys.argv[1]])
'''
    env=dict(os.environ,HOME=str(tmp_path/'empty-home'),XDG_CONFIG_HOME=str(tmp_path/'empty-xdg'))
    result=subprocess.run([python,'-I','-c',code,str(config)],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert 'Local contracts: 1.17.0' in result.stdout
    assert not (tmp_path/'empty-home').exists() and not (tmp_path/'empty-xdg').exists()


@pytest.mark.parametrize('kind',['directory','zip'])
def test_clean_installed_kit_login_and_default_read(tmp_path,fixture,kind):
    kit=os.environ.get('OPHIOLITE_TEST_KIT');wheel=os.environ.get('OPHIOLITE_TEST_SDK_WHEEL')
    if not kit or not wheel:
        if os.environ.get('OPHIOLITE_REQUIRE_KIT')=='1':pytest.fail('Supply kit and SDK wheel to the required migration lane')
        pytest.skip('Private kit qualification runs in Integration')
    kitcopy=tmp_path/'kit';shutil.copytree(kit,kitcopy,ignore=shutil.ignore_patterns('__pycache__','*.egg-info','dist','build'))
    pyproject=kitcopy/'pyproject.toml';text=pyproject.read_text()
    # Before both commits exist, replace only packaging metadata in this temporary
    # kit copy. Integration repeats against the real immutable SDK dependency.
    import re
    text=re.sub(r'\[project.scripts\][\s\S]*?(?=\n\[|\Z)','',text)
    text=re.sub(r'^dependencies = .*\n','',text,flags=re.M)
    text=text.replace('requires-python = ">=3.10"','requires-python = ">=3.10"\ndependencies = ["ophiolite @ '+Path(wheel).resolve().as_uri()+'"]')
    pyproject.write_text(text)
    target=str(kitcopy) if kind=='directory' else shutil.make_archive(str(tmp_path/'kit-package'),'zip',kitcopy)
    subprocess.run([sys.executable,'-m','venv',str(tmp_path/'venv')],check=True,capture_output=True)
    python=tmp_path/'venv/bin/python';command=tmp_path/'venv/bin/ophiolite'
    install=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check',target],capture_output=True,text=True,timeout=120)
    assert install.returncode==0,install.stderr
    assert subprocess.run([str(command),'--help'],capture_output=True).returncode==0
    descriptor,raw,artifact=fixture();project=descriptor['project_id'];counts={'token':0}
    # Native public routes expose these representation IDs; the registry fixture
    # deliberately uses shorter IDs, which the frozen kit does not support.
    for rep in descriptor['representations']:
        rep['id']='curve:GR' if rep['kind']=='normalized' else 'artifact'
    def handle(method,path,body,headers):
        base=server.url
        if path.endswith('/config'):return 200,{'issuer':base+'/provider','client_id':'synthetic'}
        if path.endswith('openid-configuration'):return 200,{'issuer':base+'/provider','device_authorization_endpoint':base+'/device','token_endpoint':base+'/token','revocation_endpoint':base+'/revoke'}
        if path=='/device':return 200,{'device_code':'synthetic-device','user_code':'CODE','verification_uri_complete':base+'/verify?code=CODE','expires_in':300,'interval':5}
        if path=='/token':
            counts['token']+=1
            return 200,{'access_token':'synthetic-access','refresh_token':'synthetic-refresh-'+str(counts['token']),'expires_in':300}
        if path.endswith('/request'):return 200,{'id':'synthetic-grant','confirmation_code':'APP','approval_url':base+'/approve?code=APP'}
        if path.endswith('/status'):return 200,{'state':'approved','project_id':project,'user_id':'synthetic-user','scopes':['read']}
        assert headers.get('Authorization')=='Bearer synthetic-access'
        assert headers.get('X-Ophiolite-Application-Grant')=='synthetic-grant'
        if '/representations/' in path:
            from urllib.parse import unquote
            return 200,raw if '/curve:GR?' in unquote(path) else artifact
        return 200,descriptor
    with fixture_server(handle) as server:
        config=tmp_path/'configuration.json';config.write_text(json.dumps({'schema':'ophiolite.read-configuration/1','url':server.url,'project':project,'asset':descriptor['asset_id'],'revision':descriptor['revision'],'curve':'GR'}))
        env=dict(os.environ,HOME=str(tmp_path/'home'),XDG_CONFIG_HOME=str(tmp_path/'xdg'))
        login=subprocess.run([str(command),'login','--configuration',str(config),'--no-browser'],env=env,capture_output=True,text=True,timeout=30)
        assert login.returncode==0,login.stderr
        code='''
import json,sys,warnings
from pathlib import Path
with warnings.catch_warnings(record=True) as notices:
 warnings.simplefilter('always',DeprecationWarning)
 import scientific_read,application_access
assert len(notices)>=2
config=scientific_read.configuration(sys.argv[1]);path=scientific_read.credentials_path(config)
assert '/sdk/v1/projects/' in str(path)
value=json.loads(path.read_text());assert value['schema']=='ophiolite.sdk-credential/1'
value['credential']['expires_at']=1;path.write_text(json.dumps(value))
client=scientific_read.Client.from_configuration(sys.argv[1])
result=client.read(config['asset'],config['revision'],config['curve'])
assert result.curve['values']==[0,10,None,30,40]
assert json.loads(path.read_text())['generation']==2
assert path.with_name(path.name+'.lock').exists()
assert not (Path.home()/'.config/ophiolite/application.json').exists()
print('Installed kit default-path read and locked refresh PASS')
'''
        run=subprocess.run([str(python),'-I','-c',code,str(config)],env=env,capture_output=True,text=True,timeout=30)
        assert run.returncode==0,run.stderr
        assert counts['token']==2
