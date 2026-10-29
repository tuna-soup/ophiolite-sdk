"""E107a C6: read a file of a folder upload on this computer with one of the project's read procedures, and send what
it made into the same upload (`ophiolite intake read RUN FILE`).

The upload's row is a file Ophiolite does not read itself but a read procedure version of the project recognises
(`needs-procedure`, with the versions listed). Before anything runs, the local file must be the row's file (its size
and sha256, C2). The version is read again (a withdrawal ends it), fetched and checked by digest, and a version you
neither registered nor trust asks E105b's question. It runs into a new `attempt-<n>` folder of this file's state
folder, `<folder>/<run>-<ordinal>/`; `convert.json` (the command id, the declaration and the resolved settings) is
written there atomically before the first request. A later `intake read` of the same file finds it, checks each
saved output against it and sends those exact bytes again under the same command: the procedure does not run again
(D5), and only outputs the upload has not got yet are sent. With --keep-original the original is sent first
(`upload-runs/convert-original`, again on a resume: the deployment answers the staged original) and is kept beside
each file read from it (C4)."""
import base64
import hashlib
import json
import os
import re
import uuid
from pathlib import Path, PurePosixPath

from . import procedures
from .models.api import UploadRunConversion
from .errors import IntegrityConflict
from .procedures import NotRun

STATE = 'ophiolite.intake-read/1'
SENTENCES = {
    'not-served': 'This deployment does not read files on your computer with read procedures. Nothing ran and nothing was sent.',
    'no-file': 'Not read: no file of this upload named {name} can be read on your computer.',
    'several-files': 'Not read: several files of this upload are named {name}: {paths}. Give the file\'s path in the upload.',
    'other-file': 'Not read: {name} on this computer is not the file chosen for this upload: its size or digest differs. Nothing ran and nothing was sent.',
    'keep-changed': 'Not read: this file was read here before {how} keeping the original, under the same command. Run it again {flag}, or remove {state} to read it again.',
    'several-versions': 'Not run: several read procedure versions can read this file. Choose one with --version: {versions}.',
    'not-listed': 'Not run: {digest} is not a read procedure version listed for this file. Choose one of: {versions}.',
    'no-file-slot': 'Not run: {label}, version {version}, does not take one file to read.',
    'saved-output-changed': 'Not sent: {file}, made earlier on this computer for this file, changed since it was made. Remove {state} to read the file again.',
}


def state_root():
    """Where a file's read state is kept (OPHIOLITE_INTAKE_STATE, else the user state directory)."""
    given = os.environ.get('OPHIOLITE_INTAKE_STATE')
    if given: return Path(given)
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'ophiolite' / 'intake'


def refused(code, details=None, **words):
    return NotRun(code, '', details or {}, sentence=SENTENCES[code].format(**words))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def _named(version):
    return '%s, version %d (%s)' % (version['label'], version['version'], version['digest'])


def _row(report, given):
    """The upload's row for FILE: a primary row that can be read on your computer (or is being read), by its path in
    the upload or its file name."""
    rows = [i for i in report.items if i.get('role', 'primary') == 'primary' and i['state'] in ('needs-procedure', 'converting', 'converted')]
    text = str(given).replace(os.sep, '/')
    exact = [i for i in rows if i['path'] == text]
    named = exact or [i for i in rows if PurePosixPath(i['path']).name == Path(given).name]
    if not named: raise refused('no-file', {'run_id': report.run_id}, name=Path(given).name)
    if len(named) > 1: raise refused('several-files', {'paths': [i['path'] for i in named]}, name=Path(given).name, paths=', '.join(i['path'] for i in named))
    return named[0]


def _load(path):
    """The saved declaration, or None: a missing, unreadable or foreign file is no state (a temporary file a kill left is
    never read)."""
    try: saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
    return saved if isinstance(saved, dict) and saved.get('schema') == STATE else None


