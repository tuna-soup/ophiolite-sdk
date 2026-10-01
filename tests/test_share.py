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



def routed(answers, calls):
    """A transport that answers per route and records (route, body): a wrong route cannot pass unnoticed."""
    def handle(request):
        route = request.url.path.split('/projects/p/', 1)[1]
        calls.append((route, json.loads(request.content or b'{}')))
        answer = answers.get(route)
        if answer is None: return httpx.Response(404, json={'error': 'not found', 'code': 'not-found'})
        return httpx.Response(answer[0], json=answer[1]) if isinstance(answer, tuple) else httpx.Response(200, json=answer)
    return httpx.MockTransport(handle)


INFO = {'asset_id': 'pub', 'revision': 'r2', 'name': 'Surface', 'owner': 'alice', 'can_share': True, 'permitted_audience': ['bob'],
        'recipients': ['bob'], 'reuse_recipients': [], 'grants_generation': 3, 'display': {}, 'via': None}


@pytest.mark.parametrize('shape', ['catalogue', 'descriptor'])
def test_a_derived_publication_from_the_catalogue_reads_and_shares_through_publications(shape):
    """H5b (G2-5): an item carrying `ophiolite:derived` that is not an application result is a derived publication:
    grants() reads publications/info and share() writes publications/share, with the same target."""
    asset = {'asset_id': 'pub', 'revision': 'r2', 'authority': 'ophiolite:derived'}
    if shape == 'descriptor': asset = {**asset, 'name': 'Surface', 'profile': 'triangulated-surface/1'}
    calls = []
    shared = {**INFO, 'recipients': [], 'grants_generation': 4, 'sharing_contract': 'conditional'}
    answers = {'applications/result-list': {'results': []}, 'publications/info': INFO, 'publications/share': shared}
    with httpx.Client(transport=routed(answers, calls)) as http:
        client = Client('http://localhost', 'p', http=http)
        got = client.grants(asset)
        assert (got.recipients, got.generation) == (['bob'], 3) and [c[0] for c in calls] == ['applications/result-list', 'publications/info']
        assert calls[1][1] == {'project_id': 'p', 'asset_id': 'pub'}
        calls.clear()
        after = client.share(asset, read=[], expected_generation=3, command_id='c1')
        assert after.recipients == [] and calls[-1][0] == 'publications/share'
        assert {k: calls[-1][1][k] for k in ('asset_id', 'audience', 'expected_generation')} == {'asset_id': 'pub', 'audience': [], 'expected_generation': 3}


def test_an_earlier_version_or_another_owner_is_refused_and_application_results_keep_their_route():
    from ophiolite.errors import Refused
    calls = []
    answers = {'applications/result-list': {'results': []}, 'publications/info': INFO}
    with httpx.Client(transport=routed(answers, calls)) as http:
        client = Client('http://localhost', 'p', http=http)
        with pytest.raises(Refused, match='current version'): client.grants({'asset_id': 'pub', 'revision': 'r1', 'authority': 'ophiolite:derived'})
    calls = []
    answers = {'applications/result-list': {'results': []}, 'publications/info': {**INFO, 'can_share': False}}
    with httpx.Client(transport=routed(answers, calls)) as http:
        with pytest.raises(PermissionRefused): Client('http://localhost', 'p', http=http).grants({'asset_id': 'pub', 'revision': 'r2', 'authority': 'ophiolite:derived'})
    calls = []
    entry = {'asset_id': 'run', 'revision': 'x', 'can_share': True, 'recipients': [], 'reuse_recipients': []}
    with httpx.Client(transport=routed({'applications/result-list': {'results': [entry]}}, calls)) as http:
        assert Client('http://localhost', 'p', http=http).grants({'asset_id': 'run', 'revision': 'x', 'authority': 'ophiolite:derived'}).recipients == []
    assert [c[0] for c in calls] == ['applications/result-list']  # an application result never touches publications
    calls = []
    with httpx.Client(transport=routed({'applications/result-list': {'results': []}, 'publications/info': {**INFO, 'asset_id': 'other'}}, calls)) as http:
        with pytest.raises(VerificationFailed): Client('http://localhost', 'p', http=http).grants({'asset_id': 'pub', 'revision': 'r2', 'authority': 'ophiolite:derived'})


def test_a_publication_share_survives_a_lost_answer_and_a_version_appended_meanwhile():
    """H5b: sharing a derived publication shares every version; a version appended between lookup and share is the same
    publication (no false refusal after the change was applied); a lost answer is replayed with the same command."""
    from ophiolite.errors import Refused
    asset = {'asset_id': 'pub', 'revision': 'r2', 'authority': 'ophiolite:derived'}
    calls, state = [], {'lost': True}
    def handle(request):
        route = request.url.path.split('/projects/p/', 1)[1]; body = json.loads(request.content or b'{}'); calls.append((route, body))
        if route == 'applications/result-list': return httpx.Response(200, json={'results': []})
        if route == 'publications/info': return httpx.Response(200, json=INFO)
        if route == 'publications/share':
            if state['lost']: state['lost'] = False; return httpx.Response(502, json={'error': 'lost'})
            return httpx.Response(200, json={**INFO, 'revision': 'r3', 'recipients': [], 'grants_generation': 4, 'sharing_contract': 'conditional'})
        return httpx.Response(404, json={})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        after = Client('http://localhost', 'p', http=http).share(asset, read=[], expected_generation=3, command_id='same')
    shares = [b for r, b in calls if r == 'publications/share']
    assert len(shares) == 2 and shares[0] == shares[1] and after.recipients == [] and after.revision == 'r3'
    assert 'every version' in Client.share.__doc__
    with httpx.Client(transport=routed({'applications/result-list': {'results': []}, 'publications/info': INFO}, [])) as http:
        with pytest.raises(Refused, match='every version'): Client('http://localhost', 'p', http=http).grants({**asset, 'revision': 'r1'})
