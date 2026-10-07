"""Bounded reads of exact scientific revisions. No implicit login or cache access."""
import gc
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import quote
import httpx
from . import _core
from .errors import (AuthenticationRequired, PermissionRefused, IntegrityConflict, CapacityExceeded, Refused, Busy,
                     Incompatible, Unavailable, VerificationFailed)

MAX_BYTES=32*1024*1024


from ._core import origin


from .auth import Credential
from .entities import EntityClient
from .navigation import Navigation


class CurveSet:
    def __init__(self,descriptors,curves,artifact,*,url='',project='',wire_descriptors=None,wire_curves=None,wire_curve_bytes=None):
        self.descriptors,self.curves,self.artifact=descriptors,curves,artifact
        self.url,self.project=url,project
        self._wire_descriptors,self._wire_curves=wire_descriptors,wire_curves
        self._wire_curve_bytes=wire_curve_bytes  # exact served bytes; their digest is in the descriptor

    @property
    def evidence(self):
        """SDK compatibility status, preserving absent older wire evidence."""
        return {asset.scientific.curve:_core.rules.interpretation(asset.model_dump(by_alias=True,exclude_unset=True)) for asset in self.descriptors}

    def to_numpy(self):
        from .scientific import to_numpy
        return to_numpy(self)

    def to_frame(self):
        from .scientific import to_frame
        return to_frame(self)

    def workspace_url(self):
        from .scientific import workspace_url
        return workspace_url(self)

    def _repr_html_(self):
        from .repr import curve_set_html
        return curve_set_html(self)

    def save(self,path,*,legacy_order=False):
        path=Path(path)
        try:path.mkdir(mode=0o700,parents=True,exist_ok=False)
        except FileExistsError:raise Refused('Output already exists. Choose a new folder.') from None
        def write(name,raw):
            fd=os.open(path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw)
        def encode(value):return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
        write('artifact.las',self.artifact)
        for index,(descriptor,view) in enumerate(zip(self.descriptors,self.curves)):
            suffix='' if len(self.curves)==1 else '-'+quote(view.curve,safe='')
            write('curve'+suffix+'.json',encode(self._wire_curves[index] if legacy_order and self._wire_curves is not None else view.model_dump(by_alias=True,exclude_unset=True)))
            # Single-curve output matches the old kit; every multi-curve descriptor
            # is retained, rather than silently keeping only the last one.
            write('descriptor'+suffix+'.json',encode(self._wire_descriptors[index] if legacy_order and self._wire_descriptors is not None else descriptor.model_dump(by_alias=True,exclude_unset=True)))


from .locations import LocationClient  # noqa: E402
from .sources import SourceClient  # noqa: E402


