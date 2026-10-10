"""E70a: check for updates, get latest, send to project (ADR 0021).

The shared core: the standard library and `.errors` only, so a host application's Python (QGIS) can carry it
(family rule X4). A *transport* reaches the project; this module never does. The record of what this program
holds (`held.json`, schema `ophiolite.held/1`) lives in a work folder that one program at a time may change
(`held.lock`); `check` reads it without the lock.

    ex = Exchange(transport, 'work')
    ex.check()                                   # changes nothing
    ex.get(item, output='folder')                # fetch, persist, then advance the record
    ex.send(data, name=..., profile=..., how=..., based_on=[held items], of=held item)

Every action ends in one of a closed list of outcomes (X6). A success returns an `Outcome`; a refusal raises an
`ExchangeRefused` subclass of an existing SDK category, so `ophiolite.cli.exit_code` maps it. Sentences hold
display values only (a name, a version number, a person's name or "someone", a relative time); identifiers and
the server's own words stay in `technical`. A host passes `sentences=` (one function per outcome) to speak its own
words.

The transport's methods (frozen here; the SDK's is `ClientTransport`, QGIS supplies its own):
  url, project                       where the record belongs
  identity()                         who sends (a pending send is bound to it)
  inventory()                        [{asset_id, kind, authority, revision, name}] every item the reader may see, at its head
  history(item)                      [{number, revision, by, at}] oldest first; `by` a display name or None
  fetch(item, revision, output, **how) -> {content, number?, facts?}; creates `output` (a new folder) and writes its files there when given
  publish(data, request, resolved, command_id) -> {asset_id, revision, number}
  same_content(held_entry, request)  whether a send would add nothing
  report(reference, holder_id, event_id)   optional (E70b): tell the project this holder received that exact version;
                                     called once by Receipt.confirm, after the record advanced; a failure changes nothing
Errors a transport raises carry `status`, `code` and `stage` attributes (the SDK's errors do); the core classifies
by code, then credential stage, then status, never by message text.
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from .errors import AuthenticationRequired, Busy, IntegrityConflict, OphioliteError, PermissionRefused, Refused, Unavailable, VerificationFailed

SCHEMA = 'ophiolite.held/1'
MAX_SEND = 32 * 1024 * 1024
CREDENTIAL_STAGES = ('no-credential', 'malformed-credential', 'credential-refused')
REPORT_TIMEOUT = 10.0  # seconds; E70b: a delivery report never holds a confirmation for longer


# -- sentences ------------------------------------------------------------------------------------

def _when(at, now):
    if not isinstance(at, (int, float)): return None
    seconds = max(0, now - at)
    for size, unit in ((86400, 'day'), (3600, 'hour'), (60, 'minute')):
        if seconds >= size:
            n = int(seconds // size); return '%d %s%s ago' % (n, unit, '' if n == 1 else 's')
    return 'just now'


def _version(entry):
    """", version 3 by Alice, 5 minutes ago" from the facts that are known; nothing for what is not."""
    text = ', version %d' % entry['number'] if entry.get('number') else ''
    if entry.get('who'): text += ' by %s, %s' % (entry['who'], entry['when']) if entry.get('when') else ' by %s' % entry['who']
    return text


def _names(entries):
    return ', '.join(e['name'] for e in entries)


def _updates(f):
    parts = []
    if f['newer']: parts.append('%d newer: %s' % (len(f['newer']), '; '.join(e['name'] + _version(e) for e in f['newer'])))
    if f['new']: parts.append('%d new since your last check: %s' % (len(f['new']), _names(f['new'])))
    if f['lost']: parts.append('%d you can no longer see: %s' % (len(f['lost']), _names(f['lost'])))
    return '. '.join(parts) + '.'


def _first(f):
    return ' This first check noted the %d item%s you can see; the next check lists what is new.' % (f['visible'], '' if f['visible'] == 1 else 's') if f.get('baseline') else ''


def _got(f):
    text = 'Got %s%s. You now hold it' % (f['name'], _version(f)) + ('; saved in %s.' % f['folder'] if f.get('folder') else '.')
    return text + (' It is a GeoTIFF generated from the stored map, not the file that was imported.' if f.get('map') else '')


def _newer(f):
    if not f.get('number'):
        return 'A newer version was added first. Your change was not sent. Either get the latest version and look at it, or send yours as a new item.'
    who = ' by %s, %s' % (f['who'], f['when']) if f.get('who') and f.get('when') else ' by %s' % f['who'] if f.get('who') else ''
    return 'Version %d was added%s. Your change was not sent. Either get version %d and look at it, or send yours as a new item.' % (f['number'], who, f['number'])


SENTENCES = {
    'nothing-new': lambda f: ('Nothing is newer than what you hold.' if f.get('holding') else 'You hold nothing yet.') + _first(f),
    'updates': lambda f: _updates(f) + _first(f),
    'access-changed': lambda f: 'You can no longer see %d item%s you hold: %s. They may have been removed or no longer shared with you.' % (
        len(f['lost']), '' if len(f['lost']) == 1 else 's', _names(f['lost'])),
    'got': lambda f: _got(f),
    'already-latest': lambda f: 'You already hold the latest version of %s, saved in %s.' % (f['name'], f['folder']),
    'not-visible': lambda f: 'You can no longer see %s. It may have been removed or no longer shared with you.' % f['name'],
    'cannot-read-here': lambda f: 'This kind of item cannot be received by this script yet: %s.' % f['reason'],
    'damaged': lambda f: 'The data did not match its fingerprint. Nothing was kept.',
    'map-unavailable': lambda f: 'That version of the map is not available (it may be withdrawn or not the one you hold).',
    'sent-new': lambda f: 'Sent %s as a new item; it is private until you share it.' % f['name'],
    'sent-version': lambda f: 'Sent %s as version %d. Version %d is kept.' % (f['name'], f['number'], f['number'] - 1) if f.get('number', 0) > 1 else
                              'Sent %s as a new version. The earlier version is kept.' % f['name'],
    'newer-version-exists': lambda f: _newer(f),
    'nothing-changed': lambda f: 'This is the same as version %d; nothing was sent.' % f['number'] if f.get('number') else 'This is the same as the version you hold; nothing was sent.',
    'access-refused': lambda f: ('The project did not allow this with this access key, so nothing was sent. '
                                 "Check that the key is for this project and can write, or ask the item's author."),
    'not-valid': lambda f: 'The project refused this: %s. Nothing was sent.' % f['reasons'],
    'not-held': lambda f: 'You can only build on items you hold. Get %s first.' % f['name'],
    'too-large': lambda f: 'The file is larger than this project accepts. Nothing was sent.',
    'outcome-unknown': lambda f: ('An earlier send of %s was started with another access key and may or may not have arrived. '
                                  'Run it again with that key to find out, or set it aside.' % f['name']) if f.get('other_key') else
                                 'An earlier send of %s may or may not have arrived. Run the same send again to find out; it will not publish twice.' % f['name'],
    'abandoned': lambda f: 'The unfinished send of %s was set aside. An item may already exist in the project; check before sending it again.' % f['name'],
    'folder-busy': lambda f: 'Another program is using this folder. Wait for it to finish, then run this again.',
    'rate-limited': lambda f: 'The project is busy. Wait a moment and run this again.',
    'sign-in-needed': lambda f: 'Your access key is not accepted any more. Ask for a new one.',
    'could-not-reach': lambda f: 'Could not reach the project. Nothing was changed; for send, run the same command again: it will not publish twice.',
}
OUTCOMES = tuple(SENTENCES)


class Outcome:
    """A success: `outcome` (a code from OUTCOMES), `sentence`, display `facts` and `technical` detail."""
    def __init__(self, outcome, sentence, facts=None, technical=None):
        self.outcome, self.sentence, self.facts, self.technical = outcome, sentence, facts or {}, technical or {}

    def to_dict(self):
        return {'outcome': self.outcome, 'sentence': self.sentence, 'facts': self.facts, 'technical': self.technical}

    def __str__(self): return self.sentence
    def __repr__(self): return 'Outcome(%r, %r)' % (self.outcome, self.sentence)


class ExchangeRefused(OphioliteError):
    """Mixed into an SDK error category: `.outcome`, `.sentence` (str(error)), `.facts`, `.technical`."""
    outcome = None

    def __init__(self, sentence, facts=None, technical=None):
        OphioliteError.__init__(self, sentence, code=type(self).outcome, details=dict(technical or {}))
        self.outcome, self.sentence, self.facts, self.technical, self.retry_after = type(self).outcome, sentence, facts or {}, technical or {}, 0

    def to_dict(self):
        return {'outcome': self.outcome, 'sentence': self.sentence, 'facts': self.facts, 'technical': self.technical}


def _refusal(code, base):
    return type(''.join(p.title() for p in code.split('-')), (ExchangeRefused, base), {'outcome': code, 'code': code})


NotVisible = _refusal('not-visible', Unavailable)
CannotReadHere = _refusal('cannot-read-here', Refused)
Damaged = _refusal('damaged', VerificationFailed)
MapUnavailable = _refusal('map-unavailable', Unavailable)
NewerVersionExists = _refusal('newer-version-exists', IntegrityConflict)
NothingChanged = _refusal('nothing-changed', IntegrityConflict)
AccessRefused = _refusal('access-refused', PermissionRefused)
NotValid = _refusal('not-valid', Refused)
NotHeld = _refusal('not-held', Refused)
TooLarge = _refusal('too-large', Refused)
OutcomeUnknown = _refusal('outcome-unknown', Unavailable)  # cli.exit_code: the code 'outcome-unknown' is 5
FolderBusy = _refusal('folder-busy', Busy)
RateLimited = _refusal('rate-limited', Busy)
SignInNeeded = _refusal('sign-in-needed', AuthenticationRequired)
CouldNotReach = _refusal('could-not-reach', Busy)
REFUSALS = {c.outcome: c for c in (NotVisible, CannotReadHere, Damaged, MapUnavailable, NewerVersionExists, NothingChanged, AccessRefused, NotValid,
                                   NotHeld, TooLarge, OutcomeUnknown, FolderBusy, RateLimited, SignInNeeded, CouldNotReach)}


# Display values only: an identifier handed in where a person's name belongs is never rendered.
_IDENTIFIER = re.compile(r'[0-9a-f]{32,}|[0-9a-f]{8}-[0-9a-f]{4}-|\boph_|\busr_|^[a-z][a-z0-9]*_[0-9a-z]{6,}$|^[a-z0-9-]+/[0-9]+$', re.I)


def display(value, fallback):
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= 160 and not _IDENTIFIER.search(value) else fallback


def failure(error):
    """What a transport error means, by its code, then its credential stage, then its status."""
    code, stage, status = getattr(error, 'code', None), getattr(error, 'stage', None), getattr(error, 'status', None)
    if isinstance(error, ExchangeRefused): return error.outcome
    if code == 'revision-conflict' and status == 409: return 'stale'
    if code in ('unreachable', 'could-not-reach') or isinstance(error, OSError): return 'could-not-reach'
    if status == 401 or stage in CREDENTIAL_STAGES or isinstance(error, AuthenticationRequired): return 'sign-in-needed'
    if status == 429: return 'rate-limited'
    if status == 413: return 'too-large'
    if status in (403, 404) or isinstance(error, PermissionRefused): return 'refused'
    if isinstance(error, VerificationFailed) and status is None: return 'damaged'
    if status in (400, 409, 422) or isinstance(error, Refused): return 'invalid'
    return 'could-not-reach'


# -- the held record and its lock ------------------------------------------------------------------

def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.%s.%s' % (path.name, uuid.uuid4().hex))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out: json.dump(value, out, indent=1, sort_keys=True); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, path)  # a reader sees the old record or the new one, never half of one


def folder_digest(path):
    """sha256 over every file below `path` (relative name and content)."""
    path = Path(path); h = hashlib.sha256()
    for f in sorted(p for p in path.rglob('*') if p.is_file()):
        h.update(f.relative_to(path).as_posix().encode() + b'\0' + hashlib.sha256(f.read_bytes()).hexdigest().encode() + b'\n')
    return h.hexdigest()


class Busy_(Exception): pass


@contextlib.contextmanager
def folder_lock(path, timeout=3.0):
    """One program at a time per work folder (fcntl on POSIX, msvcrt on Windows); held for the whole get or send."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if os.fstat(fd).st_size == 0: os.write(fd, b'0')
                    os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError, OSError):
                if time.monotonic() >= deadline: raise Busy_() from None
                time.sleep(0.02)
        try: yield
        finally:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)  # closing releases a POSIX lock too


