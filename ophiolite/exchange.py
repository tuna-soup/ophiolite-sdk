"""E70a: check for updates, get latest, send to project (ADR 0021).

The shared core: the standard library and `.errors` only, so a host application's Python (QGIS) can carry it
(family rule X4). A *transport* reaches the project; this module never does. The record of what this program
holds (`held.json`, schema `ophiolite.held/1`) lives in a work folder that one program at a time may change
(`held.lock`); `check` reads it without the lock. E173: once an item records the words it was named by (`words`) or
whether it stays on the version it holds (`mode`), the record is `ophiolite.held/2` and stays so, which an older SDK
refuses instead of dropping those fields.

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
  publish(data, request, resolved, command_id, attribution=None) -> {asset_id, revision, number}
                                     E171 s1: `attribution` ({holder, application}, saved with the pending send) names
                                     this folder as the sender's copy; it is passed only when the pending send has one
  same_content(held_entry, request)  whether a send would add nothing
  report(reference, holder_id, event_id, **held)   optional (E70b): tell the project this holder received that exact
                                     version; called once by Receipt.confirm, after the record advanced; a failure changes
                                     nothing. E171 s1: `held` is application, holds and earlier, each only when set; a
                                     transport that refuses them (an older gateway) is asked once more without them.
                                     E184 s0: and `receipt`, the get's transfer receipt
  keeps_receipts(version) -> bool    optional (E184 s0): whether the project keeps transfer receipts of that code
                                     document version; without it, or answering False, no receipt is sent (`publish`
                                     then takes `receipt=` too)
  release(holder_id, item) -> bool   optional (E171 s1): this folder no longer holds `item` (exchange/release)
Errors a transport raises carry `status`, `code` and `stage` attributes (the SDK's errors do); the core classifies
by code, then credential stage, then status, never by message text.
"""
import contextlib
import hashlib
import inspect
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from .errors import AuthenticationRequired, Busy, IntegrityConflict, OphioliteError, PermissionRefused, Refused, Unavailable, VerificationFailed

SCHEMA = 'ophiolite.held/1'
SCHEMA_WORDS = 'ophiolite.held/2'  # E173 s0 (D1): written once an entry carries `words` or `mode`; never back to /1
MAX_SEND = 32 * 1024 * 1024
DECLARATION = ('well', 'depth_kind', 'depth_datum')  # E188 C1: a sent curve's declaration, all three (E183 s2b's upload_data)
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


MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')


def _day(at):
    """'10 October 2026': the UTC calendar day of a version's time, as the server says it (E108 D5); None when unknown."""
    if not isinstance(at, (int, float)) or isinstance(at, bool): return None
    day = time.gmtime(at)
    return '%d %s %d' % (day.tm_mday, MONTHS[day.tm_mon - 1], day.tm_year)


def _earlier(f):
    if not f.get('number'): return 'This content was an earlier version.'
    return 'This content was version %d on %s.' % (f['number'], f['day']) if f.get('day') else 'This content was version %d.' % f['number']


def _newer(f):
    if not f.get('number'):
        return 'A newer version was added first. Your change was not sent. Either get the latest version and look at it, or send yours as a new item.'
    who = ' by %s, %s' % (f['who'], f['when']) if f.get('who') and f.get('when') else ' by %s' % f['who'] if f.get('who') else ''
    return 'Version %d was added%s. Your change was not sent. Either get version %d and look at it, or send yours as a new item.' % (f['number'], who, f['number'])


def _stays(f):
    """E173 s0 (D2): "latest" comes from comparing revisions (`newer`), never from a missing number."""
    held = 'version %d of %s' % (f['number'], f['name']) if f.get('number') else 'the version of %s you hold' % f['name']
    if not f.get('newer'): return 'You stay on %s, the latest.' % held
    if f.get('newer_number'): return 'You stay on %s. Version %d is newer; get it with stay=False to take it.' % (held, f['newer_number'])
    return 'You stay on %s. A newer version exists; get it with stay=False to take it.' % held


def _candidate(c):
    """"a horizon by Ada (version 2)" from what is known of one item; a part that is unknown is left out, never guessed."""
    word = c.get('type')
    text = ('an %s' if word[:1].lower() in 'aeiou' else 'a %s') % word if word else 'an item'
    text += ' by %s' % c['who'] if c.get('who') else ''
    return text + (' (version %d)' % c['number'] if c.get('number') else '')


def _unclear(f):
    said = [_candidate(c) for c in f.get('candidates') or ()]
    listed = ', '.join(said[:-1]) + ' and ' + said[-1] if len(said) > 1 else ''.join(said)
    return 'More than one item you can see is called %s%s. Name the type as well.' % (f['name'], ': ' + listed if listed else '')


SENTENCES = {
    'nothing-new': lambda f: ('Nothing is newer than what you hold.' if f.get('holding') else 'You hold nothing yet.') + _first(f),
    'updates': lambda f: _updates(f) + _first(f),
    'access-changed': lambda f: 'You can no longer see %d item%s you hold: %s. They may have been removed or no longer shared with you.' % (
        len(f['lost']), '' if len(f['lost']) == 1 else 's', _names(f['lost'])),
    'got': lambda f: _got(f),
    'already-latest': lambda f: 'You already hold the latest version of %s, saved in %s.' % (f['name'], f['folder']),
    'not-visible': lambda f: 'You can no longer see %s. It may have been removed or no longer shared with you.' % f['name'],
    'cannot-read-here': lambda f: f.get('sentence') or 'This kind of item cannot be received by this script yet: %s.' % f['reason'],  # E141 s2: a window's own sentence
    'damaged': lambda f: 'The data did not match its fingerprint. Nothing was kept.',
    'map-unavailable': lambda f: 'That version of the map is not available (it may be withdrawn or not the one you hold).',
    'sent-new': lambda f: 'Sent %s as a new item; it is private until you share it.' % f['name'],
    'sent-version': lambda f: 'Sent %s as version %d. Version %d is kept.' % (f['name'], f['number'], f['number'] - 1) if (f.get('number') or 0) > 1 else
                              'Sent %s as a new version. The earlier version is kept.' % f['name'],
    'newer-version-exists': lambda f: _newer(f),
    'nothing-changed': lambda f: 'This is the same as version %d; nothing was sent.' % f['number'] if f.get('number') else 'This is the same as the version you hold; nothing was sent.',
    'earlier-version': _earlier,  # E108 S3 (D5's SDK half): the server's sentence for an earlier version's content
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
    'stays': _stays,  # E173 s0 (D2): a folder that stays on the version it holds
    'name-unclear': _unclear,
    'name-not-found': lambda f: 'No item you can see is called %s%s. Nothing was changed.' % (f['name'], ' (%s)' % f['type'] if f.get('type') else ''),
    'made-for': lambda f: ('%s%s: the version this name means now. Send with this exact version to record what your file was made for. '
                           'Nothing was changed.' % (f['name'], _version({'number': f.get('number'), 'who': f.get('by'), 'when': f.get('when')}))),  # E192 s2
}
OUTCOMES = tuple(SENTENCES)


def held_line(held_by, on_an_older_version):
    """E171 design 6: the line a successful send adds, in the Workspace's words (HeldCopies.tsx `heldSendLine`)."""
    said = 'Held by %d connected application%s' % (held_by, '' if held_by == 1 else 's')
    return said + (', %d of them on an older version.' % on_an_older_version if on_an_older_version else '.')


# E184 s0 (D-1, D-3, D-5, D-6): a transfer receipt (`ophiolite.transfer-receipt/1`) says what one get or send kept,
# changed and did not carry. The connector that acts computes it; this core checks it against the code document
# (`ophiolite.transfer-codes/1`, which the caller passes: the core reads no files) before anything is done, sends it
# only to a project whose capabilities list the document's version, and returns it on the outcome.
UNLISTED = 'This transfer would report a change its route does not declare, so nothing was done.'
SHAPE = 'This transfer\'s receipt is not well formed, so nothing was done.'
NOT_KEPT = ' This project did not keep the lists; they are on your screen only.'
UNCONFIRMED = ' It is not known whether the project kept the lists.'
RECEIPT_LISTS = (('kept', 'Kept'), ('changed', 'Changed'), ('not_carried', 'Not carried'))
RECEIPT_ROWS, RECEIPT_BYTES = 8, 2048
_CODE = re.compile(r'[a-z][a-z0-9-]{1,47}')
_CAPABILITY = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
_CONTRACT = re.compile(r'[a-z0-9][a-z0-9.-]*(/[a-z0-9.-]+)*/[0-9]+')
_SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
_COPY = re.compile(r'[0-9a-f]{16}')


