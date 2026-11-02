"""E129 sb: `ophiolite starter export`, the derived files of one catalogue archive (strategy rev 3, D1-D9).

A pack definition whose one input is an archive (`{"archive": {"survey", "log_step", "outline_input"}}`) names an
OpendTect survey held as a zip by a catalogue record. `export` checks the definition (its own contents and subject
rules: volume kinds are allowed here only) and the archive against the catalogue evidence (Sa's `bound`), extracts the
archive under fixed bounds, runs the OpendTect connector (`ophiolite_opendtect.export`, GPL, in OpendTect's own Python:
a separate process, never imported) and reads every file it wrote back with a reader that did not write it: SEG-Y by
the bounded reader below, LAS by lasio, tracks and horizons by strict column parsers. Each file's digest of its
expected representation (D9) is recomputed from what was read and must equal the one the connector computed from
odbind's arrays before writing; the definition's volume decisions must agree with the survey. Then the outline
(OSD outline/3: one polygon per cube from its own corners, one point per well head, WGS84) is written and, last,
`derived.json`, the intermediate export report slice (c)'s `build` reads (no compatibility promise). Since E129 sc C1
horizons are points-csv/1 and the outline is named by the report's `outline` field only, never in `derived[]` (OSD E42:
it is the record outline, not a derived file).

Publication (D7): under `OUT/.lock`, each run writes a fresh `OUT/exports/<UTC stamp>-<n>/` (`files/`, `derived.json`
last) and then replaces `OUT/derived.json`, a one-line pointer `{"export": "exports/<name>"}`, with `os.replace`. A
completed folder is never changed; a run that stops leaves the previous pointer, and its folder (no `derived.json`) is
removed by the first run after 24 hours."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath

from . import starter, starter_kinds
from .errors import MissingExtra
from .starter import refuse, sha256, dumped, replaced

REPORT, EXPORT = 'ophiolite.starter-export/1', 'ophiolite.opendtect-export/1'
FOLDER = {k.key: k.folder for k in starter_kinds.CATALOGUE}  # E137 s0 D-01: KINDS, the kinds this SDK reads back, follows READERS
VOLUME_KINDS, VOLUME_TOPICS = ('seismic-3d', 'horizons', 'seismic-2d'), ('crs', 'domain', 'units', 'nulls')  # E137 s1 D-3: a line's decisions are a volume's
FAULT_TOPICS, FAULT_UNIT = ('crs', 'domain', 'units'), 's'  # E137 s2 D-5: a fault's coordinate z is in seconds (M-1a), whatever the survey's zunit
NULLS = {'seismic-3d': 'non-finite refused', 'horizons': 'undefined omitted', 'seismic-2d': 'non-finite refused'}
INPUT, ARCHIVE, OUTLINE_INPUT = ('name', 'file', 'sha256', 'bytes', 'held', 'archive'), ('survey', 'log_step', 'outline_input'), ('name', 'url', 'sha256')
MEMBERS, UNCOMPRESSED = 200_000, 8 << 30  # D7 extraction bounds
STALE, TIMEOUT = 24 * 3600, 7200
ENV = 'OPHIOLITE_OPENDTECT_PYTHON'
KEBAB, SHA = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*'), re.compile(r'[0-9a-f]{64}')
CENTS = re.compile(r'-?\d+\.\d{2}')
NOTHING = starter.NOTHING_SENT  # Sa's form and evidence checks end so; one ending for every refusal of the command
SOURCE = 'ophiolite starter export: odbind cube corners and well heads, pyproj to EPSG:4326'
LINE_SOURCE = 'ophiolite starter export: every trace position of the 2D line as its SEG-Y holds it (x and y to 0.01 m), pyproj to EPSG:4326'  # E137 s1 D-3
HOW = {'seismic-3d': 'odbind Seismic3D.getdata of cube %s, written as SEG-Y rev 1 IEEE format 5 by ophiolite_opendtect.export',
       'horizons': 'odbind Horizon3D.get_z and get_xy of horizon %s, written as points-csv/1 x,y,z,inline,crossline, every node, z empty where it holds no value',
       'wellbore-paths': 'odbind Well.track of well %s, written as md,x,y,tvdss, unchanged',
       'wellbore-logs': 'odbind Well.logs of well %s resampled on the log step by linear interpolation, written as LAS 2.0',
       'seismic-2d': 'odbind Seismic2D.getdata of line %s, written as SEG-Y rev 1 IEEE format 5 by ophiolite_opendtect.export, x and y to 0.01 m',
       'faults': 'odbind FaultStickSet or Fault3D getstick of fault %s, written as OpendTect FaultStickSet ASCII by ophiolite_opendtect.export, z in seconds, unchanged'}
HORIZON_HEADER = 'x,y,z,inline,crossline'  # E129 sc C1: horizons are points-csv/1 (OSD E42); the outline is the record outline, never derived
INTEGER = re.compile(r'-?\d+')


# --- the definition and its evidence (D1) ---------------------------------------------------------------------------

def definition(path, *, readers=None, export_profile=None, agreements=None):
    """The export definition at PATH: Sa's common form, exactly one input (the archive), contents of the four export
    kinds, decisions whose subjects are contents objects or the archive (topic units only: the log step). E137 s0
    (R2-3): READERS, EXPORT_PROFILE and AGREEMENTS default to the module tables; a test passes its own."""
    defn, bad = starter.form(path)
    inputs = defn['inputs']
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict) or 'archive' not in inputs[0]:
        bad('must name exactly one input, the archive, for an export')
    i = inputs[0]
    if set(i) != set(INPUT): bad('has an archive input not of the form {%s}' % ', '.join(INPUT))
    if not isinstance(i['name'], str) or i['name'] != starter.object_name(i['name']): bad('input names must be path-safe file names (%r)' % i['name'])
    if not isinstance(i['sha256'], str) or not SHA.fullmatch(i['sha256']) or type(i['bytes']) is not int or i['bytes'] < 0: bad('input %s needs its sha256 and bytes' % i['name'])
    if not isinstance(i['file'], str) or not i['file'] or Path(i['file']).is_absolute() or '..' in Path(i['file']).parts: bad('input %s: file must be a path inside the definition folder' % i['name'])
    held = i['held']
    if not (isinstance(held, dict) and (held.get('as') == 'verified' and set(held) == {'as', 'verifier_run', 'path'} and isinstance(held['path'], str) and held['path']
                                        and isinstance(held['verifier_run'], dict) and set(held['verifier_run']) == {'checked_at', 'tool_version'})
            or isinstance(held, dict) and held.get('as') == 'deposited' and set(held) == {'as', 'key'} and isinstance(held['key'], str)):
        bad('input %s: held must be verified {verifier_run, path} or deposited {key}' % i['name'])
    a = i['archive']
    if not isinstance(a, dict) or set(a) - {'time_depth'} != set(ARCHIVE): bad('archive must be {%s[, time_depth]}' % ', '.join(ARCHIVE))  # E137 s3 D-1
    if not isinstance(a['survey'], str) or not a['survey'] or a['survey'] != starter.object_name(a['survey']): bad('archive survey must be a folder name')
    step = a['log_step']
    if type(step) not in (int, float) or not math.isfinite(step) or not 0 < step <= 10: bad('archive log_step must be a number of metres in (0, 10]')
    o = a['outline_input']
    if not isinstance(o, dict) or set(o) != set(OUTLINE_INPUT) or not isinstance(o['name'], str) or not KEBAB.fullmatch(o['name']) \
            or not isinstance(o['url'], str) or not re.match(r'^https?://', o['url']) or not isinstance(o['sha256'], str) or not SHA.fullmatch(o['sha256']):
        bad('archive outline_input must be {name (a record input name), url, sha256}')
    contents, seen = [], set()
    if not isinstance(defn['contents'], list) or not defn['contents']: bad('names no contents')
    for c in defn['contents']:
        if not isinstance(c, dict) or set(c) != {'kind', 'ids'} or not isinstance(c['kind'], str) or c['kind'] in seen or not isinstance(c['ids'], list) or not c['ids'] \
                or len(set(c['ids'])) != len(c['ids']) or not all(isinstance(x, str) and x and x != 'pack' for x in c['ids']):
            bad('contents must be [{kind (%s), ids}], each kind once, with distinct ids' % ', '.join(KINDS))
        if not starter_kinds.known(c['kind']): bad('contents ' + starter_kinds.NOT_A_KIND % c['kind'])
        if starter_kinds.BY_KEY[c['kind']].identity == 'dataset/line':  # E137 s0 D-04: before the writer check, before extraction
            try: starter_kinds.line_paths(c['ids'])
            except ValueError as e: refuse(str(e) + NOTHING)
        if not writable(c['kind'], readers, export_profile): refuse(starter_kinds.cannot_hold(c['kind']) + NOTHING)  # E137 s0 D-02, D-03: before extraction
        seen.add(c['kind']); contents.append({'kind': c['kind'], 'ids': list(c['ids']), 'count': len(c['ids'])})
    if not isinstance(defn['decisions'], list) or not defn['decisions']: bad('names no decisions')
    for d in defn['decisions']:
        if not isinstance(d, dict) or not {'topic', 'subject', 'value', 'source'} <= set(d) or set(d) - {'topic', 'subject', 'value', 'source', 'note'} \
                or d['topic'] not in starter.TOPICS or d['source'] not in starter.SOURCES or not all(isinstance(d[k], str) and d[k] for k in d) \
                or len(d['value']) > 300 or len(d.get('note', '')) > 500 or (d['source'] == 'chosen') and 'note' not in d:
            bad('has a decision not of the form {topic, subject, value, source[, note]} (a chosen value needs its note)')
    defn = {**defn, 'contents': contents, 'folder': Path(path).resolve().parent}
    values = decided(defn, agreements)
    unit = next((d for d in defn['decisions'] if (d['topic'], d['subject']) == ('units', i['name'])), None)
    try: same = unit is not None and float(unit['value']) == float(step)
    except ValueError: same = False
    if not same or unit['source'] != 'chosen': refuse('Decision units for %s must be the log step, %r m, chosen with its note.' % (i['name'], step) + NOTHING)
    defn['values'] = values
    return defn


def decided(defn, agreements=None):
    """Rule (e) for an export: {(topic, subject): value}, each pair once, each subject a contents object or the
    archive (topic units only); the volume topics for every cube and horizon, the well topics for every well."""
    archive = defn['inputs'][0]['name']
    subjects = {x for c in defn['contents'] for x in c['ids']}
    values = {}
    for d in defn['decisions']:
        if d['subject'] == archive and d['topic'] != 'units': refuse('Decision %s names the archive %s; only units (the log step) may.' % (d['topic'], archive) + NOTHING)
        if d['subject'] not in subjects | {archive}: refuse('Decision %s names %s, which is not an object of contents.' % (d['topic'], d['subject']) + NOTHING)
        if (d['topic'], d['subject']) in values: refuse('Decision %s for %s has two values.' % (d['topic'], d['subject']) + NOTHING)
        values[(d['topic'], d['subject'])] = d['value']
    for c in defn['contents']:
        for oid in c['ids']:
            topics = agreements[c['kind']][0] if agreements and c['kind'] in agreements else VOLUME_TOPICS if c['kind'] in VOLUME_KINDS \
                else FAULT_TOPICS if c['kind'] == 'faults' else TD_TOPICS if c['kind'] == 'time-depth' else starter.WELL_TOPICS
            for topic in topics:
                if (topic, oid) not in values: refuse('Decision %s for %s (%s) is missing.' % (topic, oid, c['kind']) + NOTHING)
    return values


def outline_sums(archive):
    """OSD outlines `input_sha256` of the archive fetched as one part: the sha256 of its one SHA256SUMS line."""
    return sha256(('%s  %s\n' % (archive['sha256'], archive['name'])).encode())


def evidence(defn, catalogue, verification, custody, read=None):
    """Sa's rule (b) for the archive (`starter.bound`), then the outline input bound to the record: one of its inputs
    by name and url, and the digest of the archive fetched as that input. Returns (evidence, licence); READ, a dict,
    receives {path read: sha256} of every evidence file read (E129 sc: build binds them)."""
    ev, files = starter.bound(defn, catalogue, verification, custody)
    if read is not None: read.update(files)
    archive = defn['inputs'][0]
    o = archive['archive']['outline_input']
    rec = next((r for r in ev['record'].get('inputs') or [] if isinstance(r, dict) and r.get('name') == o['name']), None)
    if rec is None: refuse('outline_input %s is not an input of record %s.' % (o['name'], defn['record_id']) + NOTHING)
    if rec.get('url') != o['url']: refuse('outline_input url %s is not the url record %s states for %s.' % (o['url'], defn['record_id'], o['name']) + NOTHING)
    if o['sha256'] != outline_sums(archive): refuse('outline_input sha256 is not the archive fetched as input %s.' % o['name'] + NOTHING)
    return ev, starter.computed_licence(starter.licences(defn, ev), NOTHING)


def digest_of(path):
    h, n = hashlib.sha256(), 0
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''): h.update(block); n += len(block)
    return h.hexdigest(), n


def checked_file(defn):
    """The archive's local file, its size and digest checked in blocks (an archive may be large)."""
    i = defn['inputs'][0]
    p = defn['folder'] / i['file']
    try: found = digest_of(p)
    except OSError: found = None
    if found != (i['sha256'], i['bytes']): refuse('%s is not the file the definition names: its SHA-256 differs.' % i['name'] + NOTHING)
    return p