# -- the core ---------------------------------------------------------------------------------------

def delivery_event(holder_id, asset_id, revision):
    """E70b: the id of "this holder received this exact version": the same in every process, so a repeated or retried
    report is one event at the project."""
    return 'got-' + hashlib.sha256(('%s\n%s\n%s' % (holder_id, asset_id, revision)).encode()).hexdigest()[:48]


class Receipt:
    """A fetched version not yet applied. `confirm()` advances the record; anything else leaves it unchanged.
    The folder stays locked until confirm() or release() (or the end of a `with` block).

    E70b: once the record has advanced, the receipt is reported to the project (when the transport can report).
    `reported` is True after the project accepted it, False when the report failed (the confirmation stands; a later
    confirm of the same version sends the same event id), None when nothing was reported."""
    def __init__(self, exchange, lock, entry, content, facts):
        self._exchange, self._lock, self.entry, self.content, self.facts = exchange, lock, entry, content, facts
        self.confirmed = False
        self.reported = None

    def confirm(self, applied_to=None):
        if self._lock is None: raise NotValid(self._exchange._say('not-valid', {'reasons': 'this version was already confirmed or released'}))
        try:
            record = self._exchange._load()
            entry = dict(self.entry, got_at=self._exchange.clock())
            if applied_to is not None: entry['applied_to'] = str(applied_to)
            entry['note'] = (record['items'].get(entry['asset_id']) or {}).get('note')
            record['items'][entry['asset_id']] = entry
            self._exchange._save(record)
            self.confirmed = True
        finally: self.release()
        self.reported = self._report(record.get('holder_id'), entry)
        return Outcome('got', self._exchange._say('got', self.facts), self.facts,
                       {'asset_id': entry['asset_id'], 'revision': entry['revision'], 'reported': self.reported})

    def _report(self, holder_id, entry):
        report = getattr(self._exchange.transport, 'report', None)
        if report is None or not holder_id: return None
        reference = {'project_id': self._exchange.transport.project, 'asset_id': entry['asset_id'], 'revision': str(entry['revision'])}
        try: report(reference, holder_id, delivery_event(holder_id, entry['asset_id'], entry['revision']))
        except Exception: return False  # never fails the confirmation: the version is applied and recorded
        return True

    def release(self):
        lock, self._lock = self._lock, None
        if lock is not None: lock.__exit__(None, None, None)

    def __enter__(self): return self
    def __exit__(self, *exc): self.release()


