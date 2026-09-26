import json
import httpx
import pytest
from ophiolite import Client
from ophiolite import application_transport as policy,publish
from ophiolite.errors import CapacityExceeded,VerificationFailed,Refused,ValidationFailed


@pytest.mark.parametrize('raw',[b'[]',b'not json',b'{"x": NaN}',b'\xff'])
def test_invalid_response(raw):
    with pytest.raises(VerificationFailed):policy.decode(raw)


@pytest.mark.parametrize('value',['-1','61','nan','inf','not a number','1'])
def test_retry_delay_bounded(value):
    assert policy.delay(httpx.Response(503,headers={'Retry-After':value}))==(1 if value=='1' else 0)


def test_busy_start_replays_saved_request(tmp_path,monkeypatch):
    from ophiolite import Credential
    from ophiolite.testing import fixture_server
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work');binding=work.configure('synthetic','revision',curve='GR',name='Example')
        transport=client.http;attempts=[];sleep=[]
        original=server.handler
        def handler(method,path,raw,headers):
            if path.endswith('/start'):
                attempts.append(raw)
                if len(attempts)==1:return 503,{'error':'busy'}
            return original(method,path,raw,headers)
        server.handler=handler
        # Fixture server has no custom-header shortcut; the HTTP policy is also
        # tested with an actual Retry-After header below.
        work.start(binding,application_version='test/1',parameters={})
        saved=next((work.path/'requests').glob('*start.json')).read_bytes()
        assert attempts==[saved,saved]


def test_retry_after_header_is_observed(monkeypatch):
    sleeps=[];requests=[]
    def handler(request):
        requests.append(request.content)
        return httpx.Response(503,headers={'Retry-After':'1'}) if len(requests)==1 else httpx.Response(200,json={'ok':True})
    monkeypatch.setattr('ophiolite.client.time.sleep',sleeps.append)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client=Client('http://localhost','p',http=http)
        assert client._post('applications','options',{})=={'ok':True}
    assert sleeps==[1] and requests[0]==requests[1]


def test_response_size_and_redirect_refused(monkeypatch):
    monkeypatch.setattr(policy,'MAX_RESPONSE',4)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'{"long":123}'))) as http:
        with pytest.raises(CapacityExceeded):Client('http://localhost','p',http=http)._post('applications','options',{})
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(307,headers={'Location':'https://other.example'}))) as http:
        with pytest.raises(Refused):Client('http://localhost','p',http=http)._post('applications','options',{})


@pytest.mark.parametrize('damage',['empty','large','rights','name','attribution','recipient','header'])
def test_upload_local_limits_send_nothing(tmp_path,damage):
    called=[]
    source=b'~Version\n';options=dict(name='Synthetic',attribution='Original fixture',audience=['alice'],rights_confirmed=True)
    if damage=='empty':source=b''
    if damage=='large':
        path=tmp_path/'large.las';path.write_bytes(b'x'*(publish.MAX_UPLOAD+1));source=path
    if damage=='rights':options['rights_confirmed']=False
    if damage=='name':options['name']=' '
    if damage=='attribution':options['attribution']=' '
    if damage=='recipient':options['audience']=['x'*161]
    if damage=='header':options['audience']=[str(i)+'x'*150 for i in range(100)]
    with httpx.Client(transport=httpx.MockTransport(lambda request:called.append(request))) as http:
        client=Client('http://localhost','p',http=http)
        with pytest.raises(ValidationFailed):client.upload_las(source,**options)
    assert not called
