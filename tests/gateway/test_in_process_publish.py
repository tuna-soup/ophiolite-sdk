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
    alice.share(receipt,read=['bob'],reuse=['bob'],expected_generation=alice.grants(receipt).generation)
    assert set(alice.grants(receipt).recipients)=={'alice','bob'}
    b=bob.configure(receipt.output_reference.key,receipt.output_reference.revision,curve='GR',name='SDK Bob',command_id='sdk-bob',publication_profile='curve-edits/1')
    second=bob.start(b,application_version='sdk-example/1',parameters={},command_id='sdk-bob-run')
    _,values=second.input();assert values.values==[2,None,30]
    result=bob.publish(second,changes=[{'index':0,'value':3}]);assert result.identity=='bob'
    assert eve.results()==[]
    with pytest.raises((PermissionRefused,Unavailable)):eve.describe(receipt.output_reference.key,receipt.output_reference.revision,'GR')
    with pytest.raises(PermissionRefused):bob.share(receipt,read=['outsider'],expected_generation=bob.grants(receipt).generation)
    bob.share(result,read=['alice'],expected_generation=bob.grants(result).generation)
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
            await alice.share(uploaded,read=['bob'],reuse=['bob'],expected_generation=(await alice.grants(uploaded)).generation)
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
    alice.share(receipt,read=['bob'],expected_generation=alice.grants(receipt).generation)
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


@pytest.mark.parametrize('kind',['delegate','grant'])
def test_sdk_new_version_history_and_stale_parent(web,kind):
    """E8: the reviewed revision is the expected parent; a stale one is refused."""
    from ophiolite.errors import IntegrityConflict
    alice=client(web,'alice',kind)
    def publish(command,value,**kw):
        binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK versions',runners=['alice'],command_id='v-'+command,publication_profile='curve-edits/1')
        run=alice.start(binding,application_version='sdk-example/'+command,parameters={},command_id='v-run-'+command);run.input()
        return alice.publish(run,changes=[{'index':0,'value':value}],**kw)
    first=publish('1',2)
    second=publish('2',4,new_version_of=first)
    assert second.output_reference.key==first.output_reference.key and second.output_reference.revision_number==2
    history=alice.history(second)
    assert [(h.number,h.revision) for h in history.revisions]==[(1,first.output_reference.revision),(2,second.output_reference.revision)]
    assert history.revisions[1].parent_revision==first.output_reference.revision
    with pytest.raises(IntegrityConflict):publish('3',6,new_version_of=first)
    assert alice.download(first)!=alice.download(second)


