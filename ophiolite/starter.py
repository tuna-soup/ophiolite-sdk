"""E129 Sa: starter packs (Open Subsurface Data `osd.starter/1`), written from a pack definition.

A pack definition (`ophiolite.starter-definition/1`, JSON) names one catalogue record's held files, the objects they
hold and one decision per topic per object. Everything that can be refused before a byte is sent is checked here,
offline: the definition's form, the decisions (OSD's closed topic list and its required pairs), the LAS head checks a
decision asks for, each input's evidence (the record's latest verification, or a held deposit custody document) and the
pack licence computed from that evidence. The rules mirror OSD's `src/osd/starters.py` (rules b, d and e) and
`src/osd/custody.py`; nothing of OSD is imported. lasio is imported only when a LAS head is read (the `starter` extra).

`build` lands the inputs through the upload (E85) at exact revisions, journaled in `landing.json` so that a rerun in the
same folder continues and never sends a file again to learn what became of it, and writes `starter.json` (unpublished,
no keys), its fidelity document and the python target's artefacts under `files/`. `finalise` (offline) takes each
artefact's key from its held `derived` custody document and checks the pack again."""
import hashlib
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from .errors import IntegrityConflict, MissingExtra, OphioliteError, PermissionRefused, Refused
from . import starter_kinds

DEFINITION = 'ophiolite.starter-definition/1'
STARTER, EVIDENCE, LANDING = 'osd.starter/1', 'ophiolite.starter-evidence/1', 'ophiolite.starter-landing/1'
WELL_KINDS = ('wellbore-headers', 'wellbore-logs', 'wellbore-paths', 'tops')  # starters.py WELL_KINDS
WELL_TOPICS = ('crs', 'vertical-datum', 'depth-reference', 'depth-kind', 'units', 'nulls', 'names')  # starters.py WELL_TOPICS
TOPICS = WELL_TOPICS[:4] + ('units', 'nulls', 'domain', 'velocity', 'names')  # the schema's nine
SOURCES = ('publisher', 'data', 'chosen')
APPLIED = {'units': 'depth_unit', 'depth-reference': 'depth_datum'}  # D2: the declarations a topic fills
LICENCE_FIELDS = ('name', 'spdx', 'url', 'redistribution', 'attribution', 'share_alike', 'statement', 'terms')
AGREE = ('name', 'spdx', 'url', 'statement', 'terms')  # equal across inputs, or unsupported
ABSENT = '(absent)'
PROFILE_KIND = {'las2/1': 'wellbore-logs', 'well-tops-csv/1': 'tops', 'deviation-csv/1': 'wellbore-paths'}
SHA256, COMMIT = re.compile(r'[0-9a-f]{64}'), re.compile(r'[0-9a-f]{40}')
PART = r'[a-z0-9]+(-[a-z0-9]+)*'
RECORD, PACK = re.compile('%s/%s' % (PART, PART)), re.compile('%s/%s/%s' % (PART, PART, PART))
TOP = ('format', 'id', 'record_id', 'title', 'summary', 'built_at', 'recipe', 'inputs', 'contents', 'decisions', 'targets')
INPUT = ('name', 'file', 'sha256', 'bytes', 'held', 'well', 'declare')
NOTHING_SENT = ' Nothing was sent.'
EXTRA = "Install the starter extra: pip install 'ophiolite[starter]'."
ARCHIVE_NEEDS_EXPORT = 'The pack definition has an archive input: run ophiolite starter export on it, then build with --export OUT.'
ARCHIVE_TARGETS = (['opendtect'], ['opendtect', 'python'], ['opendtect', 'resinsight'], ['opendtect', 'python', 'resinsight'])  # E129 (d) D3, literally


def refuse(sentence):
    raise Refused(sentence)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def object_name(path):
    """custody.object_name: the listing path's last segment, path-safe."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', path.rstrip('/').rsplit('/', 1)[-1]).lstrip('.') or '_'


def object_key(record_id, digest, path):
    """custody.object_key, used only to check a document's own key; a pack's key is always read from its document."""
    return 'mirror/%s/%s/%s' % (record_id, digest, object_name(path))


def definition(path):
    """The pack definition at PATH, its form checked, with `count` computed and each input's local file resolved."""
    defn, bad = form(path)
    if isinstance(defn['inputs'], list) and any(isinstance(i, dict) and 'archive' in i for i in defn['inputs']):
        refuse(ARCHIVE_NEEDS_EXPORT + NOTHING_SENT)
    return inputs_and_contents(defn, bad, Path(path))


def form(path):
    """E129 sb: the checks every pack definition passes before its inputs (format, fields, id, texts, recipe, targets):
    (definition, bad), where bad(what) refuses in the definition's words."""
    path = Path(path)
    try: defn = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): refuse('%s is not a pack definition (JSON).' % path.name + NOTHING_SENT)
    def bad(what): refuse('The pack definition %s.' % what + NOTHING_SENT)
    if not isinstance(defn, dict) or defn.get('format') != DEFINITION: bad('is not %s' % DEFINITION)
    unknown = sorted(set(defn) - set(TOP))
    if unknown: bad('has fields it does not take: %s' % ', '.join(unknown))
    missing = [k for k in TOP if k not in defn]
    if missing: bad('lacks %s' % ', '.join(missing))
    if not isinstance(defn['id'], str) or not PACK.fullmatch(defn['id']) or not isinstance(defn['record_id'], str) \
            or not RECORD.fullmatch(defn['record_id']) or not defn['id'].startswith(defn['record_id'] + '/'):
        bad('id must be <record id>/<pack> of its record_id')
    for k, most in (('title', 200), ('summary', 1000)):
        if not isinstance(defn[k], str) or not 0 < len(defn[k]) <= most: bad('%s must be text of 1 to %d characters' % (k, most))
    recipe = defn['recipe']
    if not isinstance(recipe, dict) or set(recipe) != {'id', 'repository', 'commit'} or not isinstance(recipe['id'], str) or not recipe['id'] \
            or not isinstance(recipe['repository'], str) or not re.match(r'^https://[^/?#@]+/', recipe['repository']) \
            or not isinstance(recipe['commit'], str) or not COMMIT.fullmatch(recipe['commit']):
        bad('recipe must be {id, repository (https), commit (40 hex)}')
    archive = isinstance(defn['inputs'], list) and any(isinstance(i, dict) and 'archive' in i for i in defn['inputs'])
    if archive and defn['targets'] not in ARCHIVE_TARGETS:  # E129 sc D6; (e) D4: the pack notebook as well; (d) D3: ResInsight appended
        bad('targets must be ["opendtect"], ["opendtect", "python"], ["opendtect", "resinsight"] or ["opendtect", "python", "resinsight"] for an archive in this version')
    if not archive and defn['targets'] != ['python']: bad('targets must be ["python"] in this version')
    return defn, bad


def inputs_and_contents(defn, bad, path):
    if not isinstance(defn['inputs'], list) or not defn['inputs']: bad('names no inputs')
    names = set()
    for i in defn['inputs']:
        if not isinstance(i, dict) or set(i) - set(INPUT) or not {'name', 'file', 'sha256', 'bytes', 'held', 'well'} <= set(i): bad('has an input not of the form {%s}' % ', '.join(INPUT))
        if not isinstance(i['name'], str) or i['name'] != object_name(i['name']) or i['name'] in names: bad('input names must be distinct, path-safe file names (%r)' % i['name'])
        names.add(i['name'])
        if not isinstance(i['sha256'], str) or not SHA256.fullmatch(i['sha256']) or not isinstance(i['bytes'], int) or isinstance(i['bytes'], bool) or i['bytes'] < 0:
            bad('input %s needs its sha256 and bytes' % i['name'])
        if not isinstance(i['file'], str) or not i['file'] or Path(i['file']).is_absolute() or '..' in Path(i['file']).parts: bad('input %s: file must be a path inside the definition folder' % i['name'])
        if not isinstance(i['well'], str) or not i['well']: bad('input %s names no well' % i['name'])
        if not isinstance(i.get('declare', {}), dict) or not all(isinstance(v, str) for v in i.get('declare', {}).values()): bad('input %s: declare must be {field: text}' % i['name'])
        held = i['held']
        if not (isinstance(held, dict) and (held.get('as') == 'verified' and set(held) == {'as', 'verifier_run', 'path'} and isinstance(held['path'], str) and held['path']
                                            and isinstance(held['verifier_run'], dict) and set(held['verifier_run']) == {'checked_at', 'tool_version'})
                or isinstance(held, dict) and held.get('as') == 'deposited' and set(held) == {'as', 'key'} and isinstance(held['key'], str)):
            bad('input %s: held must be verified {verifier_run, path} or deposited {key}' % i['name'])
    contents, ids = [], set()
    if not isinstance(defn['contents'], list) or not defn['contents']: bad('names no contents')
    for c in defn['contents']:
        if not isinstance(c, dict) or set(c) != {'kind', 'ids'} or c['kind'] not in PROFILE_KIND.values() or not isinstance(c['ids'], list) or not c['ids'] \
                or len(set(c['ids'])) != len(c['ids']) or not all(isinstance(x, str) and x and x != 'pack' for x in c['ids']):
            bad('contents must be [{kind (%s), ids}] with distinct ids' % ', '.join(sorted(set(PROFILE_KIND.values()))))
        contents.append({'kind': c['kind'], 'ids': list(c['ids']), 'count': len(c['ids'])}); ids.update(c['ids'])
    if not isinstance(defn['decisions'], list) or not defn['decisions']: bad('names no decisions')
    for d in defn['decisions']:
        if not isinstance(d, dict) or not {'topic', 'subject', 'value', 'source'} <= set(d) or set(d) - {'topic', 'subject', 'value', 'source', 'note'} \
                or d['topic'] not in TOPICS or d['source'] not in SOURCES or not all(isinstance(d[k], str) and d[k] for k in d) \
                or len(d['value']) > 300 or len(d.get('note', '')) > 500 or (d['source'] == 'chosen') and 'note' not in d:
            bad('has a decision not of the form {topic, subject, value, source[, note]} (a chosen value needs its note)')
    for i in defn['inputs']:
        if i['well'] not in ids: bad('input %s names well %s, which contents does not' % (i['name'], i['well']))
    return {**defn, 'contents': contents, 'folder': path.resolve().parent}


def local(defn):
    """{input name: bytes} of each input's local file, each hashing to the digest and size the definition names."""
    out = {}
    for i in defn['inputs']:
        try: raw = (defn['folder'] / i['file']).read_bytes()
        except OSError: raw = None
        if raw is None or (sha256(raw), len(raw)) != (i['sha256'], i['bytes']):
            refuse('%s is not the file the definition names: its SHA-256 differs.' % i['name'] + NOTHING_SENT)
        out[i['name']] = raw
    return out


def profile(name, raw):
    """The reader profile of one input: a LAS file, a well-tops CSV or a deviation CSV (the registry's detections)."""
    text = raw[:4096].decode('utf-8', 'replace').lstrip('﻿')
    if text.lstrip().startswith('~'): return 'las2/1'
    header = [h.strip().lower() for h in (text.splitlines() or [''])[0].split(',')]
    if {'name', 'md'} <= set(header): return 'well-tops-csv/1'
    if {'md', 'inclination', 'azimuth'} <= set(header): return 'deviation-csv/1'
    refuse('%s is not a LAS file, a well-tops CSV or a deviation CSV.' % name + NOTHING_SENT)


def las_head(name, raw):
    """{well, null, depth_unit, x, y} of a LAS file's head, read with lasio (the `starter` extra)."""
    try: import lasio
    except ImportError: raise MissingExtra(EXTRA) from None
    try: las = lasio.read(raw.decode('utf-8', 'replace'), ignore_data=True)
    except Exception: refuse('%s could not be read as LAS.' % name + NOTHING_SENT)
    def value(key):
        item = las.well.get(key) if hasattr(las.well, 'get') else None
        return None if item is None or item.value in ('', None) else item.value
    def number(key):
        try: return None if value(key) is None else float(value(key))
        except (TypeError, ValueError): return None
    return {'well': None if value('WELL') is None else str(value('WELL')).strip(), 'null': number('NULL'),
            'depth_unit': (las.curves[0].unit or '').strip() if las.curves else '', 'x': number('XCOORD'), 'y': number('YCOORD')}


def complete(doc, tail=NOTHING_SENT):
    """Rule (e): every required pair of DOC (a definition or a pack document) present once, each subject an object of
    contents. Returns {(topic, subject): value}."""
    subjects = {'pack'} | {x for c in doc['contents'] for x in c['ids']}
    values = {}
    for d in doc['decisions']:
        if d['subject'] not in subjects: refuse('Decision %s names %s, which is not an object of contents.' % (d['topic'], d['subject']) + tail)
        if (d['topic'], d['subject']) in values: refuse('Decision %s for %s has two values.' % (d['topic'], d['subject']) + tail)
        values[(d['topic'], d['subject'])] = d['value']
    for c in doc['contents']:
        for oid in c['ids']:
            for topic in WELL_TOPICS if c['kind'] in WELL_KINDS else ():
                if (topic, oid) not in values: refuse('Decision %s for %s (%s) is missing.' % (topic, oid, c['kind']) + tail)
    return values


def decisions(defn, kinds, heads):
    """Rule (e) and D2: every required pair present once, each subject an object of contents; then the declarations each
    tops or deviation input takes from its well's decisions plus its own `declare`, and the LAS checks. KINDS is
    {input name: contents kind}, HEADS {input name: las_head}. Returns ({input name: declarations}, {well: crs})."""
    values = complete(defn)
    for i in defn['inputs']:
        if not any(c['kind'] == kinds[i['name']] and i['well'] in c['ids'] for c in defn['contents']):
            refuse('Input %s is %s of %s, which contents does not list.' % (i['name'], kinds[i['name']], i['well']) + NOTHING_SENT)
    declared, crs = {}, {}
    for i in defn['inputs']:
        name, well = i['name'], i['well']
        if kinds[name] == 'wellbore-logs':
            head = heads[name]
            if values[('names', well)] != well: refuse('names for %s: only the well\'s own name is supported in this version.' % well + NOTHING_SENT)
            if head['well'] != well: refuse('%s names well %s, not %s as the names decision says.' % (name, head['well'], well) + NOTHING_SENT)
            if head['depth_unit'].lower() != values[('units', well)].lower():
                refuse('%s has depth unit %s, not %s as the units decision says.' % (name, head['depth_unit'] or '(none)', values[('units', well)]) + NOTHING_SENT)
            try: same = float(head['null']) == float(values[('nulls', well)])
            except (TypeError, ValueError): same = False
            if not same: refuse('%s has NULL %s, not %s as the nulls decision says.' % (name, head['null'], values[('nulls', well)]) + NOTHING_SENT)
            if head['x'] is None or head['y'] is None: refuse('%s has no XCOORD and YCOORD, so its head cannot be placed in %s.' % (name, values[('crs', well)]) + NOTHING_SENT)
            crs[well] = values[('crs', well)]
            if i.get('declare'): refuse('%s: LAS files take no declarations.' % name + NOTHING_SENT)
        else:
            own = dict(i.get('declare') or {})
            for topic, field in APPLIED.items():
                if field in own: refuse('%s is given by the %s decision.' % (field, topic) + NOTHING_SENT)
                own[field] = values[(topic, well)]
            declared[name] = own
    for well in {i['well'] for i in defn['inputs'] if kinds[i['name']] == 'wellbore-logs'} ^ {x for c in defn['contents'] if c['kind'] == 'wellbore-logs' for x in c['ids']}:
        refuse('Well %s has no LAS input to place its head.' % well + NOTHING_SENT)
    return declared, crs


