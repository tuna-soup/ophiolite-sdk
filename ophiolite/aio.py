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


async def _complete(awaitable):
    task=asyncio.create_task(awaitable)
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
        return await _complete(self._credential_transaction())

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
                        from . import application_transport as policy
                        meta=policy.envelope(response,await policy.bounded(response))  # E31: the server's metadata, bounded
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if kind is Busy:raise Busy(message,meta.get('remedy',''),status=response.status_code,retry_after=delay,code=meta.get('code'),**policy.carried(meta))
                        raise kind(message,meta.get('remedy',''),status=response.status_code,code=meta.get('code'),**policy.carried(meta))
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
        descriptors=[];views=[];artifact=None;wire_descriptors=[];wire_curves=[]
        for curve in curves:
            path,query=self._path(asset,revision,curve)
            data=await self._json(path+query,256*1024)
            _core.verify_descriptor(data,self.project,asset,revision,curve)
            raw=_core.rules.artifact(data)
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=await self._get(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=await self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
            wire_descriptors.append(data);wire_curves.append(json.loads(body))
        return CurveSet(descriptors,views,artifact,url=self.url,project=self.project,wire_descriptors=wire_descriptors,wire_curves=wire_curves)

    async def read_data(self,asset,revision):
        """E11: typed read (well tops, trajectory, regular-grid surface); same checks as Client.read_data."""
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        data=await self._json(path,256*1024)
        _core.verify_typed_descriptor(data,self.project,asset,revision)
        raw=_core.rules.artifact(data)
        normalized=next(r for r in data['representations'] if r['kind']=='normalized')
        artifact=None if data['scientific'].get('type')=='seismic-volume' else await self._get(path+'/representations/'+quote(raw['id'],safe=''),raw['bytes'])
        body=await self._get(path+'/representations/'+quote(normalized['id'],safe=''),normalized['bytes'])
        return _core.typed_result(data,body,artifact)

    async def read_slice(self,asset,revision,axis,label,*,volume=None):
        """E16: one slice of a seismic volume; same checks as Client.read_slice."""
        if axis not in ('inline','crossline','sample') or type(label) is not int:raise Refused('Choose an inline, crossline or sample slice by its whole number.')
        if volume is None:volume=await self.read_data(asset,revision)
        volume=self._volume(asset,revision,axis,label,volume)
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/slices/'+quote(axis,safe='')+'/'+str(label)
        return _core.slice_result(volume,await self._get(path,32*1024*1024),asset,revision,axis,label)

    async def export_slices(self,asset,revision,slices,destination):
        """E16: same as Client.export_slices."""
        from .bundle import write_bundle
        chosen=self._slice_choice(slices)
        volume=await self.read_data(asset,revision)
        read=[await self.read_slice(asset,revision,axis,label,volume=volume) for axis,label in chosen]
        return await anyio.to_thread.run_sync(lambda:write_bundle(destination,[({'asset_id':asset,'revision':revision,'curves':[],'slices':[{'axis':a,'label':l} for a,l in chosen]},(volume,read))]))

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

    async def _post_bytes(self,area,operation,raw,*,extra_headers=None,headers=None,retry=False,expected_context=None):
        from . import publish as planning,application_transport as policy
        from .errors import RecoveryUnavailable
        url,project=self.url,self.project
        if expected_context is not None and (url,project)!=expected_context:raise RecoveryUnavailable('The gateway or project changed during this operation.')
        path=planning.operation_path(project,area,operation)
        if extra_headers and any(key.lower() not in ('content-type','x-ophiolite-upload') for key in extra_headers):raise Refused('Saved request headers cannot replace authorization.')
        captured=dict(await self._headers() if headers is None else headers)
        captured.update(extra_headers or {'Content-Type':'application/json'})
        attempts=3 if operation!='share' and (retry or operation in planning.READ_OPERATIONS) else 1
        for attempt in range(attempts):
            if (self.url,self.project)!=(url,project):raise RecoveryUnavailable('The gateway or project changed during this operation.')
            try:
                async with self.http.stream('POST',url+path,content=raw,headers=captured,follow_redirects=False) as response:
                    if response.status_code in (429,503) and attempt+1<attempts:
                        await anyio.sleep(policy.delay(response));continue
                    policy.status(response,operation,None if response.is_success else await policy.bounded(response))
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>policy.MAX_RESPONSE:raise CapacityExceeded('Application response exceeds its supported size.')
                    return policy.decode(bytes(content))
            except httpx.HTTPError:
                if attempt+1<attempts:continue
                policy.disconnected(operation)

    async def _post(self,area,operation,body,**options):
        from .publish import json_bytes
        if 'project_id' in body and body['project_id']!=self.project:raise Refused('The request belongs to another project.')
        return await self._post_bytes(area,operation,json_bytes({'project_id':self.project,**body}),**options)

    async def _grant_status(self,headers):
        from . import application_transport as policy
        from .publish import json_bytes
        try:
            async with self.http.stream('POST',self.url+'/api/v1/application-access/status',
                 content=json_bytes({'id':headers['X-Ophiolite-Application-Grant']}),
                 headers={**headers,'Content-Type':'application/json'},follow_redirects=False) as response:
                policy.status(response,'status',None if response.is_success else await policy.bounded(response));raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>2_100_000:raise CapacityExceeded('Authorization response exceeds its supported size.')
                return policy.decode(bytes(raw))
        except httpx.HTTPError:raise AuthenticationRequired('Authorization could not be confirmed. No mutation was sent.') from None

    async def _application(self,name,/,*args,**kwargs):
        from .models.api import Run
        result=await _complete(anyio.to_thread.run_sync(partial(getattr(_ApplicationDriver(self),name),*args,**kwargs),abandon_on_cancel=False))
        if isinstance(result,Run):
            result._client=self
            if result._work is not None:result._work=AsyncWorkFolder(self,result._work.path,lock_timeout=result._work.lock_timeout)
        return result

    def work_folder(self,path,**options):return AsyncWorkFolder(self,path,**options)


class _ApplicationDriver(Client):
    """Run shared application planning/files in a worker; HTTP stays on its loop."""
    def __init__(self,client):
        self.owner=client
        self.url,self.project,self.prefix=client.url,client.project,client.prefix
        self.credential,self.http,self._owns_http=client.credential,client.http,False

    def _post_bytes(self,area,operation,raw,**options):
        # Acquire the credential in this worker, not a nested worker. A work-folder
        # transaction already supplies its locked immutable identity snapshot.
        if options.get('headers') is None:options['headers']=self._headers()
        return anyio.from_thread.run(partial(self.owner._post_bytes,area,operation,raw,**options))

    def _grant_status(self,headers):return anyio.from_thread.run(self.owner._grant_status,headers)


class AsyncWorkFolder:
    def __init__(self,client,path,**options):self.client,self.path,self.options=client,path,options

    async def _call(self,name,/,*args,**kwargs):
        from .publish import WorkFolder
        from .models.api import Run
        def operation():return getattr(WorkFolder(_ApplicationDriver(self.client),self.path,**self.options),name)(*args,**kwargs)
        result=await _complete(anyio.to_thread.run_sync(operation,abandon_on_cancel=False))
        if isinstance(result,Run):result._client,result._work=self.client,self
        return result


def _async_application(name):
    from functools import wraps
    @wraps(getattr(Client,name))
    async def method(self,*args,**kwargs):return await self._application(name,*args,**kwargs)
    return method


def _async_work(name):
    async def method(self,*args,**kwargs):return await self._call(name,*args,**kwargs)
    method.__name__=name
    return method


for _name in ('configure','start','run_input','publish','download','results','history','grants','share','options','inspect','export',
              'upload_las','inspect_las','upload_info','members','result_preview','result_download','recover'):
    setattr(AsyncClient,_name,_async_application(_name))
for _name in ('configure','start','input','publish','download','upload_las','recover'):
    setattr(AsyncWorkFolder,_name,_async_work(_name))
