"""E127 s2: the fidelity document a catalogue reads back (`osd.fidelity/1`, Open Subsurface Data's schema).

After an upload of a local folder or file that held one catalogue manifest, `UploadRuns.fidelity(report, path)` (or
`ophiolite upload PATH --fidelity OUT`) says, per file the manifest lists, what became of it: converted (added or
already here, with the item, its kind and the reader that read it), failed (with the upload's reason) or skipped. The
manifest is read again from PATH and must be the bytes the upload read; the run's listed files are paired with the
manifest's by their order (`listed-<n>`), never by their labels. Each added item's own bytes are taken from its
provenance and checked against the digest the manifest states. A curve item adds a few values a person can compare with
the file: each curve's first sample, with its depth and unit, and the sample count. Nothing is written when any of
this cannot be said exactly: the refusal says why."""
import json
import math
import re
from datetime import datetime
from pathlib import Path
from .errors import Refused

FORMAT = 'osd.fidelity/1'
INSTANT = re.compile(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})')
RECORD = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*')
COMMIT, SHA256 = re.compile(r'[0-9a-f]{40}'), re.compile(r'[0-9a-f]{64}')
CATALOG = ('source_commit', 'verification_commit', 'built_at', 'records_digest')
RESULT = {'added': 'converted', 'already-here': 'converted', 'not-landed': 'failed', 'cancelled': 'skipped', 'expired': 'skipped'}
RESULTS = ('converted', 'partial', 'failed', 'skipped')  # the schema's result enum
ENTRY = {'sha256', 'name', 'result', 'output', 'representative', 'reason'}
REASON = 300  # the schema's longest reason
NOT_WRITTEN = ' No fidelity document was written.'
ADDRESS = 'A fidelity document is written for a manifest uploaded from this computer; this upload read an address.' + NOT_WRITTEN
NO_MANIFEST = 'This upload read no catalogue manifest, so there is no fidelity document to write.'
SEVERAL = 'This upload read %d catalogue manifests; a fidelity document is for one. Upload each manifest on its own.' + NOT_WRITTEN
CHANGED = '%s is not the file this upload read: it changed or is missing.' + NOT_WRITTEN
UNMATCHED = "This upload's files do not match the files %s lists." + NOT_WRITTEN
READING = 'This upload is still reading the files %s lists; write the fidelity document when it has finished.'
NO_SNAPSHOT = 'This manifest has no catalogue snapshot, so no fidelity document can name one.'
NO_RECORD = 'This manifest does not name one catalogue record, so no fidelity document can name it.'
NO_DIGEST = '%s was not added and the manifest states no SHA-256 for it, so the catalogue could not match it.' + NOT_WRITTEN
DIFFERS = '%s was added with other bytes than the manifest states.' + NOT_WRITTEN
UNREAD = 'What became of %s could not be read from this server.' + NOT_WRITTEN
NEWER = '%s has a newer version than the one this upload added, so its values at that version cannot be listed.' + NOT_WRITTEN
INSIDE = 'The fidelity document cannot be written inside what was uploaded; choose another file.' + NOT_WRITTEN


def listed(manifest):
    """[(asset key, asset)] of the manifest's one entry, in the order the gateway numbers them (`listed-<n>` is the n-th:
    project_gateway catalogue.entries)."""
    return [(key, asset if isinstance(asset, dict) else {}) for key, asset in manifest['entries'][0]['assets'].items()]


def stated(asset):
    """The SHA-256 the manifest states for a file (a sha2-256 multihash), or None."""
    checksum = (asset or {}).get('file:checksum')
    return checksum[4:] if isinstance(checksum, str) and checksum.startswith('1220') and SHA256.fullmatch(checksum[4:]) else None


def record(manifest):
    """The one record the manifest is for: exactly one entry, with a record id of the schema's form (S4)."""
    entries = manifest.get('entries')
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict): raise Refused(NO_RECORD)
    rid = entries[0].get('record_id')
    if not isinstance(rid, str) or not RECORD.fullmatch(rid): raise Refused(NO_RECORD)
    return rid


def instant(value):
    """An RFC 3339 date-time (the schema's `date-time`, which OSD checks)."""
    if not isinstance(value, str) or not INSTANT.fullmatch(value): return False
    try: datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
    except ValueError: return False
    return True


