"""Explicit fixture transport; never installed as a production fallback."""
import base64
import json
from pathlib import Path
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
                ident=body.get('asset_id',body.get('id'));self.audiences[ident]=(body['audience'],body.get('reuse_audience',[]))
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
    def summary(self,ident):
        if ident in self.uploads:
            answer=dict(self.uploads[ident]);read,reuse=self.audiences.get(ident,(answer['recipients'],answer['reuse_recipients']))
            return {**answer,'recipients':read,'reuse_recipients':reuse}
        run=self.runs[ident];read,reuse=self.audiences.get(ident,([run['owner']],[run['owner']]))
        return {'asset_id':ident,'revision':run['receipt']['output_reference']['revision'],'id':ident,'name':run['binding']['name'],
                'owner':run['owner'],'input':run['input'],'curve':run['binding']['curve'],'receipt':run['receipt'],
                'can_share':True,'recipients':read,'reuse_recipients':reuse,'published':run['published']}


if __name__=='__main__':
    import argparse,threading
    parser=argparse.ArgumentParser(description='Synthetic SDK application fixture, loopback only')
    parser.add_argument('--drop-response-after',choices=['configure','start','publish','upload','share'])
    options=parser.parse_args()
    with fixture_server(drop_response_after=options.drop_response_after) as server:
        print(server.url,flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:pass
