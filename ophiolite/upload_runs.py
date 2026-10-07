"""E55: a folder or a .zip in one upload, with one report.

`client.upload_runs.upload(path, attribution=..., audience=[...], rights_confirmed=True)` lists every file of the folder
(or zip) with its size and digest, starts one folder upload on the server and sends each file in turn: its first
64 KiB first, so the server decides what kind of file it is, then the whole file only when the server asks for it
(a file above the deployment's request limit goes in parts, as `upload_data` sends one). The answer is the upload's
report: one outcome per file (Added, Already here, Needs your decision, Not read, Not supported), with the reason in
words. Nothing is converted or repaired, and no wellbore is linked unless you ask (`associate_matches`).

Running the same upload again after an interruption continues the unfinished upload of the same folder (the same
paths, sizes and digests): files already added are not sent again. `new=True` starts another upload instead.
"""
import base64
import csv
import hashlib
import io
import json
import os
import stat
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .errors import IntegrityConflict, Refused, ValidationFailed, VerificationFailed
from .models.api import UploadRun, UploadRunsListAnswer, UploadRunStep

HEAD = 65536
MAX_FILES = 500
ZIP_RATIO = 100  # an entry, or the whole zip, unpacked to more than this many times its packed size is refused
ZIP_TOTAL = 512 * 1024 * 1024
LINKS = 50  # links per associate call
RESULT = {'added': 'Added', 'already-here': 'Already here', 'needs-decision': 'Needs your decision', 'not-read': 'Not read',
          'not-supported': 'Not supported', 'cancelled': 'Cancelled', 'waiting': 'Not sent yet', 'reading': 'Being added'}
OUTCOMES = ('added', 'already-here', 'needs-decision', 'not-read', 'not-supported')
COLUMNS = ('path', 'result', 'kind', 'read', 'reason', 'asset')


def _checked(model, answer, what):
    from pydantic import ValidationError
    try: model.model_validate(answer)
    except (ValidationError, ValueError, TypeError): raise VerificationFailed('The %s answered outside its documented shape.' % what) from None
    return answer


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# --- what is sent ------------------------------------------------------------------------------------------------------

class File:
    """One file of the folder or zip: its path in the upload, size and digest; its bytes are read only when sent."""
    def __init__(self, path, size, sha256, read, disk=None):
        self.path, self.size, self.sha256, self._read, self.disk = path, size, sha256, read, disk

    def head(self):
        if self.disk is None: return self._read()[:HEAD]
        with open(self.disk, 'rb') as stream: return stream.read(HEAD)

    def changed(self):
        return IntegrityConflict('%s changed after it was chosen. Choose the folder again to add the new content.' % self.path)

    def whole(self):
        raw = self._read()
        if len(raw) != self.size or hashlib.sha256(raw).hexdigest() != self.sha256: raise self.changed()
        return raw

    def source(self):
        """For a file sent in parts: read from disk one part at a time (a zip entry is held in memory)."""
        from .publish import FileSource
        if self.disk is None: return FileSource(self.whole())
        source = FileSource(self.disk)
        if source.size != self.size or source.sha256() != self.sha256: raise self.changed()
        return source


class Folder:
    def __init__(self, name, files):
        self.name, self.files = name, files

    def listing(self): return [{'path': f.path, 'bytes': f.size, 'sha256': f.sha256} for f in self.files]


def _too_many(n):
    if n > MAX_FILES: raise Refused('A folder upload holds at most %d files; this folder has %d. Choose a smaller folder.' % (MAX_FILES, n))
    if n == 0: raise Refused('This folder has no files. Nothing was sent.')


