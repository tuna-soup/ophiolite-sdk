"""Explicit fixture transport; never installed as a production fallback."""
import base64
from contextlib import contextmanager
from importlib.resources import files
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
import httpx

class FixtureTransport(httpx.MockTransport):
    """Replay ordered public request/response records without authentication material."""
    def __init__(self,recording):
        self.records=json.loads(Path(recording).read_text()) if isinstance(recording,(str,Path)) else recording
        self.index=0
        super().__init__(self.respond)

    def respond(self,request):
        if self.index>=len(self.records):raise AssertionError('Unexpected additional fixture request')
        row=self.records[self.index];self.index+=1
        if request.method!=row['method'] or request.url.raw_path.decode()!=row['path']:
            raise AssertionError('Fixture request differs from the recorded public request')
        return httpx.Response(row['status'],content=base64.b64decode(row['body_base64']),headers=row.get('headers',{}))


class FixtureServer:
    """Loopback HTTP fixture with a deterministic lost-response boundary.

    ``handler(method, path, raw_body, headers)`` returns ``(status, JSON-or-bytes)``.
    A supplied handler can drive an actual in-process gateway. The default fixture
    is a bounded synthetic application journal, never a production fallback.
    """
    def __init__(self,handler=None,*,drop_response_after=None,drop_count=3):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        self.handler=handler or _MemoryApplications()
        self.requests=[];self._lock=threading.Lock();self._drops={drop_response_after:drop_count} if drop_response_after else {}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.respond()
            def do_POST(self):self.respond()
            def respond(self):
                import socket
                length=int(self.headers.get('Content-Length','0'))
                if length>8*1024*1024:self.send_error(413);return
                raw=self.rfile.read(length)
                with owner._lock:
                    owner.requests.append({'method':self.command,'path':self.path,'body_base64':base64.b64encode(raw).decode()})
                status,value=owner.handler(self.command,self.path,raw,dict(self.headers))
                with owner._lock:
                    operation=self.path.split('?',1)[0].rsplit('/',1)[-1]
                    drop=status==200 and owner._drops.get(operation,0)>0
                    if drop:owner._drops[operation]-=1
                if drop:
                    self.close_connection=True
                    try:self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    self.connection.close();return
                body=value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode()
                self.send_response(status);self.send_header('Content-Type','application/octet-stream' if isinstance(value,bytes) else 'application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def drop(self,operation,count=3):
        with self._lock:self._drops[operation]=count
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(3)


def fixture_server(handler=None,**options):return FixtureServer(handler,**options)


class _MemoryApplications:
    def __init__(self):
        import importlib.resources,threading
        self._journal_lock=threading.RLock()
        root=importlib.resources.files('ophiolite').joinpath('contracts/assets/v1/fixtures')
        self.original=root.joinpath('original.las').read_bytes()
        self.view=json.loads(root.joinpath('curve.json').read_bytes())
        self.bindings={};self.runs={};self.uploads={};self.commands={};self.results={};self.mutations={};self.audiences={}
        # Conditional sharing (E7). conditional=False simulates a pre-E7 server that ignores the fields.
        self.conditional=True;self.generations={};self.share_commands={}
        # E78: who of the project sees a publication; project_capable=False simulates a server that predates it.
        self.project_capable=True;self.project_audiences={}
        # E70c: the members the project names to add versions to each other's results (empty: only the author, as before).
        self.version_contributors=set()
    def __call__(self,method,path,raw,headers):
        with self._journal_lock:return self._call(method,path,raw,headers)
    def _call(self,method,path,raw,headers):
        import copy,hashlib,time
        from urllib.parse import urlsplit
        from .publish import json_bytes
        token=next((v for k,v in headers.items() if k.lower()=='authorization'),'')
        owner=token.removeprefix('Bearer ').removeprefix('oph_api_').removeprefix('provider-').split(':')[0]
        if not owner or owner=='expired':return 401,{'error':'authorization required'}
        operation=urlsplit(path).path.rsplit('/',1)[-1]
        if path=='/api/v1/application-access/status':return 200,{'state':'approved','project_id':'p','user_id':owner}
        try:
            if '/publications/' in path:return self._publication(operation,path,raw,headers,owner)  # E31: derived publications
            if operation=='result-history' and json.loads(raw).get('asset_id') in getattr(self,'publications',{}):return self.history(json.loads(raw)['asset_id'],owner)  # E52
            upload='/las-uploads/' in path
            if upload and operation in ('upload','inspect'):
                extra=next(v for k,v in headers.items() if k.lower()=='x-ophiolite-upload')
                body=json.loads(base64.b64decode(extra,validate=True))
                if raw!=self.original:return 400,{'error':'Fixture accepts the packaged synthetic LAS only'}
                if operation=='inspect':return 200,{'curves':[{'mnemonic':'DEPT','unit':'M'},{'mnemonic':'GR','unit':'gAPI'}]}
            else:body=json.loads(raw)
            project=body['project_id']
            if project!='p':return 403,{'error':'project unavailable'}
            if operation in ('configure','start','upload'):
                key=(operation,owner,project,body['command_id']);fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+(raw if upload else b'')).hexdigest()
                if key in self.commands:
                    prior,answer=self.commands[key]
                    return (200,copy.deepcopy(answer)) if prior==fingerprint else (400,{'error':'Command reused with different input'})
                ident=hashlib.sha256(json_bytes(list(key))).hexdigest()
            if operation=='configure':
                answer={'id':ident,'owner':owner,'project_id':project,'kind':'binding','name':body['name'],'generation':1,'curve':body['curve'],
                        'publication_profile':body.get('publication_profile','curve-edits/1'),'managed_input':{'asset_id':body.get('asset_id','synthetic'),'revision':body.get('asset_revision','synthetic')}}
                self.bindings[ident]=answer
            elif operation=='start':
                binding=self.bindings[body['id']]
                answer={'id':ident,'owner':owner,'project_id':project,'kind':'run','binding':binding,'input':self.view['source'],
                        'input_sha256':hashlib.sha256(self.original).hexdigest(),'application_version':body['application_version'],
                        'parameters':body['parameters'],'state':'resolved','created':time.time()}
                self.runs[ident]=answer
            elif operation=='upload':
                answer={'asset_id':ident,'revision':hashlib.sha256(raw).hexdigest(),'name':body['name'],'can_share':True,
                        'acquisition':{'attribution':body['attribution']},'permitted_audience':body['audience'],'recipients':[owner],'reuse_recipients':[owner]}
                self.uploads[ident]=answer
            elif operation=='original':
                run=self.runs[body['id']]
                return 200,{'representation':'retained-original','source':run['input'],'sha256':run['input_sha256'],'payload_base64':base64.b64encode(self.original).decode()}
            elif operation=='read':return 200,copy.deepcopy(self.view)
            elif operation=='publish':
                run=self.runs[body['id']];digest=hashlib.sha256(json_bytes(body)).hexdigest()
                if run['state']=='published':
                    return (200,copy.deepcopy(run)) if run['output_digest']==digest else (400,{'error':'Run already has different publication'})
                values=list(self.view['values']);derived=body.get('derived_curves',[])
                for change in body.get('changes',[]):values[change['index']]=change['value']
                header='~Version\nVERS. 2.0\nWRAP. NO\n~Well\nNULL. -999.25\n~Curve\nDEPT.M : Depth\nGR.gAPI : Gamma ray\n'
                for curve in derived:header+=curve['mnemonic']+'.'+curve['unit']+' : '+curve['description']+'\n'
                lines=[]
                for index,(depth,value) in enumerate(zip(self.view['axis'],values)):
                    row=[depth,value]+[curve['values'][index] for curve in derived]
                    lines.append(' '.join(str(-999.25 if value is None else value) for value in row))
                payload=(header+'~ASCII\n'+'\n'.join(lines)+'\n').encode();sha=hashlib.sha256(payload).hexdigest()
                manifest={'schema':'ophiolite.derived-curves-result/1' if derived else 'ophiolite.edit-result/1','parent':run['input'],
                          'media_type':'application/x-las','bytes':len(payload),'sha256':sha,'report':{}}
                manifest['appended' if derived else 'changes']=derived or body['changes']
                receipt={'destination':'portable','upstream_write':False,'publication_id':run['id'],'identity':owner,
                         'output_reference':{'authority':'ophiolite:derived','key':run['id'],'revision':sha},'manifest':manifest}
                run.update(state='published',receipt=receipt,output_digest=digest,published=time.time());self.results[run['id']]=payload
                self.mutations['publish']=self.mutations.get('publish',0)+1
                return 200,copy.deepcopy(run)
            elif operation in ('download','result-download'):
                run=self.runs[body['id']];answer={**run['receipt'],'payload_base64':base64.b64encode(self.results[run['id']]).decode()}
                if operation=='result-download':answer['run']=run
                return 200,copy.deepcopy(answer)
            elif operation=='share':
                ident=body.get('asset_id',body.get('id'));generation=self.generations.get(ident,1)
                if self.conditional and body.get('expected_generation') is None:  # E7 cutover: as the server does
                    return 428,{'error':'Reload who can see this and share again with the version you saw','code':'condition-required'}
                if self.conditional:
                    command,digest=body.get('command_id'),json.dumps([sorted(body['audience']),sorted(body.get('reuse_audience',[]))])
                    last=self.share_commands.get(ident)
                    if command and last and last[0]==command:
                        if last[1]!=digest:return 409,{'error':'This sharing request was already used for different recipients','code':'recipients-changed'}
                        return 200,self.summary(ident)
                    if body['expected_generation']!=generation:return 409,{'error':'Recipients changed; reload before saving','code':'recipients-changed'}
                    self.share_commands[ident]=(command,digest)
                self.audiences[ident]=(body['audience'],body.get('reuse_audience',[]));self.generations[ident]=generation+1
                self.mutations['share']=self.mutations.get('share',0)+1
                return 200,self.summary(ident)
            elif operation=='result-list':return 200,{'results':[self.summary(ident) for ident in self.results]}
            elif operation=='info':return 200,self.summary(body['asset_id'])
            elif operation=='members':return 200,{'members':['alice','bob']}
            elif operation in ('list','options'):return 200,{'bindings':list(self.bindings.values()),'runs':list(self.runs.values()),'inputs':[],'assets':[]}
            else:return 404,{'error':'Fixture operation unavailable'}
            self.commands[key]=(fingerprint,copy.deepcopy(answer));self.mutations[operation]=self.mutations.get(operation,0)+1
            return 200,copy.deepcopy(answer)
        except (KeyError,ValueError,TypeError,StopIteration):return 400,{'error':'Invalid synthetic fixture request'}
    def _publication(self,operation,path,raw,headers,owner):
        """E31: publications/derive (an exact file with its declared method, idempotent per command id), info and share."""
        import copy,hashlib,time
        if operation=='derive':
            extra=next(v for k,v in headers.items() if k.lower()=='x-ophiolite-upload')
            body=json.loads(base64.b64decode(extra,validate=True))
            if body['project_id']!='p':return 403,{'error':'project unavailable'}
            if hashlib.sha256(raw).hexdigest()!=body['output_sha256'] or len(raw)!=body['output_bytes']:return 400,{'error':'The file differs from its declared digest or length'}
            key=('derive',owner,body['command_id']);fingerprint=hashlib.sha256(extra.encode()+raw).hexdigest()
            if key in self.commands:
                prior,answer=self.commands[key]
                return (200,copy.deepcopy(answer)) if prior==fingerprint else (409,{'error':'This command id was already used for a different publication','code':'command-owned'})
            self.publications=getattr(self,'publications',{})
            parents=[{'authority':'ophiolite:derived','key':p['asset_id'],'revision':p['revision'],'profile':'las2/1'} for p in body['derived_from']]
            method={'script_sha256':None,**body['method']}
            head=None
            if body.get('new_version_of') is not None:  # E52: the server's append rules, in its order and words
                head=self.publications.get(body['new_version_of']);named=self.version_contributors
                permitted=head is not None and (head['owner']==owner or owner in named and head['owner'] in named)  # E70c: a mutual group
                if not permitted or head['receipt']['profile']!=body['profile']:
                    return 403,_envelope(("Only the author, or a member the project lets add versions to each other's results, can" if named else 'Only the author can')
                                         +' add a version to this result, of the same type','PERMISSION_DENIED')
                if head['owner']!=owner and not self.readable(body['new_version_of'],owner):return 403,_envelope('Result unavailable','PERMISSION_DENIED')
                if {p['key'] for p in parents}!={p['key'] for p in head['versions'][0]['parents']}:
                    return 403,_envelope('A new version must derive from the same lineage as the existing result','PERMISSION_DENIED')
                if body['output_sha256'] in [v['revision'] for v in head['versions']]:
                    return 409,_envelope('This content is already a version of the result','revision-conflict')
                if body.get('expected_parent')!=head['versions'][-1]['revision']:
                    return 409,_envelope('The result has a newer version; review it before adding another','revision-conflict')
            ident=body['new_version_of'] if head else hashlib.sha256(json.dumps(list(key)).encode()).hexdigest()  # 64 hex, as the server's
            number=len(head['versions'])+1 if head else 1
            answer={'asset_id':ident,'revision':body['output_sha256'],'revision_number':number,'profile':body['profile'],
                    'derived_from':parents,'method':method,'command_id':body['command_id']}
            version={'number':number,'revision':body['output_sha256'],'parent_revision':head['versions'][-1]['revision'] if head else None,'bytes':raw,
                     'method':method,'parents':parents,'by':owner,'published_at':time.time(),
                     'run_id':ident if not head else hashlib.sha256(json.dumps(list(key)+['version']).encode()).hexdigest()}
            self.commands[key]=(fingerprint,copy.deepcopy(answer))
            if head:head['versions'].append(version);head['receipt']=answer;head['bytes']=raw
            else:self.publications[ident]={'receipt':answer,'name':body['name'],'owner':owner,'bytes':raw,'versions':[version]}
            self.mutations['derive']=self.mutations.get('derive',0)+1
            return 200,copy.deepcopy(answer)
        body=json.loads(raw)
        if operation=='version-contributors':  # E70c: read by any member; the fixture's administrator is alice
            return 200,{'generation':0,'members':sorted(self.version_contributors),'can_change':owner=='alice',**({'eligible':['alice','bob']} if owner=='alice' else {})}
        ident=body.get('asset_id');item=getattr(self,'publications',{}).get(ident)
        if item is None:return 404,{'error':'Publication unavailable','code':'not-found'}
        if operation=='share':
            if body.get('expected_generation') is None:return 428,{'error':'Reload who can see this and share again with the version you saw','code':'condition-required'}
            whole=body.get('project_audience') if self.project_capable else None  # an older server ignores the field
            if whole not in (None,'read','none'):return 400,{'error':'project_audience must be read or none','code':'invalid-request'}
            command,digest=body.get('command_id'),json.dumps([sorted(body.get('audience',[])),sorted(body.get('reuse_audience',[])),whole])
            last=self.share_commands.get(ident)
            if not (command and last and last==(command,digest)):  # a replay of the applied command answers the current state
                if command and last and last[0]==command:return 409,{'error':'This sharing request was already used for different recipients','code':'recipients-changed'}
                if body['expected_generation']!=self.generations.get(ident,1):return 409,{'error':'Recipients changed; reload before saving','code':'recipients-changed'}
                self.share_commands[ident]=(command,digest)
                self.audiences[ident]=(body.get('audience',[]),body.get('reuse_audience',[]));self.generations[ident]=self.generations.get(ident,1)+1
                if whole is not None:self.project_audiences[ident]=whole
                self.mutations['publication-share']=self.mutations.get('publication-share',0)+1
        elif operation!='info':return 404,{'error':'Fixture operation unavailable'}
        read,reuse=self.audiences.get(ident,([],[]))
        read,reuse=sorted(set(read)|{item['owner']}),sorted(set(reuse)|{item['owner']})  # the author always keeps both, as the server answers
        answer={'asset_id':ident,'revision':item['receipt']['revision'],'name':item['name'],'owner':item['owner'],'can_share':item['owner']==owner,
                'permitted_audience':['alice','bob'],'recipients':read,'reuse_recipients':reuse,'grants_generation':self.generations.get(ident,1),
                'can_add_version':item['owner']==owner or owner in self.version_contributors and item['owner'] in self.version_contributors}
        if self.project_capable:answer['project_audience']=self.project_audiences.get(ident,'none') if item['owner']==owner else None
        if operation=='share':answer['sharing_contract']='conditional'
        return 200,answer

    def readable(self,ident,owner):
        item=getattr(self,'publications',{}).get(ident)
        whole=getattr(self,'project_audiences',{}).get(ident)=='read' and owner in ('alice','bob')  # E78: the fixture project's members
        return item if item and (owner==item['owner'] or whole or owner in self.audiences.get(ident,([],[]))[0]) else None

    def history(self,ident,owner):
        """E52: applications/result-history for a derived publication, as the server answers it."""
        item=self.readable(ident,owner)
        if item is None:return 404,_envelope('Result unavailable','not-found')
        rows=[{'number':v['number'],'revision':v['revision'],'parent_revision':v['parent_revision'],'published_at':v['published_at'],'by':v['by'],'via':None,
               'calculation':METHOD_WORDS.get(v['method'].get('name'),'Method declared by its publisher'),'application_version':None,'input':None,
               'run_id':v['run_id'],'stage':'draft'} for v in item['versions']]
        return 200,{'asset_id':ident,'head_revision':item['versions'][-1]['revision'],'count':len(rows),'revisions':rows,
                    'display':{'member_names':{v['by']:v['by'].capitalize() for v in item['versions']}}}

    def scientific(self,route,query,owner):
        """E52: the read-back of a derived publication: its descriptor (with `derivation`, `parents` and `history`), the
        exact file and the `curve:<mnemonic>` representation, as the server serves them. None when not a publication."""
        parts=route.split('/')
        if len(parts) not in (3,5) or parts[1]!='revisions':return None
        ident,revision=parts[0],parts[2]
        if ident not in getattr(self,'publications',{}):return None
        item=self.readable(ident,owner)
        version=next((v for v in item['versions'] if v['revision']==revision),None) if item else None
        if version is None:return 404,_envelope('No such revision.','not-found')
        las=read_las(version['bytes']);curve=(query.get('curve') or [''])[0]
        if len(parts)==5 and parts[3]=='representations' and parts[4]=='artifact':return 200,version['bytes']
        if curve not in las['curves'] or curve==las['index']:return 404,_envelope('Select the available curve.','not-found')
        normalized=_normalized(ident,version,las,curve)
        if len(parts)==5 and parts[3]=='representations' and parts[4]=='curve:'+curve:return 200,normalized
        if len(parts)!=3:return 404,_envelope('No such representation.','not-found')
        return 200,_descriptor(ident,item,version,las,curve,normalized,owner)

    def summary(self,ident):
        if ident in self.uploads:
            answer=dict(self.uploads[ident]);read,reuse=self.audiences.get(ident,(answer['recipients'],answer['reuse_recipients']))
            return {**answer,'recipients':read,'reuse_recipients':reuse,**self.generation(ident)}
        run=self.runs[ident];read,reuse=self.audiences.get(ident,([run['owner']],[run['owner']]))
        return {'asset_id':ident,'revision':run['receipt']['output_reference']['revision'],'id':ident,'name':run['binding']['name'],
                'owner':run['owner'],'input':run['input'],'curve':run['binding']['curve'],'receipt':run['receipt'],
                'can_share':True,'recipients':read,'reuse_recipients':reuse,'published':run['published'],**self.generation(ident)}

    def generation(self,ident):
        return {'grants_generation':self.generations.get(ident,1)} if self.conditional else {}