def custody_problems(doc, name):
    """custody.problems beyond the schema, for one custody document file NAME (M5): its key derives from its own fields,
    its file name names its digest, and a held file is not a removal."""
    if not isinstance(doc, dict) or not isinstance(doc.get('key'), str) or not isinstance(doc.get('sha256'), str) or not isinstance(doc.get('path'), str) \
            or not isinstance(doc.get('record_id'), str) or not isinstance(doc.get('removal'), dict) or not isinstance(doc.get('bytes'), int) \
            or doc.get('format') not in ('osd.custody/1', 'osd.custody/2') or not isinstance(doc.get('licence'), dict):
        return ['%s is not a custody document' % name]
    out = []
    if doc['key'] != object_key(doc['record_id'], doc['sha256'], doc['path']):
        out.append('key %s is not %s' % (doc['key'], object_key(doc['record_id'], doc['sha256'], doc['path'])))
    tomb = name.endswith('.removed.json')
    if name != doc['sha256'] + ('.removed.json' if tomb else '.json'): out.append('file name %s does not name the digest %s' % (name, doc['sha256']))
    if tomb != (doc['removal'].get('state') == 'removed'): out.append('removal state %s in %s' % (doc['removal'].get('state'), name))
    return out


def custody_document(directory, digest, what, tail=NOTHING_SENT):
    """The held custody document of DIGEST in DIRECTORY (`<sha256>.json`), checked (M5); a tombstone wins (OSD)."""
    directory = Path(directory)
    if (directory / (digest + '.removed.json')).exists(): refuse('%s: its custody document is removed: never in a pack.' % what + tail)
    p = directory / (digest + '.json')
    if not p.is_file(): refuse('%s: no held custody document has its SHA-256.' % what + tail)
    raw = p.read_bytes()
    try: doc = json.loads(raw)
    except ValueError: refuse('%s: %s is not JSON.' % (what, p.name) + tail)
    bad = custody_problems(doc, p.name)
    if bad: refuse('%s: %s.' % (what, '; '.join(bad)) + tail)
    return doc, raw


def provenance(doc):
    return 'deposit' if 'deposit' in doc else 'derived' if 'derived' in doc else 'verified'


def record_licence(rec):
    return {k: rec['licence'][k] for k in LICENCE_FIELDS if k in rec['licence']}


def bound(defn, catalogue, verification, custody):
    """Rule (b) and D3: each input bound to its evidence. CATALOGUE is OSD's built records.json, VERIFICATION the folder of
    `<record __>.json` verification results, CUSTODY the folder of custody documents. Returns the evidence judged
    (`evidence.json`'s content) and {path read: sha256} of every evidence file read (R6)."""
    read = {}
    def load(path):
        raw = Path(path).read_bytes(); read[str(Path(path).resolve())] = sha256(raw); return json.loads(raw)
    try: records = load(catalogue)
    except (OSError, ValueError): refuse('%s is not a catalogue records.json.' % Path(catalogue).name + NOTHING_SENT)
    rid = defn['record_id']
    rec = next((r for r in records.get('records') or [] if isinstance(r, dict) and r.get('id') == rid), None) if isinstance(records, dict) else None
    if rec is None or not isinstance(records.get('catalog'), dict): refuse('Record %s is not in the catalogue %s.' % (rid, Path(catalogue).name) + NOTHING_SENT)
    evidence = {'format': EVIDENCE, 'record': rec, 'catalog': records['catalog'], 'verification': None, 'deposits': {}}
    for i in defn['inputs']:
        what = 'input %s' % i['name']
        if i['held']['as'] == 'verified':
            if evidence['verification'] is None:
                p = Path(verification) / (rid.replace('/', '__') + '.json')
                try: evidence['verification'] = load(p)
                except (OSError, ValueError): refuse('%s: no verification of %s.' % (what, rid) + NOTHING_SENT)
        else:
            doc, raw = custody_document(custody, i['sha256'], what)
            read[str((Path(custody) / (i['sha256'] + '.json')).resolve())] = sha256(raw)
            evidence['deposits'][i['name']] = doc
        held(i, evidence)
    return evidence, read


def held(i, evidence, tail=NOTHING_SENT):
    """Rule (b) for one input I ({name, sha256, bytes, held}) against the EVIDENCE `bound` judged."""
    what, held, rid = 'input %s' % i['name'], i['held'], evidence['record']['id']
    if held['as'] == 'verified':
        v = evidence['verification'] or {}
        if (held['verifier_run']['checked_at'], held['verifier_run']['tool_version']) != (v.get('checked_at'), v.get('tool_version')):
            refuse('%s: verifier_run %s %s is not the latest verification of %s.' % (what, held['verifier_run']['checked_at'], held['verifier_run']['tool_version'], rid) + tail)
        f = next((f for f in v.get('files') or [] if f.get('path') == held['path']), None)
        if f is None: refuse('%s: path %s is not a file of the latest verification of %s.' % (what, held['path'], rid) + tail)
        agrees(what, i, object_name(f['path']), f, 'the verification', tail)
    else:
        doc = evidence['deposits'].get(i['name'])
        if doc is None or doc['key'] != held['key']: refuse('%s: no held custody document has key %s.' % (what, held['key']) + tail)
        if doc['record_id'] != rid: refuse('%s: custody key %s holds a file of record %s, not %s.' % (what, held['key'], doc['record_id'], rid) + tail)
        if provenance(doc) != 'deposit': refuse('%s: custody key %s is a %s copy, not a deposit.' % (what, held['key'], provenance(doc)) + tail)
        agrees(what, i, object_name(doc['path']), doc, 'its custody document', tail)


def agrees(what, item, name, evidence, source, tail=NOTHING_SENT):
    for k in ('bytes', 'sha256'):
        if item[k] != evidence.get(k): refuse('%s: %s %s, %s states %s.' % (what, k, item[k], source, evidence.get(k)) + tail)
    if item['name'] != name: refuse('%s: name %s is not %s, the file %s names.' % (what, item['name'], name, source) + tail)


def licences(defn, evidence):
    """[{input, licence}] in input order: the record's licence for a verified input, the deposit's for a deposited one."""
    return [{'input': i['name'], 'licence': record_licence(evidence['record']) if i['held']['as'] == 'verified' else evidence['deposits'][i['name']]['licence']}
            for i in defn['inputs']]


def computed_licence(sources, tail=NOTHING_SENT):
    """Rule (d) (starters.py computed_licence): the pack licence from its inputs' licences, refused when not computable."""
    for s in sources:
        if s['licence']['redistribution'] != 'allowed':
            refuse('input %s: redistribution %s: never in a pack.' % (s['input'], s['licence']['redistribution']) + tail)
    lics, common = [s['licence'] for s in sources], {}
    for f in AGREE:
        if len({json.dumps(lic.get(f, ABSENT), sort_keys=True) for lic in lics}) > 1:
            refuse('Unsupported combination: the inputs\' licence %s differs.' % f + tail)
        if f in lics[0]: common[f] = lics[0][f]
    attribution = ('required' if any(lic['attribution'] == 'required' for lic in lics) else
                   'unknown' if any(lic['attribution'] == 'unknown' for lic in lics) else 'not-required')
    lic = {**common, 'redistribution': 'allowed', 'attribution': attribution}
    if any('share_alike' in x for x in lics): lic['share_alike'] = any(x.get('share_alike') is True for x in lics)
    return {k: lic[k] for k in LICENCE_FIELDS if k in lic}


def attribution(defn, sources, evidence):
    """ATTRIBUTION.md: each input's licence (name, spdx, url, statement) and the attribution lines of its custody document."""
    lines = ['# Attribution', '', '%s (%s), a starter pack of catalogue record %s.' % (defn['title'], defn['id'], defn['record_id']), '']
    for s in sources:
        lic = s['licence']
        lines.append('- %s: %s%s%s%s' % (s['input'], lic['name'], ' (%s)' % lic['spdx'] if lic.get('spdx') else '', ', %s' % lic['url'] if lic.get('url') else '',
                                          '. %s' % lic['statement'] if lic.get('statement') else ''))
        for line in (evidence['deposits'].get(s['input']) or {}).get('attribution') or []: lines.append('  %s' % line)
    return ('\n'.join(lines) + '\n').encode('utf-8')


# --- build and finalise (C4) -------------------------------------------------------------------------------------------

NOT_WRITTEN = ' No pack document was written.'
UNCHANGED = ' starter.json was not changed.'
OPEN_PACK, HEADS, ATTRIBUTION = 'targets/python/open_pack.py', 'targets/python/heads/%s.geojson', 'ATTRIBUTION.md'
ORACLE = {'compared': ['nothing yet: no reader outside Ophiolite has read this pack (slice e)'], 'values': 0, 'differences': 0, 'seed': 0}  # F4
LANDED_STATES = ('added', 'already-here')
SEGMENT = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]*')
MOVED = '%s has a newer version in the project than the one this pack was built from; build again in a new folder.'
BINDING = '%s differs from the one this folder was built with; build in a new folder.'
DENIED = ('This access key may not add files to project %s: %s was not landed (%d of %d inputs landed before it, kept in landing.json).'
          + NOT_WRITTEN)
# E129 sc: the archive pack, built from the export `ophiolite starter export` wrote (strategy rev 3, D1-D4, D6)
OPENDTECT_IMPORT = 'targets/opendtect/import.py'
OPENDTECT_RELEASE = '7.0.10'  # ophiolite_opendtect data/host.json opendtect.release (the SDK never imports the connector; a gateway test holds them equal)
ORACLE_OPENDTECT = {'compared': ['nothing yet: the pack has not been imported into OpendTect and compared (ophiolite starter opendtect)'],
                    'values': 0, 'differences': 0, 'seed': 0}
EXPORT_PROFILE = {'seismic-3d': 'segy/1', 'horizons': 'points-csv/1', 'wellbore-paths': 'well-path-positions-csv/1',
                  'wellbore-logs': 'las2/1', 'seismic-2d': 'segy-line/1', 'faults': 'opendtect-faultsticks/1', 'time-depth': 'time-depth-csv/1'}  # E137 s0 D-01 (R1-6): what this SDK lands; each value is its kind's catalogue profile
MAX_NODES = 100_000  # E139: the nodes a deployment that does not state its `horizon_nodes` takes (e8's B5 ruling, 29 Oct)
TOO_MANY_NODES = 'This horizon has more nodes than Ophiolite takes ({:,}).'  # E139: the deployment's M, by number
READ_BACK = '%s reads back from Ophiolite with another value than its file at node %d.' + NOT_WRITTEN  # E139 s2 (S2-12)
WINDOW = 16  # E139 s2 (S2-12): the nodes compared in order from the middle of a horizon, besides its first and last
SECOND_PATH = 'The derived file %s has the same bytes as %s; a file has one path in a pack (the mirror holds one copy per SHA-256).'
NOT_THE_EXPORT = 'The export at %s is not of this definition and archive; run ophiolite starter export again.' + NOT_WRITTEN
DERIVED_MISSING = '%s is missing from the export at %s.' + NOT_WRITTEN
DERIVED_CHANGED = '%s in the export at %s is not the file its report names: its SHA-256 differs.' + NOT_WRITTEN
DOMAIN = "The export's survey is in %s %s; horizons and cubes are landed in time (ms) or depth (m) only." + NOT_WRITTEN
LINE_DOMAIN = "The export's survey is in %s %s; 2D lines are landed in time (ms) only in this version."  # E137 s1 R1-1
LINES_OF = 'lines of dataset %s in this pack'  # E137 s1 D-4 (D84): a line's representative value, "N of M"
EXPORT_FOLDER = re.compile(r'exports/[A-Za-z0-9][A-Za-z0-9._-]*')


def dumped(doc):
    """D7: one fixed form for every document written (indent 2, the text as written, a trailing newline)."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def replaced(path, raw):
    """Every write: the bytes beside PATH, then a rename over it, so a reader sees the old file or the new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.%s.writing' % path.name)
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def placed(well, crs, x, y):
    """A well head as a GeoJSON point in WGS84 (longitude first), from its XCOORD and YCOORD in CRS, 9 decimals (D2)."""
    try: from pyproj import Transformer
    except ImportError: raise MissingExtra(EXTRA) from None
    try: lon, lat = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(x, y)
    except Exception: refuse('crs for %s: %s is not a coordinate reference system this computer can transform.' % (well, crs) + NOTHING_SENT)
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(lon, 9) + 0.0, round(lat, 9) + 0.0]},
            'properties': {'well': well, 'crs': crs, 'x': x, 'y': y}}


def open_pack(defn):
    """The python target's import script: the pack's inputs by name and digest, and its well heads."""
    wells = [i['well'] for i in defn['inputs'] if profile_of(defn, i) == 'las2/1']
    return ('"""Starter pack %s: %s.\n\nIts inputs are held files of catalogue record %s (osd get %s). heads() reads the well heads this\n'
            'pack placed in WGS84 from heads/<well>.geojson beside this file."""\nimport json\nfrom pathlib import Path\n\n'
            'PACK = %r\nINPUTS = %r  # name: SHA-256\nWELLS = %r\n\n\ndef heads():\n'
            '    """{well: (longitude, latitude)}."""\n    here = Path(__file__).resolve().parent\n'
            "    return {w: tuple(json.loads((here / 'heads' / (w + '.geojson')).read_text())['geometry']['coordinates']) for w in WELLS}\n\n\n"
            "if __name__ == '__main__':\n    for well, (lon, lat) in heads().items(): print(well, lon, lat)\n"
            % (defn['id'], defn['title'], defn['record_id'], defn['record_id'], defn['id'], {i['name']: i['sha256'] for i in defn['inputs']}, wells)).encode('utf-8')


def profile_of(defn, i):
    return defn['profiles'][i['name']]


def tools():
    """recipe.tools: the versions this run used."""
    try: import lasio, pyproj
    except ImportError: raise MissingExtra(EXTRA) from None
    from ._version import __version__
    return {'python': platform.python_version(), 'ophiolite': __version__, 'lasio': str(lasio.__version__), 'pyproj': str(pyproj.__version__)}


