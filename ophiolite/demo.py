"""E162 s1: `ophiolite demo` serves a portable bundle on this computer and prints three production commands that run on
it as printed; `ophiolite demo stop` ends it. Loopback only. The demo's configuration, key and state live in
./ophiolite-demo; its publications live in the server process and end with it. The SDK holds no well name, value or
identifier of any bundle: the commands are chosen from the bundle when the demo starts."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from .errors import Refused

BUNDLE_SHA256 = '7f8f1078b6ca7b40cad2e8afdb5f7bbe0e73aa10a26e32d61595d0e62c47c5f3'  # the restorable F3-block bundle (E162 s2a; item 241)
BUNDLE_URL = None  # set once the owner publishes the bundle for download (item 241); until then --bundle PATH
BUNDLE_NAME = 'f3-block.zip'
FOLDER = 'ophiolite-demo'
MARKER = '.ophiolite-demo'
STATE = 'state.json'
IDLE_SECONDS = 2 * 3600  # the server ends itself after this long without a request (OPHIOLITE_DEMO_IDLE_SECONDS)
START_SECONDS = 30
DEPLOYMENT = 'https://ophiolite.dev/docs/operate/install/'  # web/docs/src/content/docs/operate/install.md
NOT_PUBLISHED = 'The demo bundle is not yet published for download; use --bundle PATH.'
FOREIGN = 'An ophiolite-demo folder or link that the demo did not make is here; move it, or run ophiolite demo in another folder.'
TOKEN_HEADER = 'X-Ophiolite-Demo-Token'
# the support.py an earlier demo wrote (E162 s1), replaced when unchanged: it read the catalogue's first item (E162 s1b)
SHIPPED_SUPPORT = frozenset({'d185d8386c8bf8ab6accb0320521b467bad51410c07662ba36953c5e5f2f27f9'})
EDITED_SUPPORT = "This folder's support.py was changed; run ophiolite demo in a new folder to use the current template."


def command(args):
    """(text, payload) of `ophiolite demo [--bundle PATH]` or `ophiolite demo stop`, run from the current folder."""
    folder = Path(FOLDER)
    if getattr(args, 'demo_action', None) == 'stop': return stop(folder)
    claim(folder)
    path = locate(args.bundle, folder)
    facts = examine(path)  # the check `ophiolite exchange bundle check` runs, then the demo's own subset
    state = running(folder)
    if state is not None and state['digest'] != facts['digest']:
        raise Refused('A demo of another bundle is running here; run ophiolite demo stop first.')
    started = False
    if state is None: state, started = start(folder, path)
    url = 'http://127.0.0.1:%d' % state['port']
    configuration, credential = folder / 'configuration.json', folder / 'credential.json'
    from . import auth
    with auth._lock(folder / 'setup'):  # two starts at once: neither removes the files the other is writing or reading back
        write_private(configuration, (json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': url, 'project': facts['project']}, indent=2) + '\n').encode())
        if credential.exists() or credential.is_symlink(): credential.unlink()  # a key of an earlier server: replaced, never read
        auth.key_login(url, facts['project'], state['key'], path=credential)
        edited = template(folder)
    commands = lines(folder, facts)
    return said(facts, commands, started) + ('\n' + EDITED_SUPPORT if edited else ''), {'state': 'started' if started else 'running', 'digest': facts['digest'], 'bundle': facts['which'],
                                             'url': url, 'project': facts['project'], 'attribution': facts['attribution'], 'commands': commands}


def claim(folder):
    """The demo's folder: made here with its marker, or one the demo made earlier; anything else is refused."""
    if folder.is_symlink() or folder.exists() and (not folder.is_dir() or not (folder / MARKER).is_file()): raise Refused(FOREIGN)
    if not folder.exists():
        folder.mkdir(mode=0o700)
        (folder / MARKER).write_text('Made by ophiolite demo; ophiolite demo stop ends its server.\n')


def locate(given, folder):
    if given is not None:
        if not Path(given).is_file(): raise Refused('No bundle file at %s.' % given)
        return Path(given)
    kept = folder / BUNDLE_NAME
    if kept.is_file(): return kept
    if BUNDLE_URL is None: raise Refused(NOT_PUBLISHED)
    return download(BUNDLE_URL, kept)


