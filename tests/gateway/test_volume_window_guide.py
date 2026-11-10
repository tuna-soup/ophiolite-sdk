"""E141 s3 C3 (acceptance 8; D-G): the guide "Read part of a volume" executed as written. Every fenced block of
web/docs/.../guides/read-part-of-a-volume.md runs against the real-credential gateway (`test_service_accounts.p`)
served on a loopback port by uvicorn in a thread, on a project access key or a service account's key made through
the gateway's routes:

- the curl blocks under `bash -euo pipefail` (the controller's /usr/bin/curl, jq and sha256sum);
- the standard-library block under `python -I -S`, where `import ophiolite` is proved to fail;
- the SDK blocks through `conformance/tasks/recipes.run` with `client` on the key;
- the command-line block as a real subprocess of this environment's `ophiolite` entry point, and the segyio block on
  the file it wrote (segyio 1.9.14 from the dev extra, unguarded).

Each block's printed values (or the file segyio reads) are compared with the journeys.json window literals and each
computed digest with the row's `wire_sha256`, never with another path's output. The verification contract (R1-10,
R1-12): a proxy between the server and the unchanged curl and stdlib recipes serves a wrong revision header, a wrong
window header, a missing piece, a repeated piece, a truncated body (with its digest restated) and a stale digest; each
recipe exits non-zero naming the check. A spy on the server sees every path: no block asks for
`representations/artifact`. Fixtures are synthetic (D75): the s0 cube (IBM and IEEE) and line, and C1's long-read
volume with its piece bound of 512 bytes."""
import contextlib
import hashlib
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import segyio  # test-only, unguarded: the SDK gateway lane installs it from [dev]

from project_gateway.tests.real_credentials import ORIGIN, project as credentials  # noqa: F401 (fixture)
from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
from project_gateway.tests.test_service_accounts import p  # noqa: F401 (fixture)
from project_gateway.tests import test_volume_window_long_reads as platform
from project_gateway.tests.test_volume_window_long_reads import long as long_server  # noqa: F401 (fixture)
from project_gateway.tests.test_volume_window_contract import cube_bytes, line_bytes, CUBE
from project_gateway.tests.test_volume_window_read import share
from project_gateway.tests.test_upload_sessions import begin, send, finished, ref
from ophiolite import Client, Credential
from ophiolite import volume_windows as svw

REPO = Path(__file__).resolve().parents[3]
GUIDE = REPO / 'web/docs/src/content/docs/guides/read-part-of-a-volume.md'
PAGE = GUIDE.name
JOURNEYS = json.loads((REPO / 'ophiolite-platform/services/project_gateway/tests/fixtures/volume_window/journeys.json').read_text())
WINDOWS = JOURNEYS['windows']
ROWS = {r['id']: r for r in JOURNEYS['journeys']}
BLOCK = re.compile(r'<!-- journey: ([a-z0-9-]+) -->\n```(bash|python)\n(.*?)```', re.S)
BLOCKS = {row: (language, code) for row, language, code in BLOCK.findall(GUIDE.read_text(encoding='utf-8'))}
PYTHON_BLOCKS = [row for row, (language, _) in BLOCKS.items() if language == 'python']  # recipes.run's block order
STDLIB = [sys.executable, '-I', '-S']  # no site-packages, no PYTHON* variables, no current directory on the path
VENV_BIN = Path(sys.executable).parent
CODES = {'ibm': 1, 'ieee': 5}
EXACT_STARTS = [17.0, 19.5, 22.0]  # block-exact's sample times: 12 ms + 2.5 ms x positions 2..4 (test_exchange_window.STARTS)