def distinct(artefacts, inputs, tail, derived=()):
    """D5: no two artefacts, and no artefact and input, share a SHA-256 (an artefact is made, not copied). E129 sc C3b
    (OSD custody caveat: one custody document per digest): no two derived files and no derived file and input share a
    SHA-256 either; a derived file is published as the artefact at its own path, so an artefact with the path and
    digest of a derived entry is that file, and any other collision is refused."""
    seen = {i['sha256']: i['name'] for i in inputs}
    for d in derived:
        if d['sha256'] in seen: refuse(SECOND_PATH % (d['path'], seen[d['sha256']]) + tail)
        seen[d['sha256']] = d['path']
    own = {(d['path'], d['sha256']) for d in derived}
    for a in artefacts:
        if (a['path'], a['sha256']) in own:
            own.discard((a['path'], a['sha256']))
            continue
        if a['sha256'] in seen: refuse('%s has the same bytes as %s; an artefact must be made, not copied.' % (a['path'], seen[a['sha256']]) + tail)
        seen[a['sha256']] = a['path']


def stem(pack_id):
    return pack_id.replace('/', '__')


def prepared(definition_path, catalogue, verification, custody):
    """Everything `build` decides before anything is sent: the definition and its local files, the decisions, the evidence
    and licence, the artefacts' bytes and the pack document. Refused with nothing sent."""
    defn = definition(definition_path)
    raws = local(defn)
    defn['profiles'] = {name: profile(name, raw) for name, raw in raws.items()}
    kinds = {name: PROFILE_KIND[p] for name, p in defn['profiles'].items()}
    heads = {name: las_head(name, raws[name]) for name, p in defn['profiles'].items() if p == 'las2/1'}
    declared, crs = decisions(defn, kinds, heads)
    evidence, read = bound(defn, catalogue, verification, custody)
    sources = licences(defn, evidence)
    lic = computed_licence(sources)
    files, derived = {OPEN_PACK: open_pack(defn)}, []
    for i in defn['inputs']:
        if defn['profiles'][i['name']] != 'las2/1': continue
        if not SEGMENT.fullmatch(i['well']): refuse('Well %s cannot name a file in the pack.' % i['well'] + NOTHING_SENT)
        h = heads[i['name']]
        path = HEADS % i['well']
        files[path] = dumped(placed(i['well'], crs[i['well']], h['x'], h['y']))
        derived.append({'path': path, 'sha256': sha256(files[path]), 'bytes': len(files[path]), 'from': i['sha256'],
                        'how': 'The well head (XCOORD, YCOORD) of %s in %s, transformed with pyproj to WGS84 longitude and latitude, 9 decimals.' % (i['name'], crs[i['well']])})
    files[ATTRIBUTION] = attribution(defn, sources, evidence)
    artefacts = [{'path': p, 'sha256': sha256(raw), 'bytes': len(raw)} for p, raw in files.items()]
    distinct(artefacts, defn['inputs'], ' Nothing was written.')
    doc = {'format': STARTER, 'id': defn['id'], 'record_id': defn['record_id'], 'title': defn['title'], 'summary': defn['summary'], 'unpublished': True,
           'recipe': {**defn['recipe'], 'tools': tools()}, 'contents': defn['contents'],
           'inputs': [{k: i[k] for k in ('name', 'sha256', 'bytes', 'held')} for i in defn['inputs']], 'derived': derived, 'decisions': defn['decisions'],
           'targets': [{'application': 'python', 'version': platform.python_version(), 'artefacts': artefacts, 'import': OPEN_PACK, 'oracle': ORACLE}],
           'licence': {**lic, 'sources': sources}, 'fidelity': 'fidelity/%s.json' % stem(defn['id']), 'built_at': defn['built_at']}
    landings = [{'name': i['name'], 'path': defn['folder'] / i['file'], 'sha256': i['sha256'], 'profile': defn['profiles'][i['name']],
                 'declared': declared.get(i['name']) or {}, 'kind': PROFILE_KIND[defn['profiles'][i['name']]]} for i in defn['inputs']]
    return {'defn': defn, 'raw_definition': Path(definition_path).read_bytes(), 'declared': declared, 'evidence': evidence, 'read': read,
            'files': files, 'doc': doc, 'landings': landings, 'export': None}


def exported(out, defn, raw_definition):
    """D1: the export report OUT/derived.json points to, exactly {"export": "exports/<folder>"} naming a folder directly
    under OUT/exports/, of this definition (its sha256) and this archive. Returns (report, its bytes, folder)."""
    from . import starter_archive
    out = Path(out)
    def wrong(): refuse(NOT_THE_EXPORT % out)
    try: pointer = json.loads((out / 'derived.json').read_bytes())
    except (OSError, ValueError): wrong()
    name = pointer.get('export') if isinstance(pointer, dict) and set(pointer) == {'export'} else None
    if not isinstance(name, str) or not EXPORT_FOLDER.fullmatch(name): wrong()
    folder = out / name
    try: inside = not folder.is_symlink() and folder.is_dir() and folder.resolve().parent == (out / 'exports').resolve()
    except OSError: inside = False
    if not inside: wrong()
    try: raw = (folder / 'derived.json').read_bytes(); report = json.loads(raw)
    except (OSError, ValueError): wrong()
    archive = defn['inputs'][0]
    if not isinstance(report, dict) or report.get('format') != starter_archive.REPORT or report.get('record_id') != defn['record_id'] \
            or report.get('definition') != sha256(raw_definition) or not isinstance(report.get('archive'), dict) or report['archive'].get('sha256') != archive['sha256'] \
            or not isinstance(report.get('survey'), dict) or not isinstance(report.get('derived'), list) or not isinstance(report.get('files'), list):
        wrong()
    return report, raw, folder


def inventory(report, folder, archive, out, *, readers=None, export_profile=None):
    """D2: the report's derived files (the outline is never one), each with its kind from the report's files, its `from`
    the archive and its bytes re-hashed here; a missing or changed file refuses naming its path. E137 s0 (R2-3):
    READERS and EXPORT_PROFILE are the module tables unless a test passes its own; a path has the depth of its kind."""
    from . import starter_archive
    files = {f.get('path'): f for f in report['files'] if isinstance(f, dict)}
    paths = [d.get('path') if isinstance(d, dict) else None for d in report['derived']]
    if not paths or None in paths or len(set(paths)) != len(paths) or sorted(paths, key=str) != sorted(files, key=str): refuse(NOT_THE_EXPORT % out)
    for f in files.values():  # E137 s0 D-03, R2-5: the whole report first; a kind this SDK cannot land is named before any hash
        if starter_kinds.known(f.get('kind')) and not starter_archive.writable(f['kind'], readers, export_profile): refuse(starter_kinds.cannot_hold(f['kind']) + NOT_WRITTEN)
    derived = []
    for d in report['derived']:
        f = files[d['path']]
        if set(d) != {'path', 'sha256', 'bytes', 'from', 'how'} or d['from'] != archive['sha256'] \
                or f.get('kind') not in (starter_archive.KINDS if readers is None else readers) \
                or not isinstance(d['path'], str) or len(d['path'].split('/')) != starter_kinds.depth(f['kind']) or d['path'].split('/')[0] != starter_archive.FOLDER[f['kind']] \
                or not all(SEGMENT.fullmatch(s) for s in d['path'].split('/')):
            refuse(NOT_THE_EXPORT % out)
        p = folder / 'files' / d['path']
        if not p.is_file() or p.is_symlink(): refuse(DERIVED_MISSING % (d['path'], out))
        if starter_archive.digest_of(p) != (d['sha256'], d['bytes']): refuse(DERIVED_CHANGED % (d['path'], out))
        derived.append({**d, 'kind': f['kind'], 'object': f.get('object'), 'local': p,
                        **({'of': f.get('of')} if f['kind'] == 'seismic-2d' else {})})  # E137 s1: the dataset's line count (D84's M)
    return derived


def declarations(survey, kinds):
    """D4: per contents kind, what each derived file is declared to be, from the export's survey only; what it does not
    state is sent as unknown, never a default (B1)."""
    def known(v): return v if isinstance(v, str) and v else 'unknown'
    domain = {'twt': 'time', 'depth': 'depth'}.get(survey.get('zdomain'))
    if kinds & {'seismic-3d', 'horizons'} and (domain, survey.get('zunit')) not in (('time', 'ms'), ('depth', 'm')):
        refuse(DOMAIN % (survey.get('zdomain'), survey.get('zunit')))
    if 'seismic-2d' in kinds and (domain, survey.get('zunit')) != ('time', 'ms'): refuse(LINE_DOMAIN % (survey.get('zdomain'), survey.get('zunit')) + NOT_WRITTEN)
    crs, xy = known(survey.get('crs')), known(survey.get('xyunit'))
    return {'seismic-3d': {'crs': crs, 'z_domain': known(domain)}, 'seismic-2d': {'crs': crs, 'z_domain': known(domain)},
            'horizons': {'crs': crs, 'xy_unit': xy, 'z_meaning': known(domain), 'z_unit': known(survey.get('zunit')), 'positive': 'down'},
            'wellbore-paths': {'crs': crs, 'xy_unit': xy, 'depth_unit': known(survey.get('depth_unit')), 'tvdss_datum': 'MSL',
                               'md_reference': OPENDTECT_MD_REFERENCE},
            'wellbore-logs': {},
            'faults': {'crs': crs, 'xy_unit': xy, 'z_meaning': 'time', 'z_unit': 's', 'positive': 'down', 'vertical_datum': 'unknown'}}  # E137 s2 D-5


# E129 (f) Q6 (R2-10): the export reads each well path from OpendTect (`Well.track` dah), whose measured depth is from the
# kelly bushing: ophiolite_opendtect heads.BASIS datum, as E125 s3b declares for the same wells (a gateway test holds
# them equal, as OPENDTECT_RELEASE; the SDK never imports the connector)
OPENDTECT_MD_REFERENCE = 'KB'


def nodes(path):
    """The data rows of a points-csv/1 horizon (every node of its grid), counted without holding the file."""
    with open(path, 'rb') as f: return max(0, sum(1 for line in f if line.strip()) - 1)


def horizon_nodes(client):
    """E139: the nodes one horizon may have, as the deployment states it (`served_limits()['horizon_nodes']`, M); a
    deployment (or a client) that does not state it takes MAX_NODES, as before."""
    if not hasattr(client, 'served_limits'): return MAX_NODES
    stated = client.served_limits().get('horizon_nodes')
    return stated if isinstance(stated, int) and not isinstance(stated, bool) and stated > 0 else MAX_NODES


