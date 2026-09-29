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


def derives(server):
    return [r for r in server.requests if r['path'].endswith('/publications/derive')]


def fresh_process(server, folder):
    code = """import sys;from ophiolite import Client,Credential
sys.path.insert(0,sys.argv[3]);from support import workflow
with Client(sys.argv[1],'p',Credential.bearer('oph_api_alice')) as client:print(workflow(client,sys.argv[2])['state'])
"""
    return subprocess.run([sys.executable,'-c',code,server.url,str(folder),str(Path(__file__).resolve().parents[2])],capture_output=True,text=True)


def test_complete_loop_and_fresh_process_recovery_creates_nothing(tmp_path):
    """E31 S5: one publications/derive; the curve-pilot applications route is never called; a fresh process on the
    same folder recognises the published file and sends nothing."""
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        answer=workflow(client,tmp_path/'work');assert answer['state']=='published'
        assert server.template_mutations=={'derive':1}
        assert not [r for r in server.requests if '/applications/' in r['path']]  # the old publish route is not used
        before=len(derives(server))
        result=fresh_process(server,tmp_path/'work')
        assert result.returncode==0 and result.stdout.strip()=='recovered',result.stderr
        assert server.template_mutations=={'derive':1} and len(derives(server))==before
        correction=interval_offset(client,tmp_path/'offset')  # curve edits keep their own route
        assert correction.manifest.schema_=='ophiolite.edit-result/1'
        assert (tmp_path/'offset/result.las').is_file()


def test_a_lost_publication_answer_is_published_once_by_a_fresh_process(tmp_path):
    """R2-14: the server stored the publication, the answer was lost; a fresh process retries the same saved command
    id and gets the same receipt: exactly one publication."""
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        server.drop('derive',3)  # the answer is lost on every attempt of this process
        with pytest.raises(Exception):workflow(client,tmp_path/'work')
        assert server.template_mutations=={'derive':1}
        result=fresh_process(server,tmp_path/'work')
        assert result.returncode==0 and result.stdout.strip()=='published',result.stderr
        assert server.template_mutations=={'derive':1}
        headers=[r for r in derives(server)]
        assert len(headers)>=2  # the retries and the fresh process all sent the same command
        lineage=json.loads((tmp_path/'work/run.json').read_text())['derive']['receipt']
        assert lineage['derived_from'][0]['revision'] and lineage['method']['name']=='multiply'  # parent and method on the receipt


def test_failure_examples_refuse_without_publication(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        server.template_faults['revoked']=True
        with pytest.raises(PermissionRefused) as error:list(client.assets())
        assert 'owner' in guidance(error.value)
        server.template_faults.clear()
        client.configure('curve-a','revision',curve='GR',name='First',command_id='same-command')
        with pytest.raises(Refused):client.configure('curve-a','revision',curve='GR',name='Changed',command_id='same-command')
        state=stage(client,tmp_path/'work')
        state['values'][2]=0.0  # an input's missing sample became a number
        with pytest.raises(ValidationFailed):validate_stage(state)
        state=stage(client,tmp_path/'work',mnemonic='GR')  # the derived curve would shadow its input
        with pytest.raises(ValidationFailed):validate_stage(state)
        assert server.template_mutations.get('derive',0)==0
        selected=state['selected'];other=copy.deepcopy(selected.curves[0]);other.curve='OTHER';other.context.depth_unit='FT'
        second=copy.deepcopy(selected.descriptors[0]);second.scientific.curve='OTHER';second.scientific.axis_unit='FT'
        combined=CurveSet([selected.descriptors[0],second],[selected.curves[0],other],selected.artifact)
        with pytest.raises(AxisMismatch):combined.to_numpy()


def test_lost_share_replays_once_and_changed_recipients_are_inspected(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        state=stage(client,tmp_path/'work');receipt=publish_stage(state);server.drop('share',1)
        answer=share_after_read(client,receipt,['alice','bob'])
        # The SDK repeats the identical conditional request once; the server applies it once.
        assert answer['state']=='shared' and set(answer['grants']['recipients'])=={'alice','bob'}
        assert server.template_mutations['publication-share']==1
        assert [r['path'].rsplit('/',2)[-2:] for r in server.requests[-4:]]==[['publications','info'],['publications','info'],['publications','share'],['publications','share']]
        server.template_faults['recipients_changed']=True
        answer=share_after_read(client,receipt,['alice'])
        assert answer['state']=='inspect-recipients' and 'Read recipients first' in answer['message']
        assert set(answer['grants']['recipients'])=={'alice','bob'} and server.template_mutations['publication-share']==1
