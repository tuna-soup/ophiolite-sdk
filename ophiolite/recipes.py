"""E23b D7 (SDK mirror of the Workspace words): what a person reads for a recipe field and its value. Printed objects
use these words and never a raw field key or enum token; the raw particulars stay in `details()`."""
import base64
import hashlib
import json
from pathlib import PurePosixPath

from .errors import Refused


FIELDS = {'crs': 'Coordinate system', 'xy_unit': 'Horizontal unit', 'z_unit': 'Vertical unit', 'z_meaning': 'Values',
          'positive': 'Positive direction', 'vertical_datum': 'Vertical datum'}
VALUES = {'z_meaning': {'depth': 'depth', 'elevation': 'elevation', 'time': 'time', 'unknown': 'not stated'},
          'positive': {'up': 'up', 'down': 'down', 'unknown': 'not stated'}}

ROLES = {'x': 'X (easting)', 'y': 'Y (northing)', 'z': 'Z value', 'attribute': 'Attribute'}  # E23b: a reading layout's column roles and kinds
KINDS = {'number': 'Number', 'text': 'Text', 'category': 'Category'}


def field_label(field):
    return FIELDS[field]


def value_label(field, value):
    """A unit, CRS or datum is printed as stated; an enum value by its word."""
    if value is None: return 'not stated'
    return VALUES[field][value] if field in VALUES else str(value)


# --- E23b B7: look at how a point export is read, decide with a reason, and reuse a reading layout ----------------------

PROFILES = ('petrel-points-attributes/1', 'opendtect-horizon-ascii/1')
REASON_MOST = 120
SAY_WHY = 'Say why with --why %s:%s=TEXT; a value you decide for a point export is kept with your reason.'
NEEDLES = {'tab': '\t', 'comma': ',', 'semicolon': ';'}


def reason_problem(reason):
    """What is wrong with a reason, in words; '' when it may be kept (counted in characters, as the server counts)."""
    if not (reason or '').strip(): return 'Say why, in a few words.'
    n = len(reason)
    return 'A reason is at most %d characters; this one has %d. Nothing was cut; shorten it.' % (REASON_MOST, n) if n > REASON_MOST else ''


def locate(text, needle):
    """The line of the primary file a change is attributed to: the first that holds the text, else the first line."""
    at = next((i for i, line in enumerate(text.split('\n')) if needle and needle in line), 0)
    return 'line %d' % (at + 1)


class Choices:
    """What a person says about the files of one kind (by profile): values declared, a file's statement selected, fields
    left unresolved, each with their reason; configuration changes (an unsaved draft); or a reading layout to start from."""

    def __init__(self, declare=None, why=None, select=None, leave=None, changes=None, layout=None, *, every=False):
        self.declare, self.why, self.select, self.leave = declare or {}, why or {}, select or {}, leave or {}
        self.changes, self.layout, self.every = changes or {}, layout, every

    def given(self, profile):
        """True when these choices read files of this kind (`every`: all point exports, as `inspect` does)."""
        return self.every or self.layout is not None or any(profile in d for d in (self.declare, self.why, self.select, self.leave, self.changes))

    def reason(self, profile, field):
        said = self.why.get(profile, {}).get(field)
        if said is None: raise Refused(SAY_WHY % (profile, field))
        problem = reason_problem(said)
        if problem: raise Refused('%s (%s)' % (problem, field_label(field) if field in FIELDS else field))
        return said

    def decisions(self, profile, first=None):
        """The staged decisions of one kind, in field order; a selection needs the first inspection's observations."""
        out = {f: {'kind': 'declare', 'field': f, 'value': v, 'reason': self.reason(profile, f)} for f, v in self.declare.get(profile, {}).items()}
        out.update({f: {'kind': 'leave-unresolved', 'field': f, 'reason': self.reason(profile, f)} for f in self.leave.get(profile, ())})
        for f, value in self.select.get(profile, {}).items():
            found = [o['id'] for d in (first or {}).get('decisions', []) if d['field'] == f for o in d['observations'] if o.get('id') and o['value'] == value]
            if first is not None and not found: raise Refused('The files state no %s of %s.' % (field_label(f) if f in FIELDS else f, value))
            if found: out[f] = {'kind': 'select-evidence', 'field': f, 'observation': found[0], 'reason': self.reason(profile, f)}
        unknown = sorted(set(self.why.get(profile, {})) - set(out) - set(self.select.get(profile, {})))
        if unknown: raise Refused('--why %s:%s gives a reason for nothing you decided.' % (profile, unknown[0]))
        return [out[f] for f in sorted(out)]


def changes_of(config, primary):
    """--config FILE: {"changes": [{setting, target, to, reason, line?}]} as staged changes, with the line of the primary file
    each is attributed to (given, else located as the Workspace locates it)."""
    text = primary.decode('utf-8', 'replace')
    out = []
    for c in config.get('changes', []):
        problem = reason_problem(c.get('reason'))
        if problem: raise Refused('%s (%s of %s)' % (problem, c.get('setting'), c.get('target')))
        to = c.get('to')
        needle = to if c.get('setting') == 'label-map' else (to or [''])[0] if c.get('setting') == 'missing-marker' else NEEDLES.get(to, '') if c.get('setting') == 'delimiter' else c.get('target')
        out.append({'setting': c.get('setting'), 'target': c.get('target'), 'to': to, 'reason': c['reason'],
                    'evidence': {'member': hashlib.sha256(primary).hexdigest(), 'locator': 'line %d' % c['line'] if c.get('line') else locate(text, needle)}})
    return out