def catalog(manifest):
    snapshot = (manifest.get('metadata') or {}).get('catalog') if isinstance(manifest.get('metadata'), dict) else None
    if not isinstance(snapshot, dict) or set(snapshot) != set(CATALOG) or not instant(snapshot['built_at']) \
            or not isinstance(snapshot['records_digest'], str) or not SHA256.fullmatch(snapshot['records_digest']) \
            or any(not (snapshot[k] is None or isinstance(snapshot[k], str) and COMMIT.fullmatch(snapshot[k])) for k in CATALOG[:2]):
        raise Refused(NO_SNAPSHOT)
    return dict(snapshot)


def manifest_row(report):
    rows = [i for i in report.items if any((o.get('output') or '').startswith('listed-') for o in i.get('outputs') or [])]
    if not rows: raise Refused(NO_MANIFEST)
    if len(rows) > 1: raise Refused(SEVERAL % len(rows))
    return rows[0]


def find(client, asset):
    return next((a for a in client.assets() if a.get('asset_id') == asset), None)


def landed(client, name, asset, revision, digest):
    """The output and representative values of one added item, and its own bytes' SHA-256 (from its provenance)."""
    try: content = ((client.provenance(asset, revision).record or {}).get('content') or {}).get('content_sha256')
    except Exception: raise Refused(UNREAD % name) from None  # a version stored before records began has none
    if not isinstance(content, str) or not SHA256.fullmatch(content): raise Refused(UNREAD % name)
    if digest is not None and content != digest: raise Refused(DIFFERS % name)
    try:  # every read is at the output's revision (S7); the catalogue summary gives only the curve names, and only for it
        summary = find(client, asset)
        if summary is None: raise Refused(UNREAD % name)
        if summary.get('curves'):
            if summary.get('revision') != revision: raise Refused(NEWER % name)
            curves = list(summary['curves'])
            described = client.describe(asset, revision, curves[0])
            reader, kind, values = described.interpretation.reader, 'well-log', []
            for curve in client.read(asset, revision, curves).curves:
                first = next((n for n, v in enumerate(curve.values) if v is not None), None)
                if first is not None: values.append({'field': '%s@%r' % (curve.curve, float(curve.axis[first])), 'value': curve.values[first], 'unit': curve.unit or None})
            values.append({'field': 'samples', 'value': described.scientific.sample_count, 'unit': None})
        else:
            read = client.read_data(asset, revision)
            reader, kind, values = read.descriptor.interpretation.reader, read.type, None
    except Refused: raise
    except Exception: raise Refused(UNREAD % name) from None
    if not isinstance(reader, str) or '/' not in reader or not kind: raise Refused(UNREAD % name)
    converter, version = reader.rsplit('/', 1)
    out = {'kind': kind, 'id': asset, 'converter': converter, 'version': version}
    return content, out, values


def document(report, folder, client):
    """The fidelity document for REPORT's one catalogue manifest, read again from FOLDER (`UploadRuns.open(path)`)."""
    if folder.address is not None: raise Refused(ADDRESS)
    row = manifest_row(report)
    local = next((f for f in folder.files if f.path == row['path']), None)
    if local is None or local.sha256 != row['sha256']: raise Refused(CHANGED % row['path'])
    try: raw = local.whole()
    except Exception: raise Refused(CHANGED % row['path']) from None
    try: manifest = json.loads(raw)
    except ValueError: raise Refused(UNMATCHED % row['path']) from None
    if not isinstance(manifest, dict): raise Refused(UNMATCHED % row['path'])
    snapshot, rid = catalog(manifest), record(manifest)
    if not isinstance(manifest['entries'][0].get('assets'), dict): raise Refused(UNMATCHED % row['path'])
    files = listed(manifest)
    ordinals = [o['output'][7:] for o in row['outputs'] if (o.get('output') or '').startswith('listed-')]
    if sorted(ordinals) != sorted(str(n) for n in range(1, len(files) + 1)): raise Refused(UNMATCHED % row['path'])  # exactly 1..n, each once
    outputs = sorted(((int(o['output'][7:]), o) for o in row['outputs'] if (o.get('output') or '').startswith('listed-')), key=lambda p: p[0])
    inputs = []
    for (n, o), (key, asset) in zip(outputs, files):
        name, digest = key or 'Listed file %d' % n, stated(asset)
        if o['outcome'] == 'planned': raise Refused(READING % row['path'])
        result = RESULT.get(o['outcome'])
        if result is None: raise Refused(UNREAD % name)
        entry = {'sha256': digest, 'name': name, 'result': result}
        if result == 'converted':
            if not o.get('asset_id') or not o.get('revision'): raise Refused(UNREAD % name)
            entry['sha256'], entry['output'], values = landed(client, name, o['asset_id'], o['revision'], digest)
            if values: entry['representative'] = values
        elif digest is None: raise Refused(NO_DIGEST % name)
        if result == 'failed': entry['reason'] = (o.get('sentence') or 'Not added.')[:REASON]
        inputs.append(entry)
    return written(snapshot, rid, inputs)