def download(url, target):
    """The published bundle into the demo folder, kept only when its digest is the pinned one."""
    import httpx
    partial = target.with_name(target.name + '.partial'); digest = hashlib.sha256()
    try:
        with httpx.stream('GET', url, follow_redirects=True, timeout=60) as answer, open(os.open(partial, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'wb') as out:
            if answer.status_code != 200: raise Refused('The demo bundle could not be downloaded (HTTP %d).' % answer.status_code)
            for chunk in answer.iter_bytes(): digest.update(chunk); out.write(chunk)
        if digest.hexdigest() != BUNDLE_SHA256: raise Refused('The downloaded demo bundle does not match its published checksum; it was deleted.')
        os.replace(partial, target)
        return target
    finally:
        if partial.exists(): partial.unlink()


def examine(path):
    """What the demo prints, read from the bundle: its digest, project, attribution and the log line 2 fetches."""
    from .testing import BundleApplications
    applications = BundleApplications(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    attribution = []
    for served in applications.served:
        for descriptor in served['parsed'].values():
            words = (descriptor.get('acquisition') or {}).get('attribution')
            if isinstance(words, str) and words and words not in attribution: attribution.append(words)  # as recorded, an import record too
    gr = [a for a in applications.served if a['entry'].get('profile') == 'las2/1' and 'GR' in a['curves']]
    well, asset, revision = sorted((Path(a['source_path']).stem, a['entry']['asset_id'], a['entry']['revision']) for a in gr)[0]
    first = Path(gr[0]['source_path']).stem  # the log the template reads: the catalogue's first that carries GR (E162 s1b)
    return {'digest': digest, 'which': 'f3-block' if digest == BUNDLE_SHA256 else 'yours', 'project': applications.project,
            'attribution': attribution, 'well': well, 'asset': asset, 'revision': revision, 'template_well': first}


def lines(folder, facts):
    files = ['--configuration', str(folder / 'configuration.json'), '--credentials', str(folder / 'credential.json')]
    output = folder / (re.sub(r'[^A-Za-z0-9._-]', '_', facts['well']) + '-GR')
    return [['ophiolite', 'data', 'wells', 'list', *files],
            ['ophiolite', 'data', 'fetch', '--asset', facts['asset'], '--revision', facts['revision'], '--curve', 'GR', '--output', str(output), *files],
            [sys.executable, str(folder / 'derive-and-publish' / 'app'), *files, '--work', str(folder / 'work')]]


def shown(argv):
    if os.name == 'nt': return subprocess.list2cmdline(argv)
    import shlex
    return shlex.join(argv)


def said(facts, commands, started):
    which = 'the F3-block demo bundle' if facts['which'] == 'f3-block' else 'your bundle'
    text = ['%s %s on this computer (sha256 %s).' % ('Serving' if started else 'Still serving', which, facts['digest']), *facts['attribution'],
            'This is a demo on this computer, not a deployment: publications last until the demo stops. Deployment options: ' + DEPLOYMENT,
            '', 'Run these from this folder:',
            '  1. The wells (the demo serves them without locations):', '     ' + shown(commands[0]),
            '  2. The whole GR curve of %s, into a new folder:' % facts['well'], '     ' + shown(commands[1]),
            '  3. Double the GR curve of %s and publish it with the derive-and-publish template:' % facts['template_well'], '     ' + shown(commands[2]),
            '', 'Stop the demo with: ophiolite demo stop']
    return '\n'.join(text)


def template(folder):
    """derive-and-publish and the support module beside it, as `ophiolite tools init` copies them; kept when present,
    except a support module an earlier demo wrote unchanged, which is replaced (E162 s1b). True when an edited one is kept."""
    from importlib.resources import files
    from .cli import _copy
    root = files('ophiolite').joinpath('templates')
    if not (folder / 'derive-and-publish').exists(): _copy(root.joinpath('derive-and-publish'), folder / 'derive-and-publish')
    support, current = folder / 'support.py', root.joinpath('support.py').read_bytes()
    if support.is_file() and not support.is_symlink():
        held = support.read_bytes()
        if held == current: return False
        if hashlib.sha256(held).hexdigest() not in SHIPPED_SUPPORT: return True
    elif support.exists() or support.is_symlink(): return True
    support.write_bytes(current)
    return False


def write_private(path, raw):
    """RAW at PATH, 0600, replaced in one step."""
    partial = path.with_name('.' + path.name + '.partial')
    if partial.exists(): partial.unlink()
    with open(os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as out: out.write(raw)
    os.replace(partial, path)


def _ask(state, method, route, token=None):
    import httpx
    with httpx.Client(trust_env=False, timeout=5) as http:
        return http.request(method, 'http://127.0.0.1:%d%s' % (state['port'], route), headers={TOKEN_HEADER: state['token'] if token is None else token})


def running(folder):
    """The state of the demo server serving FOLDER, or None. A state whose server does not answer with its token is stale
    (the process ended, or another program took the port) and is removed."""
    path = folder / STATE
    try: state = json.loads(path.read_text())
    except (OSError, ValueError): return None
    try:
        answer = _ask(state, 'GET', '/demo/status')
        if answer.status_code == 200 and answer.json().get('digest') == state['digest']: return state
    except Exception: pass  # noqa: BLE001 (anything but its own answer means the server is gone)
    try: path.unlink()
    except OSError: pass
    return None


def start(folder, path):
    """(state, True) once the server this call started answers; (state, False) when another start in this folder won
    the O_EXCL lock and its server answers, so two starts at once yield one server."""
    lock = folder / 'start.lock'
    try: handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            state = running(folder)
            if state is not None: return state, False
            if not lock.exists(): return start(folder, path)  # the other start failed: try once more
            time.sleep(0.2)
        raise Refused('Another ophiolite demo is starting in this folder; remove %s if none is.' % lock) from None
    process = None
    try:
        state = running(folder)  # a start that finished between this call's first look and its lock
        if state is not None: return state, False
        log = open(os.open(folder / 'server.log', os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'wb')
        detach = {'creationflags': 0x00000008 | 0x00000200} if os.name == 'nt' else {'start_new_session': True}  # DETACHED_PROCESS, NEW_PROCESS_GROUP
        with log:
            process = subprocess.Popen([sys.executable, '-m', 'ophiolite.demo', 'serve', str(folder.resolve()), str(Path(path).resolve())],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, **detach)
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            state = running(folder)
            if state is not None: return state, True
            if process.poll() is not None: break
            time.sleep(0.1)
        if process.poll() is None: process.kill()
        words = (folder / 'server.log').read_text(errors='replace').strip().splitlines()
        raise Refused('The demo server did not start%s' % (': ' + words[-1][:300] if words else '.'))
    except BaseException:
        try: (folder / STATE).unlink()
        except OSError: pass
        raise
    finally:
        os.close(handle); lock.unlink()


def stop(folder):
    if folder.is_symlink() or folder.exists() and not (folder / MARKER).is_file(): raise Refused(FOREIGN)
    state = running(folder) if folder.exists() else None
    if state is None: return 'No demo is running here.', {'state': 'not-running'}
    answer = _ask(state, 'POST', '/demo/stop')
    if answer.status_code != 200: raise Refused('The demo server refused to stop; its state file does not match it.')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (folder / STATE).exists(): time.sleep(0.1)
    return 'The demo stopped; its publications are gone.', {'state': 'stopped'}


def serve(folder, path):
    """The server process: one bundle on a loopback port, the demo key only, ended by /demo/stop with its token or by
    IDLE_SECONDS without a request. Its state file (0600) is written once the port is bound and removed on exit."""
    import threading
    from .testing import BundleApplications, FixtureServer
    folder = Path(folder)
    applications = BundleApplications(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    token, key = secrets.token_urlsafe(32), 'oph_key_' + secrets.token_urlsafe(32)
    idle = float(os.environ.get('OPHIOLITE_DEMO_IDLE_SECONDS') or IDLE_SECONDS)
    last, done = [time.monotonic()], threading.Event()

    def handler(method, route, raw, headers):
        last[0] = time.monotonic()
        given = {k.lower(): v for k, v in headers.items()}
        if route in ('/demo/status', '/demo/stop'):
            if not secrets.compare_digest(given.get(TOKEN_HEADER.lower(), ''), token): return 403, {'error': 'Not this demo.'}
            if route == '/demo/stop' and method == 'POST': done.set(); return 200, {'state': 'stopping'}
            return 200, {'digest': digest, 'project': applications.project}
        if not secrets.compare_digest(given.get('authorization', ''), 'Bearer ' + key): return 401, {'error': 'authorization required'}
        return applications(method, route, raw, {**{k: v for k, v in headers.items() if k.lower() != 'authorization'}, 'Authorization': 'Bearer oph_api_demo'})

    server = FixtureServer(handler, record=False)
    port = int(server.url.rsplit(':', 1)[1])
    state = {'schema': 'ophiolite.demo-state/1', 'pid': os.getpid(), 'port': port, 'digest': digest, 'token': token, 'key': key, 'project': applications.project}
    with server:
        write_private(folder / STATE, json.dumps(state).encode())
        try:
            while not done.wait(min(1.0, idle)):
                if time.monotonic() - last[0] > idle: break
        finally:
            try:
                if json.loads((folder / STATE).read_text()).get('pid') == os.getpid(): (folder / STATE).unlink()
            except (OSError, ValueError): pass


if __name__ == '__main__':
    if sys.argv[1:2] != ['serve'] or len(sys.argv) != 4: raise SystemExit('usage: python -m ophiolite.demo serve FOLDER BUNDLE')
    serve(sys.argv[2], sys.argv[3])
