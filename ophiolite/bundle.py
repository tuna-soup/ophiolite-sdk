"""Portable bundles (``ophiolite.portable-bundle/1`` and ``/2``): write, check and read offline.

A bundle is a directory whose only entry point is ``manifest.json``. Reading needs no
server, account, credentials or network: this module imports no transport or
authentication code. Checks refuse another major version, unsafe or linked paths,
duplicate or oversized files, digest or size mismatches and non-finite JSON before any
scientific content is used; every descriptor/curve pair is verified as on the wire.
Checksums prove the integrity of the copy, not authorship or scientific correctness.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ._version import __version__
from .errors import VerificationFailed, Refused

SCHEMA = 'ophiolite.portable-bundle/1'
VERSION = '1.0.0'
# Bundle 2 (E11) adds typed assets; curve-only exports stay 1.0 for released readers.
SCHEMA_2 = 'ophiolite.portable-bundle/2'
VERSION_2 = '2.0.0'
TYPED_ORIGINALS = {'well-tops-csv/1': 'original.csv', 'deviation-csv/1': 'original.csv', 'esri-ascii-grid/1': 'original.asc', 'mesh-text/1': 'original.txt', 'points-csv/1': 'original.csv',
                   'opendtect-faultsticks/1': 'original.txt'}
NEWER_TYPES = {'triangulated-surface': 2, 'point-set': 2, 'polyline-set': 3, 'seismic-slice': 3}  # the 2.x minor that introduced them
TYPES_2 = ('well-log', 'well-tops', 'trajectory', 'regular-grid-surface', 'triangulated-surface', 'point-set', 'polyline-set', 'seismic-slice')
SLICE_NAME = re.compile(r'^slice-(inline|crossline|sample)-(-?[0-9]{1,9})\.json$')
MAX_ASSETS = 128
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
PATH = re.compile(r'^assets/[0-9]{1,3}/[A-Za-z0-9._-]{1,120}$')
NOTICE = ('Checksums show the integrity of this copy, not authorship or scientific correctness. '
          'Exported copies cannot be recalled; holding one grants no new upstream, sharing or AI-training rights.')


def _finite_json(raw, what):
    def refuse(value): raise ValueError(value)
    try: return json.loads(raw, parse_constant=refuse)
    except (ValueError, UnicodeDecodeError): raise VerificationFailed(what + ' is not finite JSON.') from None


def _safe_name(value):
    cleaned = re.sub(r'[^A-Za-z0-9._-]', '_', value)[:80]
    return cleaned if cleaned and cleaned not in ('.', '..') else 'curve'


class Curve:
    """One normalized curve with its served descriptor. Missing samples are None; zero stays zero."""

    def __init__(self, descriptor, view, wire_descriptor, wire_view):
        self.descriptor, self.view = descriptor, view
        self.wire_descriptor, self.wire_view = wire_descriptor, wire_view
        self.name = view.curve; self.axis = list(view.axis); self.values = list(view.values); self.unit = view.unit
        self.context = view.context.model_dump(); self.scientific = wire_descriptor.get('scientific', {})

    def to_numpy(self):
        import numpy as np
        return np.array(self.axis, dtype=float), np.array([np.nan if v is None else v for v in self.values], dtype=float)

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame({self.context['depth_index']: self.axis, self.name: pd.array(self.values, dtype='Float64')})


class BundleAsset:
    """A verified asset: `curves` for a well log, `data` (a typed object) for tops, trajectories and grids,
    `slices` (with `data` the volume's description and no original) for exported seismic slices."""
    def __init__(self, entry, original, curves, data=None, slices=None):
        self.slices = slices or []
        self.entry = entry; self.asset_id = entry['asset_id']; self.revision = entry['revision']; self.name = entry.get('name')
        self.origin = entry['origin']; self.history = entry.get('history'); self.parents = entry['parents']
        self.parent_visibility = entry['parent_visibility']; self.original = original; self.curves = curves
        self.type = entry.get('type', 'well-log'); self.data = data; self.relationships = entry.get('relationships')


class Bundle:
    def __init__(self, path, manifest, assets, unlisted):
        self.path, self.manifest, self.assets, self.unlisted = path, manifest, assets, unlisted
        # 1.1/2.1: result groups as observed at export time (members by position; not scientific truth).
        self.groups = (manifest.get('observations') or {}).get('groups') or []
        self.entities, self.relationships = [], []  # 2.4 (E20), set by open_bundle after checking

    def entity(self, entity_id):
        found = next((e for e in self.entities if e.entity_id == entity_id), None)
        if found is None: raise Refused('This bundle lists no such entity.')
        return found

    def assets_of(self, entity, profile=None):
        """Offline: the bundle's exact revisions associated with an entity (optionally one profile)."""
        wanted = set((entity if isinstance(entity, BundleEntity) else self.entity(entity)).revisions())
        return [a for a in self.assets if (a.asset_id, a.revision) in wanted and (profile is None or a.entry.get('profile') == profile)]

    def wellbores(self, well):
        well_id = getattr(well, 'entity_id', well)
        return [e for e in self.entities if e.kind == 'wellbore' and e.well_id() == well_id]

    def summary(self):
        return {'bundle_version': self.manifest['bundle_version'], 'scope': self.manifest['scope'], 'assets': len(self.assets),
                'curves': sum(len(a.curves) for a in self.assets), 'types': sorted({a.type for a in self.assets}), 'unlisted_files': self.unlisted,
                'groups': self.manifest['groups'], 'recommendations': self.manifest['recommendations']}


def _check_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema') not in (SCHEMA, SCHEMA_2): raise VerificationFailed('This is not an Ophiolite portable bundle.')
    version = manifest.get('bundle_version')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version): raise VerificationFailed('The bundle version is not readable.')
    if version.split('.')[0] not in ('1', '2'): raise Refused('This bundle uses version %s; this reader supports major versions 1 and 2. Update the SDK.' % version)
    if (version.split('.')[0] == '2') != (manifest['schema'] == SCHEMA_2): raise VerificationFailed('The bundle schema and version disagree.')
    if manifest.get('scope') != 'selection': raise VerificationFailed('The bundle scope is not a selection.')
    if manifest.get('groups', 0) is not None or manifest.get('recommendations', 0) is not None: raise VerificationFailed('Groups and recommendations travel as observations; the manifest fields must be null.')
    observations = manifest.get('observations')
    if observations is not None and (not isinstance(observations, dict) or not isinstance(observations.get('groups', []), list)): raise VerificationFailed('Observations are not readable.')
    assets = manifest.get('assets')
    if not isinstance(assets, list) or not 0 < len(assets) <= MAX_ASSETS: raise VerificationFailed('The bundle lists no assets or too many.')
    return assets