class Exchange:
    def __init__(self, transport, work, *, sentences=None, lock_timeout=3.0, clock=time.time):
        if sentences is not None:
            missing = [code for code in OUTCOMES if not callable(sentences.get(code))]
            if missing: raise ValueError('The sentence table has no sentence for: ' + ', '.join(missing))
        self.transport, self.work = transport, Path(work).expanduser().absolute()
        self.sentences, self.lock_timeout, self.clock = sentences or SENTENCES, lock_timeout, clock
        self.path, self.lock_path = self.work / 'held.json', self.work / 'held.lock'

    # record

    def _load(self):
        try: record = json.loads(self.path.read_text())
        except FileNotFoundError: return {'schema': SCHEMA, 'url': self.transport.url, 'project': self.transport.project, 'holder_id': uuid.uuid4().hex,
                                          'items': {}, 'seen': None, 'pending': None}
        except (OSError, ValueError): raise NotValid(self._say('not-valid', {'reasons': 'the record of what you hold in this folder cannot be read'})) from None
        if not isinstance(record, dict) or record.get('schema') != SCHEMA or not isinstance(record.get('items'), dict):
            raise NotValid(self._say('not-valid', {'reasons': 'this folder holds a record this version cannot read'}))
        if (record.get('url'), record.get('project')) != (self.transport.url, self.transport.project):
            raise NotValid(self._say('not-valid', {'reasons': 'this folder holds items of another project; use another folder'}))
        return record

    def _save(self, record):
        _atomic(self.path, record)

    def held(self):
        """What this folder holds (a copy; changing it changes nothing)."""
        return json.loads(json.dumps(self._load()['items']))

    @contextlib.contextmanager
    def _locked(self):
        lock = folder_lock(self.lock_path, self.lock_timeout)
        try: lock.__enter__()
        except Busy_: raise FolderBusy(self._say('folder-busy', {})) from None
        try: yield
        finally: lock.__exit__(None, None, None)

    def _lock(self):
        lock = folder_lock(self.lock_path, self.lock_timeout)
        try: lock.__enter__()
        except Busy_: raise FolderBusy(self._say('folder-busy', {})) from None
        return lock

    # words

    def _say(self, code, facts):
        return self.sentences[code](facts)

    def _raise(self, code, facts=None, technical=None, error=None):
        facts = facts or {}
        if error is not None:
            technical = dict(technical or {}, code=getattr(error, 'code', None), status=getattr(error, 'status', None),
                             stage=getattr(error, 'stage', None), server_message=getattr(error, 'server_message', None) or str(error))
        raise REFUSALS[code](self._say(code, facts), facts, technical) from error

    def _transport_error(self, error, refused, invalid='not-valid', facts=None):
        """Map a transport error to its outcome. `refused` is the outcome of a 403/404 for this action."""
        kind = failure(error)
        if kind in REFUSALS: code = kind
        else: code = {'refused': refused, 'invalid': invalid, 'stale': invalid}[kind]
        reasons = {'reasons': 'the request was not accepted'}
        self._raise(code, {**reasons, **(facts or {})}, error=error)

    def _who(self, version):
        when = _when(version.get('at'), self.clock())
        return {'number': version.get('number'), 'who': display(version.get('by'), 'someone') if version.get('at') or version.get('by') else None,
                'when': when}

    def _history(self, item):
        try: versions = self.transport.history(item)
        except Exception: return None  # a failed history read never turns an answer into an error
        return versions if isinstance(versions, list) else None

    def _at(self, item, revision):
        """number, who and when of one version, from history; empty when history is unavailable."""
        for v in self._history(item) or []:
            if v.get('revision') == revision: return self._who(v)
        return {}

    def _inventory(self):
        try: return {i['asset_id']: i for i in self.transport.inventory()}
        except Exception as error: self._transport_error(error, refused='sign-in-needed', invalid='could-not-reach')

    @staticmethod
    def _name(item, fallback='an item'):
        return display((item or {}).get('name'), fallback)

    # check for updates

    def check(self):
        """What is newer than what this folder holds, what is new and what can no longer be seen. Changes nothing
        but the list of items seen (for "new since your last check")."""
        record, inventory = self._load(), self._inventory()
        newer, lost, new = [], [], []
        for ident, entry in sorted(record['items'].items(), key=lambda kv: (kv[1].get('name') or '', kv[0])):
            item = inventory.get(ident)
            if item is None: lost.append({'asset_id': ident, 'name': self._name(entry)}); continue
            if item.get('revision') != entry.get('revision'):
                newer.append({'asset_id': ident, 'name': self._name(item), 'revision': item.get('revision'), **self._at(item, item.get('revision'))})
        seen = record.get('seen')
        baseline = seen is None
        if not baseline:
            for ident, item in sorted(inventory.items(), key=lambda kv: (kv[1].get('name') or '', kv[0])):
                if ident not in seen and not any(n['asset_id'] == ident for n in newer):
                    new.append({'asset_id': ident, 'name': self._name(item)})
        facts = {'newer': newer, 'new': new, 'lost': lost, 'holding': bool(record['items']), 'baseline': baseline, 'visible': len(inventory)}
        code = 'updates' if newer or new else 'access-changed' if lost else 'nothing-new'
        self._remember(sorted(inventory))
        return Outcome(code, self._say(code, facts), facts, {'inventory': len(inventory)})

    def _remember(self, seen):
        """The ids seen, written only when no other program holds the folder (check never waits)."""
        lock = folder_lock(self.lock_path, 0)
        try: lock.__enter__()
        except Busy_: return
        try:
            record = self._load(); record['seen'] = seen; self._save(record)
        finally: lock.__exit__(None, None, None)

    # get latest

    def fetch(self, item_id, *, output=None, **how):
        """Fetch the latest version of an item. Returns a Receipt to confirm once applied, or an Outcome when this
        folder already holds that version in `output`. The folder is locked until the receipt is confirmed or released."""
        lock = self._lock()
        try:
            record, inventory = self._load(), self._inventory()
            entry, item = record['items'].get(item_id), inventory.get(item_id)
            if item is None: self._raise('not-visible', {'name': self._name(entry, 'this item')}, {'asset_id': item_id})
            name, head = self._name(item), item.get('revision')
            selection = json.loads(json.dumps(how, sort_keys=True, default=list))
            output = Path(output).expanduser().absolute() if output is not None else None
            out = (entry or {}).get('output') or {}
            if (output is not None and entry and entry.get('revision') == head and out.get('path') == str(output) and out.get('selection') == selection
                    and output.is_dir() and folder_digest(output) == out.get('sha256')):
                facts = {'name': name, 'folder': str(output)}
                lock.__exit__(None, None, None); lock = None
                return Outcome('already-latest', self._say('already-latest', facts), facts, {'asset_id': item_id, 'revision': head})
            staging = output.with_name('.%s.partial-%s' % (output.name, uuid.uuid4().hex[:8])) if output is not None else None
            try:
                try: got = self.transport.fetch(item, head, staging, **how)
                except ExchangeRefused as refusal: self._raise(refusal.outcome, {**refusal.facts, 'name': name}, refusal.technical)
                except Exception as error: self._transport_error(error, refused='not-visible', invalid='could-not-reach', facts={'name': name})
                digest = None
                if staging is not None:
                    staging.mkdir(mode=0o700, exist_ok=True)  # the transport creates it when it writes files
                    digest = folder_digest(staging)
                    if output.exists():
                        aside = output.with_name('.%s.old-%s' % (output.name, uuid.uuid4().hex[:8]))
                        os.replace(output, aside); os.replace(staging, output); shutil.rmtree(aside, ignore_errors=True)
                    else: os.replace(staging, output)
            except BaseException:
                if staging is not None: shutil.rmtree(staging, ignore_errors=True)
                raise
            facts = {'name': name, **({'folder': str(output)} if output is not None else {}), **(got.get('facts') or {})}
            number = got.get('number')
            known = self._at(item, head) if item.get('kind') != 'external-scalar-map' else {}
            facts.update({k: v for k, v in known.items() if v is not None})
            if number and not facts.get('number'): facts['number'] = number
            entry = {'asset_id': item_id, 'name': item.get('name'), 'kind': item.get('kind'), 'revision': head, 'number': facts.get('number'),
                     'output': {'path': str(output), 'sha256': digest, 'selection': selection} if output is not None else None}
            receipt = Receipt(self, lock, entry, got.get('content'), facts); lock = None
            return receipt
        finally:
            if lock is not None: lock.__exit__(None, None, None)

    def get(self, item_id, *, output=None, **how):
        """Fetch, persist into `output` (when given), then advance the record."""
        got = self.fetch(item_id, output=output, **how)
        return got if isinstance(got, Outcome) else got.confirm(applied_to=output)

    # send to project

    def send(self, data, *, name, profile, how, based_on=(), of=None, declare=None, extra=None, expected=None):
        """Publish `data` as a new item, or (with `of`, a held item) as its next version. The parent is the version
        this folder holds, never the project's head; `based_on` are held items. The complete request is saved before
        it is sent, so running the same send again after a crash never publishes twice. `expected` (with `of`) is the
        revision the caller built on: when this folder holds another one, nothing is sent (E104). It only refuses, is
        not part of the saved request, and a retry of an unfinished send never reads it."""
        if isinstance(data, (str, Path)): data = Path(data).read_bytes()
        if not isinstance(data, (bytes, bytearray)) or not data: self._raise('not-valid', {'reasons': 'the file is empty'})
        data = bytes(data)
        reasons = [r for ok, r in ((isinstance(name, str) and name.strip() and len(name) <= 160, 'give the item a name of up to 160 characters'),
                                   (isinstance(profile, str) and profile.strip(), 'say what type of file this is'),
                                   (isinstance(how, str) and how.strip() and len(how) <= 80, 'say how you made it, in up to 80 characters'),
                                   (isinstance(based_on, (list, tuple)) and 1 <= len(based_on) <= 32 and len(set(based_on)) == len(based_on),
                                    'name between 1 and 32 items it is based on, each once'),
                                   (declare is None or isinstance(declare, dict), 'give declarations as names and values'),
                                   (extra is None or isinstance(extra, dict), 'give extra details as names and values')) if not ok]
        if reasons: self._raise('not-valid', {'reasons': '; '.join(reasons)})
        if len(data) > MAX_SEND: self._raise('too-large', {})
        request = {'name': name, 'profile': profile, 'how': how, 'based_on': list(based_on), 'of': of, 'declare': dict(declare or {}),
                   'extra': json.loads(json.dumps(extra or {}, sort_keys=True)), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        with self._locked():
            record = self._load()
            pending, first = record.get('pending'), False
            identity = self.transport.identity()
            if pending:
                facts = {'name': display(pending['request'].get('name'), 'an item')}
                if pending.get('owner') != identity: self._raise('outcome-unknown', {**facts, 'other_key': True})
                if pending['request'] != request:
                    self._raise('not-valid', {'reasons': 'an earlier send from this folder is unfinished: run it again unchanged, or set it aside'})
            else:
                missing = [i for i in ([of] if of is not None else []) + list(based_on) if i not in record['items']]
                if missing:
                    self._raise('not-held', {'name': self._name(record['items'].get(missing[0]), 'that item')}, {'asset_id': missing[0]})
                if expected is not None and of is None:
                    self._raise('not-valid', {'reasons': 'name the item this is a new version of, together with the version it builds on'})
                if expected is not None and expected != record['items'][of]['revision']:  # before same_content: identical bytes are still refused
                    self._raise('newer-version-exists', {'name': self._name(record['items'][of])})
                if of is not None and self.transport.same_content(record['items'][of], request):
                    held = record['items'][of]
                    self._raise('nothing-changed', {'name': self._name(held), 'number': held.get('number')})
                resolved = {'parents': [{'asset_id': i, 'revision': record['items'][i]['revision']} for i in based_on],
                            'expected_parent': record['items'][of]['revision'] if of is not None else None}
                pending = {'command_id': uuid.uuid4().hex, 'request': request, 'resolved': resolved, 'owner': identity, 'started': self.clock()}
                record['pending'] = pending; self._save(record); first = True  # saved BEFORE anything is sent
            facts = {'name': display(name, 'the item')}
            try:
                receipt = self.transport.publish(data, pending['request'], pending['resolved'], pending['command_id'])
            except ExchangeRefused as refusal:
                if first: self._clear()
                self._raise(refusal.outcome, {**facts, **refusal.facts}, refusal.technical)
            except Exception as error:
                kind = failure(error)
                if kind == 'stale':
                    self._clear(); self._stale(error, of, data, facts)  # stale is checked after replay: the command was not recorded
                if kind == 'could-not-reach': self._raise('outcome-unknown', facts, {'command_id': pending['command_id']}, error=error)
                if first and kind != 'rate-limited': self._clear()  # refused before anything was kept; a retry's earlier attempt stays unknown
                self._transport_error(error, refused='access-refused', facts=facts)
            record = self._load()
            number = receipt.get('number')
            record['items'][receipt['asset_id']] = {'asset_id': receipt['asset_id'], 'name': name, 'kind': 'derived', 'revision': receipt['revision'],
                                                    'number': number, 'got_at': self.clock(), 'sent': True, 'output': None,
                                                    'note': (record['items'].get(receipt['asset_id']) or {}).get('note')}
            record['pending'] = None
            self._save(record)
            code = 'sent-version' if pending['request'].get('of') is not None else 'sent-new'
            facts = {**facts, 'number': number}
            return Outcome(code, self._say(code, facts), facts, {'asset_id': receipt['asset_id'], 'revision': receipt['revision'], 'command_id': pending['command_id']})

    def _clear(self):
        record = self._load(); record['pending'] = None; self._save(record)

    def _stale(self, error, of, data, facts):
        """A stale-parent or duplicate-content refusal: history (read after it) says which."""
        record = self._load()
        held = record['items'].get(of) if of is not None else None
        versions = self._history(dict(held or {}, asset_id=of)) if held else None
        digest = hashlib.sha256(data).hexdigest()
        if versions:
            same = [v for v in versions if v.get('revision') == digest]
            if same: self._raise('nothing-changed', {**facts, 'number': same[0].get('number')}, error=error)
            head = versions[-1]
            if held and head.get('revision') != held.get('revision'):
                self._raise('newer-version-exists', {**facts, **{k: v for k, v in self._who(head).items() if v is not None}}, error=error)
        self._raise('newer-version-exists', facts, error=error)  # history unavailable: the number-free sentence

    def abandon_pending(self):
        """Set an unfinished send aside. An item may already exist in the project; nothing is deleted there."""
        with self._locked():
            record = self._load(); pending = record.get('pending')
            if not pending: self._raise('not-valid', {'reasons': 'there is no unfinished send in this folder'})
            record['pending'] = None; self._save(record)
            facts = {'name': display(pending['request'].get('name'), 'an item')}
            return Outcome('abandoned', self._say('abandoned', facts), facts, {'command_id': pending['command_id']})


# -- the SDK's transport (E70a C3) ------------------------------------------------------------------------
# Everything below reaches the project through ophiolite.Client; its imports stay inside the methods so the core
# above remains importable without httpx or pydantic.

UPLOAD_SUCCESSOR = 'a newer version of an uploaded file cannot be received yet'


class ClientTransport:
    """check, get and send over an ophiolite.Client: the inventory, result history, exact reads and derived
    publication routes that already exist. No route of its own."""
    def __init__(self, client):
        self.client, self.url, self.project = client, client.url, client.project
        self._names = {}

    def identity(self):
        """Who sends. An access key cannot learn the person it belongs to without a new route (stop rule 8), so a
        pending send is bound to the key itself (its SHA-256, as WorkFolder does) or, for an application grant, to the
        grant's person; a send started with another key is never repeated."""
        headers = self.client._headers()
        if headers.get('X-Ophiolite-Application-Grant'):
            status = self.client._grant_status(headers)
            if status.get('state') == 'approved' and isinstance(status.get('user_id'), str) and status['user_id']:
                return {'kind': 'grant', 'user_id': status['user_id']}
        token = headers.get('Authorization', '')
        if not token.startswith('Bearer ') or not token[7:]: raise AuthenticationRequired('Supply an access key.', status=401, stage='no-credential')
        return {'kind': 'delegate', 'fingerprint': hashlib.sha256(token[7:].encode()).hexdigest()}

    def inventory(self):
        return self.client.sync().inventory()

    def _exact(self, area, operation, body):
        """A read whose request names the project inside its reference (the map routes refuse a top-level project_id)."""
        from .publish import json_bytes
        return self.client._post_bytes(area, operation, json_bytes(body))

    def history(self, item):
        if item.get('kind') == 'external-scalar-map':  # numbers only: a map's history names no author or time (E71a C1)
            page = self._exact('catalog', 'history', {'asset': {'project_id': self.project, 'asset_id': item['asset_id']}})
            numbers = sorted(int(r['revision']) for r in page.get('revisions', []) if str(r.get('revision', '')).isdigit())
            return [{'number': n, 'revision': str(n), 'by': None, 'at': None} for n in numbers]
        if item.get('kind') != 'derived': raise Refused('Only derived results list their versions here.')
        page = self.client._post('applications', 'result-history', {'asset_id': item['asset_id']})
        names = (page.get('display') or {}).get('member_names') or {}
        return [{'number': r.get('number'), 'revision': r.get('revision'), 'by': names.get(r.get('by')), 'at': r.get('published_at')}
                for r in page.get('revisions', [])]

    def fetch(self, item, revision, output, **how):
        kind, asset = item.get('kind'), item['asset_id']
        if kind == 'external-scalar-map': return self._map(asset, revision, output)
        if kind not in ('derived', 'uploaded'): raise CannotReadHere('', {'reason': 'this kind of item is not one this script can receive'})
        curves = how.get('curves')
        if curves:
            data = self.client.read(asset, revision, list(curves))
            descriptor = data.wire_descriptors[0] if getattr(data, 'wire_descriptors', None) else {}
            self._successor(kind, descriptor)
            if output is not None: data.save(output)
            return {'content': data, 'number': self._number(kind, descriptor)}
        from .errors import Incompatible
        try: data = self.client.read_data(asset, revision)
        except (Incompatible, Refused) as error:
            if getattr(error, 'status', None) in (400, 422) or error.code in ('INVALID_ARGUMENT', 'incompatible-context'):
                raise CannotReadHere('', {'reason': 'name the curves to receive a well log'}) from None
            raise
        descriptor = data._wire_descriptor
        self._successor(kind, descriptor)
        if data.type == 'seismic-volume': raise CannotReadHere('', {'reason': 'a seismic volume is described here, not received; read its slices in Python'})
        if output is not None:
            output.mkdir(mode=0o700)
            (output / 'original').write_bytes(data.original); (output / 'data.json').write_bytes(data._wire_data_bytes)
            (output / 'descriptor.json').write_text(json.dumps(descriptor, indent=2) + '\n')
        return {'content': data, 'number': self._number(kind, descriptor)}

    def _map(self, asset, revision, output):
        """E70a C4: a map through the existing export route: a GeoTIFF generated from the stored map (not the imported
        file), checked for project, asset, revision and representation before any digest, then against its manifest."""
        import base64, binascii
        try: reply = self._exact('maps', 'export', {'reference': {'project_id': self.project, 'asset_id': asset, 'revision': str(revision)}})
        except Refused as error:
            if getattr(error, 'status', None) in (400, 404, 422): raise MapUnavailable('', {}) from None
            raise
        reference = reply.get('reference') if isinstance(reply, dict) else None
        if (not isinstance(reference, dict) or reply.get('asset') != asset or str(reply.get('revision')) != str(revision) or reference.get('asset_id') != asset
                or reference.get('project_id') != self.project or str(reference.get('revision')) != str(revision) or reply.get('representation') != 'source'):
            raise Damaged('', {})
        try:
            raw = base64.b64decode(reply['raster'], validate=True); source = reply['source_text'].encode()
            files = reply['manifest']['files']
        except (binascii.Error, KeyError, TypeError, AttributeError, ValueError): raise Damaged('', {}) from None
        if hashlib.sha256(raw).hexdigest() != files.get('map.tif') or hashlib.sha256(source).hexdigest() != files.get('source.txt'): raise Damaged('', {})
        if output is not None:
            output.mkdir(mode=0o700)
            (output / 'map.tif').write_bytes(raw); (output / 'source.txt').write_bytes(source)
            (output / 'manifest.json').write_text(json.dumps(reply['manifest'], indent=2, sort_keys=True) + '\n')
        return {'content': raw, 'number': int(revision) if str(revision).isdigit() else None, 'facts': {'map': True}}

    @staticmethod
    def _number(kind, descriptor):
        """The version number a descriptor states; an upload without `history` is its only version (E53 adds it from 2)."""
        number = (descriptor.get('history') or {}).get('number')
        return number if number is not None or kind != 'uploaded' else 1

    @staticmethod
    def _successor(kind, descriptor):
        if kind == 'uploaded' and (descriptor.get('history') or {}).get('number', 1) > 1:
            raise CannotReadHere('', {'reason': UPLOAD_SUCCESSOR})  # E53: until receiving one is supported (A2)

    def publish(self, data, request, resolved, command_id):
        from .writers import WrittenOriginal
        written = WrittenOriginal(data, request['profile'], dict(request.get('declare') or {}), 'derived')
        receipt = self.client.publish_derived(written, name=request['name'], from_=[(p['asset_id'], p['revision']) for p in resolved['parents']],
                                              method={'name': request['how'], 'declared': False}, command_id=command_id,
                                              new_version_of=request.get('of'), expected_parent=resolved.get('expected_parent'))
        return {'asset_id': receipt.asset_id, 'revision': receipt.revision, 'number': receipt.revision_number}

    def same_content(self, held, request):
        return request['sha256'] == held.get('revision')

    def report(self, reference, holder_id, event_id):
        """E70b: one delivery observation on the project route (`exchange-consumer/1`); the reference names the
        project. One attempt, a short timeout: a confirmation never waits long for it."""
        from .publish import json_bytes
        body = {'reference': reference, 'binding_id': holder_id, 'event_id': event_id, 'profile': 'exchange-consumer/1', 'mode': 'get'}
        return self.client._post_bytes('activity', 'report', json_bytes(body), timeout=REPORT_TIMEOUT)
