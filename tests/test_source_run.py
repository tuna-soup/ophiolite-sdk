"""E108 C4 (slice 1): `ophiolite source run`, without a server. A source procedure of the catalogue runs on this
computer and what it makes is started as one upload whose files each name the version, the team's system in words and
the output role; the configuration, log.txt and run.json are never sent. A procedure that is not enabled, not a source,
or that makes a role it does not declare or misses one is refused before anything is sent, as is a setting (a default
included) that looks like an address or a password. The gateway lane (tests/gateway/test_source_run_live.py) runs it
against the real routes, where S3's case (a colleague receives a declaration-only version 2) also runs."""
import base64
import contextlib
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from ophiolite import Client, Credential, cli, procedures
from ophiolite.procedures import NotRun
from ophiolite.upload_runs import RESULT

ORIGIN = 'https://gateway.example'
TOKEN = 'planted-token-4b1f'
WELLS = {'well_a': (75334.17681809, 448169.00072371), 'well_b': (75326.11369289, 448167.26418839), 'well_c': (75300.5, 448150.25)}
SETTING_SECRET = 'A setting looks like an address or a password; put it in the system configuration on this computer.'


@pytest.fixture(autouse=True)
def here(tmp_path, monkeypatch):
    """E108 S2: `source run`'s work folder defaults to `.ophiolite-held` in the current folder; each test has its own."""
    monkeypatch.chdir(tmp_path)

CODE = '''from ophiolite import procedure
from ophiolite.writers import write_location

WELLS = %r


@procedure
def fetch(inputs, settings):
    config = inputs['share'].config
    assert config['token'] == %r
    with open(config['counter'], 'a') as counter: counter.write('ran\\n')
    return {role: write_location(x, y, crs='EPSG:28992', elevation_reference='unknown', filename=role + '.json') for role, (x, y) in WELLS.items() if role in %r}
'''


def manifest(step='source', roles=tuple(WELLS), settings=None):
    out = {'schema': 'ophiolite.procedure/1', 'name': 'team/survey-share', 'label': 'Survey share', 'version': 2, 'step': step,
           'inputs': [{'slot': 'share', 'label': 'Team survey share', 'class': 'system', 'config_keys': ['counter', 'token', 'url']}],
           'outputs': [{'role': r, 'label': 'Well %s location' % r[-1].upper(), 'class': 'version', 'kind': 'well-location/1'} for r in roles],
           'entry': 'procedure:fetch'}
    if settings: out['settings'] = settings
    return out


def folder(root, made=tuple(WELLS), **shape):
    root.mkdir(parents=True)
    (root / 'procedure.json').write_text(json.dumps(manifest(**shape)))
    (root / 'procedure.py').write_text(CODE % (WELLS, TOKEN, tuple(made)))
    assert procedures.validate(root)['valid'], procedures.validate(root)
    return root


def added(i, f):
    return {'ordinal': i, 'path': f['path'], 'bytes': f['bytes'], 'sha256': f['sha256'], 'role': 'primary', 'state': 'added', 'kind': None,
            'reason_code': None, 'sentence': RESULT['added']}


class Server:
    """The catalogue (one version of the folder) and the upload routes; every request is kept as (operation, body)."""
    def __init__(self, procedure, state='enabled'):
        self.archive, self.digest, self.state = procedures.pack(procedure), procedures.digest(procedure), state
        self.sent, self.items = [], []

    def version(self):
        return {'digest': self.digest, 'name': 'team/survey-share', 'label': 'Survey share', 'version': 2, 'state': self.state, 'trusted': True,
                'mine': False, 'added_by': 'tina', 'added_at': 1.0, 'enabled_at': 2.0, 'withdrawn_at': None}

    def view(self, state):
        counts = {k: 0 for k in ('waiting', 'reading', 'added', 'already_here', 'needs_decision', 'not_read', 'not_supported', 'cancelled',
                                 'needs_procedure', 'converting', 'converted')}
        counts['added'] = len(self.items)
        return {'run_id': 'r' * 32, 'project_id': 'p', 'folder_name': 'Team survey share', 'state': state, 'label': 'Finished',
                'files': len(self.items), 'counts': counts, 'items': self.items, 'outputs_added': 0}

    def __call__(self, request):
        operation = '/'.join(request.url.path.rsplit('/', 2)[-2:])
        body = json.loads(request.content or b'{}')
        self.sent.append((operation, body))
        if operation == 'procedures/list': return httpx.Response(200, json={'versions': [self.version()]})
        if operation == 'procedures/get': return httpx.Response(200, json=self.version())
        if operation == 'procedures/bundle':
            return httpx.Response(200, json={'archive': base64.b64encode(self.archive).decode(), 'archive_sha256': hashlib.sha256(self.archive).hexdigest()})
        if operation == 'upload-runs/start':
            self.items = [added(i, f) for i, f in enumerate(body['files'])]
            return httpx.Response(200, json=self.view('closed'))
        if operation == 'upload-runs/status': return httpx.Response(200, json=self.view('closed'))
        if operation == 'capabilities/describe': return httpx.Response(200, json={'limits': {'upload_bytes': 1 << 30, 'file_bytes': 1 << 30}})
        return httpx.Response(404, json={'error': {'code': 'not-found', 'message': operation}})

    def uploads(self): return [(o, b) for o, b in self.sent if o.startswith('upload-runs/')]


