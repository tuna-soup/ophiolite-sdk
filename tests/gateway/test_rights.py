"""E35a C3 (F17) against the in-process gateway: the SDK reads, attaches and renews rights on a release and on a
connection target, sync and async; a stale renewal is RightsConflict with the server's sentence."""
import os
import httpx
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service  # noqa: F401
    from project_gateway.tests.test_route_matrix_rights import admins  # noqa: F401
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import RightsConflict


def client(web,persona):
    return Client('https://workspace.example','p',Credential.bearer('oph_api_'+persona+':read,write'),web.c)


@pytest.mark.parametrize('kind,ref,key',[('release',None,None),('connection','file','curve')])
def test_the_sdk_reads_attaches_and_renews_rights(admins,kind,ref,key):
    web,_=admins
    alice=client(web,'alice');ref=ref or web.r['id']
    assert alice.rights(kind,ref,key=key)['basis'] is None
    done=alice.attach_rights(kind,ref,key=key,uses=['read','derive'],last_day='2099-12-30')
    assert done['basis']['uses_words']=='Read data, Create derived results' and done['basis']['key']==key and not done['renewal']
    read=alice.rights(kind,ref,key=key)
    renewed=alice.renew_rights(kind,ref,key=key,uses=['read'],last_day='2100-01-31',expected_generation=read['basis']['generation'])
    assert renewed['renewal'] and renewed['basis']['version']==2 and renewed['basis']['last_day']=='2100-01-31'
    with pytest.raises(RightsConflict) as stale:
        alice.renew_rights(kind,ref,key=key,uses=['read'],last_day='2100-02-28',expected_generation=read['basis']['generation'])
    assert stale.value.status==409 and stale.value.code=='rights-conflict' and stale.value.request_id.startswith('req_')


def test_the_async_client_reads_and_renews_the_same_rights(admins):
    import anyio
    from ophiolite.aio import AsyncClient
    web,_=admins
    target=('release',web.r['id'])
    client(web,'alice').attach_rights(*target,uses=['read'],last_day='2099-12-30')
    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url='https://workspace.example') as http:
            async with AsyncClient('https://workspace.example','p',Credential.bearer('oph_api_alice:read,write'),http) as c:
                state=await c.rights(*target)
                return await c.renew_rights(*target,uses=['read','export'],last_day='2100-01-31',expected_generation=state['basis']['generation'])
    assert anyio.run(main)['basis']['uses']==['read','export']