def written(snapshot, rid, inputs):
    """E129 Sa (D5): the checked fidelity/1 document of record RID under catalogue SNAPSHOT (a records.json `catalog`
    block) for INPUTS, each {sha256, name, result[, output][, representative][, reason]}; every argument is checked here
    (R8), so a caller other than `document` cannot write a document the catalogue would refuse."""
    def refuse(what): raise Refused('A fidelity document cannot be written: %s.' % what + NOT_WRITTEN)
    if not isinstance(snapshot, dict) or set(snapshot) != set(CATALOG): refuse('the catalogue snapshot needs exactly %s' % ', '.join(CATALOG))
    if not instant(snapshot['built_at']): refuse('built_at is not a date-time')
    if not isinstance(snapshot['records_digest'], str) or not SHA256.fullmatch(snapshot['records_digest']): refuse('records_digest is not a SHA-256')
    for k in CATALOG[:2]:
        if not (snapshot[k] is None or isinstance(snapshot[k], str) and COMMIT.fullmatch(snapshot[k])): refuse('%s is not a commit' % k)
    if not isinstance(rid, str) or not RECORD.fullmatch(rid): refuse('the record id is not of the form <publisher>/<dataset>')
    if not isinstance(inputs, list) or not inputs: refuse('there are no inputs')
    for n, i in enumerate(inputs, 1):
        if not isinstance(i, dict) or not {'sha256', 'name', 'result'} <= set(i) or not set(i) <= ENTRY: refuse('input %d is not of the schema' % n)
        if i['result'] not in RESULTS: refuse('input %d has result %r' % (n, i['result']))
        if 'output' in i and not isinstance(i['output'], dict) or not isinstance(i.get('representative', []), list): refuse('input %d is not of the schema' % n)
    return checked({'format': FORMAT, 'catalog': dict(snapshot), 'record': rid, 'inputs': [dict(i) for i in inputs]})


def checked(doc):
    """The document as the schema requires it, checked here so that a document the catalogue would refuse is never written
    (the schema itself is OSD's; this SDK does not load it). E129 Sa (M3): `output` goes with converted and partial,
    `reason` with partial and failed, as the schema's allOf states."""
    def text(value): return isinstance(value, str) and value != ''
    def representative(r): return text(r.get('field')) and (r.get('unit') is None or isinstance(r['unit'], str)) and (
        isinstance(r.get('value'), str) or isinstance(r.get('value'), (int, float)) and not isinstance(r['value'], bool) and math.isfinite(r['value']))
    problems = [i['name'] or '?' for i in doc['inputs'] if not SHA256.fullmatch(i['sha256'] or '') or not text(i['name'])
                or (i['result'] in ('partial', 'failed')) != (text(i.get('reason')) and len(i['reason']) <= REASON)
                or (i['result'] in ('converted', 'partial')) != ('output' in i)
                or 'output' in i and not all(text(i['output'].get(k)) for k in ('kind', 'id', 'converter', 'version'))
                or not all(representative(r) for r in i.get('representative', []))]
    if not doc['inputs'] or problems or not RECORD.fullmatch(doc['record']) or not instant(doc['catalog']['built_at']): raise Refused("This upload's files cannot be described exactly%s." % (' (%s)' % ', '.join(problems) if problems else '') + NOT_WRITTEN)
    return doc


def outside(source, destination):
    """Refused when DESTINATION is the uploaded file or inside the uploaded folder: nothing uploaded is overwritten."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents: raise Refused(INSIDE)


def write(doc, path):
    path = Path(path)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return path