@contextlib.contextmanager
def client(server):
    with httpx.Client(transport=httpx.MockTransport(server)) as http:
        yield Client(ORIGIN, 'p', Credential.bearer('k'), http)


def config(tmp_path):
    path = tmp_path / 'share.json'
    path.write_text(json.dumps({'counter': str(tmp_path / 'runs.txt'), 'token': TOKEN, 'url': 'https://share.example/wells'}))
    return {'share': str(path)}


def runs(tmp_path):
    counter = tmp_path / 'runs.txt'
    return len(counter.read_text().splitlines()) if counter.exists() else 0


def source_run(tmp_path, server, **options):
    with client(server) as c:
        return c.source_run('team/survey-share', config(tmp_path), cache=tmp_path / 'cache', attribution='Team survey share', audience='me', **options)


def test_first_run_lands_with_its_source(tmp_path):
    """One upload of the three outputs, each naming the version, the system in words and its role; nothing else is sent.
    Mutation: the listing without `source` (red); log.txt or run.json sent (red)."""
    server = Server(folder(tmp_path / 'procedure'))
    result = source_run(tmp_path, server, folder=tmp_path / 'kept')
    [(_, start)] = [(o, b) for o, b in server.uploads() if o == 'upload-runs/start']
    kept = {p.name: p.read_bytes() for p in (tmp_path / 'kept').iterdir()}
    assert sorted(kept) == ['log.txt', 'run.json', 'well_a.json', 'well_b.json', 'well_c.json']
    assert start['files'] == [{'path': 'Team survey share/%s.json' % role, 'bytes': len(kept[role + '.json']), 'sha256': hashlib.sha256(kept[role + '.json']).hexdigest(),
                               'source': {'digest': server.digest, 'system': 'Team survey share', 'role': role}} for role in WELLS]
    assert (start['folder_name'], start['attribution'], start['audience'], start['rights_confirmed']) == ('Team survey share', 'Team survey share', [], True)
    assert not any(TOKEN in json.dumps(b) or 'share.example' in json.dumps(b) for _, b in server.sent)  # D9: the configuration stays here
    assert result['sentence'] == 'Ran Survey share, version 2, on this computer, reading from Team survey share.' and result['report'].ok
    assert runs(tmp_path) == 1


def test_without_a_folder_the_run_leaves_nothing_behind_and_names_the_given_system(tmp_path, monkeypatch):
    made = []
    real = procedures.tempfile.mkdtemp
    monkeypatch.setattr(procedures.tempfile, 'mkdtemp', lambda **k: made.append(real(**k)) or made[-1])
    server = Server(folder(tmp_path / 'procedure'))
    source_run(tmp_path, server, system_label='Survey share drive')
    [(_, start)] = [(o, b) for o, b in server.uploads() if o == 'upload-runs/start']
    assert {f['source']['system'] for f in start['files']} == {'Survey share drive'} and start['folder_name'] == 'Survey share drive'
    assert [m for m in made if 'ophiolite-source-' in m and Path(m).exists()] == []


ENABLE = ' A project administrator enables one in Settings → Procedures or with ophiolite procedures enable.'  # E121 B5
CASES = {
    'not-enabled': (dict(), dict(state='private'), 'Not run: Survey share has no enabled version in this project.' + ENABLE),  # B6 rev 5 (R4-8): its label
    'wrong-step': (dict(step='process'), dict(), None),
    'missing-role': (dict(made=('well_a', 'well_b')), dict(), 'Not run: the procedure did not make Well C location.'),
    'extra-role': (dict(roles=('well_a', 'well_b')), dict(), 'Not run: the procedure made an output it does not declare.'),
    'system-address': (dict(), dict(system_label='https://share.example'), "Not run: name the team's system in words; its address and passwords stay in the configuration on this computer."),
    'system-password': (dict(), dict(system_label='Share Password'), "Not run: name the team's system in words; its address and passwords stay in the configuration on this computer."),
}