def _attempts(state):
    found = [p for p in state.iterdir() if p.is_dir() and re.fullmatch(r'attempt-[0-9]+', p.name)] if state.exists() else []
    return sorted(found, key=lambda p: int(p.name.split('-')[1]))


def _choose(row, version):
    listed = row.get('procedures') or []
    if version is not None:
        chosen = [v for v in listed if v['digest'] == version]
        if not chosen: raise refused('not-listed', {'digest': version}, digest=version, versions='; '.join(map(_named, listed)))
        return chosen[0]
    if len(listed) != 1: raise refused('several-versions', {'versions': [v['digest'] for v in listed]}, versions='; '.join(map(_named, listed)))
    return listed[0]


def _run(client, row, path, state, version, settings, prompt, yes, cache, keep_original=False):
    """Run the chosen version on this computer into a new attempt folder; the declaration it makes, not yet saved."""
    chosen = _choose(row, version)
    found = client.procedure_get(chosen['digest'])
    if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=procedures._day(found['withdrawn_at']))
    digest = found['digest']
    folder = client._cached(digest, cache)
    manifest = procedures.manifest_of(folder)
    slots = [i['slot'] for i in manifest['inputs'] if i.get('class') == 'file']
    if manifest['step'] != 'read' or len(slots) != 1: raise refused('no-file-slot', {'digest': digest}, label=manifest['label'], version=manifest['version'])
    values = procedures._setting_values(manifest, settings)  # E5: a missing or wrong setting is refused before anything is asked or sent
    if not (found['trusted'] or found['mine']):
        if not yes:
            if prompt is None: raise NotRun('trust-needed', '', {'digest': digest})
            if not prompt(procedures.question(found)): raise NotRun('declined', '', {'digest': digest})
        client.procedure_trust(digest)
    procedures._before_run(folder)
    earlier = _attempts(state)
    state.mkdir(parents=True, exist_ok=True)
    destination = state / ('attempt-%d' % (int(earlier[-1].name.split('-')[1]) + 1 if earlier else 1))
    made = procedures.run(folder, destination, {slots[0]: [path]}, settings=settings, expected_digest=digest)['run']
    roles = [{'role': role, 'sha256': out['sha256'], 'bytes': (destination / out['file']).stat().st_size, 'name': out['file'],
              'declared': {k: v for k, v in (out.get('declared') or {}).items()}} for role, out in made['outputs'].items()]
    body = {'project_id': client.project, 'run_id': row['run_id'], 'ordinal': row['ordinal'], 'command_id': uuid.uuid4().hex,
            'procedure': {'digest': digest}, 'original': {'sha256': row['sha256'], 'bytes': row['bytes']}, 'roles': roles, 'keep_original': bool(keep_original),
            'settings': values}  # E5: declared, and recorded in each output's read_by
    return {'schema': STATE, 'file': row['path'], 'procedure': {'digest': digest, 'name': manifest['name'], 'label': manifest['label'], 'version': manifest['version']},
            'settings': values, 'attempt': destination.name, 'earlier_attempts': [p.name for p in earlier],
            'outputs': {role: out['file'] for role, out in made['outputs'].items()}, 'body': body}


def _saved_outputs(state, saved):
    """Each saved output's bytes, checked against the saved declaration (D5)."""
    out = {}
    for role in saved['body']['roles']:
        file = state / saved['attempt'] / saved['outputs'][role['role']]
        try: raw = file.read_bytes()
        except OSError: raw = None
        if raw is None or len(raw) != role['bytes'] or hashlib.sha256(raw).hexdigest() != role['sha256']:
            raise refused('saved-output-changed', {'role': role['role']}, file=str(file), state=str(state))
        out[role['role']] = raw
    return out


