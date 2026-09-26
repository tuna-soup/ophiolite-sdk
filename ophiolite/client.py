"""Bounded reads of exact scientific revisions. No implicit login or cache access."""
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


class CurveSet:
    def __init__(self,descriptors,curves,artifact,*,url='',project=''):
        self.descriptors,self.curves,self.artifact=descriptors,curves,artifact
        self.url,self.project=url,project

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

    def save(self,path):
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
            write('curve'+suffix+'.json',encode(view.model_dump(by_alias=True,exclude_unset=True)))
            # Single-curve output matches the old kit; every multi-curve descriptor
            # is retained, rather than silently keeping only the last one.
            write('descriptor'+suffix+'.json',encode(descriptor.model_dump(by_alias=True,exclude_unset=True)))


class Client:
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

    def close(self):
        if self._owns_http:self.http.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _get(self,path,limit):
        headers=self.credential.headers(self.url,self.project) if self.credential else {}
        categories={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
                    404:(Unavailable,'This exact revision is unavailable or not permitted.'),409:(IntegrityConflict,'Stored data failed an integrity check. Ask the deployment administrator.'),
                    413:(CapacityExceeded,'Representation exceeds the bounded size; partial reads are not supported.'),400:(Refused,'The request was refused. Check the selected input.'),
                    422:(Incompatible,'This scientific context is not supported.'),503:(Busy,'The service is busy or unavailable.'),429:(Busy,'The service is busy or unavailable.')}
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
                    if response.status_code!=200:
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if kind is Busy:raise Busy(message,status=response.status_code,retry_after=delay)
                        raise kind(message,status=response.status_code)
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
        descriptors=[];views=[];artifact=None
        for curve in curves:
            descriptor=self.describe(asset,revision,curve);data=descriptor.model_dump(by_alias=True,exclude_unset=True)
            path,query=self._path(asset,revision,curve)
            raw=next(r for r in data['representations'] if r['kind']!='normalized')
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=self._get(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
        return CurveSet(descriptors,views,artifact,url=self.url,project=self.project)

    def read_many(self,selections,**options):
        return [self.read(asset,revision,curves,**options) for asset,revision,curves in selections]

    def _headers(self):
        return self.credential.headers(self.url,self.project) if self.credential else {}

    def _post_bytes(self,area,operation,raw,*,extra_headers=None,headers=None,retry=False,expected_context=None):
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
                with self.http.stream('POST',url+path,content=raw,headers=captured,follow_redirects=False) as response:
                    if response.status_code in (429,503) and attempt+1<attempts:
                        time.sleep(policy.delay(response));continue
                    policy.status(response,operation)
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>policy.MAX_RESPONSE:raise CapacityExceeded('Application response exceeds its supported size.')
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
        run._original,run._view=original,view
        run._original_reference={k:v for k,v in result.items() if k!='payload_base64'}
        return original,view

    def publish(self,run,*,derived_curves=None,changes=None):
        """Publish reviewed values. Without a WorkFolder this is not recoverable after restart."""
        from . import publish as planning
        if run._original is None or run._view is None:raise Refused('Read the exact run input before validating and publishing values.')
        body=planning.publication_body(run,run._original,run._view,derived_curves=derived_curves,changes=changes)
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

    def grants(self,asset):
        from . import publish as planning
        asset=planning.selection(asset)
        result=(self._post('las-uploads','info',{'asset_id':asset['asset_id']}) if asset['authority']=='ophiolite:uploaded'
                else self._post('applications','result-list',{}))
        return planning.grants(asset,result)

    def share(self,asset,*,read,reuse=None):
        """Replace recipients once. Ambiguous outcomes must be inspected, never replayed automatically."""
        from . import publish as planning
        from .models.api import UploadResult
        reuse=[] if reuse is None else reuse
        planning.validate_recipients(read,reuse);asset=planning.selection(asset)
        uploaded=asset['authority']=='ophiolite:uploaded'
        body={'asset_id' if uploaded else 'id':asset['asset_id'],'audience':read,'reuse_audience':reuse}
        result=self._post('las-uploads' if uploaded else 'applications','share',body)
        parsed=planning.parse(UploadResult,result) if uploaded else planning.parse_result(result)
        if parsed.asset_id!=asset['asset_id'] or parsed.revision!=asset['revision']:raise VerificationFailed('Sharing returned a different exact asset.')
        return parsed

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
        """Upload original bytes. Without a WorkFolder this is not recoverable after restart."""
        import uuid
        from . import publish as planning
        from .models.api import UploadResult
        raw=planning.upload_bytes(source)
        filename=filename or (Path(source).name if not isinstance(source,bytes) else 'input.las')
        _,extra=planning.upload_metadata(self.project,command_id or uuid.uuid4().hex,filename=filename,name=name,attribution=attribution,audience=audience,rights_confirmed=rights_confirmed,well_notes=well_notes)
        result=planning.parse(UploadResult,self._post_bytes('las-uploads','upload',raw,extra_headers=extra))
        import hashlib
        if result.revision!=hashlib.sha256(raw).hexdigest():raise VerificationFailed('The uploaded original has a different checksum revision.')
        return result

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