# --- extraction (D7) ------------------------------------------------------------------------------------------------

def members(path):
    """E137 s3 (M4): {member key: is a folder} of the zip at PATH, keyed as `extracted` keys them."""
    try:
        with zipfile.ZipFile(path) as z: return {'/'.join(PurePosixPath(i.filename).parts): i.is_dir() for i in z.infolist()}
    except (OSError, zipfile.BadZipFile): refuse('The archive is not a zip file.' + NOTHING)


def extracted(path, dest, survey):
    """Every member of the zip at PATH under DEST, refusing absolute or escaping paths, links and special files,
    duplicates, more than MEMBERS members or UNCOMPRESSED bytes, and an archive without the survey folder."""
    try: z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile): refuse('The archive is not a zip file.' + NOTHING)
    with z:
        infos = z.infolist()
        if len(infos) > MEMBERS: refuse('The archive has %d members; at most %d are read.' % (len(infos), MEMBERS) + NOTHING)
        if sum(i.file_size for i in infos) > UNCOMPRESSED: refuse('The archive holds more than %d bytes uncompressed.' % UNCOMPRESSED + NOTHING)
        names = {}
        for i in infos:
            n = i.filename
            p = PurePosixPath(n)
            if not n or n.startswith('/') or '\\' in n or re.match(r'^[A-Za-z]:', n) or '..' in p.parts or '\x00' in n:
                refuse('The archive member %s is not a relative path inside the archive.' % n + NOTHING)
            if (i.external_attr >> 16) & 0o170000 not in (0, 0o100000, 0o040000): refuse('The archive member %s is a link or a special file.' % n + NOTHING)
            key = '/'.join(p.parts)
            if key in names: refuse('The archive member %s appears twice.' % key + NOTHING)
            names[key] = i
        if not any(k.split('/')[0] == survey and (len(k.split('/')) > 1 or names[k].is_dir()) for k in names):
            refuse('The archive holds no survey folder %s.' % survey + NOTHING)
        for key, i in names.items():
            target = dest.joinpath(*key.split('/'))
            if i.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with z.open(i) as src, open(target, 'wb') as out:
                for block in iter(lambda: src.read(1 << 20), b''):
                    written += len(block)
                    if written > i.file_size: refuse('The archive member %s is larger than the archive states.' % key + NOTHING)
                    out.write(block)
    return dest


