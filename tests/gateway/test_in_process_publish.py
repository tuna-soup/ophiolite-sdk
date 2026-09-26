"""Real gateway application routes with synthetic principals; no live OIDC claim."""
import os
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import PermissionRefused,Unavailable,ValidationFailed


def client(web,persona,kind):
    credential=(Credential.bearer('oph_api_'+persona+':read,write') if kind=='delegate'
                else Credential.bearer('provider-'+persona,grant=web.grants[persona]))
    return Client('https://workspace.example','p',credential,web.c)


@pytest.mark.parametrize('kind',['delegate','grant'])
def test_sdk_alice_bob_eve_chain(web,kind):
    alice,bob,eve=[client(web,p,kind) for p in ('alice','bob','outsider')]
    binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK Alice',runners=['alice','bob'],command_id='sdk-configure',publication_profile='curve-edits/1')
    again=alice.configure(release_id=web.r['id'],curve='GR',name='SDK Alice',runners=['alice','bob'],command_id='sdk-configure',publication_profile='curve-edits/1')
    assert again.id==binding.id
    run=alice.start(binding,application_version='sdk-example/1',parameters={},command_id='sdk-start')
    original,view=run.input();assert view.values==[0,None,30]
    sent=[];web.c.event_hooks['request'].append(lambda r:sent.append(r.url.path))
    for changes in ([{'index':True,'value':2}],[{'index':0,'value':0}]):
        with pytest.raises(ValidationFailed):alice.publish(run,changes=changes)
    assert not sent
    receipt=alice.publish(run,changes=[{'index':0,'value':2}])
    assert receipt.identity=='alice' and receipt.upstream_write is False
    assert alice.download(receipt)!=original
    assert alice.grants(receipt).recipients==['alice']
    alice.share(receipt,read=['bob'],reuse=['bob'])
    assert set(alice.grants(receipt).recipients)=={'alice','bob'}
    b=bob.configure(receipt.output_reference.key,receipt.output_reference.revision,curve='GR',name='SDK Bob',command_id='sdk-bob',publication_profile='curve-edits/1')
    second=bob.start(b,application_version='sdk-example/1',parameters={},command_id='sdk-bob-run')
    _,values=second.input();assert values.values==[2,None,30]
    result=bob.publish(second,changes=[{'index':0,'value':3}]);assert result.identity=='bob'
    assert eve.results()==[]
    with pytest.raises((PermissionRefused,Unavailable)):eve.describe(receipt.output_reference.key,receipt.output_reference.revision,'GR')
    with pytest.raises(PermissionRefused):bob.share(receipt,read=['outsider'])
    bob.share(result,read=['alice'])
    assert result.output_reference.key in [item.asset_id for item in alice.results()]


def test_sdk_derived_curves_publication(web):
    alice=client(web,'alice','grant')
    binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK calculated',runners=['alice'],command_id='derived-cfg')
    run=alice.start(binding,application_version='derived/1',parameters={},command_id='derived-run')
    source,view=run.input()
    receipt=alice.publish(run,derived_curves=[{'mnemonic':'GR_NEW','unit':'gAPI','description':'Calculated synthetic example','values':[0,None,60]}])
    result=alice.read(receipt.output_reference.key,receipt.output_reference.revision,['GR','GR_NEW'])
    assert result.curves[0].values==view.values
    assert result.curves[1].values==[0,None,60]
    assert result.curves[1].axis==view.axis
    assert result.artifact==alice.download(receipt)


@pytest.mark.parametrize('kind',['delegate','grant'])
def test_sdk_work_folder_roundtrip(web,tmp_path,kind):
    alice=client(web,'alice',kind);work=alice.work_folder(tmp_path/'work')
    binding=work.configure(release_id=web.r['id'],curve='GR',name='Durable SDK',runners=['alice'])
    run=work.start(binding,application_version='derived/1',parameters={},script=b'# original synthetic calculation\n')
    raw,view=run.input()
    receipt=work.publish(run,derived_curves=[{'mnemonic':'GR_NEW','unit':'gAPI','description':'Calculated synthetic example','values':[0,None,60]}])
    downloaded=work.download(receipt)
    assert (tmp_path/'work/input.las').read_bytes()==raw
    assert (tmp_path/'work/result.las').read_bytes()==downloaded
    assert len(list((tmp_path/'work/requests').glob('*.meta.json')))==3
    assert len(list((tmp_path/'work/responses').glob('*.json')))==3
    assert alice.recover(tmp_path/'work') is None


