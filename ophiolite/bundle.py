"""Portable bundles (``ophiolite.portable-bundle/1``): write, check and read offline.

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
    def __init__(self, entry, original, curves):
        self.entry = entry; self.asset_id = entry['asset_id']; self.revision = entry['revision']; self.name = entry.get('name')
        self.origin = entry['origin']; self.history = entry.get('history'); self.parents = entry['parents']
        self.parent_visibility = entry['parent_visibility']; self.original = original; self.curves = curves


class Bundle:
    def __init__(self, path, manifest, assets, unlisted):
        self.path, self.manifest, self.assets, self.unlisted = path, manifest, assets, unlisted

    def summary(self):
        return {'bundle_version': self.manifest['bundle_version'], 'scope': self.manifest['scope'], 'assets': len(self.assets),
                'curves': sum(len(a.curves) for a in self.assets), 'unlisted_files': self.unlisted,
                'groups': self.manifest['groups'], 'recommendations': self.manifest['recommendations']}


def _check_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA: raise VerificationFailed('This is not an Ophiolite portable bundle.')
    version = manifest.get('bundle_version')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version): raise VerificationFailed('The bundle version is not readable.')
    if version.split('.')[0] != '1': raise Refused('This bundle uses version %s; this reader supports major version 1. Update the SDK.' % version)
    if manifest.get('scope') != 'selection': raise VerificationFailed('The bundle scope is not a selection.')
    if manifest.get('groups', 0) is not None or manifest.get('recommendations', 0) is not None: raise VerificationFailed('Groups and recommendations are not part of bundle 1.0.')
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
            content.setdefault(item.get('role'), {})[item.get('curve')] = raw
        original = content.get('original', {}).get(None)
        curves = {}
        for name, raw in content.get('descriptor', {}).items():
            body = content.get('normalized', {}).get(name)
            if name is None or body is None: raise VerificationFailed('A descriptor has no matching curve file.')
            wire_descriptor = _finite_json(raw, 'A descriptor'); wire_view = _finite_json(body, 'A curve')
            if (wire_descriptor.get('asset_id'), wire_descriptor.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
                raise VerificationFailed('A descriptor belongs to another exact revision.')
            if original is None: raise VerificationFailed('The original bytes needed to verify this curve are missing.')
            model, view = _core.verify_pair(wire_descriptor, body, original, name)
            curves[name] = Curve(model, view, wire_descriptor, wire_view)
        if not curves: raise VerificationFailed('An asset carries no curves.')
        loaded.append(BundleAsset(entry, original, curves))
    listed = seen | {'manifest.json'}
    unlisted = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).as_posix() not in listed)
    return Bundle(root, manifest, loaded, unlisted)


def write_bundle(destination, items, *, grace=3600):
    """Write verified exact reads [(selection, CurveSet-like)] atomically. Internal to export."""
    destination = Path(destination)
    if destination.exists(): raise Refused('The destination already exists; choose a new folder.')
    if not 0 < len(items) <= MAX_ASSETS: raise Refused('Export between 1 and %d exact revisions.' % MAX_ASSETS)
    parent = destination.parent; parent.mkdir(parents=True, exist_ok=True)
    for stale in parent.glob('.' + destination.name + '.staging-*'):  # abandoned interrupted exports
        if time.time() - stale.stat().st_mtime > grace: shutil.rmtree(stale, ignore_errors=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.staging-', dir=parent)); os.chmod(staging, 0o700)
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
        for index, (chosen, read) in enumerate(items):
            folder = 'assets/%d/' % index
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
            selection.append(chosen)
        manifest = {'schema': SCHEMA, 'bundle_version': VERSION, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'exporter': {'name': 'ophiolite-sdk', 'version': __version__}, 'scope': 'selection', 'selection': selection, 'assets': assets,
                    'groups': None, 'recommendations': None,
                    'limits': {'max_assets': MAX_ASSETS, 'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}, 'notice': NOTICE}
        raw = (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode()
        fd = os.open(staging / 'manifest.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as out: out.write(raw)
        open_bundle(staging)  # the bundle checks as a reader would before it becomes visible
        os.replace(staging, destination)
        return open_bundle(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True); raise


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
