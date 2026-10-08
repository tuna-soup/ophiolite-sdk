import asyncio
from contextlib import contextmanager
import json
import multiprocessing
import threading
import anyio
import httpx
import pytest
from ophiolite import auth,Client
from ophiolite.aio import AsyncClient
from ophiolite.errors import AuthenticationRequired
from test_auth_concurrency import TokenServer,configured

@pytest.fixture
def anyio_backend():return 'asyncio'


def hold_file_lock(path,ready,release):
    with auth._lock(path):
        ready.set();release.wait(5)


@pytest.mark.anyio
async def test_process_lock_does_not_block_heartbeat(tmp_path,monkeypatch):
    with TokenServer() as server:
        path=configured(tmp_path,server);server.release.set()
        ctx=multiprocessing.get_context('spawn');ready=ctx.Event();release=ctx.Event()
        process=ctx.Process(target=hold_file_lock,args=(path,ready,release));process.start()
        real_lock=auth._lock
        @contextmanager
        def bounded_lock(path,**kwargs):
            with real_lock(path,timeout=.8,**kwargs):yield
        monkeypatch.setattr(auth,'_lock',bounded_lock)
        credential=auth.Credential.open(path);entered=threading.Event();real_headers=credential.headers
        def headers(*args,**kwargs):entered.set();return real_headers(*args,**kwargs)
        credential.headers=headers
        heartbeat=[]
        async def beat():
            assert await anyio.to_thread.run_sync(entered.wait,2)
            for _ in range(3):
                await anyio.sleep(.02);heartbeat.append(True)
            release.set()
        try:
            assert await anyio.to_thread.run_sync(ready.wait,3)
            async with AsyncClient(server.url,'test',credential) as client:
                ticker=asyncio.create_task(beat())
                result=await client._headers()
                await ticker
                assert result['Authorization']=='Bearer rotated-access'
                assert len(heartbeat)==3 and len(server.requests)==1
        finally:
            release.set();server.release.set();await anyio.to_thread.run_sync(process.join,3)
            if process.is_alive():process.terminate();process.join()


@pytest.mark.anyio
@pytest.mark.parametrize('phase',['lock','provider'])
@pytest.mark.parametrize('cancel_style',['asyncio','anyio'])
async def test_cancel_drains_credential_transaction(tmp_path,phase,cancel_style):
    with TokenServer() as server:
        path=configured(tmp_path,server);credential=auth.Credential.open(path)
        ctx=multiprocessing.get_context('spawn');ready=ctx.Event();release=ctx.Event();process=None
        entered=threading.Event();real_headers=credential.headers
        def headers(*args,**kwargs):entered.set();return real_headers(*args,**kwargs)
        credential.headers=headers
        if phase=='lock':
            process=ctx.Process(target=hold_file_lock,args=(path,ready,release));process.start()
            assert await anyio.to_thread.run_sync(ready.wait,3)
        scope=[];finished=[]
        async with AsyncClient(server.url,'test',credential) as client:
            async def run():
                with anyio.CancelScope() as cancel:
                    scope.append(cancel)
                    await client._headers()
                finished.append(True)
            task=asyncio.create_task(run())
            try:
                assert await anyio.to_thread.run_sync(entered.wait,3)
                if phase=='provider':assert await anyio.to_thread.run_sync(server.first.wait,3)
                if cancel_style=='asyncio':task.cancel()
                else:scope[0].cancel()
                await anyio.sleep(.03)
                assert not task.done(), 'Cancellation abandoned an active credential worker'
                assert client._credential_lock.locked()
                release.set();server.release.set()
                if cancel_style=='asyncio':
                    with pytest.raises(asyncio.CancelledError):await task
                else:await task
                assert not client._credential_lock.locked()
                assert json.loads(path.read_text())['generation']==2
                assert (await client._headers())['Authorization']=='Bearer rotated-access'
                assert len(server.requests)==1
            finally:
                release.set();server.release.set()
                await asyncio.gather(task,return_exceptions=True)
                if process:
                    await anyio.to_thread.run_sync(process.join,3)
                    if process.is_alive():process.terminate();process.join()