@pytest.mark.parametrize('kind',['delegate','grant'])
def test_sdk_export_freezes_exact_revisions_and_applies_permissions(web,kind,tmp_path):
    """E18: export through the ordinary exact-read path; refusals publish nothing."""
    from ophiolite.bundle import open_bundle
    from ophiolite.errors import PermissionRefused,Unavailable
    from project_gateway.stages import Stages
    alice,bob=client(web,'alice',kind),client(web,'bob',kind)
    def publish(command,value,index=0,**kw):
        binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK export',runners=['alice'],command_id='x-'+command,publication_profile='curve-edits/1')
        run=alice.start(binding,application_version='sdk-export/'+command,parameters={},command_id='x-run-'+command);run.input()
        return alice.publish(run,changes=[{'index':index,'value':value}],**kw)
    first=publish('1',2);second=publish('2',0,index=2,new_version_of=first)
    key,r1,r2=first.output_reference.key,first.output_reference.revision,second.output_reference.revision
    opened=alice.export([(key,r1,['GR']),(key,r2,['GR'])],tmp_path/'both')
    assert [(a.revision,a.history['number']) for a in opened.assets]==[(r1,1),(r2,2)]
    if kind=='grant':assert opened.manifest['observations']=={'groups_omitted':'This credential may not list result groups'}
    assert opened.assets[1].curves['GR'].values[2]==0.0 and opened.assets[1].curves['GR'].values[1] is None  # zero stays zero, missing stays missing
    assert opened.assets[0].original==alice.download(first) and opened.manifest['groups'] is None
    # A later version does not retarget an earlier selection.
    publish('3',5,index=2,new_version_of=second)
    again=alice.export([(key,r1,['GR'])],tmp_path/'later')
    assert again.assets[0].original==opened.assets[0].original and again.assets[0].history['count']==3
    # Bob cannot read Alice's result: nothing is written. Once shared, he can export it.
    with pytest.raises((PermissionRefused,Unavailable)):bob.export([(key,r1,['GR'])],tmp_path/'bob')
    assert not (tmp_path/'bob').exists()
    grants=alice.grants(second);alice.share(second,read=['bob'],expected_generation=grants.generation)
    assert bob.export([(key,r2,['GR'])],tmp_path/'bob').assets[0].curves['GR'].values[2]==0.0
    # Revoking Bob refuses his next export and publishes nothing.
    alice.share(second,read=[],expected_generation=alice.grants(second).generation)
    with pytest.raises((PermissionRefused,Unavailable)):bob.export([(key,r2,['GR'])],tmp_path/'bob-revoked')
    assert not (tmp_path/'bob-revoked').exists()
    # The exported bundle is read by a separately installed SDK with no network or credentials.
    import os,subprocess,json as _json
    python=os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if python:
        code=('import socket,sys,json;socket.socket=None;from ophiolite.bundle import open_bundle;'
              'b=open_bundle(sys.argv[1]);c=b.assets[1].curves["GR"];print(json.dumps([c.values,[a.revision for a in b.assets]]))')
        done=subprocess.run([python,'-I','-c',code,str(tmp_path/'both')],capture_output=True,text=True,env={'PATH':os.environ.get('PATH',''),'HOME':str(tmp_path)},timeout=60)
        assert done.returncode==0,done.stderr
        values,revisions=_json.loads(done.stdout);assert values[2]==0.0 and values[1] is None and revisions==[r1,r2]
    # Withdrawing one selected revision fails the whole export.
    Stages(web.a).call('transition',{'project_id':'p','asset_id':key,'revision':r1,'action':'withdraw','expected_generation':0,'reason':'Superseded'},'alice')
    with pytest.raises((PermissionRefused,Unavailable)):alice.export([(key,r2,['GR']),(key,r1,['GR'])],tmp_path/'withdrawn')
    assert not (tmp_path/'withdrawn').exists() and not list(tmp_path.glob('.withdrawn.staging-*'))
    assert open_bundle(tmp_path/'both').assets[0].revision==r1  # an earlier export stays readable offline


@pytest.mark.parametrize('kind',['delegate'])
def test_sdk_shares_a_result_through_any_of_its_versions(web,kind):
    alice,bob=client(web,'alice',kind),client(web,'bob',kind)
    def publish(command,value,**kw):
        binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK share versions',runners=['alice'],command_id='s-'+command,publication_profile='curve-edits/1')
        run=alice.start(binding,application_version='sdk-share/'+command,parameters={},command_id='s-run-'+command);run.input()
        return alice.publish(run,changes=[{'index':0,'value':value}],**kw)
    first=publish('1',2);second=publish('2',4,new_version_of=first)
    snapshot=alice.grants(second)
    alice.share(second,read=['bob'],expected_generation=snapshot.generation)
    assert [h.number for h in bob.history(second).revisions]==[1,2]


