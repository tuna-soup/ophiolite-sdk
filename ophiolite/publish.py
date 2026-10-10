"""Local publication checks and durable application work (preview)."""
import json
import math
import re
from .errors import ValidationFailed
from .las_header import curves as source_curves, null_marker as source_null_marker

MAX_REQUEST_BYTES=2_100_000


def _number(value,marker):
    try:
        return value is None or (isinstance(value,(int,float)) and not isinstance(value,bool)
                                and math.isfinite(value) and value!=marker)
    except OverflowError:return False


def validate_derived_curves(curves, *, source, sample_count):
    """Validate complete appended curves against the full original LAS inventory.

    Raw duplicate source mnemonics are a deliberate SDK refusal; server readers
    may rename duplicates. No unit inference, resampling or value coercion occurs.
    """
    from .windows import refuse_window  # E100a: blocks are not samples
    refuse_window(curves,*(curves if isinstance(curves,list) else ()),*(c.get('values') for c in curves if isinstance(c,dict)) if isinstance(curves,list) else ())
    inventory=source_curves(source);marker=source_null_marker(source);violations=[]
    names=[curve.mnemonic.upper() for curve in inventory]
    if len(set(names))!=len(names):violations.append('Source curve names repeat, including case variants.')
    if not isinstance(curves,list) or not 1<=len(curves)<=8:
        violations.append('Supply between one and eight derived curves.')
    if isinstance(curves,list):
        if len(inventory)+len(curves)>64:violations.append('Source and derived curves together exceed 64.')
        occupied=set(names)
        for index,curve in enumerate(curves):
            prefix=f'Derived curve {index+1}: '
            if not isinstance(curve,dict) or set(curve)!={'mnemonic','unit','description','values'}:
                violations.append(prefix+'supply exactly mnemonic, unit, description and values.')
                continue
            name=curve['mnemonic']
            if not isinstance(name,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,15}',name):
                violations.append(prefix+'use an uppercase curve name of at most 16 letters, digits or underscores.')
            if isinstance(name,str):
                if name.upper() in occupied:violations.append(prefix+'name collides with a source or derived curve.')
                occupied.add(name.upper())
            unit=curve['unit']
            if not isinstance(unit,str) or not re.fullmatch(r'[A-Za-z0-9_/*()^\-]{1,32}',unit):
                violations.append(prefix+'supply a unit label without spaces, at most 32 supported characters.')
            description=curve['description']
            if not isinstance(description,str) or not 1<=len(description)<=160 or any(not 32<=ord(c)<=126 or c in ':~' for c in description):
                violations.append(prefix+'description must be printable ASCII, at most 160 characters, without colon or tilde.')
            values=curve['values']
            if not isinstance(values,list) or len(values)!=sample_count:
                violations.append(prefix+'supply exactly one value for each source sample.')
            if isinstance(values,list) and any(not _number(value,marker) for value in values):
                violations.append(prefix+'values must be finite numbers or null, excluding booleans and the missing-value marker.')
    try:
        size=len(json.dumps(curves,allow_nan=False,separators=(',',':')).encode())
        if size>MAX_REQUEST_BYTES:violations.append('Derived curves exceed the bounded request size.')
    except (TypeError,ValueError,OverflowError):
        violations.append('Derived curves must have a finite JSON representation.')
    if type(sample_count) is not int or sample_count<=0:violations.append('Source sample count must be a positive integer.')
    if violations:raise ValidationFailed(violations)
    return curves


def validate_changes(changes, *, values, null_marker):
    """Validate a bounded changed sample set; preserve axis, units and null meaning."""
    violations=[];seen=set();different=False
    if not isinstance(changes,list) or not 1<=len(changes)<=1000:
        violations.append('Supply between one and 1,000 sample changes.')
    if isinstance(changes,list):
        for change in changes:
            if not isinstance(change,dict) or set(change)!={'index','value'}:
                violations.append('Each change must contain exactly index and value.');continue
            index,value=change['index'],change['value']
            if type(index) is not int or not 0<=index<len(values):
                violations.append('Each sample index must be an integer within the source samples.');continue
            if index in seen:violations.append('A sample index occurs more than once.')
            seen.add(index)
            if not _number(value,null_marker):violations.append('Changed values must be finite numbers or null, excluding booleans and the missing-value marker.')
            elif value!=values[index]:different=True
    if not different:violations.append('A derived result requires changed samples.')
    if violations:raise ValidationFailed(violations)
    return changes


def json_bytes(value):
    try:raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
    except (ValueError,TypeError,OverflowError):raise ValidationFailed(['Request must be finite JSON data.']) from None
    if len(raw)>MAX_REQUEST_BYTES:raise ValidationFailed(['Request exceeds 2,100,000 bytes.'])
    return raw


def validate_recipients(read,reuse):
    for values in (read,reuse):
        if not isinstance(values,list) or any(not isinstance(x,str) or not x for x in values) or len(values)!=len(set(values)):
            raise ValidationFailed(['Recipients must be distinct account names.'])
    if not set(reuse)<=set(read):raise ValidationFailed(['Reuse recipients require read access.'])

# Public operation planning is shared by the synchronous and asynchronous drivers.
import base64
import hashlib
from urllib.parse import quote
from pydantic import ValidationError
from .errors import Refused,VerificationFailed,PermissionRefused
from .models import api
from .models.generated import ApplicationCurve

