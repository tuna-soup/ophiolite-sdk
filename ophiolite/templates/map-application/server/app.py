"""Loopback map backend: the Python SDK holds the credential; the browser gets wells as GeoJSON, never a token."""
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
from support import client_for,synthetic_server,guidance
from ophiolite.errors import OphioliteError,Refused


class Backend:
    """The map's backend: it holds the Ophiolite credential and answers the browser with wells and their extent.
    The browser never sees a token; it proves each request with the per-start proof."""
    def __init__(self,client,folder,frontend_origin,fixture=None):
        parsed=urlsplit(frontend_origin)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('Configure an exact loopback frontend origin including its port.')
        self.client,self.folder,self.origin,self.fixture=client,Path(folder),frontend_origin,fixture
        self.frontend_host=parsed.netloc
        self.proof=secrets.token_urlsafe(32)
        self.lock=threading.RLock()

    def execute(self,path,body):
        if path=='/api/extent':
            extent=self.client.extent('OGC:CRS84')
            return {'bbox':extent['bbox'],'count':extent['count'],'untransformed':extent['untransformed']}
        if path=='/api/wells':
            wells=self.client.wells(crs='OGC:CRS84')
            collection=wells.to_geojson()
            for feature,well in zip(collection['features'],wells):  # what the popup's Technical details may show
                source=(well.location or {}).get('source') or {}
                feature['properties'].update(source_asset_id=source.get('asset_id'),source_revision=source.get('revision'),source_row=source.get('row'))
            return {'wells':collection,'unlocated':sum(1 for w in wells if not w.location)}
        if path=='/api/_test' and self.fixture is not None:
            if body.get('clear'):self.fixture.template_faults.clear()
            if body.get('fault'):self.fixture.template_faults[body['fault']]=True
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
        directory=stack.enter_context(tempfile.TemporaryDirectory(prefix='ophiolite-map-'))
        state=Backend(client,Path(directory)/'work',args.frontend,fixture)
        server=make_server(state,args.port)
        print('Local application backend ready.',flush=True)
        try:server.serve_forever()
        finally:server.server_close()

if __name__=='__main__':main()
