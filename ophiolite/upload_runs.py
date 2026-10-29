"""E55: a folder or a .zip in one upload, with one report.

`client.upload_runs.upload(path, attribution=..., audience=[...], rights_confirmed=True)` lists every file of the folder
(or zip) with its size and digest, starts one folder upload on the server and sends each file in turn: its first
64 KiB first, so the server decides what kind of file it is, then the whole file only when the server asks for it
(a file above the deployment's request limit goes in parts, as `upload_data` sends one). The answer is the upload's
report: one outcome per file (Added, Already here, Needs your decision, Not read, Not supported), with the reason in
words. Nothing is converted or repaired, and no wellbore is linked unless you ask (`associate_matches`).

Running the same upload again after an interruption continues the unfinished upload of the same folder (the same
paths, sizes and digests): files already added are not sent again. `new=True` starts another upload instead.

E90: an omitted attribution or audience is the project's New data setting (`client.new_data_defaults()`), and a
declared value 'project-default' (or `use_project_defaults`) keeps the project's default for that field of each file
that leaves it open; the report records it as "Project default, accepted by you" with the settings revision it was read
at, and the deployment refuses the upload, writing nothing, if the settings changed in between.

E85: one file is a folder of one, and an https address is read and added by the gateway itself: the SDK sends the
address, never the file's bytes, and the report names the host and the file, never the address's query string.

E59: a folder of a storage connection (`import_storage`) is read by the gateway too, with your own sign-in to it: the
SDK sends the connection and each object's key, never a byte or a key of the storage. Each file is either read from your
storage each time (`keep_copy=False`, a source selection pinned at the bytes read) or added as a copy, which the
organisation must allow; the report is the same report.
"""
import base64
import csv
import hashlib
import io
import shlex
import json
import os
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import IntegrityConflict, OphioliteError, Refused, ValidationFailed, VerificationFailed
from .models.api import UploadCheckAnswer, UploadRun, UploadRunsListAnswer, UploadRunStep

HEAD = 65536
MAX_FILES = 500
SENDS = 3  # E56 (N8): a question a file asks only once it is read is answered and the file sent again, at most three sends in all
ZIP_RATIO = 100  # an entry, or the whole zip, unpacked to more than this many times its packed size is refused
ZIP_TOTAL = 512 * 1024 * 1024
LINKS = 50  # links per associate call
RESULT = {'added': 'Added', 'already-here': 'Already here', 'needs-decision': 'Needs your decision', 'not-read': 'Not read',
          'not-supported': 'Not supported', 'cancelled': 'Cancelled', 'waiting': 'Not sent yet', 'reading': 'Being added',
          'needs-procedure': 'Can be read on your computer', 'converting': 'Being read on your computer',  # E107a
          'converted': 'Read on your computer'}
LISTED_RESULT = {'added': 'Added', 'already-here': 'Already here', 'planned': 'Not sent yet'}  # E127 s1a: a listed file; any other outcome is Not added
OUTCOMES = ('added', 'already-here', 'needs-decision', 'not-read', 'not-supported')
READ_STATES = ('needs-procedure', 'converting', 'converted')  # E107a: counted only when a run has them
READS = ['procedures']  # E107a (R5-8): what this SDK reads; sent only to a deployment that lists it
CLAIM_WAIT = 150  # seconds: the deployment's claim on a file being added lasts 120
COLUMNS = ('path', 'result', 'kind', 'read', 'reason', 'asset')
DEFAULT = 'project-default'  # E90: a declared value that keeps the project's default for that field
NO_ATTRIBUTION = 'No attribution given and the project has none. Pass --attribution or ask an administrator to set one.'
NOT_PROJECT = "This project's new files are not visible to everyone in it. Add the files for yourself or named people, then change who can see them (client.set_audience)."
MOVED = "The project's defaults changed while this upload was being prepared. Nothing was added; run it again."
# E123 S3b (D4): the basis items a folder upload asks once for files that share them, by their words
BASIS_ITEMS = {'crs': 'coordinate system', 'vertical_domain': 'vertical values', 'vertical_datum': 'vertical datum', 'units.xy': 'map unit',
               'units.depth': 'depth unit', 'units.time': 'time unit', 'units.z': 'vertical unit'}
BASIS_ANSWERS = 50  # answers per request
NAMED = 5  # E123 S6 (D3): the members a report line names before "and N more"


