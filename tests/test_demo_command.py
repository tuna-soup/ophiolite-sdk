"""E162 s1 C3: `ophiolite demo --bundle B` serves a synthetic demo-compatible bundle on this computer and prints three
commands that run as printed; `ophiolite demo stop` ends it. Each test names the mutation it catches."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import pytest
from ophiolite import Client, Credential, demo
from ophiolite.errors import Refused
from test_demo_bundle_server import ASCENDING, DESCENDING, Log, demo_bundle, typed


def bundle_for(tmp_path, name='demo'):
    """The descending log is first in the catalogue and first by well name, so lines 2 and 3 both read it."""
    return demo_bundle(tmp_path, [Log('log-b', 'SYN-A', DESCENDING), Log('log-a', 'SYN-B', ASCENDING), typed('tops'), typed('trajectory'), typed('grid')], name)


def environment(home, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}
    env.update(HOME=str(home), PATH=str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', ''), **extra)
    return env


def ophiolite(argv, cwd, **extra):
    return subprocess.run([sys.executable, '-m', 'ophiolite.cli', *argv], cwd=cwd, env=environment(cwd, **extra), capture_output=True, text=True, timeout=120)


@pytest.fixture
def place(tmp_path):
    """A working folder; whatever demo it starts is stopped afterwards."""
    work = tmp_path / 'work'; work.mkdir()
    yield work
    ophiolite(['demo', 'stop'], work)


def started(place, bundle, *extra):
    began = time.monotonic()
    done = ophiolite(['demo', '--bundle', str(bundle), *extra], place)
    assert done.returncode == 0, done.stderr
    return done, time.monotonic() - began


def commands(text):
    return [shlex.split(line) for line in text.splitlines() if line.startswith('     ')]


def state(place):
    return json.loads((place / 'ophiolite-demo' / 'state.json').read_text())


def test_the_three_printed_commands_run_as_printed(place, tmp_path):
    """Mutations: print a flag the parser lacks → that line exits 2; sort the fetched log → the first depth differs;
    let the template read the default credential store → it is refused (no file there)."""
    bundle = bundle_for(tmp_path)
    done, seconds = started(place, bundle)
    assert seconds < 60
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert 'Serving your bundle on this computer (sha256 %s).' % digest in done.stdout
    assert demo.DEPLOYMENT in done.stdout  # K18; the page it names is checked in the Integration tree (tools/test_demo_first_minute.py)
    wells, fetch, derive = commands(done.stdout)
    assert wells[:4] == ['ophiolite', 'data', 'wells', 'list'] and fetch[:3] == ['ophiolite', 'data', 'fetch'] and Path(derive[0]).resolve() == Path(sys.executable).resolve()
    ran = [subprocess.run(argv, cwd=place, env=environment(place), capture_output=True, text=True, timeout=120) for argv in (wells, fetch, derive)]
    assert [r.returncode for r in ran] == [0, 0, 0], [r.stderr for r in ran]
    assert ran[0].stdout.split('\n')[:2] == ["Well('SYN-A', unlocated)", "Well('SYN-B', unlocated)"]
    saved = json.loads((place / 'ophiolite-demo' / 'SYN-A-GR' / 'curve.json').read_text())
    assert saved['axis'] == [104.0, 103.0, 102.0, 101.0, 100.0] and saved['values'] == [41.5, None, 22.25, 10.0, 0.0]  # K1: file order
    receipt = json.loads(ran[2].stdout)['receipt']
    with Client('http://127.0.0.1:%d' % state(place)['port'], 'q', Credential.from_file(place / 'ophiolite-demo' / 'credential.json')) as client:
        [back] = client.read(receipt['asset_id'], receipt['revision'], ['CALC']).curves  # K3: read back through the demo
    assert back.values == [83.0, None, 44.5, 20.0, 0.0] and [p['key'] for p in receipt['derived_from']] == ['log-b']
    assert not (place / '.config').exists()  # nothing in the person's credential store (HOME is the working folder)
    for name in ('credential.json', 'state.json', 'configuration.json'):
        assert (place / 'ophiolite-demo' / name).stat().st_mode & 0o777 == 0o600
    stopped = ophiolite(['demo', 'stop'], place)
    assert stopped.returncode == 0 and stopped.stdout.strip() == 'The demo stopped; its publications are gone.'
    assert not (place / 'ophiolite-demo' / 'state.json').exists()


def test_a_flipped_byte_answers_as_bundle_check_and_starts_nothing(place, tmp_path):
    """Mutation: skip the check → the server starts and state.json appears."""
    import zipfile
    bundle = bundle_for(tmp_path); damaged = tmp_path / 'damaged.zip'
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(damaged, 'w') as out:
        for info in source.infolist():
            data = source.read(info)
            out.writestr(info, bytes([data[0] ^ 1]) + data[1:] if info.filename == 'assets/0/original.las' else data)
    checked, refused = ophiolite(['exchange', 'bundle', 'check', str(damaged)], place), ophiolite(['demo', '--bundle', str(damaged)], place)
    assert checked.returncode != 0 and (refused.returncode, refused.stderr, refused.stdout) == (checked.returncode, checked.stderr, checked.stdout)
    assert not (place / 'ophiolite-demo' / 'state.json').exists()


def test_a_bundle_the_demo_cannot_serve_is_refused_by_name(place, tmp_path):
    """K15 through the command (each rule is tested in test_demo_bundle_server). Mutation: drop the subset check → starts."""
    path = demo_bundle(tmp_path, [typed('tops'), typed('trajectory')])
    refused = ophiolite(['demo', '--bundle', str(path)], place)
    assert refused.returncode == 1 and 'The demo needs a bundle with a LAS log that carries a GR curve.' in refused.stderr
    assert not (place / 'ophiolite-demo' / 'state.json').exists()


def test_with_a_typed_asset_first_line_3_doubles_the_catalogues_first_gr_log(place, tmp_path):
    """E162 s1b: a typed asset first, then two GR logs whose catalogue order is unlike their name order. Line 2 fetches
    the first by name; line 3 doubles the catalogue's first. Mutations: template_well from served[0] → no start; the
    template back on the catalogue's first item → refused on the survey; the template's log chosen by name → its parent
    is log-a and the values differ."""
    path = demo_bundle(tmp_path, [typed('trajectory'), Log('log-b', 'SYN-B', DESCENDING), Log('log-a', 'SYN-A', ASCENDING)])
    done, _ = started(place, path)
    assert '  2. The whole GR curve of SYN-A, into a new folder:' in done.stdout.splitlines()
    assert '  3. Double the GR curve of SYN-B and publish it with the derive-and-publish template:' in done.stdout.splitlines()
    assert '  1. The wells (the demo serves them without locations):' in done.stdout.splitlines()
    derive = commands(done.stdout)[2]
    ran = subprocess.run(derive, cwd=place, env=environment(place), capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stderr
    receipt = json.loads(ran.stdout)['receipt']
    with Client('http://127.0.0.1:%d' % state(place)['port'], 'q', Credential.from_file(place / 'ophiolite-demo' / 'credential.json')) as client:
        [back] = client.read(receipt['asset_id'], receipt['revision'], ['CALC']).curves
    assert back.values == [83.0, None, 44.5, 20.0, 0.0] and [p['key'] for p in receipt['derived_from']] == ['log-b']


def test_a_support_module_an_earlier_demo_wrote_is_replaced_and_an_edited_one_kept(place, tmp_path, monkeypatch):
    """E162 s1b: a demo folder keeps derive-and-publish, but an unchanged support.py of an earlier demo (it read the
    catalogue's first item) is replaced; an edited one is kept and the demo says how to get the current one. Mutations:
    never replace → the earlier bytes stay; replace any → the edited bytes are lost and no sentence is printed."""
    from importlib.resources import files
    current = files('ophiolite').joinpath('templates/support.py').read_bytes()
    folder = tmp_path / 'ophiolite-demo'; demo.claim(folder)
    earlier = b'# the support module an earlier demo wrote\n'
    monkeypatch.setattr(demo, 'SHIPPED_SUPPORT', frozenset({hashlib.sha256(earlier).hexdigest()}))
    (folder / 'support.py').write_bytes(earlier)
    assert demo.template(folder) is False and (folder / 'support.py').read_bytes() == current
    assert demo.template(folder) is False and (folder / 'support.py').read_bytes() == current
    edited = place / 'ophiolite-demo'; demo.claim(edited)
    (edited / 'support.py').write_bytes(current + b'# mine\n')
    done, _ = started(place, bundle_for(tmp_path))
    assert done.stdout.splitlines()[-1] == demo.EDITED_SUPPORT
    assert (edited / 'support.py').read_bytes() == current + b'# mine\n'


def test_which_bundle_is_named_by_its_digest(tmp_path, monkeypatch):
    """Mutation: compare file names → a renamed pinned file is 'yours'. A bare call refuses with the exact sentence while
    nothing is published; a download whose digest is not the pinned one is deleted."""
    bundle = bundle_for(tmp_path)
    renamed = tmp_path / 'renamed.zip'; renamed.write_bytes(bundle.read_bytes())
    assert demo.examine(bundle)['which'] == 'yours'
    monkeypatch.setattr(demo, 'BUNDLE_SHA256', hashlib.sha256(bundle.read_bytes()).hexdigest())
    assert demo.examine(renamed)['which'] == 'f3-block'
    folder = tmp_path / 'ophiolite-demo'; demo.claim(folder)
    assert demo.BUNDLE_URL is None
    with pytest.raises(Refused) as bare: demo.locate(None, folder)
    assert str(bare.value) == 'The demo bundle is not yet published for download; use --bundle PATH.'
    from ophiolite.testing import FixtureServer
    with FixtureServer(lambda method, path, raw, headers: (200, b'not the bundle')) as server:
        monkeypatch.setattr(demo, 'BUNDLE_URL', server.url + '/f3-block.zip')
        with pytest.raises(Refused, match='does not match its published checksum'): demo.locate(None, folder)
    assert sorted(p.name for p in folder.iterdir()) == ['.ophiolite-demo']


def test_the_attribution_is_printed_as_recorded_an_import_record_too(tmp_path):
    """ophiolite-13's ruling (9 Nov): a table import's record ("Imported from <file> by <who>", which the gateway writes
    in place of the project's attribution) is printed as it stands, once. Mutation: leave such records out → absent."""
    record = 'Imported from synthetic-tops.csv by operator'
    path = demo_bundle(tmp_path, [Log('log-b', 'SYN-A', DESCENDING), typed('tops', attribution=record), typed('trajectory', attribution=record)])
    facts = demo.examine(path)
    assert facts['attribution'].count(record) == 1
    assert record in demo.said(facts, demo.lines(tmp_path, facts), True).splitlines()


def test_a_second_call_reprints_and_a_wrong_token_cannot_stop(place, tmp_path):
    """Mutations: start a server per call → the port differs; accept any token → the server stops."""
    import httpx
    bundle = bundle_for(tmp_path)
    started(place, bundle); first = state(place)
    again, _ = started(place, bundle)
    assert again.stdout.startswith('Still serving') and state(place)['port'] == first['port']
    answer = httpx.post('http://127.0.0.1:%d/demo/stop' % first['port'], headers={demo.TOKEN_HEADER: 'wrong'}, trust_env=False)
    assert answer.status_code == 403 and demo.running(place / 'ophiolite-demo')['pid'] == first['pid']


def test_a_stale_state_is_replaced(place, tmp_path):
    """A state naming a closed port (the process ended) is replaced by a new server. Mutation: trust the file → exit 1."""
    import socket
    bundle = bundle_for(tmp_path)
    started(place, bundle); ophiolite(['demo', 'stop'], place)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); closed = s.getsockname()[1]
    demo.write_private(place / 'ophiolite-demo' / 'state.json', json.dumps({'pid': 1, 'port': closed, 'digest': 'x', 'token': 't', 'key': 'k'}).encode())
    done, _ = started(place, bundle)
    assert done.stdout.startswith('Serving') and state(place)['port'] != closed


def test_two_starts_at_once_make_one_server(place, tmp_path):
    """Mutation: drop the O_EXCL lock → two servers, two ports."""
    bundle = bundle_for(tmp_path); demo.claim(place / 'ophiolite-demo')
    argv = [sys.executable, '-m', 'ophiolite.cli', 'demo', '--bundle', str(bundle), '--json']
    both = [subprocess.Popen(argv, cwd=place, env=environment(place), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    answers = [p.communicate(timeout=120) for p in both]
    assert [p.returncode for p in both] == [0, 0], [a[1] for a in answers]
    urls = {json.loads(out)['url'] for out, _ in answers}
    assert len(urls) == 1 and sorted(json.loads(out)['state'] for out, _ in answers) == ['running', 'started']


def test_a_second_start_never_removes_the_credential_the_first_is_reading(place, tmp_path, monkeypatch):
    """The [0, 3] of 11 Nov: each start replaces credential.json, and one start's removal fell between the other's write
    and its read-back (AuthenticationRequired, exit 3). Forced here: A pauses after writing its credential while B runs.
    Mutation: drop the demo's setup lock → A's read-back finds no file."""
    import threading
    from types import SimpleNamespace
    from ophiolite import auth
    from ophiolite.errors import AuthenticationRequired
    bundle = bundle_for(tmp_path); started(place, bundle)
    monkeypatch.chdir(place)
    written, removed = threading.Event(), threading.Event()
    real_write, real_login = auth._write, auth.key_login

    def write(path, envelope):
        real_write(path, envelope)
        if threading.current_thread().name == 'A': written.set(); removed.wait(3)

    def login(*args, **kwargs):
        if threading.current_thread().name == 'B': removed.set()  # B has removed A's credential and goes on to write its own
        return real_login(*args, **kwargs)
    monkeypatch.setattr(auth, '_write', write); monkeypatch.setattr(auth, 'key_login', login)
    outcome = {}

    def run(name):
        try: outcome[name] = demo.command(SimpleNamespace(bundle=str(bundle), demo_action=None))[1]['state']
        except AuthenticationRequired as error: outcome[name] = str(error)
    a = threading.Thread(target=run, args=('A',), name='A'); a.start()
    assert written.wait(30)
    b = threading.Thread(target=run, args=('B',), name='B'); b.start()
    a.join(60); b.join(60)
    assert outcome == {'A': 'running', 'B': 'running'}


def test_the_server_ends_itself_when_idle(place, tmp_path):
    """Mutation: ignore the idle limit → the state stays."""
    started(place, bundle_for(tmp_path), )
    ophiolite(['demo', 'stop'], place)
    done = ophiolite(['demo', '--bundle', str(bundle_for(tmp_path, 'again'))], place, OPHIOLITE_DEMO_IDLE_SECONDS='1')
    assert done.returncode == 0, done.stderr
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and (place / 'ophiolite-demo' / 'state.json').exists(): time.sleep(0.2)
    assert not (place / 'ophiolite-demo' / 'state.json').exists()


def test_a_restart_loses_the_publications(place, tmp_path):
    """The printed text says publications last until the demo stops; after a restart the receipt reads as unavailable.
    Mutation: persist publications → the read succeeds."""
    from ophiolite.writers import WrittenOriginal
    bundle = bundle_for(tmp_path)
    done, _ = started(place, bundle)
    assert 'publications last until the demo stops' in done.stdout
    def client():
        return Client('http://127.0.0.1:%d' % state(place)['port'], 'q', Credential.from_file(place / 'ophiolite-demo' / 'credential.json'))
    with client() as c:
        first = next(iter(c.assets())); source = c.read(first['asset_id'], first['revision'], ['GR'])
        receipt = c.publish_derived(WrittenOriginal(source.artifact, 'las2/1', {}, 'derived.las'), name='kept?', from_=[(first['asset_id'], first['revision'])],
                                    method={'name': 'synthetic', 'parameters': {}}, command_id='c1')
        assert c.read(receipt.asset_id, receipt.revision, ['GR']).curves[0].values == [41.5, None, 22.25, 10.0, 0.0]
    ophiolite(['demo', 'stop'], place); started(place, bundle)
    with client() as c, pytest.raises(Exception, match='unavailable'): c.read(receipt.asset_id, receipt.revision, ['GR'])


@pytest.mark.parametrize('kind', ['folder', 'link'])
def test_a_folder_the_demo_did_not_make_is_refused(place, tmp_path, kind):
    """Mutation: drop the marker check → the person's folder is written into."""
    mine = tmp_path / 'mine'; mine.mkdir(); (mine / 'notes.txt').write_text('mine')
    if kind == 'folder': (place / 'ophiolite-demo').mkdir(); (place / 'ophiolite-demo' / 'notes.txt').write_text('mine')
    else: (place / 'ophiolite-demo').symlink_to(mine, target_is_directory=True)
    refused = ophiolite(['demo', '--bundle', str(bundle_for(tmp_path))], place)
    assert refused.returncode == 1 and 'did not make' in refused.stderr
    assert sorted(p.name for p in mine.iterdir()) == ['notes.txt'] and sorted(p.name for p in (place / 'ophiolite-demo').iterdir()) == ['notes.txt']


def test_help_puts_the_demo_first():
    """Mutation: append the START row → the first line under Start here is account login."""
    done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', '--help'], capture_output=True, text=True, env=environment(Path.cwd()))
    lines = done.stdout.splitlines()
    assert lines[lines.index('Start here:') + 1].split()[1:4] == ['demo', '--bundle', 'PATH']  # the program name is cli.py under -m
    assert any(line.split()[:1] == ['demo'] for line in lines[lines.index('Groups:'):])