def receipt_bytes(receipt):
    """The receipt as a request carries it: compact JSON, UTF-8, keys sorted."""
    return json.dumps(receipt, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _text(value, most):
    return isinstance(value, str) and 1 <= len(value) <= most


def _number(value, least):
    return type(value) is int and value >= least


def _exact(value, keys, optional=()):
    return isinstance(value, dict) and set(keys) <= set(value) <= set(keys) | set(optional)


def _receipt_shape(r):
    """The first rule of the published contract a receipt breaks, or None (the gateway's TransferReceipt, by hand)."""
    lists = [n for n, _ in RECEIPT_LISTS]
    if not _exact(r, ('schema', 'direction', 'capability', 'route', 'contract', 'state', 'base', 'made', 'fingerprints', 'codes', *lists)): return 'keys'
    if r['schema'] != 'ophiolite.transfer-receipt/1' or r['direction'] not in ('get', 'send') or r['state'] not in ('planned', 'committed'): return 'words'
    if not (isinstance(r['capability'], str) and _CAPABILITY.fullmatch(r['capability'])): return 'capability'
    route = r['route']
    if not (_exact(route, ('profile', 'data', 'direction')) and _text(route['profile'], 80) and _text(route['data'], 80)
            and route['direction'] in ('read', 'write', 'publish', 'export')): return 'route'
    if not (isinstance(r['contract'], str) and len(r['contract']) <= 128 and _CONTRACT.fullmatch(r['contract'])): return 'contract'
    base, made = r['base'], r['made']
    if base is not None and not (_exact(base, ('item', 'revision', 'number')) and _text(base['item'], 512) and _text(base['revision'], 512)
                                 and _number(base['number'], 1)): return 'base'
    version = _exact(made, ('revision', 'number')) and _text(made['revision'], 512) and _number(made['number'], 1)
    copy = _exact(made, ('copy',)) and isinstance(made['copy'], str) and bool(_COPY.fullmatch(made['copy']))
    if made is not None and not (version or copy): return 'made'
    if not (_exact(r['fingerprints'], ('source', 'target', 'converter')) and all(_text(v, 128) for v in r['fingerprints'].values())): return 'fingerprints'
    codes = r['codes']
    if not (_exact(codes, ('id', 'version')) and codes['id'] == 'ophiolite.transfer-codes/1' and isinstance(codes['version'], str)
            and _SEMVER.fullmatch(codes['version'])): return 'codes'
    for name in lists:
        rows = r[name]
        if not (isinstance(rows, list) and len(rows) <= RECEIPT_ROWS): return name
        for row in rows:
            if not (_exact(row, ('code', 'sentence'), ('count', 'value')) and isinstance(row['code'], str) and _CODE.fullmatch(row['code'])
                    and _text(row['sentence'], 200) and ('count' not in row or _number(row['count'], 0))
                    and ('value' not in row or _text(row['value'], 80))): return name
    if (r['state'] == 'planned') != (made is None): return 'state'
    if made is not None and copy != (r['direction'] == 'get'): return 'made'
    if r['direction'] == 'get' and base is None: return 'base'
    if len(receipt_bytes(r)) > RECEIPT_BYTES: return 'bytes'
    return None


def receipt_problem(receipt, codes):
    """None, or (sentence, technical) for the first problem (D-3), with the gateway's verdicts (tests T4):
    SHAPE when the contract refuses the receipt, its codes version is not the document's, the document lists no row for
    its route or another contract for it, a row's sentence is not its code's template filled with the row's own
    measure, or a code is listed twice in one list; UNLISTED for a row whose code the route does not list in that list."""
    rule = _receipt_shape(receipt)
    if rule is not None: return SHAPE, {'reason': 'contract', 'error': rule}
    if not isinstance(codes, dict) or receipt['codes']['version'] != codes.get('version'):
        return SHAPE, {'reason': 'codes-version', 'version': receipt['codes']['version']}
    key = (receipt['capability'], receipt['route']['profile'], receipt['route']['data'], receipt['route']['direction'])
    route = next((r for r in codes.get('routes') or () if (r['capability'], r['profile'], r['data'], r['direction']) == key), None)
    if route is None: return SHAPE, {'reason': 'route', 'capability': receipt['capability'], 'route': receipt['route']}
    if receipt['contract'] != route['contract']: return SHAPE, {'reason': 'contract-id', 'contract': receipt['contract']}
    listed = {c['code']: c for c in route['codes']}
    for name, _ in RECEIPT_LISTS:
        if len({r['code'] for r in receipt[name]}) != len(receipt[name]): return SHAPE, {'reason': 'twice', 'list': name}
        for row in receipt[name]:
            entry = listed.get(row['code'])
            if entry is None or entry['list'] != name: return UNLISTED, {'code': row['code'], 'list': name}
            measured = {k: row[k] for k in ('count', 'value') if row.get(k) is not None}
            if set(measured) != {entry['measure']} - {'none'} or row['sentence'] != entry['sentence'].format(**measured):
                return SHAPE, {'reason': 'sentence', 'code': row['code']}
    return None


def receipt_lines(receipt):
    """The three lists as a person reads them: a heading each, one sentence per row, `nothing` for an empty list; never
    a code, a contract id or a fingerprint (the sentence already carries any count or value)."""
    lines = []
    for name, heading in RECEIPT_LISTS:
        lines.append(heading + ':')
        lines.extend(['  ' + row['sentence'] for row in receipt[name]] or ['  nothing'])
    return lines


class Outcome:
    """A success: `outcome` (a code from OUTCOMES), `sentence`, display `facts` and `technical` detail. E184 s0 (D-5):
    `receipt`, the transfer receipt the act was done with, when there was one."""
    def __init__(self, outcome, sentence, facts=None, technical=None, receipt=None):
        self.outcome, self.sentence, self.facts, self.technical = outcome, sentence, facts or {}, technical or {}
        self.receipt = receipt

    def to_dict(self):
        said = {'outcome': self.outcome, 'sentence': self.sentence, 'facts': self.facts, 'technical': self.technical}
        if self.receipt is not None: said['receipt'] = self.receipt  # only when there is one, so an answer without is unchanged
        return said

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
EarlierVersion = _refusal('earlier-version', IntegrityConflict)
AccessRefused = _refusal('access-refused', PermissionRefused)
NotValid = _refusal('not-valid', Refused)
NotHeld = _refusal('not-held', Refused)
TooLarge = _refusal('too-large', Refused)
OutcomeUnknown = _refusal('outcome-unknown', Unavailable)  # cli.exit_code: the code 'outcome-unknown' is 5
FolderBusy = _refusal('folder-busy', Busy)
RateLimited = _refusal('rate-limited', Busy)
SignInNeeded = _refusal('sign-in-needed', AuthenticationRequired)
CouldNotReach = _refusal('could-not-reach', Busy)
NameUnclear = _refusal('name-unclear', Refused)  # E173 s0 (D2): ids only in technical['candidates']
NameNotFound = _refusal('name-not-found', Unavailable)  # its own code, not the category's, as not-visible
REFUSALS = {c.outcome: c for c in (NotVisible, CannotReadHere, Damaged, MapUnavailable, NewerVersionExists, NothingChanged, EarlierVersion, AccessRefused, NotValid,
                                   NotHeld, TooLarge, OutcomeUnknown, FolderBusy, RateLimited, SignInNeeded, CouldNotReach, NameUnclear, NameNotFound)}

# E173 s0 (D3): the closed list of type words, one per source profile of the registry (checked by
# tests/test_exchange_type_words.py); a literal table, since the core reads no files and the plug-in carries no contracts.
TYPE_WORDS = {
    'well log': ('las2/1', 'osdu-welllog-parquet/1'),
    'horizon': ('esri-ascii-grid/1', 'zmap-plus-grid/1', 'cps3-ascii-grid/1', 'irap-ascii-grid/1', 'opendtect-horizon-ascii/1', 'petrel-horizon-ilxl/1'),
    'point set': ('points-csv/1', 'petrel-points-attributes/1'),
    'map': ('geotiff/1', 'petrel-scattered-data/1'),
    'map features': ('esri-shapefile/1', 'ogc-geopackage/1', 'geojson/1'),
    'well tops': ('well-tops-csv/1', 'petrel-well-tops/1'),
    'wells': ('sql-wells/1', 'edited-wells/1', 'well-location/1', 'well-set/1'),
    'deviation survey': ('deviation-csv/1',),
    'well path': ('well-path-positions-csv/1',),
    'time-depth table': ('time-depth-csv/1',),
    'surface': ('mesh-text/1', 'gocad-ascii/1'),
    'fault sticks': ('petrel-faultsticks/1', 'opendtect-faultsticks/1'),
    'seismic volume': ('segy/1', 'segy/2', 'segy/3'),
    'seismic line': ('segy-line/1',),
    'seismic section': ('seismic-section-text/1',),
    'wavelet': ('wavelet-text/1',),
    'rock model section': ('model-section-text/1',),
    'residual result': ('well-residual/1',),
    'table': ('table/1', 'table-csv/1', 'table-excel/1', 'table-parquet/1'),
    'RESQML package': ('resqml-epc/1',),
    'OSDU record': ('osdu-record/1',),
}
NO_WORD = ('native-external/1',)  # named by name only


def type_profiles(word):
    """The profiles a type word names; an unknown word is refused (not-valid), never matched loosely."""
    if isinstance(word, str) and word in TYPE_WORDS: return TYPE_WORDS[word]
    raise NotValid(SENTENCES['not-valid']({'reasons': '%s is not a type this version knows' % display(word, 'that')}))


def type_word(profile):
    """The type word of a profile, or None (a native kind, or a profile named by name only)."""
    return next((word for word, profiles in TYPE_WORDS.items() if profile in profiles), None)


def _item_type(item):
    """E173 s1 (D2, s0b): the type word of an inventory item. A point set its sender said represents a horizon is a
    horizon (the two point profiles named literally, F4); otherwise its profile's word; no profile, no word."""
    if item.get('profile') in ('points-csv/1', 'petrel-points-attributes/1') and item.get('represents') == 'horizon': return 'horizon'
    return type_word(item.get('profile'))


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


NOT_VERSIONED = 'This type of file does not take a new version by upload.'  # E70d (D7): the upload route's sentence, relayed
STALE_HEAD = 'The result has a newer version; review it before adding another'  # E70d (D4): the server's stale-head sentence
STAY_NEEDS = 'staying needs a folder to keep the version in'  # E173 s1 (F6): get(stay=...) keeps no content of its own


def _server_said(error):
    """The server's own message of a transport error, stripped; '' when it gave none."""
    said = getattr(error, 'server_message', None) or str(error)
    return said.strip() if isinstance(said, str) else ''


# -- the held record and its lock ------------------------------------------------------------------

def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.%s.%s' % (path.name, uuid.uuid4().hex))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out: json.dump(value, out, indent=1, sort_keys=True); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, path)  # a reader sees the old record or the new one, never half of one


def _kept(previous):
    """What a replaced item entry keeps from the one before it: its note and (E173 s0) the words it was named by and
    whether it stays. The last two only when present, so a folder used by id is written as before."""
    previous = previous or {}
    return dict({k: previous[k] for k in ('words', 'mode') if k in previous}, note=previous.get('note'))


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

def delivery_event(holder_id, asset_id, revision, holds=None, nonce=None):
    """E70b: the id of "this holder received this exact version": the same in every process, so a repeated or retried
    report is one event at the project. E171 s1 (D4): only when the entry declares whether it stays or follows
    (`holds`), the id also hashes that word and a nonce drawn once per confirmation, so a new confirmation of the same
    version with a declared mode is a new event; without `holds` the id is E70b's, byte for byte."""
    if holds is None: return 'got-' + hashlib.sha256(('%s\n%s\n%s' % (holder_id, asset_id, revision)).encode()).hexdigest()[:48]
    return 'got-' + hashlib.sha256(('%s\n%s\n%s\n%s\n%s' % (holder_id, asset_id, revision, holds, nonce)).encode()).hexdigest()[:48]


def earlier_event(holder_id, asset_id, revision, nonce):
    """E171 s1 (D6): the id of one deliberate get of an earlier version; a fresh nonce per go-back, kept for its retry."""
    return 'earlier-' + hashlib.sha256(('%s\n%s\n%s\n%s' % (holder_id, asset_id, revision, nonce)).encode()).hexdigest()[:48]


APPLICATION_WORD = re.compile(r'[a-z0-9._-]{1,128}')


def application_wire(word):
    """E171 s1: the SDK takes the bare word E122's application source uses (`qgis-plugin`, `opendtect`, `script`); the
    wire carries `application:<word>`, and `script` as itself. None sends none."""
    if word is None or word == 'script': return word
    if not isinstance(word, str) or not APPLICATION_WORD.fullmatch(word):
        raise ValueError("Name the application by its word (letters, digits, '.', '_' or '-'), such as 'qgis-plugin'.")
    return 'application:' + word


_REVISION = re.compile(r'[0-9a-f]{64}')
MADE_FOR_UNRECORDED = "This project's release does not record what a version was made for."  # publish.MADE_FOR_UNRECORDED


def _made_for(made_for):
    """E192 s2: [{asset_id, revision}] of 1 to 32 distinct exact versions, each a dict of those two keys or a pair; None
    when the list is not that (this file is vendored and imports nothing but errors, so publish.made_for_field is not used)."""
    if not isinstance(made_for, (list, tuple)): return None
    named = []
    for value in made_for:
        if isinstance(value, dict) and set(value) == {'asset_id', 'revision'}: pair = (value['asset_id'], value['revision'])
        elif isinstance(value, (list, tuple)) and len(value) == 2: pair = tuple(value)
        else: return None
        if not (isinstance(pair[0], str) and 0 < len(pair[0]) <= 160 and isinstance(pair[1], str) and _REVISION.fullmatch(pair[1])): return None
        named.append(pair)
    if not 1 <= len(named) <= 32 or len(set(named)) != len(named): return None
    return [{'asset_id': a, 'revision': r} for a, r in named]


def _takes(function, name):
    """Whether a transport's method takes the keyword `name`: a transport written before E171 s1 (four arguments to
    `publish`) is called as before, and its sends name no holder."""
    try: parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError): return False
    return any(p.name == name or p.kind is p.VAR_KEYWORD for p in parameters)