def open_bundle(path):
    """Check a bundle completely, then return its verified contents. Offline."""
    from . import _core
    root = Path(path)
    if root.is_symlink() or not root.is_dir(): raise VerificationFailed('A bundle is a directory.')
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file(): raise VerificationFailed('The bundle has no manifest.')
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES: raise VerificationFailed('The bundle manifest is too large.')
    manifest = _finite_json(manifest_path.read_bytes(), 'The bundle manifest')
    entries = _check_manifest(manifest)
    selection = manifest.get('selection')
    if not isinstance(selection, list) or len(selection) != len(entries): raise VerificationFailed('The selection and the assets disagree.')
    seen, total, loaded = set(), 0, []
    for index, entry in enumerate(entries):
        files = entry.get('files')
        if not isinstance(files, list) or not files: raise VerificationFailed('An asset lists no files.')
        content = {}
        for item in files:
            relative = item.get('path') if isinstance(item, dict) else None
            if not isinstance(relative, str) or not PATH.fullmatch(relative) or PurePosixPath(relative).parts[1] != str(index):
                raise VerificationFailed('A bundle path is unsafe or outside its asset folder.')
            if relative in seen: raise VerificationFailed('A bundle path is listed twice.')
            seen.add(relative); target = root / relative
            for part in (target.parent.parent, target.parent, target):
                if part.is_symlink(): raise VerificationFailed('A bundle path is a link.')
            size = item.get('bytes')
            if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES: raise VerificationFailed('A bundle file exceeds the supported size.')
            total += size
            if total > MAX_TOTAL_BYTES: raise VerificationFailed('The bundle exceeds the supported total size.')
            if not target.is_file() or target.stat().st_size != size: raise VerificationFailed('A bundle file is missing or has the wrong size.')
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item.get('sha256'): raise VerificationFailed('A bundle file does not match its checksum.')
            content.setdefault(item.get('role'), {})[relative if item.get('role') == 'slice' else item.get('curve')] = raw
        chosen = selection[index] if isinstance(selection[index], dict) else {}
        if (chosen.get('asset_id'), chosen.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
            raise VerificationFailed('An asset is not the exact revision that was selected.')
        roles = [item.get('role') for item in files]
        kind = entry.get('type', 'well-log') if manifest['schema'] == SCHEMA_2 else 'well-log'
        if manifest['schema'] == SCHEMA_2 and kind not in TYPES_2: raise VerificationFailed('An asset has an unknown type.')
        if kind != 'seismic-slice' and ('original' in entry or 'slices' in entry or 'slices' in chosen):
            raise VerificationFailed('Only seismic slices omit their original.')
        if kind == 'seismic-slice':  # 2.3: slices of a volume; the original is named by digest, not carried
            loaded.append(_slice_asset(entry, chosen, content, files)); continue
        if roles.count('original') != 1 or set(roles) - {'original', 'descriptor', 'normalized'}:
            raise VerificationFailed('Bundle 1.0 carries exactly one original per asset and only known file roles.')
        if kind != 'well-log':
            loaded.append(_typed_asset(entry, chosen, content, files, kind)); continue
        if sorted(content.get('descriptor', {})) != sorted(chosen.get('curves') or []) or sorted(content.get('normalized', {})) != sorted(chosen.get('curves') or []):
            raise VerificationFailed('The curve files are not exactly the selected curves.')
        original = content.get('original', {}).get(None)
        curves = {}
        for name, raw in content.get('descriptor', {}).items():
            body = content.get('normalized', {}).get(name)
            if name is None or body is None: raise VerificationFailed('A descriptor has no matching curve file.')
            wire_descriptor = _finite_json(raw, 'A descriptor'); wire_view = _finite_json(body, 'A curve')
            if (wire_descriptor.get('asset_id'), wire_descriptor.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
                raise VerificationFailed('A descriptor belongs to another exact revision.')
            if original is None: raise VerificationFailed('The original bytes needed to verify this curve are missing.')
            if wire_descriptor.get('scientific', {}).get('curve') != name: raise VerificationFailed('A descriptor describes another curve.')
            for field in ('origin', 'profile', 'parents', 'parent_visibility'):
                if wire_descriptor.get(field, 'complete' if field == 'parent_visibility' else None) != entry.get(field): raise VerificationFailed('The manifest disagrees with a descriptor (' + field + ').')
            if wire_descriptor.get('history') != entry.get('history'): raise VerificationFailed('The manifest disagrees with a descriptor (history).')
            model, view = _core.verify_pair(wire_descriptor, body, original, name)
            curves[name] = Curve(model, view, wire_descriptor, wire_view)
        if not curves: raise VerificationFailed('An asset carries no curves.')
        loaded.append(BundleAsset(entry, original, curves))
    _check_groups(manifest, entries)
    entities, relationships = _check_graph(manifest, entries)
    listed = seen | {'manifest.json'}
    unlisted = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).as_posix() not in listed)
    bundle = Bundle(root, manifest, loaded, unlisted)
    bundle.entities, bundle.relationships = entities, relationships
    return bundle