@pytest.mark.parametrize('case', CASES)
def test_disabled_procedure_wrong_step_or_role_is_refused(tmp_path, case):
    """Each refused with its sentence and nothing sent to the upload routes. Mutation: the step check removed; the
    process procedure runs and is sent (red). Mutation: the system-label check removed (red)."""
    shape, given, sentence = CASES[case]
    made = shape.pop('made', tuple(WELLS))
    if shape.get('step') == 'process':
        root = tmp_path / 'procedure'; root.mkdir()
        m = manifest()
        m.update(step='process', inputs=[{'slot': 'share', 'label': 'Locations', 'class': 'version', 'kinds': ['well-location/1'], 'cardinality': 'one'}])
        (root / 'procedure.json').write_text(json.dumps(m)); (root / 'procedure.py').write_text(CODE % (WELLS, TOKEN, made))
        assert procedures.validate(root)['valid'], procedures.validate(root)
        sentence = "Not run: Survey share does not read from a team's system; only a source procedure adds its results this way."
    else:
        root = folder(tmp_path / 'procedure', made=made, **shape)
    server = Server(root, state=given.pop('state', 'enabled'))
    with pytest.raises(NotRun) as refused: source_run(tmp_path, server, **given)
    assert str(refused.value) == sentence
    assert server.uploads() == []


@pytest.mark.parametrize('given', [None, ['source=me@share.example'], ['source=Survey tokens']], ids=['default', 'at', 'secret-word'])
def test_https_default_setting_is_refused(tmp_path, given):
    """D9 (ii): resolved settings, the default included, are checked before the procedure runs. Mutation: the check reads
    only the given settings; the default runs and is sent (red)."""
    settings = [{'key': 'source', 'label': 'Where the share keeps its wells', 'type': 'string', 'default': 'https://share.example/wells'}]
    server = Server(folder(tmp_path / 'procedure', settings=settings))
    with pytest.raises(NotRun) as refused: source_run(tmp_path, server, settings=given)
    assert (str(refused.value), refused.value.field) == (SETTING_SECRET, '/settings/source')
    assert runs(tmp_path) == 0 and server.uploads() == []
    plain = source_run(tmp_path, server, settings=['source=Survey share wells'])  # words are fine
    assert plain['report'].ok and runs(tmp_path) == 1


def test_the_command_line_runs_it_and_prints_what_became_of_each_file(tmp_path, monkeypatch, capsys):
    server = Server(folder(tmp_path / 'procedure'))
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    args = cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + config(tmp_path)['share'], '--attribution', 'Team survey share',
                                    '--audience', 'me', '--json'])
    with client(server) as c: cli._source(args, c)
    out = json.loads(capsys.readouterr().out)
    assert out['sentence'] == 'Ran Survey share, version 2, on this computer, reading from Team survey share.'
    assert [i['state'] for i in out['report']['items']] == ['added'] * 3 and sorted(out['run']['outputs']) == sorted(WELLS)
    args = cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + config(tmp_path)['share'], '--system-label', 'me@share'])
    with client(server) as c, pytest.raises(SystemExit) as stopped: cli._source(args, c)
    assert stopped.value.code == cli.EXIT['refused'] and "Not run: name the team's system in words" in capsys.readouterr().err


# --- B6 rev 4: what a refused run keeps, and the words it prints -------------------------------------------------------

SHARED = ('Someone in this project already added the same file from this system and shared it with you. Use that file; adding '
          'your own copy from this procedure is not available on this deployment yet.')
SETTINGS = 'This file is already in the project with other settings.'
PLANTED = CODE.replace("    with open(config['counter']", "    print('log line', config['token'], 'planted-log-7c2e')\n    with open(config['counter']")


def row(i, f, state, code=None, sentence=None):
    return {**added(i, f), 'state': state, 'reason_code': code, 'sentence': sentence or RESULT.get(state)}