def _report_held(report, reference, holder_id, event_id, held):
    """One report with the held-copy fields; when the project refuses it as a request (an older gateway knows no such
    fields), once more in E70b's shape with the same id, so the confirmed get is still recorded there. E184 s0 (D-6):
    answers whether the accepted request carried the fields (False after that fallback)."""
    held = {k: v for k, v in held.items() if v is not None and _takes(report, k)}
    if not held:
        report(reference, holder_id, event_id)
        return True
    try:
        report(reference, holder_id, event_id, **held)
        return True
    except Exception as error:
        if failure(error) != 'invalid': raise
    report(reference, holder_id, event_id)
    return False


class Receipt:
    """A fetched version not yet applied. `confirm()` advances the record; anything else leaves it unchanged.
    The folder stays locked until confirm() or release() (or the end of a `with` block).

    E70b: once the record has advanced, the receipt is reported to the project (when the transport can report).
    `reported` is True after the project accepted it, False when the report failed (the confirmation stands; a later
    confirm of the same version sends the same event id), None when nothing was reported."""
    def __init__(self, exchange, lock, entry, content, facts, outcome='got'):
        self._exchange, self._lock, self.entry, self.content, self.facts = exchange, lock, entry, content, facts
        self.outcome = outcome  # G-7: 'stays' for the held version kept by stay=True; confirm() answers it
        self.confirmed = False
        self.reported = None
        self._words = self._mode = None  # E173 s1 (D3): set by a call by name, or with stay; confirm writes them

    def confirm(self, applied_to=None, receipt=None):
        """E184 s0: `receipt`, the transfer receipt of this get, is checked before the record advances, reported with the
        get to a project that keeps it, and returned on the outcome. The sentence adds NOT_KEPT when the project did not
        keep it, UNCONFIRMED when the report's answer is not known."""
        if self._lock is None: raise NotValid(self._exchange._say('not-valid', {'reasons': 'this version was already confirmed or released'}))
        if receipt is not None: self._exchange._check_receipt(receipt)  # the lock stays: a refused receipt changes nothing
        try:
            record = self._exchange._load()
            entry = dict(self.entry, got_at=self._exchange.clock())
            if applied_to is not None: entry['applied_to'] = str(applied_to)
            entry.update(_kept(record['items'].get(entry['asset_id'])))
            entry.update({k: v for k, v in (('words', self._words), ('mode', self._mode)) if v is not None})
            record['items'][entry['asset_id']] = entry
            self._exchange._save(record)
            self.confirmed = True
        finally: self.release()
        self.reported, kept = self._report(record.get('holder_id'), entry, receipt)
        said = '' if receipt is None else NOT_KEPT if self.reported is not False and not kept else UNCONFIRMED if self.reported is False else ''
        return Outcome(self.outcome, self._exchange._say(self.outcome, self.facts) + said, self.facts,
                       {'asset_id': entry['asset_id'], 'revision': entry['revision'], 'reported': self.reported}, receipt)

    def _report(self, holder_id, entry, receipt=None):
        """(reported, kept): `reported` as the class says; `kept` whether the accepted report carried `receipt`."""
        report = getattr(self._exchange.transport, 'report', None)
        if report is None or not holder_id: return None, False
        reference = {'project_id': self._exchange.transport.project, 'asset_id': entry['asset_id'], 'revision': str(entry['revision'])}
        holds = entry.get('mode')  # E171 s1 (D4): held/2's declaration, sent as the copy's mode
        event = delivery_event(holder_id, entry['asset_id'], entry['revision'], holds, uuid.uuid4().hex if holds is not None else None)
        carried = receipt if receipt is not None and self._exchange._keeps_receipts(receipt, report) else None
        try: whole = _report_held(report, reference, holder_id, event, {'application': self._exchange.application, 'holds': holds, 'receipt': carried})
        except Exception: return False, False  # never fails the confirmation: the version is applied and recorded
        return True, carried is not None and whole

    def release(self):
        lock, self._lock = self._lock, None
        if lock is not None: lock.__exit__(None, None, None)

    def __enter__(self): return self
    def __exit__(self, *exc): self.release()


