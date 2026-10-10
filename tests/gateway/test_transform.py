"""E64 C5: Client.change_coordinates and Client.change_units against the in-process gateway (bearer credential built
in process, as test_locations.py does; no claim about credential discovery). The C2 and C1 literals come back through
the Client, and a refusal raises with the sentence the Workspace shows."""
import io
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service  # noqa: F401
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import OphioliteError

pytestmark=pytest.mark.filterwarnings('ignore:Best transformation is not available')
EXCERPT=Path(__import__('project_gateway.transformations',fromlist=['x']).__file__).parent/'tests'/'fixtures'/'e64'/'HON-GT-01-excerpt.las'  # the Platform's copy (C3)


def client(web,persona):
    return Client('https://workspace.example','p',Credential.bearer('oph_api_'+persona+':read,write'),web.c)


def mine(alice,raw,profile,declared=None,name='Source'):
    up=alice.upload_data(raw,profile=profile,name=name,attribution='Synthetic',audience=['bob'],rights_confirmed=True,declared=declared,command_id='u-'+name)
    return up


def test_change_coordinates_returns_the_c2_position_and_a_named_operation(web):
    alice=client(web,'alice')
    up=mine(alice,b'x,y,z\n75242.83,448081.04,-12.5\n','points-csv/1',{'crs':'EPSG:28992','z_unit':'m'})
    preview=alice.preview_change(up.asset_id,up.revision,{'kind':'coordinates','to':'EPSG:32631'})
    assert preview['samples'][0]['after']==pytest.approx([584090.5495,5763453.9727],abs=0.002)
    receipt=alice.change_coordinates(up.asset_id,up.revision,to='EPSG:32631',name='In UTM',command_id='c1')
    assert receipt.method.name=='Change coordinate system' and receipt.method.parameters['to']=='EPSG:32631'
    assert receipt.method.parameters['grids']==[] and receipt.method.parameters['accuracy_m']==1.0
    assert alice.change_coordinates(up.asset_id,up.revision,to='EPSG:32631',name='In UTM',command_id='c1')==receipt  # a retry
    with pytest.raises(OphioliteError,match='^The data is already in Amersfoort / RD New. Nothing was changed.'):
        alice.change_coordinates(up.asset_id,up.revision,to='EPSG:28992',name='Same',command_id='c2')


def test_change_units_keeps_the_coefficients_and_refuses_by_sentence(web):
    alice=client(web,'alice')
    up=mine(alice,EXCERPT.read_bytes(),'las2/1',name='HON')
    receipt=alice.change_units(up.asset_id,up.revision,curves={'DT':'us/m'},name='HON us/m',command_id='u1')
    assert receipt.method.parameters['curves']=={'DT':{'from':'us/ft','to':'us/m','from_abcd':[0,1e-06,0.3048,0],'to_abcd':[0,1e-06,1,0]}}
    with pytest.raises(OphioliteError,match='^gAPI measures gamma-ray intensity, not a length. It cannot be changed to m.'):
        alice.change_units(up.asset_id,up.revision,curves={'GR':'m'},name='x',command_id='u2')