# --- E52: the synthetic server of the templates and the gallery, and the read-back of a derived publication ---------

METHOD_WORDS={'scipy.spatial.Delaunay':'Delaunay triangulation (SciPy)','scipy.interpolate.griddata':'Gridding by interpolation (SciPy)',
              'ophiolite.shale-volume':'Shale volume from gamma ray'}  # the server's words for documented method names
INTERPRETATION={'reader':'asset_connectors.las_reader/1','lasio_version':'0.32','mapping':'application-curve/1',
                'null_policy':'strict declared NULL; nonfinite samples mapped to null; wrapped rows use declared curve count','parsing_policy':'las2-strict-null/1'}


def _envelope(message,code):
    return {'error':message,'code':code,'message':message}


def read_las(raw):
    """The few facts of a LAS 2.0 file written by ophiolite.writers (or the synthetic original) the fixture serves:
    the NULL text, the curves with their units (the first is the depth index) and the rows. Not a general reader."""
    section='';null='-999.25';curves={};order=[];rows=[]
    for line in raw.decode('ascii').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        if line.startswith('~'):section=line[1].upper();continue
        if section=='W' and line.split('.',1)[0].strip()=='NULL':null=line.split('.',1)[1].split(':',1)[0].strip()
        elif section=='C':
            name,rest=line.split('.',1);name=name.strip();curves[name]=rest.split(' ',1)[0].split(':',1)[0].strip();order.append(name)
        elif section=='A':rows.append([float(v) for v in line.split()])
    marker=float(null)
    columns={name:[None if r[i]==marker else r[i] for r in rows] for i,name in enumerate(order)}
    return {'null':null,'index':order[0],'curves':curves,'columns':columns}


