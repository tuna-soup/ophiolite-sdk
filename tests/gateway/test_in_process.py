"""Actual public read routes, synthetic Platform fixture; auth delegate is stubbed.

This is not browser consent, a live deployment, or C5's real-principal matrix.
"""
import os
import pytest
try:
    from project_gateway.tests.test_retained_applications import shared
    from project_gateway.tests.test_applications import app as platform_app
    from project_gateway.tests.test_organizations import service
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client, Credential
from ophiolite.errors import PermissionRefused, Unavailable


@pytest.fixture(params=['unwrapped','wrapped'])
def app(request,monkeypatch,tmp_path):
    import project_gateway.tests.test_applications as source_fixture
    if request.param=='wrapped':
        header,data=source_fixture.LAS.split('~ASCII\n',1)
        wrapped=header.replace('WRAP. NO','WRAP. YES')+'~ASCII\n'+'\n'.join(data.split())+'\n'
        monkeypatch.setattr(source_fixture,'LAS',wrapped)
    lifecycle=platform_app.__wrapped__(tmp_path)
    try:yield next(lifecycle)
    finally:
        try:next(lifecycle)
        except StopIteration:pass


def test_real_get_routes_noncompute_revocation(shared,service,monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from project_gateway.tests.test_identity import identity
    from project_gateway.app import create_app
    from project_gateway.automation import Automation
    a,b,r,permissions,path=shared
    assert not permissions['viewer']['can_compute']
    active=[True];calls=[];bodies=[];recording=[]
    def authorize(self,token,project,scope):
        if not active[0] or token!='oph_api_sdk_fixture' or project not in ('p',None) or scope!='read':raise PermissionError('Denied')
        return 'viewer','p',['read']  # E27: (parent, the delegate's project, its scopes)
    monkeypatch.setattr(Automation,'authorize',authorize)
    web=create_app(a.sources.platform,'https://workspace.example',organizations=service,identity=identity(service),sources=a.sources)
    with TestClient(web,base_url='https://workspace.example') as http:
        http.event_hooks['request'].append(lambda request:calls.append((request.method,request.url.path)))
        def capture(response):
            import base64
            raw=response.read();bodies.append(raw)
            recording.append({'method':response.request.method,'path':response.request.url.raw_path.decode(),
                              'status':response.status_code,'body_base64':base64.b64encode(raw).decode(),
                              'headers':{'content-type':response.headers.get('content-type','application/octet-stream')}})
        http.event_hooks['response'].append(capture)
        client=Client('https://workspace.example','p',Credential.bearer('oph_api_sdk_fixture'),http)
        before=a.journal.db.execute("SELECT count(*) FROM application_records WHERE kind='run'").fetchone()[0]
        item=next(client.assets());result=client.read(item['asset_id'],item['revision'],['GR'])
        assert result.curves[0].axis==[100,101,102]
        assert result.curves[0].values==[0,None,30]
        assert result.curves[0].unit=='gAPI'
        assert result.artifact==path.read_bytes()
        assert result.descriptors[0].revision==item['revision']
        # The frozen reader consumes exactly these captured responses; authentication
        # compatibility is deliberately not inferred from this data-only oracle.
        import importlib.util, json
        from pathlib import Path
        import project_gateway.app as gateway_module
        platform=Path(gateway_module.__file__).resolve().parents[2]
        monkeypatch.syspath_prepend(str(platform/'cli'))
        spec=importlib.util.spec_from_file_location('sdk_frozen_reader',platform/'services/project_gateway/tests/fixtures/cli-0.2/scientific_read.py')
        frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)
        old=object.__new__(frozen.Client);old.project='p';old.prefix=client.prefix
        recorded=list(bodies[-3:]);old._get=lambda *args:recorded.pop(0)
        baseline=old.read(item['asset_id'],item['revision'],'GR')
        assert baseline.artifact==result.artifact
        assert baseline.curve==result.curves[0].model_dump(by_alias=True)
        assert baseline.descriptor==result.descriptors[0].model_dump(by_alias=True,exclude_unset=True)
        if os.environ.get('OPHIOLITE_RECORD_FIXTURE'):
            Path(os.environ['OPHIOLITE_RECORD_FIXTURE']).write_text(json.dumps(recording,indent=2)+'\n')
        result.save(tmp_path/'read')
        assert a.journal.db.execute("SELECT count(*) FROM application_records WHERE kind='run'").fetchone()[0]==before
        assert all(method=='GET' and route.startswith('/api/v1/projects/p/scientific-assets') for method,route in calls)
        with pytest.raises(Unavailable):client.read(item['asset_id'],'wrong',['GR'])
        active[0]=False
        with pytest.raises(PermissionRefused):list(client.assets())
