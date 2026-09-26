"""Opt-in isolated-deployment workflow; credentials never enter test output."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from ophiolite import Client,Credential
from ophiolite.errors import ValidationFailed


def test_live_publication(tmp_path):
    location=os.environ.get('OPHIOLITE_LIVE_CREDENTIALS')
    if not location:
        if os.environ.get('OPHIOLITE_REQUIRE_LIVE')=='1':pytest.fail('Live qualification credentials required')
        pytest.skip('Set explicit isolated live fixture credentials')
    config=json.loads(Path(location).read_text())
    assert config['url'].startswith('http://127.0.0.1:')  # qualification fixture only
    with Client(config['url'],config['project'],Credential.bearer(config['token'])) as client:
        from importlib.resources import files
        raw=files('ophiolite').joinpath('contracts/assets/v1/fixtures/original.las').read_text()
        header,data=raw.split('~ASCII\n')
        raw=(header+'RHOB.g/cc : Original synthetic density\n~ASCII\n'+'\n'.join(line+' 2.5' for line in data.splitlines())+'\n').encode()
        upload=client.work_folder(tmp_path/'upload').upload_las(raw,name='E4 SDK live synthetic',attribution='Original synthetic SDK fixture',audience=['scientist','reviewer'],rights_confirmed=True)
        assert any(item['asset_id']==upload.asset_id for item in client.assets())
        read=client.read(upload.asset_id,upload.revision,['GR','RHOB'])
        assert read.artifact==raw and read.curves[1].values==[2.5]*5
        work=client.work_folder(tmp_path/'calculate')
        binding=work.configure(upload.asset_id,upload.revision,curve='GR',name='E4 SDK live calculation')
        run=work.start(binding,application_version='e4-live/1',parameters={'method':'multiply','factor':2})
        original,view=run.input();assert original==raw
        with pytest.raises(ValidationFailed):work.publish(run,derived_curves=[])
        receipt=work.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Original values doubled','values':[None if x is None else x*2 for x in view.values]}])
        work.download(receipt)
        after=client.read(receipt.asset['asset_id'],receipt.asset['revision'],['GR','NEW'])
        assert after.curves[1].values==[0,20,None,60,80]
        before=client.grants(receipt)
        client.share(receipt,read=['reviewer'],reuse=['reviewer'])
        assert 'reviewer' in client.grants(receipt).recipients
        code="import json,sys;from pathlib import Path;from ophiolite import Client,Credential;c=json.loads(Path(sys.argv[1]).read_text());client=Client(c['url'],c['project'],Credential.bearer(c['token']));assert client.recover(sys.argv[2]) is None;client.close()"
        result=subprocess.run([sys.executable,'-c',code,location,str(work.path)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,'Fresh-process completed-folder recovery failed'
        proof={'result':'PASS','scope':'isolated gateway; actual short-lived delegate; synthetic two-curve upload/read/publication/share/recovery',
               'samples':5,'missing':1,'recipient':'reviewer','identity':'scientist',
               'receipt':receipt.model_dump(by_alias=True,exclude_unset=True),'workspace_url':after.workspace_url()}
        destination=os.environ.get('OPHIOLITE_LIVE_PROOF')
        if destination:Path(destination).write_text(json.dumps(proof,indent=2)+'\n')
