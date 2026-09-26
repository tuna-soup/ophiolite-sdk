"""Asyncio transport over the same scientific verification and credential store."""
import asyncio
from functools import partial
import json
import math
from urllib.parse import quote
import anyio
import httpx
from . import _core
from .client import Client, CurveSet
from .errors import (AuthenticationRequired,PermissionRefused,Unavailable,IntegrityConflict,
                     CapacityExceeded,Refused,Incompatible,Busy,VerificationFailed,OphioliteError)


class AsyncClient(Client):
    def __init__(self,url,project,credential=None,http=None):
        # Validate before allocating a transport; the inherited configuration and
        # path builders are pure and shared with the synchronous client.
        _core.origin(url)
        if not isinstance(project,str) or not project:raise Refused('Choose a project.')
        super().__init__(url,project,credential,http or httpx.AsyncClient(timeout=60,follow_redirects=False,trust_env=False))
        self._owns_http=http is None
        self._credential_lock=anyio.Lock()

    async def close(self):
        if self._owns_http:await self.http.aclose()
    aclose=close
    async def __aenter__(self):return self
    async def __aexit__(self,*args):await self.close()
    def __enter__(self):raise TypeError('Use async with AsyncClient.')
    def __exit__(self,*args):raise TypeError('Use async with AsyncClient.')

    async def _credential_transaction(self):
        async with self._credential_lock:
            with anyio.CancelScope(shield=True):
                return await anyio.to_thread.run_sync(
                    partial(self.credential.headers,self.url,self.project),abandon_on_cancel=False)

    async def _headers(self):
        if self.credential is None:return {}
        # A raw asyncio Task.cancel is stronger than an AnyIO cancellation scope.
        # Own the mutex in the worker task and drain it even in that case. Token
        # rotation finishes before cancellation returns or another worker enters.
        task=asyncio.create_task(self._credential_transaction())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                while not task.done():
                    try:await asyncio.shield(task)
                    except asyncio.CancelledError:continue
                    except Exception:break
                try:task.result()
                except Exception:pass
            raise

    async def _get(self,path,limit):
        headers=await self._headers()
        categories={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
                    404:(Unavailable,'This exact revision is unavailable or not permitted.'),409:(IntegrityConflict,'Stored data failed an integrity check. Ask the deployment administrator.'),
                    413:(CapacityExceeded,'Representation exceeds the bounded size; partial reads are not supported.'),400:(Refused,'The request was refused. Check the selected input.'),
                    422:(Incompatible,'This scientific context is not supported.'),503:(Busy,'The service is busy or unavailable.'),429:(Busy,'The service is busy or unavailable.')}
        for attempt in range(3):
            try:
                async with self.http.stream('GET',self.url+path,headers=headers,follow_redirects=False) as response:
                    delay=0
                    if response.status_code in (429,503):
                        try:delay=float(response.headers.get('Retry-After','0'))
                        except ValueError:delay=0
                        if not math.isfinite(delay) or delay<0 or delay>60:delay=0
                        if attempt<2:
                            await anyio.sleep(delay);continue
                    if response.status_code!=200:
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if kind is Busy:raise Busy(message,status=response.status_code,retry_after=delay)
                        raise kind(message,status=response.status_code)
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>limit:raise CapacityExceeded('Scientific response exceeds its bounded size limit.')
                    return bytes(content)
            except httpx.HTTPError:
                raise Unavailable('Cannot reach the service. Check its address and network connection.',code='unreachable') from None
        raise Unavailable('The service remains unavailable.')

    async def _json(self,path,limit):
        try:return json.loads(await self._get(path,limit))
        except (ValueError,UnicodeError) as error:
            if isinstance(error,OphioliteError):raise
            raise VerificationFailed('Scientific response is not valid JSON.') from None

    async def assets(self):
        cursor='';seen=set()
        while True:
            page=await self._json(self.prefix+'?limit=100&cursor='+quote(cursor,safe=''),2_100_000)
            if not isinstance(page,dict) or not isinstance(page.get('items'),list):raise VerificationFailed('Invalid scientific catalogue response.')
            for item in page['items']:yield item
            cursor=page.get('next_cursor')
            if cursor is None or cursor=='':return
            if not isinstance(cursor,str) or len(cursor)>2000 or cursor in seen:raise VerificationFailed('Invalid or repeated catalogue cursor.')
            seen.add(cursor)

    async def describe(self,asset,revision,curve):
        path,query=self._path(asset,revision,curve)
        return _core.verify_descriptor(await self._json(path+query,256*1024),self.project,asset,revision,curve)

    async def read(self,asset,revision,curves,*,strict_interpretation=False):
        if not isinstance(curves,(list,tuple)) or not curves or len(set(curves))!=len(curves):
            raise Refused('Choose distinct value curves explicitly.')
        descriptors=[];views=[];artifact=None
        for curve in curves:
            descriptor=await self.describe(asset,revision,curve);data=descriptor.model_dump(by_alias=True,exclude_unset=True)
            path,query=self._path(asset,revision,curve)
            raw=next(r for r in data['representations'] if r['kind']!='normalized')
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=await self._get(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=await self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
        return CurveSet(descriptors,views,artifact,url=self.url,project=self.project)

    async def read_many(self,selections,**options):
        results=[None]*len(selections)
        async def read_one(index,selection):
            results[index]=await self.read(*selection,**options)
        # gather retains input order and propagates domain errors without wrapping
        # them in an ExceptionGroup. Cancel/drain peers on failure; no partial result.
        tasks=[asyncio.create_task(read_one(i,item)) for i,item in enumerate(selections)]
        try:await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            raise
        return results
