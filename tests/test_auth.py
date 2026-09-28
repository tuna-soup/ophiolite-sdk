import copy
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import parse_qs
import httpx
import pytest
from ophiolite import auth
from ophiolite.auth import Credential
from ophiolite.errors import AuthenticationRequired, Refused


def envelope():
    return {'schema':auth.SCHEMA,'family':'synthetic-family','generation':1,'credential':{
        'url':'http://localhost:8765','project':'test','issuer':'http://localhost:8765/provider',
        'client_id':'synthetic-client','token_endpoint':'http://localhost:8765/token',
        'revocation_endpoint':'http://localhost:8765/revoke','grant_id':'synthetic-grant',
        'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_at':time.time()+1000}}


def cache(tmp_path, value=None):
    path=tmp_path/'private'/'sdk.json';path.parent.mkdir(mode=0o700)
    path.write_text(json.dumps(value or envelope()));path.chmod(0o600)
    return path


@pytest.mark.parametrize('value',['https://example.org/token','http://localhost:8765/token','http://127.0.0.1/token','http://[::1]/token'])
def test_same_origin_allowed(value):
    assert auth.same_origin(value,value)==value


@pytest.mark.parametrize('value',[
    'http://foreign.example/token','https://user:pass@example.org/token',
    'https://example.org/token?x=1','https://example.org/token#x',
    'https://foreign.example/token','file:///token','https:///token',None])
def test_same_origin_refused(value):
    with pytest.raises(AuthenticationRequired):auth.same_origin(value,'https://example.org')


@pytest.mark.parametrize('case',['mode','owner','symlink','directory','parent','flat','schema','generation','family','foreign-token','foreign-revocation','invalid-token','lifetime'])
def test_cache_guards(tmp_path,monkeypatch,case):
    value=envelope();path=cache(tmp_path,value)
    if case=='mode':path.chmod(0o644)
    elif case=='owner':monkeypatch.setattr(auth.os,'getuid',lambda:os.stat(path).st_uid+1)
    elif case=='symlink':
        target=path.with_name('real');path.rename(target);path.symlink_to(target)
    elif case=='directory':path.unlink();path.mkdir(mode=0o600)
    elif case=='parent':path.parent.chmod(0o755)
    else:
        if case=='flat':value=value['credential']
        if case=='schema':value['schema']='other'
        if case=='generation':value['generation']=True
        if case=='family':value['family']=''
        if case=='foreign-token':value['credential']['token_endpoint']='https://foreign.example/token'
        if case=='foreign-revocation':value['credential']['revocation_endpoint']='https://foreign.example/revoke'
        if case=='invalid-token':value['credential']['access_token']='bad\ntoken'
        if case=='lifetime':value['credential']['expires_at']=float('nan')
        path.write_text(json.dumps(value))
    with pytest.raises(AuthenticationRequired):Credential.from_file(path)


def test_refresh_and_scope(tmp_path):
    value=envelope();value['credential']['expires_at']=1;path=cache(tmp_path,value);calls=[]
    def handle(req):
        calls.append(req)
        assert parse_qs(req.content.decode())['refresh_token']==['synthetic-refresh']
        return httpx.Response(200,json={'access_token':'new-access','refresh_token':'new-refresh','expires_in':300})
    credential=Credential.open(path,http=httpx.Client(transport=httpx.MockTransport(handle)))
    for url,project in [('https://foreign.example','test'),('http://localhost:8765','other')]:
        with pytest.raises(AuthenticationRequired):credential.headers(url,project)
    assert calls==[]
    headers=credential.headers('http://localhost:8765','test')
    assert headers['Authorization']=='Bearer new-access'
    assert credential.headers('http://localhost:8765','test')==headers
    assert len(calls)==1
    saved=json.loads(path.read_text());assert saved['generation']==2
    assert saved['credential']['expires_at']>time.time()+270
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert list(path.parent.glob('.sdk-*'))==[]
    assert 'new-access' not in repr(credential)