def basis_item(name):
    """A basis item by its words ('map unit', 'map-unit') or its id ('units.xy')."""
    if name.strip() in BASIS_ITEMS: return name.strip()
    words =' '.join(name.strip().lower().replace('_', ' ').replace('-', ' ').split())
    for item, label in BASIS_ITEMS.items():
        if words in (item, label): return item
    raise Refused('%s is not asked once for a folder; say one of: %s.' % (name, ', '.join(BASIS_ITEMS.values())))


def _checked(model, answer, what):
    from pydantic import ValidationError
    try: model.model_validate(answer)
    except (ValidationError, ValueError, TypeError): raise VerificationFailed('The %s answered outside its documented shape.' % what) from None
    return answer


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# --- what is sent ------------------------------------------------------------------------------------------------------

class File:
    """One file of the folder or zip: its path in the upload, size and digest; its bytes are read only when sent.
    A file at an address (E85b) has no bytes here: the gateway fetches it."""
    def __init__(self, path, size, sha256, read, disk=None, address=None, stored=False):
        self.path, self.size, self.sha256, self._read, self.disk, self.address = path, size, sha256, read, disk, address
        self.stored = stored  # E59: an object of a storage connection, which the gateway reads again

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
    def __init__(self, name, files, address=None, connection=None, left_out=()):
        self.name, self.files, self.address = name, files, address
        self.connection, self.left_out = connection, list(left_out)  # E59: the storage connection; [(key, sentence)] not read

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


def readers():
    """The deployment's reader registry as the SDK's contract snapshot holds it."""
    return json.loads((Path(__file__).parent / 'contracts/connectors/v1/readers.json').read_text())['readers']


def checked_declarations(declare, folder=None):
    """E85: `declare` names kinds and the items each kind can be told; anything else is refused before anything is sent.
    E56 (L1): a key that names a file of the folder (its path, or its name when only one file has it) holds
    {kind: {field: value}} for that file alone and wins over the kind's values."""
    entries = {e['profile']: e for e in readers()}
    def kind_values(kind, values):
        entry = entries.get(kind)
        if entry is None: raise Refused('No kind of file is named %s. Kinds: %s.' % (kind[:80], ', '.join(entries)))
        known = [f['key'] for f in entry['declared']]
        unknown = sorted(set(values) - set(known))
        if unknown:
            raise Refused('%s files do not take %s; they take %s.' % (entry['label'], ', '.join(k[:40] for k in unknown[:4]), ', '.join(known) if known else 'no declarations'))
    for key, values in (declare or {}).items():
        if key in entries or not isinstance(values, dict) or not all(isinstance(v, dict) for v in values.values()) or not values:
            kind_values(key, values); continue
        for kind, inner in values.items(): kind_values(kind, inner)
        if folder is not None and _named(folder.files, key) is None:
            raise Refused('No file of this upload is named %s; name a file by its path in the folder.' % key[:160])
    return declare


def _named(files, key):
    """The path of the one file `key` names (its path, else its name if no other file has it), or None."""
    paths = [f.path for f in files]
    if key in paths: return key
    same = [p for p in paths if PurePosixPath(p).name == key]
    return same[0] if len(same) == 1 else None


def declared_for(declare, files, item):
    """The values `declare` gives one file: its kind's, with its own (by path) winning field by field; None if neither names it."""
    kinds = {e['profile'] for e in readers()}
    own = [values[item['profile']] for key, values in (declare or {}).items()
           if key not in kinds and _named(files, key) == item['path'] and item['profile'] in values]
    general = (declare or {}).get(item['profile'])
    if not own and general is None: return None
    return {**(general or {}), **(own[0] if own else {})}


def _values(values):
    """The declared values of one `declare` entry: {field: value} for a kind, or {kind: {field: value}} for one file."""
    return [x for v in values.values() for x in (v.values() if isinstance(v, dict) else [v])] if isinstance(values, dict) else []


def is_address(path):
    return isinstance(path, str) and '://' in path[:12]


def open_file(path):
    """One file as a folder of one: its name is its path in the upload. A link is refused, as in a folder."""
    path = Path(path)
    if not stat.S_ISREG(os.lstat(path).st_mode): raise Refused('%s is not a regular file. Nothing was sent.' % path.name, 'Links and special files are not followed.')
    return Folder(path.name, [File(path.name, os.path.getsize(path), _digest(path), lambda: path.read_bytes(), str(path))])


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

@dataclass(frozen=True)
class BasisBlock:
    """E123 S6 (D1): one served block (`kind` 'block', `state` 'stated') or proposal (`kind` 'proposal', `state`
    'proposed', 'confirmed' or 'declined') of a folder upload. `members` are its files in served order; `stated` what a
    block's files share (a copy, keyed by item words; {} for a proposal); `open` every item still asked of the group or
    of any of its files, first occurrence kept (an aggregate, not only what one answer to the group settles); `sentence`
    the served sentence for it, or ''. A known item is in words; an item this SDK does not know stays as served."""
    target: str
    kind: str
    state: str
    members: tuple
    stated: dict
    open: tuple
    sentence: str


