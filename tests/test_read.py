import hashlib
import json
from urllib.parse import quote
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite import _core
from ophiolite.errors import *
from test_validate import encoded


def response_transport(fixture,*,other=False,corrupt_artifact=False):
    d,raw,artifact=fixture();calls=[]
    def handler(request):
        calls.append(request.url.raw_path.decode())
        if '/representations/' in request.url.path:
            body=raw if request.url.path.endswith('/curve') else artifact
            if corrupt_artifact and request.url.path.endswith('/las'):body+=b'x'
            return httpx.Response(200,content=body)
        return httpx.Response(200,json=d)
    return d,raw,artifact,calls,httpx.MockTransport(handler)


def test_exact_read_and_private_save(fixture,tmp_path):
    d,raw,artifact,calls,transport=response_transport(fixture)
    with httpx.Client(transport=transport) as http:
        client=Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http)
        data=client.read(d['asset_id'],d['revision'],['GR'])
    assert data.artifact==artifact
    assert data.curves[0].axis==[100,101,102,103,104]
    assert data.curves[0].values==[0,10,None,30,40]
    data.save(tmp_path/'out')
    assert (tmp_path/'out/artifact.las').read_bytes()==artifact
    assert (tmp_path/'out').stat().st_mode&0o777==0o700
    assert all(p.stat().st_mode&0o777==0o600 for p in (tmp_path/'out').iterdir())
    assert len(calls)==3
    with pytest.raises(ValueError):data.save(tmp_path/'out')


def test_requested_curve_substitution(fixture):
    d,raw,artifact=fixture();v=json.loads(raw);v['curve']='RHOB';d['scientific']['curve']='RHOB';raw=encoded(d,v)
    # Internally valid alternative curve: the request binding alone must refuse.
    from ophiolite.validate import pair
    pair(d,raw)
    with pytest.raises(VerificationFailed,match='Requested curve'):_core.verify_descriptor(d,d['project_id'],d['asset_id'],d['revision'],'GR')
    with pytest.raises(VerificationFailed,match='Requested curve'):_core.verify_pair(d,raw,artifact,'GR')

@pytest.mark.parametrize('field',['project_id','asset_id','revision'])
def test_request_identity(fixture,field):
    d,_,_=fixture();original=dict(d);d[field]='different'
    with pytest.raises(VerificationFailed):_core.verify_descriptor(d,original['project_id'],original['asset_id'],original['revision'],'GR')


def test_multicurve_one_artifact(fixture):
    first,raw,artifact=fixture();requests=[]
    def handler(request):
        requests.append(request.url.path)
        selected=request.url.params['curve'];d=json.loads(json.dumps(first));v=json.loads(raw)
        d['scientific']['curve']=selected;v['curve']=selected
        body=encoded(d,v)
        if '/representations/' in request.url.path:
            return httpx.Response(200,content=body if request.url.path.endswith('/curve') else artifact)
        return httpx.Response(200,json=d)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        data=Client('http://localhost',first['project_id'],http=http).read(first['asset_id'],first['revision'],['GR','RHOB'])
    assert [c.curve for c in data.curves]==['GR','RHOB']
    assert sum(path.endswith('/las') for path in requests)==1


def test_second_descriptor_artifact_mismatch(fixture):
    d,raw,artifact=fixture();v=json.loads(raw);d['representations'][0]['sha256']='0'*64;v['source_sha256']='0'*64
    raw=encoded(d,v)
    with pytest.raises(VerificationFailed,match='checksum'):_core.verify_pair(d,raw,artifact,'GR')

@pytest.mark.parametrize('status,kind',[(401,AuthenticationRequired),(403,PermissionRefused),(404,Unavailable),(409,IntegrityConflict),(413,CapacityExceeded),(400,Refused),(422,Incompatible),(503,Busy),(302,Unavailable)])
def test_status_categories(fixture,status,kind):
    d,_,_=fixture();calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,headers={'Location':'https://foreign.invalid'},text='secret-provider-body')
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(kind) as error:Client('http://localhost',d['project_id'],http=http).describe(d['asset_id'],d['revision'],'GR')
    assert 'secret-provider-body' not in str(error.value)
    assert error.value.status==status and error.value.code
    assert error.value.retryable==(status==503)
    assert len(calls)==(3 if status==503 else 1)


def test_catalogue_cursor_and_bound():
    calls=[]
    def repeated(request):
        calls.append(request)
        assert len(calls)<=2, 'Client sent another request after a repeated cursor'
        return httpx.Response(200,json={'items':[],'next_cursor':'same'})
    with httpx.Client(transport=httpx.MockTransport(repeated)) as http:
        with pytest.raises(VerificationFailed,match='cursor'):list(Client('http://localhost','p',http=http).assets())
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'x'*12))) as http:
        with pytest.raises(VerificationFailed,match='bounded'):Client('http://localhost','p',http=http)._get('/path',10)


