"""E31 S1 against the in-process gateway: the Platform's real refusals (P3 envelope) reach the SDK error with the
server's code, remedy, docs anchor and request id; a captured refusal replayed byte for byte gives the same error."""
import os
import httpx
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service  # noqa: F401
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import PermissionRefused,Refused,Unavailable


def client(web,persona,http=None):
    return Client('https://workspace.example','p',Credential.bearer('oph_api_'+persona+':read,write'),http or web.c)


def test_live_refusals_carry_the_servers_metadata(web):
    bob=client(web,'bob')
    with pytest.raises(Refused) as raised:bob._post('entities','list',{'kind':'well','crs':'EPSG:2154'})  # past the SDK's own check
    error=raised.value
    assert error.status==400 and error.code=='unsupported-crs' and error.docs=='/docs/reference/errors/#unsupported-crs'
    assert error.request_id.startswith('req_') and error.remedy and error.recovery==error.remedy
    with pytest.raises(Unavailable) as raised:bob._post('entities','get',{'entity_id':'no-such-well'})
    assert raised.value.status==404 and raised.value.request_id.startswith('req_') and raised.value.request_id!=error.request_id


def test_a_captured_refusal_replays_to_the_same_error(web):
    headers=Credential.bearer('oph_api_nobody:read').headers('https://workspace.example','p')
    web.c.cookies.clear()
    live=web.c.post('/api/v1/projects/p/entities/list',json={'project_id':'p','kind':'well'},headers=headers)  # not a member
    assert live.status_code==403 and live.json()['request_id']==live.headers['x-request-id']
    captured=(live.status_code,live.content,{'Content-Type':live.headers['content-type'],'X-Request-Id':live.headers['x-request-id']})
    replay=client(web,'nobody',httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(captured[0],content=captured[1],headers=captured[2]))))
    with pytest.raises(PermissionRefused) as raised:replay._post('entities','list',{'kind':'well'})
    body=live.json()
    assert (raised.value.code,raised.value.remedy,raised.value.docs,raised.value.request_id)==(body['code'],body['remedy'],body['docs'],body['request_id'])
