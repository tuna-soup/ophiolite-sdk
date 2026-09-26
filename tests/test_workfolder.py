import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import pytest
from ophiolite import Client,Credential
from ophiolite import publish
from ophiolite.testing import fixture_server
from test_recovery import child


def test_payload_and_metadata_durability_order(tmp_path,monkeypatch):
    events=[];original_fdopen=os.fdopen;original_fsync=os.fsync;original_link=os.link;original_replace=os.replace
    def fdpath(fd):return os.readlink('/proc/self/fd/'+str(fd))
    class Writer:
        def __init__(self,stream):self.stream=stream;self.path=fdpath(stream.fileno())
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def write(self,raw):events.append(('write',self.path));return self.stream.write(raw)
        def flush(self):events.append(('flush',self.path));return self.stream.flush()
        def fileno(self):return self.stream.fileno()
    def fdopen(fd,mode,*args,**kwargs):
        stream=original_fdopen(fd,mode,*args,**kwargs)
        return Writer(stream) if mode=='wb' else stream
    def fsync(fd):events.append(('dir-fsync' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file-fsync',fdpath(fd)));return original_fsync(fd)
    def link(source,target,*args,**kwargs):events.append(('install',str(target),str(source)));return original_link(source,target,*args,**kwargs)
    def replace(source,target,*args,**kwargs):events.append(('install',str(target),str(source)));return original_replace(source,target,*args,**kwargs)
    monkeypatch.setattr(os,'fdopen',fdopen);monkeypatch.setattr(os,'fsync',fsync);monkeypatch.setattr(os,'link',link);monkeypatch.setattr(os,'replace',replace)
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'upload');send=client._post_bytes
        def observed(area,operation,raw,**options):
            events.append(('send',operation,raw))
            return send(area,operation,raw,**options)
        monkeypatch.setattr(client,'_post_bytes',observed)
        work.upload_las(server.handler.original,name='Synthetic',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
        metadata_path=next((work.path/'requests').glob('*.meta.json'));metadata=json.loads(metadata_path.read_text());payload_path=metadata_path.parent/metadata['file']
        sent=next(i for i,event in enumerate(events) if event[:2]==('send','upload'))
        assert events[sent][2]==payload_path.read_bytes()
        prior_end=-1
        for target in (payload_path,metadata_path):
            install=next(i for i,event in enumerate(events) if event[:2]==('install',str(target)))
            temporary=events[install][2]
            write=next(i for i,e in enumerate(events) if e==('write',temporary))
            flush=next(i for i,e in enumerate(events) if e==('flush',temporary))
            sync=next(i for i,e in enumerate(events) if e==('file-fsync',temporary))
            directory=next(i for i,e in enumerate(events) if i>install and e==('dir-fsync',str(target.parent)))
            assert prior_end<write<flush<sync<install<directory<sent
            prior_end=directory
        assert all(stat.S_IMODE(path.stat().st_mode)==0o600 for path in work.path.rglob('*') if path.is_file())


PROCESS=r'''
import json,sys
from pathlib import Path
from ophiolite import Client,Credential
from ophiolite.publish import parse_run
from ophiolite.errors import OphioliteError
url,folder,action=sys.argv[1:];folder=Path(folder)
with Client(url,'p',Credential.bearer('oph_api_alice')) as client:
 work=client.work_folder(folder,lock_timeout=.2)
 try:
  if action=='recover':work.recover()
  else:
   run=parse_run(json.loads((folder/'resolved.json').read_text()),client)
   values=json.loads((folder/'normalized.json').read_text())['values']
   work.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic result','values':[0]*len(values)}])
 except OphioliteError as error:
  print(error.code);sys.exit(9)
'''


@pytest.mark.parametrize('second_action',['publish','recover'])
def test_two_process_folder_transaction_serializes_held_reply(tmp_path,second_action):
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        folder=tmp_path/'work';work=client.work_folder(folder);binding=work.configure('synthetic','revision',curve='GR',name='Synthetic')
        run=work.start(binding,application_version='synthetic/1',parameters={});run.input()
        first_seen=threading.Event();release=threading.Event();handler=server.handler
        def held(method,path,raw,headers):
            answer=handler(method,path,raw,headers)
            if path.endswith('/publish') and not first_seen.is_set():first_seen.set();release.wait(5)
            return answer
        server.handler=held
        first=subprocess.Popen([sys.executable,'-c',PROCESS,server.url,str(folder),'publish'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            assert first_seen.wait(3)
            second=child(PROCESS,server.url,folder,second_action)
            assert second.returncode==9 and second.stdout.strip()=='busy',second.stdout+second.stderr
            assert len([r for r in server.requests if r['path'].endswith('/publish')])==1
            release.set();out,err=first.communicate(timeout=5);assert first.returncode==0,out+err
            assert handler.mutations['publish']==1
            assert len(list((folder/'requests').glob('*publish.meta.json')))==1
            assert len(list((folder/'responses').glob('*publish.json')))==1
        finally:
            release.set()
            if first.poll() is None:first.kill();first.wait()


@pytest.mark.parametrize('change',['credential','project','origin'])
def test_identity_lookup_and_send_use_one_snapshot(tmp_path,change):
    from ophiolite.errors import RecoveryUnavailable
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('provider-alice',grant='grant-one')) as client:
        original=client._grant_status
        def switched(headers):
            result=original(headers)
            if change=='credential':client.credential=Credential.bearer('provider-bob',grant='grant-bob')
            if change=='project':client.project='other'
            if change=='origin':client.url='https://other.example'
            return result
        client._grant_status=switched
        work=client.work_folder(tmp_path/'work')
        if change=='credential':
            binding=work.configure('synthetic','revision',curve='GR',name='Example')
            assert binding.owner=='alice'
        else:
            with pytest.raises(RecoveryUnavailable):work.configure('synthetic','revision',curve='GR',name='Example')
            assert not server.handler.mutations
            assert not (work.path/'owner.json').exists()


def test_fresh_grant_same_user_recovers_but_other_identity_refuses(tmp_path):
    from ophiolite.errors import Unavailable,RecoveryUnavailable
    with fixture_server(drop_response_after='configure') as server,Client(server.url,'p',Credential.bearer('provider-alice',grant='grant-one')) as client:
        work=client.work_folder(tmp_path/'work')
        with pytest.raises(Unavailable):work.configure('synthetic','revision',curve='GR',name='Example')
        client.credential=Credential.bearer('provider-bob',grant='grant-bob')
        with pytest.raises(RecoveryUnavailable):client.recover(work.path)
        assert server.handler.mutations['configure']==1
        client.credential=Credential.bearer('provider-alice',grant='fresh-grant')
        assert client.recover(work.path).owner=='alice'
        assert server.handler.mutations['configure']==1


def test_changed_work_origin_refuses_before_authentication(tmp_path):
    from ophiolite.errors import RecoveryUnavailable
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('provider-alice',grant='grant-one')) as client:
        work=client.work_folder(tmp_path/'work');work.configure('synthetic','revision',curve='GR',name='Example')
        client.url='https://other.example'
        with pytest.raises(RecoveryUnavailable):client.recover(work.path)
        assert len(server.requests)==2  # one status and one original configure only


def test_response_checkpoint_repairs_missing_local_alias_without_send(tmp_path):
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work');binding=work.configure('synthetic','revision',curve='GR',name='Example')
        work.start(binding,application_version='synthetic/1',parameters={})
        resolved=(work.path/'resolved.json').read_bytes();(work.path/'resolved.json').unlink();before=len(server.requests)
        assert client.recover(work.path) is None
        assert len(server.requests)==before and (work.path/'resolved.json').read_bytes()==resolved


def test_refused_repeated_start_preserves_original_configuration(tmp_path):
    from ophiolite.errors import Refused
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work');binding=work.configure('synthetic','revision',curve='GR',name='Example')
        work.start(binding,application_version='synthetic/1',parameters={});before=(work.path/'run.json').read_bytes()
        for candidate,version,parameters in ((binding,'different/1',{}),(binding,'synthetic/1',{'changed':True}),(binding.model_copy(update={'id':'different'}),'synthetic/1',{})):
            with pytest.raises(Refused):work.start(candidate,application_version=version,parameters=parameters)
            assert (work.path/'run.json').read_bytes()==before


def test_frozen_legacy_folder_bytes(tmp_path,monkeypatch):
    """Nine files frozen against the complete pre-SDK CLI, with fixed origin."""
    import time,uuid,types
    monkeypatch.setattr(time,'time',lambda:1700000000.0)
    ids=iter(['c'*32,'d'*32])
    monkeypatch.setattr(uuid,'uuid4',lambda:types.SimpleNamespace(hex=next(ids)))
    expected=Path(__file__).parent/'fixtures/workfolder-0.2'
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work')
        binding=work.configure('synthetic','revision',curve='GR',name='Example')
        run=work.start(binding,application_version='manual-rock-physics/1',parameters={'method':'synthetic'},script=(expected/'calculation.py').read_bytes())
        run.input()
        receipt=work.publish(run,derived_curves=json.loads((expected/'curves.json').read_text()))
        work.download(receipt)
        state=json.loads((work.path/'run.json').read_text())
        state['config']['url']='http://localhost:8765'
        actual_run=json.dumps(state,indent=2,allow_nan=False).encode()
        assert len(list(expected.iterdir()))==9
        for frozen in expected.iterdir():
            actual=actual_run if frozen.name=='run.json' else (work.path/frozen.name).read_bytes()
            assert actual==frozen.read_bytes(),frozen.name


@pytest.mark.parametrize('operation',['configure','upload'])
def test_corrupt_saved_reply_cannot_repair_alias(tmp_path,operation):
    from ophiolite.errors import VerificationFailed
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work')
        if operation=='configure':
            work.configure('synthetic','revision',curve='GR',name='Example')
            alias=work.path/'binding.json'
        else:
            work.upload_las(server.handler.original,name='Synthetic',attribution='Original fixture',audience=['alice'],rights_confirmed=True)
            alias=work.path/'upload.json'
        response=next((work.path/'responses').glob('*.json'))
        data=json.loads(response.read_text())
        data['project_id' if operation=='configure' else 'revision']='wrong'
        response.write_text(json.dumps(data));alias.unlink();sent=len(server.requests)
        with pytest.raises(VerificationFailed):work.recover()
        assert not alias.exists() and len(server.requests)==sent


def test_completed_upload_still_checks_owned_payload(tmp_path):
    from ophiolite.errors import RecoveryUnavailable
    with fixture_server() as server,Client(server.url,'p',Credential.bearer('oph_api_alice')) as client:
        work=client.work_folder(tmp_path/'work')
        work.upload_las(server.handler.original,name='Synthetic',attribution='Original fixture',audience=['alice'],rights_confirmed=True)
        meta=next((work.path/'requests').glob('*.meta.json'))
        saved=json.loads(meta.read_text());payload=meta.parent/saved['file']
        raw=payload.read_bytes();payload.write_bytes(raw.replace(b'gAPI',b'xxxx'))
        assert len(payload.read_bytes())==len(raw)
        count=len(server.requests)
        with pytest.raises(RecoveryUnavailable):work.recover()
        assert len(server.requests)==count
