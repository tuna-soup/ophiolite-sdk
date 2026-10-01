"""E50a S2: the SDK reaches the source routes and names their refusals.

One table in application_transport selects a class by the server's SOURCE_* code before the HTTP status; the server's
message is passed on verbatim, its code, remedy, docs and request id are kept. A 503 that names a final state
(SOURCE_DETACHED) is answered once, not retried three times as "busy" (re-verification R4). The SDK's own response bound
is stated in bytes. Other areas keep their classes.
"""
import json
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite import application_transport as policy
from ophiolite.errors import (Busy, CapacityExceeded, IntegrityConflict, PermissionRefused, Refused, SourceDetached, SourceNeedsReview,
                              SourceRevisionUnavailable, Unavailable)
from ophiolite.publish import operation_path

ENVELOPE = {'remedy': 'The server says what to do.', 'docs': '/docs/reference/errors/#x', 'request_id': 'req_0123456789abcdef01234567'}


def answer(status, code, message):
    body = {'error': message, 'code': code, 'message': message, **ENVELOPE}
    return httpx.Response(status, content=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Request-Id': ENVELOPE['request_id']})


def client(handler):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=httpx.Client(transport=httpx.MockTransport(handler)))


def counted(response):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return response
    return handler, calls


def test_the_source_reads_are_allowed_and_nothing_else_is():
    """Red before E50a: `sources` had no entry, so `ophiolite sources list` raised Refused('Unsupported application operation.')."""
    assert operation_path('p', 'sources', 'list') == '/api/v1/projects/p/sources/list'
    assert operation_path('p', 'sources', 'export') == '/api/v1/projects/p/sources/export'
    for area, operation in (('sources', 'records'), ('sources', 'bind'), ('sources', 'remove'), ('applications', 'export')):
        with pytest.raises(Refused, match='Unsupported application operation'):
            operation_path('p', area, operation)


@pytest.mark.parametrize('status,code,kind,attempts', [
    (409, 'SOURCE_NEEDS_REVIEW', SourceNeedsReview, 1),
    (410, 'SOURCE_REVISION_UNAVAILABLE', SourceRevisionUnavailable, 1),
    (503, 'SOURCE_DETACHED', SourceDetached, 1),
    (403, 'SOURCE_ACCESS_DENIED', PermissionRefused, 1),
    (404, 'SOURCE_MISSING', Unavailable, 1),
    (410, 'SOURCE_DELETED', Unavailable, 1),
    (503, 'SOURCE_OFFLINE', Busy, 3),
    (503, 'SOURCE_PENDING', Busy, 3),
])
def test_every_source_refusal_has_its_class_and_keeps_the_envelope(status, code, kind, attempts):
    handler, calls = counted(answer(status, code, 'Server words for ' + code))
    with client(handler) as c, pytest.raises(kind) as raised:
        c._post('sources', 'export', {'id': 's1'}, retry=True)
    error = raised.value
    assert type(error) is kind and len(calls) == attempts, (type(error), len(calls))
    assert (error.code, error.status, error.request_id, error.message) == (code, status, ENVELOPE['request_id'], 'Server words for ' + code)
    if code == 'SOURCE_DETACHED':  # the server sends only its generic fallback for this code; the SDK's own remedy and anchor win
        assert error.remedy.startswith('This source was removed from the project. Ask a project administrator to resume it') and error.docs == '/docs/guides/source-rows-and-project-wells/#source-detached'
    else:
        assert (error.remedy, error.docs) == (ENVELOPE['remedy'], ENVELOPE['docs'])


def test_a_detached_source_is_not_retried_three_times_as_busy():
    """The trap R4 names: by status alone a 503 is `Busy` and a read is sent three times. Under the old classification this
    test fails twice over (three requests; a Busy saying "The service is busy")."""
    handler, calls = counted(answer(503, 'SOURCE_DETACHED', 'Source selection is not ready'))
    with client(handler) as c, pytest.raises(SourceDetached) as raised:
        c._post('sources', 'export', {'id': 's1'}, retry=True)
    assert calls == ['/api/v1/projects/p/sources/export'] and not isinstance(raised.value, Busy) and not raised.value.retryable
    assert 'busy' not in str(raised.value).lower()


def test_a_detached_answer_is_final_even_when_the_next_answer_would_succeed():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return answer(503, 'SOURCE_DETACHED', 'Source selection is not ready') if len(calls) == 1 else httpx.Response(200, json={'manifest': {}, 'payload_base64': ''})
    with client(handler) as c, pytest.raises(SourceDetached):
        c._post('sources', 'export', {'id': 's1'}, retry=True)
    assert len(calls) == 1  # the second (successful) answer is never consumed


def test_a_source_refusal_over_the_servers_bound_passes_its_message_on_verbatim():
    message = 'SQL snapshot exceeds 64 MiB'
    handler, _ = counted(answer(409, 'SOURCE_NEEDS_REVIEW', message))
    with client(handler) as c, pytest.raises(SourceNeedsReview) as raised:
        c._post('sources', 'export', {'id': 's1'}, retry=True)
    assert raised.value.message == message and isinstance(raised.value, IntegrityConflict)


def test_a_list_is_retried_on_a_plain_503_and_other_areas_keep_their_classes():
    handler, calls = counted(answer(503, 'busy', 'busy'))
    with client(handler) as c, pytest.raises(Busy):
        c._post('sources', 'list', {})
    assert len(calls) == 3
    handler, _ = counted(answer(409, 'CONFLICT', 'Changed'))
    with client(handler) as c, pytest.raises(IntegrityConflict) as raised:
        c._post('entities', 'create', {})
    assert type(raised.value) is IntegrityConflict and raised.value.message == 'The request conflicts with the stored result.'
    handler, _ = counted(answer(400, 'INVALID_ARGUMENT', 'Source selection is unavailable for this account'))
    with client(handler) as c, pytest.raises(Refused):  # a server 400 stays Refused (disposition 5)
        c._post('sources', 'export', {'id': 'nope'}, retry=True)


def test_the_sdk_response_bound_is_stated_in_bytes(monkeypatch):
    monkeypatch.setattr(policy, 'MAX_RESPONSE', 1024)
    big = httpx.Response(200, content=b'{"payload_base64": "' + b'A' * 4096 + b'"}', headers={'Content-Type': 'application/json'})
    with client(lambda r: big) as c, pytest.raises(CapacityExceeded) as raised:
        c._post('sources', 'export', {'id': 's1'}, retry=True)
    assert '1,024 bytes' in raised.value.message and raised.value.remedy and raised.value.docs.endswith('#capacity-exceeded')


def test_the_asynchronous_driver_shares_the_table_and_the_bound(monkeypatch):
    import anyio
    from ophiolite.aio import AsyncClient
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return answer(503, 'SOURCE_DETACHED', 'Source selection is not ready') if len(calls) == 1 else httpx.Response(200, content=b'{"x": "' + b'A' * 4096 + b'"}')
    async def main():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with AsyncClient('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=http) as c:
            with pytest.raises(SourceDetached):
                await c._post('sources', 'export', {'id': 's1'}, retry=True)
            assert len(calls) == 1
            monkeypatch.setattr(policy, 'MAX_RESPONSE', 1024)
            with pytest.raises(CapacityExceeded, match='1,024 bytes'):
                await c._post('sources', 'export', {'id': 's1'}, retry=True)
    anyio.run(main)
