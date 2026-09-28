import json
import httpx
import pytest
from ophiolite import Client,Credential
from ophiolite.errors import ShareOutcomeUnknown,PermissionRefused,VerificationFailed,ValidationFailed
from ophiolite.testing import fixture_server


def result(client):
    binding=client.configure('synthetic','revision',curve='GR',name='Example')
    run=client.start(binding,application_version='synthetic/1',parameters={});_,view=run.input()
    return client.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Synthetic','values':[0]*len(view.values)}])


def test_share_requires_the_reviewed_generation():
    """E7 cutover: there is no unconditional share() any more; a server refuses one sent raw (428)."""
    import inspect
    assert inspect.signature(Client.share).parameters['expected_generation'].default is inspect.Parameter.empty
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        asset=client.upload_las(server.handler.original,name='Synthetic',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True)
        with pytest.raises(TypeError):client.share(asset,read=['bob'])
        raw=client.http.post(server.url+'/api/v1/projects/p/las-uploads/share',json={'project_id':'p','asset_id':asset.asset_id,'audience':['bob']},headers=client._headers())
        assert raw.status_code==428 and raw.json()['code']=='condition-required' and server.handler.mutations.get('share',0)==0


@pytest.mark.parametrize('case',['missing','revision','non-owner','fields','empty','changed'])
def test_result_grants_exact_owner_selection(case):
    asset={'asset_id':'result','revision':'exact','authority':'ophiolite:derived'}
    entry={'asset_id':'result','revision':'exact','can_share':True,'recipients':[],'reuse_recipients':[]}
    if case=='revision':entry['revision']='other'
    if case=='non-owner':entry['can_share']=False
    if case=='fields':entry.pop('reuse_recipients')
    if case=='changed':entry.update(recipients=['bob'],reuse_recipients=['bob'])
    body={'results':[] if case=='missing' else [entry]}
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=body))) as http:
        client=Client('http://localhost','p',http=http)
        if case in ('empty','changed'):
            assert client.grants(asset).recipients==([] if case=='empty' else ['bob'])
        else:
            with pytest.raises((PermissionRefused,VerificationFailed)):client.grants(asset)


def test_invalid_share_sends_nothing():
    requests=[]
    with httpx.Client(transport=httpx.MockTransport(lambda request:requests.append(request))) as http:
        client=Client('http://localhost','p',http=http)
        for read,reuse in (([],['bob']),(['bob','bob'],[]),([True],[])):
            with pytest.raises(ValidationFailed):client.share({'asset_id':'r','revision':'v','authority':'ophiolite:derived'},read=read,reuse=reuse,expected_generation=1)
    assert requests==[]


def asset_for(client,server,area):
    return result(client) if area=='applications' else client.upload_las(server.handler.original,name='Synthetic',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True)


@pytest.mark.parametrize('area',['applications','las-uploads'])
def test_conditional_share_replays_once_after_lost_response(area):
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        asset=asset_for(client,server,area);handler=server.handler
        snapshot=client.grants(asset);assert snapshot.generation==1
        server.drop('share',1)
        shared=client.share(asset,read=['bob'],expected_generation=snapshot.generation)
        assert handler.mutations['share']==1 and client.grants(asset).generation==2
        import base64
        sent=[json.loads(base64.b64decode(r['body_base64'])) for r in server.requests if r['path'].endswith('/share')]
        assert len(sent)==2 and sent[0]==sent[1] and sent[0]['expected_generation']==1 and sent[0]['command_id']
        assert shared.asset_id==snapshot.asset_id and shared.revision==snapshot.revision


@pytest.mark.parametrize('area',['applications','las-uploads'])
def test_conditional_replay_cannot_undo_a_revocation(area):
    from ophiolite.errors import IntegrityConflict
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        asset=asset_for(client,server,area);handler=server.handler;key='asset_id' if area=='las-uploads' else 'id'
        ident=client.grants(asset).asset_id;state=[]
        def lost_then_revoked(method,path,raw,headers):
            answer=handler(method,path,raw,headers)
            if path.endswith('/share') and not state:
                state.append(1)
                # Someone else revokes Bob before the lost response is retried.
                handler(method,path,json.dumps({'project_id':'p',key:ident,'audience':[],'reuse_audience':[],'expected_generation':2,'command_id':'revoke'}).encode(),headers)
                return 503,{'error':'lost'}
            return answer
        server.handler=lost_then_revoked
        with pytest.raises(IntegrityConflict,match='recipients changed'):client.share(asset,read=['bob'],expected_generation=1)
        server.handler=handler
        assert client.grants(asset).recipients==[] and handler.mutations['share']==2


def test_conditional_share_refuses_on_a_server_without_generations():
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        asset=asset_for(client,server,'las-uploads');server.handler.conditional=False
        assert client.grants(asset).generation is None
        with pytest.raises(Exception,match='does not support conditional sharing'):client.share(asset,read=['bob'],expected_generation=1)
        assert server.handler.mutations.get('share',0)==0


@pytest.mark.parametrize('bad',[True,-1,'1',1.0])
def test_invalid_generation_sends_nothing(bad):
    requests=[]
    with httpx.Client(transport=httpx.MockTransport(lambda request:requests.append(request))) as http:
        client=Client('http://localhost','p',http=http)
        with pytest.raises(Exception,match='expected_generation'):
            client.share({'asset_id':'r','revision':'v','authority':'ophiolite:derived'},read=['bob'],expected_generation=bad)
    assert requests==[]