def read_back(name, path, unit):
    """E139 s2 (S2-12): a check of a landed horizon's read-back, independent of the fidelity enum: its Z values in file order
    against the file's own text, at the first and last node and WINDOW nodes from the middle. Equal float64 values are
    float32-exact wherever the file's text is. Returns the read's representative values; another value refuses."""
    import csv
    with open(path, newline='') as f:
        rows = csv.reader(f)
        column = next(rows).index('z')
        source = [float(r[column]) if r[column] != '' else None for r in rows if r]
    def compare(read):
        served = [p[2] for p in read.points]
        middle = max(0, len(source) // 2 - WINDOW // 2)
        at = sorted({0, len(source) - 1, *range(middle, min(len(source), middle + WINDOW))})
        if len(served) != len(source): raise Refused(READ_BACK % (name, min(len(served), len(source)) + 1))
        for k in at:
            if served[k] != source[k]: raise Refused(READ_BACK % (name, k + 1))
        shown = lambda v: 'no value' if v is None else v
        return [{'field': 'Z of node 1', 'value': shown(served[0]), 'unit': unit}, {'field': 'Z of node %d' % len(served), 'value': shown(served[-1]), 'unit': unit},
                {'field': 'nodes compared with the file in order (the first, the last, and from node %d)' % (middle + 1), 'value': '%d of %d equal' % (len(at), len(at)), 'unit': None}]
    return compare


NO_CONNECTOR = 'Run this import with the Python the OpendTect connector (ophiolite-opendtect) is installed in; nothing was placed.'


def opendtect_import(defn, files, not_read):
    """D6's import artefact (E129 sc C3): a launcher of the installed connector's `ophiolite_opendtect.starter_import`
    with this pack's id, its files {path: {kind, object, declared}} and the export's not_read entries. It is text here:
    the SDK never imports the connector (X2), and the script needs only the connector, the pack's files and a survey.
    E129 (f) D6, D7: the text says logs are placed or refused per curve, the GUI well step and the measured release."""
    return ('"""Starter pack %s: the OpendTect import.\n\nPlaces the pack\'s seismic cubes, horizons and logs in an existing OpendTect '
            'survey through odbind; each log is\nplaced or refused per curve, on a well the survey already has. OpendTect 7.0.10 '
            'cannot create a well from\nPython: import each well path in OpendTect first (Survey > Import > Wells), then run this '
            'import.\nMeasured with OpendTect 7.0.10; check your installation with python -m ophiolite_opendtect.host DTECT_APPL.\n'
            'Run it with the Python the OpendTect connector (ophiolite-opendtect) is installed in:\n\n    python import.py PACK --survey '
            'ROOT/NAME\n\nPACK is the folder holding starter.json and files/, with the pack\'s files at their paths."""\nimport sys\n\n'
            'PACK = %r\nFILES = %r\nNOT_READ = %r\n\n\n'
            "if __name__ == '__main__':\n    try: from ophiolite_opendtect import starter_import\n    except ImportError: sys.exit(%r)\n"
            '    sys.exit(starter_import.main(sys.argv[1:], pack=PACK, files=FILES, not_read=NOT_READ))\n'
            % (defn['id'], defn['id'], files, not_read, NO_CONNECTOR)).encode('utf-8')


PY_EXPECTED_FORMAT, PY_EXPECTED_LINES = 'ophiolite.starter-python-expected/1', 'ophiolite.starter-python-expected/2'  # E137 s1 R1-17: /2 only with lines
PY_IMPORT, PY_EXPECTED, PY_RESULT = 'targets/python/open-a-starter-pack.ipynb', 'targets/python/expected.json', 'targets/python/result.json'
NO_CUBE = 'The Python target reads a cube or a 2D line; this export has neither.'  # E137 s1 D-4
NO_PLANE = 'the pack holds no cube, so its wells have no inline or crossline; each is read at its own x and y'  # E137 s1 R2-9
FLAT = "The cube's corners do not span an area; the Python target cannot place wells on it."


def affine(headers):
    """E129 (e) D1: (origin, inline step, crossline step, inverse) of the plane through three corner traces of the grid
    (first inline and crossline, last crossline, last inline), in coordinates per line number; refused when the corners
    span no area (one inline, one crossline, or collinear positions)."""
    at = {(i, c): (x, y) for i, c, x, y in headers}
    inlines, crosslines = sorted({h[0] for h in headers}), sorted({h[1] for h in headers})
    i0, i1, c0, c1 = inlines[0], inlines[-1], crosslines[0], crosslines[-1]
    if i0 == i1 or c0 == c1: refuse(FLAT + NOT_WRITTEN)
    (x0, y0), (xi, yi), (xc, yc) = at[(i0, c0)], at[(i1, c0)], at[(i0, c1)]
    di, dc = ((xi - x0) / (i1 - i0), (yi - y0) / (i1 - i0)), ((xc - x0) / (c1 - c0), (yc - y0) / (c1 - c0))
    det = di[0] * dc[1] - di[1] * dc[0]
    if abs(det) <= 1e-9 * max(1e-300, math.hypot(*di) * math.hypot(*dc)): refuse(FLAT + NOT_WRITTEN)
    def lines(x, y):
        """(inline, crossline) of the position (x, y) on the plane."""
        dx, dy = x - x0, y - y0
        return i0 + (dx * dc[1] - dy * dc[0]) / det, c0 + (di[0] * dy - di[1] * dx) / det
    return lines


def las_facts(path):
    """E129 (e) D1: (curves, [STRT, STOP]) of a LAS 2.0 file from its text: the ~Curve lines after the index curve,
    and the ~Well STRT and STOP values (read without lasio, so the notebook's lasio read is checked against them)."""
    section, curves, well = None, 0, {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        s = line.strip()
        if not s or s.startswith('#'): continue
        if s.startswith('~'): section = s[1:2].upper(); continue
        if section == 'C': curves += 1
        elif section == 'W' and '.' in s:
            mnemonic, rest = s.split('.', 1)
            value = rest.split(None, 1)[1] if rest[:1] not in (' ', '\t') and len(rest.split(None, 1)) > 1 else rest
            well[mnemonic.strip().upper()] = value.split(':', 1)[0].strip()
    try: depth = [float(well['STRT']), float(well['STOP'])]
    except (KeyError, ValueError): refuse('%s has no STRT and STOP depths.' % Path(path).name + NOT_WRITTEN)
    return max(0, curves - 1), depth


def first_station(path, name):
    """(x, y) of the first row of a `md,x,y,tvdss` positions file."""
    lines = Path(path).read_text(encoding='ascii').splitlines()
    try:
        md, x, y, tvdss = (float(v) for v in lines[1].split(','))
        if lines[0] != 'md,x,y,tvdss' or not all(math.isfinite(v) for v in (md, x, y, tvdss)): raise ValueError
    except (IndexError, ValueError): refuse('%s has no first row md,x,y,tvdss.' % name + NOT_WRITTEN)
    return x, y


def expected(derived):
    """E137 s3 D-8 (F3): `_expected`, and for a pack with time-depth models their pairs (`time_depth`, path order) last;
    a pack without models keeps every byte."""
    doc = _expected(derived)
    models = time_depth_expected(derived)
    return {**doc, 'time_depth': models} if models else doc


def time_depth_expected(derived):
    """E137 s3 D-8: [{well, path, pairs: [[depth, time], ...]}] of the pack's time-depth files in path order, the pairs
    as floats in file order, read from the written time-depth-csv/1 text (header `depth,time`)."""
    out = []
    for d in sorted((d for d in derived if d['kind'] == 'time-depth'), key=lambda d: d['path']):
        rows = Path(d['local']).read_text(encoding='utf-8').splitlines()[1:]
        out.append({'well': d['object'], 'path': d['path'], 'pairs': [[float(v) for v in row.split(',')] for row in rows]})
    return out


def _expected(derived):
    """E129 (e) D1: `files/targets/python/expected.json` of an archive pack's derived files ([{path, kind, object,
    local}]): the first cube in path order, the floor middle of its inline range, three samples of that inline (first,
    middle and last crossline at the middle sample index), its float64 sum (the exactly rounded sum of its float32
    samples, so the order of summing does not matter), and each well's first station projected onto the cube's lines
    through the plane of its trace headers, with its LAS's curve count and depth range where the pack holds one.
    E137 s1 D-4 (R1-14, R1-17, R2-9): a pack with 2D lines gets /2, its `lines` (`line_expected`, path order) after
    the rest; without a cube, `cube` and its values are null, and each well's inline and crossline too (`not_computed`
    says why). A pack without lines keeps /1 byte for byte."""
    from . import starter_archive
    cubes = sorted((d for d in derived if d['kind'] == 'seismic-3d'), key=lambda d: d['path'])
    lines_of = sorted((d for d in derived if d['kind'] == 'seismic-2d'), key=lambda d: d['path'])
    if not cubes and not lines_of: refuse(NO_CUBE + NOT_WRITTEN)
    if not cubes:
        doc = {'schema': PY_EXPECTED_LINES, 'cube': None, 'inline': None, 'crosslines': None, 'z': None, 'samples': [], 'inline_sum': None,
               'wells': wells_at(derived, None), 'not_computed': NO_PLANE}
        return {**doc, 'lines': [line_expected(d) for d in lines_of]}
    cube = cubes[0]
    def middle(axes):
        i0, i1, step = axes['inline']
        return i0 + step * (((i1 - i0) // step) // 2)
    axes, headers, inline, line = starter_archive.cube_inline(cube['local'], cube['path'], middle)
    lines = affine(headers)
    c0, c1, cstep = axes['crossline']
    count = axes['z'][2]
    picks = [0, (len(line) - 1) // 2, len(line) - 1]
    k = (count - 1) // 2
    doc = {'schema': PY_EXPECTED_FORMAT, 'cube': cube['path'], 'inline': inline, 'crosslines': [c0, c1, cstep], 'z': axes['z'],
           'samples': [{'crossline': c0 + cstep * n, 'index': k, 'value': line[n][k]} for n in picks],
           'inline_sum': math.fsum(v for trace in line for v in trace), 'wells': wells_at(derived, lines)}
    return {**doc, 'schema': PY_EXPECTED_LINES, 'lines': [line_expected(d) for d in lines_of]} if lines_of else doc


def wells_at(derived, lines):
    """Each well's first station, projected through LINES (the cube's plane; None without a cube: inline and crossline
    null), with its LAS's curve count and depth range where the pack holds one."""
    logs = {d['object']: d for d in derived if d['kind'] == 'wellbore-logs'}
    wells = []
    for d in sorted((d for d in derived if d['kind'] == 'wellbore-paths'), key=lambda d: d['path']):
        x, y = first_station(d['local'], d['path'])
        il, xl = lines(x, y) if lines else (None, None)
        las = logs.get(d['object'])
        curves, depth = las_facts(las['local']) if las else (None, None)
        wells.append({'name': d['object'], 'positions': d['path'], 'x': x, 'y': y, 'inline': None if il is None else round(il, 2) + 0.0,
                      'crossline': None if xl is None else round(xl, 2) + 0.0, 'las': las['path'] if las else None, 'curves': curves, 'depth': depth})
    return wells


def line_expected(d):
    """E137 s1 D-4 (R1-14): what the notebook must read of the 2D line D: its trace numbers, source points (None for
    none), x and y in file order, Z [delay ms, interval us, count], three samples (first, middle and last trace at the
    middle index), the float64 sum of its samples and the SHA-256 of its float32 samples (big-endian, file order)."""
    from . import starter_archive
    rows, h = [], hashlib.sha256()
    def each(number, sp, scalar, x, y, samples):
        h.update(samples)
        rows.append((number, None if (sp, scalar) == (0, 0) else sp / -scalar if scalar < 0 else float(sp * scalar), x / 100, y / 100,
                     struct.unpack('>%df' % (len(samples) // 4), samples)))
    axes = starter_archive.line_scanned(d['local'], {'path': d['path'], 'object': d['object']}, each)
    k = (axes['z'][2] - 1) // 2
    picks = sorted({0, (len(rows) - 1) // 2, len(rows) - 1})
    return {'path': d['path'], 'object': d['object'], 'traces': len(rows), 'numbers': [r[0] for r in rows], 'source_points': [r[1] for r in rows],
            'x': [r[2] for r in rows], 'y': [r[3] for r in rows], 'z': axes['z'],
            'samples': [{'trace': rows[n][0], 'index': k, 'value': rows[n][4][k]} for n in picks],
            'sum': math.fsum(v for r in rows for v in r[4]), 'sha256': h.hexdigest()}


NOTEBOOK = Path(__file__).resolve().parent / 'templates' / 'starter-pack'  # the packaged notebook: its script and its built .ipynb
ORACLE_PYTHON = {'compared': ['nothing yet: the pack notebook has not been run on this pack (ophiolite starter python)'], 'values': 0, 'differences': 0, 'seed': 0}
PY_FAULTS_LINE = 'faults: not drawn; the pack notebook does not read fault sticks'  # E137 s2 D-8: last, for a pack with faults
PY_TD_LINE = 'Time-depth model %s: %d pairs checked'  # E137 s3 D-8 (V): one per model the notebook compared, before PY_FAULTS_LINE


def python_waiting(faults):
    """The Python oracle before the notebook runs: ORACLE_PYTHON, with PY_FAULTS_LINE last for a pack with faults."""
    return {**ORACLE_PYTHON, 'compared': [*ORACLE_PYTHON['compared'], PY_FAULTS_LINE]} if faults else ORACLE_PYTHON
SHARED = 'artefact %s is listed by two targets with different bytes or keys; a derived file is one artefact in every target.'
SAME_BYTES = 'artefacts %s and %s of two targets have the same bytes; a file has one path in a pack.'


def python_files(derived):
    """E129 (e) D4: ({path: bytes} the Python target makes, its expected values): the packaged notebook and expected.json."""
    values = expected(derived)
    return {PY_IMPORT: (NOTEBOOK / 'open-a-starter-pack.ipynb').read_bytes(), PY_EXPECTED: dumped(values)}, values


def across(targets, derived, tail):
    """E129 (e) D4, R2-8: a path two targets both list is a derived file, listed with the same path, sha256, bytes (and
    key, once finalised) in each; and no two paths of the pack's targets hold the same bytes."""
    own, seen, paths = {d['path']: d for d in derived}, {}, {}
    for t in targets:
        for a in t['artefacts']:
            if a['path'] not in seen: seen[a['path']] = a; continue
            d = own.get(a['path'])
            if d is None or a != seen[a['path']] or (a['sha256'], a['bytes']) != (d['sha256'], d['bytes']): refuse(SHARED % a['path'] + tail)
    for n, t in enumerate(targets):  # within one target, distinct() says it
        for a in t['artefacts']:
            other = paths.get(a['sha256'])
            if other and other[0] != n and other[1] != a['path']: refuse(SAME_BYTES % (other[1], a['path']) + tail)
            paths.setdefault(a['sha256'], (n, a['path']))


def artefact_digest(out, path):
    """(sha256, bytes) of OUT/files/PATH read in blocks (a derived artefact may be a large cube); None when unreadable."""
    from . import starter_archive
    try: return starter_archive.digest_of(Path(out) / 'files' / path)
    except OSError: return None


def copied(source, path, digest, size):
    """E129 sc C3: a derived file into the pack's files/ at its own path (C3b: its one path, the artefact OSD publishes
    and import.py reads): copied beside, checked, renamed over; a file already there with its size and digest is kept."""
    from . import starter_archive
    path = Path(path)
    if path.is_file() and not path.is_symlink() and starter_archive.digest_of(path) == (digest, size): return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.%s.writing' % path.name)
    shutil.copyfile(source, temporary)
    if starter_archive.digest_of(temporary) != (digest, size):
        temporary.unlink()
        refuse('%s changed while it was copied into the pack folder; build again.' % path.name + NOT_WRITTEN)
    os.replace(temporary, path)


# -- E129 (d): the ResInsight target (strategy rev 3, D1-D4) -------------------------------------------------------------

RI_IMPORT, RI_RESULT = 'targets/resinsight/import.py', 'targets/resinsight/result.json'
RI_RELEASE, RIPS_RELEASE = '2026.09.0', '2026.9.0.2'  # D1: the measured pair (the Connectors' resinsight extra pins rips)
RI_VERSION = '%s (rips %s)' % (RI_RELEASE, RIPS_RELEASE)
CUBE_LINE = 'cube: false; wells and logs only (rips %s has no SEG-Y import)' % RIPS_RELEASE  # D2: the entry's first compared line
LINES_LINE = 'lines: not placed; rips %s has no seismic API' % RIPS_RELEASE  # E137 s1 D-4 (R1-15, R1-18): beside CUBE_LINE for a pack with lines
FAULTS_LINE = 'faults: not placed; rips %s has no fault-stick import' % RIPS_RELEASE  # E137 s2 D-8: after LINES_LINE for a pack with faults
TD_LINE = 'Time-depth models: not placed; this starter does not import time-depth models into ResInsight'  # E137 s3 D-8 (R2-12): after FAULTS_LINE
ORACLE_RESINSIGHT = {'compared': [CUBE_LINE, 'nothing yet: the pack has not been imported into ResInsight and compared (ophiolite starter resinsight)'],
                     'values': 0, 'differences': 0, 'seed': 0}
NO_PATHS = 'The ResInsight target reads well paths; this export has none.'
RI_LINES = "\nThe pack's 2D lines are not imported: ResInsight cannot import seismic lines in this version."  # E137 s1 R1-19
RI_FAULTS = "\nThis version of ResInsight cannot import fault sticks; the pack's faults are not imported."  # E137 s2 D-8
RI_TD = "\nThis starter does not import time-depth models into ResInsight; the pack's time-depth models are not imported."  # E137 s3 D-8
NO_CONNECTORS = ('Run this import with a Python that has the Connectors package and its resinsight extra installed '
                 '(pip install "arraybridge-connectors[resinsight]"); nothing was imported.')
RI_CHANGED = '%s is not the file this pack names: its SHA-256 differs; nothing was imported.'


def resinsight_import(defn, files, lines=False, faults=False, models=False):
    """D4's launcher (`targets/resinsight/import.py`), text like `opendtect_import`: the pack's id and its well files
    {path: {sha256, bytes, kind, object}}. It parses its arguments, checks every embedded file's digest before anything
    else (R2-8: no `rips` import before), then hands the import to `asset_connectors.resinsight_starter.run` (R2-5), which
    owns the ResInsight process, the project folder and every `rips` call. The SDK never imports `rips` or the module.
    E137 s1 D-4 (R1-19): for a pack with LINES the text says they are not imported; other packs keep their bytes. E137 s2
    D-8: so for a pack with FAULTS; E137 s3 D-8: and with time-depth MODELS."""
    return ('"""Starter pack %s: the ResInsight import.\n\nReads the pack\'s well paths (wells/<well>-positions.csv) and logs '
            '(wells/<well>.las) and saves them as a new ResInsight\nproject in PROJECT_OUT. The seismic cube is not imported: '
            'ResInsight\'s Python API cannot import SEG-Y in this version.%s\nRun it with a Python that has the Connectors package '
            'and its resinsight extra installed, from any folder:\n\n    python PACK/files/targets/resinsight/import.py PACK '
            'PROJECT_OUT [--port N | --resinsight EXE]\n\nPACK is the folder holding starter.json and files/; PROJECT_OUT is '
            'relative to the working folder and must be absent,\nempty, or a folder this launcher wrote for this pack. Without '
            '--port it starts ResInsight %s (EXE, or\nRESINSIGHT_EXECUTABLE) with its Python server and stops it at the end; '
            '--port N uses a ResInsight you started\nyourself with an empty project."""\nimport argparse\nimport hashlib\n'
            'import json\nimport sys\nfrom pathlib import Path\n\nPACK = %r\nFILES = %r\n\n\ndef digest(path):\n'
            '    h, size = hashlib.sha256(), 0\n    with open(path, \'rb\') as f:\n'
            "        for block in iter(lambda: f.read(1 << 20), b''):\n            h.update(block); size += len(block)\n"
            '    return h.hexdigest(), size\n\n\ndef main(argv):\n'
            "    p = argparse.ArgumentParser(prog='python import.py', description='Save this starter pack\\'s well paths and logs as a new ResInsight project.')\n"
            "    p.add_argument('pack', help='the pack folder: starter.json and files/')\n"
            "    p.add_argument('project_out', help='the new project folder (relative to the working folder)')\n"
            '    server = p.add_mutually_exclusive_group()\n'
            "    server.add_argument('--port', type=int, help='a running ResInsight with its Python server on this port and an empty project')\n"
            "    server.add_argument('--resinsight', help='the ResInsight executable to start (default: RESINSIGHT_EXECUTABLE)')\n"
            "    p.add_argument('--json', action='store_true', help='print the outcome as one JSON line')\n"
            '    args = p.parse_args(argv)\n    pack = Path(args.pack).resolve()\n'
            '    for path, f in sorted(FILES.items()):  # every file first, before rips is imported\n'
            "        local = pack / 'files' / path\n"
            "        try: same = local.is_file() and not local.is_symlink() and digest(local) == (f['sha256'], f['bytes'])\n"
            '        except OSError: same = False\n'
            '        if not same:\n            print(%r %% path, file=sys.stderr)\n            return 2\n'
            '    try: from asset_connectors import resinsight_starter\n'
            '    except ImportError:\n        print(%r, file=sys.stderr)\n        return 2\n'
            '    try: outcome = resinsight_starter.run(pack, Path(args.project_out).resolve(), pack_id=PACK, files=FILES, port=args.port, executable=args.resinsight)\n'
            '    except resinsight_starter.Refused as refusal:\n        print(str(refusal), file=sys.stderr)\n        return 2\n'
            '    print(json.dumps(outcome, sort_keys=True) if args.json else resinsight_starter.said(outcome))\n    return 0\n\n\n'
            "if __name__ == '__main__':\n    sys.exit(main(sys.argv[1:]))\n"
            % (defn['id'], (RI_LINES if lines else '') + (RI_FAULTS if faults else '') + (RI_TD if models else ''), RI_RELEASE, defn['id'], files, RI_CHANGED, NO_CONNECTORS)).encode('utf-8')


def resinsight_files(derived):
    """D4: the derived files the ResInsight target reads ({path: {sha256, bytes, kind, object}}, every positions and LAS
    file in path order), refused when the export holds no well path (D3)."""
    wells = sorted((d for d in derived if d['kind'] in ('wellbore-paths', 'wellbore-logs')), key=lambda d: d['path'])
    if not any(d['kind'] == 'wellbore-paths' for d in wells): refuse(NO_PATHS + NOT_WRITTEN)
    return {d['path']: {'sha256': d['sha256'], 'bytes': d['bytes'], 'kind': d['kind'], 'object': d['object']} for d in wells}


def archived(definition_path, out, catalogue, verification, custody):
    """E129 sc (D1-D4, D6): everything `build` decides for an archive pack before anything is sent: the sb definition and
    its evidence, the export at OUT and its derived files, their profiles and declarations, the OpendTect target's
    artefacts and the pack document. Refused with nothing sent."""
    from . import starter_archive
    defn = starter_archive.definition(definition_path)
    raw_definition = Path(definition_path).read_bytes()
    read = {}
    evidence, _ = starter_archive.evidence(defn, catalogue, verification, custody, read)
    archive = defn['inputs'][0]
    report, report_raw, folder = exported(out, defn, raw_definition)
    starter_archive.agreed(defn, report)  # D4: the decisions say what the export's survey says
    derived = inventory(report, folder, archive, Path(out))
    wells = resinsight_files(derived) if 'resinsight' in defn['targets'] else None  # E129 (d) D3: refused before anything else
    declared = declarations(report['survey'], {d['kind'] for d in derived})
    def own(d):  # E137 s3 D-3: a time-depth model is declared by its own well's decisions, every other kind per kind
        return starter_archive.time_depth_declared(defn['values'], d['object']) if d['kind'] == 'time-depth' else dict(declared[d['kind']])
    landings, lines = [], {}  # E137 s1 D-4 (D84): per dataset, how many of its lines the pack holds
    for d in derived:
        if d['kind'] == 'seismic-2d': lines[d['object'].partition('/')[0]] = lines.get(d['object'].partition('/')[0], 0) + 1
    for d in derived:
        ds = d['object'].partition('/')[0] if d['kind'] == 'seismic-2d' else None
        # B5: a horizon's nodes, compared at build with the deployment's M (E139); over it is recorded, never uploaded
        landings.append({'name': d['path'], 'path': d['local'], 'sha256': d['sha256'], 'profile': EXPORT_PROFILE[d['kind']], 'declared': own(d),
                         'kind': d['kind'], 'from': d['from'], **({'nodes': nodes(d['local'])} if d['kind'] == 'horizons' else {}),
                         **({'lines': {'field': LINES_OF % ds, 'unit': None, 'value': '%d of %d' % (lines[ds], d['of'])}} if ds else {})})
    sources = licences(defn, evidence)
    lic = computed_licence(sources)
    placed = {d['path']: {'kind': d['kind'], 'object': d['object'], 'declared': own(d)} for d in derived}
    not_read = [{k: n.get(k) for k in ('kind', 'name', 'reason')} for n in report.get('not_read') or [] if isinstance(n, dict)]
    files = {OPENDTECT_IMPORT: opendtect_import(defn, placed, not_read), ATTRIBUTION: attribution(defn, sources, evidence)}
    # E129 sc C3b: each derived file is also an artefact, at its one path (derived[] path = files/ path), which import.py reads
    artefacts = [{'path': p, 'sha256': sha256(raw), 'bytes': len(raw)} for p, raw in files.items()] + [
        {'path': d['path'], 'sha256': d['sha256'], 'bytes': d['bytes']} for d in derived]
    distinct(artefacts, defn['inputs'], ' Nothing was written.', derived=derived)
    targets = [{'application': 'opendtect', 'version': OPENDTECT_RELEASE, 'artefacts': artefacts, 'import': OPENDTECT_IMPORT, 'oracle': ORACLE_OPENDTECT}]
    if 'python' in defn['targets']:  # E129 (e) D4: the pack notebook, its expected values and the derived files it reads
        made = python_files(derived)
        reads = ({made[1]['cube']} - {None}) | {w['positions'] for w in made[1]['wells']} | {w['las'] for w in made[1]['wells'] if w['las']} \
            | {line['path'] for line in made[1].get('lines', [])} | {m['path'] for m in made[1].get('time_depth', [])}  # E137 s1 D-4: lines, no cube; E137 s3 R2-3: models
        own = [{'path': p, 'sha256': sha256(raw), 'bytes': len(raw)} for p, raw in made[0].items()] + [
            {'path': d['path'], 'sha256': d['sha256'], 'bytes': d['bytes']} for d in derived if d['path'] in reads]
        distinct(own, defn['inputs'], ' Nothing was written.', derived=derived)
        targets.append({'application': 'python', 'version': platform.python_version(), 'artefacts': own, 'import': PY_IMPORT,
                        'oracle': python_waiting(any(d['kind'] == 'faults' for d in derived))})
        files.update(made[0])
    if wells is not None:  # E129 (d) D2-D4: the launcher and the well files it reads, at their one path; wells and logs only
        lined, faulted, modelled = (any(d['kind'] == k for d in derived) for k in ('seismic-2d', 'faults', 'time-depth'))
        launcher = resinsight_import(defn, wells, lined, faulted, modelled)
        own = [{'path': RI_IMPORT, 'sha256': sha256(launcher), 'bytes': len(launcher)}] + [
            {'path': d['path'], 'sha256': d['sha256'], 'bytes': d['bytes']} for d in derived if d['path'] in wells]
        distinct(own, defn['inputs'], ' Nothing was written.', derived=derived)
        targets.append({'application': 'resinsight', 'version': RI_VERSION, 'artefacts': own, 'import': RI_IMPORT, 'oracle': resinsight_waiting(lined, faulted, modelled)})
        files[RI_IMPORT] = launcher
    across(targets, derived, ' Nothing was written.')
    # rule (e) subjects are contents objects or `pack`: the archive's one decision (its log step) is the pack's
    decided = [dict(d, subject='pack') if d['subject'] == archive['name'] else d for d in defn['decisions']]
    used = {**tools(), **({'resinsight': RI_RELEASE, 'rips': RIPS_RELEASE} if wells is not None else {})}  # D1: both, for a ResInsight pack only
    doc = {'format': STARTER, 'id': defn['id'], 'record_id': defn['record_id'], 'title': defn['title'], 'summary': defn['summary'], 'unpublished': True,
           'recipe': {**defn['recipe'], 'tools': used}, 'contents': defn['contents'],
           'inputs': [{k: archive[k] for k in ('name', 'sha256', 'bytes', 'held')}],
           'derived': [{k: d[k] for k in ('path', 'sha256', 'bytes', 'from', 'how')} for d in derived], 'decisions': decided,
           'targets': targets,
           'licence': {**lic, 'sources': sources}, 'fidelity': 'fidelity/%s.json' % stem(defn['id']), 'built_at': defn['built_at']}
    bound_export = {'report': sha256(report_raw), 'definition': report['definition'], 'derived': [[d['path'], d['sha256']] for d in derived]}
    return {'defn': defn, 'raw_definition': raw_definition, 'evidence': evidence, 'read': read, 'files': files, 'doc': doc, 'landings': landings,
            'export': bound_export, 'copies': [(d['path'], d['local'], d['sha256'], d['bytes']) for d in derived]}


def build(client, definition_path, out, *, catalogue, verification, custody, export=None):
    """`ophiolite starter build`: land the inputs, then write OUT/starter.json (unpublished, no keys), its fidelity document
    and the python target under OUT/files/. A rerun with the same OUT continues from landing.json (D7). E129 sc: with
    EXPORT (the folder `ophiolite starter export` wrote) the definition is an archive's, and its derived files are landed
    instead, with the OpendTect target. Returns the pack document."""
    from . import fidelity
    from .upload_runs import UploadRuns
    p = prepared(definition_path, catalogue, verification, custody) if export is None else archived(definition_path, export, catalogue, verification, custody)
    defn, doc, out = p['defn'], p['doc'], Path(out)
    evidence_raw = dumped(p['evidence'])
    bindings = {'url': client.url, 'project': client.project, 'definition': sha256(p['raw_definition']), 'evidence.json': sha256(evidence_raw), 'evidence': p['read'],
                **({'export': p['export']} if p['export'] is not None else {})}
    journal_path = out / 'landing.json'
    if journal_path.exists():
        try: journal = json.loads(journal_path.read_bytes())
        except ValueError: refuse('landing.json in %s is not JSON; build in a new folder.' % out.name + NOT_WRITTEN)
        before = journal.get('bindings') or {}
        for key, said in (('url', 'The gateway URL'), ('project', 'The project'), ('definition', 'The pack definition'), ('evidence.json', 'The evidence'),
                          ('export', 'The export')):  # D3: the export by content (report, definition, inventory), never by its folder
            if before.get(key) != bindings.get(key): refuse(BINDING % said + NOT_WRITTEN)
        for path in sorted(set(before.get('evidence') or {}) | set(bindings['evidence'])):
            if (before.get('evidence') or {}).get(path) != bindings['evidence'].get(path): refuse(BINDING % ('The evidence file %s' % Path(path).name) + NOT_WRITTEN)
    else:
        journal = {'format': LANDING, 'bindings': bindings, 'inputs': {}}
    replaced(out / 'evidence.json', evidence_raw)
    def save(): replaced(journal_path, dumped(journal))
    save()
    runs, entries = UploadRuns(client), []
    limit = horizon_nodes(client) if any('nodes' in i for i in p['landings']) else None  # E139: M, read once
    for i in p['landings']:
        name, path, prof, sent = i['name'], i['path'], i['profile'], i['declared']
        if 'nodes' in i and i['nodes'] > limit:  # E129 sc (B5): not uploaded; its row says why, with M (E139)
            entries.append({'sha256': i['sha256'], 'name': name, 'result': 'failed', 'reason': TOO_MANY_NODES.format(limit)})
            continue
        landed = sum(e['state'] == 'landed' for e in journal['inputs'].values())
        entry = journal['inputs'].get(name)
        try:
            if entry and entry['state'] == 'landed':
                current(client, name, entry['asset_id'], entry['revision'])
            else:
                row = None
                if entry and entry['state'] == 'started':  # D7: read the original run; never send the file again to learn its result
                    report = runs.status(entry['run_id'])
                    if report.state == 'open': report = runs.send(entry['run_id'], runs.open(str(path)))
                    row = outcome(report, i, refuse_open=False)
                if row is None:
                    def started(run_id):
                        journal['inputs'][name] = {'state': 'started', 'run_id': run_id}; save()
                    report = runs.upload(str(path), attribution=statement(doc), rights_confirmed=True, audience='me',
                                         declare={prof: sent} if sent else None, source_name=defn['id'], started=started)
                    row = outcome(report, i)
                    recovered = False
                else:
                    recovered = True
                if (row.get('declared') or {}) != {k: str(v) for k, v in sent.items()}:
                    refuse('%s was landed with the declarations %s, not the ones sent (%s).' % (name, json.dumps(row.get('declared') or {}, sort_keys=True), json.dumps(sent, sort_keys=True)) + NOT_WRITTEN)
                compare = read_back(name, path, sent.get('z_unit')) if 'nodes' in i else None  # E139 s2 (S2-12)
                content, output, values = fidelity.landed(client, name, row['asset_id'], row['revision'], i['sha256'], compare=compare)
                if recovered: current(client, name, row['asset_id'], row['revision'])
                entry = {'state': 'landed', 'run_id': report.run_id, 'asset_id': row['asset_id'], 'revision': row['revision'], 'profile': prof,
                         'output': {**output, 'kind': i['kind']}, **({'from': i['from']} if 'from' in i else {}), **({'representative': values} if values else {})}
                journal['inputs'][name] = entry; save()
        except PermissionRefused:
            raise PermissionRefused(DENIED % (client.project, name, landed, len(p['landings']))) from None
        shown = (entry.get('representative') or []) + ([i['lines']] if 'lines' in i else [])  # E137 s1 D-4: a line's "N of M" last
        entries.append({'sha256': i['sha256'], 'name': name, 'result': 'converted', 'output': entry['output'],
                        **({'representative': shown} if shown else {})})
    replaced(out / doc['fidelity'], dumped(fidelity.written(p['evidence']['catalog'], defn['record_id'], entries)))
    for rel, raw in p['files'].items(): replaced(out / 'files' / rel, raw)
    for rel, local, digest, size in p.get('copies', ()): copied(local, out / 'files' / rel, digest, size)  # E129 sc C3b: the artefact at its one path
    replaced(out / 'starter.json', dumped(doc))
    return doc


def statement(doc):
    """The attribution an upload carries: the pack licence's statement, or else its name."""
    return doc['licence'].get('statement') or doc['licence']['name']


def outcome(report, i, refuse_open=True):
    """The one row of input I's upload once it landed (D4); None for a closed run that landed nothing, when recovering."""
    rows = [r for r in report.items if r.get('role') == 'primary']
    row = rows[0] if len(rows) == 1 else None
    if report.state == 'closed' and row is not None and row['state'] in LANDED_STATES and row.get('asset_id') and row.get('revision'):
        if row.get('sha256') not in (None, i['sha256']): refuse('%s was landed with other bytes than the definition names.' % i['name'] + NOT_WRITTEN)
        return row
    if not refuse_open and report.state != 'open': return None
    said = (row or {}).get('sentence') or 'the upload %s' % report.label
    refuse('%s was not landed: %s.' % (i['name'], said.rstrip('.')) + NOT_WRITTEN)


def current(client, name, asset, revision):
    """D7: a pinned revision must still be the asset's current one; a moved one is a conflict (exit 4)."""
    from . import fidelity
    summary = fidelity.find(client, asset)
    if summary is None or summary.get('revision') != revision: raise IntegrityConflict(MOVED % name)


def shaped(doc):
    """The pack document `build` writes, in the shape the pinned schema states (checked again by OSD's own validate)."""
    def bad(): refuse('starter.json is not a pack document ophiolite starter build wrote.' + UNCHANGED)
    if not isinstance(doc, dict) or doc.get('format') != STARTER or doc.get('unpublished') is not True: bad()
    if set(doc) != {'format', 'id', 'record_id', 'title', 'summary', 'unpublished', 'recipe', 'contents', 'inputs', 'derived', 'decisions', 'targets', 'licence', 'fidelity', 'built_at'}: bad()
    targets = doc['targets']  # E129 (e) D4, (d) D3: one target per application, OpendTect, Python and ResInsight of an archive at most
    if not isinstance(targets, list) or not 1 <= len(targets) <= 3 or not all(isinstance(t, dict) and isinstance(t.get('artefacts'), list) for t in targets) \
            or len({t.get('application') for t in targets}) != len(targets): bad()
    for a in (a for t in targets for a in t['artefacts']):
        if not isinstance(a, dict) or not {'path', 'sha256', 'bytes'} <= set(a) <= {'path', 'sha256', 'bytes', 'key'} or not isinstance(a['path'], str) \
                or not all(SEGMENT.fullmatch(s) for s in a['path'].split('/')) or not isinstance(a['sha256'], str) or not SHA256.fullmatch(a['sha256']): bad()
    if not isinstance(doc['fidelity'], str) or not re.fullmatch(r'fidelity/[A-Za-z0-9_-][A-Za-z0-9._-]*\.json', doc['fidelity']): bad()
    if not isinstance(doc['inputs'], list) or not all(isinstance(i, dict) and set(i) == {'name', 'sha256', 'bytes', 'held'} for i in doc['inputs']): bad()


def finalise(out, custody):
    """`ophiolite starter finalise OUT --custody DIR` (offline, D6): each artefact's key from its held `derived` custody
    document, after the pack is checked again against the evidence it was built from and the custody documents now.
    Writes every key at once, by rename; any refusal leaves starter.json byte-identical. Returns the pack document."""
    out, custody = Path(out), Path(custody)
    try: landing = json.loads((out / 'landing.json').read_bytes()); evidence_raw = (out / 'evidence.json').read_bytes(); before = (out / 'starter.json').read_bytes()
    except (OSError, ValueError): refuse('%s is not a folder ophiolite starter build finished: landing.json, evidence.json or starter.json is missing.' % out.name + UNCHANGED)
    if sha256(evidence_raw) != (landing.get('bindings') or {}).get('evidence.json'): refuse('evidence.json is not the evidence this pack was built from: its SHA-256 differs.' + UNCHANGED)
    evidence = json.loads(evidence_raw)
    try: doc = json.loads(before)
    except ValueError: refuse('starter.json is not JSON.' + UNCHANGED)
    shaped(doc)
    across(doc['targets'], doc.get('derived') or [], UNCHANGED)
    if not_compared(doc): refuse(NOT_COMPARED % doc['id'] + UNCHANGED)  # E129 sc D6: the import runs and is compared before keys
    differs = opendtect_differences(doc)
    if differs: refuse(DIFFERS % (doc['id'], differs) + UNCHANGED)  # E129 (f) R2-1: and it compared without a difference
    if not_run(doc): refuse(NOT_RUN % doc['id'] + UNCHANGED)  # E129 (e) D4: so does the pack notebook
    if not_imported(doc): refuse(NOT_IMPORTED % doc['id'] + UNCHANGED)  # E129 (d) A6: and the ResInsight import and its read-back
    for i in doc['inputs']: held(i, evidence, UNCHANGED)  # rule (b), against the evidence build judged
    sources = licences(doc, evidence)
    if {**computed_licence(sources, UNCHANGED), 'sources': sources} != doc['licence']: refuse('The pack licence is not the one its inputs\' evidence gives.' + UNCHANGED)  # rule (d)
    complete(doc, UNCHANGED)  # rule (e)
    for t in doc['targets']: distinct(t['artefacts'], doc['inputs'], UNCHANGED, derived=doc.get('derived') or [])
    every = [a for t in doc['targets'] for a in t['artefacts']]
    first = {}
    for a in every: first.setdefault(a['path'], a)
    artefacts = list(first.values())  # each path once, in the order first listed
    for a in artefacts:
        if artefact_digest(out, a['path']) != (a['sha256'], a['bytes']): refuse('artefact %s: the file in files/ is not the one starter.json names.' % a['path'] + UNCHANGED)
    fidelity_of(doc, out)
    for i in doc['inputs']:  # O2: every deposit against the custody documents now; a tombstone wins
        if i['held']['as'] != 'deposited': continue
        now, _ = custody_document(custody, i['sha256'], 'input %s' % i['name'], UNCHANGED)
        then = evidence['deposits'][i['name']]
        for field in ('key', 'record_id', 'bytes', 'licence'):
            if now.get(field) != then.get(field): refuse('input %s: its custody document\'s %s differs from the one this pack was built with.' % (i['name'], field) + UNCHANGED)
        if provenance(now) != 'deposit': refuse('input %s: custody key %s is a %s copy, not a deposit.' % (i['name'], now['key'], provenance(now)) + UNCHANGED)
    keys = []
    for a in artefacts:  # rule (f): the key is read from the held derived document with that digest, never computed
        what = 'artefact %s' % a['path']
        d, _ = custody_document(custody, a['sha256'], what, UNCHANGED)
        if provenance(d) != 'derived': refuse('%s: custody key %s is a %s copy of %s, not an artefact of %s.' % (what, d['key'], provenance(d), d['record_id'], doc['id']) + UNCHANGED)
        if d['derived'].get('pack_id') != doc['id']: refuse('%s: custody key %s is an artefact of %s, not %s.' % (what, d['key'], d['derived'].get('pack_id'), doc['id']) + UNCHANGED)
        if d['record_id'] != doc['record_id']: refuse('%s: custody key %s holds a file of record %s, not %s.' % (what, d['key'], d['record_id'], doc['record_id']) + UNCHANGED)
        if d['bytes'] != a['bytes']: refuse('%s: bytes %d, its custody document states %d.' % (what, a['bytes'], d['bytes']) + UNCHANGED)
        keys.append(d['key'])
    keyed = {a['path']: key for a, key in zip(artefacts, keys)}
    for a in every: a['key'] = keyed[a['path']]  # every occurrence of a shared path carries its one key
    raw = dumped(doc)
    if raw != before: replaced(out / 'starter.json', raw)
    return doc


def fidelity_of(doc, out):
    """O1: the fidelity document starter.json names, checked as OSD's `_fidelity` checks it (starters.py)."""
    from . import fidelity
    what = 'fidelity %s' % doc['fidelity']
    try: raw = (out / doc['fidelity']).read_bytes()
    except OSError: refuse('%s: not found in %s.' % (what, out.name) + UNCHANGED)
    try: fd = json.loads(raw)
    except ValueError: refuse('%s: not JSON.' % what + UNCHANGED)
    try:
        if not isinstance(fd, dict) or fd.get('format') != fidelity.FORMAT or set(fd) != {'format', 'catalog', 'record', 'inputs'}: raise Refused('')
        if fidelity.written(fd['catalog'], fd['record'], fd['inputs']) != fd: raise Refused('')
    except Refused: refuse('%s: not a fidelity/1 document.' % what + UNCHANGED)
    if fd['record'] != doc['record_id']: refuse('%s: record %s, the pack is of %s.' % (what, fd['record'], doc['record_id']) + UNCHANGED)
    pack = {i['sha256']: i['name'] for i in doc['inputs']}
    results = {i['sha256']: i for i in fd['inputs']}
    kinds = {c['kind'] for c in doc['contents']}
    derived = {d['sha256'] for d in doc['derived']}
    for sha, name in pack.items():  # OSD rule (h): an input the recipe expanded (an archive) may be covered by its derived files
        if sha in results: continue
        own = [d['path'] for d in doc['derived'] if d['from'] == sha]
        if not own: refuse('%s: no result for input %s.' % (what, name) + UNCHANGED)
        missing = [d['path'] for d in doc['derived'] if d['from'] == sha and d['sha256'] not in results]
        if missing: refuse('%s: no result for input %s nor for its derived %s.' % (what, name, ', '.join(missing)) + UNCHANGED)
    for sha, i in results.items():
        if sha not in pack and sha not in derived: refuse('%s: input %s is not a pack input or derived file.' % (what, i['name']) + UNCHANGED)
        if i['result'] == 'failed' and sha in derived and sha not in pack: continue  # E129 sc (B5): a derived file not landed, with its reason (fidelity/1)
        if i['result'] not in ('converted', 'partial'): refuse('%s: input %s is %s.' % (what, i['name'], i['result']) + UNCHANGED)
        if i['output']['kind'] not in kinds: refuse('%s: input %s became %s, not a contents kind.' % (what, i['name'], i['output']['kind']) + UNCHANGED)


# -- E129 sc C3: the OpendTect target's qualification (strategy rev 3, D6-D8) -------------------------------------------

RESULT = 'targets/opendtect/result.json'
RESULT_FORMAT = 'ophiolite.opendtect-starter-result/1'
OPENDTECT_TIMEOUT = 7200
NOT_COMPARED = ('The OpendTect target of %s has not been imported and compared yet (its oracle says "nothing yet"): run ophiolite starter '
                'opendtect on it first.')
NOT_OPENDTECT = 'starter.json has no OpendTect target; ophiolite starter opendtect compares an archive pack only.' + UNCHANGED
NO_PYTHON = 'Name the OpendTect connector\'s Python: --opendtect-python PY or OPHIOLITE_OPENDTECT_PYTHON.' + UNCHANGED
IMPORT_REFUSED = 'The import refused: %s' + UNCHANGED
IMPORT_STOPPED = 'The import stopped (exit status %d): %s' + UNCHANGED
IMPORT_TIMEOUT = 'The import did not finish within %d seconds.' + UNCHANGED
IMPORT_NOT_STARTED = 'The OpendTect connector interpreter %s cannot be started.' + UNCHANGED
NOT_READ_BACK = '%s was placed as “%s” but is not read back as this pack\'s object; run ophiolite starter opendtect again.' + UNCHANGED
LANDED_OTHER = '%s: the project\'s item %s at %s does not hold the pack\'s file (its SHA-256 differs).' + UNCHANGED
LANDED_UNREAD = '%s: the project\'s item %s at %s could not be read from this server.' + UNCHANGED
RESULT_NOT_NAMED = ('files/%s is the result starter.json names, but the oracle there is not the one it gives; build the pack again in a new '
                    'folder.' % RESULT) + UNCHANGED
RESULT_UNREADABLE = 'files/%s is not a result of this pack; remove it and run ophiolite starter opendtect again.' % RESULT + UNCHANGED
# E129 (f) R2-4: the result says its version; a result without one is the (c) result (version 1), recognised, checked
# against its own oracle and replaced by this version's on the next run
RESULT_VERSION = 2
DIFFERS = 'The OpendTect import of %s differs from the pack in %d places; run ophiolite starter opendtect again after fixing the survey.'  # R2-1
FAILED = ("failed: OpendTect holds something other than the pack's files (%d differences); run ophiolite starter opendtect again after "
          'fixing the survey')  # D6's failed state: the oracle's first line
LINE = 300  # the OSD schema's maxLength of one oracle `compared` line (R2-8 h)
MORE = '… '  # what a continued oracle line starts with


def nothing_yet(t):
    compared = (t.get('oracle') or {}).get('compared') or ['nothing yet']
    return any(isinstance(c, str) and c.startswith('nothing yet') for c in compared)


def not_compared(doc):
    """True for an OpendTect target whose oracle still says nothing yet (D6: finalise refuses it)."""
    return any(t.get('application') == 'opendtect' and nothing_yet(t) for t in doc['targets'])


def not_run(doc):
    """E129 (e) D4: True for an archive pack's Python target (the pack notebook) whose oracle still says nothing yet; a
    wells pack's Python target (open_pack.py) keeps its placeholder oracle (R2-3)."""
    return any(t.get('application') == 'python' and t.get('import') == PY_IMPORT and nothing_yet(t) for t in doc['targets'])


NOT_IMPORTED = ('The ResInsight target of %s has not been imported and compared yet (its oracle says "nothing yet"): run ophiolite starter '
                'resinsight on it first.')


def not_imported(doc):
    """E129 (d) A6: True for a ResInsight target whose oracle still says nothing yet."""
    return any(t.get('application') == 'resinsight' and nothing_yet(t) for t in doc['targets'])


def target_of(doc, application):
    return next((t for t in doc['targets'] if t.get('application') == application), None)


def opendtect_differences(doc):
    """E129 (f) R2-1: the OpendTect target's oracle `differences` (0 without the target or before its comparison)."""
    t = target_of(doc, 'opendtect')
    return ((t or {}).get('oracle') or {}).get('differences') or 0


def bounded(line):
    """R2-8 h: LINE as oracle lines of at most `LINE` characters each, split between words; each continued line starts
    with `MORE` (a word longer than a line is cut)."""
    out = []
    while len(line) > LINE:
        cut = line.rfind(' ', len(MORE) + 1, LINE + 1)
        if cut < 0: cut = LINE  # no space to split at: the word is cut
        out.append(line[:cut])
        line = MORE + line[cut:].lstrip(' ')
    return out + [line]


def label(e):
    """'seismic cube Syn2', 'horizon Top', 'log SYN-C GR', 'well path SYN-C' (V1)."""
    if e['kind'] == 'wellbore-logs' and e.get('curve'): return 'log %s %s' % (e.get('well') or e['object'], e['curve'])
    return '%s %s' % (starter_kinds.label(e['kind']), e['object'])


def _compared_line(e, verb):
    landed = 'item %s at %s' % (e['item'], e['version']) if e.get('item') else 'not landed in Ophiolite'
    if e['kind'] == 'faults':  # E137 s2 D-7 (c): a fault the person imported, read back
        big = e['largest']
        return '%s files/%s (%s) %s OpendTect as “%s”: %d values, %d differences (largest x %g m, y %g m, z %g s)' % (
            starter_kinds.label(e['kind']), e['file'], landed, 'imported by you into' if verb == 'into' else verb, e['object'], e['values'], e['differences'], big['x'], big['y'], big['z'])
    if e['kind'] != 'wellbore-logs':
        return '%s %s (%s) %s OpendTect as “%s”: %d values, %d differences, %d moved' % (
            starter_kinds.label(e['kind']), e['file'], landed, verb, e['object'], e['values'], e['differences'], len(e['moves']))
    r, tags = e['rounded'], e.get('labels') or {}
    relabelled = ''
    if tags.get('stored') and tags['stored'] != tags.get('given'):  # E129 (f) C4: OpendTect labels a log itself
        relabelled = '; OpendTect labels it unit “%s”, mnemonic “%s” (the LAS file: “%s”, “%s”)' % (
            tags['stored']['unit'], tags['stored']['mnemonic'], tags['given']['unit'], tags['given']['mnemonic'])
    return ' '.join(['%s (files/%s, %s) %s OpendTect as “%s”: %d values, %d differences; trimmed %d+%d empty end samples; 32-bit storage '
                     'changed %d depths (max %.3g m) and %d values (max %.3g)%s' % (
                         label(e), e['file'], landed, verb, e['object'], e['values'], e['differences'], e['trimmed'][0], e['trimmed'][1],
                         r['depths']['count'], r['depths']['max'], r['values']['count'], r['values']['max'], relabelled)] + list(e.get('said') or []))


def oracle_of(result):
    """The target's oracle from a version 2 result (D6, E129 (f)): when anything differs, a "failed: …" first line; one
    line per placed object (a log's with its trims and 32-bit roundings), one per recorded object compared but not
    placed by this run (R2-3), one "not placed: …" line per refusal and omission; every line at most `LINE` characters
    (R2-8 h). `values` and `differences` count every compared object."""
    if result.get('version') != RESULT_VERSION: return _oracle_v1(result)
    lines = [FAILED % result['differences']] if result['differences'] else []
    for e in result['placed']: lines += bounded(_compared_line(e, 'into'))
    for e in result['compared']: lines += bounded(_compared_line(e, 'compared in'))
    for n in result['not_placed']: lines += bounded('not placed: %s: %s' % (label(n), n['reason']))
    every = result['placed'] + result['compared']
    return {'compared': lines, 'values': sum(e['values'] for e in every), 'differences': result['differences'], 'seed': 0}


def _oracle_v1(result):
    """The (c) oracle of a version 1 result, frozen (R2-4): what `oracle_of` gave before E129 (f)."""
    lines = []
    for p in result['placed']:
        landed = 'item %s at %s' % (p['item'], p['version']) if p['item'] else 'not landed in Ophiolite'
        lines.append('%s %s (%s) into OpendTect as “%s”: %d values, %d differences, %d moved'
                     % (p['kind'], p['file'], landed, p['object'], p['values'], p['differences'], len(p['moves'])))
    lines += ['not placed: %s %s: %s' % (n['kind'], n['object'], n['reason']) for n in result['not_placed']]
    return {'compared': lines, 'values': sum(p['values'] for p in result['placed']), 'differences': sum(p['differences'] for p in result['placed']), 'seed': 0}


V1_KEYS = {'format', 'pack', 'survey', 'placed', 'not_placed', 'ticket'}
V1_PLACED = {'kind', 'file', 'item', 'version', 'object', 'digest', 'values', 'differences', 'moves'}
V2_KEYS = {'format', 'version', 'pack', 'survey', 'placed', 'compared', 'not_placed', 'differences'}


def _result_shaped(result):
    """R2-4: True for a version 1 result of the (c) shape or a version 2 result of this one."""
    def rows(v, keys=None, at_least=frozenset()):
        return isinstance(v, list) and all(isinstance(e, dict) and (set(e) == keys if keys else set(e) >= at_least) for e in v)
    if 'version' not in result:
        return set(result) == V1_KEYS and rows(result['placed'], V1_PLACED) and rows(result['not_placed'], {'kind', 'object', 'reason'})
    return (set(result) == V2_KEYS and result['version'] == RESULT_VERSION and isinstance(result['differences'], int)
            and rows(result['placed'], at_least={'kind', 'file', 'object', 'values', 'differences', 'moves'})
            and rows(result['compared'], at_least={'kind', 'file', 'object', 'values', 'differences', 'moves'})
            and rows(result['not_placed'], at_least={'kind', 'object', 'reason'}))


def _connector(python, argv, timeout):
    """One run of the pack's import.py in the connector's interpreter: its JSON line, or the import's refusal."""
    try: done = subprocess.run([python] + argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except OSError: refuse(IMPORT_NOT_STARTED % python)
    except subprocess.TimeoutExpired: refuse(IMPORT_TIMEOUT % timeout)
    last = (done.stderr.strip().splitlines() or ['(nothing on stderr)'])[-1]
    if done.returncode == 2: refuse(IMPORT_REFUSED % last)
    if done.returncode != 0: refuse(IMPORT_STOPPED % (done.returncode, last))
    try: return json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError): refuse(IMPORT_STOPPED % (0, 'it printed no outcome'))


def _held_result(out, doc):
    """D6 (B4) on a resume: the result file and starter.json checked against each other. Returns the result's bytes on
    disk, or None. A result starter.json names with its bytes must give starter.json's oracle; a result file not named
    (or named with other bytes: a run stopped between the two writes) is replaced by this run's. E129 (f) R2-4: a result
    without a version is the (c) result: checked against its (c) shape and the frozen (c) oracle, then replaced."""
    try: raw = (out / 'files' / RESULT).read_bytes()
    except FileNotFoundError: return None
    except OSError: refuse(RESULT_UNREADABLE)
    try: result = json.loads(raw)
    except ValueError: refuse(RESULT_UNREADABLE)
    if not isinstance(result, dict) or result.get('format') != RESULT_FORMAT or result.get('pack') != doc['id']: refuse(RESULT_UNREADABLE)
    if not _result_shaped(result): refuse(RESULT_UNREADABLE)
    t = target_of(doc, 'opendtect')
    named = next((a for a in t['artefacts'] if a['path'] == RESULT), None)
    if named and (named['sha256'], named['bytes']) == (sha256(raw), len(raw)):
        try: given = oracle_of(result)
        except (KeyError, TypeError): refuse(RESULT_UNREADABLE)
        if t.get('oracle') != given: refuse(RESULT_NOT_NAMED)
    return raw


def opendtect(client, out, survey, *, python=None, timeout=OPENDTECT_TIMEOUT):
    """`ophiolite starter opendtect OUT --survey ROOT/NAME` (D6, maintainer only): run the pack's import.py into the
    survey, read every placed object back through the connector and compare it with the pack's file, whose bytes are
    the landed item's at its pinned version (its provenance, every run); write `files/targets/opendtect/result.json`
    first, then starter.json with the result artefact and the oracle, by rename. The comparison is made again on every
    run, so a run after an interruption gives the same bytes; a completed rerun changes nothing. Returns (doc, result).

    E129 (f): the comparison is keyed by (file, curve), so one LAS file gives one placed entry per curve, each landed
    file's provenance read once; every recorded object the comparison reads is in the result, placed this run or not
    (R2-3), and `differences` counts them all. A result with differences is still written, and its oracle starts with
    the failed line, which `finalise` refuses (D6, R2-1)."""
    out = Path(out)
    python = python or os.environ.get('OPHIOLITE_OPENDTECT_PYTHON')
    if not python: refuse(NO_PYTHON)
    try: landing = json.loads((out / 'landing.json').read_bytes()); before = (out / 'starter.json').read_bytes()
    except (OSError, ValueError): refuse('%s is not a folder ophiolite starter build finished: landing.json or starter.json is missing.' % out.name + UNCHANGED)
    try: doc = json.loads(before)
    except ValueError: refuse('starter.json is not JSON.' + UNCHANGED)
    shaped(doc)
    target = target_of(doc, 'opendtect')
    if target is None or target.get('import') != OPENDTECT_IMPORT: refuse(NOT_OPENDTECT)
    across(doc['targets'], doc.get('derived') or [], UNCHANGED)  # E129 (e) R2-8
    for a in target['artefacts']:
        if a['path'] == RESULT: continue
        if artefact_digest(out, a['path']) != (a['sha256'], a['bytes']): refuse('artefact %s: the file in files/ is not the one starter.json names.' % a['path'] + UNCHANGED)
    held_raw = _held_result(out, doc)
    script = [str(out / 'files' / OPENDTECT_IMPORT), str(out), '--survey', str(survey), '--json']
    imported = _connector(python, script, timeout)
    every = _connector(python, script + ['--compare'], timeout)['compared']
    compared = {(c['file'], c.get('curve')): c for c in every}
    derived = {d['path']: d for d in doc['derived']}
    landed_at = {}

    def landed(path):
        """(item, version) of the landed item holding the pack's file PATH, its provenance read once per file."""
        if path not in landed_at:
            entry = (landing.get('inputs') or {}).get(path)
            item = version = None
            if entry and entry.get('state') == 'landed':  # the landed item at its pinned version holds exactly the pack's file
                item, version = entry['asset_id'], entry['revision']
                try: content = ((client.provenance(item, version).record or {}).get('content') or {}).get('content_sha256')
                except OphioliteError: raise  # as E125's horizon get: a lost permission is the server's own refusal, nothing written
                except Exception: refuse(LANDED_UNREAD % (path, item, version))
                if content != derived[path]['sha256']: refuse(LANDED_OTHER % (path, item, version))
            landed_at[path] = item, version
        return landed_at[path]

    def entry(c):
        item, version = landed(c['file'])
        return {'kind': c['kind'], 'file': c['file'], 'item': item, 'version': version, **{k: v for k, v in c.items() if k not in ('kind', 'file')}}

    placed, seen = [], set()
    for p in imported['placed']:
        key = (p['file'], p.get('curve'))
        c = compared.get(key)
        if c is None or c['object'] != p['name']: refuse(NOT_READ_BACK % (label(p), p['name']))
        seen.add(key)
        placed.append(entry(c))
    rest = [entry(c) for c in every if (c['file'], c.get('curve')) not in seen]  # R2-3: recorded, compared, not placed this run
    result = {'format': RESULT_FORMAT, 'version': RESULT_VERSION, 'pack': doc['id'], 'survey': Path(survey).name, 'placed': placed,
              'compared': rest, 'not_placed': imported['not_placed'], 'differences': sum(e['differences'] for e in placed + rest)}
    raw = dumped(result)
    if raw != held_raw: replaced(out / 'files' / RESULT, raw)  # the result first
    artefact = {'path': RESULT, 'sha256': sha256(raw), 'bytes': len(raw)}
    named = next((a for a in target['artefacts'] if a['path'] == RESULT), None)
    if named is None: target['artefacts'].append(artefact)
    elif (named['sha256'], named['bytes']) != (artefact['sha256'], artefact['bytes']):
        named.clear(); named.update(artefact)  # new bytes: their key, if any, is no longer theirs
    target['oracle'] = oracle_of(result)
    after = dumped(doc)
    if after != before: replaced(out / 'starter.json', after)  # starter.json last
    return doc, result


# -- E129 (e): the Python target's run (strategy rev 3, D3-D5) ---------------------------------------------------------

PY_TIMEOUT = 600
RESULT_KEYS = {'inline', 'samples', 'inline_sum', 'wells', 'without_logs', 'plotted', 'differences'}
NOT_RUN = ('The Python target of %s has not been run yet (its oracle says "nothing yet"): run ophiolite starter python on it first.')
NOT_PYTHON = 'starter.json has no pack notebook target; ophiolite starter python runs the notebook of an archive pack only.' + UNCHANGED
NOTEBOOK_FAILED = 'The pack notebook did not pass: %s' + UNCHANGED
NOTEBOOK_TIMEOUT = 'The pack notebook did not finish within %d seconds.' + UNCHANGED
PY_RESULT_UNREADABLE = 'files/%s is not a result of this pack; remove it and run ophiolite starter python again.' % PY_RESULT + UNCHANGED
PY_RESULT_NOT_NAMED = ('files/%s is the result starter.json names, but the oracle there is not the one it gives; build the pack again in a new '
                       'folder.' % PY_RESULT) + UNCHANGED


def python_oracle(result, faults=False):
    """The Python target's oracle from the notebook's result: what it read and drew, every value compared with
    expected.json (the notebook asserts each; a result it wrote with a difference is never accepted). E137 s2 D-8: for a
    pack with FAULTS, PY_FAULTS_LINE last. E137 s3 D-8: a result with `time_depth` (a pack with models) says each
    model's pairs checked, two values per pair and one count per model."""
    if not RESULT_KEYS <= set(result) or set(result) - RESULT_KEYS - {'lines', 'time_depth'} or result['differences'] != []: raise ValueError('not a passing result')
    cube = result['inline'] is not None  # E137 s1 D-4: a pack of lines may hold no cube
    lines = ['inline %d: %d samples and the inline sum read with segyio' % (result['inline'], len(result['samples']))] if cube else []
    for w in result['wells']:
        logs = '; %d curves from %s to %s read with lasio' % (w['curves'], *w['depth']) if w['curves'] is not None else '; positions only'
        at = 'projected to inline %.2f, crossline %.2f' % (w['inline'], w['crossline']) if w['inline'] is not None else 'not projected (no cube)'
        lines.append('well %s: %s%s' % (w['name'], at, logs))
    for line in result.get('lines', []):
        lines.append('line %s: %d trace numbers, source points, x and y, Z, 3 samples, the sum and the SHA-256 of every sample read with segyio'
                     % (line['object'], line['traces']))
    if cube: lines.append('plotted: the inline image and %d well lines, read back from the figure' % len(result['plotted']['wells']))
    if 'line' in result['plotted']: lines.append('plotted: line %s, read back from the figure' % result['plotted']['line']['object'])
    values = (len(result['samples']) + 1 if cube else 0) + sum((2 if w['inline'] is not None else 0) + (3 if w['curves'] is not None else 0) for w in result['wells']) \
        + sum(4 * line['traces'] + 3 + len(line['samples']) + 2 for line in result.get('lines', [])) \
        + sum(2 * m['pairs'] + 1 for m in result.get('time_depth', []))
    lines += [PY_TD_LINE % (m['well'], m['pairs']) for m in result.get('time_depth', [])]
    return {'compared': lines + ([PY_FAULTS_LINE] if faults else []), 'values': values, 'differences': 0, 'seed': 0}


def _held_python(out, target, faults=False):
    """D5 (R2-4) on a resume, as _held_result: a result starter.json names with its bytes must give starter.json's oracle;
    one not named, or named with other bytes, is replaced by this run's. Returns its bytes on disk, or None."""
    try: raw = (out / 'files' / PY_RESULT).read_bytes()
    except FileNotFoundError: return None
    except OSError: refuse(PY_RESULT_UNREADABLE)
    try: result = json.loads(raw)
    except ValueError: refuse(PY_RESULT_UNREADABLE)
    if not isinstance(result, dict): refuse(PY_RESULT_UNREADABLE)
    named = next((a for a in target['artefacts'] if a['path'] == PY_RESULT), None)
    if named and (named['sha256'], named['bytes']) == (sha256(raw), len(raw)):
        try: given = python_oracle(result, faults)
        except (KeyError, TypeError, ValueError): refuse(PY_RESULT_UNREADABLE)
        if target.get('oracle') != given: refuse(PY_RESULT_NOT_NAMED)
    return raw


def _notebook(out, keep, timeout):
    """D3: the packaged notebook script run with this interpreter in an empty folder (KEEP, or a temporary one), with
    OPHIOLITE_PACK naming OUT and every other OPHIOLITE_* removed. Returns its JSON."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}
    env.update(OPHIOLITE_PACK=str(Path(out).resolve()), MPLBACKEND='Agg')
    with tempfile.TemporaryDirectory(prefix='starter-python-') as temporary:
        work = Path(keep) if keep else Path(temporary)
        work.mkdir(parents=True, exist_ok=True)
        (work / 'open-a-starter-pack.py').write_bytes((NOTEBOOK / 'open-a-starter-pack.py').read_bytes())
        try: done = subprocess.run([sys.executable, 'open-a-starter-pack.py'], cwd=work, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: refuse(NOTEBOOK_TIMEOUT % timeout)
        if done.returncode != 0: refuse(NOTEBOOK_FAILED % (done.stderr.strip().splitlines() or ['(nothing on stderr)'])[-1])
        try: result = json.loads((work / 'open-a-starter-pack.json').read_bytes())
        except (OSError, ValueError): refuse(NOTEBOOK_FAILED % 'it wrote no open-a-starter-pack.json')
    return result


def python(out, *, keep=None, timeout=PY_TIMEOUT):
    """`ophiolite starter python OUT` (D5, offline): check the Python target's artefacts in files/ against starter.json
    (refused before anything runs), run the pack notebook on the pack folder with the network blocked, then write
    `files/targets/python/result.json` (the notebook's JSON) first and starter.json with the result artefact and the
    oracle last, by rename. A rerun gives the same bytes; the OpendTect target is never touched. Returns (doc, result)."""
    out = Path(out)
    try: before = (out / 'starter.json').read_bytes()
    except OSError: refuse('%s is not a folder ophiolite starter build finished: starter.json is missing.' % out.name + UNCHANGED)
    try: doc = json.loads(before)
    except ValueError: refuse('starter.json is not JSON.' + UNCHANGED)
    shaped(doc)
    target = target_of(doc, 'python')
    if target is None or target.get('import') != PY_IMPORT: refuse(NOT_PYTHON)
    across(doc['targets'], doc.get('derived') or [], UNCHANGED)
    for a in target['artefacts']:
        if a['path'] == PY_RESULT: continue
        if artefact_digest(out, a['path']) != (a['sha256'], a['bytes']): refuse('artefact %s: the file in files/ is not the one starter.json names.' % a['path'] + UNCHANGED)
    held_raw = _held_python(out, target, holds_faults(doc))
    result = _notebook(out, keep, timeout)
    try: oracle = python_oracle(result, holds_faults(doc))
    except (KeyError, TypeError, ValueError): refuse(NOTEBOOK_FAILED % 'its open-a-starter-pack.json is not a passing result')
    raw = dumped(result)
    if raw != held_raw: replaced(out / 'files' / PY_RESULT, raw)  # the result first
    artefact = {'path': PY_RESULT, 'sha256': sha256(raw), 'bytes': len(raw)}
    named = next((a for a in target['artefacts'] if a['path'] == PY_RESULT), None)
    if named is None: target['artefacts'].append(artefact)
    elif (named['sha256'], named['bytes']) != (artefact['sha256'], artefact['bytes']):
        named.clear(); named.update(artefact)  # new bytes: their key, if any, is no longer theirs
    target['oracle'] = oracle
    after = dumped(doc)
    if after != before: replaced(out / 'starter.json', after)  # starter.json last
    return doc, result


# -- E129 (d): the ResInsight target's import and comparison (strategy rev 3, D5, D6) -----------------------------------

RI_TIMEOUT = 1800
RI_RESULT_FORMAT = 'ophiolite.resinsight-starter-result/1'
RI_RESULT_KEYS = {'format', 'cube', 'resinsight', 'rips', 'wells', 'stations', 'samples', 'tolerance_m', 'without_logs', 'reopened', 'differences'}
NOT_RESINSIGHT = 'starter.json has no ResInsight target; ophiolite starter resinsight imports an archive pack only.' + UNCHANGED
NO_RI_PYTHON = ('Name the Python that has the Connectors package and its resinsight extra: --resinsight-python PY or '
                'OPHIOLITE_RESINSIGHT_PYTHON.') + UNCHANGED
RI_NOT_STARTED = 'The Connectors interpreter %s cannot be started.' + UNCHANGED
RI_REFUSED = 'The ResInsight import refused: %s' + UNCHANGED
RI_STOPPED = 'The ResInsight import stopped (exit status %d): %s' + UNCHANGED
RI_TIMED_OUT = 'The ResInsight import did not finish within %d seconds.' + UNCHANGED
RI_DIFFERS = 'ResInsight read the pack back with %d differences; the first: %s' + UNCHANGED
RI_RESULT_UNREADABLE = 'files/%s is not a result of this pack; remove it and run ophiolite starter resinsight again.' % RI_RESULT + UNCHANGED
RI_RESULT_NOT_NAMED = ('files/%s is the result starter.json names, but the oracle there is not the one it gives; build the pack again in a new '
                       'folder.' % RI_RESULT) + UNCHANGED


def metres(v):
    """A tolerance in metres to three significant digits, written without an exponent (0.0000153, not 1.53e-05)."""
    from decimal import Decimal
    return format(Decimal('%.3g' % v), 'f')


def resinsight_waiting(lines, faults=False, models=False):
    """The ResInsight oracle before a comparison: ORACLE_RESINSIGHT, with LINES_LINE after CUBE_LINE for a pack with lines
    and FAULTS_LINE after them for a pack with faults (E137 s2 D-8), then TD_LINE for a pack with models (E137 s3)."""
    if not (lines or faults or models): return ORACLE_RESINSIGHT
    return {**ORACLE_RESINSIGHT, 'compared': [CUBE_LINE, *said_not_placed(lines, faults, models), *ORACLE_RESINSIGHT['compared'][1:]]}


def said_not_placed(lines, faults, models):
    return [*([LINES_LINE] if lines else []), *([FAULTS_LINE] if faults else []), *([TD_LINE] if models else [])]


def holds_lines(doc, kind='seismic-2d'):
    """E137 s1: the pack document derives at least one 2D line file (E137 s2: or one file of KIND)."""
    from . import starter_archive
    folder = starter_archive.FOLDER[kind] + '/'
    return any(isinstance(d, dict) and str(d.get('path', '')).startswith(folder) for d in doc.get('derived') or [])


def holds_faults(doc):
    """E137 s2 D-8: the pack document derives at least one fault file."""
    return holds_lines(doc, 'faults')


def holds_time_depth(doc):
    """E137 s3 D-8 (R2-10): the pack document derives at least one time-depth model, known by its file's name form
    (`wells/` also holds well paths and logs, so the folder says nothing)."""
    return any(isinstance(d, dict) and str(d.get('path', '')).endswith('-time-depth.csv') for d in doc.get('derived') or [])


def resinsight_oracle(result, lines=False, faults=False, models=False):
    """D5: the ResInsight target's oracle from a passing comparison result (no difference, read back again after the
    project was reopened); its first line is D2's. Values: four per station (part a), three coordinates per sample read
    back (part b), one per sampled log value."""
    if set(result) != RI_RESULT_KEYS or result['format'] != RI_RESULT_FORMAT or result['differences'] != 0 or result['reopened'] is not True \
            or result['cube'] is not False:
        raise ValueError('not a passing result')
    wells, tol = result['wells'], result['tolerance_m']
    logs = sum(len(w['logs']) for w in wells)
    said = [CUBE_LINE, *said_not_placed(lines, faults, models),
             "well paths: %d read back at ResInsight's 1 m samples, within x %s m, y %s m, z %s m of the pack's stations interpolated in md"
             % (len(wells), metres(tol['x']), metres(tol['y']), metres(tol['z'])),
             'stations: the %d of the positions files written to the .dev files ResInsight read, each as written; first and last read back '
             'exactly as float32' % result['stations'],
             'logs: %d LAS files on their wells: curves, lengths, null masks and measured depths, then %d values drawn with random.Random(0), '
             'equal as float32; %d well paths without logs' % (logs, result['samples'], len(result['without_logs'])),
             'not seen in what ResInsight holds (it exposes no imported station): a station dropped on the line through its neighbours, or a '
             'bend narrower than the 1 m between two samples',
             'reopened: the same read-back, with no difference, after the project was saved, closed and opened again']
    values = 4 * result['stations'] + 3 * sum(w['samples'] for w in wells) + result['samples']
    return {'compared': said, 'values': values, 'differences': 0, 'seed': 0}


def _held_resinsight(out, target, lines=False, faults=False, models=False):
    """D6 on a resume, as _held_result: a result starter.json names with its bytes must give starter.json's oracle; one
    not named, or named with other bytes (a run stopped between the two writes), is replaced by this run's."""
    try: raw = (out / 'files' / RI_RESULT).read_bytes()
    except FileNotFoundError: return None
    except OSError: refuse(RI_RESULT_UNREADABLE)
    try: result = json.loads(raw)
    except ValueError: refuse(RI_RESULT_UNREADABLE)
    if not isinstance(result, dict) or result.get('format') != RI_RESULT_FORMAT: refuse(RI_RESULT_UNREADABLE)
    named = next((a for a in target['artefacts'] if a['path'] == RI_RESULT), None)
    if named and (named['sha256'], named['bytes']) == (sha256(raw), len(raw)):
        try: given = resinsight_oracle(result, lines, faults, models)
        except (KeyError, TypeError, ValueError): refuse(RI_RESULT_UNREADABLE)
        if target.get('oracle') != given: refuse(RI_RESULT_NOT_NAMED)
    return raw


def _connectors(python, argv, timeout):
    """One run in the Connectors interpreter (the pack's launcher, or the comparison): its last JSON line, or its refusal."""
    try: done = subprocess.run([python] + argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except OSError: refuse(RI_NOT_STARTED % python)
    except subprocess.TimeoutExpired: refuse(RI_TIMED_OUT % timeout)
    last = (done.stderr.strip().splitlines() or ['(nothing on stderr)'])[-1]
    if done.returncode == 2: refuse(RI_REFUSED % last)
    if done.returncode != 0: refuse(RI_STOPPED % (done.returncode, last))
    try: return json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError): refuse(RI_STOPPED % (0, 'it printed no outcome'))


def resinsight(out, *, port=None, executable=None, python=None, timeout=RI_TIMEOUT):
    """`ophiolite starter resinsight OUT [--port N | --resinsight EXE]` (D6): check the ResInsight target's artefacts in
    files/ against starter.json (refused before anything runs), run the packaged launcher in the Connectors interpreter
    into a new temporary project folder, then `python -m asset_connectors.resinsight_starter compare` on it (the SDK never
    imports rips); a comparison with any difference refuses with nothing written (R2-9). Then
    `files/targets/resinsight/result.json` first and starter.json with the result artefact and the oracle last, by
    rename. A rerun gives the same bytes; the other targets are never touched. Returns (doc, result)."""
    out = Path(out)
    python = python or os.environ.get('OPHIOLITE_RESINSIGHT_PYTHON')
    if not python: refuse(NO_RI_PYTHON)
    try: before = (out / 'starter.json').read_bytes()
    except OSError: refuse('%s is not a folder ophiolite starter build finished: starter.json is missing.' % out.name + UNCHANGED)
    try: doc = json.loads(before)
    except ValueError: refuse('starter.json is not JSON.' + UNCHANGED)
    shaped(doc)
    target = target_of(doc, 'resinsight')
    if target is None or target.get('import') != RI_IMPORT: refuse(NOT_RESINSIGHT)
    across(doc['targets'], doc.get('derived') or [], UNCHANGED)
    for a in target['artefacts']:
        if a['path'] == RI_RESULT: continue
        if artefact_digest(out, a['path']) != (a['sha256'], a['bytes']): refuse('artefact %s: the file in files/ is not the one starter.json names.' % a['path'] + UNCHANGED)
    held_raw = _held_resinsight(out, target, holds_lines(doc), holds_faults(doc), holds_time_depth(doc))
    server = ['--port', str(int(port))] if port is not None else ['--resinsight', str(executable)] if executable else []
    pack = str(out.resolve())
    with tempfile.TemporaryDirectory(prefix='starter-resinsight-') as temporary:
        project_out = str(Path(temporary) / 'project')
        _connectors(python, [str(out.resolve() / 'files' / RI_IMPORT), pack, project_out, '--json'] + server, timeout)
        compared = _connectors(python, ['-m', 'asset_connectors.resinsight_starter', 'compare', pack, project_out] + server, timeout)
    try: result, found = compared['result'], list(compared['found'])
    except (KeyError, TypeError): refuse(RI_STOPPED % (0, 'the comparison printed no result'))
    if found or not isinstance(result, dict) or result.get('differences') != 0:
        refuse(RI_DIFFERS % (len(found) or (result.get('differences') if isinstance(result, dict) else 0) or 0, found[0] if found else 'none named'))
    try: oracle = resinsight_oracle(result, holds_lines(doc), holds_faults(doc), holds_time_depth(doc))
    except (KeyError, TypeError, ValueError): refuse(RI_STOPPED % (0, 'the comparison printed no passing result'))
    raw = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode('utf-8')  # D5: JSON with sorted keys
    if raw != held_raw: replaced(out / 'files' / RI_RESULT, raw)  # the result first
    artefact = {'path': RI_RESULT, 'sha256': sha256(raw), 'bytes': len(raw)}
    named = next((a for a in target['artefacts'] if a['path'] == RI_RESULT), None)
    if named is None: target['artefacts'].append(artefact)
    elif (named['sha256'], named['bytes']) != (artefact['sha256'], artefact['bytes']):
        named.clear(); named.update(artefact)  # new bytes: their key, if any, is no longer theirs
    target['oracle'] = oracle
    after = dumped(doc)
    if after != before: replaced(out / 'starter.json', after)  # starter.json last
    return doc, result