# --- time-depth models (E137 s3) ------------------------------------------------------------------------------------
# A model is the archive's own checkshot table, named by the definition (D-1) and written as time-depth-csv/1 with its
# cells' text unchanged (D-4); its numbers are read as the profile reads them (float, finite, strictly increasing).

TD_FIELDS, TD_DELIMITERS = ('member', 'header_line', 'delimiter', 'depth', 'time'), {'tab': '\t', 'comma': ','}
TD_MAX_PAIRS, TD_BYTES, TD_HOW = 100_000, 16 << 20, 300  # R2-1: well under the gateway's 32 MiB whole-read bound
TD_DOMAIN = re.compile(r'(one-way|two-way) time in (s|ms|us)')
TD_DEPTH_KINDS = {'MD': 'md', 'TVD': 'tvd', 'TVDSS': 'tvdss'}
TD_HEADER = 'depth,time'
TD_TOPICS = starter.WELL_TOPICS + ('domain',)  # D-2: a model's well's decisions, and its time kind and unit
TD_UNEXPECTED = "The archive's time_depth is given, but contents lists no time-depth model."
TD_NOT_NAMED = "The time-depth model of %s is not named in the archive's time_depth; name its file and columns."
TD_EXTRA = "The archive's time_depth names %s, which contents does not list as a time-depth model."
TD_FORM = ("The archive's time_depth entry for %s must be {member, header_line (a line number from 1), delimiter (tab or "
           "comma), depth, time}.")
TD_MEMBER_PATH = 'The time-depth file %r for %s is not a relative path inside the archive.'
TD_MEMBER_DIR = 'The time-depth file %r for %s is a folder of the archive, not a file.'
TD_MEMBER_MISSING = 'The archive holds no file %r for the time-depth model of %s.'
TD_LONG = 'The description of the time-depth model of %s would be longer than 300 characters; name a shorter file or columns.'
TD_NO_PATH = "The time-depth model of %s needs the well's path in the pack: list %s under wellbore-paths too."
TD_DOMAIN_BAD = 'Decision domain for %s must be one-way or two-way time in s, ms or us (for example "one-way time in s"), not %r.'
TD_DEPTH_KIND = 'Decision depth-kind for %s must be MD, TVD or TVDSS for its time-depth model, not %r.'
TD_ONE_NAME = 'The time-depth models of %s and %s would be written to one file name.'
TD_NOT_TEXT = 'The time-depth file %r for %s is not UTF-8 text.'
TD_NO_HEADER = 'The time-depth file for %s has no line %d to read as its header.'
TD_COLUMN = 'The header of the time-depth file for %s does not name the column %r exactly once.'
TD_ROW = 'The time-depth model of %s: %s No repair was applied.'  # the profile's sentence, with the well's name
TD_TOO_LARGE = 'The time-depth model of %s would be larger than 16 MiB written; a starter pack cannot hold it.'
HOW_TD = 'the archive file %s, columns %s (depth) and %s (time) from header line %d, written as time-depth-csv/1 depth,time, the text unchanged'


def time_depth_checked(archive, contents, values, names):
    """D-1, D-2, D-3 (M4): {well: spec} of the archive's `time_depth` key for the contents' time-depth models, each
    member a file of NAMES ({member key: is a folder}, as `extracted` keys them), each well also under wellbore-paths,
    its domain and depth-kind decisions of the forms a model needs. A spec holds the member, the header line, the
    delimiter, both column names, the pack path, `how` and the declarations. Refused by name, before extraction."""
    ids = next((c['ids'] for c in contents if c['kind'] == 'time-depth'), [])
    given = archive.get('time_depth')
    if not ids:
        if given is not None: refuse(TD_UNEXPECTED + NOTHING)
        return {}
    if not isinstance(given, dict): refuse(TD_NOT_NAMED % ids[0] + NOTHING)
    for well in given:
        if well not in ids: refuse(TD_EXTRA % well + NOTHING)
    paths = next((c['ids'] for c in contents if c['kind'] == 'wellbore-paths'), [])
    specs, stems = {}, {}
    for well in ids:
        if well not in given: refuse(TD_NOT_NAMED % well + NOTHING)
        s = given[well]
        if not isinstance(s, dict) or set(s) != set(TD_FIELDS) or type(s['header_line']) is not int or s['header_line'] < 1 \
                or s['delimiter'] not in TD_DELIMITERS or not all(isinstance(s[k], str) and s[k] for k in ('member', 'depth', 'time')):
            refuse(TD_FORM % well + NOTHING)
        member = s['member']
        p = PurePosixPath(member)
        if member.startswith('/') or '\\' in member or re.match(r'^[A-Za-z]:', member) or '..' in p.parts or '\x00' in member:
            refuse(TD_MEMBER_PATH % (member, well) + NOTHING)
        key = '/'.join(p.parts)
        if names.get(key) is True or member.endswith('/'): refuse(TD_MEMBER_DIR % (member, well) + NOTHING)
        if key not in names: refuse(TD_MEMBER_MISSING % (member, well) + NOTHING)
        if well not in paths: refuse(TD_NO_PATH % (well, well) + NOTHING)
        domain = values.get(('domain', well))
        m = TD_DOMAIN.fullmatch(domain) if isinstance(domain, str) else None
        if m is None: refuse(TD_DOMAIN_BAD % (well, domain) + NOTHING)
        kind = values.get(('depth-kind', well))
        if not isinstance(kind, str) or kind.upper() not in TD_DEPTH_KINDS: refuse(TD_DEPTH_KIND % (well, kind) + NOTHING)
        how = HOW_TD % (key, s['depth'], s['time'], s['header_line'])
        if len(how) > TD_HOW: refuse(TD_LONG % well + NOTHING)
        stem = starter_kinds.stem(well)
        if stem.lower() in stems: refuse(TD_ONE_NAME % (stems[stem.lower()], well) + NOTHING)
        stems[stem.lower()] = well
        specs[well] = {'member': key, 'header_line': s['header_line'], 'delimiter': TD_DELIMITERS[s['delimiter']],
                       'depth': s['depth'], 'time': s['time'], 'path': '%s/%s-time-depth.csv' % (FOLDER['time-depth'], stem), 'how': how,
                       'declared': time_depth_declared(values, well)}
    return specs