class Recording(Server):
    """Every request kept whole (URL, headers, raw body). The source run's rows answer as `plan` says; then the server
    takes an ordinary upload of a folder (each file waits, its head is sent, it is added)."""
    def __init__(self, procedure, plan):
        super().__init__(procedure)
        self.plan, self.raw, self.hand, self.folder_name, self.fail = plan, [], False, None, None

    def view(self, state):
        out = super().view(state)
        counts = {k: 0 for k in out['counts']}
        for i in self.items: counts[i['state'].replace('-', '_')] += 1
        return {**out, 'counts': counts, 'folder_name': self.folder_name, 'state': state if self.items and all(i['state'] != 'waiting' for i in self.items) else 'open'}

    def __call__(self, request):
        self.raw.append((str(request.url), dict(request.headers), request.content))
        operation = '/'.join(request.url.path.rsplit('/', 2)[-2:])
        if self.fail == operation or (operation == 'upload-runs/file' and self.fail == json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))['ordinal']):
            return httpx.Response(409, json={'error': {'code': 'conflict', 'message': 'The deployment refused this request.'}})
        if operation == 'upload-runs/file':
            header = json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))
            self.items[header['ordinal']] = {**self.items[header['ordinal']], 'state': 'added', 'sentence': RESULT['added']}
            return httpx.Response(200, json={'run_id': 'r' * 32, 'step': 'done', 'file': self.items[header['ordinal']]})
        if operation == 'upload-runs/list': return httpx.Response(200, json={'runs': []})
        if operation == 'upload-runs/start':
            body = json.loads(request.content)
            self.sent.append((operation, body)); self.folder_name = body['folder_name']
            if self.hand: self.items = [row(i, f, 'waiting') for i, f in enumerate(body['files'])]
            else: self.items = [row(i, f, *self.plan[i]) if i < len(self.plan) else added(i, f) for i, f in enumerate(body['files'])]
            return httpx.Response(200, json=self.view('closed'))
        return super().__call__(request)


def refused_then_uploaded_by_hand(tmp_path, plan, label=None, **options):
    """A source run whose rows answer as `plan` says, then the documented fallback run as printed: `ophiolite upload`."""
    root = tmp_path / 'procedure'; root.mkdir()
    (root / 'procedure.json').write_text(json.dumps(manifest())); (root / 'procedure.py').write_text(PLANTED % (WELLS, TOKEN, tuple(WELLS)))
    server = Recording(root, plan)
    args = cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + config(tmp_path)['share'], '--attribution', 'Team survey share',
                                    '--audience', 'me'] + (['--system-label', label] if label else []))
    return server, args


def test_a_refused_run_keeps_only_the_outputs_and_the_fallback_sends_no_log_or_run_record(tmp_path, monkeypatch, capsys):
    """B6 rev 4 (R3-1, disclosure): case 6 refuses every file. The recovery directory holds exactly the outputs the
    manifest lists; the log (with the configuration's token in it) and run.json stay outside it. The fallback printed,
    `ophiolite upload <kept>`, adds the outputs, and no request of it (URL, headers, the detection header, any body) holds
    the token, the log's line, the run record or its digest. Mutation: the recovery directory is the run folder (red)."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    server, args = refused_then_uploaded_by_hand(tmp_path, [('not-supported', 'source-shared', SHARED)] * 3)
    with client(server) as c, pytest.raises(SystemExit) as stopped: cli._source(args, c)
    assert stopped.value.code == cli.EXIT['conflict']
    printed = capsys.readouterr().out
    [line] = [l for l in printed.splitlines() if l.startswith('The files the procedure made are kept in ')]
    kept = Path(line.split(' To add them by hand: ophiolite upload ')[1])
    assert line == 'The files the procedure made are kept in %s. To add them by hand: ophiolite upload %s' % (kept, kept)
    assert sorted(p.name for p in kept.iterdir()) == ['well_a.json', 'well_b.json', 'well_c.json'] and runs(tmp_path) == 1
    server.hand, server.raw = True, []
    upload = cli.parser().parse_args(['upload', str(kept), '--attribution', 'Team survey share', '--audience', 'me', '--rights-confirmed'])
    with client(server) as c: cli._upload(upload, c)
    assert [i['state'] for i in server.items] == ['added'] * 3 and runs(tmp_path) == 1
    heads = [h for _, h, _ in server.raw if 'x-ophiolite-upload' in h]
    assert len(heads) == 3  # each file's detection header and first bytes were sent
    for url, headers, body in server.raw:
        seen = url + json.dumps(headers) + body.decode('latin-1') + ''.join(base64.b64decode(v).decode('latin-1') for k, v in headers.items() if k == 'x-ophiolite-upload')
        for secret in (TOKEN, 'planted-log-7c2e', 'log.txt', 'run.json', server.digest, '"outputs"', 'share.example'):
            assert secret not in seen, (secret, url)


def test_the_source_report_names_outputs_by_label_on_failed_and_decision_rows(tmp_path, monkeypatch, capsys):
    """B6 rev 4 (R3-7, R2-8): with `share_v2` as the system label, the whole default output reads as words: the
    opening sentence, the folder, and the rows that are not added (a refused row and a decision row) by their output
    labels; no role, no output file name and no `share_v2`, except in the recovery instruction's path. The request
    still names the system exactly. Mutation: the neutral rule removed, or rows by path (red)."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    server, args = refused_then_uploaded_by_hand(tmp_path, [('not-supported', 'source-shared', SHARED), ('needs-decision', 'other-settings', SETTINGS)],
                                                 label='share_v2')
    with client(server) as c, pytest.raises(SystemExit): cli._source(args, c)
    printed = capsys.readouterr().out.splitlines()
    kept = [l for l in printed if l.startswith('The files the procedure made are kept in ')]
    words = '\n'.join(l for l in printed if l not in kept)
    assert printed[0] == "Ran Survey share, version 2, on this computer, reading from a team's system."
    assert '  Well A location: Not supported - ' + SHARED in words and '  Well B location: Needs your decision - ' + SETTINGS in words
    for raw in ('share_v2', 'well_a', 'well_b', 'well_c', '.json'):
        assert raw not in words, raw
    assert words.splitlines()[1].startswith('Team system - 3 files')
    [(_, start)] = [(o, b) for o, b in server.uploads() if o == 'upload-runs/start']
    assert {f['source']['system'] for f in start['files']} == {'share_v2'} and start['folder_name'] == 'Team system'


