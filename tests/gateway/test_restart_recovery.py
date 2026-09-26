"""Fresh SDK processes replay lost replies from the real gateway journal."""
import json
import os
from pathlib import Path
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service
    from project_gateway.tests.test_applications import LAS
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform runtime required',allow_module_level=True)
from ophiolite.testing import fixture_server
from test_recovery import FIRST,RECOVER,child


@pytest.mark.parametrize('operation',['configure','start','publish','upload'])
def test_real_gateway_commits_then_fresh_process_recovers_same_journal(web,tmp_path,operation):
    def handler(method,path,raw,headers):
        headers={key:value for key,value in headers.items() if key.lower() not in ('host','connection','content-length')}
        response=web.c.request(method,path,content=raw,headers=headers)
        return response.status_code,response.json()
    with fixture_server(handler,drop_response_after=operation) as server:
        source=tmp_path/'source.las';source.write_bytes(LAS.encode());folder=tmp_path/'work'
        code=FIRST.replace("Credential.bearer('oph_api_alice')","Credential.bearer('oph_api_alice:read,write')")
        code=code.replace("work.configure('synthetic','revision',curve='GR',name='Synthetic calculation')",
                          "work.configure(release_id="+repr(web.r['id'])+",runners=['alice'],curve='GR',name='Synthetic calculation')")
        initial=child(code,server.url,folder,operation,'lost',source)
        assert initial.returncode==7,initial.stdout+initial.stderr
        def journal():
            return {table:web.a.journal.db.execute('SELECT id FROM '+table+' ORDER BY id').fetchall() for table in ('application_records','retained_assets')}
        committed=journal()
        assert committed['application_records'] or committed['retained_assets']
        pending=next(p for p in (folder/'requests').glob('*.meta.json') if json.loads(p.read_text())['operation']==operation)
        assert not (folder/'responses'/pending.name.replace('.meta.json','.json')).exists()
        if operation=='upload':source.unlink()
        recovered=child(RECOVER,server.url,folder,'oph_api_alice:read,write')
        assert recovered.returncode==0,recovered.stdout+recovered.stderr
        assert json.loads(recovered.stdout) is not None
        assert journal()==committed, 'Recovery created another binding, run, upload or result'
        requests=[entry for entry in server.requests if entry['path'].endswith('/'+operation)]
        assert len(requests)==4
        assert len({entry['body_base64'] for entry in requests})==1