def time_depth_declared(values, well):
    """D-3: what WELL's model is declared to be, from its decisions only (checked by `time_depth_checked`)."""
    m = TD_DOMAIN.fullmatch(values[('domain', well)])
    return {'depth_type': TD_DEPTH_KINDS[values[('depth-kind', well)].upper()], 'depth_unit': values[('units', well)],
            'time_kind': m.group(1), 'time_unit': m.group(2), 'datum': values[('vertical-datum', well)]}


def _td_number(cell, what, row, well):
    """A cell as time-depth-csv/1 reads it (F1): float, finite; refused with the profile's sentence."""
    try: value = float(cell)
    except ValueError: refuse(TD_ROW % (well, '%s on data row %d is not a number.' % (what, row)) + NOTHING)
    if not math.isfinite(value): refuse(TD_ROW % (well, '%s on data row %d is not finite.' % (what, row)) + NOTHING)
    return value


def time_depth_rows(text, spec, well):
    """D-4: [(depth text, time text)] of a table's data rows after its header line, stripped, in file order; every row
    of the header's cell count, both cells finite numbers strictly increasing, at least two pairs, at most 100,000."""
    lines = text.split('\n')
    if len(lines) < spec['header_line']: refuse(TD_NO_HEADER % (well, spec['header_line']) + NOTHING)
    split = lambda line: [c.strip() for c in line.rstrip('\r').split(spec['delimiter'])]
    header = split(lines[spec['header_line'] - 1])
    for column in (spec['depth'], spec['time']):
        if header.count(column) != 1: refuse(TD_COLUMN % (well, column) + NOTHING)
    at_depth, at_time = header.index(spec['depth']), header.index(spec['time'])
    rows, last = [], None
    for line in lines[spec['header_line']:]:
        cells = split(line)
        if all(not c for c in cells): continue
        n = len(rows) + 1
        if n > TD_MAX_PAIRS: refuse(TD_ROW % (well, 'The table has more than 100,000 pairs.') + NOTHING)
        if len(cells) != len(header): refuse(TD_ROW % (well, 'Data row %d has %d cells; the header has %d.' % (n, len(cells), len(header))) + NOTHING)
        d, t = cells[at_depth], cells[at_time]
        if not d: refuse(TD_ROW % (well, 'Depth on data row %d is missing; every pair needs a depth.' % n) + NOTHING)
        if not t: refuse(TD_ROW % (well, 'Time on data row %d is missing; every pair needs a time.' % n) + NOTHING)
        pair = (_td_number(d, 'Depth', n, well), _td_number(t, 'Time', n, well))
        if last and pair[0] <= last[0]: refuse(TD_ROW % (well, 'Depth on data row %d does not increase; pairs must be in strictly increasing depth.' % n) + NOTHING)
        if last and pair[1] <= last[1]: refuse(TD_ROW % (well, 'Time on data row %d does not increase; pairs must be in strictly increasing time.' % n) + NOTHING)
        rows.append((d, t)); last = pair
    if len(rows) < 2: refuse(TD_ROW % (well, 'A time-depth table needs at least two pairs.') + NOTHING)
    return rows


def time_depth_digest(rows):
    """M5: SHA-256 over the UTF-8 bytes of the written data rows, `<depth>,<time>\\n` each, the header excluded."""
    return hashlib.sha256(''.join('%s,%s\n' % r for r in rows).encode('utf-8')).hexdigest()


def converted(work, stage, specs):
    """D-4: every model of SPECS read from its member under WORK and written to STAGE at its path, after every model
    has passed (a refusal writes nothing); [{path, kind, object, axes: {pairs}, digest}] in contents order."""
    out = []
    for well, spec in specs.items():
        try: text = work.joinpath(*spec['member'].split('/')).read_bytes().decode('utf-8')
        except UnicodeDecodeError: refuse(TD_NOT_TEXT % (spec['member'], well) + NOTHING)
        rows = time_depth_rows(text.removeprefix('﻿'), spec, well)
        raw = (TD_HEADER + '\n' + ''.join('%s,%s\n' % r for r in rows)).encode('utf-8')
        if len(raw) > TD_BYTES: refuse(TD_TOO_LARGE % well + NOTHING)
        out.append((spec['path'], raw, {'path': spec['path'], 'kind': 'time-depth', 'object': well, 'axes': {'pairs': len(rows)},
                                        'digest': time_depth_digest(rows)}))
    for path, raw, _ in out:
        (stage / path).parent.mkdir(parents=True, exist_ok=True)
        (stage / path).write_bytes(raw)
    return [entry for _, _, entry in out]


# --- the connector (a separate process) -----------------------------------------------------------------------------