def test_interpretation_warning_and_strict(fixture):
    d,raw,artifact=fixture('capture');d['recorded_interpretation']['lasio_version']='different';d['interpretation_evidence']='recorded-differs'
    with pytest.warns(InterpretationDiffers):_core.verify_pair(d,raw,artifact,'GR')
    with pytest.raises(InterpretationChanged) as error:_core.verify_pair(d,raw,artifact,'GR',strict_interpretation=True)
    assert error.value.details=={'recorded':d['recorded_interpretation'],'live':d['interpretation']}

@pytest.mark.parametrize('url',['http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com?a=1','file:///tmp/example'])
def test_origin_refusal(url):
    with pytest.raises(ValueError):Client(url,'project')


def test_recorded_gateway_and_frozen_output(tmp_path):
    from pathlib import Path
    from ophiolite.testing import FixtureTransport
    recording=Path(__file__).parent/'recordings/synthetic-read.json'
    transport=FixtureTransport(recording)
    with httpx.Client(transport=transport) as http:
        client=Client('http://localhost','p',http=http)
        item=next(client.assets());result=client.read(item['asset_id'],item['revision'],['GR'])
        result.save(tmp_path/'saved')
    assert transport.index==4
    assert result.curves[0].axis==[100,101,102] and result.curves[0].values==[0,None,30]
    import base64
    original=json.loads(base64.b64decode(json.loads(recording.read_text())[1]['body_base64']))
    assert json.loads((tmp_path/'saved/descriptor.json').read_text())==original
    assert 'acquisition' not in original

@pytest.mark.parametrize('field,value,message',[
 ('url',None,'service origin'),('project','','Choose a project'),
])
def test_constructor_validation(field,value,message):
    args={'url':'http://localhost','project':'p'};args[field]=value
    with pytest.raises(ValueError,match=message):Client(**args)

@pytest.mark.parametrize('token,grant',[(None,None),('',None),('two tokens',None),('safe',''),('safe',42),('safe','two grants')])
def test_explicit_credential_validation(token,grant):
    with pytest.raises(ValueError,match='credential|grant'):Credential.bearer(token,grant=grant)

@pytest.mark.parametrize('case',['schema','pair','selection'])
def test_configuration_validation(tmp_path,case):
    data={'schema':'ophiolite.read-configuration/1','url':'http://localhost','project':'p'}
    if case=='schema':data['schema']='unsupported/1'
    if case=='pair':data['asset']='a'
    if case=='selection':data.update(asset='a',revision='r',curve='')
    path=tmp_path/'config.json';path.write_text(json.dumps(data))
    with pytest.raises(ValueError):Client.from_configuration(path)

@pytest.mark.parametrize('arguments',[('a','r',''),('','r','GR'),('a','','GR')])
def test_no_inferred_selection(arguments):
    with Client('http://localhost','p') as client:
        with pytest.raises(ValueError,match='Choose an asset'):client._path(*arguments)

@pytest.mark.parametrize('curves',[[],['GR','GR'],'GR'])
def test_distinct_curve_selection(curves):
    with Client('http://localhost','p') as client:
        with pytest.raises(ValueError,match='distinct'):client.read('a','r',curves)


def test_catalogue_shape():
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'items':None}))) as http:
        with pytest.raises(VerificationFailed,match='catalogue'):list(Client('http://localhost','p',http=http).assets())


def test_fixture_transport_rejects_extra_or_wrong_request():
    from ophiolite.testing import FixtureTransport
    with pytest.raises(AssertionError,match='additional'):FixtureTransport([]).respond(httpx.Request('GET','http://localhost/a'))
    fixture=FixtureTransport([{'method':'GET','path':'/a','status':200,'body_base64':''}])
    with pytest.raises(AssertionError,match='differs'):fixture.respond(httpx.Request('GET','http://localhost/b'))


def test_busy_retry_evidence(monkeypatch):
    import ophiolite.client as module
    sleeps=[];calls=[];monkeypatch.setattr(module.time,'sleep',sleeps.append)
    def handler(request):calls.append(request);return httpx.Response(503,headers={'Retry-After':'7'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(Busy) as error:Client('http://localhost','p',http=http)._get('/path',1)
    assert error.value.retry_after==7 and error.value.retryable and error.value.status==503
    assert len(calls)==3 and sleeps==[7,7]


def test_evidence_error_has_human_message_and_technical_code():
    error=VerificationFailed('evidence-inconsistent')
    assert error.code=='evidence-inconsistent'
    assert 'evidence-inconsistent' not in str(error)
    assert 'reader history' in error.message