# the test that runs each block as written (test_volume_window_journeys checks it covers every block, none skipped)
RUNS = {'http-plain-window': 'test_the_document_block_answers_each_windows_axes',
        'http-curl-window': 'test_the_curl_and_stdlib_blocks_read_each_windows_literals',
        'http-stdlib-window': 'test_the_curl_and_stdlib_blocks_read_each_windows_literals',
        'sdk-read-window': 'test_the_sdk_block_reads_the_literals_on_a_key_and_never_the_original',
        'exchange-get-window': 'test_the_command_line_block_writes_a_file_the_segyio_block_reads_as_the_literals',
        'segyio-reads-window': 'test_the_command_line_block_writes_a_file_the_segyio_block_reads_as_the_literals',
        'long-read-personal-key': 'test_the_long_read_blocks_read_all_three_pieces_on_each_key',
        'long-read-service-key': 'test_the_long_read_blocks_read_all_three_pieces_on_each_key'}


def recipes():
    """conformance/tasks/recipes.py, the executor the conformance task runs the SDK block with. The repository root is
    on the path only while it is imported (it is not on the SDK lane's path)."""
    sys.path.append(str(REPO))
    try:
        from conformance.tasks import recipes as module
    finally:
        sys.path.remove(str(REPO))
    return module


def run_python_block(row, client, workdir, given):
    i = PYTHON_BLOCKS.index(row)
    return recipes().run(PAGE, client, workdir, given=given, start=i, end=i + 1)


# --- the loopback server and its spy ---------------------------------------------------------------------------------

def spied(app, log):
    """APP, recording (path, which credential) for every request; the credential as a short digest, never the key. It
    stands where a deployment's front proxy stands: the request reaches the gateway with the public Host the world was
    built for (`real_credentials.ORIGIN`), as a proxy forwards it."""
    host = urllib.parse.urlsplit(ORIGIN).netloc.encode()

    async def wrapper(scope, receive, send):
        if scope['type'] == 'http':
            auth = dict(scope['headers']).get(b'authorization', b'')
            log.append((scope['path'], hashlib.sha256(auth[7:]).hexdigest()[:12] if auth.startswith(b'Bearer ') else None))
            scope = {**scope, 'headers': [(k, host if k == b'host' else v) for k, v in scope['headers']]}
        await app(scope, receive, send)
    return wrapper


def who(key):
    return hashlib.sha256(key.encode()).hexdigest()[:12]


@contextlib.contextmanager
def served(app, log):
    """The gateway on a loopback port (uvicorn in a thread, as conformance/roundtrip/live_target.py); yields its origin."""
    import uvicorn
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(spied(app, log), access_log=False, log_level='warning', timeout_keep_alive=5, lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True, name='e141s3-guide-gateway')
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, 'the loopback gateway did not start'
        time.sleep(0.05)
    try:
        yield 'http://127.0.0.1:%d' % sock.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def landed(p, raw, command, profile='segy/1'):
    """A synthetic volume or line sent through the upload sessions by alice, published and shared with bob."""
    sessions, token = p.sources.upload_sessions, p.tokens['alice']
    sessions.disk = lambda _: SimpleNamespace(free=10 ** 12)
    view = begin(sessions, raw, token, command, profile=profile)
    send(sessions, raw, view, user=token)
    assert finished(sessions, view, token)['state'] == 'checked'
    info = sessions.publish({**ref(view), 'name': command, 'attribution': 'Synthetic test', 'audience': ['alice', 'bob'], 'rights_confirmed': True}, token)
    share(SimpleNamespace(p=p, info=info), ['bob'])
    return info


@pytest.fixture
def guide(p):
    """The s0 cube (IBM, IEEE) and line at the deployment's own piece bound, bob's project access key, the server."""
    infos = {'ibm': landed(p, cube_bytes('ibm'), 'guide-cube-ibm'), 'ieee': landed(p, cube_bytes('ieee'), 'guide-cube-ieee'),
             'line': landed(p, line_bytes(), 'guide-line', 'segy-line/1')}
    key = platform.personal(SimpleNamespace(p=p))['key']
    log = []
    with served(p.app, log) as origin:
        yield SimpleNamespace(p=p, infos=infos, key=key, log=log, origin=origin)