def exported(python, root, survey, stage, objects, step, timeout):
    """Run the OpendTect connector's exporter; its export.json, of its form."""
    argv = [python, '-m', 'ophiolite_opendtect.export', str(root), survey, str(stage), '--objects', json.dumps(objects), '--log-step', repr(float(step))]
    try: done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except OSError: refuse('The OpendTect connector interpreter %s cannot be started.' % python + NOTHING)
    except subprocess.TimeoutExpired: refuse('The export did not finish within %d seconds.' % timeout + NOTHING)
    if done.returncode:
        refuse('The export stopped: %s.' % ((done.stderr.strip().splitlines() or ['(no message)'])[-1]).rstrip('.') + NOTHING)
    try: doc = json.loads((Path(stage) / 'export.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): doc = None
    files = doc.get('files') if isinstance(doc, dict) else None
    keys = {'format', 'survey', 'cubes', 'wells', 'files', 'not_read'}  # E137 s1 D-3: and `lines` when the export wrote 2D lines
    if not isinstance(doc, dict) or doc.get('format') != EXPORT or set(doc) not in (keys, keys | {'lines'}) or not isinstance(doc.get('lines', {}), dict) \
            or not isinstance(files, list) or not all(isinstance(f, dict) and {'path', 'kind', 'object', 'axes', 'digest'} <= set(f) and starter_kinds.known(f['kind']) for f in files) \
            or not isinstance(doc['survey'], dict) or not isinstance(doc['cubes'], dict) or not isinstance(doc['wells'], dict) or not isinstance(doc['not_read'], list):
        refuse('The export wrote no export.json of its form (%s).' % EXPORT + NOTHING)
    return doc


# --- read back (D2, D9) ---------------------------------------------------------------------------------------------

def head(kind, name, axes):
    """D9: the digest's header line, canonical JSON of kind, object and axes."""
    return json.dumps({'axes': axes, 'kind': kind, 'object': name}, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def mask(defined):
    """D9: a null mask as a bit array, most significant bit first."""
    out = bytearray((len(defined) + 7) // 8)
    for n, d in enumerate(defined):
        if d: out[n // 8] |= 0x80 >> (n % 8)
    return bytes(out)


def steps(rng):
    return list(range(rng[0], rng[1] + 1, rng[2]))


def axis(values):
    """[first, last, step] of evenly spaced, increasing line numbers, or None."""
    gaps = {b - a for a, b in zip(values, values[1:])}
    if not values or len(gaps) > 1 or any(g <= 0 for g in gaps): return None
    return [values[0], values[-1], gaps.pop() if gaps else 1]


def ranges(rng):
    return isinstance(rng, list) and len(rng) == 3 and all(type(v) is int for v in rng) and rng[2] > 0 and rng[0] <= rng[1]


def differs(f, what):
    refuse('%s does not hold what export.json states: %s.' % (f['path'], what) + NOTHING)


def scanned(path, name, each):
    """D3's SEG-Y, read here and only in this form: rev 1, format 5, big-endian, fixed trace length, no extended
    headers, scalar -100, one delay and interval on every trace, inline-major traces on a full grid of finite samples.
    EACH(inline, crossline, x, y, samples) is called per trace in file order (x and y in hundredths, the samples as the
    file's big-endian bytes). Returns the axes read; NAME is the file's path in the refusal."""
    def bad(what): refuse('%s is not the SEG-Y the export writes: %s.' % (name, what) + NOTHING)
    traces, delay = [], None
    with open(path, 'rb') as stream:
        stream.read(3200)
        binary = stream.read(400)
        if len(binary) != 400: bad('too short')
        interval, count, code = struct.unpack('>H', binary[16:18])[0], struct.unpack('>H', binary[20:22])[0], struct.unpack('>h', binary[24:26])[0]
        revision, fixed, extended = struct.unpack('>H', binary[300:302])[0], struct.unpack('>h', binary[302:304])[0], struct.unpack('>h', binary[304:306])[0]
        if (code, revision, fixed, extended) != (5, 0x0100, 1, 0) or not count or not interval: bad('format %d, revision %#x, fixed-length flag %d' % (code, revision, fixed))
        length = 240 + 4 * count
        size = os.fstat(stream.fileno()).st_size - 3600
        if size <= 0 or size % length: bad('the traces are not of one fixed length')
        for _ in range(size // length):
            t = stream.read(length)
            x, y, i, c = struct.unpack('>iiii', t[180:196])
            scalar, own_delay = struct.unpack('>h', t[70:72])[0], struct.unpack('>h', t[108:110])[0]
            if scalar != -100: bad('coordinate scalar %d' % scalar)
            if struct.unpack('>HH', t[114:118]) != (count, interval): bad('a trace states other sampling')
            delay = own_delay if delay is None else delay
            if own_delay != delay: bad('the traces start at different times')
            if not all(math.isfinite(v) for v in struct.unpack('>%df' % count, t[240:])): bad('a sample is not finite')
            traces.append((i, c))
            each(i, c, x, y, t[240:])
    inlines, crosslines = sorted({i for i, _ in traces}), sorted({c for _, c in traces})
    ia, ca = axis(inlines), axis(crosslines)
    if ia is None or ca is None or traces != [(i, c) for i in inlines for c in crosslines]: bad('the traces are not a full inline-major grid')
    return {'inline': ia, 'crossline': ca, 'z': [delay, interval, count]}


def read_cube(path, f):
    """D3's SEG-Y (`scanned`): its axes and D9 digest (the stream is hashed after the header export.json states; the
    axes read must then equal those)."""
    digest = hashlib.sha256(head(f['kind'], f['object'], f['axes']))
    axes = scanned(path, f['path'], lambda i, c, x, y, samples: digest.update(struct.pack('>iiqq', i, c, x, y) + samples))
    return axes, digest.hexdigest()


def cube_inline(path, name, pick):
    """E129 (e) D1: the trace headers and one inline of D3's SEG-Y at PATH, read with the same checks (`scanned`).
    PICK(axes) names the inline once the axes are known. Returns (axes, headers, inline, samples): headers
    [(inline, crossline, x, y)] of every trace with x and y in coordinate units (the scalar -100 applied), samples
    [[float32 values as floats] per crossline of that inline, in crossline order]. The file is read twice (headers, then
    the inline), so only one inline is ever held."""
    headers, line = [], []
    axes = scanned(path, name, lambda i, c, x, y, samples: headers.append((i, c, x / 100, y / 100)))
    inline = pick(axes)
    count = axes['z'][2]
    again = scanned(path, name, lambda i, c, x, y, samples: line.append(list(struct.unpack('>%df' % count, samples))) if i == inline else None)
    if again != axes: refuse('%s changed while it was read.' % name + NOTHING)
    return axes, headers, inline, line


def read_horizon(path, f):
    """points-csv/1 `x,y,z,inline,crossline` (E129 sc C1): the header, then every node of the grid once in inline-major
    order, x and y to 0.01, z a float32 value or empty where the horizon holds none."""
    axes = f['axes']
    if not (isinstance(axes, dict) and set(axes) == {'inline', 'crossline'} and ranges(axes['inline']) and ranges(axes['crossline'])): differs(f, 'its axes are not ranges')
    grid = [(i, c) for i in steps(axes['inline']) for c in steps(axes['crossline'])]
    lines = Path(path).read_text(encoding='ascii').splitlines()
    if not lines or lines[0] != HORIZON_HEADER: refuse('%s does not start %s.' % (f['path'], HORIZON_HEADER) + NOTHING)
    if len(lines) - 1 != len(grid): refuse('%s has %d rows; its grid has %d nodes.' % (f['path'], len(lines) - 1, len(grid)) + NOTHING)
    defined, body = [], bytearray()
    for line, node in zip(lines[1:], grid):
        parts = line.split(',')
        try:
            if len(parts) != 5 or not CENTS.fullmatch(parts[0]) or not CENTS.fullmatch(parts[1]) or not INTEGER.fullmatch(parts[3]) or not INTEGER.fullmatch(parts[4]): raise ValueError
            x, y, i, c = int(Decimal(parts[0]) * 100), int(Decimal(parts[1]) * 100), int(parts[3]), int(parts[4])
            z = None if parts[2] == '' else float(parts[2])
            if (i, c) != node or z is not None and (not math.isfinite(z) or struct.unpack('>f', struct.pack('>f', z))[0] != z): raise ValueError
        except (ValueError, OverflowError, struct.error): refuse('%s has a row not of the form x,y,z,inline,crossline on the grid, in order: %r.' % (f['path'], line) + NOTHING)
        defined.append(z is not None)
        if z is not None: body += struct.pack('>iiqqf', i, c, x, y, z)
    return axes, hashlib.sha256(head(f['kind'], f['object'], axes) + mask(defined) + bytes(body)).hexdigest()


def read_positions(path, f):
    """`md,x,y,tvdss`, finite numbers, measured depth increasing."""
    lines = Path(path).read_text(encoding='ascii').splitlines()
    if not lines or lines[0] != 'md,x,y,tvdss': refuse('%s does not start md,x,y,tvdss.' % f['path'] + NOTHING)
    body, md = b'', -math.inf
    for line in lines[1:]:
        try:
            row = [float(v) for v in line.split(',')]
            if len(row) != 4 or not all(math.isfinite(v) for v in row) or row[0] <= md: raise ValueError
        except ValueError: refuse('%s has a row not of the form md,x,y,tvdss with increasing md: %r.' % (f['path'], line) + NOTHING)
        md = row[0]; body += struct.pack('>dddd', *row)
    axes = {'count': len(lines) - 1}
    return axes, hashlib.sha256(head(f['kind'], f['object'], axes) + body).hexdigest()


def read_las(path, f):
    """LAS 2.0 by lasio: DEPT in metres on one step, NULL -999.25, its curves as written."""
    try: import lasio
    except ImportError: raise MissingExtra(starter.EXTRA) from None
    try: las = lasio.read(str(path), mnemonic_case='preserve')  # lasio upper-cases mnemonics by default
    except Exception: refuse('%s could not be read as LAS.' % f['path'] + NOTHING)
    def well(key):
        try: return las.well[key].value
        except (KeyError, IndexError): return None
    try: step, null = float(well('STEP')), float(well('NULL'))
    except (TypeError, ValueError): step = null = None
    if las.curves[0].mnemonic != 'DEPT' or (las.curves[0].unit or '').lower() != 'm' or null != -999.25 or step is None:
        refuse('%s is not the LAS the export writes: DEPT in m, NULL -999.25 and a STEP.' % f['path'] + NOTHING)
    md = [float(v) for v in las.index]
    if not md or any(not math.isclose(b - a, step, rel_tol=1e-6) for a, b in zip(md, md[1:])): refuse('%s is not on one depth step of %r.' % (f['path'], step) + NOTHING)
    axes = {'md': [md[0], md[-1], len(md)], 'step': step, 'curves': [[c.mnemonic, c.unit] for c in las.curves[1:]]}
    digest = hashlib.sha256(head(f['kind'], f['object'], axes) + b''.join(struct.pack('>d', v) for v in md))
    for c in las.curves[1:]:
        values = [float(v) for v in c.data]
        digest.update(mask([math.isfinite(v) for v in values]) + b''.join(struct.pack('>d', v) for v in values if math.isfinite(v)))
    return axes, digest.hexdigest()


LINE_MARKER = 'C 6 OPHIOLITE 2D SEISMIC LINE'  # E137 s1 D-3: card C6 of the exporter's 2D line (the Connectors' detect.LINE_MARKER)
SP_SCALARS = (1, -10, -100, -1000, -10000)  # D-2: the scalars the exporter writes for a present source point


def line_scanned(path, f, each):
    """E137 s1 D-3: D-2's SEG-Y 2D line, read here and only in this form: card C6 the marker, C7 and C8 the dataset and
    line of F's object, rev 1, format 5, big-endian, fixed trace length, no extended headers, at most 200,000 traces of
    at most 20,000 samples, scalar -100, one delay and interval on every trace, inline byte 189 zero and crossline byte
    193 the trace number (byte 21), the source point's scalar one the exporter writes ((0, 0) for none), every sample
    finite and below OpendTect's undefined value. EACH(trace number, source point value, its scalar, x, y, samples) is
    called per trace in file order (x and y in hundredths, the samples as the file's big-endian bytes). Returns the
    axes read."""
    name = f['path']
    def bad(what): refuse('%s is not the SEG-Y line the export writes: %s.' % (name, what) + NOTHING)
    dataset, _, line = str(f['object']).partition('/')
    traces, delay, numbers = 0, None, set()
    with open(path, 'rb') as stream:
        text = stream.read(3200)
        try: cards = [text[80 * n:80 * (n + 1)].decode('ascii').rstrip() for n in range(40)]
        except UnicodeDecodeError: bad('its textual header is not ASCII')
        if cards[5] != LINE_MARKER: bad('card C6 is not the 2D line marker')
        if (cards[6], cards[7]) != ('C 7 DATASET %s' % dataset, 'C 8 LINE %s' % line): bad('cards C7 and C8 do not name %s' % f['object'])
        binary = stream.read(400)
        if len(binary) != 400: bad('too short')
        interval, count, code = struct.unpack('>H', binary[16:18])[0], struct.unpack('>H', binary[20:22])[0], struct.unpack('>h', binary[24:26])[0]
        revision, fixed, extended = struct.unpack('>H', binary[300:302])[0], struct.unpack('>h', binary[302:304])[0], struct.unpack('>h', binary[304:306])[0]
        if (code, revision, fixed, extended) != (5, 0x0100, 1, 0) or not 0 < count <= 20_000 or not interval: bad('format %d, revision %#x, fixed-length flag %d' % (code, revision, fixed))
        length = 240 + 4 * count
        size = os.fstat(stream.fileno()).st_size - 3600
        if size <= 0 or size % length or size // length > 200_000: bad('the traces are not 1 to 200,000 of one fixed length')
        for n in range(size // length):
            t = stream.read(length)
            ordinal, number = struct.unpack('>i', t[0:4])[0], struct.unpack('>i', t[20:24])[0]
            x, y, inline, crossline, sp = struct.unpack('>iiiii', t[180:200])
            scalar, sp_scalar, own_delay = struct.unpack('>h', t[70:72])[0], struct.unpack('>h', t[200:202])[0], struct.unpack('>h', t[108:110])[0]
            if scalar != -100: bad('coordinate scalar %d' % scalar)
            if (ordinal, inline, crossline) != (n + 1, 0, number): bad('trace %d does not carry its ordinal, inline 0 and its trace number as crossline' % (n + 1))
            if number in numbers: bad('trace number %d appears twice' % number)
            if sp_scalar not in SP_SCALARS and (sp, sp_scalar) != (0, 0): bad('trace %d has source point scalar %d' % (n + 1, sp_scalar))
            if struct.unpack('>HH', t[114:118]) != (count, interval): bad('a trace states other sampling')
            delay = own_delay if delay is None else delay
            if own_delay != delay: bad('the traces start at different times')
            if not all(math.isfinite(v) and abs(v) < 1e29 for v in struct.unpack('>%df' % count, t[240:])): bad('a sample is not finite')
            numbers.add(number); traces += 1
            each(number, sp, sp_scalar, x, y, t[240:])
    return {'traces': traces, 'z': [delay, interval, count]}


def read_line(path, f):
    """E137 s1 D-3: D-2's 2D line (`line_scanned`): its axes and D-2's digest, recomputed from what was read."""
    digest = hashlib.sha256(head(f['kind'], f['object'], f['axes']))
    axes = line_scanned(path, f, lambda number, sp, scalar, x, y, samples: digest.update(struct.pack('>iihqq', number, sp, scalar, x, y) + samples))
    return axes, digest.hexdigest()


def line_positions(path, f):
    """[(trace number, source point or None, x, y)] of the 2D line at PATH in file order, x and y in coordinate units
    (the scalar -100 applied), the source point as SEG-Y's scalar rule reads it."""
    out = []
    line_scanned(path, f, lambda number, sp, scalar, x, y, samples: out.append(
        (number, None if (sp, scalar) == (0, 0) else sp / -scalar if scalar < 0 else float(sp * scalar), x / 100, y / 100)))
    return out


def read_faults(path, f):
    """E137 s2 D-4: the fault file as the export writes it, read by `ophiolite.faults.read` (the Connectors' rule): its
    sticks numbered 0..n-1 in order and its bytes the canonical spelling (A-1: `faults.BANNER`, then `faults.write` of
    what was read); axes
    {sticks, points} and D-4's digest, recomputed from what was read."""
    from . import faults
    from .errors import ValidationFailed
    try: text = Path(path).read_bytes().decode('ascii')
    except UnicodeDecodeError: refuse('%s is not an ASCII fault-stick file.' % f['path'] + NOTHING)
    try: sticks = faults.read(text)
    except ValidationFailed as error: refuse('%s: %s' % (f['path'], ' '.join(error.violations)) + NOTHING)
    if [s['index'] for s in sticks] != list(range(len(sticks))): refuse('%s numbers its sticks other than 0 to %d in order.' % (f['path'], len(sticks) - 1) + NOTHING)
    if faults.BANNER + faults.write(sticks) != text: refuse('%s is not in the form the export writes (its first line, then x y z stick-index, each number in its shortest exact spelling).' % f['path'] + NOTHING)
    digest = hashlib.sha256(head(f['kind'], f['object'], {'sticks': len(sticks)}))
    for s in sticks: digest.update(struct.pack('>I', len(s['points'])) + b''.join(struct.pack('>ddd', p['x'], p['y'], p['z']) for p in s['points']))
    return {'sticks': len(sticks), 'points': sum(len(s['points']) for s in sticks)}, digest.hexdigest()


def read_time_depth(path, f):
    """E137 s3 D-6: the model file as the SDK writes it: `depth,time`, then finite pairs strictly increasing in both,
    LF endings; axes {pairs} and the digest of its data rows (`time_depth_digest`), recomputed from what was read."""
    try: lines = Path(path).read_bytes().decode('utf-8').split('\n')
    except UnicodeDecodeError: lines = []
    if not lines or lines[0] != TD_HEADER or lines[-1] != '': refuse('%s does not start depth,time or does not end with a line end.' % f['path'] + NOTHING)
    rows, last = [], None
    for line in lines[1:-1]:
        cells = line.split(',')
        try:
            pair = tuple(float(c) for c in cells)
            if len(cells) != 2 or any(c != c.strip() or not c for c in cells) or not all(math.isfinite(v) for v in pair) \
                    or last and (pair[0] <= last[0] or pair[1] <= last[1]): raise ValueError
        except ValueError: refuse('%s has a row not of the form depth,time increasing in both: %r.' % (f['path'], line) + NOTHING)
        rows.append(tuple(cells)); last = pair
    if len(rows) < 2: refuse('%s holds fewer than two pairs.' % f['path'] + NOTHING)
    return {'pairs': len(rows)}, time_depth_digest(rows)


READERS = {'seismic-3d': read_cube, 'horizons': read_horizon, 'wellbore-paths': read_positions, 'wellbore-logs': read_las,
           'seismic-2d': read_line, 'faults': read_faults, 'time-depth': read_time_depth}  # E137 s1 C3, s2 C3, s3 C2
KINDS = tuple(READERS)  # E137 s0 D-01: a catalogue kind without a reader here is refused by name (starter_kinds.cannot_hold)


def writable(kind, readers=None, export_profile=None):
    """E137 s0 D-01 (R1-6): this SDK writes a pack file of KIND only when it can read it back and land it."""
    return kind in (READERS if readers is None else readers) and kind in (starter.EXPORT_PROFILE if export_profile is None else export_profile)


def read_back(stage, doc, defn, *, readers=None, export_profile=None):
    """Every file export.json lists, and only those, read again: its axes and D9 digest equal to export.json's; every
    object of contents has its file or a `not_read` reason; each cube's ranges agree with its SEG-Y axes."""
    stage = Path(stage)
    for f in doc['files']:  # E137 s0 R1-11: a file of a kind this SDK cannot read back is refused by name, before any read
        if not writable(f['kind'], readers, export_profile): refuse(starter_kinds.cannot_hold(f['kind']) + NOTHING)
    readers = READERS if readers is None else readers
    paths = [f['path'] for f in doc['files']]
    present = sorted(str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file() and p.name != 'export.json')
    if len(set(paths)) != len(paths) or sorted(paths) != present: refuse('The export wrote files that export.json does not list, or lists files it did not write.' + NOTHING)
    listed = {(c['kind'], x) for c in defn['contents'] for x in c['ids']}
    covered = {(f['kind'], f['object']) for f in doc['files']} | {(n.get('kind'), n.get('name')) for n in doc['not_read'] if isinstance(n, dict)}
    for kind, name in sorted(listed - covered): refuse('The export says nothing of %s %s.' % (kind, name) + NOTHING)
    for kind, name in sorted({(f['kind'], f['object']) for f in doc['files']} - listed): refuse('The export wrote %s %s, which contents does not list.' % (kind, name) + NOTHING)
    for f in doc['files']:
        p = PurePosixPath(f['path']) if isinstance(f['path'], str) else None
        if p is None or p.is_absolute() or '..' in p.parts or len(p.parts) != starter_kinds.depth(f['kind']) or p.parts[0] != FOLDER[f['kind']]:
            refuse('The export wrote %r, not a file of its own folders.' % (f['path'],) + NOTHING)
        axes, digest = readers[f['kind']](stage / f['path'], f)
        if axes != f['axes']: differs(f, 'its axes are %s, not %s' % (json.dumps(axes), json.dumps(f['axes'])))
        if digest != f['digest']: differs(f, 'its values differ from those odbind gave (digest of the expected representation)')
        if f['kind'] == 'seismic-3d':
            c = doc['cubes'].get(f['object']) or {}
            z = c.get('z') or [None, None, None]
            if [c.get('inline'), c.get('crossline')] != [axes['inline'], axes['crossline']] or z[0] != axes['z'][0] or z[2] is None \
                    or round(z[2] * 1000) != axes['z'][1] or not math.isclose(z[0] + (axes['z'][2] - 1) * z[2], z[1], abs_tol=1e-6) \
                    or [k[:2] for k in c.get('corners') or []] != [[axes['inline'][0], axes['crossline'][0]], [axes['inline'][0], axes['crossline'][1]],
                                                                  [axes['inline'][1], axes['crossline'][1]], [axes['inline'][1], axes['crossline'][0]]]:
                differs(f, 'the cube ranges or corners in export.json are not its own')
        if f['kind'] == 'seismic-2d' and readers[f['kind']] is read_line:  # E137 s1 D-3: the line's report, its ends and Z, against its file (a test's stub reader reads no line)
            r = (doc.get('lines') or {}).get(f['object']) or {}
            at = line_positions(stage / f['path'], f)
            end = lambda n: [at[n][0], at[n][2], at[n][3]]  # noqa: E731
            z = r.get('z') or [None, None, None]
            dataset, _, line = f['object'].partition('/')
            if (r.get('dataset'), r.get('line'), r.get('traces'), r.get('first'), r.get('last')) != (dataset, line, len(at), end(0), end(-1)) \
                    or z[0] != axes['z'][0] or z[2] is None or round(z[2] * 1000) != axes['z'][1] \
                    or not math.isclose(z[0] + (axes['z'][2] - 1) * z[2], z[1], abs_tol=1e-6) or type(r.get('of')) is not int or r['of'] < 1:
                differs(f, 'the line report in export.json is not its own')


def agreed(defn, doc, agreements=None):
    """D8: each cube's and horizon's crs, domain, units and nulls as the survey and the export say; each well's crs
    the survey's and its units metres. E137 s0 (R2-3): AGREEMENTS, {kind: (topics, survey -> {topic: value})}, is a
    test's stub-kind path; no kind of the module has one."""
    values, s = defn['values'], doc['survey']
    domain = {'twt': 'time', 'depth': 'depth'}.get(s.get('zdomain'))
    for c in defn['contents']:
        for oid in c['ids']:
            if agreements and c['kind'] in agreements:
                want = agreements[c['kind']][1](s)
            elif c['kind'] == 'faults':  # E137 s2 D-5: time, seconds, the survey's CRS
                want = {'crs': s.get('crs'), 'domain': 'time', 'units': FAULT_UNIT}
            elif c['kind'] in VOLUME_KINDS:
                if c['kind'] == 'seismic-2d' and (domain, s.get('zunit')) != ('time', 'ms'):  # E137 s1 R1-1: lines in time (ms) only
                    refuse(starter.LINE_DOMAIN % (s.get('zdomain'), s.get('zunit')) + NOTHING)
                want = {'crs': s.get('crs'), 'domain': domain, 'units': s.get('zunit'), 'nulls': NULLS[c['kind']]}
            else:
                want = {'crs': s.get('crs'), 'units': 'm'}
            for topic, value in want.items():
                if values[(topic, oid)].lower() != str(value).lower():
                    refuse('Decision %s for %s is %s; the survey says %s.' % (topic, oid, values[(topic, oid)], value) + NOTHING)
            if c['kind'] in VOLUME_KINDS and domain == 'depth' and ('velocity', oid) not in values: refuse('Decision velocity for %s (depth) is missing.' % oid + NOTHING)


# --- outline (D6) ---------------------------------------------------------------------------------------------------

def outline(defn, doc, licence, stage=None):
    """OSD outline/3: per cube one survey-3d polygon through its four corners in perimeter order, closed; per well
    one wellbore point at its head; WGS84 longitude first, 9 decimals. E137 s1 D-3: per 2D line one survey-2d
    LineString through every trace position its file in STAGE holds, in file order (a Point for a one-trace line,
    R2-10)."""
    try: from pyproj import Transformer
    except ImportError: raise MissingExtra(starter.EXTRA) from None
    crs = doc['survey'].get('crs')
    try: t = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    except Exception: refuse('The survey\'s CRS %s is not one this computer can transform.' % crs + NOTHING)
    def at(x, y):
        lon, lat = t.transform(x, y)
        if not (math.isfinite(lon) and math.isfinite(lat)): refuse('A position of the survey does not transform to WGS84.' + NOTHING)
        return [round(lon, 9) + 0.0, round(lat, 9) + 0.0]
    o, rid = defn['inputs'][0]['archive']['outline_input'], defn['record_id']
    def feature(kind, name, geometry, source=SOURCE):
        return {'type': 'Feature', 'geometry': geometry, 'properties': {'record_id': rid, 'kind': kind, 'name': name, 'approximate': False, 'source': source,
                                                                       'feature_id': '%s#%s/%s' % (rid, kind, name), 'input': o['name']}}
    features = []
    for name in sorted(doc['cubes']):
        ring = [at(x, y) for _, _, x, y in doc['cubes'][name]['corners']]
        features.append(feature('survey-3d', name, {'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}))
    for name in sorted(doc['wells']):
        features.append(feature('wellbore', name, {'type': 'Point', 'coordinates': at(doc['wells'][name]['x'], doc['wells'][name]['y'])}))
    for f in sorted((f for f in doc['files'] if f['kind'] == 'seismic-2d'), key=lambda f: f['object']):
        path = [at(x, y) for _, _, x, y in line_positions(Path(stage) / f['path'], f)]
        geometry = {'type': 'Point', 'coordinates': path[0]} if len(path) == 1 else {'type': 'LineString', 'coordinates': path}
        features.append(feature('survey-2d', f['object'], geometry, LINE_SOURCE))
    return {'type': 'FeatureCollection', 'licence': licence.get('spdx') or licence['name'], 'inputs': {o['name']: {'url': o['url'], 'sha256': o['sha256']}},
            'features': features}


# --- publication (D7) -----------------------------------------------------------------------------------------------

@contextmanager
def locked(out):
    with open(out / '.lock', 'a+') as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: refuse('Another export holds %s; wait for it to finish.' % (out / '.lock') + NOTHING)
        yield


def cleaned(out, now):
    """Remove only export folders that never published (no derived.json) and were last changed over 24 hours ago."""
    for p in sorted((out / 'exports').iterdir()) if (out / 'exports').is_dir() else []:
        if p.is_dir() and not (p / 'derived.json').exists() and now - p.stat().st_mtime > STALE: shutil.rmtree(p)


def fresh(out, now):
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (out / 'exports').mkdir(parents=True, exist_ok=True)
    n = 1
    while (out / 'exports' / ('%s-%d' % (stamp, n))).exists(): n += 1
    folder = out / 'exports' / ('%s-%d' % (stamp, n))
    folder.mkdir()
    return folder


def export(definition_path, out, *, catalogue, verification, custody, python=None, timeout=TIMEOUT, now=time.time,
           readers=None, export_profile=None, how=None, agreements=None):
    """`ophiolite starter export`: the derived files of the definition's archive in a fresh OUT/exports/<name>/,
    published by OUT/derived.json. Returns (report, folder). E137 s0 (R2-3): READERS, EXPORT_PROFILE, HOW and
    AGREEMENTS are the module tables unless a test passes its own."""
    defn = definition(definition_path, readers=readers, export_profile=export_profile, agreements=agreements)
    _, licence = evidence(defn, catalogue, verification, custody)
    path = checked_file(defn)
    python = python or os.environ.get(ENV)
    if not python: refuse('Name the OpendTect connector\'s Python: --opendtect-python PY or %s.' % ENV + NOTHING)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    archive = defn['inputs'][0]
    with locked(out):
        cleaned(out, now())
        folder = fresh(out, now())
        work, stage = folder / 'work', folder / 'files'
        try:
            work.mkdir(); stage.mkdir()
            specs = time_depth_checked(archive['archive'], defn['contents'], defn['values'], members(path))  # E137 s3 D-1: before extraction
            extracted(path, work, archive['archive']['survey'])
            objects = {c['kind']: c['ids'] for c in defn['contents']}
            doc = exported(python, work, archive['archive']['survey'], stage, objects, archive['archive']['log_step'], timeout)
            doc['files'] += converted(work, stage, specs)  # D-4: inside work/, before it is removed
        finally:
            shutil.rmtree(work, ignore_errors=True)
        read_back(stage, doc, defn, readers=readers, export_profile=export_profile)
        agreed(defn, doc, agreements)
        replaced(stage / 'outline.geojson', dumped(outline(defn, doc, licence, stage)))
        derived = []  # E129 sc C1: the outline stays in the folder and the report's `outline` field, never a derived file (OSD E42)
        for f in doc['files']:
            digest, size = digest_of(stage / f['path'])
            told = specs[f['object']]['how'] if f['kind'] == 'time-depth' else (HOW if how is None else how)[f['kind']] % f['object']
            derived.append({'path': f['path'], 'sha256': digest, 'bytes': size, 'from': archive['sha256'], 'how': told})
        report = {'format': REPORT, 'record_id': defn['record_id'], 'definition': sha256(Path(definition_path).read_bytes()),
                  'archive': {'name': archive['name'], 'sha256': archive['sha256']}, 'survey': doc['survey'], 'derived': derived,
                  'files': [{'path': f['path'], 'kind': f['kind'], 'object': f['object'], **({'of': doc['lines'][f['object']]['of']} if f['kind'] == 'seismic-2d' else {})}
                            for f in doc['files']],  # E137 s1 D-3: a line's `of` (D84's M)
                  'outline': 'outline.geojson', 'not_read': doc['not_read'], 'tools': starter.tools()}
        replaced(folder / 'derived.json', dumped(report))
        replaced(out / 'derived.json', dumped({'export': 'exports/' + folder.name}))
    return report, folder