@pytest.mark.parametrize('reply',[{'access_token':'new','expires_in':100},{'access_token':'new','refresh_token':'new','expires_in':0},{'error':'invalid_grant'}])
def test_refresh_failure_no_write_or_retry(tmp_path,reply):
    value=envelope();value['credential']['expires_at']=1;path=cache(tmp_path,value);before=path.read_bytes();calls=[]
    def handle(req):calls.append(req);return httpx.Response(200,json=reply)
    credential=Credential.open(path,http=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(AuthenticationRequired):credential.headers('http://localhost:8765','test')
    assert len(calls)==1 and path.read_bytes()==before


@pytest.mark.parametrize('kind',['redirect','network','oversize','non-object','invalid-json','http-error'])
def test_request_refusals(kind):
    calls=[]
    def handle(req):
        calls.append(req)
        if kind=='network':raise httpx.ReadTimeout('private-provider-output')
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://foreign.example'})
        if kind=='oversize':return httpx.Response(200,json={'large':'x'*2_100_001})
        if kind=='non-object':return httpx.Response(200,json=[])
        if kind=='invalid-json':return httpx.Response(200,content=b'private-provider-output')
        return httpx.Response(403,json={'error':'private-provider-output'})
    with pytest.raises(AuthenticationRequired) as error:
        auth.request('http://localhost/token',{},form=True,http=httpx.Client(transport=httpx.MockTransport(handle)))
    assert len(calls)==1 and 'private-provider-output' not in str(error.value)


def test_save_update_delete_order(tmp_path):
    path=cache(tmp_path);first=Credential.open(path);second=Credential.open(path)
    first.update({'access_token':'new','refresh_token':'new-refresh','expires_in':300})
    with pytest.raises(AuthenticationRequired):second.update({'access_token':'old','refresh_token':'old','expires_in':300})
    second.save();assert json.loads(path.read_text())['credential']['access_token']=='new'
    first.delete()
    for operation in (second.save,lambda:second.headers('http://localhost:8765','test'),lambda:second.update({'access_token':'old','refresh_token':'old','expires_in':300})):
        with pytest.raises(AuthenticationRequired):operation()
    assert not path.exists()
    fresh=envelope();fresh['family']='explicit-new-login';path.write_text(json.dumps(fresh));path.chmod(0o600)
    with pytest.raises(AuthenticationRequired):first.delete()
    assert path.exists()


@pytest.mark.parametrize('partial',[False,True])
def test_revoke_and_delete(tmp_path,partial):
    path=cache(tmp_path);calls=[]
    def handle(req):
        calls.append(req.url.path)
        if partial:return httpx.Response(403,json={'error':'denied'})
        return httpx.Response(200,json={} ) if req.url.path.endswith('/revoke') and req.url.path.startswith('/api') else httpx.Response(200)
    credential=Credential.open(path,http=httpx.Client(transport=httpx.MockTransport(handle)))
    if partial:
        with pytest.raises(AuthenticationRequired,match='Workspace grant revocation unconfirmed.*Provider revocation unconfirmed'):credential.revoke()
    else:credential.revoke()
    assert calls==['/api/v1/application-access/revoke','/revoke'] and not path.exists()


class Provider:
    def __init__(self,monkeypatch,errors=None,state=None,change=None):
        self.clock=0;self.sleeps=[];self.calls=[];self.call_times=[];self.errors=list(errors or ['authorization_pending','slow_down','tokens'])
        self.states=list(state or ['pending','approved']);self.change=change
        monkeypatch.setattr(auth.time,'monotonic',lambda:self.clock)
        monkeypatch.setattr(auth.time,'sleep',self.sleep)
        self.http=httpx.Client(transport=httpx.MockTransport(self.handle))
    def sleep(self,seconds):self.sleeps.append(seconds);self.clock+=seconds
    def handle(self,req):
        self.calls.append(req);self.call_times.append(self.clock)
        route=req.url.path
        if route.endswith('/config'):value={'issuer':'http://localhost:8765/provider','client_id':'synthetic-client'}
        elif route.endswith('openid-configuration'):value={'issuer':'http://localhost:8765/provider','device_authorization_endpoint':'http://localhost:8765/device','token_endpoint':'http://localhost:8765/token','revocation_endpoint':'http://localhost:8765/revoke'}
        elif route=='/device':value={'device_code':'synthetic-device','user_code':'CODE','verification_uri_complete':'http://localhost:8765/verify?code=CODE','expires_in':5000,'interval':5}
        elif route=='/token':
            event=self.errors.pop(0) if len(self.errors)>1 else self.errors[0]
            value={'access_token':'fresh-access','refresh_token':'fresh-refresh','expires_in':300} if event=='tokens' else {'error':event}
        elif route.endswith('/request'):
            assert json.loads(req.content)['label']=='Example'
            value={'id':'fresh-grant','confirmation_code':'APP','approval_url':'http://localhost:8765/approve?code=APP'}
        elif route.endswith('/status'):value={'state':self.states.pop(0) if len(self.states)>1 else self.states[0]}
        else:raise AssertionError(route)
        if self.change:self.change(route,value)
        return httpx.Response(200,json=value)


def test_device_login(tmp_path,monkeypatch):
    provider=Provider(monkeypatch);shown=[];path=tmp_path/'private'/'auth.json'
    credential=auth.device_login('http://localhost:8765','test',path=path,label='Example',http=provider.http,notify=lambda *args:shown.append(args))
    assert provider.sleeps==[5,5,10,5,5]
    assert len(shown)==2
    assert credential.headers('http://localhost:8765','test')['Authorization']=='Bearer fresh-access'
    value=json.loads(path.read_text());assert value['schema']==auth.SCHEMA and value['generation']==1
    assert 'access_token' not in value
    assert stat.S_IMODE(path.parent.stat().st_mode)==0o700


@pytest.mark.parametrize('error',['access_denied','expired_token','invalid_grant','authorization_pending'])
def test_device_refusal_and_timeout(tmp_path,monkeypatch,error):
    provider=Provider(monkeypatch,errors=[error]);path=tmp_path/'private'/'auth.json'
    with pytest.raises(AuthenticationRequired):auth.device_login('http://localhost:8765','test',path=path,http=provider.http,label='Example')
    assert not path.exists() and provider.clock<=600
    token_times=[t for req,t in zip(provider.calls,provider.call_times) if req.url.path=='/token']
    assert all(t<600 for t in token_times)
    if error!='authorization_pending':assert len(token_times)==1


@pytest.mark.parametrize('state',['denied','revoked','pending'])
def test_consent_refusal_and_timeout(tmp_path,monkeypatch,state):
    provider=Provider(monkeypatch,errors=['tokens'],state=[state]);path=tmp_path/'private'/'auth.json'
    with pytest.raises(AuthenticationRequired):auth.device_login('http://localhost:8765','test',path=path,http=provider.http,label='Example')
    assert not path.exists() and provider.clock<=605
    status_times=[t for req,t in zip(provider.calls,provider.call_times) if req.url.path.endswith('/status')]
    assert all(t<605 for t in status_times)
    if state!='pending':assert len(status_times)==1


@pytest.mark.parametrize('case',['issuer','device','token','revocation','verification','approval','lifetime'])
def test_device_endpoint_guards(tmp_path,monkeypatch,case):
    def change(route,value):
        if route.endswith('openid-configuration'):
            key={'issuer':'issuer','device':'device_authorization_endpoint','token':'token_endpoint','revocation':'revocation_endpoint'}.get(case)
            if key:value[key]='https://foreign.example/endpoint'
        if route=='/device' and case=='verification':value['verification_uri_complete']='https://foreign.example/verify'
        if route=='/device' and case=='lifetime':value['expires_in']=0
        if route.endswith('/request') and case=='approval':value['approval_url']='https://foreign.example/approve'
    provider=Provider(monkeypatch,errors=['tokens'],change=change);path=tmp_path/'private'/'auth.json'
    with pytest.raises(AuthenticationRequired):auth.device_login('http://localhost:8765','test',path=path,http=provider.http,label='Example')
    assert not path.exists()
    assert all(req.url.host=='localhost' for req in provider.calls)

@pytest.mark.parametrize('value',[None,'',True,0,-1,float('inf'),float('nan')])
def test_invalid_lifetime(value):
    with pytest.raises(AuthenticationRequired):auth._positive(value)

@pytest.mark.parametrize('value',[None,'','bad token','bad\r\ntoken',42])
def test_invalid_token(value):
    with pytest.raises(AuthenticationRequired):auth._token(value)


def test_atomic_save_failure_retains_previous(tmp_path,monkeypatch):
    path=cache(tmp_path);before=path.read_bytes();credential=Credential.open(path)
    def fail(fd):raise OSError('synthetic storage failure')
    monkeypatch.setattr(auth.os,'fsync',fail)
    with pytest.raises(OSError):credential.update({'access_token':'new','refresh_token':'new','expires_in':300})
    assert path.read_bytes()==before and list(path.parent.glob('.sdk-*'))==[]


def test_lock_file_modes(tmp_path):
    path=cache(tmp_path);lock=path.with_name(path.name+'.lock');lock.write_text('');lock.chmod(0o644)
    with pytest.raises(AuthenticationRequired):
        with auth._lock(path):pytest.fail('unsafe lock entered')


def test_verification_credentials_and_fragment():
    for value in ('https://user:pass@example.org/verify','https://example.org/verify#token','https://foreign.example/verify','http://example.org/verify'):
        with pytest.raises(AuthenticationRequired):auth._browser_url(value,'https://example.org')


def test_client_credential_scope(tmp_path):
    from ophiolite import Client
    path=cache(tmp_path);credential=Credential.open(path);sent=[]
    http=httpx.Client(transport=httpx.MockTransport(lambda request:sent.append(request)))
    with Client('http://localhost:8765','other',credential=credential,http=http) as client:
        with pytest.raises(AuthenticationRequired):client._get('/scientific',100)
    assert not sent


@pytest.mark.parametrize('value',[None,[],42,'invalid'])
def test_non_object_saved_credential(tmp_path,value):
    data=envelope();data['credential']=value;path=cache(tmp_path,data)
    with pytest.raises(AuthenticationRequired,match='Invalid saved authorization'):
        Credential.open(path)


def test_device_login_asks_for_capability_2_for_an_assistant_and_3_for_an_application(tmp_path,monkeypatch):
    sent=[]
    provider=Provider(monkeypatch);provider.change=lambda route,value:None
    original=provider.http._transport.handle_request
    def spy(req):
        if req.url.path.endswith('/request'):
            body=json.loads(req.content);sent.append(body)
            req=httpx.Request(req.method,req.url,headers=req.headers,content=json.dumps({**body,'label':'Example'}).encode())  # the helper checks the label
        return original(req)
    provider.http._transport.handle_request=spy
    auth.device_login('http://localhost:8765','test',path=tmp_path/'a'/'auth.json',http=provider.http,assistant='Notebook assistant',write=True,compute=True)
    assert sent==[{'project_id':'test','scopes':['read','write','compute'],'label':'Notebook assistant','capability':2}]
    sent.clear()
    auth.device_login('http://localhost:8765','test',path=tmp_path/'b'/'auth.json',http=provider.http,label='Example',compute=True)
    assert sent==[{'project_id':'test','scopes':['read'],'label':'Example','capability':3}]  # compute only for assistants; E22b: applications ask for capability 3