class Exchange:
    def __init__(self, transport, work, *, sentences=None, lock_timeout=3.0, clock=time.time, application='script', codes=None):
        """E171 s1: `application` is the word of the program holding this folder's copies (`application_wire`):
        `script` for the SDK, `qgis-plugin` or `opendtect` for a connector; it is reported with each confirmed get and
        sent with each send, and the project shows it beside the copy. E184 s0: `codes`, the code document
        (`ophiolite.transfer-codes/1`, read by the caller), checks each transfer receipt a send or a get carries."""
        if sentences is not None:
            missing = [code for code in OUTCOMES if not callable(sentences.get(code))]
            if missing: raise ValueError('The sentence table has no sentence for: ' + ', '.join(missing))
        self.application = application_wire(application)
        self.transport, self.work = transport, Path(work).expanduser().absolute()
        self.sentences, self.lock_timeout, self.clock = sentences or SENTENCES, lock_timeout, clock
        self.path, self.lock_path = self.work / 'held.json', self.work / 'held.lock'
        self.codes = codes

    def _check_receipt(self, receipt):
        """E184 s0 (D-3): refuses before anything is done, with UNLISTED or SHAPE and the reason in technical."""
        problem = receipt_problem(receipt, self.codes)
        if problem is not None: raise NotValid(problem[0], {}, problem[1])

    def _keeps_receipts(self, receipt, method):
        """E184 s0 (D-6): whether this project keeps a receipt of this codes version, and `method` can carry it."""
        keeps = getattr(self.transport, 'keeps_receipts', None)
        try: return callable(keeps) and _takes(method, 'receipt') and keeps(receipt['codes']['version']) is True
        except Exception: return False  # a capabilities answer that cannot be read keeps nothing; the act goes ahead

    # record

    def _load(self):
        try: record = json.loads(self.path.read_text())
        except FileNotFoundError: return {'schema': SCHEMA, 'url': self.transport.url, 'project': self.transport.project, 'holder_id': uuid.uuid4().hex,
                                          'items': {}, 'seen': None, 'pending': None}
        except (OSError, ValueError): raise NotValid(self._say('not-valid', {'reasons': 'the record of what you hold in this folder cannot be read'})) from None
        if not isinstance(record, dict) or record.get('schema') not in (SCHEMA, SCHEMA_WORDS) or not isinstance(record.get('items'), dict):
            raise NotValid(self._say('not-valid', {'reasons': 'this folder holds a record this version cannot read'}))
        if (record.get('url'), record.get('project')) != (self.transport.url, self.transport.project):
            raise NotValid(self._say('not-valid', {'reasons': 'this folder holds items of another project; use another folder'}))
        return record

    def _save(self, record):
        if record.get('schema') == SCHEMA_WORDS or any('words' in e or 'mode' in e for e in record['items'].values() if isinstance(e, dict)):
            record['schema'] = SCHEMA_WORDS  # E173 s0 (D1): an older SDK refuses the folder rather than drop these fields
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

    # names (E173 s1)

    def _named(self, item_id, name, type):
        """D1: the words of a call by name ({name, type?}), None for a call by id. Exactly one of the two; a type only
        beside a name, and one of TYPE_WORDS."""
        if name is None and type is not None: self._raise('not-valid', {'reasons': 'a type is given only together with a name'})
        if (item_id is None) == (name is None): self._raise('not-valid', {'reasons': 'name the item by its id or by its name, one of the two'})
        if name is None: return None
        if not isinstance(name, str) or not name: self._raise('not-valid', {'reasons': 'a name is the text an item is called'})
        if type is not None: type_profiles(type)
        return dict({'name': name}, **({'type': type} if type is not None else {}))

    def _resolve(self, words, record, inventory):
        """D2: the id a call by name means. The entry this folder recorded with these words first, so a rename, or another
        item called the same since, changes nothing here (one that has gone is refused or reported as by id); else the one
        visible item called exactly this, of this type when one is named. Matching uses the raw name; display() only
        shapes the sentence. History is asked on the refusal path only."""
        held = sorted(i for i, e in record['items'].items() if isinstance(e, dict) and e.get('words') == words)
        if held: return held[0]
        name, type = words['name'], words.get('type')
        called = [i for i in inventory.values() if i.get('name') == name and (type is None or _item_type(i) == type)]
        shown = display(name, 'that name')
        if not called: self._raise('name-not-found', dict({'name': shown}, **({'type': type} if type else {})))
        if len(called) > 1:
            candidates = [{'type': _item_type(i), 'who': display(i.get('by_name'), None), 'number': len(self._history(i) or ()) or None} for i in called]
            self._raise('name-unclear', {'name': shown, 'candidates': candidates}, {'candidates': [i['asset_id'] for i in called]})
        return called[0]['asset_id']

    def _remember_entry(self, item_id, words, mode):
        """F5: an answer given without fetching still records the words the item was named by and the mode asked for;
        the caller holds the folder lock. A call by id with no stay changes nothing."""
        if words is None and mode is None: return
        record = self._load(); entry = record['items'].get(item_id)
        if entry is None: return
        entry.update({k: v for k, v in (('words', words), ('mode', mode)) if v is not None})
        self._save(record)

    # check for updates

    def check(self, *, name=None, type=None):
        """What is newer than what this folder holds, what is new and what can no longer be seen. Changes nothing
        but the list of items seen (for "new since your last check"). E173 s1 (D5, F7): with `name` (and `type`), the
        same answer for the one item that name resolves to, as get resolves it; a held item that has gone is
        access-changed, never a refusal; and the list of items seen stays as it was."""
        words = None if name is None and type is None else self._named(None, name, type)
        record, inventory = self._load(), self._inventory()
        held, listed = record['items'], inventory
        if words is not None:
            only = self._resolve(words, record, inventory)
            held, listed = {k: v for k, v in held.items() if k == only}, {k: v for k, v in inventory.items() if k == only}
        newer, lost, new = [], [], []
        for ident, entry in sorted(held.items(), key=lambda kv: (kv[1].get('name') or '', kv[0])):
            item = listed.get(ident)
            if item is None: lost.append({'asset_id': ident, 'name': self._name(entry)}); continue
            if item.get('revision') != entry.get('revision'):
                newer.append({'asset_id': ident, 'name': self._name(item), 'revision': item.get('revision'), **self._at(item, item.get('revision'))})
        seen = record.get('seen')
        baseline = seen is None and words is None  # a check by name notes nothing, so it is never the first check
        if seen is not None:
            for ident, item in sorted(listed.items(), key=lambda kv: (kv[1].get('name') or '', kv[0])):
                if ident not in seen and not any(n['asset_id'] == ident for n in newer):
                    new.append({'asset_id': ident, 'name': self._name(item)})
        facts = {'newer': newer, 'new': new, 'lost': lost, 'holding': bool(held), 'baseline': baseline, 'visible': len(listed)}
        code = 'updates' if newer or new else 'access-changed' if lost else 'nothing-new'
        if words is None: self._remember(sorted(inventory))
        return Outcome(code, self._say(code, facts), facts, {'inventory': len(listed)})

    def _remember(self, seen):
        """The ids seen, written only when no other program holds the folder (check never waits)."""
        lock = folder_lock(self.lock_path, 0)
        try: lock.__enter__()
        except Busy_: return
        try:
            record = self._load(); record['seen'] = seen; self._save(record)
        finally: lock.__exit__(None, None, None)

    # get latest

    def fetch(self, item_id=None, *, name=None, type=None, stay=None, output=None, **how):
        """Fetch the latest version of an item. Returns a Receipt to confirm once applied, or an Outcome when this
        folder already holds that version in `output`. The folder is locked until the receipt is confirmed or released.
        E173 s1: the item by its id, or by `name` (and `type`, a word of TYPE_WORDS), resolved once (`_resolve`); a
        call by name records the words, also when it answers without fetching.
        G-7 (R-M7): `stay` is get's rule for a host that applies the version itself. `stay=True` returns a receipt over
        the version this folder holds, never the head, whose content is that exact version (read again when there is no
        `output`: the host keeps its own copy); its facts are the `stays` sentence's and confirm() answers `stays` and
        records that the folder stays. The first time (nothing held) it takes the latest. `stay=False` takes the latest
        and records that the folder follows. Without `stay`, as before: the latest, whatever the folder recorded."""
        if stay is not None and not isinstance(stay, bool): self._raise('not-valid', {'reasons': 'stay is True or False'})
        return self._fetch(item_id, self._named(item_id, name, type), output, how, stay)

    def _fetch(self, item_id, words, output, how, stay=None, honour=False):
        """The one step of get and fetch. `stay` is the caller's; `honour` (the folder's recorded mode decides when
        `stay` is None) is get's only (D4), so fetch without `stay` is as it was. Staying answers `_stay`'s receipt;
        get, which persists into `output`, refuses staying without one (F6)."""
        lock = self._lock()
        try:
            record, inventory = self._load(), self._inventory()
            if words is not None: item_id = self._resolve(words, record, inventory)
            entry, item = record['items'].get(item_id), inventory.get(item_id)
            if item is None: self._raise('not-visible', {'name': self._name(entry, 'this item')}, {'asset_id': item_id})
            name, head = self._name(item), item.get('revision')
            selection = json.loads(json.dumps(how, sort_keys=True, default=list))
            output = Path(output).expanduser().absolute() if output is not None else None
            mode = None if stay is None else 'stays' if stay else 'follows'
            staying = stay if stay is not None else honour and (entry or {}).get('mode') == 'stays'
            if staying and output is None and honour: self._raise('not-valid', {'reasons': STAY_NEEDS})
            if staying and entry:
                receipt = self._stay(lock, item, entry, output, selection, how, words); lock = None
                return receipt
            out = (entry or {}).get('output') or {}
            if (output is not None and entry and entry.get('revision') == head and out.get('path') == str(output) and out.get('selection') == selection
                    and output.is_dir() and folder_digest(output) == out.get('sha256')):
                facts = {'name': name, 'folder': str(output)}
                self._remember_entry(item_id, words, mode)
                lock.__exit__(None, None, None); lock = None
                return Outcome('already-latest', self._say('already-latest', facts), facts, {'asset_id': item_id, 'revision': head})
            got, digest = self._pull(item, head, output, how)
            facts = {'name': name, **({'folder': str(output)} if output is not None else {}), **(got.get('facts') or {})}
            number = got.get('number')
            known = self._at(item, head) if item.get('kind') != 'external-scalar-map' else {}
            facts.update({k: v for k, v in known.items() if v is not None})
            if number and not facts.get('number'): facts['number'] = number
            entry = {'asset_id': item_id, 'name': item.get('name'), 'kind': item.get('kind'), 'revision': head, 'number': facts.get('number'),
                     'output': {'path': str(output), 'sha256': digest, 'selection': selection} if output is not None else None}
            receipt = Receipt(self, lock, entry, got.get('content'), facts); lock = None
            receipt._words, receipt._mode = words, mode
            return receipt
        finally:
            if lock is not None: lock.__exit__(None, None, None)

    def _pull(self, item, revision, output, how):
        """One version of `item` from the transport, written into `output` when given (the folder replaced only once the
        new one is complete). Returns the transport's answer and the written folder's digest."""
        name = self._name(item)
        if output is not None: output.parent.mkdir(parents=True, exist_ok=True)  # E91: the card's `data/<item name>` in a new folder
        staging = output.with_name('.%s.partial-%s' % (output.name, uuid.uuid4().hex[:8])) if output is not None else None
        try:
            try: got = self.transport.fetch(item, revision, staging, **how)
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
        return got, digest

    def _stay(self, lock, item, entry, output, selection, how, words):
        """D4: a folder that stays keeps the version it holds. Intact (already-latest's test, at the held version): no
        fetch, and that version is confirmed again, so the project learns the folder stays. Changed or missing: that
        exact version is fetched again, never the head. Returns the receipt over the held version (it takes the lock);
        its facts are the `stays` sentence's: the newer version, when there is one, from the inventory's head.
        G-7: without `output` the host keeps the copy (fetch only): the held version is read again and is the receipt's
        content, and the entry records no folder."""
        held, head = entry.get('revision'), item.get('revision')
        out = entry.get('output') or {}
        again, content = dict(entry, name=item.get('name')), None
        if output is None:
            got, _ = self._pull(item, held, None, how)
            again['output'], content = None, got.get('content')
        elif not (out.get('path') == str(output) and out.get('selection') == selection and output.is_dir() and folder_digest(output) == out.get('sha256')):
            got, digest = self._pull(item, held, output, how)
            again['output'], content = {'path': str(output), 'sha256': digest, 'selection': selection}, got.get('content')
        facts = {'name': self._name(item), 'number': entry.get('number'), 'newer': head != held}
        if head != held: facts['newer_number'] = self._at(item, head).get('number')
        receipt = Receipt(self, lock, again, content, facts, 'stays')
        receipt._words, receipt._mode = words, 'stays'
        return receipt

    def read_exact(self, item, revision, output):
        """E109 D6: read one exact version of `item` (an inventory entry) into `output`, a new folder, for a delivery.
        The held record is neither read nor changed and the folder is not locked: what this folder holds stays what
        `get` last took. A seismic volume is refused with `get`'s reason. Returns the transport's answer."""
        output = Path(output).expanduser().absolute()
        if output.exists() or output.is_symlink(): raise ValueError('read_exact writes into a new folder')
        name = self._name(item)
        staging = output.with_name('.%s.partial-%s' % (output.name, uuid.uuid4().hex[:8]))
        try:
            try: got = self.transport.fetch(item, revision, staging)
            except ExchangeRefused as refusal: self._raise(refusal.outcome, {**refusal.facts, 'name': name}, refusal.technical)
            except Exception as error: self._transport_error(error, refused='not-visible', invalid='could-not-reach', facts={'name': name})
            staging.mkdir(mode=0o700, exist_ok=True)
            os.replace(staging, output)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return got

    def get(self, item_id=None, *, name=None, type=None, stay=None, output=None, window=None, **how):
        """Fetch, persist into `output` (when given), then advance the record. E141 s2: `window` (the CLI form
        `inline=100:104,by=label` or a mapping of read_window's keywords) writes part of a seismic volume as SEG-Y; the
        held record's selection records it. E173 s1: the item by its id or by `name` and `type`, as `fetch`.
        `stay=True` keeps the version this folder holds (`stays`; nothing is fetched while the folder is intact) and
        records that it stays; the first time, it takes the latest. `stay=False` takes the latest and records that the
        folder follows. Without `stay`, a folder that recorded it stays, stays. Staying needs `output`."""
        if stay is not None and not isinstance(stay, bool): self._raise('not-valid', {'reasons': 'stay is True or False'})
        words = self._named(item_id, name, type)
        if stay and output is None: self._raise('not-valid', {'reasons': STAY_NEEDS})
        if window is not None: how['window'] = window
        got = self._fetch(item_id, words, output, how, stay, True)
        return got if isinstance(got, Outcome) else got.confirm(applied_to=output)  # a `stays` receipt answers `stays`

    # what a file is made for (E192 s2)

    def made_for(self, item_id=None, *, name=None, type=None):
        """E192 s2 (D2): the first answer. The exact version an item means now, by its id or by `name` (and `type`) among
        the items you can see; this folder's own names are not consulted, since what a file is made for need not be held.
        Writes nothing, here or in the project. Answers `made-for` with facts {name, number, by, at, when} of that very
        version and technical {asset_id, revision}: pass the technical pair to `send(made_for=[...])`."""
        words = self._named(item_id, name, type)
        inventory = self._inventory()
        item_id = self._resolve(words, {'items': {}}, inventory) if words is not None else item_id
        item = inventory.get(item_id)
        if item is None: self._raise('not-visible', {'name': display(item_id, 'that item')}, {'asset_id': item_id})
        shown = self._name(item)
        if item.get('kind') not in ('uploaded', 'derived'):
            self._raise('not-valid', {'reasons': '%s can be named as made for only when it is an uploaded or published version' % shown}, {'asset_id': item_id})
        revision = item.get('revision')
        try: versions = self.transport.history(item)
        except Exception as error: self._transport_error(error, refused='not-visible', invalid='could-not-reach', facts={'name': shown})
        version = next((v for v in versions or () if isinstance(v, dict) and v.get('revision') == revision), None)
        if version is None: self._raise('could-not-reach', {'name': shown}, {'asset_id': item_id, 'revision': revision})
        who = self._who(version)
        facts = {'name': shown, 'number': version.get('number'), 'by': who['who'], 'at': version.get('at'), 'when': who['when']}
        return Outcome('made-for', self._say('made-for', facts), facts, {'asset_id': item_id, 'revision': revision})

    # send to project

    def send(self, data, *, name, profile, how, based_on=(), of=None, declare=None, extra=None, expected=None, source=None,
             rights_confirmed=False, receipt=None, curve_declaration=None, made_for=None):
        """E192 s2: `made_for`, 1 to 32 exact versions ({asset_id, revision} or a pair, as `made_for()` answers in
        technical) this file was made for, none also a version it is based on; saved in the request only when given, so
        a retry sends the saved ones and a retry naming others is refused. A transport that does not say
        `takes_made_for` refuses it before anything is saved.
        E188 C1: `curve_declaration` ({'well', 'depth_kind', 'depth_datum'}, three non-blank texts; the project's model
        decides the rest) declares the curve of the next version of a held LAS upload (`of`, profile 'las2/1' only). It
        is saved in the request only when given, so every other request and its replay is as before, and a retry sends
        the saved one. A sent item keeps the survey object it was placed as (`applied_to`).
        E184 s0: `receipt`, the transfer receipt the connector computed for this send, is checked before anything
        is sent, saved with the pending send (a retry of an unfinished send carries the saved one, never a new one),
        sent only to a project that keeps it, and returned on the outcome; a project that does not keep it adds
        NOT_KEPT to the sentence.
        Publish `data` as a new item, or (with `of`, a held item) as its next version. The parent is the version
        this folder holds, never the project's head; `based_on` are held items. The complete request is saved before
        it is sent, so running the same send again after a crash never publishes twice. `expected` (with `of`) is the
        revision the caller built on: when this folder holds another one, nothing is sent (E104). It only refuses, is
        not part of the saved request, and a retry of an unfinished send never reads it. E122 s4a: `source` names the
        application object the data came from ({system: 'application:<client id>', instance, container, id, as_new}); it
        is saved in the request only when given. Without `of` or `as_new` the project decides: a new item, the next
        version of the item this object sent before, or nothing changed (the folder then holds that item).
        E70d: with `of` naming a held upload, the next version is an upload (`based_on` names only that item, and
        `rights_confirmed=True` confirms that you may share this version); a transport without that route refuses."""
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
        if source is not None and not isinstance(source, dict): reasons.append('give the source as names and values')
        if curve_declaration is not None and not (isinstance(curve_declaration, dict) and set(curve_declaration) == set(DECLARATION)
                                                  and all(isinstance(v, str) and v.strip() for v in curve_declaration.values())):
            reasons.append('declare the curve as its well, depth kind and depth datum, each as text')
        if not isinstance(rights_confirmed, bool): reasons.append('confirm that you may share this version, or leave it out')
        if made_for is not None:  # E192 s2: exact versions, checked as the client checks them (publish.made_for_field)
            made_for = _made_for(made_for)
            if made_for is None: reasons.append('name between 1 and 32 exact versions it was made for, each once (an id and a revision, as made_for answers)')
        if reasons: self._raise('not-valid', {'reasons': '; '.join(reasons)})
        if made_for is not None and getattr(self.transport, 'takes_made_for', False) is not True:
            self._raise('not-valid', {'reasons': 'this application does not send what a file was made for; send it from Python or the command line'},
                        {'argument': 'made_for'})
        if receipt is not None: self._check_receipt(receipt)
        if len(data) > MAX_SEND: self._raise('too-large', {})
        request = {'name': name, 'profile': profile, 'how': how, 'based_on': list(based_on), 'of': of, 'declare': dict(declare or {}),
                   'extra': json.loads(json.dumps(extra or {}, sort_keys=True)), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        if source is not None: request['source'] = json.loads(json.dumps(source, sort_keys=True))  # E122 s4a: only when given (R13)
        if rights_confirmed: request['rights_confirmed'] = True  # E70d (D2): only when given, so a derived request is as before
        if curve_declaration is not None: request['curve_declaration'] = {k: curve_declaration[k] for k in DECLARATION}  # E188 C1: only when given
        if made_for is not None: request['made_for'] = made_for  # E192 s2: only when given, compared whole on a retry
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
                upload = of is not None and record['items'][of].get('kind') == 'uploaded'  # E121 B7: an upload's next version is an upload
                if upload and not getattr(self.transport, 'appends_uploads', False):
                    self._raise('not-valid', {'reasons': '%s is an upload, which does not take a sent version; send this as a new item based on it'
                                              % self._name(record['items'][of])})
                if upload and list(based_on) != [of]:  # E70d (D3): the upload route records only the version it builds on
                    self._raise('not-valid', {'reasons': "an upload's next version records only the version it builds on; name only %s as based on"
                                              % self._name(record['items'][of])})
                if curve_declaration is not None and not (upload and profile == 'las2/1'):  # E188 C1: the upload route's las2/1 only
                    self._raise('not-valid', {'reasons': 'a curve declaration goes only with the next version of an uploaded LAS 2.0 file'},
                                {'argument': 'curve_declaration'})
                if upload and not rights_confirmed:  # E70d (D2): rights belong to uploads (ADR 0021)
                    self._raise('not-valid', {'reasons': 'confirm that you may share this version'}, {'argument': 'rights_confirmed'})
                if rights_confirmed and not upload:
                    self._raise('not-valid', {'reasons': 'only the next version of an upload asks you to confirm that you may share it'},
                                {'argument': 'rights_confirmed'})
                if expected is not None and of is None:
                    self._raise('not-valid', {'reasons': 'name the item this is a new version of, together with the version it builds on'})
                if expected is not None and expected != record['items'][of]['revision']:  # before same_content: identical bytes are still refused
                    self._raise('newer-version-exists', {'name': self._name(record['items'][of])})
                if of is not None and self.transport.same_content(record['items'][of], request):
                    held = record['items'][of]
                    self._raise('nothing-changed', {'name': self._name(held), 'number': held.get('number')})
                resolved = {'parents': [{'asset_id': i, 'revision': record['items'][i]['revision']} for i in based_on],
                            'expected_parent': record['items'][of]['revision'] if of is not None else None}
                if upload: resolved = {'parents': [], 'expected_parent': record['items'][of]['revision'], 'route': 'upload'}  # E70d (D1)
                if made_for is not None and {(p['asset_id'], p['revision']) for p in resolved['parents']} & {(m['asset_id'], m['revision']) for m in made_for}:
                    self._raise('not-valid', {'reasons': 'a version it is based on is not also what it was made for'}, {'argument': 'made_for'})  # E192 s0 (D3)
                pending ={'command_id': uuid.uuid4().hex, 'request': request, 'resolved': resolved, 'owner': identity, 'started': self.clock()}
                # E171 s1 (Codex D4): who holds the sent version, saved with the send and sent from here, outside `request`
                # (compared whole) and `resolved`; a send saved before the upgrade has none and is resent as it was.
                pending['attribution'] = {k: v for k, v in (('holder', record['holder_id']), ('application', self.application)) if v is not None}
                if receipt is not None: pending['receipt'] = receipt  # E184 s0 (B-D2): outside `request`, as attribution
                record['pending'] = pending; self._save(record); first = True  # saved BEFORE anything is sent
            facts = {'name': display(name, 'the item')}
            attribution = {'attribution': pending['attribution']} if pending.get('attribution') and _takes(self.transport.publish, 'attribution') else {}
            lists = pending.get('receipt')  # E184 s0: the saved receipt, also on a retry
            kept = lists is not None and self._keeps_receipts(lists, self.transport.publish)
            if kept: attribution['receipt'] = lists
            try:
                receipt = self.transport.publish(data, pending['request'], pending['resolved'], pending['command_id'], **attribution)
            except ExchangeRefused as refusal:
                if first: self._clear()
                self._raise(refusal.outcome, {**facts, **refusal.facts}, refusal.technical)
            except Exception as error:
                kind = failure(error)
                by_upload = pending['resolved'].get('route') == 'upload'
                if kind == 'stale':
                    self._clear()
                    if by_upload: self._recurrence(error, of, facts)  # E70d (D4): the server's own words name an upload's recurrence
                    self._stale(error, of, data, facts)  # stale is checked after replay: the command was not recorded
                if by_upload and kind == 'invalid' and _server_said(error) == NOT_VERSIONED:
                    if first: self._clear()
                    self._raise('not-valid', {**facts, 'reasons': 'this type of file does not take a new version by upload'}, error=error)
                if 'made_for' in pending['request'] and getattr(error, 'message', None) == MADE_FOR_UNRECORDED:  # E192 s2: the client's sentence
                    if first: self._clear()
                    self._raise('not-valid', {**facts, 'reasons': "this project's release does not record what a version was made for"}, error=error)
                if kind == 'could-not-reach': self._raise('outcome-unknown', facts, {'command_id': pending['command_id']}, error=error)
                if first and kind != 'rate-limited': self._clear()  # refused before anything was kept; a retry's earlier attempt stays unknown
                self._transport_error(error, refused='access-refused', facts=facts)
            by_upload = pending['resolved'].get('route') == 'upload'
            number = receipt.get('number')
            if by_upload and number is None:  # E70d (D5): an upload answers no number; history may (never fails the send)
                number = self._at({'asset_id': receipt['asset_id'], 'kind': 'uploaded'}, receipt['revision']).get('number')
            record = self._load()
            previous = record['items'].get(receipt['asset_id']) or {}
            placed = {'applied_to': previous['applied_to']} if 'applied_to' in previous else {}  # E188 C1 (Codex D1): in the same save
            record['items'][receipt['asset_id']] = {'asset_id': receipt['asset_id'], 'name': name, 'kind': 'uploaded' if by_upload else 'derived',
                                                    'revision': receipt['revision'],
                                                    'number': number, 'got_at': self.clock(), 'sent': True, 'output': None,
                                                    **placed, **_kept(previous)}  # a send keeps the mode
            record['pending'] = None
            self._save(record)
            change = receipt.get('source_change')  # E122 s4a: what the project decided for a send naming its source
            code = 'sent-version' if pending['request'].get('of') is not None or change == 'changed' else 'sent-new'
            facts = {**facts, 'number': number}
            if change == 'unchanged':
                self._raise('nothing-changed', facts, {'asset_id': receipt['asset_id'], 'revision': receipt['revision'], 'command_id': pending['command_id']})
            sentence = self._say(code, facts) + (NOT_KEPT if lists is not None and not kept else '')
        held = self._held_by(receipt['asset_id'])  # E171 design 6: after the folder's lock is let go; never fails the send
        if held:  # the sentence stays as it was (qualification compares it); the CLI prints `held_line` after it
            facts = {**facts, 'held_by': held[0], 'on_an_older_version': held[1], **({'held_line': held_line(*held)} if held[0] else {})}
        return Outcome(code, sentence, facts, {'asset_id': receipt['asset_id'], 'revision': receipt['revision'], 'command_id': pending['command_id']},
                       lists)

    def _held_by(self, item):
        """E171 design 6 (amended 11 November): one holders read for the item just sent, when the transport has one;
        (held by, on an older version), or None when there is no read or it failed or answered rows it cannot count."""
        holders = getattr(self.transport, 'holders', None)
        if holders is None: return None
        try:
            rows = holders(item)
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows): return None
            return len(rows), sum(1 for r in rows if r.get('state') == 'behind')
        except Exception:
            return None

    def _clear(self):
        record = self._load(); record['pending'] = None; self._save(record)

    def _recurrence(self, error, of, facts):
        """E70d (D4): an upload's recurrence is the server's call (bytes and declarations, the head first); its own
        sentence names the version. A stale head is said as for a derived item, with the head's number, author and time
        from history, never by comparing digests (the head may have these bytes under other declarations). Any other
        message falls through to `_stale`."""
        said = _server_said(error)
        same = re.fullmatch(r'Nothing changed: this is version (\d+)\.', said)
        if same: self._raise('nothing-changed', {**facts, 'number': int(same.group(1))}, error=error)
        earlier = re.fullmatch(r'This content was version (\d+) on (.+)\.', said)
        if earlier: self._raise('earlier-version', {**facts, 'number': int(earlier.group(1)), 'day': earlier.group(2)}, error=error)
        if said == STALE_HEAD:
            versions = self._history({'asset_id': of, 'kind': 'uploaded'})
            who = self._who(versions[-1]) if versions else {}
            self._raise('newer-version-exists', {**facts, **{k: v for k, v in who.items() if v is not None}}, error=error)

    def _stale(self, error, of, data, facts):
        """A stale-parent or duplicate-content refusal: history (read after it) says which."""
        record = self._load()
        held = record['items'].get(of) if of is not None else None
        versions = self._history(dict(held or {}, asset_id=of)) if held else None
        digest = hashlib.sha256(data).hexdigest()
        if versions:
            same = [v for v in versions if v.get('revision') == digest]
            head = versions[-1]
            if same and same[0] is not head:  # E108 D5: an earlier version's content is named as that version, with its day
                self._raise('earlier-version', {**facts, 'number': same[0].get('number'), 'day': _day(same[0].get('at'))}, error=error)
            if same: self._raise('nothing-changed', {**facts, 'number': same[0].get('number')}, error=error)
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

    # E171 s1: the project's record of this folder's copies

    def _holder(self):
        """This folder's holder id, or None when nothing was ever kept here (no copy to name)."""
        return self._load().get('holder_id') if self.path.exists() else None

    def holder_id(self):
        """This folder's holder id, for a host that sends by a route of its own (OpendTect's horizon upload) and names
        the folder as the core's send does. A folder that never kept anything (no `held.json`) gets one minted and the
        record saved first, under the folder's lock, so a first send names it and a retry after a crash names the same
        one. Refuses as reading the record does (`NotValid`, `FolderBusy`). `_holder()` still answers None for such a
        folder (release_copy, report_earlier)."""
        with self._locked():
            record = self._load()
            if not self.path.exists(): self._save(record)
        return record.get('holder_id')

    def release_copy(self, item):
        """E171 s1 (D7): tell the project this folder no longer holds `item` (exchange/release). `held.json` is left as
        it is, so a later confirmed get of the item brings the copy back. True when a copy was released, False when the
        project had none for this folder, None when the transport cannot release (an assistant's) or nothing was kept."""
        release, holder = getattr(self.transport, 'release', None), self._holder()
        if release is None or not holder: return None
        try: return release(holder, item) is True
        except Exception as error: self._transport_error(error, refused='access-refused', facts={'reasons': 'the project did not release the copy'})

    def report_earlier(self, item, revision):
        """E171 s1 (D6): a deliberate get of an earlier version (OpendTect "Go back"), which a plain late report never
        records: one report with `earlier`, its id fresh per go-back and kept for its own retry. `held.json` is never
        written. True, False or None as a confirmation's `reported`."""
        report, holder = getattr(self.transport, 'report', None), self._holder()
        if report is None or not holder: return None
        reference = {'project_id': self.transport.project, 'asset_id': item, 'revision': str(revision)}
        event = earlier_event(holder, item, revision, uuid.uuid4().hex)
        try: _report_held(report, reference, holder, event, {'application': self.application, 'earlier': True})
        except Exception: return False
        return True