READ_OPERATIONS={'list','get','read','original','download','options','inspect','result-list','result-preview','result-download','result-history','info','members'}
WRITE_OPERATIONS={'configure','start','publish','upload','share'}
GROUP_OPERATIONS={'list','diff'}  # E8: result groups and diffs are read operations
AI_OPERATIONS={'ai-use':{'get','grant','corpus'},'search':{'query'},'publications':{'derive','info','share'}}  # E14; E30b publications
ENTITY_OPERATIONS={'entities':{'list','get','assets','associations','lineage','create','identify','share','associate','dissociate','extent'}}  # E20; E29 extent; H3 associations
SOURCE_OPERATIONS={'sources':{'list','export'}}  # E50a: the source reads (not READ_OPERATIONS, which would also allow applications/export)
MAP_OPERATIONS={'maps':{'export'},'catalog':{'history'}}  # E70a C4: `get` of a scalar map and its version numbers (existing read routes)
RESULT_OPERATIONS={'results':{'story','what-changed','dependents','remake-run','remake-save'}}  # E94: how a result was made, and making it again
REPORT_OPERATIONS={'activity':{'report'}}  # E70b: a confirmed `get` reports which version this holder received
IMPORT_OPERATIONS={'well-imports':{'preview','start','step','status','list','cancel'},  # E42a: import a copy of an approved well table
                   'upload-runs':{'start','file','check','file-parts','status','list','cancel','associate','decide','share'}}  # E55: a folder upload; E85: check
RELEASE_OPERATIONS={'releases':{'list','get','download','download-snapshot'}}  # E50c: the kept copies Wells.with_source reads (read routes only)
SESSION_OPERATIONS={'las-uploads':{'begin','part','state','finish','cancel'},'capabilities':{'describe'}}  # E54: a file sent in parts; the served limits


# E39: an organisation's connections are not a project's; their routes carry no project (/api/v1/<area>/<op>).
ORGANIZATION_OPERATIONS={'org-connections':{'list'}}


def operation_path(project,area,operation):
    if area in ORGANIZATION_OPERATIONS:
        if operation not in ORGANIZATION_OPERATIONS[area]:raise Refused('Unsupported application operation.')
        return '/api/v1/'+area+'/'+operation
    allowed=(GROUP_OPERATIONS if area=='result-groups' else READ_OPERATIONS|WRITE_OPERATIONS if area in ('applications','las-uploads')
             else ENTITY_OPERATIONS.get(area) or SOURCE_OPERATIONS.get(area) or MAP_OPERATIONS.get(area) or REPORT_OPERATIONS.get(area) or RESULT_OPERATIONS.get(area) or IMPORT_OPERATIONS.get(area) or RELEASE_OPERATIONS.get(area) or AI_OPERATIONS.get(area,set()))
    allowed=allowed|SESSION_OPERATIONS.get(area,set())
    if operation not in allowed:
        raise Refused('Unsupported application operation.')
    return '/api/v1/projects/'+quote(project,safe='')+'/'+area+'/'+operation


def parse(model,data):
    try:return model.model_validate(data)
    except (ValidationError,ValueError,TypeError):raise VerificationFailed('The application response does not match the supported contract.') from None


def parse_run(data,client=None):
    model=api.RestrictedRun if data.get('parent_visibility')=='restricted' else api.Run
    result=parse(model,data)
    if isinstance(result,api.Run):result._client=client
    return result


def parse_result(data):
    # A missing input is not interpreted as a redacted input; only explicit null is.
    model=api.RestrictedResultSummary if 'input' in data and data['input'] is None else api.ResultSummary
    return parse(model,data)


def selection(asset):
    if isinstance(asset,api.Receipt):asset=asset.asset
    elif isinstance(asset,api.UploadResult):asset={**asset.model_dump(),'authority':'ophiolite:uploaded'}
    elif isinstance(asset,api.PublicationReceipt):asset={'asset_id':asset.asset_id,'revision':asset.revision,'authority':'ophiolite:publication'}  # E31
    elif hasattr(asset,'model_dump'):asset=asset.model_dump(by_alias=True,exclude_unset=True)
    if not isinstance(asset,dict) or any(not isinstance(asset.get(key),str) or not asset[key] for key in ('asset_id','revision','authority')):
        raise Refused('Supply an exact asset and revision with its source authority.')
    if asset['authority'] not in ('ophiolite:derived','ophiolite:uploaded','ophiolite:publication'):
        raise Refused('Sharing here supports retained results, uploaded originals and derived publications.')
    return dict(asset)


def grants(asset,result):
    asset=selection(asset)
    if asset['authority'] in ('ophiolite:uploaded','ophiolite:publication'):item=result
    else:
        items=result.get('results')
        if not isinstance(items,list):raise VerificationFailed('Invalid result catalogue response.')
        selected=[item for item in items if item.get('asset_id')==asset['asset_id'] and item.get('revision')==asset['revision']]
        if len(selected)!=1:raise PermissionRefused('Current recipients are unavailable for this exact result.')
        item=selected[0]
    if item.get('asset_id')!=asset['asset_id'] or item.get('revision')!=asset['revision'] or item.get('can_share') is not True:
        raise PermissionRefused('Current recipients are unavailable for this exact asset.')
    if 'recipients' not in item or 'reuse_recipients' not in item:
        raise VerificationFailed('The recipient response is incomplete.')
    generation=item.get('grants_generation')
    if generation is not None and (type(generation) is not int or generation<0):raise VerificationFailed('The recipient generation is invalid.')
    audience=item.get('project_audience')  # E78: the author's answer carries it where the server supports it
    if audience not in (None,'read','none'):raise VerificationFailed('The project audience is invalid.')
    result=parse(api.Grants,{**{key:item[key] for key in ('asset_id','revision','recipients','reuse_recipients')},'generation':generation,
                             'project':None if audience is None else audience=='read'})
    validate_recipients(result.recipients,result.reuse_recipients)
    return result