def _normalized(ident,version,las,curve):
    value={'schema':'ophiolite.application-curve/1','representation':'normalized','axis':las['columns'][las['index']],'values':las['columns'][curve],
           'curve':curve,'unit':las['curves'][curve],
           'context':{'depth_index':las['index'],'depth_unit':las['curves'][las['index']],'depth_reference':'source declared; not inferred',
                      'missing_value_marker':las['null'],'missing_value_policy':'Declared LAS NULL marker; missing samples are not zero'},
           'source':{'authority':'ophiolite:derived','key':ident,'revision':version['revision'],'profile':'las2/1'},'source_sha256':version['revision'],
           'interpretation':dict(INTERPRETATION)}
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _descriptor(ident,item,version,las,curve,normalized,owner):
    """The server's descriptor of one revision of a derived publication, without its revision manifest and display words."""
    import hashlib,time
    axis=las['columns'][las['index']];values=las['columns'][curve]
    order='insufficient' if len(axis)<2 else 'increasing' if all(a<b for a,b in zip(axis,axis[1:])) else 'decreasing' if all(a>b for a,b in zip(axis,axis[1:])) else 'unordered'
    scientific={'curve':curve,'unit':las['curves'][curve],'unit_status':'declared','axis_unit':las['curves'][las['index']],'axis_unit_status':'declared',
                'depth_reference':'source declared; not inferred','sample_count':len(axis),'axis_order':order,'axis_duplicates':len(set(axis))!=len(axis),
                'missing_count':sum(v is None for v in values),'missing_value_marker':las['null']}
    output=((version['method'].get('parameters') or {}).get('outputs') or {}).get(curve)
    if output and output.get('quantity') in _quantities():scientific.update(quantity=output['quantity'],quantity_status='declared')
    allowed=['read','export','use-as-input']
    return {'schema':'ophiolite.scientific-asset/1','asset_id':ident,'revision':version['revision'],'project_id':'p','authority':'ophiolite:derived',
            'origin':'managed-derived','custodian':'ophiolite:managed','source_reference':None,'profile':'las2/1','scientific':scientific,
            'interpretation':dict(INTERPRETATION),'interpretation_evidence':'recorded','recorded_interpretation':dict(INTERPRETATION),
            'representations':[{'id':'artifact','kind':'derived-artifact','media_type':'application/x-las','profile':'las2/1','bytes':len(version['bytes']),
                                'sha256':version['revision'],'available':True,'losses':[]},
                               {'id':'curve:'+curve,'kind':'normalized','media_type':'application/json','profile':'ophiolite.application-curve/1',
                                'bytes':len(normalized),'sha256':hashlib.sha256(normalized).hexdigest(),'available':True,
                                'losses':['LAS formatting is represented by the exact artifact, not normalized JSON']}],
            'retention':{'mode':'retained','policy':'No automatic eviction; current distribution rights required','historical_reads':'while-retained-and-authorized'},
            'parents':[dict(p) for p in version['parents']],'parent_visibility':'complete',
            'provenance':{'evidence':'script-declared','method':version['method'].get('name'),'code_reference':None,'environment_reference':None,
                          'omissions':['Code and execution environment were not captured']},
            'supported_operations':allowed,
            'authorization':{'status':'evaluated','evaluated_for':owner,'evaluated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'allowed_operations':allowed},
            'history':{'number':version['number'],'count':len(item['versions']),'head_revision':item['versions'][-1]['revision'],'parent_revision':version['parent_revision']},
            'derivation':{'method':dict(version['method'])}}


def _quantities():
    import importlib.resources
    return {q['name'] for q in json.loads(importlib.resources.files('ophiolite').joinpath('contracts/vocabulary/v1/quantities.json').read_bytes())['quantities']}


# Synthetic wells (E31 map-application): two located by a source you may read, one without a location.
WELLS = [{'entity_id':'well-synthetic-1','kind':'well','name':'Synthetic well 1','owner':'alice','generation':1,
          'location':{'x':5.1,'y':52.1,'crs':'OGC:CRS84','source':{'asset_id':'wells-table','revision':'r1','profile':'ophiolite/sql-table/1','row':'1'},'elevation_reference':'unknown'}},
         {'entity_id':'well-synthetic-2','kind':'well','name':'Synthetic well 2','owner':'alice','generation':1,
          'location':{'x':6.2,'y':52.9,'crs':'OGC:CRS84','source':{'asset_id':'wells-table','revision':'r1','profile':'ophiolite/sql-table/1','row':'2'},'elevation_reference':'unknown'}},
         {'entity_id':'well-synthetic-3','kind':'well','name':'Synthetic well 3','owner':'alice','generation':1,'location':None}]


@contextmanager
def synthetic_server():
    """The templates' and the gallery's synthetic server: one synthetic gamma-ray log (curve-a), the application journal,
    derived publications with versions, and their read-back. Loopback only; never a production fallback."""
    from . import validate
    root = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
    descriptor = json.loads(root.joinpath('source.json').read_bytes())
    descriptor['project_id'] = 'p'
    raw = root.joinpath('curve.json').read_bytes()
    original = root.joinpath('original.las').read_bytes()
    validate.pair(descriptor, raw)
    server = fixture_server()
    applications = server.handler
    faults = {}
    prefix = '/api/v1/projects/p/scientific-assets'
    exact = prefix + '/' + descriptor['asset_id'] + '/revisions/' + descriptor['revision']
    summary = {key: descriptor[key] for key in ('asset_id','revision','origin','authority','profile','custodian')}
    summary.update(name='Synthetic gamma ray', curves=['GR'], sample_count=5, allowed_operations=['read','export','use-as-input'])

    def handler(method, path, body, headers):
        token = next((v for k,v in headers.items() if k.lower() == 'authorization'), '')
        if token == 'Bearer expired' or faults.get('expired'): return 401, {'error':'Sign in again.'}
        if faults.get('revoked'): return 403, {'error':'Access has been revoked.'}
        if faults.get('busy'): return 503, {'error':'Service is busy.'}
        if faults.get('capacity'): return 413, {'error':'Supported size exceeded.'}
        if path.endswith('/share') and faults.pop('recipients_changed', None):
            # Someone else changed the recipients after this client read them.
            ident = json.loads(body).get('id') or json.loads(body).get('asset_id')
            applications.generations[ident] = applications.generations.get(ident, 1) + 1
        parsed = urlsplit(path)
        route = unquote(parsed.path)
        if method == 'GET':
            if not token: return 401, {'error':'Sign in again.'}
            if route == prefix: return 200, {'items':[summary], 'next_cursor':None}
            if route == exact:
                if parse_qs(parsed.query).get('curve') != ['GR']: return 404, {'error':'Select the available curve.'}
                changed = json.loads(json.dumps(descriptor))
                if faults.get('changed_input'): changed['revision'] = 'changed'
                return 200, changed
            if route == exact + '/representations/las': return 200, original
            if route == exact + '/representations/curve': return 200, raw
            if route.startswith(prefix + '/'):  # E52: a derived publication made against this server
                found = applications.scientific(route[len(prefix) + 1:], parse_qs(parsed.query), _owner(token))
                if found is not None: return found
            return 404, {'error':'No such synthetic revision.'}
        if method == 'POST' and route.endswith(('/entities/list', '/entities/extent')):  # E31: the synthetic wells a map shows
            if not token: return 401, {'error':'Sign in again.'}
            request = json.loads(body or b'{}')
            if route.endswith('/entities/extent'): return 200, {'crs':request.get('crs','OGC:CRS84'),'bbox':[5.1,52.1,6.2,52.9],'count':2,'untransformed':0}
            return 200, {'entities':[dict(well, location=dict(well['location'], crs=request.get('crs') or 'OGC:CRS84') if well['location'] else None) for well in WELLS],
                         'next_cursor':None,'untransformed':0}
        return applications(method,path,body,headers)

    server.handler = handler
    # Public fixture controls are intentionally separate from all product responses.
    server.template_faults = faults
    server.template_mutations = applications.mutations
    server.template_applications = applications  # E78: who may read a publication, for tests
    server.template_descriptor = descriptor
    with server:
        yield server


def _owner(token):
    return token.removeprefix('Bearer ').removeprefix('oph_api_').removeprefix('provider-').split(':')[0]


if __name__=='__main__':
    import argparse,threading
    parser=argparse.ArgumentParser(description='Synthetic SDK application fixture, loopback only')
    parser.add_argument('--drop-response-after',choices=['configure','start','publish','upload','share'])
    options=parser.parse_args()
    with fixture_server(drop_response_after=options.drop_response_after) as server:
        print(server.url,flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:pass