@pytest.mark.parametrize('where', ['upload-runs/start', 1], ids=['before-the-first-upload', 'after-one-output-was-added'])
def test_an_upload_that_fails_after_the_run_keeps_the_outputs_and_says_where(tmp_path, monkeypatch, capsys, where):
    """B6 rev 5 (R4-3): the procedure ran; the upload then fails, at its start or after the first output was added.
    The error carries `kept` and the CLI prints the recovery instruction; the directory holds exactly the outputs with
    their bytes, no log.txt or run.json; nothing sent holds the token or the log; the procedure ran once. Mutation:
    the exception path deletes the outputs (red)."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    server, args = refused_then_uploaded_by_hand(tmp_path, [('waiting',)] * 3)
    server.fail = where
    with client(server) as c, pytest.raises(Exception) as failed: cli._source(args, c)
    kept = Path(failed.value.kept)
    assert capsys.readouterr().err.splitlines()[-1] == 'The files the procedure made are kept in %s. To add them by hand: ophiolite upload %s' % (kept, kept)
    assert sorted(p.name for p in kept.iterdir()) == ['well_a.json', 'well_b.json', 'well_c.json'] and runs(tmp_path) == 1
    [start] = [json.loads(body) for url, _, body in server.raw if url.endswith('/upload-runs/start')]
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in kept.iterdir()} == {f['path'].rsplit('/', 1)[1]: f['sha256'] for f in start['files']}
    assert [i['state'] for i in server.items][:1] == (['added'] if where == 1 else [])  # nothing was started, or one was added
    for url, headers, body in server.raw:
        for secret in (TOKEN, 'planted-log-7c2e', 'log.txt', 'run.json'):
            assert secret not in url + json.dumps(headers) + body.decode('latin-1'), secret


def test_an_unavailable_version_is_named_by_its_label_or_this_procedure_on_stderr(tmp_path, monkeypatch, capsys):
    """B6 rev 5 (R4-8): the catalogue lookup refusal says the version's readable label, or "this procedure" when none
    reads as a name or none is listed, never the catalogue name, which stays in --json's details."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    root = folder(tmp_path / 'procedure')
    args = lambda *more: cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + config(tmp_path)['share'], *more])
    for label, said in (('Survey share', 'Survey share'), ('survey_share_v2', 'this procedure'), (None, 'this procedure')):
        server = Server(root, state='private')
        if label is None: server.version = lambda: {**Server.version(server), 'name': 'team/other'}
        else: server.version = lambda label=label: {**Server.version(server), 'label': label}
        with client(server) as c, pytest.raises(SystemExit) as stopped: cli._source(args(), c)
        err = capsys.readouterr().err
        assert stopped.value.code == cli.EXIT['refused'] and err.strip() == 'Not run: %s has no enabled version in this project.' % said + ENABLE and 'team/survey-share' not in err
    with client(server) as c, pytest.raises(SystemExit): cli._source(args('--json'), c)
    assert json.loads(capsys.readouterr().out)['error']['details'] == {'name': 'team/survey-share'}


