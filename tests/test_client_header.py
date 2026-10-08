"""E93 C6: the library, the command line and every gateway path name the program with a literal product/version and
nothing else, and carry the caller's active trace as a valid traceparent (none without one; never invented)."""
import asyncio

import httpx
import pytest

from ophiolite import Client, Credential, _client_header, cli
from ophiolite.account import Account
from ophiolite.agents import AgentClient
from ophiolite.aio import AsyncClient

URL = 'https://gateway.example'


def recorder():
    seen = []
    def handle(request):
        seen.append(dict(request.headers))
        return httpx.Response(403, json={'error': 'no', 'code': 'PERMISSION_DENIED', 'message': 'no'})
    return seen, httpx.MockTransport(handle)


def attempt(call):
    try: call()
    except Exception: pass


def paths():
    """(name, call(transport)) for every way the library reaches the gateway."""
    bearer = Credential.bearer('provider-token', grant='g-1')
    def sync(t): attempt(lambda: list(Client(URL, 'p', bearer, httpx.Client(transport=t)).assets()))
    def upload(t): attempt(lambda: Client(URL, 'p', bearer, httpx.Client(transport=t)).upload_las(b'~V\n', name='n', attribution='a', audience=['alice'], rights_confirmed=True))
    def aio(t):
        async def go():
            client = AsyncClient(URL, 'p', bearer, httpx.AsyncClient(transport=t))
            try:
                async for _ in client.assets(): pass
            except Exception: pass
        asyncio.run(go())
    def agents(t): attempt(lambda: AgentClient(URL, 'p', 'oph_agent_test', http=httpx.Client(transport=t))._post('entities', 'list', {}))
    def discovery(t): attempt(lambda: Account(URL, bearer, http=httpx.Client(transport=t)).projects())
    return [('sync', sync), ('upload', upload), ('aio', aio), ('agents', agents), ('discovery', discovery)]


@pytest.mark.parametrize('name,call', paths(), ids=[n for n, _ in paths()])
def test_every_path_names_the_python_library_and_nothing_else(name, call):
    seen, transport = recorder()
    call(transport)
    assert seen, name
    assert {h['x-ophiolite-client'] for h in seen} == {'ophiolite-python/0.1.0'}  # mutation: the path skipped (agents.py _post)
    assert all('traceparent' not in h for h in seen)  # no active trace: none sent (mutation: an invented id)


def test_the_command_line_names_itself_only_while_it_runs(monkeypatch):
    during = []
    monkeypatch.setattr(cli, '_discover', lambda args: during.append(_client_header.value()) or 0)
    cli.main(['projects', '--url', URL, '--json'])
    assert during == ['ophiolite-cli/0.1.0'] and _client_header.value() == 'ophiolite-python/0.1.0'


def test_an_active_trace_is_sent_as_a_valid_traceparent():
    trace = pytest.importorskip('opentelemetry.trace')
    sdk = pytest.importorskip('opentelemetry.sdk.trace')
    tracer = sdk.TracerProvider().get_tracer('test')
    seen, transport = recorder()
    with tracer.start_as_current_span('caller') as span:
        attempt(lambda: list(Client(URL, 'p', Credential.bearer('t'), httpx.Client(transport=transport)).assets()))
        context = span.get_span_context()
    expected = '00-%032x-%016x-%02x' % (context.trace_id, context.span_id, int(context.trace_flags))
    assert seen[0]['traceparent'] == expected and trace.get_current_span().get_span_context().is_valid is False


def test_the_report_has_no_host_or_user_text():
    value = _client_header.headers()[_client_header.HEADER]
    import getpass, socket
    assert value == 'ophiolite-python/0.1.0' and socket.gethostname() not in value and getpass.getuser() not in value  # mutation: host appended
