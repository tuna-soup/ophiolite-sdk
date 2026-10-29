"""E35a C3: a rights refusal reaches the SDK as its own category with the server's sentence (test 8)."""
import httpx
import pytest
from ophiolite.errors import IntegrityConflict, PermissionRefused, RightsConflict, RightsEnded
from test_error_envelope import client, refusal

SENTENCE = 'The rights to use this data ended after 30 June 2099. Ask the project administrator to renew them.'
ENDED = {'error': SENTENCE, 'code': 'rights-ended', 'message': SENTENCE, 'last_day': '2099-06-30',
         'remedy': 'Ask the project administrator to renew the rights to use this data.', 'docs': '/docs/reference/errors/#rights-ended',
         'request_id': 'req_rights0123456789abcdef'}


def test_an_ended_basis_is_rights_ended_with_the_sentence_and_the_last_day():
    with client(lambda r: refusal(403, ENDED, ENDED['request_id'])) as c, pytest.raises(RightsEnded) as raised:
        c._post('las-uploads', 'info', {'asset_id': 'a'})
    error = raised.value
    assert isinstance(error, PermissionRefused)  # existing handlers of a permission refusal still catch it
    assert (error.message, error.last_day, error.code, error.status, error.request_id) == (SENTENCE, '2099-06-30', 'rights-ended', 403, ENDED['request_id'])


def test_a_malformed_last_day_is_dropped_and_the_sentence_kept():
    with client(lambda r: refusal(403, {**ENDED, 'last_day': '30/06/2099'})) as c, pytest.raises(RightsEnded) as raised:
        c._post('las-uploads', 'info', {'asset_id': 'a'})
    assert raised.value.last_day is None and raised.value.message == SENTENCE


def test_a_stale_renewal_is_rights_conflict():
    body = {'error': 'The rights changed; reload before saving', 'code': 'rights-conflict', 'message': 'The rights changed; reload before saving',
            'remedy': 'Read the rights again, then renew them from what you read.', 'docs': '/docs/reference/errors/#rights-conflict', 'request_id': 'req_c'}
    with client(lambda r: refusal(409, body, 'req_c')) as c, pytest.raises(RightsConflict) as raised:
        c._post('las-uploads', 'info', {'asset_id': 'a'})  # (the transport decides by code, not by route)
    assert isinstance(raised.value, IntegrityConflict) and raised.value.message == 'The rights changed; reload before saving'


def test_the_async_client_raises_the_same_category():
    import anyio
    from ophiolite import Credential
    from ophiolite.aio import AsyncClient
    async def main():
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: refusal(403, ENDED, ENDED['request_id'])))
        async with AsyncClient('https://ophiolite.example', 'p', Credential.bearer('oph_api_alice'), http=http) as c:
            with pytest.raises(RightsEnded) as raised: await c._post('las-uploads', 'info', {'asset_id': 'a'})
        return raised.value
    assert anyio.run(main).last_day == '2099-06-30'


BASIS = {'id': 'b1', 'target_kind': 'connection', 'target_ref': 'c1', 'key': 'curve', 'generation': 2, 'version': 2, 'uses': ['read', 'derive'],
         'uses_words': 'Read data, Create derived results', 'last_day': '2026-12-31', 'last_day_words': '31 December 2026', 'ended': False, 'delete_on_end': False}


def recording(answer):
    import json
    seen = []
    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=answer)
    return seen, handler


def test_the_client_reads_attaches_and_renews_on_the_rights_routes():
    """E35a C3: one route per operation; a connection target carries its key; renew sends the generation read."""
    seen, handler = recording({'basis': BASIS, 'can_change': True})
    with client(handler) as c:
        assert c.rights('connection', 'c1', key='curve')['basis'] == BASIS
        c.attach_rights('upload', 'a1', uses=['read'], last_day='2026-12-31')
        c.renew_rights('release', 'r1', uses=('read', 'export'), last_day='2027-01-31', expected_generation=2, delete_on_end=True)
    assert seen == [('/api/v1/projects/p/rights/get', {'project_id': 'p', 'target_kind': 'connection', 'target_ref': 'c1', 'key': 'curve'}),
                    ('/api/v1/projects/p/rights/attach', {'project_id': 'p', 'target_kind': 'upload', 'target_ref': 'a1', 'uses': ['read'], 'last_day': '2026-12-31',
                                                          'delete_on_end': False}),
                    ('/api/v1/projects/p/rights/renew', {'project_id': 'p', 'target_kind': 'release', 'target_ref': 'r1', 'uses': ['read', 'export'],
                                                         'last_day': '2027-01-31', 'delete_on_end': True, 'expected_generation': 2})]


def test_the_async_client_inherits_the_three_operations_as_awaitables():
    import anyio
    from ophiolite import Credential
    from ophiolite.aio import AsyncClient
    seen, handler = recording({'basis': BASIS, 'can_change': True})
    async def main():
        async with AsyncClient('https://ophiolite.example', 'p', Credential.bearer('oph_api_alice'), http=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as c:
            state = await c.rights('connection', 'c1', key='curve')
            await c.renew_rights('connection', 'c1', key='curve', uses=['read'], last_day='2027-01-31', expected_generation=state['basis']['generation'])
    anyio.run(main)
    assert [path for path, _ in seen] == ['/api/v1/projects/p/rights/get', '/api/v1/projects/p/rights/renew'] and seen[1][1]['expected_generation'] == 2


@pytest.mark.parametrize('kind,ref,key', [('dataset', 'a1', None), ('upload', '', None), ('connection', 'c1', None), ('upload', 'a1', 'curve')])
def test_a_target_that_names_nothing_is_refused_before_any_request(kind, ref, key):
    from ophiolite.errors import Refused
    seen, handler = recording({})
    with client(handler) as c, pytest.raises(Refused, match='Name an upload, a release, or a connection with its key'):
        c.rights(kind, ref, key=key)
    assert seen == []