def decode_payload(data,*,sha256,limit=32*1024*1024,length=None):
    try:raw=base64.b64decode(data['payload_base64'],validate=True)
    except (KeyError,ValueError,TypeError):raise VerificationFailed('The application artifact is not valid encoded data.') from None
    if len(raw)>limit or (length is not None and len(raw)!=length):raise VerificationFailed('The application artifact has an unexpected length.')
    if hashlib.sha256(raw).hexdigest()!=sha256:raise VerificationFailed('The application artifact checksum differs.')
    return raw


def configure_body(asset,revision,curve,name,command_id,*,publication_profile='las-derived-curves/1',release_id=None,asset_index=0,runners=None):
    if not all(isinstance(value,str) and value for value in (curve,name,command_id)):
        raise Refused('Supply curve, name and a command for the input configuration.')
    if publication_profile not in ('las-derived-curves/1','curve-edits/1'):raise Refused('Unsupported publication profile.')
    body={'curve':curve,'name':name,'command_id':command_id,'publication_profile':publication_profile}
    if release_id is not None:
        if asset is not None or revision is not None:raise Refused('Choose one exact retained input.')
        body.update(release_id=release_id,asset_index=asset_index,runners=runners or [])
    else:
        if not all(isinstance(value,str) and value for value in (asset,revision)):raise Refused('Supply an exact input asset and revision.')
        body.update(asset_id=asset,asset_revision=revision)
    return body


def start_body(binding,command_id,application_version,parameters):
    if not isinstance(binding,api.Binding):binding=parse(api.Binding,binding)
    if not isinstance(command_id,str) or not command_id or not isinstance(application_version,str) or not application_version:
        raise Refused('Supply the command and declared application version.')
    if not isinstance(parameters,dict) or len(json_bytes(parameters))>4096:raise Refused('Application parameters exceed the supported size.')
    return {'id':binding.id,'generation':binding.generation,'command_id':command_id,'application_version':application_version,'parameters':parameters}


def publication_body(run,original,view,*,derived_curves=None,changes=None,new_version_of=None):
    if not isinstance(run,api.Run):raise Refused('Use a resolved run owned by this application.')
    if (derived_curves is None)==(changes is None):raise ValidationFailed(['Choose derived curves or sample changes, exclusively.'])
    if hashlib.sha256(original).hexdigest()!=run.input_sha256:raise VerificationFailed('Resolved input checksum differs.')
    if view.source_sha256!=run.input_sha256 or view.source.model_dump()!=run.input_reference.model_dump():
        raise VerificationFailed('Resolved normalized input refers to a different source.')
    profile='las-derived-curves/1' if derived_curves is not None else 'curve-edits/1'
    if run.binding.publication_profile!=profile:raise Refused('Publication profile differs from the resolved binding.')
    body={'id':run.id,'publication_profile':profile}
    if derived_curves is not None:body['derived_curves']=validate_derived_curves(derived_curves,source=original,sample_count=len(view.values))
    else:body['changes']=validate_changes(changes,values=view.values,null_marker=source_null_marker(original))
    if new_version_of is not None:
        # The revision you reviewed is the expected parent: a newer head is refused (409), never overwritten.
        target=selection(new_version_of)
        if target['authority']!='ophiolite:derived':raise Refused('New versions apply to your published results only.')
        body.update(append_to=target['asset_id'],expected_parent=target['revision'])
    json_bytes(body)
    return body

import os
from pathlib import Path
import tempfile
import uuid
from contextlib import contextmanager
from . import auth
from .errors import AuthenticationRequired,Busy,RecoveryUnavailable


def _fsync_directory(path):
    if os.name=='nt':return  # Windows durability is not qualified.
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _private_bytes(path):
    try:
        auth._check(path.lstat())
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as stream:
            auth._check(os.fstat(stream.fileno()))
            return stream.read()
    except (OSError,AuthenticationRequired):raise RecoveryUnavailable('Cannot read the private work checkpoint.') from None


def _stored(path):
    raw=_private_bytes(path)
    try:return json.loads(raw)
    except (ValueError,UnicodeError):raise RecoveryUnavailable('The work checkpoint is not valid JSON.') from None