# --- E108 S2: later runs become versions (C4 tests 1-5, 7 and 10) ---------------------------------------------------

SURVEY_CODE = '''import json
from ophiolite import procedure
from ophiolite.writers import write_survey


@procedure
def fetch(inputs, settings):
    config = inputs['share'].config
    with open(config['counter'], 'a') as counter: counter.write('ran\\n')
    with open(config['data']) as given: data = json.load(given)
    return {'survey': write_survey(data['stations'], depth_unit='m', azimuth_reference=data['azimuth_reference'], depth_datum='KB')}
'''
A = [{'md': 100, 'inclination': 0, 'azimuth': 0}, {'md': 200, 'inclination': 10, 'azimuth': 0}]
B = [{'md': 100, 'inclination': 0, 'azimuth': 0}, {'md': 200, 'inclination': 12, 'azimuth': 0}]
NEWER_SENTENCE = 'Version 2 was added by Bob, 1 day ago. Your change was not sent. Either get version 2 and look at it, or send yours as a new item.'


def survey_folder(root):
    root.mkdir(parents=True)
    m = manifest()
    m['inputs'][0]['config_keys'] = ['counter', 'data']
    m['outputs'] = [{'role': 'survey', 'label': 'Survey', 'class': 'version', 'kind': 'deviation-csv/1'}]
    (root / 'procedure.json').write_text(json.dumps(m))
    (root / 'procedure.py').write_text(SURVEY_CODE)
    assert procedures.validate(root)['valid'], procedures.validate(root)
    return root


class Versions(Server):
    """The upload routes with versions as C1-C3 serve them: a file naming `append_to` at the head is that item's next
    version (already here when its bytes and declarations equal the head, else `newer-version` when the head moved); a run
    is replayed by its command id; `land` rows are added at start, the others wait for their file (sent by `send`)."""
    def __init__(self, procedure):
        super().__init__(procedure)
        self.assets, self.runs, self.land, self.clock = {}, {}, None, 1791633600

    def version_of(self, f):
        decl = json.dumps(f.get('decisions') or {}, sort_keys=True)
        if f.get('append_to') is None:
            ident = 'item-%d' % (len(self.assets) + 1)
            self.assets[ident] = [(f['sha256'], f['sha256'], decl, 'alice', self.clock)]
            return 'added', None, ident, f['sha256']
        versions = self.assets[f['append_to']]
        if versions[-1][1:3] == (f['sha256'], decl): return 'already-here', None, f['append_to'], versions[-1][0]  # the head first (R5 D3)
        if versions[-1][0] != f['expected_parent']: return 'needs-decision', 'newer-version', None, None
        revision = hashlib.sha256((f['sha256'] + decl).encode()).hexdigest() if any(v[1] == f['sha256'] for v in versions) else f['sha256']
        versions.append((revision, f['sha256'], decl, 'alice', self.clock))
        return 'added', None, f['append_to'], revision

    def settle(self, run, i):
        state, code, asset, revision = self.version_of(run['files'][i])
        run['items'][i] = {**run['items'][i], 'state': state, 'reason_code': code, 'asset_id': asset, 'revision': revision, 'sentence': RESULT.get(state)}

    def answer(self, run):
        self.items = run['items']
        return httpx.Response(200, json={**self.view('closed' if all(i['state'] != 'waiting' for i in run['items']) else 'open'), 'items': run['items']})

    def __call__(self, request):
        operation = '/'.join(request.url.path.rsplit('/', 2)[-2:])
        if operation == 'upload-runs/start':
            body = json.loads(request.content); self.sent.append((operation, body))
            run = self.runs.get(body['command_id'])
            if run is None:
                run = self.runs[body['command_id']] = {'files': body['files'], 'items': [row(i, f, 'waiting') for i, f in enumerate(body['files'])]}
                for i in range(len(body['files']) if self.land is None else self.land): self.settle(run, i)
            self.current = run
            return self.answer(run)
        if operation == 'upload-runs/status': self.sent.append((operation, {})); return self.answer(self.current)
        if operation == 'upload-runs/file':
            header = json.loads(base64.b64decode(request.headers['x-ophiolite-upload'])); self.sent.append((operation, header))
            self.settle(self.current, header['ordinal'])
            return httpx.Response(200, json={'run_id': 'r' * 32, 'step': 'done', 'file': self.current['items'][header['ordinal']]})
        if operation == 'applications/result-history':
            body = json.loads(request.content)
            revisions = [{'number': n + 1, 'revision': v[0], 'by': v[3], 'published_at': v[4]} for n, v in enumerate(self.assets[body['asset_id']])]
            return httpx.Response(200, json={'asset_id': body['asset_id'], 'revisions': revisions, 'display': {'member_names': {'alice': 'Alice', 'bob': 'Bob'}}})
        return super().__call__(request)