def _words(item): return BASIS_ITEMS.get(item, item)


def _members(paths):
    """E123 S6 (D3): 'a, b and c'; past five, the first five 'and N more'."""
    if len(paths) > NAMED: return '%s and %d more' % (', '.join(paths[:NAMED]), len(paths) - NAMED)
    return ' and '.join([', '.join(paths[:-1]), paths[-1]]) if len(paths) > 1 else ''.join(paths)


class Report:
    """A folder upload as its report shows it. `counts` names the five outcomes (and `cancelled` when any file was
    stopped or skipped); `ok` is true when every file was added or is already here."""
    def __init__(self, view):
        self.view = view
        self.run_id, self.state, self.label, self.items = view['run_id'], view['state'], view['label'], view['items']
        self.left_out = []  # E59: [(key, sentence)] of a storage folder's objects the gateway did not read
        self.names = {}  # E108 S1 (B6 rev 4): a source run's rows by output label; the path stays a technical detail
        counts = {k.replace('_', '-'): v for k, v in view['counts'].items()}
        self.counts = {k: counts[k] for k in OUTCOMES}
        if counts['cancelled']: self.counts['cancelled'] = counts['cancelled']
        for state in READ_STATES:  # E107a
            if counts.get(state): self.counts[state] = counts[state]
        if counts['waiting'] or counts['reading']: self.counts['not-sent'] = counts['waiting'] + counts['reading']

    @property
    def ok(self): return self.state == 'closed' and all(i['state'] in ('added', 'already-here', 'converted') for i in self.items)

    @property
    def proposals(self):
        """E122 s3b: how many files of a named send are asked whether they are an earlier file renamed; 0 when not served."""
        return (self.view.get('changes') or {}).get('proposals', 0)

    @property
    def basis(self):
        """E123 S6 (D1, D2): the served blocks, then the served proposals, as `BasisBlock`s; () when nothing is served."""
        basis = self.view.get('basis') or {}
        grouping = basis.get('grouping') or {}
        plan, resolved = grouping.get('plan') or {}, grouping.get('resolved') or {}
        said, states, questions = {}, resolved.get('proposals') or {}, resolved.get('questions') or []
        for s in basis.get('sentences') or []: said.setdefault(s['target'], s['sentence'])

        def group(g, kind, state, stated):
            members = tuple(g['members'])
            asked = [_words(q['item']) for q in questions if q['target'] == g['id'] or q['target'] in members]
            return BasisBlock(g['id'], kind, state, members, {_words(k): v for k, v in stated.items()}, tuple(dict.fromkeys(asked)), said.get(g['id'], ''))
        return tuple([group(b, 'block', 'stated', b.get('stated') or {}) for b in plan.get('blocks') or []]
                     + [group(p, 'proposal', states.get(p['id'], 'proposed'), {}) for p in plan.get('proposals') or []])

    @property
    def conflicts(self):
        """E123 S6: (path, item in words, what the file states, what was answered) per served conflict; () when none."""
        resolved = ((self.view.get('basis') or {}).get('grouping') or {}).get('resolved') or {}
        return tuple((c['path'], _words(c['item']), c['stated'], c['answered']) for c in resolved.get('conflicts') or [])

    def rows(self):
        """One row per file, each followed by the files its catalogue manifest lists (E127 s1a)."""
        return [r for i in self.items for r in [self.row(i)] + self.listed(i)]

    @staticmethod
    def row(i):
        return {'path': i['path'], 'result': RESULT[i['state']], 'kind': i.get('kind') or '', 'read': i.get('read') or '',
                'reason': i.get('sentence') or '', 'asset': i.get('asset_id') or ''}

    @staticmethod
    def listed(i):
        """E127 s1a (A12): the rows of the files a manifest row lists (outputs `listed-<n>`), as `<path>: <label>`; any
        other output (a conversion's, a package's) is not a row. Whether the run is ok follows from the manifest's row."""
        return [{'path': '%s: %s' % (i['path'], o['label']), 'result': LISTED_RESULT.get(o['outcome'], 'Not added'), 'kind': o.get('kind') or '',
                 'read': o.get('line') or '', 'reason': o.get('sentence') or '', 'asset': o.get('asset_id') or ''}
                for o in i.get('outputs') or [] if (o.get('output') or '').startswith('listed-')]

    def text(self):
        said = ', '.join('%d %s' % (n, RESULT.get(k, 'Not sent yet')) for k, n in self.counts.items())
        lines = ['%s - %d files - %s. %s' % (self.view['folder_name'], self.view['files'], self.label, said)]
        if self.view.get('changes'): lines.append(self.view['changes']['sentence'])  # E122 s1 (D5): the server's sentence, as served
        if ((self.view.get('changes') or {}).get('elements') or {}).get('sentence'): lines.append(self.view['changes']['elements']['sentence'])  # E122 s3a (D3): the items, as served
        if (self.view.get('scope') or {}).get('sentence'): lines.append(self.view['scope']['sentence'])  # E122 s2 (D7): what is gone, as served
        groups = {g.target: g.members for g in self.basis}
        for s in (self.view.get('basis') or {}).get('sentences') or []:  # E123 S3a (D4): the basis blocks and proposals, as served
            lines.append(s['sentence'])
            if s['target'] in groups: lines.append('    ' + _members(groups[s['target']]))  # E123 S6 (D3): which files it means
        for item in self.items:  # each file with its own row (E127 s1a: a manifest's rows follow it)
            r, name = self.row(item), self.names.get(item['path'], item['path'])
            if r['result'] not in ('Added', 'Already here'):
                lines.append('  %s: %s%s' % (name, r['result'], ' - ' + r['reason'] if r['reason'] else ''))
                if item['state'] == 'needs-procedure' and item['role'] == 'primary':  # E107a: the exact command that reads it here
                    lines.append('    To read it on this computer: ophiolite intake read %s %s' % (self.run_id, shlex.quote(PurePosixPath(item['path']).name)))
            for listed in self.listed(item):
                if listed['result'] in ('Added', 'Already here'): continue
                lines.append('  %s%s: %s%s' % (name, listed['path'][len(item['path']):], listed['result'], ' - ' + listed['reason'] if listed['reason'] else ''))
        settings = self.view.get('settings') or {}
        if settings.get('defaults'):  # E90: what the run took from the project's settings, and at which revision
            took = {'attribution': 'attribution "%s"' % settings.get('attribution', ''), 'audience': who_sees(settings)}
            used = [took[k] for k in settings['defaults']['fields']] + ['what files leave open, where kept'] * (not settings['defaults']['fields'])
            lines.append('Project default, accepted by you (settings revision %d): %s.' % (settings['defaults']['revision'], '; '.join(used)))
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


