"""E125 s3a: a well path given as positions is uploaded and read back by a separate Python process that uses only the
public SDK, against the in-process gateway served over local HTTP (status, headers and bytes passed through as they
are). Expected values are the literals of the strategy's §6, not the reader's output."""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_well_imports import TOKEN  # the in-process gateway's fixture credential, passed in the environment

CSV = b'md,x,y,tvdss\n0,1000.0,2000.0,50.0\n150,1000.0,2000.0,-12.5\n400.5,1003.25,2010.5,300.25\n800,1010.0,2030.0,610.75\n1100.25,1020.5,2055.25,480.5\n'
DECLARED = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'depth_unit': 'm', 'md_reference': 'KB', 'tvdss_datum': 'MSL'}
STATIONS = [{'md': 0.0, 'x': 1000.0, 'y': 2000.0, 'tvdss': 50.0}, {'md': 150.0, 'x': 1000.0, 'y': 2000.0, 'tvdss': -12.5},
            {'md': 400.5, 'x': 1003.25, 'y': 2010.5, 'tvdss': 300.25}, {'md': 800.0, 'x': 1010.0, 'y': 2030.0, 'tvdss': 610.75},
            {'md': 1100.25, 'x': 1020.5, 'y': 2055.25, 'tvdss': 480.5}]
CHILD = '''
import json, os, sys
from ophiolite import Client, Credential
client = Client(sys.argv[1], 'p', Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY']))
raw = open(sys.argv[2], 'rb').read()
upload = client.upload_data(raw, profile='well-path-positions-csv/1', name='F3 well path', filename='path.csv', declared=json.loads(sys.argv[3]),
                            attribution='Synthetic', audience=[], rights_confirmed=True, command_id='e125s3a-child')
path = client.read_data(upload.asset_id, upload.revision)
print(json.dumps({'class': type(path).__name__, 'original': path.original == raw, 'stations': path.stations, 'context': path.context}))
'''


def serve(web):
    """Forward each request to the in-process gateway and its answer back unchanged."""
    class Handler(BaseHTTPRequestHandler):
        def handle_one(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
            answer = web.c.request(self.command, self.path, content=raw, headers=headers)
            self.send_response(answer.status_code)
            for key, value in answer.headers.items():
                if key.lower() not in ('content-length', 'connection', 'transfer-encoding', 'date', 'server'): self.send_header(key, value)
            self.send_header('Content-Length', str(len(answer.content))); self.end_headers(); self.wfile.write(answer.content)
        do_GET = do_POST = handle_one
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_well_path_upload_and_read_in_a_separate_process(web, tmp_path):
    (tmp_path / 'path.csv').write_bytes(CSV)
    server = serve(web)
    try:
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(p for p in sys.path if p), 'HOME': str(tmp_path), 'OPHIOLITE_ACCESS_KEY': TOKEN}
        done = subprocess.run([sys.executable, '-c', CHILD, 'http://127.0.0.1:%d' % server.server_port, str(tmp_path / 'path.csv'),
                               json.dumps(DECLARED)], env=env, capture_output=True, text=True, timeout=120)
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    assert (answer['class'], answer['original'], answer['stations']) == ('WellPath', True, STATIONS)
    context = answer['context']
    assert {k: context[k] for k in DECLARED} == DECLARED and context['type'] == 'well-path'
    assert (context['count'], context['md_range'], context['tvdss_range']) == (5, [0.0, 1100.25], [-12.5, 610.75])
    assert context['fidelity']['unknown_context'] == []