def _check_graph(manifest, entries):
    """E20 (bundle 2.4): every entity once; every relationship registered, of the kinds its predicate
    joins, between exported exact revisions and listed entities; a listed wellbore's well is listed."""
    from .navigation import PREDICATES
    entities, relationships = manifest.get('entities'), manifest.get('relationships')
    if entities is None and relationships is None: return [], []
    if manifest.get('schema') != SCHEMA_2 or not isinstance(entities, list) or not isinstance(relationships, list):
        raise VerificationFailed('Entities and relationships travel together in a bundle 2.4 or later.')
    listed = {}
    for e in entities:
        if not isinstance(e, dict) or set(e) != {'entity_id', 'kind', 'name', 'identity'} or e['kind'] not in ('well', 'wellbore') or e['entity_id'] in listed:
            raise VerificationFailed('An entity is malformed or listed twice.')
        listed[e['entity_id']] = e
    exported = {(a.get('asset_id'), a.get('revision')) for a in entries}
    seen = set()
    for r in relationships:
        p = PREDICATES.get(r.get('predicate')) if isinstance(r, dict) else None
        if p is None or p['asserted_by'] != 'people' or p['status'] != 'active':
            raise VerificationFailed('A relationship is not a registered association.')
        subject, obj = r.get('subject') or {}, r.get('object') or {}
        if subject.get('kind') not in p['subject'] or obj.get('kind') not in p['object']:
            raise VerificationFailed('A relationship joins kinds its predicate does not join.')
        if subject['kind'] == 'revision':
            if (subject.get('asset_id'), subject.get('revision')) not in exported: raise VerificationFailed('A relationship names a revision that is not in this bundle.')
        elif listed.get(subject.get('entity_id'), {}).get('kind') != subject['kind']: raise VerificationFailed('A relationship names an entity that is not listed.')
        if listed.get(obj.get('entity_id'), {}).get('kind') != obj['kind']: raise VerificationFailed('A relationship names an entity that is not listed.')
        key = json.dumps([r['predicate'], subject, obj], sort_keys=True)
        if key in seen: raise VerificationFailed('A relationship is listed twice.')
        seen.add(key)
    return [BundleEntity(e, relationships) for e in entities], relationships


