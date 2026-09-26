"""Run the unchanged synchronous read scenario table through real AsyncClient calls."""
import asyncio
import inspect
import httpx
from ophiolite.aio import AsyncClient
from ophiolite.client import Client


def adapter(loop,instances):
    class ScenarioClient:
        def __init__(self,url,project,credential=None,http=None):
            if http is not None:
                assert isinstance(http._transport,httpx.MockTransport)
                http=httpx.AsyncClient(transport=http._transport)
            self.client=AsyncClient(url,project,credential,http)
            instances.append(self.client)
        @classmethod
        def from_configuration(cls,*args,**kwargs):return Client.from_configuration.__func__(cls,*args,**kwargs)
        def __getattr__(self,name):
            member=getattr(self.client,name)
            if inspect.iscoroutinefunction(member):
                return lambda *args,**kwargs:loop.run_until_complete(member(*args,**kwargs))
            return member
        def assets(self):
            async def collect():return [item async for item in self.client.assets()]
            return iter(loop.run_until_complete(collect()))
        def __enter__(self):return self
        def __exit__(self,*args):loop.run_until_complete(self.client.http.aclose())
    return ScenarioClient