def survey_run(tmp_path, server, stations, azimuth='true-north', **options):
    data = tmp_path / 'data.json'
    data.write_text(json.dumps({'stations': stations, 'azimuth_reference': azimuth}))
    path = tmp_path / 'share.json'
    path.write_text(json.dumps({'counter': str(tmp_path / 'runs.txt'), 'data': str(data)}))
    with client(server) as c:
        return c.source_run('team/survey-share', {'share': str(path)}, cache=tmp_path / 'cache', attribution='Team survey share', audience='me',
                            work=tmp_path / 'held', **options)


def held_survey(tmp_path):
    return json.loads((tmp_path / 'held' / 'held.json').read_text())['sources'][json.dumps(['team/survey-share', 'Team survey share', 'survey'])]


def test_unchanged_second_run_is_nothing_changed_with_no_requests(tmp_path):
    """Test 1. Mutation: the held comparison skipped (the second run starts an upload)."""
    server = Versions(survey_folder(tmp_path / 'procedure'))
    first = survey_run(tmp_path, server, A)
    assert first['report'].ok and [i['state'] for i in first['report'].items] == ['added']
    before = len(server.uploads())
    again = survey_run(tmp_path, server, A)
    assert (again['outcome'], again['outcome_sentence']) == ('nothing-changed', 'This is the same as the version you hold; nothing was sent.')
    assert len(server.uploads()) == before and runs(tmp_path) == 2  # the procedure ran; nothing was sent


def test_changed_run_gives_version_two(tmp_path):
    """Test 2: the file names the held item and version. Mutation: no `append_to` (a second item)."""
    server = Versions(survey_folder(tmp_path / 'procedure'))
    survey_run(tmp_path, server, A)
    v1 = held_survey(tmp_path)
    second = survey_run(tmp_path, server, B)
    [(_, start)] = [(o, b) for o, b in server.uploads() if o == 'upload-runs/start'][1:]
    assert (start['files'][0]['append_to'], start['files'][0]['expected_parent']) == ('item-1', v1['revision'])
    assert second['report'].ok and [(i['state'], i['asset_id']) for i in second['report'].items] == [('added', 'item-1')]
    assert len(server.assets['item-1']) == 2 and held_survey(tmp_path)['revision'] == server.assets['item-1'][1][0] != v1['revision']


def test_declaration_only_change_gives_version_two(tmp_path):
    """Test 3. Mutation: the held comparison ignores declarations (nothing changed is said)."""
    server = Versions(survey_folder(tmp_path / 'procedure'))
    survey_run(tmp_path, server, A, 'true-north')
    second = survey_run(tmp_path, server, A, 'grid-north')
    assert second['outcome'] == 'sent' and [(i['state'], i['asset_id']) for i in second['report'].items] == [('added', 'item-1')]
    v1, v2 = server.assets['item-1']
    assert v1[1] == v2[1] and v1[0] != v2[0] and held_survey(tmp_path)['revision'] == v2[0]


def test_competing_run_gives_newer_version_exists(tmp_path, monkeypatch):
    """Test 4: Bob's folder added version 2 on 12 October; this folder still holds version 1 (read on 13 October)."""
    from ophiolite import exchange
    from ophiolite.exchange import NewerVersionExists
    monkeypatch.setitem(exchange.Exchange.__init__.__kwdefaults__, 'clock', lambda: 1791892800)  # 13 October 2026, noon UTC
    server = Versions(survey_folder(tmp_path / 'procedure'))
    survey_run(tmp_path, server, A)
    server.assets['item-1'].append(('b' * 64, 'c' * 64, '{}', 'bob', 1791806400))
    with pytest.raises(NewerVersionExists) as raised:
        survey_run(tmp_path, server, B)
    assert str(raised.value) == NEWER_SENTENCE