@pytest.mark.parametrize('kind',['delegate'])
def test_sdk_reads_and_exports_typed_data(web,kind,tmp_path):
    """E11: tops (explicitly associated with an uploaded log), a survey and a grid read exactly and export offline."""
    from project_gateway.las_uploads import LASUploads,Upload,WellLog
    from project_gateway.tests.test_applications import LAS
    from ophiolite.errors import PermissionRefused,Unavailable
    from ophiolite.typed import WellTops,Trajectory,GridSurface
    uploads=LASUploads(web.a);prior=web.a.sources.platform
    web.a.sources.platform=lambda m,b,t:({'members':[{'user_id':u} for u in ('alice','bob')]} if m=='ListProjectMembers' else prior(m,b,t))
    base=dict(project_id='p',filename='x',attribution='Synthetic',audience=['alice','bob'],rights_confirmed=True)
    log=uploads.ingest(Upload(command_id='t-log',name='Log',**base),LAS.encode(),'alice')
    link=WellLog(asset_id=log['asset_id'],revision=log['revision'])
    tops=uploads.ingest(Upload(command_id='t-tops',name='Tops',profile='well-tops-csv/1',declared={'depth_unit':'M','depth_basis':'same-as-log'},well_log=link,**base),b'name,md\nTop A,100\nTop B,101.5\n','alice')
    survey=uploads.ingest(Upload(command_id='t-survey',name='Survey',profile='deviation-csv/1',declared={'azimuth_reference':'grid-north'},well_log=link,**base),b'md,inclination,azimuth\n100,0,0\n200,10,0\n','alice')
    grid=uploads.ingest(Upload(command_id='t-grid',name='Grid',profile='esri-ascii-grid/1',declared={'crs':'EPSG:28992','z_unit':'m','z_meaning':'depth','positive':'down'},**base),b'ncols 2\nnrows 1\nxllcenter 0\nyllcenter 0\ncellsize 5\nNODATA_value -1\n0 -1\n','alice')
    alice,bob=client(web,'alice',kind),client(web,'bob',kind)
    t=alice.read_data(tops['asset_id'],tops['revision'])
    assert isinstance(t,WellTops) and [x['md'] for x in t.tops]==[100.0,101.5] and t.relationships=={'well_log':{'asset_id':log['asset_id'],'revision':log['revision']}}
    s=alice.read_data(survey['asset_id'],survey['revision']);g=alice.read_data(grid['asset_id'],grid['revision'])
    assert isinstance(s,Trajectory) and abs(s.minimum_curvature()[1]['dtvd']-99.4931)<1e-3 and s.context['azimuth_reference']=='grid-north'
    assert isinstance(g,GridSurface) and g.values==[0.0,None] and g.context['registration']=='center' and g.original.startswith(b'ncols')
    from ophiolite.errors import Incompatible
    with pytest.raises(Incompatible):alice.read(tops['asset_id'],tops['revision'],['md'])  # the server refuses curves on typed data
    opened=alice.export([(log['asset_id'],log['revision'],['GR']),(tops['asset_id'],tops['revision'],None),(survey['asset_id'],survey['revision'],None),(grid['asset_id'],grid['revision'],None)],tmp_path/'four')
    assert opened.manifest['bundle_version']=='2.0.0' and [a.type for a in opened.assets]==['well-log','well-tops','trajectory','regular-grid-surface']
    # Bob: refused until shared; then the tops show a restricted log (not shared) and export succeeds without its id.
    with pytest.raises((PermissionRefused,Unavailable)):bob.read_data(tops['asset_id'],tops['revision'])
    uploads.call('share',{'project_id':'p','asset_id':tops['asset_id'],'audience':['bob'],'expected_generation':1},'alice')
    exported=bob.export([(tops['asset_id'],tops['revision'],None)],tmp_path/'bob')
    assert exported.assets[0].relationships=={'well_log':'restricted'} and log['asset_id'] not in (tmp_path/'bob'/'manifest.json').read_text()+(tmp_path/'bob'/'assets/0/descriptor.json').read_text()
    uploads.call('share',{'project_id':'p','asset_id':tops['asset_id'],'audience':[],'expected_generation':2},'alice')
    with pytest.raises((PermissionRefused,Unavailable)):bob.export([(tops['asset_id'],tops['revision'],None)],tmp_path/'bob-revoked')
    assert not (tmp_path/'bob-revoked').exists()


@pytest.mark.parametrize('kind',['delegate'])
def test_sdk_reads_result_groups_and_compares_versions(web,kind):
    """E8: groups show only what the caller may open; a diff names parameters and sample changes."""
    from project_gateway.result_groups import ResultGroups
    alice,bob=client(web,'alice',kind),client(web,'bob',kind)
    def publish(command,changes,parameters):
        binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK groups',runners=['alice'],command_id='gr-'+command,publication_profile='curve-edits/1')
        run=alice.start(binding,application_version='sdk-groups/'+command,parameters=parameters,command_id='gr-run-'+command);run.input()
        return alice.publish(run,changes=changes)
    one=publish('1',[{'index':0,'value':2}],{'offset':2});two=publish('2',[{'index':0,'value':5}],{'offset':5})
    ResultGroups(web.a).call('save',{'project_id':'p','name':'Corrections','members':[one.output_reference.key,two.output_reference.key]},'alice')
    alice.share(one,read=['bob'],expected_generation=alice.grants(one).generation)
    [mine]=alice.result_groups();[seen]=bob.result_groups()
    assert len(mine.members)==2 and [m.asset_id for m in seen.members]==[one.output_reference.key] and seen.recommended is None
    d=alice.diff(one,two)
    assert d.parameters['changed']==['offset'] and d.samples['changed']==1 and d.samples['largest_change']==3.0