class BundleEntity:
    """A well or wellbore as exported, with offline navigation over the bundle's relationships."""
    def __init__(self, document, relationships):
        self.document, self._relationships = document, relationships
        self.entity_id, self.kind, self.name, self.identity = document['entity_id'], document['kind'], document['name'], document['identity']

    def __repr__(self):
        return 'BundleEntity(%s %r)' % (self.kind, self.name)

    def revisions(self):
        """[(asset_id, revision)] associated with this entity in the bundle."""
        return [(r['subject']['asset_id'], r['subject']['revision']) for r in self._relationships
                if r['predicate'] == 'of-entity' and r['object']['entity_id'] == self.entity_id]

    def well_id(self):
        return next((r['object']['entity_id'] for r in self._relationships if r['predicate'] == 'part-of' and r['subject']['entity_id'] == self.entity_id), None)


def _check_groups(manifest, entries):
    for group in (manifest.get('observations') or {}).get('groups') or []:
        if not isinstance(group, dict) or group.get('meaning') != 'observation-at-export' or not isinstance(group.get('name'), str):
            raise VerificationFailed('A group is not an export-time observation.')
        members = group.get('members')
        if not isinstance(members, list) or not members or len(set(members)) != len(members) or any(type(m) is not int or not 0 <= m < len(entries) for m in members):
            raise VerificationFailed('A group names assets that are not in this bundle.')
        rec = group.get('recommended')
        if rec is not None and (not isinstance(rec, dict) or type(rec.get('asset_position')) is not int or rec['asset_position'] not in members or entries[rec['asset_position']].get('revision') != rec.get('revision')):
            raise VerificationFailed('A group recommends a version that is not in this bundle.')


