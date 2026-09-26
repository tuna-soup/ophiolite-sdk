import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from ophiolite import Client,Credential
from ophiolite.errors import RecoveryUnavailable
from ophiolite.testing import fixture_server

FIRST=r'''
import os,signal,sys
from pathlib import Path
from ophiolite import Client,Credential
from ophiolite.errors import OphioliteError
url,folder,target,mode,source=sys.argv[1:]
with Client(url,'p',Credential.bearer('oph_api_alice')) as client:
 if mode=='kill':
  original=client._post_bytes
  def send(area,operation,*args,**kwargs):
   if operation==target:os.kill(os.getpid(),signal.SIGKILL)
   return original(area,operation,*args,**kwargs)
  client._post_bytes=send
 work=client.work_folder(folder)
 try:
  if target=='upload':work.upload_las(source,name='Synthetic upload',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
  else:
   binding=work.configure('synthetic','revision',curve='GR',name='Synthetic calculation')
   run=work.start(binding,application_version='synthetic/1',parameters={},script=b'# original synthetic code\n')
   raw,view=run.input()
   receipt=work.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic result','values':[0]*len(view.values)}])
   work.download(receipt)
 except OphioliteError as error:
  print(error.code);sys.exit(7)
'''
RECOVER=r'''
import json,sys
from ophiolite import Client,Credential
from ophiolite.errors import OphioliteError
url,folder,token=sys.argv[1:]
try:
 with Client(url,'p',Credential.bearer(token)) as client:
  result=client.recover(folder)
  print(json.dumps(None if result is None else result.model_dump(by_alias=True,exclude_unset=True)))
except OphioliteError as error:
 print(error.code);sys.exit(8)
'''


def child(code,*args):
    return subprocess.run([sys.executable,'-c',code,*map(str,args)],capture_output=True,text=True,timeout=15)


@pytest.mark.parametrize('operation',['configure','start','publish','upload'])
@pytest.mark.parametrize('mode',['lost','kill'])
def test_fresh_process_recovers_each_operation_once(tmp_path,operation,mode):
    with fixture_server() as server:
        source=tmp_path/'original.las';source.write_bytes(server.handler.original);folder=tmp_path/'work'
        if mode=='lost':server.drop(operation,3)
        first=child(FIRST,server.url,folder,operation,mode,source)
        assert first.returncode==(7 if mode=='lost' else -9),first.stdout+first.stderr
        assert server.handler.mutations.get(operation,0)==(1 if mode=='lost' else 0)
        requests=[p for p in (folder/'requests').glob('*.meta.json') if json.loads(p.read_text())['operation']==operation]
        assert len(requests)==1
        metadata=json.loads(requests[0].read_text());owned=folder/'requests'/metadata['file'];before=owned.read_bytes()
        if operation=='upload':source.unlink()
        recovered=child(RECOVER,server.url,folder,'oph_api_alice')
        assert recovered.returncode==0,recovered.stdout+recovered.stderr
        assert json.loads(recovered.stdout) is not None
        assert server.handler.mutations[operation]==1
        assert owned.read_bytes()==before
        count=len(server.requests)
        repeated=child(RECOVER,server.url,folder,'oph_api_alice')
        assert repeated.returncode==0 and json.loads(repeated.stdout) is None
        assert len(server.requests)==count


@pytest.mark.parametrize('damage',['payload-changed','payload-missing','header','project','parameters','identity','origin'])
def test_recovery_refuses_changed_checkpoint_or_identity(tmp_path,damage):
    target='upload' if damage.startswith('payload') or damage=='header' else 'start'
    with fixture_server() as server:
        source=tmp_path/'original.las';source.write_bytes(server.handler.original);folder=tmp_path/'work';server.drop(target)
        assert child(FIRST,server.url,folder,target,'lost',source).returncode==7
        meta=next(p for p in (folder/'requests').glob('*.meta.json') if json.loads(p.read_text())['operation']==target)
        value=json.loads(meta.read_text());payload=meta.parent/value['file']
        if damage=='payload-changed':payload.write_bytes(payload.read_bytes()+b'changed')
        if damage=='payload-missing':payload.unlink()
        if damage=='header':value['headers']['X-Ophiolite-Upload']='eyJjaGFuZ2VkIjp0cnVlfQ==';meta.write_text(json.dumps(value))
        if damage in ('project','parameters','origin'):
            path=folder/'run.json';state=json.loads(path.read_text())
            if damage=='parameters':state['config']['parameters']['extra']='changed'
            elif damage=='origin':state['config']['url']='https://other.example'
            else:state['config']['project']='other'
            path.write_text(json.dumps(state))
        before=len(server.requests)
        recovered=child(RECOVER,server.url,folder,'oph_api_bob' if damage=='identity' else 'oph_api_alice')
        assert recovered.returncode==8,recovered.stdout+recovered.stderr
        assert len(server.requests)==before and server.handler.mutations[target]==1


def test_upload_recovery_uses_owned_copy_after_original_changes(tmp_path):
    with fixture_server(drop_response_after='upload') as server:
        source=tmp_path/'original.las';source.write_bytes(server.handler.original);folder=tmp_path/'work'
        assert child(FIRST,server.url,folder,'upload','lost',source).returncode==7
        source.write_bytes(b'different input')
        result=child(RECOVER,server.url,folder,'oph_api_alice')
        assert result.returncode==0,result.stdout+result.stderr
        assert server.handler.mutations['upload']==1


def test_recovery_requires_original_folder(tmp_path):
    with Client('http://localhost','p',Credential.bearer('oph_api_alice')) as client:
        for path in (tmp_path/'missing',tmp_path):
            with pytest.raises(RecoveryUnavailable):client.recover(path)
        file=tmp_path/'not-folder';file.write_text('no')
        with pytest.raises(RecoveryUnavailable):client.recover(file)