@pytest.fixture
def anyio_backend():return 'asyncio'


@pytest.mark.anyio
async def test_sdk_async_work_folder_and_upload(web,tmp_path):
    import httpx
    from ophiolite.aio import AsyncClient
    from project_gateway.tests.test_applications import LAS
    credential=Credential.bearer('oph_api_alice:read,write')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url='https://workspace.example') as http:
        async with AsyncClient('https://workspace.example','p',credential,http) as alice:
            uploaded=await alice.work_folder(tmp_path/'upload').upload_las(LAS.encode(),name='SDK original',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True)
            assert uploaded.can_share
            await alice.share(uploaded,read=['bob'],reuse=['bob'])
            assert 'bob' in (await alice.grants(uploaded)).recipients
            work=alice.work_folder(tmp_path/'calculate')
            binding=await work.configure(uploaded.asset_id,uploaded.revision,curve='GR',name='Async calculation')
            run=await work.start(binding,application_version='async/1',parameters={})
            raw,view=await run.input();assert raw==LAS.encode()
            receipt=await work.publish(run,derived_curves=[{'mnemonic':'GR_NEW','unit':'gAPI','description':'Async derived curve','values':[0,None,60]}])
            assert await work.download(receipt)
            assert await alice.recover(tmp_path/'calculate') is None
            assert (await alice.result_preview(receipt)).rows[0]['GR_NEW']==0
            downloaded,parsed,result=await alice.result_download(receipt)
            assert parsed.output_reference==receipt.output_reference and result.id==receipt.publication_id
            assert downloaded==await alice.download(receipt)


def test_sdk_restricted_result_models_do_not_restore_parent(web):
    import json
    from project_gateway.tests.test_applications import LAS
    alice=client(web,'alice','delegate');bob=client(web,'bob','grant')
    original=alice.upload_las(LAS.encode(),name='Private original',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True)
    binding=alice.configure(original.asset_id,original.revision,curve='GR',name='Shared calculation',command_id='private-parent')
    run=alice.start(binding,application_version='derived/1',parameters={},command_id='private-parent-run');run.input()
    receipt=alice.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Shared result','values':[0,None,60]}])
    alice.share(receipt,read=['bob'])
    summaries=[item for item in bob.results() if item.asset_id==receipt.publication_id];assert len(summaries)==1
    preview=bob.result_preview(receipt);raw,result,visible=bob.result_download(receipt)
    assert raw==alice.download(receipt) and visible.input is None
    assert preview.rows[0]['NEW']==0 and preview.rows[1]['NEW'] is None
    public=json.dumps([obj.model_dump(by_alias=True,exclude_unset=True) for obj in (summaries[0],preview,result,visible)])
    assert original.asset_id not in public and original.revision not in public
    assert 'parent' not in result.manifest.model_dump(by_alias=True,exclude_unset=True)


@pytest.mark.parametrize('kind',['delegate','grant'])
def test_sdk_conditional_share_against_the_gateway(web,kind):
    """E7: the snapshot generation guards the replace; a stale retry cannot undo a revocation."""
    from ophiolite.errors import IntegrityConflict
    alice=client(web,'alice',kind)
    binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK conditional',runners=['alice'],command_id='sdk-cond',publication_profile='curve-edits/1')
    run=alice.start(binding,application_version='sdk-example/1',parameters={},command_id='sdk-cond-run');run.input()
    receipt=alice.publish(run,changes=[{'index':0,'value':2}])
    snapshot=alice.grants(receipt);assert snapshot.generation==1
    alice.share(receipt,read=['bob'],expected_generation=1,command_id='add-bob')
    assert alice.share(receipt,read=['bob'],expected_generation=1,command_id='add-bob').recipients==['alice','bob']  # idempotent replay
    alice.share(receipt,read=[],expected_generation=2,command_id='revoke-bob')
    with pytest.raises(IntegrityConflict):alice.share(receipt,read=['bob'],expected_generation=1,command_id='add-bob')
    assert alice.grants(receipt).recipients==['alice'] and alice.grants(receipt).generation==3