def _typed_asset(entry, chosen, content, files, kind):
    from . import _core
    if chosen.get('curves') != [] or roles_of(files) != ['descriptor', 'normalized', 'original'] or any(item.get('curve') is not None for item in files):
        raise VerificationFailed('A typed asset carries exactly one original, one descriptor and one data file, and no curves.')
    wire_descriptor = _finite_json(content['descriptor'][None], 'A descriptor'); body = content['normalized'][None]; _finite_json(body, 'Typed data')
    if (wire_descriptor.get('asset_id'), wire_descriptor.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
        raise VerificationFailed('A descriptor belongs to another exact revision.')
    if (wire_descriptor.get('scientific') or {}).get('type') != kind: raise VerificationFailed('The manifest disagrees with a descriptor (type).')
    for field in ('origin', 'profile', 'parents', 'parent_visibility', 'relationships'):
        if wire_descriptor.get(field, 'complete' if field == 'parent_visibility' else None) != entry.get(field): raise VerificationFailed('The manifest disagrees with a descriptor (' + field + ').')
    data = _core.typed_result(wire_descriptor, body, content['original'][None])
    return BundleAsset(entry, content['original'][None], {}, data)


def _slice_asset(entry, chosen, content, files):
    """Seismic slices: one volume descriptor, its description, and each chosen slice exactly as
    served. Every slice is checked against the description (identity, direction, axes, sample
    meaning, shape, chunks); the absent original is identified by its digest."""
    from . import _core
    from .typed import SeismicSlice
    wanted = chosen.get('slices')
    if chosen.get('curves') != [] or not isinstance(wanted, list) or not wanted or any(not isinstance(w, dict) or set(w) != {'axis', 'label'} for w in wanted):
        raise VerificationFailed('A slice export names the slices it carries and no curves.')
    listed = [item for item in files if item.get('role') == 'slice']
    if sorted(item.get('role') for item in files if item.get('role') != 'slice') != ['descriptor', 'normalized'] or any(item.get('curve') is not None for item in files):
        raise VerificationFailed('A slice export carries one descriptor, one volume description and its slices, and no original.')
    names = [(SLICE_NAME.fullmatch(PurePosixPath(item['path']).name), item) for item in listed]
    if any(m is None for m, _ in names): raise VerificationFailed('A slice file is not named by its direction and number.')
    order = [{'axis': m.group(1), 'label': int(m.group(2))} for m, _ in names]
    if order != wanted: raise VerificationFailed('The slice files are not exactly the selected slices.')
    wire_descriptor = _finite_json(content['descriptor'][None], 'A descriptor'); body = content['normalized'][None]; _finite_json(body, 'The volume description')
    if (wire_descriptor.get('asset_id'), wire_descriptor.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
        raise VerificationFailed('A descriptor belongs to another exact revision.')
    if (wire_descriptor.get('scientific') or {}).get('type') != 'seismic-volume': raise VerificationFailed('Slices come from a seismic volume.')
    for field in ('origin', 'profile', 'parents', 'parent_visibility'):
        if wire_descriptor.get(field, 'complete' if field == 'parent_visibility' else None) != entry.get(field): raise VerificationFailed('The manifest disagrees with a descriptor (' + field + ').')
    volume = _core.typed_result(wire_descriptor, body, None)
    original = next(r for r in wire_descriptor['representations'] if r['kind'] != 'normalized')
    if entry.get('original') != {'sha256': original['sha256'], 'bytes': original['bytes'], 'included': False} or original['sha256'] != entry.get('revision'):
        raise VerificationFailed('The manifest does not identify the original volume by its digest.')
    slices = []
    for (m, item), want in zip(names, wanted):
        raw = content['slice'][item['path']]
        slices.append(_core.slice_result(volume, raw, entry['asset_id'], entry['revision'], want['axis'], want['label']))
    if entry.get('slices') != [{'axis': s.axis, 'label': s.label, 'shape': [len(s.rows[1]), len(s.columns[1])], 'scope': s.scope} for s in slices]:
        raise VerificationFailed('The manifest disagrees with a slice.')
    return BundleAsset(entry, None, {}, volume, slices)


def roles_of(files):
    return sorted(item.get('role') for item in files)


def write_bundle(destination, items, *, grace=3600, groups=None, groups_omitted=None, graph=None):
    """Write verified exact reads [(selection, CurveSet-like)] atomically. Internal to export."""
    destination = Path(destination)
    if destination.exists(): raise Refused('The destination already exists; choose a new folder.')
    if not 0 < len(items) <= MAX_ASSETS: raise Refused('Export between 1 and %d exact revisions.' % MAX_ASSETS)
    parent = destination.parent; parent.mkdir(parents=True, exist_ok=True)
    for stale in parent.glob('.' + destination.name + '.staging-*'):  # abandoned interrupted exports only
        try: owner = int((stale / '.owner').read_text())
        except (OSError, ValueError): owner = None
        alive = owner is not None and _alive(owner)
        if not alive and time.time() - stale.stat().st_mtime > grace: shutil.rmtree(stale, ignore_errors=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.staging-', dir=parent)); os.chmod(staging, 0o700)
    (staging / '.owner').write_text(str(os.getpid()))
    try:
        assets, selection, total = [], [], 0
        def put(relative, raw, role, curve=None):
            nonlocal total
            if len(raw) > MAX_FILE_BYTES: raise Refused('A file exceeds the supported size for a bundle.')
            total += len(raw)
            if total > MAX_TOTAL_BYTES: raise Refused('The selection exceeds the supported bundle size.')
            target = staging / relative; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as out: out.write(raw)
            entry = {'path': relative, 'role': role, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            if curve is not None: entry['curve'] = curve
            return entry
        typed_bundle = any(hasattr(read, '_wire_data_bytes') or isinstance(read, tuple) for _, read in items) or bool(graph)  # entities need 2.4
        for index, (chosen, read) in enumerate(items):
            folder = 'assets/%d/' % index
            if isinstance(read, tuple):  # E16: (volume description, [slices]) — the original is named, not carried
                volume, slices = read; first = volume._wire_descriptor
                original = next(r for r in first['representations'] if r['kind'] != 'normalized')
                files = [put(folder + 'descriptor.json', (json.dumps(first, indent=2, allow_nan=False) + '\n').encode(), 'descriptor'),
                         put(folder + 'volume.json', volume._wire_data_bytes, 'normalized')]
                files += [put(folder + 'slice-%s-%d.json' % (x.axis, x.label), x.raw, 'slice') for x in slices]
                assets.append({'asset_id': first['asset_id'], 'revision': first['revision'], 'origin': first['origin'], 'profile': first['profile'],
                               'type': 'seismic-slice', 'name': None, 'files': files, 'history': first.get('history'), 'parents': first.get('parents', []),
                               'parent_visibility': first.get('parent_visibility', 'complete'),
                               'original': {'sha256': original['sha256'], 'bytes': original['bytes'], 'included': False},
                               'slices': [{'axis': x.axis, 'label': x.label, 'shape': [len(x.rows[1]), len(x.columns[1])], 'scope': x.scope} for x in slices],
                               'omissions': list(first.get('provenance', {}).get('omissions', [])) + ['The original volume is not included; it is identified by its SHA-256'],
                               'losses': sorted({loss for r in first.get('representations', []) for loss in r.get('losses', [])})})
                selection.append(chosen); continue
            if getattr(read, 'type', None) == 'seismic-volume': raise Refused('A seismic volume is exported as chosen slices; the complete volume is not exported.')
            if hasattr(read, '_wire_data_bytes'):  # E11 typed data: exact original, descriptor and data as served
                first = read._wire_descriptor
                files = [put(folder + TYPED_ORIGINALS[first['profile']], read.original, 'original'),
                         put(folder + 'descriptor.json', (json.dumps(first, indent=2, allow_nan=False) + '\n').encode(), 'descriptor'),
                         put(folder + 'data.json', read._wire_data_bytes, 'normalized')]
                assets.append({'asset_id': first['asset_id'], 'revision': first['revision'], 'origin': first['origin'], 'profile': first['profile'],
                               'type': first['scientific']['type'], 'name': None, 'files': files, 'history': first.get('history'), 'parents': first.get('parents', []),
                               'parent_visibility': first.get('parent_visibility', 'complete'), 'relationships': first.get('relationships'),
                               'omissions': list(first.get('provenance', {}).get('omissions', [])),
                               'losses': sorted({loss for r in first.get('representations', []) for loss in r.get('losses', [])})})
                selection.append({**chosen, 'curves': []}); continue
            files = [put(folder + 'original.las', read.artifact, 'original')]
            first = read._wire_descriptors[0]
            for wire_descriptor, wire_curve, body in zip(read._wire_descriptors, read._wire_curves, read._wire_curve_bytes):
                name = wire_curve['curve']; safe = _safe_name(name)
                files.append(put(folder + 'descriptor-' + safe + '.json', (json.dumps(wire_descriptor, indent=2, allow_nan=False) + '\n').encode(), 'descriptor', name))
                files.append(put(folder + 'curve-' + safe + '.json', body, 'normalized', name))  # exact served bytes (digest in the descriptor)
            omissions = list(first.get('provenance', {}).get('omissions', []))
            losses = sorted({loss for r in first.get('representations', []) for loss in r.get('losses', [])})
            assets.append({'asset_id': first['asset_id'], 'revision': first['revision'], 'origin': first['origin'], 'profile': first['profile'],
                           'name': (first.get('display') or {}).get('name') if isinstance(first.get('display'), dict) else None,
                           'files': files, 'history': first.get('history'), 'parents': first.get('parents', []),
                           'parent_visibility': first.get('parent_visibility', 'complete'), 'omissions': omissions, 'losses': losses})
            if typed_bundle: assets[-1]['type'] = 'well-log'
            selection.append(chosen)
        observations = {**({'groups': groups} if groups else {}), **({'groups_omitted': groups_omitted} if groups_omitted else {})}
        # The lowest version that expresses this content: 1.x for well logs, 2.x for typed data;
        # the minor rises only for observations (1) or the newer types (2), so older readers keep working.
        minor = max([1 if observations else 0, 4 if graph else 0] + [NEWER_TYPES.get(a.get('type'), 0) for a in assets])
        version = ('2' if typed_bundle else '1') + f'.{minor}.0'
        manifest = {'schema': SCHEMA_2 if typed_bundle else SCHEMA, 'bundle_version': version, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'exporter': {'name': 'ophiolite-sdk', 'version': __version__}, 'scope': 'selection', 'selection': selection, 'assets': assets,
                    'groups': None, 'recommendations': None, **({'observations': observations} if observations else {}),
                    **({'entities': graph['entities'], 'relationships': graph['relationships']} if graph else {}),
                    'limits': {'max_assets': MAX_ASSETS, 'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}, 'notice': NOTICE}
        raw = (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode()
        fd = os.open(staging / 'manifest.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as out: out.write(raw)
        (staging / '.owner').unlink()
        open_bundle(staging)  # the bundle checks as a reader would before it becomes visible
        # Claim the name exclusively, then swap the finished bundle in: a concurrent export
        # to the same destination fails at the claim and nothing is ever overwritten.
        try: os.mkdir(destination, 0o700)
        except FileExistsError: raise Refused('The destination already exists; choose a new folder.') from None
        os.replace(staging, destination)
        return open_bundle(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True); raise


def _alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


def plot_svg(curve, path, *, width=240, height=640):
    """A dependency-free depth track: missing samples break the line; nothing is filled."""
    points = [(a, v) for a, v in zip(curve.axis, curve.values)]
    finite = [v for _, v in points if v is not None]
    if not finite: raise Refused('This curve has no values to plot.')
    lo, hi = min(finite), max(finite); top, bottom = min(curve.axis), max(curve.axis)
    sx = lambda v: 20 + (width - 40) * ((v - lo) / (hi - lo) if hi > lo else 0.5)
    sy = lambda d: 20 + (height - 40) * ((d - top) / (bottom - top) if bottom > top else 0.5)
    segments, current = [], []
    for depth, value in points:
        if value is None:
            if current: segments.append(current); current = []
        else: current.append('%.2f,%.2f' % (sx(value), sy(depth)))
    if current: segments.append(current)
    lines = ''.join('<polyline fill="none" stroke="black" stroke-width="1" points="%s"/>' % ' '.join(s) for s in segments)
    label = '%s (%s)' % (curve.name, curve.unit or 'unit not stated')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d"><title>%s</title>%s'
           '<text x="20" y="14" font-size="11">%s</text></svg>\n') % (width, height, label, lines, label)
    Path(path).write_text(svg)
    return Path(path)