def test_a_b_a_gives_earlier_version(tmp_path):
    """Test 5: the row says which version it was (C3's sentence, served); nothing new is held."""
    server = Versions(survey_folder(tmp_path / 'procedure'))
    survey_run(tmp_path, server, A); survey_run(tmp_path, server, B)
    held = held_survey(tmp_path)
    plain = server.version_of
    def earlier(f):
        if f.get('append_to') and f['sha256'] == server.assets['item-1'][0][1]: return 'not-supported', 'earlier-version', None, None
        return plain(f)
    server.version_of = earlier
    third = survey_run(tmp_path, server, A)
    assert [(i['state'], i['reason_code']) for i in third['report'].items] == [('not-supported', 'earlier-version')]
    assert held_survey(tmp_path) == held


def test_killed_after_output_one_resumes_without_rerunning(tmp_path, monkeypatch):
    """Test 7: of three outputs one lands, then the process stops. The next call sends the other two from the saved
    send under the same command id; the procedure runs once. Mutation: the procedure run again on resume (2 runs)."""
    from ophiolite.upload_runs import UploadRuns
    server = Versions(folder(tmp_path / 'procedure'))
    server.land = 1
    real, calls = UploadRuns._file, []
    def stop_once(self, run_id, ordinal, files):
        calls.append(ordinal)
        if len(calls) == 1: raise KeyboardInterrupt('stopped')
        return real(self, run_id, ordinal, files)
    monkeypatch.setattr(UploadRuns, '_file', stop_once)
    with client(server) as c, pytest.raises(KeyboardInterrupt):
        c.source_run('team/survey-share', config(tmp_path), cache=tmp_path / 'cache', attribution='Team survey share', audience='me', work=tmp_path / 'held')
    assert runs(tmp_path) == 1 and json.loads((tmp_path / 'held' / 'held.json').read_text())['pending_source'] is not None
    with client(server) as c:
        resumed = c.source_run('team/survey-share', config(tmp_path), cache=tmp_path / 'cache', attribution='Team survey share', audience='me', work=tmp_path / 'held')
    starts = [b['command_id'] for o, b in server.uploads() if o == 'upload-runs/start']
    assert len(set(starts)) == 1 and len(starts) == 2 and runs(tmp_path) == 1
    assert resumed['report'].ok and [i['state'] for i in resumed['report'].items] == ['added'] * 3 and calls == [1, 1, 2]
    assert json.loads((tmp_path / 'held' / 'held.json').read_text())['pending_source'] is None



def test_the_command_line_keeps_what_was_added_in_ophiolite_held_by_default(tmp_path, monkeypatch, capsys):
    """7-5: `source run` takes E70's `--work`, default `.ophiolite-held` in the current folder, as check/get/send do; an
    unchanged second run prints the nothing-changed sentence. Mutation: `--work` not passed on (a second upload)."""
    server = Versions(survey_folder(tmp_path / 'procedure'))
    data = tmp_path / 'data.json'; data.write_text(json.dumps({'stations': A, 'azimuth_reference': 'true-north'}))
    share = tmp_path / 'share.json'; share.write_text(json.dumps({'counter': str(tmp_path / 'runs.txt'), 'data': str(data)}))
    args = cli.parser().parse_args(['source', 'run', 'team/survey-share', '--system', 'share=' + str(share), '--attribution', 'Team survey share', '--audience', 'me'])
    assert args.work == Path('.ophiolite-held')
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    for _ in range(2):
        with client(server) as c: cli._source(args, c)
    assert capsys.readouterr().out.splitlines()[-1] == 'This is the same as the version you hold; nothing was sent.'
    assert len([o for o, _ in server.uploads() if o == 'upload-runs/start']) == 1 and (tmp_path / '.ophiolite-held' / 'held.json').is_file()

@pytest.mark.parametrize('receipt,accepted', [
    ({'revision': 'd' * 64, 'sha256': 'DIGEST'}, True),  # a declared-version: its revision is not the bytes' digest
    ({'revision': 'DIGEST'}, True),  # a server from before E108
    ({'revision': 'd' * 64}, False),
    ({'revision': 'DIGEST', 'sha256': 'e' * 64}, False),  # contradictory (Q2)
])
def test_declared_version_receipt_is_checked_by_sha256(receipt, accepted):
    """Test 10 (N2, Q2). Mutations: the check by revision only (row 1 refused); `revision == digest or sha256 == digest`
    (row 4 accepted)."""
    from ophiolite.publish import receipt_matches
    digest = hashlib.sha256(b'bytes').hexdigest()
    given = {k: (digest if v == 'DIGEST' else v) for k, v in receipt.items()}
    assert receipt_matches(given, digest) is accepted
