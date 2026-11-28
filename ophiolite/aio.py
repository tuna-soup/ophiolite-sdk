"""Asyncio transport over the same scientific verification and credential store."""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

import asyncio
from functools import partial
import json
import math
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode
import anyio
import httpx
from . import _client_header  # E93
from . import _core
from . import _deprecation  # E148
from . import _ranges  # E100d1
from .client import Client, CurveSet, PROFILES
from .client import (PROVENANCE_BYTES,NO_SOURCE_RECORDS,_provenance_path,_provenance_of,_no_provenance_route,  # E122 s5b
                     _parts_of,_warn_source_records_omitted)
from .errors import (AuthenticationRequired,PermissionRefused,Unavailable,IntegrityConflict,
                     CapacityExceeded,Refused,Incompatible,Busy,VerificationFailed,OphioliteError)

if TYPE_CHECKING:  # E217 s0 (D1, D2): read by a type checker only; `import ophiolite.aio` loads none of these
    import os
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path
    from typing import Any

    from .bundle import Bundle
    from .client import Provenance
    from .models.api import (Binding, Grants, History, Receipt, RestrictedReceipt, RestrictedResultPreview, RestrictedResultSummary,
                             RestrictedRun, ResultPreview, ResultSummary, Run, UploadResult)
    from .models.generated import ApplicationCurve, ScientificAsset, SearchAnswer, SearchAnswerByMeaning, SearchRow, SurveyPage
    from .models.items import AssetItem
    from .surveys import Survey
    from .typed import SeismicSlice, TypedData
    from .volume_windows import AsyncWindowReader, VolumeWindowResult
    from .windows import CurveWindow


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
    """One project on an Ophiolite deployment, as `Client` gives it, with each request awaited.

    It takes the arguments `Client` takes and is used in `async with` (a plain `with` is refused). Awaited, a method
    answers what the `Client` method of the same name answers; `assets` is an asynchronous iterator (`async for`) and
    `work_folder` gives a folder whose calls are awaited. A `Client` method whose synchronous body cannot run over this
    client's transport raises TypeError naming the `Client` method, before any request.
    """
    if TYPE_CHECKING:  # E217 s0 (D2): the coroutines the loop at the end of this module attaches, named for a type checker;
        # never defined at run time. Each repeats its Client method's parameters and return exactly
        # (tests/test_async_declarations.py); awaited, it gives what the Client method returns.
        # A declaration that spans lines carries its ignore on the first, where a checker reports the override.
        async def configure(self, asset: str | None = None, revision: str | None = None, *, curve: str, name: str,  # type: ignore[override]
                            command_id: str | None = None, publication_profile: str = 'las-derived-curves/1', release_id=None,
                            asset_index: int = 0, runners=None) -> Binding: ...
        async def start(self, binding, *, application_version, parameters, command_id: str | None = None) -> Run: ...  # type: ignore[override]
        async def run_input(self, run) -> tuple[bytes, ApplicationCurve]: ...  # type: ignore[override]
        async def publish(self, run, *, derived_curves=None, changes=None, new_version_of=None) -> Receipt: ...  # type: ignore[override]
        async def download(self, receipt) -> bytes: ...  # type: ignore[override]
        async def results(self) -> list[ResultSummary | RestrictedResultSummary]: ...  # type: ignore[override]
        async def history(self, asset) -> History: ...  # type: ignore[override]
        async def grants(self, asset) -> Grants: ...  # type: ignore[override]
        async def share(self, asset, *, read, expected_generation: int, reuse=None, command_id: str | None = None,  # type: ignore[override]
                        project: bool | None = None) -> Grants | UploadResult | ResultSummary | RestrictedResultSummary: ...
        async def options(self) -> dict[str, Any]: ...  # type: ignore[override]
        async def inspect(self, asset: str | None = None, revision: str | None = None, *, curve: str = '', name: str = '',  # type: ignore[override]
                          release_id=None, asset_index: int = 0) -> dict[str, Any]: ...
        async def export(self, selections, destination: str | os.PathLike[str], *, groups: bool = True,  # type: ignore[override]
                         entities: bool = True, citation=None) -> Bundle: ...
        async def upload_las(self, source, *, name, attribution, audience, rights_confirmed, filename=None,  # type: ignore[override]
                             well_notes='', command_id=None, curve_declaration=None) -> UploadResult: ...
        async def inspect_las(self, source) -> dict[str, Any]: ...  # type: ignore[override]
        async def upload_info(self, asset) -> UploadResult: ...  # type: ignore[override]
        async def members(self) -> dict[str, Any]: ...  # type: ignore[override]
        async def result_preview(self, asset) -> ResultPreview | RestrictedResultPreview: ...  # type: ignore[override]
        async def result_download(self, asset) -> tuple[bytes, Receipt | RestrictedReceipt, Run | RestrictedRun]: ...  # type: ignore[override]
        async def recover(self, path: str | os.PathLike[str], through: str | None = None) -> Binding | Run | Receipt | UploadResult | None: ...  # type: ignore[override]
        async def upload_data(self, source, *, profile, name, attribution, audience, rights_confirmed, declared=None,  # type: ignore[override]
                              filename=None, well_log=None, well_notes='', command_id=None, origin=None, append_to=None,
                              expected_parent=None, provenance=None, application_source=None, represents=None, holder=None,
                              application=None, receipt=None, curve_declaration=None, made_for=None) -> UploadResult: ...
        async def served_limits(self) -> dict[str, Any]: ...  # type: ignore[override]
        async def download_original(self, asset: str, revision: str, destination: str | os.PathLike[str], *,  # type: ignore[override]
                                    part_bytes: int = 8 * 1024 * 1024) -> Path: ...
        async def survey(self, survey_id: str, revision=None, *, view: str = 'revision') -> Survey: ...  # type: ignore[override]
        async def create_survey(self, name, members, *, relations=(), identity=None, context=None, source=None,  # type: ignore[override]
                                command_id=None) -> dict[str, Any]: ...
        async def add_survey_members(self, survey_id, expected_revision, members, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def remove_survey_members(self, survey_id, expected_revision, members, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def replace_survey_member(self, survey_id, expected_revision, old, new, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def relate_survey_members(self, survey_id, expected_revision, relations, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def unrelate_survey_members(self, survey_id, expected_revision, relations, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def rename_survey(self, survey_id, expected_revision, name, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def identify_survey(self, survey_id, expected_revision, identity, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def withdraw_survey(self, survey_id, expected_revision, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def restate_survey(self, survey_id, expected_revision, members, relations=(), *, name=None,  # type: ignore[override]
                                 command_id=None) -> dict[str, Any]: ...
        async def link_survey_members(self, survey_id, expected_revision, members, *, command_id=None) -> dict[str, Any]: ...  # type: ignore[override]
        async def holders(self, item: str | None = None) -> dict[str, Any]: ...  # type: ignore[override]
        async def affected(self, item: str, *, against: str = 'head') -> dict[str, Any]: ...  # type: ignore[override]
        async def receipts(self, item: str, revision: str) -> dict[str, Any]: ...  # type: ignore[override]
        async def find(self, organization: str, text: str | None = None, *, method: str | None = None, kinds=None,  # type: ignore[override]
                       well=None, bbox=None, since=None, until=None, published_by=None, projects=None, include_archived: bool = False,
                       limit: int = 20, cursor: str | None = None) -> SearchAnswer | SearchAnswerByMeaning: ...
        async def find_log(self, *, curves: str | Sequence[str] = (), quantity: str | None = None,  # type: ignore[override]
                           name: str | None = None, operation: str = 'use-as-input') -> AssetItem: ...

    def __init__(self,url,project,credential=None,http=None,*,application=None,host=None):
        # Validate before allocating a transport; the inherited configuration and
        # path builders are pure and shared with the synchronous client.
        _core.origin(url)
        if not isinstance(project,str) or not project:raise Refused('Choose a project.')
        _client_header.sender(application,host)  # E182 s1: refused before a transport exists
        super().__init__(url,project,credential,http or httpx.AsyncClient(timeout=60,follow_redirects=False,trust_env=False),application=application,host=host)
        self._owns_http=http is None
        self._credential_lock=anyio.Lock()

    async def close(self) -> None:  # type: ignore[override]
        """Close the connection, unless you gave the client your own httpx client; `aclose` is the same call."""
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
        if self.credential is None:return _client_header.stamp({},self._sender)  # E93, E182 s1
        return _client_header.stamp(await _complete(self._credential_transaction()),self._sender)

    async def _get(self,path,limit,*,ranged=None,answer=None):
        headers=await self._headers()
        if ranged is not None:headers={**headers,'Range':ranged}  # E54: one byte range of an original; 206 answers it
        categories={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
                    404:(Unavailable,'This exact revision is unavailable or not permitted.'),409:(IntegrityConflict,'Stored data failed an integrity check. Ask the deployment administrator.'),
                    413:(CapacityExceeded,'Representation exceeds the bounded size; partial reads are not supported.'),400:(Refused,'The request was refused. Check the selected input.'),
                    422:(Incompatible,'This scientific context is not supported.'),503:(Busy,'The service is busy or unavailable.'),429:(Busy,'The service is busy or unavailable.'),
                    416:(Refused,'This byte range is outside the file.')}
        for attempt in range(3):
            try:
                async with self.http.stream('GET',self.url+path,headers=headers,follow_redirects=False) as response:
                    _deprecation.note(_deprecation.of(self),'GET',self.url+path,response)
                    delay=0
                    if response.status_code in (429,503):
                        try:delay=float(response.headers.get('Retry-After','0'))
                        except ValueError:delay=0
                        if not math.isfinite(delay) or delay<0 or delay>60:delay=0
                        if attempt<2:
                            await anyio.sleep(delay);continue
                    if response.status_code!=(200 if ranged is None else 206):
                        from . import application_transport as policy
                        meta=policy.envelope(response,await policy.bounded(response))  # E31: the server's metadata, bounded
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if response.status_code==422 and meta.get('message'):message=meta['message']  # H48: the server's reason, not the generic sentence
                        if kind is Busy:raise Busy(message,meta.get('remedy',''),status=response.status_code,retry_after=delay,code=meta.get('code'),**policy.carried(meta))
                        raise kind(message,meta.get('remedy',''),status=response.status_code,code=meta.get('code'),**policy.carried(meta))
                    if answer is not None:answer.update({k.lower():v for k,v in response.headers.items() if k.lower() in ('content-range','x-content-sha256','etag','x-ophiolite-access-generation','x-ophiolite-revision','content-disposition','x-ophiolite-window','x-ophiolite-piece')})  # E100a: window validators; E141 (R1-7): sync parity and a piece's identity
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

    async def assets(self) -> AsyncIterator[AssetItem]:  # type: ignore[override]
        """Every item in this project that you may read, one page asked at a time, for `async for`."""
        cursor='';seen=set()
        while True:
            page=await self._json(self.prefix+'?limit=100&cursor='+quote(cursor,safe=''),2_100_000)
            if not isinstance(page,dict) or not isinstance(page.get('items'),list):raise VerificationFailed('Invalid scientific catalogue response.')
            for item in page['items']:yield item
            cursor=page.get('next_cursor')
            if cursor is None or cursor=='':return
            if not isinstance(cursor,str) or len(cursor)>2000 or cursor in seen:raise VerificationFailed('Invalid or repeated catalogue cursor.')
            seen.add(cursor)

    async def describe(self,asset,revision,curve) -> ScientificAsset:  # type: ignore[override]
        """What the server states about one curve of an exact version, checked, without reading its values."""
        path,query=self._path(asset,revision,curve)
        return _core.verify_descriptor(await self._json(path+query+PROFILES,256*1024),self.project,asset,revision,curve)

    async def read(self,asset,revision,curves,*,strict_interpretation=False) -> CurveSet:  # type: ignore[override]
        """Read chosen curves of one exact version, each checked against what the server stored; see Client.read()."""
        if not isinstance(curves,(list,tuple)) or not curves or len(set(curves))!=len(curves):
            raise Refused('Choose distinct value curves explicitly.')
        descriptors=[];views=[];artifact=None;wire_descriptors=[];wire_curves=[]
        for curve in curves:
            path,query=self._path(asset,revision,curve)
            data=await self._json(path+query+PROFILES,256*1024)
            _core.refuse_windows_only(_core.verify_descriptor(data,self.project,asset,revision,curve))
            raw=_core.rules.artifact(data)
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=await self._artifact(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=await self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
            wire_descriptors.append(data);wire_curves.append(json.loads(body))
        return CurveSet(descriptors,views,artifact,url=self.url,project=self.project,wire_descriptors=wire_descriptors,wire_curves=wire_curves)

    async def _artifact(self,path,size):
        """E100d1: Client._artifact with the same checks."""
        if size<=_ranges.WHOLE_BYTES:return await self._get(path,size)
        parts,out=_ranges.Parts(size=size),bytearray()
        while parts.pending():
            answer={}
            out.extend(parts.accept(await self._get(path,parts.part_bytes,ranged=parts.range(),answer=answer),answer))
        return bytes(out)

    async def curve_window(self,asset,revision,curve,top,base,*,level=None,rows=None,max_pages=64) -> CurveWindow:  # type: ignore[override]
        """The part of one exact curve between two depths, for display, with the checks of Client.curve_window()."""
        # E100a
        from .windows import Window,PAGE_BYTES
        window=Window(self.project,asset,revision,curve,top,base,level,rows,max_pages)
        path,query=self._path(asset,revision,curve)
        data=await self._json(path+query+PROFILES,256*1024)
        _core.verify_descriptor(data,self.project,asset,revision,curve);window.bind(data)
        while True:
            answer={}
            if not window.accept(await self._get(window.path(path),PAGE_BYTES,answer=answer),answer):return window.result()

    async def read_data(self,asset,revision) -> TypedData:  # type: ignore[override]
        """Read well tops, a trajectory, a surface or another kind of data at one exact version; see Client.read_data()."""
        # E11
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        data=await self._json(path+'?'+PROFILES[1:],256*1024)
        _core.verify_typed_descriptor(data,self.project,asset,revision)
        raw=_core.rules.artifact(data)
        normalized=next(r for r in data['representations'] if r['kind']=='normalized')
        artifact=None if data['scientific'].get('type')=='seismic-volume' else await self._artifact(path+'/representations/'+quote(raw['id'],safe=''),raw['bytes'])
        body=await self._artifact(path+'/representations/'+quote(normalized['id'],safe=''),normalized['bytes'])  # E139 s2: by ranges above the bound
        return _core.typed_result(data,body,artifact)

    async def read_window(self,asset,revision,*,inline=None,crossline=None,trace=None,sample=None,by=None,description=None) -> VolumeWindowResult:  # type: ignore[override]
        """Read part of a seismic volume or of a 2D line at one exact version, checked; see Client.read_window()."""
        # E141
        reader=await self.iter_window(asset,revision,inline=inline,crossline=crossline,trace=trace,sample=sample,by=by,description=description)
        from .volume_windows import VolumeWindowResult
        traces=[]
        async for piece in reader:traces.extend(piece.values)
        return VolumeWindowResult(reader.window,traces)

    async def iter_window(self,asset,revision,*,inline=None,crossline=None,trace=None,sample=None,by=None,description=None) -> AsyncWindowReader:  # type: ignore[override]
        """Read the window `read_window` reads, one checked piece at a time, as an AsyncWindowReader.

        Use it with `async for`, `async with` or `aclose()`; see Client.iter_window().
        """
        # E141
        from .volume_windows import AsyncWindowReader,Window,asked,check_document,parse_window,window_path
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        query=parse_window(inline=inline,crossline=crossline,trace=trace,sample=sample,by=by)
        base=window_path(self.prefix,asset,revision)
        description=await self._window_description(asset,revision,description)  # E140 s3: first, so a native cube asks windows=2 (R5)
        request=asked(query,description)
        document=await self._window_json(base+('?'+urlencode(request) if request else ''))
        return AsyncWindowReader(self,Window(check_document(document,asset=asset,revision=revision,query=query,description=description),query,description,base))

    async def _window_get(self,path,limit,answer=None):
        from .volume_windows import server_refusal
        try:return await self._get(path,limit,answer=answer)
        except OphioliteError as error:
            refused=server_refusal(error)
            if refused is not None:raise refused from None
            raise

    async def _window_json(self,path):
        from .volume_windows import DOCUMENT_BYTES
        try:return json.loads(await self._window_get(path,DOCUMENT_BYTES))
        except (ValueError,UnicodeError) as error:
            if isinstance(error,OphioliteError):raise
            raise VerificationFailed('The window document is not valid JSON.') from None

    async def _window_description(self,asset,revision,description):
        from .volume_windows import WindowDescription,describe_line,describe_volume,line_representation
        if description is not None:
            if not isinstance(description,WindowDescription) or (description.asset,description.revision)!=(asset,revision):raise Refused('description= is a window description of this exact revision.')
            return description
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        descriptor=await self._json(path+'?'+PROFILES[1:],256*1024)
        _core.verify_typed_descriptor(descriptor,self.project,asset,revision)
        found=describe_volume(asset,revision,descriptor)
        if found is not None:return found
        rep=line_representation(descriptor)
        raw=await self._artifact(path+'/representations/'+quote(rep['id'],safe=''),rep['bytes'])
        _core.verify_bytes(rep,raw)
        return describe_line(asset,revision,raw)

    async def read_slice(self,asset,revision,axis,label,*,volume=None) -> SeismicSlice:  # type: ignore[override]
        """Read one slice of a seismic volume at one exact version, checked; see Client.read_slice()."""
        # E16
        if axis not in ('inline','crossline','sample') or type(label) is not int:raise Refused('Choose an inline, crossline or sample slice by its whole number.')
        if volume is None:volume=await self.read_data(asset,revision)
        volume=self._volume(asset,revision,axis,label,volume)
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/slices/'+quote(axis,safe='')+'/'+str(label)
        return _core.slice_result(volume,await self._get(path,32*1024*1024),asset,revision,axis,label)

    async def export_slices(self,asset,revision,slices,destination) -> Bundle:  # type: ignore[override]
        """Export chosen slices of one exact version of a seismic volume into a new portable bundle; see Client.export_slices()."""
        # E16
        from .bundle import write_bundle
        chosen=self._slice_choice(slices)
        volume=await self.read_data(asset,revision)
        read=[await self.read_slice(asset,revision,axis,label,volume=volume) for axis,label in chosen]
        state={}
        volume.source_record,volume.sender=await self._provenance_parts(asset,revision,state)  # E122 s5b; E182 s2b
        _warn_source_records_omitted(state.get('omitted'))
        return await anyio.to_thread.run_sync(lambda:write_bundle(destination,[({'asset_id':asset,'revision':revision,'curves':[],'slices':[{'axis':a,'label':l} for a,l in chosen]},(volume,read))],
                                                                  source_records_omitted=state.get('omitted')))

    async def provenance(self,asset,revision) -> Provenance:  # type: ignore[override]
        """Where one exact version came from, as the server records it; see Client.provenance()."""
        # E122 s5b
        return _provenance_of(await self._json(_provenance_path(self.prefix,asset,revision),PROVENANCE_BYTES),asset,revision)

    async def _provenance_parts(self,asset,revision,state):
        """Same as Client._provenance_parts, awaited."""
        if state.get('omitted'):return None,None
        try:found=await self.provenance(asset,revision)
        except Unavailable as error:
            if not _no_provenance_route(error):raise
            state['omitted']=NO_SOURCE_RECORDS;return None,None
        return _parts_of(found)

    async def read_many(self,selections,**options) -> list[CurveSet]:  # type: ignore[override]
        """Read several exact versions' curves at the same time, one `read` each, answered in the order given.

        When one read fails, the others are cancelled and its error is raised; no partial result is returned.
        """
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
        captured=_client_header.stamp(await self._headers() if headers is None else headers,self._sender)
        captured.update(extra_headers or {'Content-Type':'application/json'})
        attempts=3 if operation!='share' and (retry or operation in planning.READ_OPERATIONS) else 1
        for attempt in range(attempts):
            if (self.url,self.project)!=(url,project):raise RecoveryUnavailable('The gateway or project changed during this operation.')
            try:
                async with self.http.stream('POST',url+path,content=raw,headers=captured,follow_redirects=False) as response:
                    _deprecation.note(_deprecation.of(self),'POST',url+path,response)
                    refusal=None if response.is_success else await policy.bounded(response)
                    if response.status_code in (429,503) and attempt+1<attempts and policy.retried(response,refusal):
                        await anyio.sleep(policy.delay(response));continue
                    policy.status(response,operation,refusal)
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>policy.MAX_RESPONSE:raise policy.too_large()
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
                 headers=_client_header.stamp({**headers,'Content-Type':'application/json'},self._sender),follow_redirects=False) as response:
                _deprecation.note(_deprecation.of(self),'POST',self.url+'/api/v1/application-access/status',response)
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

    def work_folder(self,path,**options) -> AsyncWorkFolder:  # type: ignore[override]
        """A private folder that keeps each request, so the work can be recovered after a restart; its calls are awaited."""
        return AsyncWorkFolder(self,path,**options)

    async def _listed(self,name,/,*args,**kwargs):
        """E142 s1: a paged read of Client gathered into a list in one worker (its HTTP stays on this loop)."""
        return await _complete(anyio.to_thread.run_sync(lambda:list(getattr(_ApplicationDriver(self),name)(*args,**kwargs)),abandon_on_cancel=False))

    async def surveys(self) -> list[dict[str, Any]]:  # type: ignore[override]
        """The project's surveys you may see, oldest first, as a list; see Client.surveys()."""
        # E142 s1
        return await self._listed('surveys')

    async def holder_pages(self,item=None,*,limit=None) -> list[dict[str, Any]]:  # type: ignore[override]
        """Every page of which member's application holds which version, as a list; see Client.holder_pages()."""
        # E171 s1
        return await self._listed('holder_pages',item,limit=limit)

    async def affected_pages(self,item,*,against='head',limit=None) -> list[dict[str, Any]]:  # type: ignore[override]
        """Every page of what rests on the versions of an item other than its newest, as a list; see Client.affected_pages()."""
        # E177 s1
        return await self._listed('affected_pages',item,against=against,limit=limit)

    async def survey_pages(self,survey_id,revision=None,*,view='revision',limit=None) -> list[SurveyPage]:  # type: ignore[override]
        """Every page of one survey revision, first page first, as a list; see Client.survey_pages()."""
        # E142 s1
        return await self._listed('survey_pages',survey_id,revision,view=view,limit=limit)

    async def survey_history(self,survey_id) -> list[dict[str, Any]]:  # type: ignore[override]
        """The survey's events you may read, newest first, as a list; see Client.survey_history()."""
        # E142 s1
        return await self._listed('survey_history',survey_id)

    async def find_all(self,organization,text=None,*,limit=50,**filters) -> list[SearchRow]:  # type: ignore[override]
        """Every row `find` answers, in the server's order, as a list; see Client.find_all()."""
        # adhoc-async-client-find
        return await self._listed('find_all',organization,text,limit=limit,**filters)

    async def _organization_post(self,body,headers):
        """adhoc-async-client-find: Client.find's one POST (access_history._post) on this loop: a bounded answer, and a
        refusal with the deployment's own sentence and code."""
        from . import application_transport as policy
        from .publish import json_bytes
        url=self.url+'/api/v1/organizations/search'
        try:
            async with self.http.stream('POST',url,content=json_bytes(body),headers=headers,follow_redirects=False) as response:
                _deprecation.note(_deprecation.of(self),'POST',url,response)
                if not response.is_success:
                    head=await policy.bounded(response)
                    if response.status_code==403:
                        meta=policy.envelope(response,head)
                        raise PermissionRefused(meta.get('message') or 'This credential cannot read this.',status=403,code=meta.get('code'),**policy.carried(meta))
                    policy.status(response,'search',head)
                content=bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content)>policy.MAX_RESPONSE:raise policy.too_large()
        except httpx.HTTPError:
            raise Unavailable('Cannot reach the service. Check its address and network connection.',code='unreachable') from None
        return policy.decode(bytes(content))

    async def sources(self) -> list[AsyncSource]:  # type: ignore[override]
        """The source selections you bound in this project (every profile); see Client.sources()."""
        # E50a
        return [AsyncSource(self,source.document) for source in await self._application('sources')]

    async def source(self,id) -> AsyncSource:  # type: ignore[override]
        """The selection with this stable id (SourceNotFound when you have none); see Client.source()."""
        # E50a
        return AsyncSource(self,(await self._application('source',id)).document)


class AsyncSource:
    """E50a: one source selection for the asynchronous client. describe() and read() run the synchronous, verified
    read in a worker (HTTP stays on this loop) and return the same SourceDescription / SourceSnapshot. A cancelled
    read finishes or fails as a whole before the cancellation is raised; no partial result is returned."""
    def __init__(self,client,document):
        self._client,self.document=client,document
        self.id,self.name,self.profile,self.state,self.mode=document['id'],document['name'],document['profile'],document['state'],document['mode']
        self.authority,self.key,self.revision=document['authority'],document['key'],document['reference']['revision']

    def __repr__(self):return 'AsyncSource(%r, %s, %s, revision %s)' % (self.name,self.profile,self.state,self.revision[:12])

    async def _run(self,name,expect_revision,**options):
        from .sources import Source
        def operation():return getattr(Source(_ApplicationDriver(self._client),self.document),name)(expect_revision,**options)
        return await _complete(anyio.to_thread.run_sync(operation,abandon_on_cancel=False))

    async def read(self,expect_revision=None,require_all_columns=False):return await self._run('read',expect_revision,require_all_columns=require_all_columns)

    async def describe(self,expect_revision=None):return await self._run('describe',expect_revision)


class _ApplicationDriver(Client):
    """Run shared application planning/files in a worker; HTTP stays on its loop."""
    def __init__(self,client):
        self.owner=client
        self.url,self.project,self.prefix=client.url,client.project,client.prefix
        self.credential,self.http,self._owns_http=client.credential,client.http,False
        self._sender=client._sender  # E182 s1: the owner's name on the requests this driver plans

    def _post_bytes(self,area,operation,raw,**options):
        # Acquire the credential in this worker, not a nested worker. A work-folder
        # transaction already supplies its locked immutable identity snapshot.
        if options.get('headers') is None:options['headers']=self._headers()
        return anyio.from_thread.run(partial(self.owner._post_bytes,area,operation,raw,**options))

    def _get(self,path,limit,**options):return anyio.from_thread.run(partial(self.owner._get,path,limit,**options))  # E54: ranged reads

    def _grant_status(self,headers):return anyio.from_thread.run(self.owner._grant_status,headers)

    def _organization_search(self,body):  # adhoc-async-client-find: the headers in this worker, the POST on the owner's loop
        from .access_history import _headers
        return anyio.from_thread.run(self.owner._organization_post,body,_headers(self.credential,self.url,None,self._sender))


class AsyncWorkFolder:
    if TYPE_CHECKING:  # E217 s0 (D2): the coroutines the last loop of this module attaches, named for a type checker; never
        # defined at run time. Each repeats its publish.WorkFolder method's parameters; WorkFolder states no returns, so
        # each return is its Client counterpart's (`input` is Client.run_input's), checked in tests/test_async_declarations.py.
        async def configure(self, asset=None, revision=None, *, curve, name, publication_profile='las-derived-curves/1', release_id=None,
                            asset_index=0, runners=None) -> Binding: ...
        async def start(self, binding, *, application_version, parameters, script=None) -> Run: ...
        async def input(self, run) -> tuple[bytes, ApplicationCurve]: ...
        async def publish(self, run, *, derived_curves=None, changes=None, new_version_of=None) -> Receipt: ...
        async def download(self, receipt) -> bytes: ...
        async def upload_las(self, source, *, name, attribution, audience, rights_confirmed, filename=None, well_notes='',
                             curve_declaration=None) -> UploadResult: ...
        async def recover(self, through=None) -> Binding | Run | Receipt | UploadResult | None: ...

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
              'upload_las','inspect_las','upload_info','members','result_preview','result_download','recover',
              'upload_data','served_limits','download_original',  # E54: files sent in parts, originals read by ranges
              'survey','create_survey','add_survey_members','remove_survey_members','replace_survey_member','relate_survey_members',
              'unrelate_survey_members','rename_survey','identify_survey','withdraw_survey',  # E142 s1
              'restate_survey','link_survey_members',  # E142 s2a
              'holders',  # E171 s1
              'affected',  # E177 s1
              'receipts',  # E184 s0a
              'find','find_log'):  # adhoc-async-client-find
    setattr(AsyncClient,_name,_async_application(_name))


# adhoc-async-client-find (D133 item 4): Client methods whose synchronous body would get an un-awaited answer from this
# client's transport (it reads the answer, or hands this client to a helper that does). Until E218 gives them
# asynchronous versions they refuse at once, before any request, and name Client. An inherited method that only returns
# its request (search, lineage, ...) is awaited as it is; tests/test_aio_parity.py keeps both lists exact.
_SYNC_ONLY=('access_history','access_teams','associations','audience','bindings','browse','change_coordinates','change_units',
           'create_entity','data','deliver','diff','entities','entity','exchange','export_access_history','export_corpus','export_file',
           'export_trajectories','extent','identify','import_bundle','import_storage','layouts','new_data_defaults','of_entity',
           'org_connections','outcome_claims','outcome_list','outcome_named','part_of','parts','procedure_again','procedure_bundle',
           'procedure_list','procedure_publish','procedure_run','procedure_sandbox_job','procedure_sandbox_run','procedure_version',
           'proposals','publish_derived','receipt_pages','result_groups','result_version','set_audience','set_new_data_defaults',
           'share_entity','source_run','start_sample','sync','template','templates','tool_again','tool_bundle','tool_declaration',
           'tool_list','tool_publish','tool_run','tool_sandbox_job','tool_sandbox_run','tool_version','transfer_codes_kept','try_result',
           'upload','upload_reads','well_imports','wells','withdraw')
_SYNC_ONLY_PROPERTIES=('chains','documents','figures','imports','public_repositories','table_kinds','upload_runs','well_names','well_sets')


def _sync_only(name):
    def refused(self,*args,**kwargs):
        raise TypeError(f'AsyncClient.{name} is not asynchronous yet; use Client.{name} (ophiolite.Client).')
    refused.__name__=refused.__qualname__=name
    refused.__doc__=f'Not asynchronous yet: it raises TypeError naming Client.{name}, before any request.'
    return refused


for _name in _SYNC_ONLY:
    setattr(AsyncClient,_name,_sync_only(_name))
for _name in _SYNC_ONLY_PROPERTIES:
    setattr(AsyncClient,_name,property(_sync_only(_name)))
for _name in ('configure','start','input','publish','download','upload_las','recover'):
    setattr(AsyncWorkFolder,_name,_async_work(_name))