def _atomic(path,raw,*,replace=False):
    if not replace and (path.exists() or path.is_symlink()):
        if _private_bytes(path)!=raw:raise Refused(path.name+' belongs to different work; use a new run folder.')
        return
    fd,temporary=tempfile.mkstemp(prefix='.checkpoint-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if replace:
            if path.exists() or path.is_symlink():auth._check(path.lstat())
            os.replace(temporary,path)
        else:os.link(temporary,path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def _checkpoint(path,value,*,replace=False,sort_keys=False):
    # Match the frozen handoff's bytes: indent=2, no appended newline.
    raw=json.dumps(value,indent=2,allow_nan=False,sort_keys=sort_keys).encode()
    if not replace and path.exists():
        if _stored(path)!=value:raise Refused(path.name+' belongs to different work; use a new run folder.')
        return
    _atomic(path,raw,replace=replace)


class WorkFolder:
    """One private recoverable application workflow; no token is saved in this folder."""
    def __init__(self,client,path,*,lock_timeout=5):
        self.client,self.path,self.lock_timeout=client,Path(path).expanduser().absolute(),lock_timeout
        self.path.mkdir(mode=0o700,parents=True,exist_ok=True)
        auth._parent(self.path/'run.json')

    @contextmanager
    def _locked(self):
        lock=auth._lock(self.path/'.transaction',timeout=self.lock_timeout)
        try:lock.__enter__()
        except AuthenticationRequired:raise Busy('This work folder is busy or not private. Retry when its current operation finishes.') from None
        try:yield
        finally:lock.__exit__(None,None,None)

    @contextmanager
    def _identity(self):
        credential=self.client.credential
        if credential is None:raise AuthenticationRequired('Supply an explicit SDK credential for recoverable work.')
        url,project=self.client.url,self.client.project
        owner=self.path/'owner.json'
        if owner.exists():
            known=_stored(owner)
            if not isinstance(known,dict) or (known.get('url'),known.get('project'))!=(url,project):
                raise RecoveryUnavailable('This folder belongs to another gateway or project.')
        with credential.snapshot(url,project) as captured:
            headers=dict(captured)
            grant=headers.get('X-Ophiolite-Application-Grant')
            if grant:
                result=self.client._grant_status(headers)
                if result.get('state')!='approved' or result.get('project_id')!=project or not isinstance(result.get('user_id'),str) or not result['user_id']:
                    raise AuthenticationRequired('The application grant is not approved for this project.')
                identity={'kind':'grant','user_id':result['user_id']}
            else:
                token=headers.get('Authorization','')
                if not token.startswith('Bearer ') or not token[7:]:raise AuthenticationRequired('Supply an explicit scoped delegate for recoverable work.')
                identity={'kind':'delegate','fingerprint':hashlib.sha256(token[7:].encode()).hexdigest()}
            if (self.client.url,self.client.project)!=(url,project):raise RecoveryUnavailable('The gateway or project changed during authorization.')
            expected={'schema':'ophiolite.sdk-work/1','url':url,'project':project,'identity':identity}
            owner=self.path/'owner.json'
            if owner.exists():
                if _stored(owner)!=expected:raise RecoveryUnavailable('This folder belongs to another gateway, project or credential identity. Keep it and reopen with its original identity.')
            else:_checkpoint(owner,expected)
            # Keep this credential snapshot locked through lookup and send.
            yield headers

    def _state(self):
        value=_stored(self.path/'run.json')
        if not isinstance(value,dict) or not isinstance(value.get('config'),dict):raise RecoveryUnavailable('The work configuration is not a supported object.')
        config=value['config']
        if config.get('url')!=self.client.url or config.get('project')!=self.client.project:
            raise RecoveryUnavailable('This work folder belongs to another gateway or project.')
        return value

    def _request_paths(self):
        return sorted((self.path/'requests').glob('[0-9]*.meta.json'))

    def _validate_context(self,operation,body,state):
        if body.get('project_id')!=self.client.project:raise RecoveryUnavailable('The saved request belongs to another project.')
        if operation=='configure':
            spec=state['config'].get('input')
            if not isinstance(spec,dict) or any(body.get(k)!=v for k,v in spec.items()) or body.get('command_id')!=state.get('configure_command'):
                raise RecoveryUnavailable('The input configuration differs from its saved request.')
        if operation=='start':
            if body.get('id')!=state.get('binding',state['config'].get('binding')) or body.get('parameters')!=state['config'].get('parameters') or body.get('command_id')!=state.get('command_id') or body.get('generation')!=state.get('generation'):
                raise RecoveryUnavailable('The resolved run configuration differs from its saved request.')
        if operation=='publish':
            run=_stored(self.path/'resolved.json')
            if body.get('id')!=run.get('id'):raise RecoveryUnavailable('Publication refers to another resolved run.')
            if _stored(self.path/'publication.json')!={k:v for k,v in body.items() if k!='project_id'}:
                raise RecoveryUnavailable('Publication differs from its saved request.')
        script=self.path/'calculation.py'
        code=state['config'].get('parameters',{}).get('code_sha256')
        if code and (not script.exists() or hashlib.sha256(_private_bytes(script)).hexdigest()!=code):
            raise RecoveryUnavailable('Calculation changed; prepare a new run folder.')

    def _typed(self,operation,data,body=None):
        checked=verify_application_reply(operation,body,data,self.client.project,self.client) if body is not None and operation!='upload' else None
        if operation=='configure':return checked or parse(api.Binding,data)
        if operation in ('start','publish'):
            result=checked or parse_run(data,self.client)
            if not isinstance(result,api.Run):raise VerificationFailed('An owned workflow returned a restricted result.')
            result._work=self
            if operation=='publish':
                if result.receipt is None:raise VerificationFailed('Publication returned no receipt.')
                resolved=_stored(self.path/'resolved.json')
                if data.get('input')!=resolved.get('input') or data.get('input_sha256')!=resolved.get('input_sha256'):raise VerificationFailed('Publication changed the resolved scientific input.')
                return result.receipt
            return result
        if operation=='upload':return parse(api.UploadResult,data)
        raise RecoveryUnavailable('Unsupported saved operation.')

    def _finish(self,operation,data,state):
        if operation=='configure':
            state.update(binding=data['id'],generation=data['generation'])
            _checkpoint(self.path/'run.json',state,replace=True)
            _checkpoint(self.path/'binding.json',data)
        elif operation=='start':_checkpoint(self.path/'resolved.json',data)
        elif operation=='publish':_checkpoint(self.path/'receipt.json',data)
        elif operation=='upload':_checkpoint(self.path/'upload.json',data)

    def _step(self,operation,body,headers,*,area='applications',payload=None,extra_headers=None):
        state=self._state();complete={'project_id':self.client.project,**body}
        if operation!='upload':self._validate_context(operation,complete,state)
        for directory in ('requests','responses'):(self.path/directory).mkdir(mode=0o700,exist_ok=True)
        _fsync_directory(self.path)
        existing=[p for p in self._request_paths() if _stored(p).get('operation')==operation]
        if existing:
            if len(existing)!=1:raise RecoveryUnavailable('The work folder contains conflicting requests.')
            metadata_path=existing[0];metadata=_stored(metadata_path)
            if metadata['request']!=complete or metadata['area']!=area or metadata.get('headers',{})!=(extra_headers or {}):
                raise Refused('This operation belongs to different work; use a new run folder.')
            if payload is not None and hashlib.sha256(payload).hexdigest()!=metadata['sha256']:
                raise Refused('Upload bytes belong to different work; use a new run folder.')
        else:
            number=len(self._request_paths())+1;stem=f'{number:04d}-{operation}'
            metadata_path=self.path/'requests'/(stem+'.meta.json')
            raw=payload if payload is not None else json_bytes(complete)
            filename=stem+('.las' if payload is not None else '.json')
            _atomic(self.path/'requests'/filename,raw)
            metadata={'schema':'ophiolite.sdk-request/1','operation':operation,'area':area,'request':complete,
                      'file':filename,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'headers':extra_headers or {}}
            _checkpoint(metadata_path,metadata)
        raw=self._verify_request(metadata_path,metadata)
        response_path=self.path/'responses'/metadata_path.name.replace('.meta.json','.json')
        if response_path.exists():data=_stored(response_path)
        else:
            owner=_stored(self.path/'owner.json')
            data=self.client._post_bytes(area,operation,raw,extra_headers=metadata['headers'] or None,headers=headers,retry=True,expected_context=(owner['url'],owner['project']))
            if operation=='upload' and data.get('revision')!=metadata['sha256']:raise VerificationFailed('The uploaded original has a different checksum revision.')
            self._typed(operation,data,metadata['request'])  # Refuse malformed responses before checkpointing.
            _checkpoint(response_path,data)
        if operation=='upload' and data.get('revision')!=metadata['sha256']:raise VerificationFailed('The uploaded original has a different checksum revision.')
        result=self._typed(operation,data,metadata['request'])
        self._finish(operation,data,state)
        return result

    def _verify_request(self,path,metadata):
        if not isinstance(metadata,dict):raise RecoveryUnavailable('The saved request is not a supported object.')
        if metadata.get('schema')!='ophiolite.sdk-request/1' or metadata.get('operation') not in ('configure','start','publish','upload'):
            raise RecoveryUnavailable('Unsupported saved request.')
        filename=metadata.get('file')
        if not isinstance(filename,str) or Path(filename).name!=filename or filename in ('.','..'):
            raise RecoveryUnavailable('Unsafe saved request path.')
        raw=_private_bytes(path.parent/filename)
        if len(raw)!=metadata.get('bytes') or hashlib.sha256(raw).hexdigest()!=metadata.get('sha256'):
            raise RecoveryUnavailable('Saved request bytes are missing or changed; keep the folder for inspection.')
        if metadata['operation']!='upload':
            if metadata.get('area')!='applications':raise RecoveryUnavailable('Invalid saved application area.')
            if raw!=json_bytes(metadata['request']):raise RecoveryUnavailable('Saved request metadata and bytes disagree.')
            self._validate_context(metadata['operation'],metadata['request'],self._state())
        else:
            if metadata.get('area')!='las-uploads' or metadata['request'].get('project_id')!=self.client.project or metadata['request'].get('command_id')!=self._state().get('upload_command'):
                raise RecoveryUnavailable('Invalid upload request context.')
            expected={'Content-Type':'application/octet-stream','X-Ophiolite-Upload':base64.b64encode(json_bytes(metadata['request'])).decode()}
            if metadata.get('headers')!=expected:raise RecoveryUnavailable('Saved upload header differs from its request.')
        if metadata['operation']!='upload' and metadata.get('headers')!={}:raise RecoveryUnavailable('Unexpected saved request headers.')
        return raw

    def configure(self,asset=None,revision=None,*,curve,name,publication_profile='las-derived-curves/1',release_id=None,asset_index=0,runners=None):
        spec=({'asset_id':asset,'asset_revision':revision,'curve':curve,'name':name} if release_id is None
              else {'release_id':release_id,'asset_index':asset_index,'curve':curve,'name':name,'runners':runners or []})
        with self._locked(),self._identity() as headers:
            state_path=self.path/'run.json'
            if state_path.exists():
                state=self._state()
                if state['config'].get('input')!=spec:raise Refused('Input belongs to different work; use a new run folder.')
            else:
                state={'config':{'url':self.client.url,'project':self.client.project,'binding':None,'parameters':{},'input':spec},
                       'command_id':uuid.uuid4().hex,'configure_command':uuid.uuid4().hex}
                _checkpoint(state_path,state)
            body=configure_body(asset,revision,curve,name,state['configure_command'],publication_profile=publication_profile,release_id=release_id,asset_index=asset_index,runners=runners)
            return self._step('configure',body,headers)

    def start(self,binding,*,application_version,parameters,script=None):
        if not isinstance(binding,api.Binding):binding=parse(api.Binding,binding)
        parameters=dict(parameters)
        if script is not None:
            raw=Path(script).read_bytes() if not isinstance(script,bytes) else script
            parameters['code_sha256']=hashlib.sha256(raw).hexdigest()
        with self._locked(),self._identity() as headers:
            if (self.path/'run.json').exists():state=self._state()
            else:
                state={'config':{'url':self.client.url,'project':self.client.project,'binding':binding.id,'parameters':parameters,'input':None},'command_id':uuid.uuid4().hex}
            prior=[_stored(p) for p in self._request_paths() if _stored(p)['operation']=='start']
            if prior and (state['config']['parameters']!=parameters or state.get('binding')!=binding.id or state.get('generation')!=binding.generation or prior[0]['request'].get('application_version')!=application_version):
                raise Refused('Parameters or binding belong to different work; use a new run folder.')
            state['config']['parameters']=parameters;state.update(binding=binding.id,generation=binding.generation)
            if script is not None:_atomic(self.path/'calculation.py',raw)
            _checkpoint(self.path/'run.json',state,replace=True)
            body=start_body(binding,state['command_id'],application_version,parameters)
            return self._step('start',body,headers)

    def input(self,run):
        with self._locked():
            original,view=self.client.run_input(run)
            _atomic(self.path/'input.las',original)
            _checkpoint(self.path/'input-reference.json',run._original_reference)
            _checkpoint(self.path/'normalized.json',view.model_dump(by_alias=True,exclude_unset=True))
            return original,view

    def publish(self,run,*,derived_curves=None,changes=None,new_version_of=None):
        original=_private_bytes(self.path/'input.las')
        view=parse(ApplicationCurve,_stored(self.path/'normalized.json'))
        body=publication_body(run,original,view,derived_curves=derived_curves,changes=changes,new_version_of=new_version_of)
        with self._locked(),self._identity() as headers:
            if derived_curves is not None:_checkpoint(self.path/'curves.json',derived_curves)
            _checkpoint(self.path/'publication.json',body)
            return self._step('publish',body,headers)

    def download(self,receipt):
        with self._locked():
            raw=self.client.download(receipt);_atomic(self.path/'result.las',raw);return raw

    def correct(self,binding,*,start,stop,offset):
        """Explicit local interval-offset example, preserving the pilot files."""
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (start,stop,offset)) or start>stop:
            raise ValidationFailed(['Finite ordered interval and offset required'])
        run=self.start(binding,application_version='interval-offset/1',parameters={'start':start,'stop':stop,'offset':offset})
        recovered=(self.path/'receipt.json').exists()
        if (self.path/'input.json').exists():
            original=_private_bytes(self.path/'original.las')
            wire=_stored(self.path/'input.json');view=parse(ApplicationCurve,wire)
        else:
            original,view=self.input(run);wire=run._view_wire
        changes=[{'index':i,'value':value+offset} for i,(depth,value) in enumerate(zip(view.axis,view.values)) if start<=depth<=stop and value is not None and offset!=0]
        validate_changes(changes,values=view.values,null_marker=source_null_marker(original))
        with self._locked():
            _atomic(self.path/'original.las',original)
            _checkpoint(self.path/'input.json',wire)
            _checkpoint(self.path/'changes.json',changes)
        body=publication_body(run,original,view,changes=changes)
        body.pop('publication_profile')  # Frozen offset CLI uses the server's curve-edit default.
        with self._locked(),self._identity() as headers:
            _checkpoint(self.path/'publication.json',body)
            receipt=self._step('publish',body,headers)
        self.download(receipt)
        with self._locked():
            for name in ('run.json','changes.json','receipt.json'):
                _checkpoint(self.path/name,_stored(self.path/name),replace=True,sort_keys=True)
        print('Recovered existing publication; source unchanged. Run:' if recovered else 'Published portable LAS; source unchanged. Run:',run.id)
        print('Output:',self.path/'result.las')
        print('Provenance is script-declared. This is not scientific approval.')
        return receipt

    def recover(self,through=None):
        if through not in (None,'configure','start','publish','upload'):raise RecoveryUnavailable('Choose a saved operation to recover through.')
        with self._locked(),self._identity() as headers:
            paths=self._request_paths()
            if not paths:raise RecoveryUnavailable('This folder has no saved request to recover.')
            result=None
            for path in paths:
                metadata=_stored(path);self._verify_request(path,metadata)
                response=self.path/'responses'/path.name.replace('.meta.json','.json')
                if response.exists():
                    data=_stored(response)
                    if metadata['operation']=='upload' and data.get('revision')!=metadata['sha256']:raise VerificationFailed('The uploaded original has a different checksum revision.')
                    self._typed(metadata['operation'],data,metadata['request'])
                    self._finish(metadata['operation'],data,self._state());continue
                operation=metadata['operation'];body={k:v for k,v in metadata['request'].items() if k!='project_id'}
                payload=_private_bytes(path.parent/metadata['file']) if operation=='upload' else None
                result=self._step(operation,body,headers,area=metadata['area'],payload=payload,extra_headers=metadata['headers'])
                if through is None or operation==through:return result
            return result

MAX_UPLOAD=32*1024*1024  # the largest single request (inspect, derive, work folders); upload_data and upload_las follow the served table
SINGLE=8*1024*1024  # a file up to this size is sent in one request, as before E54, without asking for the limits
DIGEST_BLOCK=1024*1024


class FileSource:
    """E54: an original read by ranges, from a path (never read whole) or from bytes already in memory."""
    def __init__(self,source):
        if isinstance(source,(bytes,bytearray,memoryview)):self.raw,self.path,self.size=bytes(source),None,len(source)
        else:self.raw,self.path=None,Path(source);self.size=self.path.stat().st_size
        if not self.size:raise ValidationFailed(['The file is empty; nothing was sent.'])

    def read(self,offset,n):
        if self.raw is not None:return self.raw[offset:offset+n]
        with self.path.open('rb') as stream:
            stream.seek(offset);return stream.read(n)

    def whole(self):
        return self.raw if self.raw is not None else self.read(0,self.size)

    def sha256(self):
        if self.raw is not None:return hashlib.sha256(self.raw).hexdigest()
        digest=hashlib.sha256()
        with self.path.open('rb') as stream:
            for block in iter(lambda:stream.read(DIGEST_BLOCK),b''):digest.update(block)
        return digest.hexdigest()


def part_header(project,upload_id,index,raw):
    meta={'project_id':project,'upload_id':upload_id,'index':index,'sha256':hashlib.sha256(raw).hexdigest()}
    return {'Content-Type':'application/octet-stream','X-Ophiolite-Upload':base64.b64encode(json_bytes(meta)).decode()}


def upload_bytes(source):
    if isinstance(source,bytes):raw=source
    else:
        with Path(source).open('rb') as stream:raw=stream.read(MAX_UPLOAD+1)
    if not raw or len(raw)>MAX_UPLOAD:raise ValidationFailed(['LAS uploads must contain between one byte and 32 MiB; a deployment may set a lower limit.'])
    return raw


def upload_metadata(project,command_id,*,filename,name,attribution,audience,rights_confirmed,well_notes='',profile=None,declared=None,well_log=None,origin=None,
                    append_to=None,expected_parent=None):
    value={'project_id':project,'command_id':command_id,'filename':filename,'name':name,'attribution':attribution,
           'audience':audience,'rights_confirmed':rights_confirmed,'well_notes':well_notes}
    # Fields are sent only when used, so existing LAS uploads keep their exact request (and retry fingerprint).
    if profile not in (None,'las2/1'):value['profile']=profile
    if declared:value['declared']=declared
    if well_log is not None:value['well_log']=well_log
    if origin is not None:value['origin']=origin
    if (append_to is None)!=(expected_parent is None):raise ValidationFailed(['Name the result and the version it replaces.'])
    if append_to is not None:value.update(append_to=append_to,expected_parent=expected_parent)  # E53: a new version of your own upload
    try:api.UploadRequest.model_validate(value)
    except ValidationError:raise ValidationFailed(['Confirm rights, project, name, attribution and bounded upload details.']) from None
    validate_recipients(audience,[])
    if not name.strip() or not attribution.strip() or any(len(recipient)>160 for recipient in audience):
        raise ValidationFailed(['Supply a name, attribution and supported recipient names.'])
    encoded=base64.b64encode(json_bytes(value)).decode()
    if len(encoded)>8192:raise ValidationFailed(['Upload details exceed the supported header size.'])
    return value,{'Content-Type':'application/octet-stream','X-Ophiolite-Upload':encoded}


def _work_upload(self,source,*,name,attribution,audience,rights_confirmed,filename=None,well_notes=''):
    raw=upload_bytes(source)
    filename=filename or (Path(source).name if not isinstance(source,bytes) else 'input.las')
    # Validate before any identity lookup or mutation; the stable command is filled
    # from the folder only after taking its transaction lock.
    upload_metadata(self.client.project,'validation',filename=filename,name=name,attribution=attribution,audience=audience,rights_confirmed=rights_confirmed,well_notes=well_notes)
    with self._locked(),self._identity() as headers:
        state=self._state() if (self.path/'run.json').exists() else {'config':{'url':self.client.url,'project':self.client.project,'binding':None,'parameters':{},'input':None},'command_id':uuid.uuid4().hex}
        if 'upload_command' not in state:state['upload_command']=uuid.uuid4().hex
        _checkpoint(self.path/'run.json',state,replace=True)
        body,extra=upload_metadata(self.client.project,state['upload_command'],filename=filename,name=name,attribution=attribution,audience=audience,rights_confirmed=rights_confirmed,well_notes=well_notes)
        return self._step('upload',body,headers,area='las-uploads',payload=raw,extra_headers=extra)

WorkFolder.upload_las=_work_upload


def _parent(value):
    if isinstance(value,(tuple,list)) and len(value)==2:return {'asset_id':value[0],'revision':value[1]}
    if hasattr(value,'model_dump'):value=value.model_dump(by_alias=True)
    elif not isinstance(value,dict):value={'asset_id':getattr(value,'asset_id',None),'revision':getattr(value,'revision',None)}
    parent={'asset_id':value.get('asset_id') or value.get('key'),'revision':value.get('revision')}
    if not all(isinstance(v,str) and v for v in parent.values()):raise ValidationFailed(['Name each parent by its exact asset and revision.'])
    return parent


def derive_request(project,written,*,name,from_,method,command_id,of_entity=None,new_version_of=None,expected_parent=None):
    """The X-Ophiolite-Upload header of publications/derive, validated before anything is sent."""
    import hashlib
    from .writers import WrittenOriginal
    if not isinstance(written,WrittenOriginal):raise ValidationFailed(['Publish a file made by ophiolite.writers (a WrittenOriginal).'])
    if not isinstance(command_id,str) or not 0<len(command_id)<=64:raise ValidationFailed(['Give a command id (1-64 characters) that you keep for retries.'])
    if not written.bytes or len(written.bytes)>MAX_UPLOAD:raise ValidationFailed(['A derived file holds between one byte and 32 MiB; a deployment may set a lower limit.'])
    parents=[_parent(p) for p in (from_ if isinstance(from_,(list,tuple)) and not (len(from_)==2 and isinstance(from_[0],str)) else [from_])]
    method=method.model_dump() if hasattr(method,'model_dump') else dict(method)
    body={'project_id':project,'command_id':command_id,'profile':written.profile,'name':name,'derived_from':parents,'method':method,
          'output_sha256':hashlib.sha256(written.bytes).hexdigest(),'output_bytes':len(written.bytes)}
    if written.declared:body['declared']=dict(written.declared)
    if of_entity is not None:body['of_entity']=dict(of_entity)
    if (new_version_of is None)!=(expected_parent is None):raise ValidationFailed(['A new version names both your earlier result and the version it replaces.'])
    if new_version_of is not None:body.update(new_version_of=new_version_of,expected_parent=expected_parent)
    if not 1<=len(parents)<=32 or len({(p['asset_id'],p['revision']) for p in parents})!=len(parents):raise ValidationFailed(['Name 1-32 distinct parents.'])
    if not isinstance(name,str) or not name.strip() or len(name)>160:raise ValidationFailed(['Give the result a name (up to 160 characters).'])
    try:api.MethodRecord.model_validate(method)
    except ValidationError:raise ValidationFailed(['Declare the method: a name (1-80 characters), and library, version and script digest only when declared.']) from None
    if method.get('declared') is False and (method.get('library') or method.get('version') or method.get('script_sha256')):
        raise ValidationFailed(['An undeclared method names no library, version or script; nothing is invented.'])
    if len(json_bytes(method.get('parameters') or {}))>4096:raise ValidationFailed(['Method parameters are limited to 4096 bytes.'])
    encoded=base64.b64encode(json_bytes(body)).decode()
    if len(encoded)>16384:raise ValidationFailed(['The publication details exceed the supported header size.'])
    return body,{'Content-Type':'application/octet-stream','X-Ophiolite-Upload':encoded}


def verify_derived(body,receipt):
    """The receipt names this file, these parents (in order) and this method."""
    if receipt.revision!=body['output_sha256'] or receipt.command_id!=body['command_id'] or receipt.profile!=body['profile']:
        raise VerificationFailed('The publication receipt names a different file or command.')
    # A parent kept from a connected source (a package copy) is recorded by that source's own reference, so its key is the
    # source's; the exact revision (the copy's sha256) still has to match. Ophiolite's own parents match by asset id too.
    named=[(r.authority.startswith('ophiolite:'),r.key,r.revision) for r in receipt.derived_from]
    sent=[(p['asset_id'],p['revision']) for p in body['derived_from']]
    if len(named)!=len(sent) or any(rev!=revision or (own and key!=asset) for (own,key,rev),(asset,revision) in zip(named,sent)):
        raise VerificationFailed('The publication receipt names different parents.')
    if body.get('new_version_of') and receipt.asset_id!=body['new_version_of']:raise VerificationFailed('The new version was published to a different result.')
    return receipt


def _work_derive(self,written,*,name,from_,method,of_entity=None,new_version_of=None,expected_parent=None):
    """Recoverable publish_derived: the command id and the file's digest are saved in the folder before sending,
    so a crash or a lost response retries the identical command (and a different file under it is refused)."""
    import hashlib
    derive_request(self.client.project,written,name=name,from_=from_,method=method,command_id='validation',of_entity=of_entity,
                   new_version_of=new_version_of,expected_parent=expected_parent)
    digest=hashlib.sha256(written.bytes).hexdigest()
    with self._locked(),self._identity() as headers:
        state=self._state() if (self.path/'run.json').exists() else {'config':{'url':self.client.url,'project':self.client.project,'binding':None,'parameters':{},'input':None},'command_id':uuid.uuid4().hex}
        pending=state.get('derive')
        if pending is None or pending.get('done'):
            pending={'command_id':uuid.uuid4().hex,'output_sha256':digest,'done':False}
        elif pending['output_sha256']!=digest:
            raise RecoveryUnavailable('This folder has an unfinished publication of another file; finish it first (publish the same file again).')
        state['derive']=pending
        _checkpoint(self.path/'run.json',state,replace=True)
        body,extra=derive_request(self.client.project,written,name=name,from_=from_,method=method,command_id=pending['command_id'],of_entity=of_entity,
                                  new_version_of=new_version_of,expected_parent=expected_parent)
        from .models.api import PublicationReceipt
        receipt=verify_derived(body,parse(PublicationReceipt,self.client._post_bytes('publications','derive',written.bytes,extra_headers=extra,headers=headers,retry=True,
                                                                                    expected_context=(self.client.url,self.client.project))))
        state['derive']={**pending,'done':True,'receipt':receipt.model_dump(by_alias=True)}
        _checkpoint(self.path/'run.json',state,replace=True)
        return receipt

def _work_derived(self,written):
    """E31: the receipt this folder already holds for exactly this file, or None (nothing is sent)."""
    import hashlib
    if not (self.path/'run.json').exists():return None
    done=self._state().get('derive') or {}
    if done.get('done') and done.get('output_sha256')==hashlib.sha256(written.bytes).hexdigest():
        from .models.api import PublicationReceipt
        return parse(PublicationReceipt,done['receipt'])
    return None

WorkFolder.publish_derived=_work_derive
WorkFolder.published_derived=_work_derived


def verify_application_reply(operation,body,data,project,client=None):
    if not isinstance(data,dict) or data.get('project_id')!=project:
        raise VerificationFailed('The application response belongs to another project.')
    if operation=='configure':
        result=parse(api.Binding,data)
        if (result.curve,result.name,result.publication_profile)!=(body['curve'],body['name'],body['publication_profile']):
            raise VerificationFailed('The input configuration differs from the requested selection.')
        expected=({'asset_id':body['asset_id'],'revision':body['asset_revision']} if body.get('asset_id') is not None
                  else {'release_id':body['release_id'],'asset_index':body['asset_index']})
        source=data.get('managed_input' if body.get('asset_id') is not None else 'retained_input',{})
        if any(source.get(key)!=value for key,value in expected.items()):raise VerificationFailed('The input configuration refers to a different exact source.')
        return result
    result=parse_run(data,client)
    if not isinstance(result,api.Run):raise VerificationFailed('An owned operation returned a restricted result.')
    if operation=='start':
        if (result.binding.id,result.binding.generation,result.application_version,result.parameters)!=(body['id'],body['generation'],body['application_version'],body['parameters']):
            raise VerificationFailed('The resolved run differs from the requested work.')
    elif operation=='publish':
        if result.id!=body['id'] or result.state!='published' or result.receipt is None:
            raise VerificationFailed('Publication returned a different or incomplete run.')
        if result.receipt.manifest.parent!=result.input_reference:
            raise VerificationFailed('Publication ancestry differs from its resolved input.')
        if body.get('append_to') and (result.receipt.output_reference.key!=body['append_to'] or result.receipt.output_reference.revision_number is None):
            raise VerificationFailed('The new version was published to a different result.')
    return result