def companions(paths, entries, most=8):
    """Connectors `readers.group`, as the Workspace mirrors it: {primary: [(path, role)]} in path order; a file two primaries
    could take goes to neither."""
    taken = {}
    for path in paths:
        p = PurePosixPath(path)
        if p.name == 'README.txt' or path.endswith('.crsmeta.xml'): continue
        entry = next((r for r in entries if r.get('companions') and p.suffix.lower() in r['extensions']), None)
        for rule in (entry or {}).get('companions', []):
            name = str(p.parent / rule['pattern'].replace('{stem}', p.stem)) if str(p.parent) != '.' else rule['pattern'].replace('{stem}', p.stem)
            if name != path and name in paths: taken.setdefault(name, []).append((path, rule['role']))
    groups = {}
    for name, owners in taken.items():
        if len(owners) == 1 and len(groups.setdefault(owners[0][0], [])) < most: groups[owners[0][0]].append((name, owners[0][1]))
    return {k: sorted(v) for k, v in groups.items()}


class Inspection:
    """How one point export is read with your decisions: each field's decision, the first points, and whether it may be
    added. Printed in words; `details()` has the raw answer (ids, digests, the receipt)."""

    def __init__(self, path, profile, staged, answer):
        from .typed import Decision
        self.path, self.profile, self.staged_set, self.answer = path, profile, staged, answer
        self.decisions = [Decision(d) for d in answer['decisions']]
        self.open = [d['field'] for d in answer['decisions'] if d['status'] != 'decided' and not d.get('left_unresolved')]
        self.preview_receipt = answer['preview_receipt']

    @property
    def ready(self): return not self.open

    def pin(self): return {'scientific_decisions': self.staged_set, 'preview_receipt': self.preview_receipt}

    def lines(self):
        out = ['%s: %s, %d points' % (self.path, reader_label(self.profile), self.answer['context'].get('count', len(self.answer['preview'])))]
        for d, raw in zip(self.decisions, self.answer['decisions']):
            left = raw.get('left_unresolved') and not d.decided
            out.append('  ' + ('%s: left unresolved' % field_label(d.field) if left else repr(d)[len('<Decision '):-1]))  # its reason is in the recipe's events
        out.append('Ready to add.' if self.ready else 'Still needs a decision: %s.' % ', '.join(field_label(f) if f in FIELDS else 'another field' for f in self.open))
        return out

    def __repr__(self): return '<Inspection %s: %s>' % (self.path, 'ready to add' if self.ready else 'needs a decision')

    def details(self): return {'staged_set': self.staged_set, **self.answer}


def _said(call):
    """A refused reading or set in the server's sentence (what the file has and what the reading expects), as the
    Workspace shows it; the transport's generic words otherwise."""
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if error.status != 400 or not error.server_message: raise
        raise Refused(error.server_message, status=error.status, code=error.code, request_id=error.request_id, details=error.details) from error


class Scientific:
    """las-uploads/decision-set and las-uploads/inspect for the point exports of a folder (E23b)."""

    def __init__(self, client):
        self.client = client

    def stage(self, profile, members, decisions=(), changes=(), layout=None):
        body = {'profile': profile, 'package': members, 'decisions': list(decisions), 'changes': list(changes), **({'layout': layout} if layout else {})}
        return _said(lambda: self.client._post('las-uploads', 'decision-set', body))['staged_set']

    def preview(self, profile, staged, raw):
        header = base64.b64encode(json.dumps({'project_id': self.client.project, 'profile': profile, 'staged_set': staged}, separators=(',', ':')).encode()).decode()
        return _said(lambda: self.client._post_bytes('las-uploads', 'inspect', raw, extra_headers={'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': header}))

    def layout_pin(self, name, profile):
        """The reading layout NAME as a pin {asset_id, generation}; refused naming it when it reads another kind of file."""
        from .layouts import holds
        view = self.client.layouts().find(name)
        if view.get('kind') != 'import-recipe':
            raise Refused('The layout "%s" is a table layout (%s); it does not read %s.' % (view['name'], holds(view), reader_label(profile)))
        if view['target'] != profile:
            raise Refused('The layout "%s" reads %s; it does not read %s.' % (view['name'], reader_label(view['target']), reader_label(profile)))
        return {'asset_id': view['asset_id'], 'generation': view['generation']}

    def inspect(self, folder, choices, kinds):
        """{path: Inspection} of every point export of the folder (`kinds`: {path: profile} from the deployment's check)."""
        from .upload_runs import readers
        files = {f.path: f for f in folder.files}
        groups, out = companions(list(files), readers(), 8), {}
        for path, profile in kinds.items():
            members = [(path, 'primary'), *groups.get(path, [])]
            raw = [files[p].whole() for p, _ in members]
            listed = [{'name': PurePosixPath(p).name, 'role': role, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for (p, role), b in zip(members, raw)]
            layout = self.layout_pin(choices.layout, profile) if choices.layout else None
            changes = changes_of({'changes': choices.changes.get(profile, [])}, raw[0])
            first = None
            if choices.select.get(profile):
                staged = self.stage(profile, listed, [], changes, layout); first = self.preview(profile, staged, b''.join(raw))
            staged = self.stage(profile, listed, choices.decisions(profile, first), changes, layout)
            out[path] = Inspection(path, profile, staged, self.preview(profile, staged, b''.join(raw)))
        return out


def reader_label(profile):
    from .upload_runs import readers
    return next((r['label'] for r in readers() if r['profile'] == profile), 'another kind of file')