def read(client, run_id, path, *, keep_original=False, version=None, folder=None, settings=None, prompt=None, yes=False, cache=None):
    """Read PATH, a file of upload RUN_ID that can be read on your computer, with a read procedure version listed for it,
    and send what it made into the same upload. Returns {sentence, report, conversion, state, attempt, earlier_attempts,
    resumed}. Raises NotRun before anything is sent (and the deployment's refusal after)."""
    path = Path(path)
    runs = client.upload_runs
    if not runs.reads(): raise refused('not-served')
    row = {**_row(runs.status(run_id), path), 'run_id': run_id}
    if (path.stat().st_size, _sha256(path)) != (row['bytes'], row['sha256']):  # C2: with or without --keep-original
        raise refused('other-file', {'sha256': row['sha256'], 'bytes': row['bytes']}, name=path.name)
    state = Path(folder or state_root()) / ('%s-%d' % (run_id, row['ordinal']))
    saved = _load(state / 'convert.json')
    resumed = saved is not None and saved['body']['original'] == {'sha256': row['sha256'], 'bytes': row['bytes']}
    if resumed and bool(saved['body'].get('keep_original')) != bool(keep_original):  # the declaration under its command cannot change
        raise refused('keep-changed', {'keep_original': bool(saved['body'].get('keep_original'))}, how='with' if keep_original is False else 'without',
                      flag='with --keep-original' if keep_original is False else 'without --keep-original', state=str(state))
    if resumed: raw = _saved_outputs(state, saved)
    else:
        saved = _run(client, row, path, state, version, settings, prompt, yes, cache, keep_original)
        raw = _saved_outputs(state, saved)
        procedures._save(state / 'convert.json', saved)  # before the first request: a kill from here on resumes these bytes
    answer = _declare(client, saved['body'])
    kept = saved['body'].get('keep_original') and answer['conversion']['state'] in ('declared', 'partial')
    original = path.read_bytes() if kept else None  # checked against the row above (size and sha256)
    if kept: answer = _keep(client, saved['body'], original)  # C4 (D2): before any output; a resume is answered the staged original
    for role in answer['conversion']['roles']:
        if answer['conversion']['state'] not in ('declared', 'partial'): break
        if role.get('outcome') is None:
            try: answer = _send(client, saved['body'], role['role'], raw[role['role']])
            except IntegrityConflict as error:  # H1: the staged original expired before this output; send it again, then the output
                if original is None or ((getattr(error, 'details', None) or {}).get('reason') != 'original-expired'): raise
                _keep(client, saved['body'], original)
                answer = _send(client, saved['body'], role['role'], raw[role['role']])
    report = runs.status(run_id)
    conversion, p = answer['conversion'], saved['procedure']
    sentence = 'Read %s on this computer with %s, version %d.%s' % (PurePosixPath(row['path']).name, p['label'], p['version'],
                                                                     ' ' + conversion['sentence'] if conversion.get('sentence') else '')
    if saved['earlier_attempts']: sentence += ' Earlier attempts left in %s: %s.' % (state, ', '.join(saved['earlier_attempts']))
    return {'sentence': sentence, 'report': report, 'conversion': conversion, 'state': str(state), 'attempt': saved['attempt'],
            'earlier_attempts': saved['earlier_attempts'], 'resumed': resumed}


def _declare(client, body):
    from .upload_runs import _checked
    return _checked(UploadRunConversion, client._post('upload-runs', 'convert', body, retry=True), 'read on your computer')


def _keep(client, body, raw):
    from .upload_runs import _checked
    header = {'project_id': client.project, 'run_id': body['run_id'], 'ordinal': body['ordinal']}
    extra = {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json.dumps(header, separators=(',', ':')).encode()).decode()}
    return _checked(UploadRunConversion, client._post_bytes('upload-runs', 'convert-original', raw, extra_headers=extra, retry=True), 'read on your computer')


def _send(client, body, role, raw):
    from .upload_runs import _checked
    header = {'project_id': client.project, 'run_id': body['run_id'], 'ordinal': body['ordinal'], 'role': role}
    extra = {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json.dumps(header, separators=(',', ':')).encode()).decode()}
    return _checked(UploadRunConversion, client._post_bytes('upload-runs', 'convert-output', raw, extra_headers=extra, retry=True), 'read on your computer')
