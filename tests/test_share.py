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


@pytest.mark.parametrize('area',['applications','las-uploads'])
@pytest.mark.parametrize('failure',['connection','busy'])
def test_share_ambiguous_outcome_never_replays(area,failure):
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        asset=result(client) if area=='applications' else client.upload_las(server.handler.original,name='Synthetic',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True)
        handler=server.handler;failed=[]
        if failure=='connection':server.drop('share',1)
        else:
            def busy(method,path,raw,headers):
                answer=handler(method,path,raw,headers)
                if path.endswith('/share') and not failed:failed.append(True);return 503,{'error':'busy after commit'}
                return answer
            server.handler=busy
        with pytest.raises(ShareOutcomeUnknown,match='Read the current recipients first') as error:client.share(asset,read=['bob'])
        assert error.value.retryable is False
        assert handler.mutations['share']==1
        assert len([request for request in server.requests if request['path'].endswith('/share')])==1
        assert client.grants(asset).recipients==['bob']
        # A replay would succeed and replace the grant set again: it is deliberately
        # a new, explicit decision after reading the current recipients.
        client.share(asset,read=['bob'],reuse=['bob'])
        assert handler.mutations['share']==2


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
            with pytest.raises(ValidationFailed):client.share({'asset_id':'r','revision':'v','authority':'ophiolite:derived'},read=read,reuse=reuse)
    assert requests==[]
