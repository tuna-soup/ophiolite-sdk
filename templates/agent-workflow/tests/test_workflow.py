import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from support import synthetic_server,client_for,workflow,interval_offset,stage,validate_stage,publish_stage,share_after_read,guidance
from ophiolite import Client,Credential,CurveSet
from ophiolite.errors import AxisMismatch,PermissionRefused,Refused,ValidationFailed


def test_complete_loop_and_fresh_process_recovery_creates_nothing(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        answer=workflow(client,tmp_path/'work');assert answer['state']=='published'
        assert (tmp_path/'work/result.las').is_file()
        before=dict(server.template_mutations);requests=len(server.requests)
        code='''import sys;from ophiolite import Client,Credential
sys.path.insert(0,sys.argv[3]);from support import workflow
with Client(sys.argv[1],'p',Credential.bearer('oph_api_alice')) as client:assert workflow(client,sys.argv[2])['state']=='recovered'
'''
        result=subprocess.run([sys.executable,'-c',code,server.url,str(tmp_path/'work'),str(Path(__file__).resolve().parents[2])],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert server.template_mutations==before and len(server.requests)==requests
        correction=interval_offset(client,tmp_path/'offset')
        assert correction.manifest.schema_=='ophiolite.edit-result/1'
        assert (tmp_path/'offset/result.las').is_file()


def test_failure_examples_refuse_without_publication(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        server.template_faults['revoked']=True
        with pytest.raises(PermissionRefused) as error:list(client.assets())
        assert 'owner' in guidance(error.value)
        server.template_faults.clear()
        client.configure('curve-a','revision',curve='GR',name='First',command_id='same-command')
        with pytest.raises(Refused):client.configure('curve-a','revision',curve='GR',name='Changed',command_id='same-command')
        state=stage(client,tmp_path/'work')
        state['curves'][0]['values'][0]=-999.25
        with pytest.raises(ValidationFailed):validate_stage(state)
        state['curves'][0]['values'][0]=0
        state['original']=state['original'].replace(b'~ASCII',b'RHOB.g/cc : Other source curve\n~ASCII')
        state['curves'][0]['mnemonic']='RHOB'
        with pytest.raises(ValidationFailed):validate_stage(state)
        assert server.template_mutations.get('publish',0)==0
        selected=state['selected'];other=copy.deepcopy(selected.curves[0]);other.curve='OTHER';other.context.depth_unit='FT'
        second=copy.deepcopy(selected.descriptors[0]);second.scientific.curve='OTHER';second.scientific.axis_unit='FT'
        combined=CurveSet([selected.descriptors[0],second],[selected.curves[0],other],selected.artifact)
        with pytest.raises(AxisMismatch):combined.to_numpy()


def test_lost_share_reads_grants_without_retry(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        state=stage(client,tmp_path/'work');receipt=publish_stage(state);server.drop('share',1)
        answer=share_after_read(client,receipt,['alice','bob'])
        assert answer['state']=='inspect-recipients' and 'Read recipients first' in answer['message']
        assert set(answer['grants']['recipients'])=={'alice','bob'}
        assert server.template_mutations['share']==1
        assert [r['path'].rsplit('/',1)[-1] for r in server.requests[-3:]]==['result-list','share','result-list']