@pytest.mark.anyio
async def test_sync_and_async_share_one_refresh(tmp_path):
    with TokenServer() as server:
        path=configured(tmp_path,server)
        sync=auth.Credential.open(path);asynchronous=auth.Credential.open(path)
        first=asyncio.create_task(anyio.to_thread.run_sync(sync.headers,server.url,'test'))
        entered=threading.Event();captured=threading.Event();real_headers=asynchronous.headers;real_current=asynchronous._current
        def headers(*args):entered.set();return real_headers(*args)
        def current():captured.set();return real_current()
        asynchronous.headers=headers;asynchronous._current=current
        async with AsyncClient(server.url,'test',asynchronous) as client:
            second=None
            try:
                assert await anyio.to_thread.run_sync(server.first.wait,3)
                second=asyncio.create_task(client._headers())
                assert await anyio.to_thread.run_sync(entered.wait,3)
                await anyio.sleep(.1)
                assert not captured.is_set() and not server.second.is_set()
                server.release.set()
                assert {**await first,"X-Ophiolite-Client":"ophiolite-python/0.1.0"}==await second  # E93: the client stamps its name
                assert len(server.requests)==1
            finally:
                server.release.set()
                await asyncio.gather(*[t for t in (first,second) if t],return_exceptions=True)


@pytest.mark.anyio
async def test_concurrent_read_many_preserves_order_and_refreshes_once(tmp_path,fixture):
    d,raw,artifact=fixture()
    with TokenServer() as server:
        path=configured(tmp_path,server)
        value=json.loads(path.read_text());value['credential']['project']=d['project_id'];path.write_text(json.dumps(value))
        credential=auth.Credential.open(path)
        seen=[]
        async def handle(request):
            assert request.headers['Authorization']=='Bearer rotated-access'
            seen.append(request.url.path)
            if '/representations/' in request.url.path:
                return httpx.Response(200,content=raw if request.url.path.endswith('/curve') else artifact)
            selected=request.url.path.split('/scientific-assets/',1)[1].split('/revisions/',1)[0]
            descriptor=dict(d);descriptor['asset_id']=selected
            if selected=='second':await anyio.sleep(.02)
            return httpx.Response(200,json=descriptor)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            async with AsyncClient(server.url,d['project_id'],credential,http) as client:
                task=asyncio.create_task(client.read_many([(asset,d['revision'],['GR']) for asset in ('second','first')]))
                try:
                    assert await anyio.to_thread.run_sync(server.first.wait,3)
                    await anyio.sleep(.05);assert len(server.requests)==1
                    server.release.set();result=await task
                    assert [item.descriptors[0].asset_id for item in result]==['second','first']
                    assert all(item.curves[0].values==[0,10,None,30,40] for item in result)
                    assert len(seen)==6 and len(server.requests)==1
                finally:
                    server.release.set();await asyncio.gather(task,return_exceptions=True)


@pytest.mark.anyio
async def test_cancel_mid_read_closes_stream_without_partial_result(tmp_path,fixture):
    d,raw,artifact=fixture();entered=asyncio.Event();closed=[];results=[]
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield artifact[:4];entered.set();await asyncio.Event().wait();yield artifact[4:]
        async def aclose(self):closed.append(True)
    async def handle(request):
        if request.url.path.endswith('/las'):return httpx.Response(200,stream=SlowStream())
        if request.url.path.endswith('/curve'):return httpx.Response(200,content=raw)
        return httpx.Response(200,json=d)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with AsyncClient('http://localhost',d['project_id'],http=http) as client:
            async def read():results.append(await client.read(d['asset_id'],d['revision'],['GR']))
            task=asyncio.create_task(read());await asyncio.wait_for(entered.wait(),2);task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
    assert closed==[True] and not results and not list(tmp_path.iterdir())


@pytest.mark.anyio
async def test_async_resource_ownership_and_configuration(tmp_path):
    path=tmp_path/'configuration.json';path.write_text(json.dumps({'schema':'ophiolite.read-configuration/1','url':'http://localhost','project':'p'}))
    client=AsyncClient.from_configuration(path)
    async with client:assert not client.http.is_closed
    assert client.http.is_closed
    async with httpx.AsyncClient() as external:
        async with AsyncClient('http://localhost','p',http=external):pass
        assert not external.is_closed


@pytest.mark.anyio
async def test_cancel_with_failed_refresh_preserves_cancellation_and_old_cache(tmp_path,monkeypatch):
    with TokenServer() as server:
        path=configured(tmp_path,server);before=path.read_bytes();entered=threading.Event();release=threading.Event()
        def denied(*args,**kwargs):
            entered.set();release.wait(3)
            raise AuthenticationRequired('Synthetic provider refusal.')
        monkeypatch.setattr(auth,'request',denied)
        async with AsyncClient(server.url,'test',auth.Credential.open(path)) as client:
            task=asyncio.create_task(client._headers())
            try:
                assert await anyio.to_thread.run_sync(entered.wait,2)
                task.cancel();await anyio.sleep(.02);assert not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):await task
                assert path.read_bytes()==before and not client._credential_lock.locked()
                with pytest.raises(AuthenticationRequired):await client._headers()
            finally:
                release.set();await asyncio.gather(task,return_exceptions=True)


