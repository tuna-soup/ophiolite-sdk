"""E31 S1: the server's error envelope reaches the caller, bounded, without changing the SDK's categories.

The refusal bodies here are the Platform's P3 envelope as the gateway sends it (the gateway lane replays a
real one in tests/gateway/test_error_envelope.py); a pre-E31 body keeps today's message; a malformed,
truncated or oversized body falls back to the status category; a streaming refusal is read only to the
bound; retries report the last attempt's request id; sharing keeps its own recovery path.
"""
import json
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite import application_transport as policy
from ophiolite.errors import Busy, IntegrityConflict, PermissionRefused, Refused, ShareOutcomeUnknown, Unavailable

ENVELOPE = {'error': 'Not a member of this project', 'code': 'PERMISSION_DENIED', 'message': 'Not a member of this project',
            'remedy': 'Use a credential whose scope, kind and project reach this operation, or ask a project administrator for access.',
            'docs': '/docs/reference/errors/#permission_denied', 'request_id': 'req_0123456789abcdef01234567'}


def client(handler):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_api_alice'),
                  http=httpx.Client(transport=httpx.MockTransport(handler)))


def refusal(status, body, request_id=None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return httpx.Response(status, content=raw, headers={'Content-Type': 'application/json', **({'X-Request-Id': request_id} if request_id else {})})


def test_the_envelope_travels_on_the_sdk_error():
    with client(lambda r: refusal(403, ENVELOPE, ENVELOPE['request_id'])) as c, pytest.raises(PermissionRefused) as raised:
        c._post('entities', 'get', {'entity_id': 'w1'})
    error = raised.value
    assert (error.code, error.status, error.request_id, error.docs) == ('PERMISSION_DENIED', 403, ENVELOPE['request_id'], ENVELOPE['docs'])
    assert error.remedy == ENVELOPE['remedy'] and error.recovery == ENVELOPE['remedy'] and error.message == 'Check project access and the approved grant.'


def test_a_pre_e31_body_keeps_todays_message():
    with client(lambda r: refusal(404, {'error': 'Asset unavailable', 'code': 'not-found'})) as c, pytest.raises(Unavailable) as raised:
        c._post('entities', 'get', {'entity_id': 'w1'})
    error = raised.value
    assert str(error) == 'The requested application data is unavailable or not permitted.' and error.code == 'not-found'
    assert (error.remedy, error.docs, error.request_id) == (None, None, None)


@pytest.mark.parametrize('body', [b'{"error": "cut', b'[1, 2]', b'\xff\xfe', b'{"code": "has spaces and more", "remedy": 7}',
                                  json.dumps({**ENVELOPE, 'remedy': 'x' * 5000}).encode()])
def test_a_malformed_envelope_falls_back_to_the_category(body):
    with client(lambda r: refusal(400, body, ENVELOPE['request_id'])) as c, pytest.raises(Refused) as raised:
        c._post('entities', 'get', {'entity_id': 'w1'})
    error = raised.value  # the header's request id survives whatever the body is
    assert error.request_id == ENVELOPE['request_id'] and error.code in ('INVALID_ARGUMENT', 'PERMISSION_DENIED')
    assert error.remedy is None or len(error.remedy) <= 1000


def test_a_streaming_refusal_is_read_only_to_the_bound():
    served = []
    class Endless(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(10_000):  # 40 MB if read to the end
                served.append(i); yield b'x' * 4096
    with client(lambda r: httpx.Response(400, stream=Endless(), headers={'X-Request-Id': 'req_stream'})) as c, pytest.raises(Refused) as raised:
        c._post('entities', 'get', {'entity_id': 'w1'})
    assert raised.value.request_id == 'req_stream' and len(served) <= policy.ENVELOPE_LIMIT // 4096 + 2


def test_retry_exhaustion_reports_the_last_attempt(monkeypatch):
    import ophiolite.client
    monkeypatch.setattr(ophiolite.client.time, 'sleep', lambda s: None)
    ids = iter(['req_first', 'req_second', 'req_last'])
    def handler(request):
        rid = next(ids)
        return refusal(503, {**ENVELOPE, 'code': 'busy', 'request_id': rid, 'remedy': 'Retry after the number of seconds in Retry-After.'}, rid)
    with client(handler) as c, pytest.raises(Busy) as raised:
        c._post('entities', 'list', {})  # a read: retried
    assert raised.value.request_id == 'req_last' and raised.value.code == 'busy'


def test_sharing_keeps_its_recovery_and_gains_the_metadata():
    with client(lambda r: refusal(503, {**ENVELOPE, 'code': 'UNAVAILABLE', 'request_id': 'req_share'}, 'req_share')) as c, pytest.raises(ShareOutcomeUnknown) as raised:
        c._post('applications', 'share', {'asset_id': 'a'})
    assert raised.value.recovery == policy.SHARE_RECOVERY and raised.value.request_id == 'req_share' and raised.value.code == 'share-outcome-unknown'
    with client(lambda r: refusal(409, {**ENVELOPE, 'code': 'recipients-changed', 'request_id': 'req_conflict'}, 'req_conflict')) as c, pytest.raises(IntegrityConflict) as raised:
        c._post('applications', 'share', {'asset_id': 'a'})
    assert raised.value.recovery == policy.SHARE_RECOVERY and raised.value.code == 'recipients-changed' and raised.value.request_id == 'req_conflict'


def test_the_async_client_reads_the_same_envelope():
    import anyio
    from ophiolite.aio import AsyncClient
    async def main():
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: refusal(403, ENVELOPE, ENVELOPE['request_id'])))
        async with AsyncClient('https://ophiolite.example', 'p', Credential.bearer('oph_api_alice'), http=http) as c:
            with pytest.raises(PermissionRefused) as raised:
                await c._post('entities', 'get', {'entity_id': 'w1'})
        return raised.value
    error = anyio.run(main)
    assert error.request_id == ENVELOPE['request_id'] and error.remedy == ENVELOPE['remedy']


def test_the_event_log_and_project_discovery_carry_it_too():
    from ophiolite.errors import ResyncRequired
    with client(lambda r: refusal(409, {**ENVELOPE, 'code': 'CURSOR_EXPIRED', 'request_id': 'req_log'}, 'req_log')) as c:
        with pytest.raises(ResyncRequired) as raised: list(c.sync().changes('e', 1))
    assert raised.value.request_id == 'req_log' and raised.value.code == 'CURSOR_EXPIRED'
    from ophiolite.account import connect
    with connect('https://ophiolite.example', Credential.bearer('oph_api_alice'), http=httpx.Client(transport=httpx.MockTransport(lambda r: refusal(403, ENVELOPE, ENVELOPE['request_id'])))) as account:
        with pytest.raises(PermissionRefused) as raised: account.projects()
    assert raised.value.request_id == ENVELOPE['request_id'] and raised.value.remedy == ENVELOPE['remedy']
