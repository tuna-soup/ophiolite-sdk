"""E122 s0 C4 against the in-process gateway: `client.provenance(asset, revision)` returns the route's answer, its
`words` the gateway's sentence; an unreadable version is Unavailable, as an unknown one."""
import hashlib
import os
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service  # noqa: F401
    from project_gateway.tests.test_source_provenance_route import PATH, folder, route
    from project_gateway.tests.test_upload_runs import TUM2
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import Unavailable


def client(web,persona):
    return Client('https://workspace.example','p',Credential.bearer('oph_api_'+persona+':read'),web.c)


def test_the_sdk_returns_the_routes_answer_and_its_sentence(web):
    _,(item,)=folder(web)
    found=client(web,'alice').provenance(item['asset_id'],item['revision'])
    assert found.words=='From file `%s` (checksum %s…), no source id.'%(PATH,hashlib.sha256(TUM2).hexdigest()[:12])
    assert found.record['identity']['source_object_id']=={'path':PATH,'part':None} and found.observation['declared_by']=='alice'
    served=web.c.get(route(item['asset_id'],item['revision']),headers={'Authorization':'Bearer oph_api_alice:read'})
    assert found.json==served.json()


def test_an_unreadable_version_is_unavailable_as_an_unknown_one(web):
    _,(item,)=folder(web)
    bob=client(web,'bob')
    with pytest.raises(Unavailable) as hidden:bob.provenance(item['asset_id'],item['revision'])
    with pytest.raises(Unavailable) as unknown:bob.provenance(item['asset_id'],'f'*64)
    assert (hidden.value.status,str(hidden.value).split(' (')[0])==(unknown.value.status,str(unknown.value).split(' (')[0])