# -- the SDK's transport (E70a C3) ------------------------------------------------------------------------
# Everything below reaches the project through ophiolite.Client; its imports stay inside the methods so the core
# above remains importable without httpx or pydantic.

class ClientTransport:
    """check, get and send over an ophiolite.Client: the inventory, result history, exact reads and derived
    publication routes that already exist. No route of its own."""
    takes_made_for = True  # E192 s2: a send's `made_for` goes with the upload or the derived publication

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
            numbers = sorted(int(r['revision']) for r in page.get('revisions', []) if str(r.get('revision', '')).isascii() and str(r.get('revision', '')).isdigit())
            return [{'number': n, 'revision': str(n), 'by': None, 'at': None} for n in numbers]
        if item.get('kind') not in ('derived', 'uploaded'): raise Refused('Only results and uploads list their versions here.')  # E108 (D6)
        page = self.client._post('applications', 'result-history', {'asset_id': item['asset_id']})
        names = (page.get('display') or {}).get('member_names') or {}
        return [{'number': r.get('number'), 'revision': r.get('revision'), 'by': names.get(r.get('by')), 'at': r.get('published_at')}
                for r in page.get('revisions', [])]

    FORMS = ('ophiolite.well-log-curve/1',)  # E183 s3: the forms a fetch passes on to Client.read (a connector's capability guard reads it)

    def fetch(self, item, revision, output, **how):
        kind, asset = item.get('kind'), item['asset_id']
        if kind == 'external-scalar-map': return self._map(asset, revision, output)
        if kind not in ('derived', 'uploaded'): raise CannotReadHere('', {'reason': 'this kind of item is not one this script can receive'})
        form = how.get('form')
        if form is not None:
            if form not in self.FORMS or not how.get('curves'): raise NotValid('', {'reasons': 'a form is read for named curves, as one of %s' % ', '.join(self.FORMS)})
            return self._form(item, revision, output, form, list(how['curves']))
        if how.get('window') is not None: return self.window(item, revision, output, how['window'])
        curves = how.get('curves')
        if curves:
            data = self.client.read(asset, revision, list(curves))
            descriptor = data.wire_descriptors[0] if getattr(data, 'wire_descriptors', None) else {}
            if output is not None: data.save(output)
            return {'content': data, 'number': self._number(kind, descriptor)}
        from .errors import Incompatible
        try: data = self.client.read_data(asset, revision)
        except (Incompatible, Refused) as error:
            if getattr(error, 'status', None) in (400, 422) or error.code in ('INVALID_ARGUMENT', 'incompatible-context'):
                raise CannotReadHere('', {'reason': 'name the curves to receive a well log'}) from None
            raise
        descriptor = data._wire_descriptor
        if data.type == 'seismic-volume':  # E141 s2 (D-S): a volume is received as a window
            sentence = 'Give a window, for example --window inline=100:104,by=label, or call Client.download_original for the whole file.'
            raise CannotReadHere(sentence, {'sentence': sentence, 'reason': sentence.rstrip('.')}, {'reason': 'volume-needs-window'})
        if output is not None:
            output.mkdir(mode=0o700)
            normalized = next((r for r in descriptor.get('representations') or [] if r.get('kind') == 'normalized'), {})
            named = 'data.ophpts' if normalized.get('profile') == 'ophiolite.point-columns/1' else 'data.json'  # E139 s3 (O2): by its codec, as typed.data_file_of (inline: the plug-in carries no typed.py)
            (output / 'original').write_bytes(data.original); (output / named).write_bytes(data._wire_data_bytes)
            (output / 'descriptor.json').write_text(json.dumps(descriptor, indent=2) + '\n')
        return {'content': data, 'number': self._number(kind, descriptor)}

    def _form(self, item, revision, output, form, curves):
        """E183 s3: curves read in `form` (Client.read(form=)). The gateway's refusal of the form (422) is CannotReadHere
        with its sentence verbatim and the refused revision, so a connector may read the stored form of that one version
        instead; every other error takes the curves read's path. Nothing is written to the held record."""
        try: data = self.client.read(item['asset_id'], revision, curves, form=form)
        except Refused as error:
            if getattr(error, 'status', None) != 422: raise
            sentence = getattr(error, 'server_message', None) or error.message
            raise CannotReadHere(sentence, {'sentence': sentence, 'reason': 'form'}, {'form': form, 'status': 422, 'revision': revision}) from None
        descriptor = data.wire_descriptors[0] if getattr(data, 'wire_descriptors', None) else {}
        if output is not None: data.save(output)
        return {'content': data, 'number': self._number(item.get('kind'), descriptor)}

    def window(self, item, revision, output, window):
        """E141 s2 (D-S, D-X, D-W): part of a seismic volume written into `output` (the staging folder) as window.sgy,
        window.json (the document, the window digest and the headers digest) and descriptor.json. Asked in order: the
        descriptor, the window document (both checked; an inexact crop refuses here), the file header (revision and
        header positions checked), then headers answers and sample pieces as the writer needs them. The original is
        never asked for; refusals are CannotReadHere with `technical.reason` (volume_windows.WINDOW_CODES)."""
        from .volume_windows import (LINE_WINDOW, NEEDS_OUTPUT, OTHER_WINDOW, SegyWindowWriter, Window, WindowRefused, as_exchange, asked, cannot,
                                     check_document, check_file_header, describe_volume, exact_crop, once_more, parse_spec, parse_window, window_path)
        from urllib.parse import urlencode
        asset, client = item['asset_id'], self.client
        try:
            query = parse_spec(window) if isinstance(window, str) else parse_window(**dict(window))
            if any(name == 'trace' for name, _ in query): raise cannot('window-volume-only', LINE_WINDOW)
            if output is None: raise cannot('window-needs-output', NEEDS_OUTPUT)
            descriptor = client._window_descriptor(asset, revision)
            kind = (descriptor.get('scientific') or {}).get('type')
            if kind != 'seismic-volume': raise cannot('window-volume-only', LINE_WINDOW if kind == 'seismic-line' else OTHER_WINDOW)
            description = describe_volume(asset, revision, descriptor)
            base = window_path(client.prefix, asset, revision)
            request = asked(query, description)  # E140 s3: windows=2 for a native cube only (R5)
            document = check_document(client._window_json(base + ('?' + urlencode(request) if request else '')), asset=asset, revision=revision,
                                      query=query, description=description)
            delay = exact_crop(document, description.context['samples'])
            file_header, answer = once_more(lambda: client._window_file_header(base, request, document))
            positions = check_file_header(document, file_header, answer)
            reading = Window(document, query, description, base)
            writer = SegyWindowWriter(output, document, file_header, positions, delay)

            def piece(n):
                path, length = reading.piece(n); answer = {}
                return client._window_get(path, length, answer), answer
            def headers(n):  # E175 s1 (R1-4): the document's partition, a `/3` answer's mask included in its bound
                return client._window_headers(base, request, document, n, writer.headers_length(n))
            written = writer.write(lambda n: once_more(lambda: headers(n)), lambda n: once_more(lambda: piece(n)))
        except WindowRefused as refused: raise as_exchange(refused) from None
        record = {'document': document, 'window_digest': written['window_digest'], 'headers_digest': written['headers_digest']}
        (output / 'window.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        (output / 'descriptor.json').write_text(json.dumps(descriptor, indent=2) + '\n')
        return {'content': record, 'number': self._number(item.get('kind'), descriptor)}

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
        return {'content': raw, 'number': int(revision) if str(revision).isascii() and str(revision).isdigit() else None, 'facts': {'map': True}}

    @staticmethod
    def _number(kind, descriptor):
        """The version number a descriptor states; an upload without `history` is its only version (E53 adds it from 2).
        E108 S3 (D8') amends E70a's adapter row 127 by name: an upload's newer version is read like any other version (it
        was refused cannot-read-here); a declaration-only one is found by its own revision (B3)."""
        number = (descriptor.get('history') or {}).get('number')
        return number if number is not None or kind != 'uploaded' else 1

    appends_uploads = True  # E70d (D1): an upload's next version goes through the upload-version route

    def keeps_receipts(self, version):
        """E184 s0 (D-6): whether the project's capabilities list this code document version (`transfer_receipts`)."""
        return self.client.transfer_codes_kept(version)

    def publish(self, data, request, resolved, command_id, attribution=None, receipt=None):
        held = {k: v for k, v in (attribution or {}).items() if k in ('holder', 'application') and v is not None}  # E171 s1
        if receipt is not None: held['receipt'] = receipt  # E184 s0: only when the project keeps it (Exchange.send asks)
        if request.get('made_for') is not None: held['made_for'] = request['made_for']  # E192 s2: the saved versions, on both routes
        if resolved.get('route') == 'upload':  # E70d: the author's own upload, at the version this folder holds
            if request.get('curve_declaration') is not None: held['curve_declaration'] = request['curve_declaration']  # E188 C1: the saved one
            got = self.client.upload_data(data, profile=request['profile'], name=request['name'], attribution=request['how'], audience=[],
                                          rights_confirmed=request.get('rights_confirmed') is True, declared=request.get('declare') or None,
                                          filename=request['name'], command_id=command_id, append_to=request['of'],
                                          expected_parent=resolved['expected_parent'], application_source=request.get('source'), **held)
            return {'asset_id': got.asset_id, 'revision': got.revision, 'number': None}
        from .writers import WrittenOriginal
        written = WrittenOriginal(data, request['profile'], dict(request.get('declare') or {}), 'derived')
        receipt = self.client.publish_derived(written, name=request['name'], from_=[(p['asset_id'], p['revision']) for p in resolved['parents']],
                                              method={'name': request['how'], 'declared': False}, command_id=command_id,
                                              new_version_of=request.get('of'), expected_parent=resolved.get('expected_parent'),
                                              **({'source': request['source']} if request.get('source') is not None else {}), **held)
        answer = {'asset_id': receipt.asset_id, 'revision': receipt.revision, 'number': receipt.revision_number}
        if receipt.source_change is not None: answer['source_change'] = receipt.source_change
        return answer

    def same_content(self, held, request):
        """E70d (D4): an upload's sameness is the server's (bytes and declarations), so it is never decided here."""
        return held.get('kind') != 'uploaded' and request['sha256'] == held.get('revision')

    def report(self, reference, holder_id, event_id, *, application=None, holds=None, earlier=None, receipt=None):
        """E70b: one delivery observation on the project route (`exchange-consumer/1`); the reference names the
        project. One attempt, a short timeout: a confirmation never waits long for it. E171 s1: the held copy's
        application word, its declared mode and `earlier`, each only when given (so E70b's body is unchanged without).
        E184 s0: the get's transfer receipt likewise."""
        from .publish import json_bytes
        body = {'reference': reference, 'binding_id': holder_id, 'event_id': event_id, 'profile': 'exchange-consumer/1', 'mode': 'get'}
        body.update({k: v for k, v in (('application', application), ('holds', holds), ('earlier', earlier), ('receipt', receipt)) if v is not None})
        return self.client._post_bytes('activity', 'report', json_bytes(body), timeout=REPORT_TIMEOUT)

    def release(self, holder_id, item):
        """E171 s1 (D7): exchange/release of this folder's copy of `item`; the project's answer `released`."""
        answer = self.client._post('exchange', 'release', {'project_id': self.project, 'binding_id': holder_id, 'item': item})
        return (answer or {}).get('released') is True

    def holders(self, item):
        """E171 design 6: the rows of exchange/holders for `item` (Client.holders, read whole), read once after a send."""
        return self.client.holders(item)['rows']
