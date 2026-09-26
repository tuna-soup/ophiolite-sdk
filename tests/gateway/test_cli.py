"""SDK CLI over actual public routes, with an external frozen pre-SDK oracle."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_in_process_publish import web,shared,app,service,client
from ophiolite import auth
from ophiolite.testing import fixture_server


def test_cli_fetch_bytes_match_complete_frozen_cli(web,tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from project_gateway import scientific_api
    clock_calls=[]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            clock_calls.append(tz)
            return datetime(2026,9,26,12,tzinfo=timezone.utc)
    monkeypatch.setattr(scientific_api,'datetime',Clock)
    from project_gateway.tests.test_applications import LAS
    frozen=Path(os.environ.get('OPHIOLITE_FROZEN_KIT','/tmp/e4-cli-0.2'))
    if not (frozen/'scientific_cli.py').exists():pytest.fail('Supply the frozen pre-SDK CLI for compatibility qualification')
    expected_hashes={'scientific_cli.py': '8ac2e2a34357a58a2d74de29e3846dc2d17f23e588b6b827689166a3b9354fc3', 'scientific_read.py': 'cceee0ca4c47efafd9ef2091542fe9040b3acd0e64fffe977410b77fb9bee274', 'scientific_handoff.py': '0cd6b8b6fff2382014ba4eb4c4bf0c8c019b10f7b795e6ae607345c7051ff5ad', 'application_access.py': 'b482e1095647824276e26ab805626cce726a3cb3f26a19a4fd3bf3abc69e90a3', 'curve_application.py': '72413a4dbfa108fc5bef0f4a6dd767e8e8c56b915123bb3f3e7032e19919a456'}
    assert all(hashlib.sha256((frozen/name).read_bytes()).hexdigest()==digest for name,digest in expected_hashes.items()), 'Frozen CLI source revision differs'
    upload=client(web,'alice','delegate').upload_las(LAS.encode(),name='CLI input',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
    def handler(method,path,raw,headers):
        headers={k:v for k,v in headers.items() if k.lower() not in ('host','connection','content-length')}
        response=web.c.request(method,path,content=raw,headers=headers)
        return response.status_code,response.content
    with fixture_server(handler) as server:
        config=tmp_path/'configuration.json';config.write_text(json.dumps({'schema':'ophiolite.read-configuration/1','url':server.url,'project':'p','asset':upload.asset_id,'revision':upload.revision,'curve':'GR'}))
        data={'url':server.url,'project':'p','issuer':server.url,'token_endpoint':server.url+'/token','client_id':'synthetic','access_token':'provider-alice','refresh_token':'synthetic-unused','expires_at':9999999999,'grant_id':web.grants['alice']}
        old=tmp_path/'legacy.json';old.write_text(json.dumps(data));old.chmod(0o600)
        new=tmp_path/'sdk.json';new.write_text(json.dumps({'schema':auth.SCHEMA,'family':'synthetic-family','generation':1,'credential':data}));new.chmod(0o600)
        outputs={}
        for label,command,credential in [('legacy',[sys.executable,str(frozen/'scientific_cli.py')],old),('sdk',[sys.executable,'-m','ophiolite.cli'],new)]:
            clock_before=len(clock_calls)
            result=subprocess.run(command+['fetch','--configuration',str(config),'--credentials',str(credential),'--output',str(tmp_path/label)],capture_output=True,text=True,timeout=30)
            assert result.returncode==0,result.stderr
            outputs[label]=result.stdout
            assert len(clock_calls)>clock_before  # Both descriptors consume the fixed server clock.
        assert outputs['legacy']==outputs['sdk']
        for name in ('artifact.las','curve.json','descriptor.json'):
            assert (tmp_path/'legacy'/name).read_bytes()==(tmp_path/'sdk'/name).read_bytes(),name
        # The same actual public gateway also qualifies the CLI's advanced path.
        config.write_text(json.dumps({'schema':'ophiolite.local-configuration/1','url':server.url,'project':'p'}))
        code=tmp_path/'calculation.py';code.write_text('raise AssertionError("prepare executed Python")\n')
        parameters=tmp_path/'parameters.json';parameters.write_text('{}')
        work=tmp_path/'work'
        def invoke(arguments):
            result=subprocess.run([sys.executable,'-m','ophiolite.cli',*arguments,'--configuration',str(config),'--credentials',str(new)],capture_output=True,text=True,timeout=30)
            assert result.returncode==0,result.stderr
            return result.stdout
        prepare=['prepare','--work',str(work),'--release',web.r['id'],'--curve','GR','--name','CLI release','--runner','alice','--script',str(code),'--parameters',str(parameters)]
        assert invoke(prepare)==invoke(prepare)
        curves=work/'curves.json';curves.write_text(json.dumps([{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic example','values':[0,None,60]}]));curves.chmod(0o600)
        assert 'Committed derived asset:' in invoke(['publish','--work',str(work)])
        assert invoke(['recover','--work',str(work)])==''
        receipt=json.loads((work/'receipt.json').read_text())['receipt']
        assert 'readers:' in invoke(['share','--asset',receipt['output_reference']['key'],'--read','bob'])