# --- E50a S4: the same source read for the asynchronous client ------------------------------------------------------

def _source_gateway(export, calls=None):
    from test_sources import exported, payload, selection
    selected = selection(export if isinstance(export, dict) else exported(payload()))  # the answers below are of this table
    def handle(request):
        operation = request.url.path.rsplit('/', 1)[-1]
        if calls is not None: calls.append(operation)
        if operation == 'list': return httpx.Response(200, json={'selections': [selected], 'scope': 's'})
        return export(request) if callable(export) else httpx.Response(200, json=export)
    return handle


@pytest.mark.anyio
async def test_async_source_read_matches_the_synchronous_one():
    from test_sources import exported, payload
    from ophiolite.aio import AsyncSource
    answer = exported(payload())
    with Client('http://localhost', 'p', http=httpx.Client(transport=httpx.MockTransport(_source_gateway(answer)))) as sync:
        expected = sync.source('s1').read(); described = sync.source('s1').describe().to_dict()
    async with httpx.AsyncClient(transport=httpx.MockTransport(_source_gateway(answer))) as http:
        async with AsyncClient('http://localhost', 'p', http=http) as client:
            listed = await client.sources()
            source = await client.source('s1')
            snapshot = await source.read(expect_revision=source.revision)
            description = await source.describe()
    assert [type(s) for s in listed] == [AsyncSource] and source.revision == expected.revision
    assert (snapshot.rows, snapshot.original, snapshot.revision, snapshot.crs) == (expected.rows, expected.original, expected.revision, expected.crs)
    assert description.to_dict() == described


@pytest.mark.anyio
async def test_async_source_errors_match_the_synchronous_ones():
    from test_sources import exported, payload
    from ophiolite.errors import SourceChecksumMismatch, SourceDetached, SourceNotFound, SourceNotSupported, SourceRevisionDiffers
    good = exported(payload())
    tampered = {**good, 'payload_base64': __import__('base64').b64encode(payload().replace(b'"x":4.3', b'"x":4.4')).decode()}
    detached = lambda request: httpx.Response(503, json={'code': 'SOURCE_DETACHED', 'message': 'Source selection is not ready', 'error': 'x'})
    for export, call, expected in ((good, lambda s: s.read(expect_revision='0' * 64), SourceRevisionDiffers), (tampered, lambda s: s.read(), SourceChecksumMismatch),
                                   (detached, lambda s: s.read(), SourceDetached)):
        calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(_source_gateway(export, calls))) as http:
            async with AsyncClient('http://localhost', 'p', http=http) as client:
                source = await client.source('s1')
                with pytest.raises(expected): await call(source)
                with pytest.raises(SourceNotFound): await client.source('nope')
        assert calls.count('export') == 1, (expected, calls)
    from test_sources import selection
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'selections': [selection(None, profile='las2/1')], 'scope': 's'}))) as http:
        async with AsyncClient('http://localhost', 'p', http=http) as client:
            with pytest.raises(SourceNotSupported): await (await client.source('s1')).read()


@pytest.mark.anyio
async def test_cancel_mid_source_read_completes_the_request_and_returns_nothing():
    from test_sources import exported, payload
    answer = json.dumps(exported(payload())).encode(); entered = asyncio.Event(); release = threading.Event(); closed = []; results = []
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield answer[:10]; entered.set()
            while not release.is_set(): await asyncio.sleep(0.01)
            yield answer[10:]
        async def aclose(self): closed.append(True)
    def export(request): return httpx.Response(200, stream=SlowStream(), headers={'Content-Type': 'application/json'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(_source_gateway(export))) as http:
        async with AsyncClient('http://localhost', 'p', http=http) as client:
            source = await client.source('s1')
            async def read(): results.append(await source.read())
            task = asyncio.create_task(read()); await asyncio.wait_for(entered.wait(), 5); task.cancel(); release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert task.done() and task.cancelled()
    assert closed == [True] and results == []  # the response was read to its end and closed; no partial or late result
