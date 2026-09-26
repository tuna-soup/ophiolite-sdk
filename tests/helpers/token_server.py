"""Synthetic rotating provider with explicit scheduling observations; no real tokens."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs


class TokenServer:
    def __init__(self):
        self.requests=[];self.lock=threading.Lock();self.first=threading.Event()
        self.second=threading.Event();self.release=threading.Event()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                with owner.lock:
                    owner.requests.append(body);number=len(owner.requests)
                    (owner.first if number==1 else owner.second).set()
                owner.release.wait(5)
                value=({'access_token':'rotated-access','refresh_token':'rotated-refresh','expires_in':300}
                       if number==1 else {'error':'invalid_grant'})
                raw=json.dumps(value).encode();self.send_response(200 if number==1 else 400)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join(3)
