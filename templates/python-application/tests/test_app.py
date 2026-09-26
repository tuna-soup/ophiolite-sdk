import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from support import derive,synthetic_server,client_for,workflow,guidance
from ophiolite import Client,Credential
from ophiolite.errors import AuthenticationRequired,CapacityExceeded,VerificationFailed


def test_derivation_preserves_zero_null_and_all_samples():
    assert derive([0,None,-2,3.5])==[0,None,-4,7]


def test_application_complete_workflow(tmp_path):
    with synthetic_server() as server,client_for(server.url,fixture=True) as client:
        answer=workflow(client,tmp_path/'work',share=['alice','bob'])
        assert answer['state']=='published' and answer['sharing']['state']=='shared'
        assert server.template_mutations=={'configure':1,'start':1,'publish':1,'share':1}


def test_expired_capacity_and_changed_input_guidance():
    with synthetic_server() as server:
        with Client(server.url,'p',Credential.bearer('expired')) as client:
            with pytest.raises(AuthenticationRequired) as error:list(client.assets())
            assert 'ophiolite login' in guidance(error.value)
        with client_for(server.url,fixture=True) as client:
            server.template_faults['capacity']=True
            with pytest.raises(CapacityExceeded) as error:list(client.assets())
            assert 'smaller' in guidance(error.value)
            server.template_faults.clear();asset=next(client.assets());server.template_faults['changed_input']=True
            with pytest.raises(VerificationFailed) as error:client.read(asset['asset_id'],asset['revision'],['GR'])
            assert 'exact version' in guidance(error.value)