def who_sees(settings):
    """J2's words for who can see the files a run adds."""
    if settings.get('project_audience') == 'read': return 'Everyone in this project can see it'
    named = [p for p in settings.get('audience') or []]
    return 'Only you can see it' if not named else 'You and %s can see it' % ' and '.join(named)


# --- the client --------------------------------------------------------------------------------------------------------

class UploadRuns:
    def __init__(self, client):
        self.client = client
        self.sent_bytes = 0  # the file bytes this object sent (heads, bodies and parts), for a resumed upload's account
        self._reads = None

    def reads(self):
        """E107a (R5-8): True when the deployment lists `upload_runs.reads: ['procedures']` in its capabilities; only then
        does this SDK say it reads read procedures (start, reports and file steps). Read once."""
        if self._reads is None:
            described = getattr(self.client, 'upload_reads', None)
            self._reads = bool(described()) if described is not None else False
        return self._reads

    def _declared(self, value):
        return {**value, 'reads': list(READS)} if self.reads() else value

    def _header(self, header):
        header = self._declared(header)
        return {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json.dumps(header, separators=(',', ':')).encode()).decode()}

    def _call(self, operation, body, model, retry=True):
        return _checked(model, self.client._post('upload-runs', operation, self._declared(body), retry=retry), 'folder upload ' + operation)

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
        """Answer files that need a decision: 'add-separately', 'add-new', 'declare' (with `declared`), 'same-item'
        (confirm a same-bytes question: the file is the earlier file renamed) or 'skip'. Files to add go back to waiting;
        send them with `send(run_id, open(path))`."""
        body = {'run_id': run_id, 'ordinals': sorted(ordinals), 'choice': choice, **({'declared': dict(declared or {})} if choice == 'declare' else {})}
        body['command_id'] = command_id or _sha(['decide', body])
        return Report(self._call('decide', body, UploadRun))

    def basis(self, run_id, decision=None, answers=(), command_id=None):
        """E123 S3b: say whether the files a report proposes share one basis (`decision` (proposal id, 'confirm' or
        'decline')) and answer the basis questions the report serves (`answers` [(target, item, value)], or dicts that
        may say kept='project-default' for a suggestion kept as shown): a block or a confirmed proposal is answered once
        for its files. A file whose declarations are then all given goes back to waiting; send it with `send`."""
        body = {'run_id': run_id}
        if decision is not None:
            proposal, choice = (decision['proposal'], decision['choice']) if isinstance(decision, dict) else decision
            body['decision'] = {'proposal': proposal, 'choice': choice}
        body['answers'] = [dict(a) if isinstance(a, dict) else dict(zip(('target', 'item', 'value'), a)) for a in answers]
        body['command_id'] = command_id or _sha(['basis', body])
        return Report(self._call('basis', body, UploadRun))

    def answer_basis(self, run_id, report, share=None, given=None):
        """E123 S3b (D4): decide every undecided proposal of the report (`share` True confirms, False declines, None
        leaves it), then answer each open basis question whose item `given` {item: value} names (an item by its words or
        id). A question that names why its file could not take an answer is left to that file. True if anything was sent."""
        given = {basis_item(k): v for k, v in (given or {}).items()}
        grouping = (report.view.get('basis') or {}).get('grouping')
        if grouping is None: return False
        acted = False
        if share is not None:
            for p in grouping['plan']['proposals']:
                if grouping['resolved']['proposals'].get(p['id']) != 'proposed': continue
                report, acted = self.basis(run_id, decision=(p['id'], 'confirm' if share else 'decline')), True
            grouping = (report.view.get('basis') or {}).get('grouping') or grouping
        asked = [(q['target'], q['item']) for q in grouping['resolved']['questions'] if q['item'] in given and not q.get('reason')]
        for i in range(0, len(asked), BASIS_ANSWERS):
            self.basis(run_id, answers=[(t, item, given[item]) for t, item in asked[i:i + BASIS_ANSWERS]]); acted = True
        return acted

    def share(self, run_id, readers):
        """Name the project members who may read this report (the whole list; empty revokes). Its files keep their own access."""
        return Report(self._call('share', {'run_id': run_id, 'readers': sorted(set(readers))}, UploadRun, retry=False))

    def report(self, run, path):
        """Save a report (a Report or a run id) as CSV, or as JSON for a .json path."""
        return (run if isinstance(run, Report) else self.status(run)).save(path)

    def fidelity(self, report, source, destination):
        """E127 s2: write the catalogue's fidelity document (`osd.fidelity/1`) for the one catalogue manifest REPORT (a
        Report or run id) read from SOURCE (the local file or folder that was uploaded, read again here) to DESTINATION,
        and return DESTINATION. Refused, with nothing written, when any file's outcome cannot be stated exactly
        (ophiolite.fidelity)."""
        from . import fidelity
        if is_address(source): raise Refused(fidelity.ADDRESS)
        fidelity.outside(source, destination)
        report = report if isinstance(report, Report) else self.status(report)
        return fidelity.write(fidelity.document(report, self.open(source), self.client), destination)

    # the whole journey

    def open(self, path):
        """The folder or zip at PATH as it will be sent (checked; nothing is sent)."""
        if is_address(path): raise Refused('An address is read by the gateway; use upload(address).')
        path = Path(path)
        if path.is_dir(): return open_folder(path)
        if path.suffix.lower() == '.zip': return open_zip(path, self.client.served_limits()['file_bytes'])
        if path.is_file() or path.is_symlink(): return open_file(path)
        raise Refused('%s was not found. Choose a file, a folder, a .zip file or an https address.' % path.name)

    def check(self, address):
        """E85b: what the gateway reads at an https address (its kind, what the file states and leaves open, and what was
        fetched); nothing is added. Its refusals carry the deployment's sentence."""
        header = {'project_id': self.client.project, 'mode': 'whole', 'address': address}
        extra = self._header(header)
        return _checked(UploadCheckAnswer, self.client._post_bytes('upload-runs', 'check', b'', extra_headers=extra, retry=True), 'file check')

    def fetched(self, address):
        """The address as a folder of one file, from the gateway's read of it."""
        got = self.check(address)['fetched']
        return Folder(got['host'][:160], [File(got['name'], got['bytes'], got['sha256'], None, address=address)], address)

    # E59: a folder of a storage connection, read by the gateway with your own sign-in

    def check_object(self, connection, key):
        """E59: what the gateway reads of the object KEY of a storage connection (its kind, what it states and leaves
        open, and its size and digest); nothing is added. Its refusals carry the deployment's sentence."""
        header = {'project_id': self.client.project, 'mode': 'whole', 'bucket': {'connection_id': connection, 'key': key}}
        extra = self._header(header)
        return _checked(UploadCheckAnswer, self.client._post_bytes('upload-runs', 'check', b'', extra_headers=extra, retry=True), 'file check')

    def stored(self, connection, prefix=None):
        """E59: every object below PREFIX (and its subfolders) as a folder the gateway reads, each checked by it. An object
        the gateway does not read (larger than the deployment's request limit) is left out with its sentence in
        `left_out`; an empty object is listed as the empty file it is."""
        found, pending, seen = {}, [prefix], {prefix}
        while pending:
            at, cursor = pending.pop(0), None
            while True:
                page = self.client.browse(connection, at, cursor)
                found.update((i['key'], i['size']) for i in page['items'])
                if len(found) > MAX_FILES: _too_many(len(found))
                for sub in page['folders']:
                    if sub not in seen and (at is None or sub.startswith(at)): seen.add(sub); pending.append(sub)
                cursor = page['next_cursor']
                if not cursor: break
        _too_many(len(found))
        files, left_out = [], []
        for key in sorted(found):
            if found[key] == 0:
                files.append(File(key, 0, hashlib.sha256(b'').hexdigest(), None, stored=True)); continue
            try: got = self.check_object(connection, key)['fetched']
            except OphioliteError as error:
                if not str(error.code).startswith('bucket-') or error.code in ('bucket-refused', 'bucket-offline', 'bucket-busy'): raise
                left_out.append((key, error.server_message or error.message)); continue
            files.append(File(key, got['bytes'], got['sha256'], None, stored=True))
        name = (prefix or '').rstrip('/').rsplit('/', 1)[-1] or connection
        return Folder(name[:160], files, connection=connection, left_out=left_out)

    def import_storage(self, connection, prefix=None, *, keep_copy=False, attribution, rights_confirmed, audience=(), well_notes='',
                       declare=None, skip_decisions=False, associate_matches=False, new=False, progress=None):
        """E59: add every file below PREFIX of a storage connection in one upload and return its Report. Without
        `keep_copy` each file is read from your storage each time (pinned at the bytes read now); with it each file is
        added as a copy, which the organisation's copy declaration must allow (its audience bounds `audience`). Objects
        the gateway does not read are in `report.left_out`."""
        if rights_confirmed is not True:
            raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience.'])
        checked_declarations(declare)
        folder = self.stored(connection, prefix)
        checked_declarations(declare, folder)
        custody = {'connection_id': connection, 'custody': 'copy' if keep_copy else 'read-in-place', 'keys': [f.path for f in folder.files]}
        run = None if new else self.unfinished(folder)
        if run is None:
            body = {'command_id': uuid.uuid4().hex, 'folder_name': folder.name, 'files': folder.listing(), 'attribution': attribution,
                    'well_notes': well_notes, 'audience': list(audience), 'rights_confirmed': True, 'bucket': custody}
            run = self._call('start', body, UploadRun)['run_id']
        report = self.send(run, folder, progress)
        for _ in range(SENDS - 1):
            if not self.answer(run, report, declare, folder): break
            report = self.send(run, folder, progress)
        if skip_decisions:
            ordinals = [i['ordinal'] for i in self.status(run).items if i['state'] == 'needs-decision' and i['role'] == 'primary']
            if ordinals: self.decide(run, ordinals, 'skip')
            report = self.send(run, folder, progress)
        if associate_matches:
            links = [(i['ordinal'], i['proposal']['entity_id']) for i in report.items if i.get('proposal')]
            if links: report, _ = self.associate(run, links)
        report.left_out = folder.left_out
        return report

    def upload(self, path, *, attribution=None, rights_confirmed, audience=None, well_notes='', declare=None, skip_decisions=False,
               associate_matches=False, new=False, progress=None, use_project_defaults=False, source_name=None, send=None, scope=None, started=None,
               share_basis=None, basis=None):
        """Upload a file, a folder, a .zip or an https address and return its Report. E122 s1: `source_name` names where
        the files come from ("Petrel export"); a later send under the same name reports each file unchanged,
        changed (its next version) or new, and `report.view['changes']['sentence']` says how many. E122 s2: `send='complete'`
        says the folder is everything in that source (or in its folder `scope`): a file the source sent before and this send
        does not list is marked gone (nothing is removed), and `report.view['scope']['sentence']` says which; a source
        emptied completely is not marked gone. `send='incremental'` (or nothing) marks nothing. `declare` {kind: {field: value}} answers the files of that
        kind (profile, e.g. 'esri-ascii-grid/1') that need you to say what their values mean; `skip_decisions` skips
        every other file that needs a decision; `associate_matches` links each file to the one wellbore its header names.
        `progress(report)` is called after each file. E90: `attribution` None and `audience` None ('project' needs it to be
        the project's setting; 'me' is no one else) take the project's New data settings; a `declare` value 'project-default'
        or `use_project_defaults` keeps the project's default for a field a file leaves open. E129 Sa: `started(run_id)` is
        called once the run is started or resumed, before any file content is sent. E123 S3b: `share_basis` True (or
        False) says the files the report proposes do (or do not) share one basis, and `basis` {item: value} answers the
        basis questions, an item by its words ('map unit') or id, before `declare` answers each file's own fields."""
        if rights_confirmed is not True:
            raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience.'])
        if not isinstance(path, (str, os.PathLike)):  # E56 (F1): a path is read and digested here; an open stream is not
            raise Refused('Pass the path of a file, a folder or a .zip, or an https address; an open file is not read. Nothing was sent.')
        checked_declarations(declare)
        for item in basis or {}: basis_item(item)  # refused before anything is sent
        folder = self.fetched(path) if is_address(path) else self.open(path)
        checked_declarations(declare, folder)
        declared = (source_name, send or 'incremental', scope) if source_name is not None else None
        run = None if new else self.unfinished(folder, declared)
        if run is None:
            body = {'command_id': uuid.uuid4().hex, 'folder_name': folder.name[:160], 'files': folder.listing(),
                    'well_notes': well_notes, 'rights_confirmed': True, **({'address': folder.address} if folder.address else {}),
                    **({'source_name': source_name} if source_name is not None else {}),
                    **({'send': send} if send is not None else {}), **({'scope': scope} if scope is not None else {})}
            body.update(self.defaults(folder, attribution, audience, declare, use_project_defaults))
            run = self._call('start', body, UploadRun)['run_id']
        if started is not None: started(run)
        report = self.send(run, folder, progress)
        if (share_basis is not None or basis) and self.answer_basis(run, report, share_basis, basis):  # E123 S3b: before each file's own
            report = self.send(run, folder, progress)
        for _ in range(SENDS - 1):  # E56 (N8): a file may ask again once it is read (a layer, corners); answered from `declare`
            if not self.answer(run, report, declare, folder): break
            report = self.send(run, folder, progress)
        if skip_decisions:
            ordinals = [i['ordinal'] for i in self.status(run).items if i['state'] == 'needs-decision' and i['role'] == 'primary']
            if ordinals: self.decide(run, ordinals, 'skip')
            report = self.send(run, folder, progress)
        if associate_matches:
            links = [(i['ordinal'], i['proposal']['entity_id']) for i in report.items if i.get('proposal')]
            if links: report, _ = self.associate(run, links)
        return report

    def defaults(self, folder, attribution, audience, declare, use_project_defaults):
        """E90: the start's run settings and, where a project default is kept, each file's decisions; with the settings
        revision whenever a default is used, read once here and never refetched."""
        out = {} if attribution is None else {'attribution': attribution}
        if isinstance(audience, str) and audience not in ('me', 'project'): raise Refused("Choose who can see the files: 'project', 'me' or a list of people.")
        if audience is not None and audience != 'project': out['audience'] = [] if audience == 'me' else list(audience)
        keeps = use_project_defaults or any(v == DEFAULT for values in (declare or {}).values() for v in _values(values))
        if attribution is not None and 'audience' in out and not keeps: return out
        from . import new_data
        snap = new_data.defaults(self.client)
        if attribution is None and not (snap['attribution'] or '').strip(): raise Refused(NO_ATTRIBUTION)
        if audience == 'project' and snap['visible_to'] != 'project': raise Refused(NOT_PROJECT)
        out['defaults_revision'] = snap['revision']
        if keeps: out['files'] = [{**f, **self.kept(folder, f, declare, use_project_defaults, snap['revision'])} for f in folder.listing()]
        return out

    def kept(self, folder, listed, declare, everything, revision):
        """One file's decisions when it keeps a project default: its kind from the deployment's check of its head, the
        values `declare` gives that kind (typed ones are yours), and the defaults kept."""
        file = next(f for f in folder.files if f.path == listed['path'])
        if folder.address: found = self.check(folder.address)  # the gateway reads the address again; nothing is sent from here
        else:
            header = {'project_id': self.client.project, 'name': file.path, 'bytes': file.size, 'mode': 'head', 'sha256': file.sha256}
            extra = self._header(header)
            found = _checked(UploadCheckAnswer, self.client._post_bytes('upload-runs', 'check', file.head(), extra_headers=extra, retry=True), 'file check')
        if not found.get('kind'): return {}
        if found.get('defaults_revision') != revision: raise Refused(MOVED)
        values = declared_for(declare, folder.files, {'path': file.path, 'profile': found['kind']['profile']}) or {}
        offered = [s['key'] for s in found.get('suggestions') or [] if s['class'] == DEFAULT]
        typed = {k: v for k, v in values.items() if v != DEFAULT}
        keep = [k for k, v in values.items() if v == DEFAULT] + [k for k in offered if everything and k not in values]
        missing = [k for k in keep if k not in offered]
        if missing: raise Refused('The project has no default %s for %s; give a value instead.' % (', '.join(missing), file.path))
        return {'decisions': typed, 'suggested': keep} if keep or typed else {}

    def answer(self, run, report, declare, folder):
        """Answer from `declare` each file that waits for declarations and is told something it asks; True if any was."""
        answered = False
        for item in report.items:
            if item['state'] != 'needs-decision' or item['reason_code'] != 'needs-declarations' or item['role'] != 'primary': continue
            values = declared_for(declare, folder.files, item)
            if values is None: continue
            asks = item.get('asks')
            if asks is not None:  # asked after it was read: what it asks and is known adds to what it was told before
                values = {k: v for k, v in values.items() if k in {a['key'] for a in asks}}
                if not values: continue
            self.decide(run, [item['ordinal']], 'declare', values); answered = True
        return answered

    def unfinished(self, folder, declared=None):
        """The id of your unfinished upload of this folder (the same name, paths, sizes and digests), or None. An upload
        whose files all ended but one still waits for a decision is unfinished too (E56, N8): `declare` may answer it now.
        E122 s2 (D7): only the same send resumes: `declared` (source name, 'complete' or 'incremental', scope), or None
        for an unnamed upload, equals the run's served `scope` block (none for an unnamed run)."""
        listing = folder.listing()
        for summary in self.list():
            if summary['state'] not in ('open', 'closed') or summary['folder_name'] != folder.name[:160]: continue
            view = self.status(summary['run_id']).view
            if summary['state'] == 'closed' and not any(i['state'] == 'needs-decision' and i['role'] == 'primary' for i in view['items']): continue
            block = view.get('scope')
            if (None if not block else (block['source_name'], block['send'], block['scope'])) != declared: continue
            if [{'path': i['path'], 'bytes': i['bytes'], 'sha256': i['sha256']} for i in view['items']] == listing: return summary['run_id']
        return None

    def send(self, run_id, folder, progress=None, passes=3):
        """Send every file the upload still waits for, in order; a file that waits for another (the same content
        earlier in the folder) is tried again after the others. A file another request holds (or whose bytes were lost
        after its head) is waited for until its claim ends, at most CLAIM_WAIT seconds; the deployment then lets it wait
        again and it is sent. Returns the report."""
        files = {i: f for i, f in enumerate(folder.files)}
        until, done = time.monotonic() + CLAIM_WAIT, 0
        while done < passes:
            report = self.status(run_id)
            waiting = [i for i in report.items if i['state'] == 'waiting' and i['role'] == 'primary']
            if report.state != 'open': return report
            if not waiting:
                if not any(i['state'] == 'reading' and i['role'] == 'primary' for i in report.items) or time.monotonic() > until: return report
                time.sleep(5.0); continue
            done += 1
            for item in waiting:
                try: self._file(run_id, item['ordinal'], files)
                except IntegrityConflict as error:
                    if error.code == 'run-ended': return self.status(run_id)
                    if error.code != 'claimed': raise  # another request holds this file; the report says what became of it
                if progress: progress(self.status(run_id))
        return self.status(run_id)

    def _post_file(self, run_id, ordinal, mode, raw, attempt=None, address=None, stored=False):
        header = {'project_id': self.client.project, 'run_id': run_id, 'ordinal': ordinal, 'mode': mode, **({'attempt': attempt} if attempt else {}),
                  **({'address': address} if address else {}), **({'bucket': True} if stored else {})}
        extra = self._header(header)
        self.sent_bytes += len(raw)
        return _checked(UploadRunStep, self.client._post_bytes('upload-runs', 'file', raw, extra_headers=extra, retry=mode == 'head'), 'folder upload file')

    def _file(self, run_id, ordinal, files):
        if files[ordinal].address: return self._post_file(run_id, ordinal, 'head', b'', address=files[ordinal].address)  # the gateway fetches it again
        if files[ordinal].stored: return self._post_file(run_id, ordinal, 'head', b'', stored=True)  # E59: the gateway reads the object again
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
