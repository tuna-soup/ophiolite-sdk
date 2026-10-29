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
import os
import platform
import re
from pathlib import Path

from .errors import IntegrityConflict, MissingExtra, PermissionRefused, Refused

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
    if defn['targets'] != ['python']: bad('targets must be ["python"] in this version')
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


def distinct(artefacts, inputs, tail):
    """D5: no two artefacts, and no artefact and input, share a SHA-256 (an artefact is made, not copied)."""
    seen = {i['sha256']: i['name'] for i in inputs}
    for a in artefacts:
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
    return {'defn': defn, 'raw_definition': Path(definition_path).read_bytes(), 'declared': declared, 'evidence': evidence, 'read': read,
            'files': files, 'doc': doc}


def build(client, definition_path, out, *, catalogue, verification, custody):
    """`ophiolite starter build`: land the inputs, then write OUT/starter.json (unpublished, no keys), its fidelity document
    and the python target under OUT/files/. A rerun with the same OUT continues from landing.json (D7). Returns the pack
    document."""
    from . import fidelity
    from .upload_runs import UploadRuns
    p = prepared(definition_path, catalogue, verification, custody)
    defn, doc, out = p['defn'], p['doc'], Path(out)
    evidence_raw = dumped(p['evidence'])
    bindings = {'url': client.url, 'project': client.project, 'definition': sha256(p['raw_definition']), 'evidence.json': sha256(evidence_raw), 'evidence': p['read']}
    journal_path = out / 'landing.json'
    if journal_path.exists():
        try: journal = json.loads(journal_path.read_bytes())
        except ValueError: refuse('landing.json in %s is not JSON; build in a new folder.' % out.name + NOT_WRITTEN)
        before = journal.get('bindings') or {}
        for key, said in (('url', 'The gateway URL'), ('project', 'The project'), ('definition', 'The pack definition'), ('evidence.json', 'The evidence')):
            if before.get(key) != bindings[key]: refuse(BINDING % said + NOT_WRITTEN)
        for path in sorted(set(before.get('evidence') or {}) | set(bindings['evidence'])):
            if (before.get('evidence') or {}).get(path) != bindings['evidence'].get(path): refuse(BINDING % ('The evidence file %s' % Path(path).name) + NOT_WRITTEN)
    else:
        journal = {'format': LANDING, 'bindings': bindings, 'inputs': {}}
    replaced(out / 'evidence.json', evidence_raw)
    def save(): replaced(journal_path, dumped(journal))
    save()
    runs, entries = UploadRuns(client), []
    for n, i in enumerate(defn['inputs']):
        name, path = i['name'], defn['folder'] / i['file']
        prof = defn['profiles'][name]
        sent = p['declared'].get(name) or {}
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
                content, output, values = fidelity.landed(client, name, row['asset_id'], row['revision'], i['sha256'])
                if recovered: current(client, name, row['asset_id'], row['revision'])
                entry = {'state': 'landed', 'run_id': report.run_id, 'asset_id': row['asset_id'], 'revision': row['revision'], 'profile': prof,
                         'output': {**output, 'kind': PROFILE_KIND[prof]}, **({'representative': values} if values else {})}
                journal['inputs'][name] = entry; save()
        except PermissionRefused:
            raise PermissionRefused(DENIED % (client.project, name, landed, len(defn['inputs']))) from None
        entries.append({'sha256': i['sha256'], 'name': name, 'result': 'converted', 'output': entry['output'],
                        **({'representative': entry['representative']} if entry.get('representative') else {})})
    replaced(out / doc['fidelity'], dumped(fidelity.written(p['evidence']['catalog'], defn['record_id'], entries)))
    for rel, raw in p['files'].items(): replaced(out / 'files' / rel, raw)
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
    targets = doc['targets']
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], dict) or not isinstance(targets[0].get('artefacts'), list): bad()
    for a in targets[0]['artefacts']:
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
    for i in doc['inputs']: held(i, evidence, UNCHANGED)  # rule (b), against the evidence build judged
    sources = licences(doc, evidence)
    if {**computed_licence(sources, UNCHANGED), 'sources': sources} != doc['licence']: refuse('The pack licence is not the one its inputs\' evidence gives.' + UNCHANGED)  # rule (d)
    complete(doc, UNCHANGED)  # rule (e)
    artefacts = doc['targets'][0]['artefacts']
    distinct(artefacts, doc['inputs'], UNCHANGED)
    for a in artefacts:
        try: raw = (out / 'files' / a['path']).read_bytes()
        except OSError: raw = None
        if raw is None or (sha256(raw), len(raw)) != (a['sha256'], a['bytes']): refuse('artefact %s: the file in files/ is not the one starter.json names.' % a['path'] + UNCHANGED)
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
    for a, key in zip(artefacts, keys): a['key'] = key
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
    for sha, name in pack.items():
        if sha not in results: refuse('%s: no result for input %s.' % (what, name) + UNCHANGED)
    for sha, i in results.items():
        if sha not in pack: refuse('%s: input %s is not a pack input.' % (what, i['name']) + UNCHANGED)
        if i['result'] not in ('converted', 'partial'): refuse('%s: input %s is %s.' % (what, i['name'], i['result']) + UNCHANGED)
        if i['output']['kind'] not in kinds: refuse('%s: input %s became %s, not a contents kind.' % (what, i['name'], i['output']['kind']) + UNCHANGED)