def _digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def open_folder(path):
    """Every regular file under PATH, by its path below the folder's parent (the folder's name first, as a browser
    names a chosen folder's files). A link is refused: it is not followed, and nothing is sent."""
    root = Path(path)
    found = []
    for directory, folders, names in os.walk(root, followlinks=False):
        folders.sort()
        for name in sorted(names) + [f for f in folders if os.path.islink(os.path.join(directory, f))]:
            full = os.path.join(directory, name)
            relative = PurePosixPath(root.name, *Path(full).relative_to(root).parts).as_posix()
            mode = os.lstat(full).st_mode
            if not stat.S_ISREG(mode): raise Refused('This folder contains %s, which is not allowed. Nothing was sent.' % relative, 'Links and special files are not followed.')
            found.append((relative, full))
        folders[:] = [f for f in folders if not os.path.islink(os.path.join(directory, f))]
    found.sort()
    _too_many(len(found))
    return Folder(root.name, [File(rel, os.path.getsize(full), _digest(full), lambda full=full: Path(full).read_bytes(), full) for rel, full in found])


def open_zip(path, file_bytes):
    """The files of a .zip, checked before anything is sent: no entry outside the folder, no link, none over the
    deployment's file limit, none (and not the whole) more than 100 times its packed size or over 512 MiB unpacked."""
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
        entries = [i for i in archive.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as error:
        raise Refused('This zip file cannot be opened. Nothing was sent.', details={'technical': str(error)[:300]}) from None
    _too_many(len(entries))
    def refuse(name): raise Refused('This zip file contains %s, which is not allowed. Nothing was sent.' % name[:200])
    total = 0
    for i in entries:
        parts = PurePosixPath(i.filename).parts
        if (i.filename.startswith(('/', '\\')) or '\\' in i.filename or ':' in (parts[0] if parts else '') or '..' in parts
                or stat.S_ISLNK(i.external_attr >> 16) or i.flag_bits & 0x1):
            refuse(i.filename)
        if i.file_size > file_bytes or i.file_size > ZIP_RATIO * max(i.compress_size, 1) or i.file_size > ZIP_TOTAL: refuse(i.filename)
        total += i.file_size
    if total > ZIP_TOTAL or total > ZIP_RATIO * max(path.stat().st_size, 1):
        raise Refused('This zip file contains %s, which is not allowed. Nothing was sent.' % path.name, 'Together its files unpack to more than 512 MiB or more than 100 times the zip.')
    def reader(info):
        def read():
            with archive.open(info) as stream: raw = stream.read(info.file_size + 1)
            if len(raw) != info.file_size: refuse(info.filename)  # the entry is not the size its header states
            return raw
        return read
    files = []
    for i in entries:
        read = reader(i)
        try: raw = read()
        except (zipfile.BadZipFile, OSError, ValueError, EOFError) as error:
            raise Refused('This zip file cannot be opened. Nothing was sent.', details={'technical': str(error)[:300]}) from None
        files.append(File(i.filename, i.file_size, hashlib.sha256(raw).hexdigest(), read)); del raw
    return Folder(path.stem, files)


# --- the report --------------------------------------------------------------------------------------------------------

class Report:
    """A folder upload as its report shows it. `counts` names the five outcomes (and `cancelled` when any file was
    stopped or skipped); `ok` is true when every file was added or is already here."""
    def __init__(self, view):
        self.view = view
        self.run_id, self.state, self.label, self.items = view['run_id'], view['state'], view['label'], view['items']
        counts = {k.replace('_', '-'): v for k, v in view['counts'].items()}
        self.counts = {k: counts[k] for k in OUTCOMES}
        if counts['cancelled']: self.counts['cancelled'] = counts['cancelled']
        if counts['waiting'] or counts['reading']: self.counts['not-sent'] = counts['waiting'] + counts['reading']

    @property
    def ok(self): return self.state == 'closed' and all(i['state'] in ('added', 'already-here') for i in self.items)

    def rows(self):
        return [{'path': i['path'], 'result': RESULT[i['state']], 'kind': i.get('kind') or '', 'read': i.get('read') or '',
                 'reason': i.get('sentence') or '', 'asset': i.get('asset_id') or ''} for i in self.items]

    def text(self):
        said = ', '.join('%d %s' % (n, RESULT.get(k, 'Not sent yet')) for k, n in self.counts.items())
        lines = ['%s - %d files - %s. %s' % (self.view['folder_name'], self.view['files'], self.label, said)]
        lines += ['  %s: %s%s' % (r['path'], r['result'], ' - ' + r['reason'] if r['reason'] else '') for r in self.rows() if r['result'] not in ('Added', 'Already here')]
        return '\n'.join(lines)

    def save(self, path):
        """Write the report: JSON (the whole report) for a .json path, otherwise CSV with `path,result,kind,read,reason,asset`."""
        path = Path(path)
        if path.suffix.lower() == '.json': text = json.dumps(self.view, indent=2) + '\n'
        else:
            out = io.StringIO(); writer = csv.DictWriter(out, COLUMNS, lineterminator='\n'); writer.writeheader(); writer.writerows(self.rows()); text = out.getvalue()
        path.write_text(text, encoding='utf-8')
        return path

    def __repr__(self): return '<Report %s: %s %s>' % (self.view['folder_name'], self.label, self.counts)


# --- the client --------------------------------------------------------------------------------------------------------

class UploadRuns:
    def __init__(self, client):
        self.client = client
        self.sent_bytes = 0  # the file bytes this object sent (heads, bodies and parts), for a resumed upload's account

    def _call(self, operation, body, model, retry=True):
        return _checked(model, self.client._post('upload-runs', operation, body, retry=retry), 'folder upload ' + operation)

    # one-call operations

    def status(self, run_id): return Report(self._call('status', {'run_id': run_id}, UploadRun))

    def list(self): return self._call('list', {}, UploadRunsListAnswer)['runs']

    def cancel(self, run_id):
        """Stop the upload: files not yet added are cancelled; what was added stays."""
        return Report(self._call('cancel', {'run_id': run_id}, UploadRun))

    def associate(self, run_id, links):
        """Link files to wellbores: `links` is [(ordinal, entity_id)], at most 50 at a time are sent; the same link again
        adds nothing. Returns (report, links added)."""
        added, view = 0, None
        links = [{'ordinal': o, 'entity_id': e} for o, e in links]
        for i in range(0, len(links), LINKS):
            view = self._call('associate', {'run_id': run_id, 'links': links[i:i + LINKS]}, UploadRun); added += view['linked']
        return (Report(view) if view else self.status(run_id)), added

    def decide(self, run_id, ordinals, choice, declared=None, command_id=None):
        """Answer files that need a decision: 'add-separately', 'add-new', 'declare' (with `declared`) or 'skip'. Files
        to add go back to waiting; send them with `send(run_id, open(path))`."""
        body = {'run_id': run_id, 'ordinals': sorted(ordinals), 'choice': choice, **({'declared': dict(declared or {})} if choice == 'declare' else {})}
        body['command_id'] = command_id or _sha(['decide', body])
        return Report(self._call('decide', body, UploadRun))

    def share(self, run_id, readers):
        """Name the project members who may read this report (the whole list; empty revokes). Its files keep their own access."""
        return Report(self._call('share', {'run_id': run_id, 'readers': sorted(set(readers))}, UploadRun, retry=False))

    def report(self, run, path):
        """Save a report (a Report or a run id) as CSV, or as JSON for a .json path."""
        return (run if isinstance(run, Report) else self.status(run)).save(path)

    # the whole journey

    def open(self, path):
        """The folder or zip at PATH as it will be sent (checked; nothing is sent)."""
        path = Path(path)
        if path.is_dir(): return open_folder(path)
        if path.suffix.lower() == '.zip': return open_zip(path, self.client.served_limits()['file_bytes'])
        raise Refused('Choose a folder or a .zip file.')

    def upload(self, path, *, attribution, rights_confirmed, audience=(), well_notes='', declare=None, skip_decisions=False,
               associate_matches=False, new=False, progress=None):
        """Upload a folder or a .zip and return its Report. `declare` {kind: {field: value}} answers the files of that
        kind (profile, e.g. 'esri-ascii-grid/1') that need you to say what their values mean; `skip_decisions` skips
        every other file that needs a decision; `associate_matches` links each file to the one wellbore its header names.
        `progress(report)` is called after each file."""
        if rights_confirmed is not True:
            raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience.'])
        folder = self.open(path)
        run = None if new else self.unfinished(folder)
        if run is None:
            body = {'command_id': uuid.uuid4().hex, 'folder_name': folder.name[:160], 'files': folder.listing(), 'attribution': attribution,
                    'well_notes': well_notes, 'audience': list(audience), 'rights_confirmed': True}
            run = self._call('start', body, UploadRun)['run_id']
        report = self.send(run, folder, progress)
        if declare or skip_decisions:
            for kind, values in (declare or {}).items():
                ordinals = [i['ordinal'] for i in report.items if i['state'] == 'needs-decision' and i['reason_code'] == 'needs-declarations' and i['profile'] == kind]
                if ordinals: self.decide(run, ordinals, 'declare', values)
            if skip_decisions:
                ordinals = [i['ordinal'] for i in self.status(run).items if i['state'] == 'needs-decision' and i['role'] == 'primary']
                if ordinals: self.decide(run, ordinals, 'skip')
            report = self.send(run, folder, progress)
        if associate_matches:
            links = [(i['ordinal'], i['proposal']['entity_id']) for i in report.items if i.get('proposal')]
            if links: report, _ = self.associate(run, links)
        return report

    def unfinished(self, folder):
        """The id of your unfinished upload of this folder (the same name, paths, sizes and digests), or None."""
        listing = folder.listing()
        for summary in self.list():
            if summary['state'] != 'open' or summary['folder_name'] != folder.name[:160]: continue
            view = self.status(summary['run_id']).view
            if [{'path': i['path'], 'bytes': i['bytes'], 'sha256': i['sha256']} for i in view['items']] == listing: return summary['run_id']
        return None

    def send(self, run_id, folder, progress=None, passes=3):
        """Send every file the upload still waits for, in order; a file that waits for another (the same content
        earlier in the folder) is tried again after the others. Returns the report."""
        files = {i: f for i, f in enumerate(folder.files)}
        for _ in range(passes):
            report = self.status(run_id)
            waiting = [i for i in report.items if i['state'] == 'waiting' and i['role'] == 'primary']
            if report.state != 'open' or not waiting: return report
            for item in waiting:
                try: self._file(run_id, item['ordinal'], files)
                except IntegrityConflict as error:
                    if error.code == 'run-ended': return self.status(run_id)
                    if error.code != 'claimed': raise  # another request holds this file; the report says what became of it
                if progress: progress(self.status(run_id))
        return self.status(run_id)

    def _post_file(self, run_id, ordinal, mode, raw, attempt=None):
        header = {'project_id': self.client.project, 'run_id': run_id, 'ordinal': ordinal, 'mode': mode, **({'attempt': attempt} if attempt else {})}
        extra = {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json.dumps(header, separators=(',', ':')).encode()).decode()}
        self.sent_bytes += len(raw)
        return _checked(UploadRunStep, self.client._post_bytes('upload-runs', 'file', raw, extra_headers=extra, retry=mode == 'head'), 'folder upload file')

    def _file(self, run_id, ordinal, files):
        step = self._post_file(run_id, ordinal, 'head', files[ordinal].head())
        if step['step'] != 'send': return step
        members = step['send']['members']
        if step['send']['mode'] == 'body':
            return self._post_file(run_id, ordinal, 'body', b''.join(files[m['ordinal']].whole() for m in members), step['attempt'])
        ref = {'run_id': run_id, 'ordinal': ordinal, 'attempt': step['attempt']}
        begun = self._call('file-parts', {**ref, 'mode': 'begin'}, UploadRunStep)
        if begun['step'] != 'parts': return begun
        source = files[ordinal].source()
        before = len(begun['session'].get('received') or [])
        self.client._transfer_parts(source, begun['session'])
        self.sent_bytes += max(0, source.size - before * begun['session']['part_bytes'])
        wait = 0.2
        while True:
            answer = self._call('file-parts', {**ref, 'mode': 'session', 'upload_id': begun['session']['upload_id']}, UploadRunStep)
            if answer['step'] != 'checking': return answer
            time.sleep(wait); wait = min(wait * 2, 5.0)