@pytest.fixture
def long(long_server, monkeypatch):
    """C1's long-read volume (3 pieces of 512 bytes) served on loopback; the SDK's piece bound lowered with the server's."""
    monkeypatch.setattr(svw, 'BYTES_MAX', platform.PIECE)
    log = []
    with served(long_server.p.app, log) as origin:
        yield SimpleNamespace(server=long_server, info=long_server.info, log=log, origin=origin)


def environment(origin, key, info, window='', home=None):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'OPHIOLITE_'))}
    return {**clean, 'HOME': str(home or clean.get('HOME', '/tmp')), 'PATH': str(VENV_BIN) + os.pathsep + clean.get('PATH', ''),
            'OPHIOLITE_URL': origin, 'OPHIOLITE_PROJECT': 'p', 'OPHIOLITE_ACCESS_KEY': key,
            'ASSET': info['asset_id'], 'REVISION': info['revision'], 'WINDOW': window}


def bash(row, env, cwd):
    return subprocess.run(['bash', '-euo', 'pipefail', '-c', BLOCKS[row][1]], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def stdlib(env, cwd):
    return subprocess.run(STDLIB + ['-c', BLOCKS['http-stdlib-window'][1]], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def query(name):
    return '&'.join('%s=%s' % (k, v) for k, v in WINDOWS[name]['query'])


def cases(row):
    """(window, kind, info key) for every window of ROW: a volume window on both cubes, a line window on the line."""
    return [(name, kind, kind if WINDOWS[name]['geometry'] == 'volume' else 'line')
            for name in ROWS[row]['windows'] for kind in (('ibm', 'ieee') if WINDOWS[name]['geometry'] == 'volume' else ('ieee',))]


def nested_sha256(values):
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def originals(log):
    return [path for path, _ in log if path.endswith('/representations/artifact')]


# --- the blocks, each against its literals ---------------------------------------------------------------------------

def test_the_document_block_answers_each_windows_axes(guide, tmp_path):
    """Section 1's curl asks for the document only: its labels and sample positions are each window's literals."""
    for name, kind, at in cases('http-plain-window'):
        done = bash('http-plain-window', environment(guide.origin, guide.key, guide.infos[at], query(name)), tmp_path)
        assert done.returncode == 0, (name, done.stdout[-300:], done.stderr)
        d, w = json.loads(done.stdout), WINDOWS[name]
        axes = {a['name']: a for a in d['axes']}
        assert {n: axes[n]['labels'] for n in w['labels']} == w['labels'], name
        if w['at'] != 'all': assert list(range(axes['sample']['first'], axes['sample']['last'] + 1)) == w['at']['sample'], name
        assert (d['schema'], d['samples']['format_code']) == ('ophiolite.volume-window/1', CODES[kind]), name
    assert originals(guide.log) == []


def test_the_curl_and_stdlib_blocks_read_each_windows_literals(guide, tmp_path):
    """The curl block prints the computed digest, the stdlib block the values and the digest: each equals the window's
    literal. Mutations: two axes swapped in the stdlib decoder (values red); the IBM bias given as 63 (IBM values red)."""
    for row in ('http-curl-window', 'http-stdlib-window'):
        for name, kind, at in cases(row):
            env, w = environment(guide.origin, guide.key, guide.infos[at], query(name)), WINDOWS[name]
            done = bash(row, env, tmp_path) if row == 'http-curl-window' else stdlib(env, tmp_path)
            assert done.returncode == 0, (row, name, kind, done.stderr)
            if row == 'http-curl-window':
                assert done.stdout.strip() == w['wire_sha256'][kind], (name, kind)
                continue
            got = json.loads(done.stdout)
            assert got['sha256'] == w['wire_sha256'][kind], (name, kind)
            if w['at'] == 'all': assert (sum(len(t) for x in got['values'] for t in x), nested_sha256(got['values'])) == (w['count'], w['values_sha256'])
            else: assert got['values'] == w['values'], (name, kind)
    assert originals(guide.log) == []


def test_the_stdlib_interpreter_cannot_import_ophiolite(tmp_path):
    """The isolation is proved, not assumed. Mutation: STDLIB is the lane venv's plain python (the import succeeds)."""
    done = subprocess.run(STDLIB + ['-c', 'import ophiolite'], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and 'ModuleNotFoundError' in done.stderr, done.stderr


def test_the_sdk_block_reads_the_literals_on_a_key_and_never_the_original(guide, tmp_path):
    """Section 4 through recipes.run, `client` on bob's key over loopback HTTP: the ordinal window is `block`, the whole
    volume's digest is `whole`'s. Mutation: read_window replaced by download_original (the spy sees the original)."""
    for kind in CODES:
        info = guide.infos[kind]
        client = Client(guide.origin, 'p', Credential.bearer(guide.key))
        guide.log.clear()
        ns = run_python_block('sdk-read-window', client, tmp_path / kind, {'asset': info['asset_id'], 'revision': info['revision']})
        assert ns['values'] == WINDOWS['block']['values'], kind
        assert ns['window'].window_digest == WINDOWS['block']['wire_sha256'][kind], kind
        assert (ns['reader'].complete, ns['reader'].window_digest) == (True, WINDOWS['whole']['wire_sha256'][kind]), kind
        assert originals(guide.log) == [] and {k for _, k in guide.log} == {who(guide.key)}, kind


def test_the_command_line_block_writes_a_file_the_segyio_block_reads_as_the_literals(guide, tmp_path):
    """Section 5: `ophiolite get --window` as a real subprocess (this environment's entry point, the key from
    OPHIOLITE_ACCESS_KEY, configuration.json in its folder); then the segyio block in that folder (R1-7)."""
    assert (VENV_BIN / 'ophiolite').is_file(), VENV_BIN
    for kind in CODES:
        folder = tmp_path / kind
        folder.mkdir()
        (folder / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': guide.origin, 'project': 'p'}))
        guide.log.clear()
        done = bash('exchange-get-window', environment(guide.origin, guide.key, guide.infos[kind], home=folder), folder)
        assert done.returncode == 0, (kind, done.stdout, done.stderr)
        assert json.loads((folder / 'window/window.json').read_text())['window_digest'] == WINDOWS['block-exact']['wire_sha256'][kind]
        assert originals(guide.log) == [], kind
        ns = run_python_block('segyio-reads-window', None, folder, {})
        w = WINDOWS['block-exact']
        assert (ns['inlines'], ns['crosslines'], ns['times']) == (w['labels']['inline'], w['labels']['crossline'], EXACT_STARTS), kind
        assert ns['cube'].tolist() == w['values'], kind


def test_the_long_read_blocks_read_all_three_pieces_on_each_key(long, tmp_path, monkeypatch):
    """Section 6 on the long-read volume: the personal-key block (`client` on bob's key) and the service-key block (its
    own client from the environment) each read 3 pieces and compute the rows' `wire_sha256`; every window request
    carries that key."""
    given = {'asset': long.info['asset_id'], 'revision': long.info['revision']}
    personal = platform.personal(long.server)['key']
    long.log.clear()
    ns = run_python_block('long-read-personal-key', Client(long.origin, 'p', Credential.bearer(personal)), tmp_path / 'personal', given)
    row = ROWS['long-read-personal-key']
    assert (ns['reader'].complete, ns['reader'].document['pieces']['count'], ns['reader'].window_digest) == (True, row['pieces'], row['wire_sha256'])
    assert [json.loads(line)['piece'] for line in (tmp_path / 'personal/volume.json').read_text().splitlines()] == [0, 1, 2]
    asked = [k for path, k in long.log if '/volume-windows' in path]
    assert len(asked) == 4 and set(asked) == {who(personal)}
    key = platform.service_key(long.server)['key']
    for name, value in environment(long.origin, key, long.info).items():
        if name.startswith('OPHIOLITE_'): monkeypatch.setenv(name, value)
    long.log.clear()
    ns = run_python_block('long-read-service-key', None, tmp_path / 'service', given)
    row = ROWS['long-read-service-key']
    assert (ns['volume'].document['pieces']['count'], ns['volume'].window_digest) == (row['pieces'], row['wire_sha256'])
    asked = [k for path, k in long.log if '/volume-windows' in path]
    assert len(asked) == 4 and set(asked) == {who(key)}
    assert originals(long.log) == []


# --- the verification contract: the unchanged recipes refuse a damaged answer ---------------------------------------

NAMES = ('Content-Type', 'X-Ophiolite-Window', 'X-Ophiolite-Revision', 'X-Ophiolite-Piece', 'X-Content-SHA256')
PIECE = re.compile(r'/pieces/([0-9]+)\?')
FAULTS = {  # fault -> what the recipe says (both recipes, curl capitalised)
    'revision': 'is of another revision', 'window': 'belongs to another window', 'missing': 'is missing or repeated',
    'repeated': 'is missing or repeated', 'truncated': 'not complete', 'stale': 'is damaged'}


@contextlib.contextmanager
def proxy(upstream, fault):
    """A loopback proxy after the server's own storage verification, answering piece requests with FAULT applied."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path, found = self.path, PIECE.search(self.path)
            index = int(found.group(1)) if found else None
            if fault == 'missing' and index == 1: path = path.replace('/pieces/1?', '/pieces/0?')  # piece 1 never arrives
            if fault == 'repeated' and index == 2: path = path.replace('/pieces/2?', '/pieces/1?')  # piece 1 arrives twice
            try:
                with urllib.request.urlopen(urllib.request.Request(upstream + path, headers={'Authorization': self.headers['Authorization']})) as r:
                    status, headers, body = r.status, {k: r.headers[k] for k in NAMES if r.headers[k] is not None}, r.read()
            except urllib.error.HTTPError as error:
                status, headers, body = error.code, {k: error.headers[k] for k in NAMES if error.headers[k] is not None}, error.read()
            if index is not None and status == 200:
                if fault == 'revision': headers['X-Ophiolite-Revision'] = '0' * 64
                if fault == 'window' and index == 1: headers['X-Ophiolite-Window'] = 'f' * 64
                if fault == 'truncated' and index == 2:
                    body = body[:-4]
                    headers['X-Content-SHA256'] = hashlib.sha256(body).hexdigest()  # a consistent but short last piece
                if fault == 'stale' and index == 1: body = bytes([body[0] ^ 1]) + body[1:]
            self.send_response(status)
            for name, value in headers.items(): self.send_header(name, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name='e141s3-faulty-proxy')
    thread.start()
    try:
        yield 'http://127.0.0.1:%d' % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('recipe', ['curl', 'stdlib'])
@pytest.mark.parametrize('fault', [None] + list(FAULTS))
def test_the_unchanged_recipes_refuse_each_damaged_answer(long, tmp_path, recipe, fault):
    """R1-10, R1-12, on the long-read volume (3 pieces of 512 bytes): through a clean proxy each recipe prints the
    rows' digest; under each fault it exits non-zero with the check's words. Mutations (each recipe, one check line
    removed from the guide): the window, revision, piece-index, digest and byte-count checks (that fault then exits 0)."""
    key = platform.service_key(long.server)['key']
    with proxy(long.origin, fault) as origin:
        env = environment(origin, key, long.info)
        done = bash('http-curl-window', env, tmp_path) if recipe == 'curl' else stdlib(env, tmp_path)
    if fault is None:
        assert done.returncode == 0, done.stderr
        printed = done.stdout.strip() if recipe == 'curl' else json.loads(done.stdout)['sha256']
        assert printed == ROWS['long-read-service-key']['wire_sha256']
    else:
        assert done.returncode != 0, (recipe, fault, done.stdout[-200:])
        assert FAULTS[fault] in done.stderr, (recipe, fault, done.stderr[-300:])
    assert originals(long.log) == []