@pytest.mark.parametrize('kind',['delegate'])
def test_sdk_export_carries_visible_groups_only(web,kind,tmp_path):
    """E18 completion: groups travel as observations; members and recommendations the exporter cannot see do not."""
    from project_gateway.result_groups import ResultGroups
    alice,bob=client(web,'alice',kind),client(web,'bob',kind)
    def publish(command,value,**kw):
        binding=alice.configure(release_id=web.r['id'],curve='GR',name='SDK bundle groups',runners=['alice'],command_id='bg-'+command,publication_profile='curve-edits/1')
        run=alice.start(binding,application_version='sdk-bg/'+command,parameters={'v':value},command_id='bg-run-'+command);run.input()
        return alice.publish(run,changes=[{'index':0,'value':value}],**kw)
    one,two=publish('1',2),publish('2',5);one_v2=publish('3',3,new_version_of=one)
    groups=ResultGroups(web.a);g=groups.call('save',{'project_id':'p','name':'Corrections','members':[one.output_reference.key,two.output_reference.key]},'alice')
    # Recommend the OLDER version of "one"; select both versions in reversed order.
    groups.call('recommend',{'project_id':'p','id':g['id'],'expected_generation':g['generation'],'recommended':{'asset_id':one.output_reference.key,'revision':one.output_reference.revision},'reason':'Closer'},'alice')
    ref=lambda r:(r.output_reference.key,r.output_reference.revision,['GR'])
    mine=alice.export([ref(one_v2),ref(one),ref(two)],tmp_path/'alice')
    assert mine.manifest['bundle_version']=='1.1.0' and mine.groups[0]['members']==[0,1,2]
    assert mine.groups[0]['recommended']['asset_position']==1 and mine.groups[0]['recommended']['revision']==one.output_reference.revision
    assert alice.export([ref(one)],tmp_path/'plain',groups=False).manifest['bundle_version']=='1.0.0'
    # Bob: the server itself hides Alice-only members, then the bundle carries only what he can see.
    alice.share(two,read=['bob'],expected_generation=alice.grants(two).generation)
    [raw]=bob.result_groups()
    assert [m.asset_id for m in raw.members]==[two.output_reference.key] and raw.recommended is None
    theirs=bob.export([ref(two)],tmp_path/'bob')
    assert theirs.groups[0]['members']==[0] and theirs.groups[0]['recommended'] is None
    assert one.output_reference.key not in (tmp_path/'bob'/'manifest.json').read_text()


@pytest.mark.parametrize('kind',['delegate'])
def test_sdk_reads_and_exports_meshes_and_points(web,kind,tmp_path):
    """E11 continuation: triangulated surfaces and point sets read exactly and leave in bundle 2.2."""
    from project_gateway.las_uploads import LASUploads,Upload
    from ophiolite.typed import TriangulatedSurface,PointSet
    uploads=LASUploads(web.a);prior=web.a.sources.platform
    web.a.sources.platform=lambda m,b,t:({'members':[{'user_id':u} for u in ('alice','bob')]} if m=='ListProjectMembers' else prior(m,b,t))
    base=dict(project_id='p',filename='x',attribution='Synthetic',audience=['alice','bob'],rights_confirmed=True)
    mesh=uploads.ingest(Upload(command_id='m-1',name='Mesh',profile='mesh-text/1',declared={'crs':'EPSG:28992','z_unit':'m'},**base),b'# ophiolite-mesh 1\nattributes amp\nvertices\n0 0 100 1\n10 0 - 0\n0 10 110 -\ntriangles\n0 1 2\n','alice')
    points=uploads.ingest(Upload(command_id='p-1',name='Points',profile='points-csv/1',**base),b'x,y,z,phi\n1,2,3,0\n4,5,,0.2\n','alice')
    alice=client(web,'alice',kind)
    m=alice.read_data(mesh['asset_id'],mesh['revision']);p=alice.read_data(points['asset_id'],points['revision'])
    assert isinstance(m,TriangulatedSurface) and m.vertices[1]==[10.0,0.0,None] and m.data['attributes'][0]['values']==[1.0,0.0,None]
    assert isinstance(p,PointSet) and p.points[1]==[4.0,5.0,None] and list(p.to_frame()['phi'])==[0.0,0.2]
    opened=alice.export([(mesh['asset_id'],mesh['revision'],None),(points['asset_id'],points['revision'],None)],tmp_path/'b')
    assert opened.manifest['bundle_version']=='2.2.0' and opened.assets[0].data.triangles==[[0,1,2]]
