"""Loopback template backend. Credential ownership stays in the Python SDK."""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import quote,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from support import client_for,synthetic_server,stage,validate_stage,publish_stage,share_after_read,guidance
from ophiolite.errors import OphioliteError,ValidationFailed,Refused


class Backend:
    def __init__(self,client,folder,frontend_origin,fixture=None):
        parsed=urlsplit(frontend_origin)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('Configure an exact loopback frontend origin including its port.')
        self.client,self.folder,self.origin,self.fixture=client,Path(folder),frontend_origin,fixture
        self.frontend_host=parsed.netloc
        self.proof=secrets.token_urlsafe(32)
        self.lock=threading.RLock()
        self.staged=None;self.receipt=None

    def execute(self,path,body):
        if path=='/api/list':return {'assets':list(self.client.assets())}
        if path=='/api/read':
            data=self.client.read(body['asset_id'],body['revision'],[body['curve']])
            _,descriptor=data.to_numpy()
            return {'descriptor_html':data._repr_html_(),'axis':data.curves[0].axis,'values':data.curves[0].values,'unit':data.curves[0].unit,'depth_unit':descriptor.axis.unit,'workspace_url':data.workspace_url()}
        if path=='/api/stage':
            if self.staged is not None:raise Refused('A calculation is already staged. Validate it before publishing.')
            self.staged=stage(self.client,self.folder,mnemonic=body['mnemonic'],asset={'asset_id':body['asset_id'],'revision':body['revision']},curve=body['curve'])
            return {'message':'Calculation staged locally. Review and validate before publishing.'}
        if path=='/api/validate':
            if self.staged is None:raise Refused('Stage a calculation first.')
            self.staged['curves'][0]['mnemonic']=body['mnemonic']
            validate_stage(self.staged)
            return {'valid':True,'message':'The selected calculation satisfies the supported publication checks.'}
        if path=='/api/publish':
            if self.staged is None:raise Refused('Stage and validate a calculation first.')
            self.receipt=publish_stage(self.staged)
            output=self.receipt.output_reference;curve=self.staged['curves'][0]['mnemonic']
            link=self.client.url+'/project/'+quote(self.client.project,safe='')+'/asset/'+quote(output.key,safe='')+'?revision='+quote(output.revision,safe='')+'&kind=scientific&curve='+quote(curve,safe='')
            return {'message':'The derived result is saved. The original is unchanged.','workspace_url':link,'receipt':self.receipt.model_dump(by_alias=True)}
        if path=='/api/share':
            if self.receipt is None:raise Refused('Publish a result before sharing it.')
            return share_after_read(self.client,self.receipt,body['audience'])
        if path=='/api/_test' and self.fixture is not None:
            if body.get('clear'):self.fixture.template_faults.clear()
            if body.get('fault'):self.fixture.template_faults[body['fault']]=True
            if body.get('drop_share'):self.fixture.drop('share',1)
            return {'mutations':dict(self.fixture.template_mutations)}
        raise Refused('This example does not provide that operation.')


def make_server(state,port=56111):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            raw=json.dumps(value,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.reply(405,{'message':'Use an explicit POST request for this example API.'})
        def do_OPTIONS(self):self.reply(403,{'message':'Cross-origin requests are not permitted.'})
        def do_POST(self):
            hosts={state.frontend_host,'127.0.0.1:'+str(self.server.server_port)}
            if len(self.headers.get_all('Host',[]))!=1 or self.headers.get('Host') not in hosts:
                self.reply(403,{'message':'The request host is not permitted.'});return
            if len(self.headers.get_all('Origin',[]))!=1 or self.headers.get('Origin')!=state.origin:
                self.reply(403,{'message':'Open this application on its configured local address.'});return
            if self.path=='/api/bootstrap':
                if self.headers.get('X-Ophiolite-Bootstrap')!='1' or self.headers.get('Sec-Fetch-Site')!='same-origin':
                    self.reply(403,{'message':'Start from the local application page.'});return
                self.reply(200,{'proof':state.proof});return
            supplied=self.headers.get('X-Ophiolite-Proof','')
            if len(self.headers.get_all('X-Ophiolite-Proof',[]))!=1 or not hmac.compare_digest(supplied.encode(),state.proof.encode()):
                self.reply(403,{'message':'Reload the local application to start a new session.'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=64*1024:
                    self.reply(413,{'message':'The request is too large or empty.'});return
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ValueError('Expected JSON object')
                with state.lock:result=state.execute(self.path,body)
                self.reply(200,result)
            except ValidationFailed as error:self.reply(422,{'message':'Correct the calculation before publishing.','violations':list(error.violations)})
            except OphioliteError as error:self.reply(error.status or 400,{'message':error.message if isinstance(error,Refused) else guidance(error)})
            except (KeyError,ValueError,TypeError):self.reply(400,{'message':'Supply the required fields for this action.'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',action='store_true');parser.add_argument('--port',type=int,default=56111);parser.add_argument('--frontend',default='http://127.0.0.1:56110');args=parser.parse_args()
    with ExitStack() as stack:
        fixture=stack.enter_context(synthetic_server()) if args.fixture else None
        url=fixture.url if fixture else os.environ['OPHIOLITE_URL'];project='p' if fixture else os.environ['OPHIOLITE_PROJECT']
        client=stack.enter_context(client_for(url,project,fixture=fixture is not None))
        directory=stack.enter_context(tempfile.TemporaryDirectory(prefix='ophiolite-react-')) if args.fixture else os.environ['OPHIOLITE_WORK']
        state=Backend(client,Path(directory)/'work',args.frontend,fixture)
        server=make_server(state,args.port)
        print('Local application backend ready.',flush=True)
        try:server.serve_forever()
        finally:server.server_close()

if __name__=='__main__':main()