class Client(Navigation, EntityClient, LocationClient, SourceClient):  # E29: wells() and extent(); E50a: sources()
    def __init__(self,url,project,credential=None,http=None):
        self.url=origin(url)
        if not isinstance(project,str) or not project:raise Refused('Choose a project.')
        self.project,self.credential=project,credential
        self.prefix='/api/v1/projects/'+quote(project,safe='')+'/scientific-assets'
        self._owns_http=http is None
        self.http=http or httpx.Client(timeout=60,follow_redirects=False,trust_env=False)

    @classmethod
    def from_configuration(cls,path='configuration.json',*,credential=None,http=None):
        try:value=json.loads(Path(path).read_text())
        except (OSError,ValueError):raise Refused('Cannot read configuration. Download it again from Connect.') from None
        if not isinstance(value,dict) or value.get('schema') not in ('ophiolite.read-configuration/1','ophiolite.local-configuration/1'):
            raise Refused('Download a supported configuration from Connect.')
        if ('asset' in value)!=('revision' in value):raise Refused('An exact selection needs both asset and revision.')
        for key in ('asset','revision','curve'):
            if key in value and (not isinstance(value[key],str) or not value[key]):raise Refused('Invalid exact-read selection.')
        return cls(value.get('url'),value.get('project'),credential,http)

    def sync(self,checkpoint=None):
        """E28: a local copy of this project kept current from its event log (ophiolite.sync.Sync)."""
        from .sync import Sync
        return Sync(self,checkpoint=checkpoint)

    @property
    def upload_runs(self):
        """E55: upload a folder or a .zip with one report (ophiolite.upload_runs.UploadRuns)."""
        from .upload_runs import UploadRuns
        return UploadRuns(self)

    def upload(self,path_or_address,*,attribution,rights_confirmed,audience=(),well_notes='',declare=None,skip_decisions=False,link_wellbore=False,new=False,progress=None):
        """E85: add a file, a folder, a .zip or an https address in one upload and return its report
        (ophiolite.upload_runs.Report). `declare` {kind: {field: value}} answers what the files of that kind leave open;
        `link_wellbore` links each file to the one wellbore whose name its header names. An address is fetched by the
        gateway: no file bytes are sent from here."""
        return self.upload_runs.upload(path_or_address,attribution=attribution,rights_confirmed=rights_confirmed,audience=audience,well_notes=well_notes,
                                       declare=declare,skip_decisions=skip_decisions,associate_matches=link_wellbore,new=new,progress=progress)

    def well_imports(self):
        """E42a: import a copy of an approved well table as wells (ophiolite.well_imports.WellImports)."""
        from .well_imports import WellImports
        return WellImports(self)

    def exchange(self,work,**options):
        """E70a: check for updates, get latest and send to project from a work folder (ophiolite.exchange.Exchange)."""
        from .exchange import Exchange,ClientTransport
        return Exchange(ClientTransport(self),work,**options)

    def close(self):
        if self._owns_http:self.http.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _get(self,path,limit,*,ranged=None,answer=None):
        headers=self.credential.headers(self.url,self.project) if self.credential else {}
        if ranged is not None:headers={**headers,'Range':ranged}  # E54: one byte range of an original; 206 answers it
        categories={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
                    404:(Unavailable,'This exact revision is unavailable or not permitted.'),409:(IntegrityConflict,'Stored data failed an integrity check. Ask the deployment administrator.'),
                    413:(CapacityExceeded,'Representation exceeds the bounded size; partial reads are not supported.'),400:(Refused,'The request was refused. Check the selected input.'),
                    422:(Incompatible,'This scientific context is not supported.'),503:(Busy,'The service is busy or unavailable.'),429:(Busy,'The service is busy or unavailable.'),
                    416:(Refused,'This byte range is outside the file.')}
        for attempt in range(3):
            try:
                with self.http.stream('GET',self.url+path,headers=headers,follow_redirects=False) as response:
                    delay=0
                    if response.status_code in (429,503):
                        try:delay=float(response.headers.get('Retry-After','0'))
                        except ValueError:delay=0
                        if not math.isfinite(delay) or delay<0 or delay>60:delay=0
                        if attempt<2:
                            time.sleep(delay);continue
                    if response.status_code!=(200 if ranged is None else 206):
                        from . import application_transport as policy
                        meta=policy.envelope(response)  # E31: the server's code, remedy, docs and request id, read with a bound
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if kind is Busy:raise Busy(message,meta.get('remedy',''),status=response.status_code,retry_after=delay,code=meta.get('code'),**policy.carried(meta))
                        raise kind(message,meta.get('remedy',''),status=response.status_code,code=meta.get('code'),**policy.carried(meta))
                    if answer is not None:answer.update({k.lower():v for k,v in response.headers.items() if k.lower() in ('content-range','x-content-sha256')})
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>limit:raise CapacityExceeded('Scientific response exceeds its bounded size limit.')
                    return bytes(content)
            except httpx.HTTPError:
                raise Unavailable('Cannot reach the service. Check its address and network connection.',code='unreachable') from None
        raise Unavailable('The service remains unavailable.')

    def _json(self,path,limit):
        try:return json.loads(self._get(path,limit))
        except (ValueError,UnicodeError) as exc:
            # Domain errors subclass ValueError; preserve their recovery category.
            from .errors import OphioliteError
            if isinstance(exc,OphioliteError):raise
            raise VerificationFailed('Scientific response is not valid JSON.') from None

    def assets(self):
        cursor='';seen=set()
        while True:
            page=self._json(self.prefix+'?limit=100&cursor='+quote(cursor,safe=''),2_100_000)
            if not isinstance(page,dict) or not isinstance(page.get('items'),list):raise VerificationFailed('Invalid scientific catalogue response.')
            yield from page['items'];cursor=page.get('next_cursor')
            if cursor is None or cursor=='':return
            if not isinstance(cursor,str) or len(cursor)>2000 or cursor in seen:raise VerificationFailed('Invalid or repeated catalogue cursor.')
            seen.add(cursor)

    def _path(self,asset,revision,curve):
        if not all(isinstance(x,str) and x for x in (asset,revision,curve)):
            raise Refused('Choose an asset, exact revision and value curve.')
        return self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe=''),'?curve='+quote(curve,safe='')

    def describe(self,asset,revision,curve):
        path,query=self._path(asset,revision,curve)
        return _core.verify_descriptor(self._json(path+query,256*1024),self.project,asset,revision,curve)

    def read(self,asset,revision,curves,*,strict_interpretation=False):
        if not isinstance(curves,(list,tuple)) or not curves or len(set(curves))!=len(curves):
            raise Refused('Choose distinct value curves explicitly.')
        descriptors=[];views=[];artifact=None;wire_descriptors=[];wire_curves=[];wire_curve_bytes=[]
        for curve in curves:
            path,query=self._path(asset,revision,curve)
            data=self._json(path+query,256*1024)
            _core.verify_descriptor(data,self.project,asset,revision,curve)
            raw=_core.rules.artifact(data)
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=self._get(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
            wire_descriptors.append(data);wire_curves.append(json.loads(body));wire_curve_bytes.append(body)
        return CurveSet(descriptors,views,artifact,url=self.url,project=self.project,wire_descriptors=wire_descriptors,wire_curves=wire_curves,wire_curve_bytes=wire_curve_bytes)

    def read_data(self,asset,revision):
        """E11: read well tops, a trajectory or a regular-grid surface at an exact revision."""
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        data=self._json(path,256*1024)
        _core.verify_typed_descriptor(data,self.project,asset,revision)
        raw=_core.rules.artifact(data)
        normalized=next(r for r in data['representations'] if r['kind']=='normalized')
        # E16: a seismic volume is described, never downloaded here; read_slice reads its samples.
        artifact=None if data['scientific'].get('type')=='seismic-volume' else self._get(path+'/representations/'+quote(raw['id'],safe=''),raw['bytes'])
        body=self._get(path+'/representations/'+quote(normalized['id'],safe=''),normalized['bytes'])
        return _core.typed_result(data,body,artifact)

    def read_slice(self,asset,revision,axis,label,*,volume=None):
        """E16: one slice of a seismic volume at an exact revision. `axis` is 'inline', 'crossline'
        or 'sample'; `label` is the inline or crossline number from the trace headers, or the
        0-based sample number. Verified against the volume's description (read once and reusable
        through `volume=`); only the chunks holding the slice are read on the server."""
        volume=self._volume(asset,revision,axis,label,volume)
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/slices/'+quote(axis,safe='')+'/'+str(label)
        return _core.slice_result(volume,self._get(path,32*1024*1024),asset,revision,axis,label)

    def _volume(self,asset,revision,axis,label,volume):
        if axis not in ('inline','crossline','sample') or type(label) is not int:raise Refused('Choose an inline, crossline or sample slice by its whole number.')
        if volume is None:volume=self.read_data(asset,revision)
        if getattr(volume,'type',None)!='seismic-volume' or (volume.descriptor.asset_id,volume.descriptor.revision)!=(asset,revision):raise Refused('Slices come from a seismic volume at this exact revision.')
        return volume

    def export_slices(self,asset,revision,slices,destination):
        """E16: export chosen slices [(axis, label), ...] of one exact volume revision into a new
        portable bundle (2.3). The bundle carries the volume's description and each slice with its
        declared scope; the original volume is named by its digest and not included."""
        from .bundle import write_bundle
        chosen=self._slice_choice(slices)
        volume=self.read_data(asset,revision)
        read=[self.read_slice(asset,revision,axis,label,volume=volume) for axis,label in chosen]
        return write_bundle(destination,[({'asset_id':asset,'revision':revision,'curves':[],'slices':[{'axis':a,'label':l} for a,l in chosen]},(volume,read))])

    @staticmethod
    def _slice_choice(slices):
        if not isinstance(slices,(list,tuple)) or not slices or len(slices)>64:raise Refused('Choose between 1 and 64 slices.')
        chosen=[tuple(s) for s in slices]
        if len(set(chosen))!=len(chosen):raise Refused('Each slice is chosen once.')
        return chosen

    def read_many(self,selections,**options):
        return [self.read(asset,revision,curves,**options) for asset,revision,curves in selections]

    def export(self,selections,destination,*,groups=True,entities=True):
        """Export exact revisions [(asset, revision, [curves] or None)] into a new portable bundle.

        Every item is read through the ordinary exact-read path, so the server's current
        permissions apply to each representation; one refusal fails the whole export and
        nothing is published. The bundle becomes visible only after it checks as a reader
        would. Returns the opened Bundle."""
        from .bundle import write_bundle
        if not isinstance(selections,(list,tuple)) or not selections:raise Refused('Choose at least one exact revision to export.')
        items=[]
        for asset,revision,curves in selections:
            if not curves:  # E11: well tops, trajectories and grids have no curves (bundle 2)
                read=self.read_data(asset,revision)
                if read.type=='seismic-volume':raise Refused('A seismic volume is exported as chosen slices (export_slices); the complete volume is not exported.')
                items.append(({'asset_id':asset,'revision':revision,'curves':[]},read));continue
            items.append(({'asset_id':asset,'revision':revision,'curves':list(curves)},self.read(asset,revision,list(curves))))
        found,omitted=self._bundle_groups(items) if groups else (None,None)
        graph,left_out=self._bundle_graph(items) if entities else (None,'not requested')
        if left_out and left_out!='not requested':
            import warnings
            warnings.warn('Wells and wellbores were left out of this bundle: '+left_out+'.',UserWarning,stacklevel=2)
        return write_bundle(destination,items,groups=found,groups_omitted=omitted,graph=graph,entities_omitted=left_out)

    def _bundle_graph(self,items):
        """E20: the wells and wellbores (you may read) that exported revisions belong to, their wells one
        part-of hop up, and those associations with their evidence, with why none travel when they
        cannot (E22b: recorded in the bundle, never silent). (None, None) when there are none."""
        from .errors import Unavailable,PermissionRefused
        selected={(chosen['asset_id'],chosen['revision']) for chosen,_ in items}
        try:visible={e.entity_id:e for e in self.entities()}
        except PermissionRefused:return None,'this sign-in may not read wells and wellbores'
        except Unavailable as error:
            if getattr(error,'status',None)==404:return None,'this server has no wells and wellbores'
            raise
        included,edges={},[]
        for e in visible.values():
            for item in self.data(e):
                if (item['asset_id'],item['revision']) in selected:
                    included[e.entity_id]=e
                    edges.append({'predicate':'of-entity','subject':{'kind':'revision','asset_id':item['asset_id'],'revision':item['revision'],**({'row':item['row']} if item.get('row') else {})},  # E29: the row of a table of wells
                                  'object':{'kind':e.kind,'entity_id':e.entity_id},'evidence':item['association']['evidence']})
        for e in list(included.values()):
            link=e.document.get('part_of')
            if e.kind=='wellbore' and link and link['entity_id'] in visible:
                included[link['entity_id']]=visible[link['entity_id']]
                edges.append({'predicate':'part-of','subject':{'kind':'wellbore','entity_id':e.entity_id},'object':{'kind':'well','entity_id':link['entity_id']},
                              'evidence':None})  # the statement stays with the deployment; the link is what the bundle records
        if not included:return None,None
        entities=[{k:e.document[k] for k in ('entity_id','kind','name','identity')} for e in sorted(included.values(),key=lambda x:x.entity_id)]
        return {'entities':entities,'relationships':sorted(edges,key=lambda r:json.dumps(r,sort_keys=True))},None

    def _bundle_groups(self,items):
        """Result groups (as this account sees them now) that contain selected results, by bundle position."""
        from datetime import datetime,timezone
        selected=[(chosen['asset_id'],chosen['revision']) for chosen,_ in items]
        if not any(getattr(read,'descriptors',None) and read.descriptors[0].origin=='managed-derived' for _,read in items):return None,None
        from .errors import Unavailable,PermissionRefused
        try:groups=self.result_groups()
        except Unavailable as error:
            if getattr(error,'status',None)==404:return None,'This server does not offer result groups'
            raise
        except PermissionRefused:return None,'This credential may not list result groups'  # stated in the bundle, never silently empty
        observed=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ');out=[]
        for g in groups:
            members=[i for i,(asset,_) in enumerate(selected) if asset in {m.asset_id for m in g.members}]
            if not members:continue
            rec=g.recommended;recommended=None
            if rec and rec.asset_id and (rec.asset_id,rec.revision) in selected:
                recommended={'asset_position':selected.index((rec.asset_id,rec.revision)),'revision':rec.revision,'by':rec.by,'at':float(rec.at),'reason':rec.reason}
            out.append({'name':g.name,'observed_at':observed,'meaning':'observation-at-export','members':members,'recommended':recommended})
        return out or None,None

    def _headers(self):
        return self.credential.headers(self.url,self.project) if self.credential else {}

    def _post_bytes(self,area,operation,raw,*,extra_headers=None,headers=None,retry=False,expected_context=None,timeout=None):
        from . import publish as planning,application_transport as policy
        from .errors import RecoveryUnavailable
        url,project=self.url,self.project
        if expected_context is not None and (url,project)!=expected_context:raise RecoveryUnavailable('The gateway or project changed during this operation.')
        path=planning.operation_path(project,area,operation)
        if extra_headers and any(key.lower() not in ('content-type','x-ophiolite-upload') for key in extra_headers):raise Refused('Saved request headers cannot replace authorization.')
        captured=dict(self._headers() if headers is None else headers)
        captured.update(extra_headers or {'Content-Type':'application/json'})
        attempts=3 if operation!='share' and (retry or operation in planning.READ_OPERATIONS) else 1
        for attempt in range(attempts):
            if (self.url,self.project)!=(url,project):raise RecoveryUnavailable('The gateway or project changed during this operation.')
            try:
                with self.http.stream('POST',url+path,content=raw,headers=captured,follow_redirects=False,**({'timeout':timeout} if timeout else {})) as response:
                    refusal=None if response.is_success else policy.head_bytes(response)
                    if response.status_code in (429,503) and attempt+1<attempts and policy.retried(response,refusal):
                        time.sleep(policy.delay(response));continue
                    policy.status(response,operation,refusal)
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>policy.MAX_RESPONSE:raise policy.too_large()
                    return policy.decode(bytes(content))
            except httpx.HTTPError:
                if attempt+1<attempts:continue
                policy.disconnected(operation)

    def _post(self,area,operation,body,**options):
        from .publish import json_bytes
        if 'project_id' in body and body['project_id']!=self.project:raise Refused('The request belongs to another project.')
        return self._post_bytes(area,operation,json_bytes({'project_id':self.project,**body}),**options)

    def configure(self,asset=None,revision=None,*,curve,name,command_id=None,publication_profile='las-derived-curves/1',release_id=None,asset_index=0,runners=None):
        """Configure exact input. Without a WorkFolder this is not recoverable after restart."""
        import uuid
        from . import publish as planning
        from .models.api import Binding
        body=planning.configure_body(asset,revision,curve,name,command_id or uuid.uuid4().hex,publication_profile=publication_profile,release_id=release_id,asset_index=asset_index,runners=runners)
        return planning.verify_application_reply('configure',body,self._post('applications','configure',body),self.project,self)

    def start(self,binding,*,application_version,parameters,command_id=None):
        """Resolve a run. Without a WorkFolder this is not recoverable after restart."""
        import uuid
        from . import publish as planning
        body=planning.start_body(binding,command_id or uuid.uuid4().hex,application_version,parameters)
        return planning.verify_application_reply('start',body,self._post('applications','start',body),self.project,self)

    def run_input(self,run):
        from . import publish as planning
        from .models.generated import ApplicationCurve
        result=self._post('applications','original',{'id':run.id})
        if result.get('source')!=run.input_reference.model_dump():raise VerificationFailed('The run input refers to another source.')
        original=planning.decode_payload(result,sha256=run.input_sha256)
        value=self._post('applications','read',{'id':run.id})
        view=planning.parse(ApplicationCurve,value);_core.rules.curve(value)
        if view.source_sha256!=run.input_sha256 or view.source.model_dump()!=run.input_reference.model_dump() or view.curve!=run.binding.curve:
            raise VerificationFailed('The run input refers to another source or selected curve.')
        run._view_wire=value
        run._original,run._view=original,view
        run._original_reference={k:v for k,v in result.items() if k!='payload_base64'}
        return original,view

    def publish(self,run,*,derived_curves=None,changes=None,new_version_of=None):
        """Publish reviewed values. Without a WorkFolder this is not recoverable after restart.

        ``new_version_of`` (a receipt or exact result you author, or one your project lets you add versions
        to, E70c) adds the values as the next version of that result; its revision is the expected parent."""
        from . import publish as planning
        if run._original is None or run._view is None:raise Refused('Read the exact run input before validating and publishing values.')
        body=planning.publication_body(run,run._original,run._view,derived_curves=derived_curves,changes=changes,new_version_of=new_version_of)
        published=planning.verify_application_reply('publish',body,self._post('applications','publish',body),self.project,self)
        if published.input_reference!=run.input_reference or published.input_sha256!=run.input_sha256:raise VerificationFailed('Publication changed the resolved scientific input.')
        return published.receipt

    def download(self,receipt):
        from . import publish as planning
        result=self._post('applications','download',{'id':receipt.publication_id})
        return planning.decode_payload(result,sha256=receipt.manifest.sha256,length=receipt.manifest.bytes)

    def results(self):
        from . import publish as planning
        value=self._post('applications','result-list',{})
        if not isinstance(value.get('results'),list):raise VerificationFailed('Invalid result catalogue response.')
        return [planning.parse_result(item) for item in value['results']]

    def ai_use(self,asset):
        """Who may use this item for AI (as its owner) or your own permission (as a reader)."""
        return self._post('ai-use','get',{'asset_id':asset})

    def grant_ai_use(self,asset,grants,*,expected_generation,command_id=None):
        """Owner only: {person: ['embedding'|'training'|'evaluation', ...]} for people who can read the item."""
        import uuid
        return self._post('ai-use','grant',{'asset_id':asset,'grants':grants,'expected_generation':expected_generation,'command_id':command_id or uuid.uuid4().hex})

    def search(self,text,*,method=None,limit=20):
        """Rank what you may read by its description ('words', or 'embedding' with the deployment's local model)."""
        return self._post('search','query',{'text':text,'limit':limit,**({'method':method} if method else {})})

    def export_corpus(self,selections,destination,*,purpose,seed=0,fractions=(0.8,0.1,0.1),groups=None):
        """An AI corpus of exact curves the server authorized for `purpose`; see ophiolite.corpus."""
        from .corpus import export_corpus
        return export_corpus(self,selections,destination,purpose=purpose,seed=seed,fractions=fractions,groups=groups)

    def result_groups(self):
        """Project result groups you can see, with only the members and recommendation you may open."""
        from . import publish as planning
        from .models.api import ResultGroup
        return [planning.parse(ResultGroup,g) for g in self._post('result-groups','list',{})['groups']]

    def diff(self,a,b):
        """Changes between two exact result versions: parameters, input and (when comparable) samples."""
        from . import publish as planning
        from .models.api import ResultDiff
        pick=lambda x:{k:v for k,v in planning.selection(x).items() if k in ('asset_id','revision')} if not isinstance(x,(tuple,list)) else {'asset_id':x[0],'revision':x[1]}
        return planning.parse(ResultDiff,self._post('result-groups','diff',{'a':pick(a),'b':pick(b)}))

    def history(self,asset):
        """Every version of a result you can read, oldest first."""
        from . import publish as planning
        from .models.api import History
        target=planning.selection(asset)
        if target.get('authority')=='ophiolite:uploaded':  # H4 (E32 F4): the server would answer with a misleading refusal
            raise Refused('history lists the versions of results and derived publications; the versions of an uploaded original are not listed. '
                          'Read the exact revision you were given, or ask its uploader.')
        return planning.parse(History,self._post('applications','result-history',{'asset_id':target['asset_id']}))

    def _sharing_target(self,asset):
        """H5b: one classification for grants and share. A derived item (a catalogue entry or a descriptor carries
        `ophiolite:derived`) that is not an application result is a derived publication when publications/info names
        the same asset; its recipients are set on its current version."""
        from . import publish as planning
        asset=planning.selection(asset)
        if asset['authority']=='ophiolite:uploaded':return asset,self._post('las-uploads','info',{'asset_id':asset['asset_id']})
        if asset['authority']=='ophiolite:publication':return asset,self._post('publications','info',{'asset_id':asset['asset_id']})  # E31
        results=self._post('applications','result-list',{})
        items=results.get('results') if isinstance(results,dict) else None
        if not isinstance(items,list) or any(i.get('asset_id')==asset['asset_id'] for i in items if isinstance(i,dict)):return asset,results
        try:info=self._post('publications','info',{'asset_id':asset['asset_id']})
        except (PermissionRefused,Unavailable):return asset,results  # neither: the result refusal below explains it
        if not isinstance(info,dict) or info.get('asset_id')!=asset['asset_id']:raise VerificationFailed('Sharing returned a different publication.')
        if info.get('revision')!=asset['revision']:raise Refused('Recipients are set on the publication as a whole and share every version; select its current version to review them.')
        return {**asset,'authority':'ophiolite:publication'},info

    def grants(self,asset):
        from . import publish as planning
        asset,result=self._sharing_target(asset)
        return planning.grants(asset,result)

    def share(self,asset,*,read,expected_generation,reuse=None,command_id=None,project=None):
        """Replace recipients, conditionally.

        Recipients belong to the result or derived publication as a whole: sharing
        shares every version of it, earlier and later; an uploaded original has one.
        Pass ``expected_generation`` from the ``client.grants(asset)`` snapshot you
        reviewed. The request carries a command id; after an unknown outcome it is
        replayed once, which returns the applied result or refuses with
        IntegrityConflict if anyone changed the recipients meanwhile (a revocation
        is never undone). Unconditional replacement ended with the E7 transition
        release; servers refuse it (428).

        ``project=True`` also shares a derived publication with everyone in the
        project, including people who join later; ``False`` withdraws that.
        ``None`` (the default) leaves it as it is. Either explicit value needs a
        server that reports it, is refused before anything is sent otherwise, and
        is verified in the answer."""
        import uuid
        from . import publish as planning
        from .errors import ShareOutcomeUnknown
        from .models.api import UploadResult
        reuse=[] if reuse is None else reuse
        planning.validate_recipients(read,reuse)
        if type(expected_generation) is not int or expected_generation<0:raise Refused('expected_generation must be a non-negative integer from client.grants(asset).')
        if command_id is not None and (not isinstance(command_id,str) or not 0<len(command_id)<=64):raise Refused('command_id must be 1-64 characters.')
        if project is not None and type(project) is not bool:raise Refused('project must be True, False or None.')
        asset,_=self._sharing_target(asset)  # H5b: the same target as grants; validated input first, nothing sent before
        uploaded=asset['authority']=='ophiolite:uploaded';publication=asset['authority']=='ophiolite:publication'
        body={'asset_id' if uploaded or publication else 'id':asset['asset_id'],'audience':read,'reuse_audience':reuse}
        area='las-uploads' if uploaded else 'publications' if publication else 'applications'
        # Never infer support: an older server would apply the request unconditionally.
        snapshot=self.grants(asset)
        if snapshot.generation is None:raise Refused('This server does not support conditional sharing.')
        if project is not None:  # E78: only a derived publication can be shared with the whole project; never sent unverified
            if not publication:raise Refused('Only a derived publication can be shared with everyone in the project; share this by name.')
            if snapshot.project is None:raise Refused('This server does not support sharing with everyone in the project.')
            body['project_audience']='read' if project else 'none'
        body.update(expected_generation=expected_generation,command_id=command_id or uuid.uuid4().hex)
        try:result=self._post(area,'share',body)
        except ShareOutcomeUnknown:result=self._post(area,'share',body)  # identical replay: idempotent or refused
        if publication:  # E31: a derived publication answers its sharing view; its grants are the result
            # H5b: recipients belong to the publication as a whole; a version appended meanwhile is the same publication
            parsed=planning.grants({**asset,'revision':result.get('revision')},{k:v for k,v in result.items() if k!='sharing_contract'})
            if parsed.asset_id!=asset['asset_id']:raise VerificationFailed('Sharing returned a different publication.')
            if project is not None and parsed.project is not project:raise VerificationFailed('Sharing returned a different project audience.')
            return parsed
        parsed=planning.parse(UploadResult,result) if uploaded else planning.parse_result(result)
        # Recipients belong to a result as a whole (every version, E8); an upload has one revision.
        if parsed.asset_id!=asset['asset_id'] or uploaded and parsed.revision!=asset['revision']:raise VerificationFailed('Sharing returned a different exact asset.')
        return parsed

    def bindings(self):
        from . import publish as planning
        from .models.api import Binding
        data=self._post('applications','list',{})
        if not isinstance(data.get('bindings'),list):raise VerificationFailed('Invalid application binding list.')
        return [planning.parse(Binding,item) for item in data['bindings']]

    def options(self):return self._post('applications','options',{})

    def inspect(self,asset=None,revision=None,*,curve='',name='',release_id=None,asset_index=0):
        body={'curve':curve,'name':name}
        if release_id is not None:body.update(release_id=release_id,asset_index=asset_index)
        else:body.update(asset_id=asset,asset_revision=revision)
        return self._post('applications','inspect',body)


    def _grant_status(self,headers):
        from .auth import request
        return request(self.url+'/api/v1/application-access/status',{'id':headers['X-Ophiolite-Application-Grant']},headers,http=self.http)

    def work_folder(self,path,**options):
        from .publish import WorkFolder
        return WorkFolder(self,path,**options)

    def recover(self,path,through=None):
        from .errors import RecoveryUnavailable
        path=Path(path)
        if not path.is_dir() or not (path/'owner.json').is_file():raise RecoveryUnavailable('Recovery requires the original private SDK work folder.')
        return self.work_folder(path).recover(through)

    def upload_las(self,source,*,name,attribution,audience,rights_confirmed,filename=None,well_notes='',command_id=None):
        """Upload original bytes. Without a WorkFolder this is not recoverable after restart; with the same
        `command_id`, a file sent in parts continues where it stopped (E54)."""
        import uuid
        from . import publish as planning
        filename=filename or (Path(source).name if not isinstance(source,bytes) else 'input.las')
        body,extra=planning.upload_metadata(self.project,command_id or uuid.uuid4().hex,filename=filename,name=name,attribution=attribution,audience=audience,rights_confirmed=rights_confirmed,well_notes=well_notes)
        return self._send(source,body,extra)

    def upload_data(self,source,*,profile,name,attribution,audience,rights_confirmed,declared=None,filename=None,well_log=None,well_notes='',command_id=None,origin=None,
                    append_to=None,expected_parent=None):
        """E11/E18: upload an original of any supported type with the context you declare (units, CRS,
        meanings; nothing is inferred). Starts private. A repeated command id returns the same asset.
        E53: `append_to` (your uploaded wavelet, model or section) with `expected_parent` (its current revision)
        adds the file as that result's next version; its audience stays the result's."""
        import uuid
        from . import publish as planning
        filename=filename or (Path(source).name if not isinstance(source,bytes) else 'upload')
        body,extra=planning.upload_metadata(self.project,command_id or uuid.uuid4().hex,filename=filename,name=name,attribution=attribution,audience=audience,
                                            rights_confirmed=rights_confirmed,well_notes=well_notes,profile=profile,declared=declared,well_log=well_log,origin=origin,
                                            append_to=append_to,expected_parent=expected_parent)
        return self._send(source,body,extra)

    def served_limits(self):
        """E54: this deployment's limits as its capabilities state them (`upload_bytes`, `file_bytes`, ...), read once."""
        if getattr(self,'_served_limits',None) is None:
            value=self._post('capabilities','describe',{},retry=True).get('limits')
            if not isinstance(value,dict) or not all(isinstance(value.get(k),int) for k in ('upload_bytes','file_bytes')):
                raise VerificationFailed('The deployment did not state its upload limits.')
            self._served_limits=value
        return self._served_limits

    def _send(self,source,body,extra):
        """E54: a file within the request limit goes in one request, as before; a larger one in parts, read from the
        path one part at a time (bytes in memory are sliced). Either way the revision must be the file's digest."""
        import hashlib
        from . import publish as planning
        from .models.api import UploadResult
        size=len(source) if isinstance(source,(bytes,bytearray)) else Path(source).stat().st_size
        if size<=planning.SINGLE or size<=self.served_limits()['upload_bytes']:
            raw=planning.upload_bytes(source);digest=hashlib.sha256(raw).hexdigest()
            result=planning.parse(UploadResult,self._post_bytes('las-uploads','upload',raw,extra_headers=extra))
        else:
            file=planning.FileSource(source);digest=file.sha256()
            result=planning.parse(UploadResult,self._upload_parts(file,digest,body))
        if result.revision!=digest:raise VerificationFailed('The uploaded original has a different checksum revision.')
        return result

    def _upload_parts(self,file,digest,body):
        """begin (the same command continues), the parts not yet received, finish, the check (polled), publish."""
        begin={'command_id':body['command_id'],'filename':body['filename'],'profile':body.get('profile','las2/1'),'declared':body.get('declared',{}),
               'bytes':file.size,'sha256':digest,**{k:body[k] for k in ('append_to','expected_parent') if k in body}}
        view=self._transfer_parts(file,self._post('las-uploads','begin',begin,retry=True))
        if view['state'] not in ('checked','published'):raise session_refusal(view)
        fields={k:body[k] for k in ('name','attribution','audience','rights_confirmed','well_notes','well_log') if k in body}
        return self._post('las-uploads','publish',{'upload_id':view['upload_id'],**fields},retry=True)

    def _transfer_parts(self,file,view):
        """The parts a begun session has not received, finish, and its check (polled); the session's last state.
        E55: a folder upload's large file is begun by the run and saved by it, so only this middle is shared."""
        from . import publish as planning
        ref={'upload_id':view['upload_id']}
        if view['state']=='open':
            have={p['index'] for p in view['received']}
            for index in range(view['parts']):
                if index in have:continue
                raw=file.read(index*view['part_bytes'],view['part_bytes'])
                for attempt in (0,1):  # a part damaged on the way is sent once more
                    try:self._post_bytes('las-uploads','part',raw,extra_headers=planning.part_header(self.project,view['upload_id'],index,raw),retry=True);break
                    except Refused as error:
                        if error.code!='part-corrupt' or attempt:raise
                del raw;gc.collect(1)  # httpx keeps a response in a reference cycle with its request (and so the part) until collected
            view=self._post('las-uploads','finish',ref,retry=True)
        wait=0.2
        while view['state']=='finishing':
            time.sleep(wait);wait=min(wait*2,5.0)
            view=self._post('las-uploads','state',ref,retry=True)
        return view

    def download_original(self,asset,revision,destination,*,part_bytes=8*1024*1024):
        """E54: save the exact original of a revision to `destination`, read by ranges and verified against the
        whole digest the deployment states; nothing is left at `destination` unless every byte matched."""
        import hashlib,uuid
        destination=Path(destination)
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/representations/artifact'
        partial=destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex[:12]+'.partial')
        whole,expected,at,size=hashlib.sha256(),None,0,None
        try:
            with partial.open('xb') as out:
                while size is None or at<size:
                    answer={}
                    raw=self._get(path,part_bytes,ranged='bytes=%d-%d'%(at,at+part_bytes-1),answer=answer)
                    first,total=_content_range(answer.get('content-range'))
                    stated=answer.get('x-content-sha256')
                    if first!=at or (size is not None and total!=size) or (expected is not None and stated!=expected) or not raw:
                        raise VerificationFailed('The deployment answered another part of the file.')
                    size,expected=total,stated
                    out.write(raw);whole.update(raw);at+=len(raw)
                out.flush();os.fsync(out.fileno())
            if whole.hexdigest()!=expected:raise IntegrityConflict('The downloaded original does not match the file the deployment holds; nothing was saved.')
            os.replace(partial,destination)
        except BaseException:
            partial.unlink(missing_ok=True);raise
        return destination

    def publish_derived(self,written,*,name,from_,method,command_id,of_entity=None,new_version_of=None,expected_parent=None):
        """E30b: publish a file you derived (a `WrittenOriginal` from ophiolite.writers) from exact revisions you
        may reuse, with the method you declare. `command_id` is required: a network retry with the same id is
        safe (the same receipt comes back); a fresh id on retry can create a second asset. Use
        WorkFolder.publish_derived for automatic recovery (it saves a stable command id and the file's digest
        before sending). `from_` names 1-32 parents (objects with asset_id and revision, or (asset_id, revision));
        `new_version_of`/`expected_parent` add a version to an earlier publication of the same lineage: your own, or
        (E70c) a colleague's when the project names you both; its author stays the author."""
        from . import publish as planning
        from .models.api import PublicationReceipt
        body,extra=planning.derive_request(self.project,written,name=name,from_=from_,method=method,command_id=command_id,of_entity=of_entity,
                                           new_version_of=new_version_of,expected_parent=expected_parent)
        return planning.verify_derived(body,planning.parse(PublicationReceipt,self._post_bytes('publications','derive',written.bytes,extra_headers=extra,retry=True)))

    def import_bundle(self,bundle,*,audience,attribution,rights_confirmed,well_logs=None):
        """E18: upload every original a portable bundle carries as your own new, private upload, with
        the context the bundle declares and its origin recorded as provenance (not authority). History,
        groups, grants and lineage stay behind. Safe to repeat: each asset's upload uses a stable
        command, so a retry after a lost answer returns the same destination asset."""
        from .bundle import import_plan
        from .errors import ImportIncomplete,ValidationFailed
        if rights_confirmed is not True:raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience; holding a bundle grants no rights.'])
        plan=import_plan(bundle,well_logs or {})
        results=[]
        for position,step in enumerate(plan):
            if step['state']!='ready':results.append(step);continue
            try:
                done=self.upload_data(step['original'],profile=step['profile'],name=step['name'],attribution=attribution,audience=list(audience),
                                      rights_confirmed=rights_confirmed,declared=step['declared'] or None,filename=step['filename'],well_log=step['well_log'],
                                      command_id=step['command_id'],origin=step['origin'])
            except Exception as error:
                results.append({**_public(step),'state':'failed','reason':str(error)[:300]})
                results+=[{**_public(s),'state':'not attempted' if s['state']=='ready' else s['state']} for s in plan[position+1:]]
                raise ImportIncomplete('The import stopped; repeat it to continue (finished assets are not duplicated).',details={'assets':results}) from error
            results.append({**_public(step),'state':'imported','destination':{'asset_id':done.asset_id,'revision':done.revision}})
        return [_public(r) if 'original' in r else r for r in results]

    def inspect_las(self,source):
        import base64
        from . import publish as planning
        raw=planning.upload_bytes(source)
        header=base64.b64encode(planning.json_bytes({'project_id':self.project})).decode()
        return self._post_bytes('las-uploads','inspect',raw,extra_headers={'Content-Type':'application/octet-stream','X-Ophiolite-Upload':header})

    def upload_info(self,asset):
        from . import publish as planning
        from .models.api import UploadResult
        chosen=planning.selection(asset)
        result=planning.parse(UploadResult,self._post('las-uploads','info',{'asset_id':chosen['asset_id']}))
        if result.asset_id!=chosen['asset_id'] or result.revision!=chosen['revision']:raise VerificationFailed('The upload response refers to a different exact asset.')
        return result

    def members(self):return self._post('las-uploads','members',{})

    def result_preview(self,asset):
        from . import publish as planning
        from .models.api import ResultPreview,RestrictedResultPreview
        chosen=planning.selection(asset)
        data=self._post('applications','result-preview',{'id':chosen['asset_id']})
        model=RestrictedResultPreview if 'input' in data and data['input'] is None else ResultPreview
        result=planning.parse(model,data)
        if result.asset_id!=chosen['asset_id'] or result.revision!=chosen['revision']:raise VerificationFailed('The preview refers to a different exact result.')
        return result

    def result_download(self,asset):
        from . import publish as planning
        from .models.api import RestrictedRun,Receipt,RestrictedReceipt
        chosen=planning.selection(asset)
        data=self._post('applications','result-download',{'id':chosen['asset_id']})
        run=planning.parse_run(data.get('run',{}),self)
        receipt=planning.parse(RestrictedReceipt if isinstance(run,RestrictedRun) else Receipt,{k:v for k,v in data.items() if k not in ('run','payload_base64')})
        if receipt.asset!= {key:chosen[key] for key in ('asset_id','revision','authority')}:raise VerificationFailed('The download refers to a different exact result.')
        raw=planning.decode_payload(data,sha256=receipt.manifest.sha256,length=receipt.manifest.bytes)
        return raw,receipt,run


def _public(step):
    return {k:v for k,v in step.items() if k not in ('original','declared','profile','filename','well_log','command_id','name')}


def _content_range(value):
    """(first byte, total) of a `Content-Range: bytes a-b/N` answer."""
    import re
    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',value or '')
    if match is None:raise VerificationFailed('The deployment did not say which bytes it sent.')
    return int(match.group(1)),int(match.group(3))


def session_refusal(view):
    """E54: the error for a file sent in parts that ended without being saved, with the deployment's sentence."""
    reason=view.get('reason') or {}
    code=reason.get('code') if isinstance(reason.get('code'),str) else 'unknown-upload'
    message=reason.get('message') if isinstance(reason.get('message'),str) else 'This upload is no longer known to this deployment. Start it again.'
    kind={'not-a-volume':Refused,'file-mismatch':IntegrityConflict,'access-lost':PermissionRefused}.get(code,Unavailable)
    return kind(message,status=None,code=code)
