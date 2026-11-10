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
                   'opendtect-faultsticks/1': 'original.txt', 'wavelet-text/1': 'original.txt', 'model-section-text/1': 'original.txt', 'seismic-section-text/1': 'original.txt',
                   'time-depth-csv/1': 'original.csv', 'zmap-plus-grid/1': 'original.zmap', 'cps3-ascii-grid/1': 'original.cps3', 'irap-ascii-grid/1': 'original.irap',
                   'geojson/1': 'original.geojson', 'ogc-geopackage/1': 'original.gpkg',  # E56
                   'petrel-points-attributes/1': 'original.txt', 'opendtect-horizon-ascii/1': 'original.txt', 'esri-shapefile/1': 'original.shp',  # E23c: package primaries
                   'petrel-horizon-ilxl/1': 'original.txt',  # E123 s1b
                   'petrel-scattered-data/1': 'original.txt',  # E123 s1c: a grid or a point set, by its content
                   'petrel-faultsticks/1': 'original.txt'}  # E123 S1f-c: a packaged polyline set (bundle 2.11)
NEWER_TYPES = {'triangulated-surface': 2, 'point-set': 2, 'polyline-set': 3, 'seismic-slice': 3, 'wavelet': 5, 'model-section': 5, 'seismic-section': 5, 'time-depth': 6,
               'feature-set': 7, 'well-table': 17}  # the 2.x minor that introduced them
# E56: grids of the new formats are a known type with an original an older reader cannot send back; they need 2.7 too
NEWER_PROFILES = {'zmap-plus-grid/1': 7, 'cps3-ascii-grid/1': 7, 'irap-ascii-grid/1': 7,
                  'petrel-faultsticks/1': 11}  # E123 S1f-c: a packaged polyline set needs 2.11; other polyline sets keep their minor
TYPES_2 = ('well-log', 'well-tops', 'trajectory', 'regular-grid-surface', 'triangulated-surface', 'point-set', 'polyline-set', 'seismic-slice',
           'wavelet', 'model-section', 'seismic-section', 'time-depth', 'feature-set', 'well-table')  # 2.5 (E53); 2.6 (E57); 2.7 (E56); 2.17 (E162 s2a)
NOT_IMPORTED_PACKAGE = 'Importing a file that comes with companion files is not available yet.'
PACKAGE_TYPES, PACKAGE_ROLES, PACKAGE_MINOR = ('point-set', 'feature-set', 'polyline-set'), ('package', 'companion', 'interpretation'), 8  # E23c (bundle 2.8); polyline-set 2.11 (E123 S1f-c)
PROVENANCE_MINOR = 9  # E107a C6b (bundle 2.9): the original a file read on a computer was read from, beside its recorded reading
PROVENANCE_SHAPE = 'A file read on a computer carries its kept original once, beside the reading that names it, and on no curve.'
PROVENANCE_OTHER = 'The original kept beside this file is not the one its reading names.'
# E122 s5b (bundle 1.10 / 2.10): an asset may carry its version's source record inline, as the gateway served it; the
# major stays the content's, released readers ignore the key. `provenance` above stays E107a's kept original.
SOURCE_RECORD_MINOR = 10
SOURCE_RECORD_SCHEMA = 'ophiolite.source-provenance/1'
SOURCE_OTHER = 'A source record belongs to another exact revision.'
SOURCE_SHAPE = 'A source record is not an ophiolite.source-provenance/1 record.'
SOURCE_MINOR = 'A source record needs bundle version 1.10 or 2.10.'
SOURCE_TOO_LARGE = "The selection's records exceed the supported bundle manifest size."
# E116 s1 (bundle 2.12): a project folder block (ophiolite.project-folder/1) lists the files ophiolite-mapper write adds
# beside the assets; with it, and only with it, assets and selection may be empty, since a folder the box writes alone
# holds no exact server revision. The block is checked by the contract's own validator, mapper/v1/mapper.py.
FOLDER_MINOR = 12
FOLDER_NEEDS_MINOR = 'A project folder needs bundle version 2.12.'
FOLDER_CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'mapper' / 'v1' / 'mapper.py'
MAX_FOLDER_FILES = 1006  # folder-schema.json files.maxItems
_folder_module = None
# E117 s1 (bundle 2.14): a block may be ophiolite.project-folder/2, checked by contracts/folders/v1/folder.py, whose MINOR
# is the one answer to the least bundle minor of each folder schema. Its files are verified by folder_verdicts, the one
# traversal open_bundle and ophiolite.folder.check share.
FOLDER_2 = 'ophiolite.project-folder/2'
FOLDER_2_NEEDS_MINOR = 'A project folder of format /2 needs bundle version 2.%d.'
FOLDER_2_BESIDE_ASSETS = 'A /2 folder beside server assets is not read yet.'
FOLDERS_CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'folders' / 'v1' / 'folder.py'
_folders_module = None
FOLDER_SENTENCES = {'file-link': 'The folder file %s is a link or lies under one.',
                    'file-too-large': 'The folder file %s exceeds the supported size.',
                    'total-too-large': 'The bundle exceeds the supported total size.',
                    'file-missing': 'The folder file %s is missing or has the wrong size.',
                    'file-size': 'The folder file %s is missing or has the wrong size.',
                    'file-digest': 'The folder file %s does not match its checksum.'}
# E147 s0 (bundle 2.15): a manifest's citation lists the standard descriptors beside it at the root (RO-Crate, Croissant,
# DataCite) and a bundle's standalone prov.json, digested in the citation. The descriptors are not digested: each is
# compared, by contracts/descriptors/v1/descriptors.py, with what the manifest says. A refusal names its code, its file
# and the JSON path in it.
DESCRIPTORS_CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'descriptors' / 'v1' / 'descriptors.py'
_descriptors_module = None
CITATION_DESCRIPTOR, CITATION_PROV = 'citation-descriptor', 'citation-prov'  # their roles in ophiolite.folder.check's report
CITATION_SENTENCES = {'citation-minor': 'the citation needs bundle version 2.15',
                      'citation-schema': 'the citation in the manifest is not valid',
                      'citation-media-type': 'a file of the manifest has no media type, which a citation needs',
                      'notice-without-null-licence': 'the manifest gives an access notice beside an open licence',
                      'descriptor-repeated': 'the citation lists a descriptor twice'}
# E162 s2a (bundle 2.17): at most one well-table entry, the accepted rows a wells import kept (sql-wells/1), exactly as
# kept, beside the kept copy's source manifest as served. Checked by sources.verified_table; each well the bundle lists
# is located by exactly one of its rows. It is restored with its wells (ophiolite.restore), never uploaded.
WELL_TABLE, WELL_TABLE_PROFILE, WELL_TABLE_MINOR = 'well-table', 'sql-wells/1', NEWER_TYPES['well-table']
WELL_TABLE_RESTORED = 'A wells table is restored with its wells (`ophiolite.restore`), not uploaded'
WELL_TABLE_SHAPE = 'A wells table carries exactly its kept rows (original.json) and their source manifest (descriptor.json), and no curves.'
WELL_TABLE_RECORD = 'The source manifest of a wells table is not the record of its kept rows.'
WELL_TABLE_ONE = 'A bundle carries at most one wells table.'
WELL_TABLE_ROWS = 'An association of the wells table names a row it does not hold.'
WELL_TABLE_WELLS = 'Each well in a bundle with a wells table is located by exactly one of its rows.'
CITATION_FILE_SENTENCES = {'file-missing': '%s is missing or has the wrong size', 'file-size': '%s is missing or has the wrong size',
                           'file-digest': '%s does not match its checksum', 'file-link': '%s is a link or lies under one',
                           'file-too-large': '%s exceeds the supported size', 'total-too-large': 'the bundle exceeds the supported total size'}


class DescriptorRefused(VerificationFailed):
    """E147 s0 (D3): a citation or a descriptor the reader refuses. `code` is the contract's or the reader's code, `file`
    the file it is in, `json_path` the place in it (None for the file as a whole); `path` is ophiolite.folder.check's
    place (a manifest JSON path, a file name, or `file:json path`), `where` what --details prints, `sentence` the words."""

    def __init__(self, code, file, json_path=None, sentence=None):
        self.file, self.json_path = file, json_path
        self.where = file if json_path is None else '%s:%s' % (file, json_path)
        self.path = json_path if file == 'manifest.json' else self.where
        self.sentence = sentence or code
        super().__init__(self.sentence[0].upper() + self.sentence[1:] + '.', code=code)


NOT_IMPORTED_SYNTHETIC = ('A synthetic section is not imported: its model and wavelet are not part of the project it would join. '
                          'Import them and compute it again.')
SLICE_NAME = re.compile(r'^slice-(inline|crossline|sample)-(-?[0-9]{1,9})\.json$')
MAX_ASSETS = 128
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
PATH = re.compile(r'^assets/[0-9]{1,3}/[A-Za-z0-9._-]{1,120}$')
NOTICE = ('Checksums show the integrity of this copy, not authorship or scientific correctness. '
          'Exported copies cannot be recalled; holding one grants no new upstream, sharing or AI-training rights.')
# E147 s2 (D5): a cited export states each file's media type by its suffix; a suffix not listed is bytes (octet-stream).
MEDIA_TYPES = {'.las': 'text/plain', '.txt': 'text/plain', '.asc': 'text/plain', '.zmap': 'text/plain', '.cps3': 'text/plain',
               '.irap': 'text/plain', '.csv': 'text/csv', '.json': 'application/json', '.geojson': 'application/json',
               '.parquet': 'application/vnd.apache.parquet', '.tif': 'image/tiff', '.tiff': 'image/tiff'}
OCTET_STREAM = 'application/octet-stream'
CITED_RESOURCE_TYPES = ('Well log bundle', 'Dataset bundle')  # DataCite's resourceType: every asset a well log, or not


def media_type(path):
    """The media type a cited bundle states for the file at PATH (by its lower-case suffix)."""
    return MEDIA_TYPES.get(PurePosixPath(path).suffix.lower(), OCTET_STREAM)


def recorded_reading(descriptor):
    """E107a (B2): the reading an item records: its own (`acquisition.read_by`), or the one its import kept as recorded
    (`acquisition.origin.read_by`); None for any other item."""
    acquisition = descriptor.get('acquisition') if isinstance(descriptor, dict) else None
    if not isinstance(acquisition, dict): return None
    return acquisition.get('read_by') or (acquisition.get('origin') or {}).get('read_by')


def recorded_source(descriptor):
    """E108 S1 (5R-8): the source procedure an item records: its own (`acquisition.sourced_by`), or the one its import
    kept as recorded (`acquisition.origin.sourced_by`); None for any other item."""
    acquisition = descriptor.get('acquisition') if isinstance(descriptor, dict) else None
    if not isinstance(acquisition, dict): return None
    return acquisition.get('sourced_by') or (acquisition.get('origin') or {}).get('sourced_by')


def _listed_provenance(descriptor):
    """(sha256, bytes) of the `provenance` row the descriptor's manifest lists, None when it lists none, or False
    without a manifest (a descriptor served before E107a, or a fixture)."""
    manifest = descriptor.get('manifest')
    if not isinstance(manifest, dict): return False
    row = next((r for r in manifest.get('representations') or [] if isinstance(r, dict) and r.get('id') == 'provenance'), None)
    return None if row is None else (row.get('sha256'), row.get('bytes'))


def _kept_of(read, descriptor):
    """C6b (writer): (bytes, reading, file name) of a read whose original was kept, or None. The bytes are bound to the
    reading's original and to the manifest listing before anything is written (B1)."""
    raw = getattr(read, 'provenance', None)
    if raw is None: return None
    record = recorded_reading(descriptor)
    listed = _listed_provenance(descriptor)
    found = (hashlib.sha256(raw).hexdigest(), len(raw))
    if not isinstance(record, dict) or found != ((record.get('original') or {}).get('sha256'), (record.get('original') or {}).get('bytes')) \
            or listed is None or (listed is not False and listed != found) or record.get('kept') not in (None, found[0]):
        raise VerificationFailed(PROVENANCE_OTHER)
    suffix = PurePosixPath(record['original'].get('name') or '').suffix.lower()
    return raw, record, 'provenance' + (suffix if re.fullmatch(r'\.[a-z0-9]{1,8}', suffix) else '.bin')


def _kept_check(entry, files, content, descriptor):
    """C6b (reader, B1): exactly one `provenance` file, on no curve, beside the entry's reading; the reading is the one the
    descriptor records; the bytes are the reading's original and the row the descriptor's manifest lists."""
    listed = [f for f in files if f.get('role') == 'provenance']
    if 'read_by' not in entry: return None, None  # a provenance file without a reading is an unknown role (refused above)
    record = entry['read_by']
    if len(listed) != 1 or listed[0].get('curve') is not None or not isinstance(record, dict): raise VerificationFailed(PROVENANCE_SHAPE)
    if record != recorded_reading(descriptor): raise VerificationFailed('The manifest disagrees with a descriptor (read_by).')
    raw = content['provenance'][None]
    found = (hashlib.sha256(raw).hexdigest(), len(raw))
    original = record.get('original') if isinstance(record.get('original'), dict) else {}
    named = _listed_provenance(descriptor)
    if found != (original.get('sha256'), original.get('bytes')) or named is None or (named is not False and named != found) or record.get('kept') not in (None, found[0]):
        raise VerificationFailed(PROVENANCE_OTHER)
    return raw, record


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
        self.package = None  # 2.8 (E23c): the source package, its companions and interpretation (bundle_package.Package)
        self.provenance, self.read_by = None, None  # 2.9 (E107a): the kept original a file read on a computer was read from, and that reading
        self.source_record = None  # 1.10/2.10 (E122 s5b): the version's source-provenance/1 record as served, or None


class WellTable:
    """E162 s2a (2.17): a wells import's kept rows, verified: `original` the kept bytes (their sha256 is the revision),
    `source_schema` and `source_rows` the table as read, `wells` one mapped row per source row (by `well_id`),
    `mapping` the reviewed mapping, `descriptor` the kept copy's source manifest as served. The writer's read and the
    reader's `BundleAsset.data` alike."""
    type = WELL_TABLE

    def __init__(self, original, descriptor, name=None):
        from .sources import verified_table
        revision = hashlib.sha256(original).hexdigest()
        reference = descriptor.get('reference') if isinstance(descriptor, dict) else None
        if (not isinstance(reference, dict) or descriptor.get('schema') != 'ophiolite.source-snapshot/1'
                or (reference.get('profile'), reference.get('revision'), descriptor.get('sha256'), descriptor.get('bytes')) != (WELL_TABLE_PROFILE, revision, revision, len(original))):
            raise VerificationFailed(WELL_TABLE_RECORD)
        self.original, self.descriptor, self._wire_descriptor, self.revision, self.name = original, descriptor, descriptor, revision, name
        self.source_schema, self.source_rows, self.wells, self.mapping = verified_table(_finite_json(original, 'A wells table'))


class Bundle:
    def __init__(self, path, manifest, assets, unlisted):
        self.path, self.manifest, self.assets, self.unlisted = path, manifest, assets, unlisted
        # 1.1/2.1: result groups as observed at export time (members by position; not scientific truth).
        self.groups = (manifest.get('observations') or {}).get('groups') or []
        self.entities, self.relationships = [], []  # 2.4 (E20), set by open_bundle after checking
        self.folder = []  # 2.12 (E116 s1): the verified rows of the project folder block, set by open_bundle
        self.items = []  # 2.14 (E117 s1): the folder's items, the /2 block's own or translate_1's reading of a /1 block
        self.citation = []  # 2.15 (E147 s0): the verified files the citation lists at the root, [{path, role}]

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
                'groups': self.manifest['groups'], 'recommendations': self.manifest['recommendations'],
                **({'entities_omitted': (self.manifest.get('observations') or {})['entities_omitted']} if (self.manifest.get('observations') or {}).get('entities_omitted') else {}),
                **({'source_records': sum(a.source_record is not None for a in self.assets)} if any(a.source_record is not None for a in self.assets) else {}),
                **({'source_records_omitted': (self.manifest.get('observations') or {})['source_records_omitted']}
                   if (self.manifest.get('observations') or {}).get('source_records_omitted') else {}),  # E122 s5b: only when there is something to say
                **({'folder_files': len(self.folder)} if self.folder else {})}  # E116 s1: the project folder's files, verified


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
    folder = 'folder' in manifest
    folder_2 = folder and isinstance(manifest['folder'], dict) and manifest['folder'].get('schema') == FOLDER_2
    if folder and (manifest['schema'] != SCHEMA_2 or int(version.split('.')[1]) < FOLDER_MINOR): raise VerificationFailed(FOLDER_NEEDS_MINOR)
    if folder_2 and int(version.split('.')[1]) < _folders_contract().MINOR[FOLDER_2]:  # E117 s1: the contract's minor
        raise VerificationFailed(FOLDER_2_NEEDS_MINOR % _folders_contract().MINOR[FOLDER_2])
    assets = manifest.get('assets')
    if not isinstance(assets, list) or not (0 if folder else 1) <= len(assets) <= MAX_ASSETS: raise VerificationFailed('The bundle lists no assets or too many.')
    if folder: _folder_valid(manifest)
    if folder_2 and assets: raise VerificationFailed(FOLDER_2_BESIDE_ASSETS)
    return assets


def _folder_contract():
    """The packaged mapper validator (contracts/mapper/v1/mapper.py), loaded once from its source text."""
    global _folder_module
    if _folder_module is None:
        import types
        module = types.ModuleType('ophiolite_mapper_contract')
        module.__file__ = str(FOLDER_CONTRACT)
        exec(compile(FOLDER_CONTRACT.read_text(encoding='utf-8'), str(FOLDER_CONTRACT), 'exec'), module.__dict__)
        _folder_module = module
    return _folder_module


def _folders_contract():
    """The packaged project folder validator (contracts/folders/v1/folder.py, /2 and the /1 dispatch), loaded once."""
    global _folders_module
    if _folders_module is None:
        import types
        module = types.ModuleType('ophiolite_folder_contract')
        module.__file__ = str(FOLDERS_CONTRACT)
        exec(compile(FOLDERS_CONTRACT.read_text(encoding='utf-8'), str(FOLDERS_CONTRACT), 'exec'), module.__dict__)
        _folders_module = module
    return _folders_module


def _descriptors_contract():
    """The packaged descriptors contract (contracts/descriptors/v1/descriptors.py), loaded once from its source text."""
    global _descriptors_module
    if _descriptors_module is None:
        import types
        module = types.ModuleType('ophiolite_descriptors_contract')
        module.__file__ = str(DESCRIPTORS_CONTRACT)
        exec(compile(DESCRIPTORS_CONTRACT.read_text(encoding='utf-8'), str(DESCRIPTORS_CONTRACT), 'exec'), module.__dict__)
        _descriptors_module = module
    return _descriptors_module


def _refused(error):
    """A contract DescriptorError as the reader's DescriptorRefused, with its words."""
    contract = _descriptors_contract()
    words = CITATION_SENTENCES.get(error.code) or contract.sentence(error)
    return DescriptorRefused(error.code, error.file, error.path, words)


def citation_valid(manifest):
    """E147 s0: raise DescriptorRefused for the first problem of a manifest's citation block (its minor, the block, a
    media type on every asset row); return the files it lists at the root, prov.json first, then the descriptors in
    their order. [] for a manifest without a citation."""
    if not isinstance(manifest, dict) or 'citation' not in manifest: return []
    contract = _descriptors_contract()
    try: citation = contract.validate_citation(manifest)
    except contract.DescriptorError as error: raise _refused(error) from None
    return ([citation['prov']['path']] if 'prov' in citation else []) + list(citation['descriptors'])


def citation_names(manifest):
    """The root files a manifest's citation names, read without validating it (what is listed, for the unlisted
    report beside a refused citation): known descriptor names and a prov path given as text."""
    citation = manifest.get('citation') if isinstance(manifest, dict) else None
    if not isinstance(citation, dict): return []
    contract = _descriptors_contract()
    prov = citation.get('prov')
    names = [prov['path']] if isinstance(prov, dict) and prov.get('path') == contract.PROV_PATH else []
    return names + [n for n in citation.get('descriptors') or [] if isinstance(n, str) and n in contract.NAMES]


def citation_verdicts(root, manifest, total):
    """E147 s0 (D3): the citation's own files, checked after the asset and folder files. Returns ([{path, role,
    verdict}], first DescriptorRefused or None, total). The block is validated first (a refusal there names the
    manifest and lists no row). prov.json is a digested file (folder_verdicts' codes); each descriptor goes through the
    same guards (no link, a regular file, MAX_FILE_BYTES and the running total; a fault is descriptor-unreadable, an
    absent file file-missing), then is parsed and compared with the manifest by the contract."""
    try: names = citation_valid(manifest)
    except DescriptorRefused as error: return [], error, total
    if not names: return [], None, total
    contract = _descriptors_contract()
    citation, files, tables = contract.inputs(manifest)
    rows, first = [], None
    if 'prov' in citation:
        prov = citation['prov']
        (verdict,), total = folder_verdicts(root, [prov], total)
        rows.append({'path': prov['path'], 'role': CITATION_PROV, 'verdict': verdict})
        if verdict != 'ok': first = DescriptorRefused(verdict, prov['path'], None, CITATION_FILE_SENTENCES[verdict].replace('%s', prov['path']))
    for name in citation['descriptors']:
        target, error = root / name, None
        if target.is_symlink(): error = contract.DescriptorError('descriptor-unreadable', name)
        elif not target.exists(): error = DescriptorRefused('file-missing', name, None, CITATION_FILE_SENTENCES['file-missing'] % name)
        elif not target.is_file() or target.stat().st_size > MAX_FILE_BYTES or total + target.stat().st_size > MAX_TOTAL_BYTES:
            error = contract.DescriptorError('descriptor-unreadable', name)
        else:
            raw = target.read_bytes(); total += len(raw)
            try: error = contract._disagreement(name, contract.parse(name, raw), citation, files, tables)
            except contract.DescriptorError as refused: error = refused
        if isinstance(error, contract.DescriptorError): error = _refused(error)
        rows.append({'path': name, 'role': CITATION_DESCRIPTOR, 'verdict': 'ok' if error is None else error.code})
        if error is not None and first is None: first = error
    return rows, first, total


def _folder_valid(manifest, recipe=None):
    """2.12 (E116 s1): refuse a folder block the contract's validator refuses, naming its rule and place. 2.14 (E117 s1):
    a /2 block goes to the folders contract's validator (its recipe digest is its rule), any other to the mapper's."""
    block = manifest['folder']
    if isinstance(block, dict) and block.get('schema') == FOLDER_2:
        contract = _folders_contract()
        check, error_type = (lambda: contract.validate(block, manifest)), contract.FolderError
    else:
        contract = _folder_contract()
        check, error_type = (lambda: contract.validate_folder(block, manifest, recipe)), contract.MapperError
    try: check()
    except error_type as error: raise VerificationFailed('The project folder block is not valid (%s at %s).' % (error.code, error.path)) from None


def folder_verdicts(root, rows, total):
    """E117 s1 (D1): the one traversal of a folder block's files, shared by open_bundle and ophiolite.folder.check. Each
    row is verified as an asset file is (no link on the way, the file and total limits, size, SHA-256). Returns
    ([verdict per row], total): 'ok' or the code of that file's first fault."""
    verdicts = []
    for row in rows:
        parts = PurePosixPath(row['path']).parts
        target = root / row['path']
        if any(root.joinpath(*parts[:depth]).is_symlink() for depth in range(1, len(parts) + 1)): verdict = 'file-link'
        elif row['bytes'] > MAX_FILE_BYTES: verdict = 'file-too-large'
        elif total + row['bytes'] > MAX_TOTAL_BYTES: verdict, total = 'total-too-large', total + row['bytes']
        else:
            total += row['bytes']
            if not target.is_file(): verdict = 'file-missing'
            elif target.stat().st_size != row['bytes']: verdict = 'file-size'
            elif hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']: verdict = 'file-digest'
            else: verdict = 'ok'
        verdicts.append(verdict)
    return verdicts, total


def _folder_files(root, manifest, total):
    """2.12 (E116 s1): verify every file of the folder block (folder_verdicts), the first fault refused with its sentence
    naming the path; then bind a /1 block's items to the verified recipe (a /2 block's recipe is bound by its digest)."""
    block = manifest['folder']
    rows = block['files']
    verdicts, _ = folder_verdicts(root, rows, total)
    for row, verdict in zip(rows, verdicts):
        if verdict != 'ok': raise VerificationFailed(FOLDER_SENTENCES[verdict].replace('%s', row['path']))
    if block['schema'] != FOLDER_2: _folder_valid(manifest, _finite_json((root / 'recipe.json').read_bytes(), 'The folder recipe'))
    return [dict(row) for row in rows]


def _folder_items(root, block, rows):
    """2.14 (E117 s1): the items of a verified folder block: a /2 block's own, or translate_1's reading of a /1 block
    from its verified recipe and lineage (never guessed); none when a /1 block lists no item file."""
    if block['schema'] == FOLDER_2: return [dict(item) for item in block['items']]
    if not any(row['role'] == 'item' for row in rows): return []
    activity = {}  # the lineage is a verified file the /1 validator does not read: a row count only where it states one
    if any(r['role'] == 'lineage-prov' for r in rows):
        try: prov = _finite_json((root / 'lineage' / 'prov.json').read_bytes(), 'The folder lineage')
        except VerificationFailed: prov = {}
        found = prov.get('activity') if isinstance(prov, dict) else None
        activity = {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}
    recipe = _finite_json((root / 'recipe.json').read_bytes(), 'The folder recipe')
    return _folders_contract().translate_1(block, recipe, {'activity': activity})['items']


ZIP_RATIO = 100  # largest accepted uncompressed/compressed ratio per entry
MAX_ENTRIES = 1 + MAX_ASSETS * 131 + MAX_FOLDER_FILES + 4  # E147 s0: prov.json and three descriptors
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def pack(folder, destination):
    """Write a verified bundle folder as one deterministic `.zip` (manifest first, sorted entries, fixed
    times and permissions). Refuses unlisted files and names that collide ignoring case; never
    overwrites; a failed pack leaves nothing."""
    import zipfile, zlib
    opened = open_bundle(folder)
    if opened.unlisted: raise Refused('The bundle folder holds files it does not list (%s); remove them before packing.' % ', '.join(opened.unlisted[:3]))
    names = sorted([item['path'] for entry in opened.manifest['assets'] for item in entry['files']] + [row['path'] for row in opened.folder]
                   + [row['path'] for row in opened.citation])  # E147 s0: prov.json and the descriptors
    if len({n.lower() for n in names + ['manifest.json']}) != len(names) + 1: raise Refused('Two bundle paths differ only in letter case; a zip would not keep both.')
    destination = Path(destination)
    if destination.exists(): raise Refused('The destination already exists; choose a new file.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.packing-', dir=destination.parent); os.close(handle)
    try:
        with zipfile.ZipFile(temporary, 'w') as archive:
            for name in ['manifest.json'] + names:
                data = (opened.path / name).read_bytes()
                info = zipfile.ZipInfo(name, date_time=FIXED_TIME); info.external_attr = 0o100600 << 16
                deflated = len(zlib.compress(data, 9)) if data else 0
                info.compress_type = zipfile.ZIP_DEFLATED if data and len(data) <= deflated * ZIP_RATIO else zipfile.ZIP_STORED
                archive.writestr(info, data, compresslevel=9 if info.compress_type == zipfile.ZIP_DEFLATED else None)
        try: os.link(temporary, destination)  # claims the name only if nobody else has
        except FileExistsError: raise Refused('The destination already exists; choose a new file.') from None
        return destination
    finally:
        os.unlink(temporary)


def _open_zip(path):
    """Check a zip before extracting anything, then extract into a private folder the bundle owns."""
    import stat, weakref, zipfile
    try: archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError): raise VerificationFailed('This is not a readable bundle archive.') from None
    with archive:
        infos = archive.infolist()
        if not 0 < len(infos) <= MAX_ENTRIES: raise VerificationFailed('The archive holds no entries or too many.')
        seen, total = set(), 0
        folder_path = re.compile(_folder_contract().FOLDER_SCHEMA['$defs']['file']['properties']['path']['pattern'])  # 2.12 (E116 s1)
        folder_2_path = re.compile(_folders_contract().SCHEMA['$defs']['file']['properties']['path']['pattern'])  # 2.14 (E117 s1): items/<name>.tif
        cited = set(_descriptors_contract().NAMES) | {_descriptors_contract().PROV_PATH}  # 2.15 (E147 s0): at the root, if listed
        for info in infos:
            name = info.filename
            if name != 'manifest.json' and name not in cited and (not (PATH.fullmatch(name) or folder_path.fullmatch(name) or folder_2_path.fullmatch(name)) or set(PurePosixPath(name).parts) & {'.', '..'} or name.split('/')[-1] in ('.', '..')):
                raise VerificationFailed('An archive entry name is unsafe or outside the bundle layout.')
            if name.lower() in seen: raise VerificationFailed('Two archive entries have the same name (ignoring letter case).')
            seen.add(name.lower())
            kind = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or (kind and kind != stat.S_IFREG): raise VerificationFailed('An archive entry is a link, folder or special file.')
            limit = MAX_MANIFEST_BYTES if name == 'manifest.json' else MAX_FILE_BYTES
            if info.file_size > limit: raise VerificationFailed('An archive entry exceeds the supported size.')
            if info.compress_size and info.file_size > info.compress_size * ZIP_RATIO: raise VerificationFailed('An archive entry is compressed beyond the supported ratio.')
            total += info.file_size
            if total > MAX_TOTAL_BYTES: raise VerificationFailed('The archive exceeds the supported total size.')
        if 'manifest.json' not in {i.filename for i in infos}: raise VerificationFailed('The archive has no bundle manifest.')
        def read(info):
            data = b''
            with archive.open(info) as stream:  # never more than the declared size; the CRC check follows
                while True:
                    chunk = stream.read(1 << 20)
                    if not chunk: break
                    data += chunk
                    if len(data) > info.file_size: raise VerificationFailed('An archive entry is larger than it declares.')
            return data
        try:
            manifest = _finite_json(read(archive.getinfo('manifest.json')), 'The bundle manifest')
            entries = _check_manifest(manifest)
            listed = {item.get('path') for entry in entries for item in (entry.get('files') or []) if isinstance(item, dict)}
            listed |= {row['path'] for row in manifest['folder']['files']} if 'folder' in manifest else set()  # validated by _check_manifest
            listed |= set(citation_valid(manifest))  # E147 s0: the citation block validated before extraction
            if {i.filename for i in infos} != listed | {'manifest.json'}: raise VerificationFailed('The archive holds entries its manifest does not list, or lacks listed ones.')
            staging = Path(tempfile.mkdtemp(prefix='ophiolite-bundle-')); os.chmod(staging, 0o700)
            try:
                for info in infos:
                    target = staging / info.filename; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'wb') as out: out.write(read(info))
                bundle = open_bundle(staging)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True); raise
        except zipfile.BadZipFile as error:
            raise VerificationFailed('The archive is damaged (%s).' % str(error)[:80]) from None
    bundle.archive = Path(path)
    bundle.close = weakref.finalize(bundle, shutil.rmtree, staging, True)
    return bundle


def open_bundle(path):
    """Check a bundle completely, then return its verified contents. Offline. `path` is a bundle folder
    or a `.zip` written by `pack` (checked before anything is extracted)."""
    from . import _core
    if Path(path).is_file() and not Path(path).is_symlink(): return _open_zip(path)
    root = Path(path)
    if root.is_symlink() or not root.is_dir(): raise VerificationFailed('A bundle is a directory.')
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file(): raise VerificationFailed('The bundle has no manifest.')
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES: raise VerificationFailed('The bundle manifest is too large.')
    manifest = _finite_json(manifest_path.read_bytes(), 'The bundle manifest')
    entries = _check_manifest(manifest)
    citation_valid(manifest)  # E147 s0: the citation block before any content is used
    selection = manifest.get('selection')
    if not isinstance(selection, list) or len(selection) != len(entries): raise VerificationFailed('The selection and the assets disagree.')
    records = [_source_record_of(manifest, entry) for entry in entries]  # E122 s5b (D4): before any content is used
    seen, total, loaded = set(), 0, []
    for index, entry in enumerate(entries):
        files = entry.get('files')
        if not isinstance(files, list) or not files: raise VerificationFailed('An asset lists no files.')
        content, raw_by_path = {}, {}
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
            content.setdefault(item.get('role'), {})[relative if item.get('role') in ('slice', 'companion') else item.get('curve')] = raw
            raw_by_path[relative] = raw
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
        if kind == WELL_TABLE:  # 2.17 (E162 s2a): the kept rows and their source manifest; the rows are checked with the graph
            loaded.append(_well_table_asset(manifest, entry, chosen, content, files)); continue
        known = {'original', 'descriptor', 'normalized'} | (set(PACKAGE_ROLES) if kind in PACKAGE_TYPES else set())  # 2.8 (E23c)
        if manifest['schema'] == SCHEMA_2 and 'read_by' in entry: known.add('provenance')  # 2.9 (E107a): only beside a reading
        if roles.count('original') != 1 or set(roles) - known:
            raise VerificationFailed('Bundle 1.0 carries exactly one original per asset and only known file roles.')
        if kind != 'well-log':
            typed = _typed_asset(entry, chosen, content, files, kind, raw_by_path.__getitem__)
            typed.provenance, typed.read_by = _kept_check(entry, files, content, typed.data._wire_descriptor)
            loaded.append(typed); continue
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
        las = BundleAsset(entry, original, curves)
        las.provenance, las.read_by = _kept_check(entry, files, content, next(iter(curves.values())).wire_descriptor)
        loaded.append(las)
    _check_groups(manifest, entries)
    entities, relationships = _check_graph(manifest, entries)
    _check_well_table(loaded, entities, relationships)  # 2.17 (E162 s2a)
    folder = _folder_files(root, manifest, total) if 'folder' in manifest else []  # 2.12 (E116 s1)
    cited, refused, _ = citation_verdicts(root, manifest, total + sum(row['bytes'] for row in folder))  # E147 s0 (D3)
    if refused is not None: raise refused
    listed = seen | {'manifest.json'} | {row['path'] for row in folder} | {row['path'] for row in cited}
    unlisted = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).as_posix() not in listed)
    for asset, record in zip(loaded, records): asset.source_record = record  # one loaded asset per entry, in order
    bundle = Bundle(root, manifest, loaded, unlisted)
    bundle.entities, bundle.relationships = entities, relationships
    bundle.folder = folder
    bundle.citation = [{'path': row['path'], 'role': row['role']} for row in cited]  # 2.15 (E147 s0): prov.json and the descriptors, verified
    bundle.items =_folder_items(root, manifest['folder'], folder) if folder else []  # 2.14 (E117 s1)
    return bundle


def _text(value, most, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and 0 < len(value) <= most)


def _closed(value, required, optional=()):
    return isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional)


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def source_record_valid(record):
    """`ophiolite.source-provenance/1` as its schema says, on the parsed dict, which it never changes: every object
    closed, the required keys, constants, the id scheme, digests and lengths; a path's `part` optional. (The generated
    models are open, so they are not the check here.)"""
    if not _closed(record, ('schema', 'identity', 'content', 'context')) or record['schema'] != SOURCE_RECORD_SCHEMA: return False
    identity, content, context = record['identity'], record['content'], record['context']
    if not (_closed(identity, ('source_system', 'source_instance', 'id_scheme', 'source_object_id')) and _text(identity['source_system'], 160)
            and _text(identity['source_instance'], 160, True) and identity['id_scheme'] in ('source-native', 'source-path', 'none')): return False
    named = identity['source_object_id']
    if named is not None and not ((_closed(named, ('path',), ('part',)) and _text(named['path'], 1024) and _text(named.get('part'), 128, True))
                                  or (_closed(named, ('container', 'id')) and _text(named['container'], 256, True) and _text(named['id'], 256))): return False
    return (_closed(content, ('content_sha256', 'source_version')) and _digest(content['content_sha256']) and _text(content['source_version'], 256, True)
            and _closed(context, ('comparison', 'context_sha256')) and context['comparison'] == 'comparison/1' and _digest(context['context_sha256']))


def _source_record_of(manifest, entry):
    """E122 s5b (D4): an entry's `source_record`, checked: the served identity of this exact revision, a valid record,
    in a bundle whose version says it may carry records; None when the entry has none."""
    if not isinstance(entry, dict) or 'source_record' not in entry: return None
    if int(manifest['bundle_version'].split('.')[1]) < SOURCE_RECORD_MINOR: raise VerificationFailed(SOURCE_MINOR)
    held = entry['source_record']
    if not _closed(held, ('schema', 'asset_id', 'revision', 'record')) or held['schema'] != SOURCE_RECORD_SCHEMA: raise VerificationFailed(SOURCE_SHAPE)
    if (held['asset_id'], held['revision']) != (entry.get('asset_id'), entry.get('revision')): raise VerificationFailed(SOURCE_OTHER)
    if not source_record_valid(held['record']): raise VerificationFailed(SOURCE_SHAPE)  # its lengths bound its size
    return held['record']


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
            if 'row' in subject and (not p.get('row_scoped') or not isinstance(subject['row'], str) or not 0 < len(subject['row']) <= 160):  # E29
                raise VerificationFailed('A relationship names a row its predicate does not scope.')
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

    def rows(self):
        """E29: [(asset_id, revision, row)] associated with this entity; row is None for a whole revision."""
        return [(r['subject']['asset_id'], r['subject']['revision'], r['subject'].get('row')) for r in self._relationships
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


def _typed_asset(entry, chosen, content, files, kind, raw_of):
    from . import _core, bundle_package
    if chosen.get('curves') != [] or [r for r in roles_of(files) if r not in PACKAGE_ROLES + ('provenance',)] != ['descriptor', 'normalized', 'original'] \
            or any(item.get('curve') is not None for item in files if item.get('role') != 'provenance'):  # 2.9: the kept original is checked with its reading
        raise VerificationFailed('A typed asset carries exactly one original, one descriptor and one data file, and no curves.')
    from .typed import COLUMNS_FILE, data_file_of
    wire_descriptor = _finite_json(content['descriptor'][None], 'A descriptor'); body = content['normalized'][None]
    # E139 s2: the data file is named by its codec (a .json name only for JSON bytes); columns are checked by their reader
    columns = data_file_of(wire_descriptor) == COLUMNS_FILE
    if columns != next(f['path'] for f in files if f.get('role') == 'normalized').endswith('.ophpts'):
        raise VerificationFailed('A data file is not named by its codec.')
    if not columns: _finite_json(body, 'Typed data')
    if (wire_descriptor.get('asset_id'), wire_descriptor.get('revision')) != (entry.get('asset_id'), entry.get('revision')):
        raise VerificationFailed('A descriptor belongs to another exact revision.')
    if (wire_descriptor.get('scientific') or {}).get('type') != kind: raise VerificationFailed('The manifest disagrees with a descriptor (type).')
    for field in ('origin', 'profile', 'parents', 'parent_visibility', 'relationships'):
        if wire_descriptor.get(field, 'complete' if field == 'parent_visibility' else None) != entry.get(field): raise VerificationFailed('The manifest disagrees with a descriptor (' + field + ').')
    package = bundle_package.check(entry, files, raw_of, wire_descriptor, {} if columns else json.loads(body))  # 2.8 (E23c): before the data is used
    data = _core.typed_result(wire_descriptor, body, content['original'][None])
    loaded = BundleAsset(entry, content['original'][None], {}, data); loaded.package = package
    return loaded


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


def _well_table_asset(manifest, entry, chosen, content, files):
    """E162 s2a (2.17): a wells table: the kept rows as kept, their sha256 the revision, beside the kept copy's source
    manifest; the table passes sources.verified_table (WellTable). Its associations are checked by _check_well_table."""
    if int(manifest['bundle_version'].split('.')[1]) < WELL_TABLE_MINOR: raise VerificationFailed('A wells table needs bundle version 2.%d.' % WELL_TABLE_MINOR)
    named = sorted((item.get('role'), PurePosixPath(item['path']).name) for item in files)
    if chosen.get('curves') != [] or named != [('descriptor', 'descriptor.json'), ('original', 'original.json')] or any(item.get('curve') is not None for item in files) \
            or entry.get('profile') != WELL_TABLE_PROFILE or any(key in entry for key in ('read_by', 'package')):
        raise VerificationFailed(WELL_TABLE_SHAPE)
    raw = content['original'][None]
    if hashlib.sha256(raw).hexdigest() != entry.get('revision'): raise VerificationFailed('A wells table is not the exact revision it names.')
    if entry.get('origin') != 'retained-capture' or entry.get('parents') != [] or entry.get('parent_visibility') != 'complete':
        raise VerificationFailed('The manifest disagrees with a wells table (origin).')
    table = WellTable(raw, _finite_json(content['descriptor'][None], 'A descriptor'), entry.get('name'))
    return BundleAsset(entry, raw, {}, table)


def _check_well_table(loaded, entities, relationships):
    """E162 s2a (2.17): at most one wells table; every association of it is of-entity and names one of its rows, each row
    at most once; every listed well is located by exactly one of its rows. Nothing for a bundle without one."""
    tables = [a for a in loaded if a.type == WELL_TABLE]
    if not tables: return
    if len(tables) > 1: raise VerificationFailed(WELL_TABLE_ONE)
    table = tables[0]; rows = {w['well_id'] for w in table.data.wells}
    edges = [r for r in relationships if r['subject'].get('kind') == 'revision' and (r['subject'].get('asset_id'), r['subject'].get('revision')) == (table.asset_id, table.revision)]
    named = [r['subject'].get('row') for r in edges]
    if any(r['predicate'] != 'of-entity' for r in edges) or not set(named) <= rows or len(set(named)) != len(named): raise VerificationFailed(WELL_TABLE_ROWS)
    located = [r['object']['entity_id'] for r in edges]
    if any(located.count(e.entity_id) != 1 for e in entities if e.kind == 'well'): raise VerificationFailed(WELL_TABLE_WELLS)


def roles_of(files):
    return sorted(item.get('role') for item in files)


def horizon_too_large(read):
    """E139 s3 (O1, K4): the sentence refusing a typed point set whose original file or point data is above the bundle's
    per-file cap (original first, as it is written first); None when both fit or READ is not a typed point set. For a
    columns body the sentence adds a columns-only estimate of the nodes a bundle file holds: the cap less this body's
    own header, over 8 bytes for each of its columns."""
    if getattr(read, 'type', None) != 'point-set' or not hasattr(read, '_wire_data_bytes'): return None
    limit = 'a bundle file holds at most {:,} bytes'.format(MAX_FILE_BYTES)
    original, data = read.original or b'', read._wire_data_bytes
    if len(original) > MAX_FILE_BYTES:
        return "This horizon's original file is {:,} bytes; {}. Export the original file on its own. Nothing was written.".format(len(original), limit)
    if len(data) <= MAX_FILE_BYTES: return None
    from .point_columns import MAGIC
    if data[:len(MAGIC)] == MAGIC:
        start = len(MAGIC) + 4
        size = int.from_bytes(data[len(MAGIC):start], 'little')
        columns = len(json.loads(data[start:start + size])['columns'])
        limit += ' (about {:,} nodes with its {} columns)'.format((MAX_FILE_BYTES - start - size) // (8 * columns), columns)
    return "This horizon's point data is {:,} bytes; {}. Export the original file on its own. Nothing was written.".format(len(data), limit)


def write_bundle(destination, items, *, grace=3600, groups=None, groups_omitted=None, graph=None, entities_omitted=None, source_records_omitted=None,
                 citation=None):
    """Write verified exact reads [(selection, CurveSet-like)] atomically. Internal to export.

    E147 s2 (D5): with CITATION (a complete `ophiolite.citation/1` block) the bundle is schema 2 at 2.15 or above, every
    file row states its media type, and the descriptors the citation lists are written beside the manifest before the
    bundle checks itself; without one the bytes are as before. E147 s2b: a cited bundle with a typed table (well tops, a
    deviation survey, a time-depth table or a point set in data.json) is 2.16 or above, its Croissant file holding a
    record set per table."""
    from .typed import data_file_of
    destination = Path(destination)
    if destination.exists(): raise Refused('The destination already exists; choose a new folder.')
    if not 0 < len(items) <= MAX_ASSETS: raise Refused('Export between 1 and %d exact revisions.' % MAX_ASSETS)
    if any(getattr(read, 'type', None) == 'well-path' for _, read in items):  # E125 s3a: refused before anything is written
        raise Refused('A well path given as positions is not exported in a bundle yet; export it on its own as the original file.')
    for _, read in items:  # E139 s3 (O1): a horizon a bundle file cannot hold is refused by number before anything is written
        too_large = horizon_too_large(read)
        if too_large: raise Refused(too_large)
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
            entry = {'path': relative, 'role': role, **({'media_type': media_type(relative)} if citation is not None else {}),
                     'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            if curve is not None: entry['curve'] = curve
            return entry
        typed_bundle = any(hasattr(read, '_wire_data_bytes') or isinstance(read, tuple) for _, read in items) or bool(graph)  # entities need 2.4
        typed_bundle = typed_bundle or any(getattr(read, 'provenance', None) is not None for _, read in items)  # B3: a kept original needs schema 2 (2.9)
        typed_bundle = typed_bundle or citation is not None  # E147 s2: a citation needs schema 2 (2.15)
        typed_bundle = typed_bundle or any(isinstance(read, WellTable) for _, read in items)  # E162 s2a: a wells table needs schema 2 (2.17)
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
            if isinstance(read, WellTable):  # E162 s2a (2.17): the kept rows exactly as kept, and the source manifest as served
                files = [put(folder + 'original.json', read.original, 'original'),
                         put(folder + 'descriptor.json', (json.dumps(read.descriptor, indent=2, allow_nan=False) + '\n').encode(), 'descriptor')]
                assets.append({'asset_id': chosen['asset_id'], 'revision': read.revision, 'origin': 'retained-capture', 'profile': WELL_TABLE_PROFILE,
                               'type': WELL_TABLE, 'name': read.name, 'files': files, 'history': None, 'parents': [], 'parent_visibility': 'complete',
                               'omissions': [], 'losses': list(read.descriptor.get('losses') or [])})
                selection.append({**chosen, 'curves': []}); continue
            if hasattr(read, '_wire_data_bytes'):  # E11 typed data: exact original, descriptor and data as served
                first = read._wire_descriptor
                files = [put(folder + TYPED_ORIGINALS[first['profile']], read.original, 'original'),
                         put(folder + 'descriptor.json', (json.dumps(first, indent=2, allow_nan=False) + '\n').encode(), 'descriptor'),
                         put(folder + data_file_of(first), read._wire_data_bytes, 'normalized')]  # E139 s2: named by its codec
                block = None
                if first.get('package') is not None:  # E23c (2.8): the package, its companions and the interpretation travel too
                    from .bundle_package import write_files
                    more, block = write_files(read, folder, put, files[0]['path']); files += more
                assets.append({'asset_id': first['asset_id'], 'revision': first['revision'], 'origin': first['origin'], 'profile': first['profile'],
                               'type': first['scientific']['type'], 'name': None, 'files': files, 'history': first.get('history'), 'parents': first.get('parents', []),
                               'parent_visibility': first.get('parent_visibility', 'complete'), 'relationships': first.get('relationships'),
                               'omissions': list(first.get('provenance', {}).get('omissions', [])),
                               'losses': sorted({loss for r in first.get('representations', []) for loss in r.get('losses', [])})})
                if block is not None: assets[-1]['package'] = block
                kept = _kept_of(read, first)
                if kept is not None: files.append(put(folder + kept[2], kept[0], 'provenance')); assets[-1]['read_by'] = kept[1]  # 2.9 (E107a)
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
            kept = _kept_of(read, first)
            if kept is not None: files.append(put(folder + kept[2], kept[0], 'provenance')); assets[-1]['read_by'] = kept[1]  # 2.9 (E107a)
            selection.append(chosen)
        for (_, read), entry in zip(items, assets):  # E122 s5b (D1): the served record, as the client was answered for this version
            held = getattr(read[0] if isinstance(read, tuple) else read, 'source_record', None)
            if held is not None: entry['source_record'] = held
        observations = {**({'groups': groups} if groups else {}), **({'groups_omitted': groups_omitted} if groups_omitted else {}),
                        **({'entities_omitted': entities_omitted} if entities_omitted else {}),  # E22b: why no wells travel
                        **({'source_records_omitted': source_records_omitted} if source_records_omitted else {})}  # E122 s5b: why no records travel
        # The lowest version that expresses this content: 1.x for well logs, 2.x for typed data;
        # the minor rises only for observations (1) or the newer types (2), so older readers keep working.
        minor = max([1 if observations else 0, 4 if graph else 0] + [max(NEWER_TYPES.get(a.get('type'), 0), NEWER_PROFILES.get(a.get('profile'), 0)) for a in assets]
                    + [PACKAGE_MINOR for a in assets if 'package' in a]  # E23c: 2.8 only for an asset with a package
                    + [PROVENANCE_MINOR for a in assets if 'read_by' in a]  # E107a: 2.9 only for an asset with a kept original
                    + [SOURCE_RECORD_MINOR for a in assets if 'source_record' in a])  # E122 s5b: 1.10/2.10 only when a record travels
        if citation is not None: minor = max(minor, _descriptors_contract().MINOR)  # E147 s2: 2.15, or the content's own minor above it
        if citation is not None and _descriptors_contract().bundle_tables(assets):  # E147 s2b: 2.16 when a typed table gets a record set
            minor = max(minor, _descriptors_contract().TABLES_MINOR)
        version = ('2' if typed_bundle else '1') + f'.{minor}.0'
        manifest = {'schema': SCHEMA_2 if typed_bundle else SCHEMA, 'bundle_version': version, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'exporter': {'name': 'ophiolite-sdk', 'version': __version__}, 'scope': 'selection', 'selection': selection, 'assets': assets,
                    'groups': None, 'recommendations': None, **({'observations': observations} if observations else {}),
                    **({'entities': graph['entities'], 'relationships': graph['relationships']} if graph else {}),
                    'limits': {'max_assets': MAX_ASSETS, 'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}, 'notice': NOTICE}
        if citation is not None:  # E147 s2 (D5): the descriptors are written from the manifest before it is, inside the staging
            manifest['citation'] = citation
            contract = _descriptors_contract()
            kind = CITED_RESOURCE_TYPES[0] if all(a.get('type') == 'well-log' for a in assets) else CITED_RESOURCE_TYPES[1]
            for name, document in contract.documents(*contract.inputs(manifest), kind).items():
                fd = os.open(staging / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'wb') as out: out.write(contract.serialize(document))
        raw = (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode()
        if len(raw) > MAX_MANIFEST_BYTES and any('source_record' in a for a in assets): raise Refused(SOURCE_TOO_LARGE)  # E122 s5b: before anything is visible
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


# E18: what an import may declare, per data type — the uploader's declarations the descriptor carries.
DECLARABLE = {'well-tops': ('depth_unit', 'depth_basis'), 'trajectory': ('depth_unit', 'azimuth_reference', 'depth_datum'),
              'regular-grid-surface': ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum'),
              'triangulated-surface': ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum'),
              'point-set': ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum'),
              'polyline-set': ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum'),
              'time-depth': ('depth_type', 'depth_unit', 'time_kind', 'time_unit', 'datum'),
              'feature-set': ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum', 'encoding', 'layer')}  # E56: as its kind takes them
REGISTRATION = {'center': 'centres', 'corner': 'edges'}  # E56: a grid's stored registration is the corners it was read with
NOT_IMPORTED_CPS3 = ('A CPS-3 grid is imported by uploading its file again: where each column of the file starts is not kept with the grid. '
                     'Upload the original and choose North end or South end.')
DECLARABLE_NUMBERS = {'time-depth': ('seismic_reference_elevation',)}  # E57: served as a number, declared as its canonical decimal text


def _declared_keys(profile):
    """E56: the fields a kind of file takes, from the reader registry this SDK carries; None for the kinds before E56,
    whose declarations are unchanged."""
    if profile not in ('zmap-plus-grid/1', 'cps3-ascii-grid/1', 'irap-ascii-grid/1', 'geojson/1', 'ogc-geopackage/1'): return None
    readers = json.loads((Path(__file__).parent / 'contracts/connectors/v1/readers.json').read_text())['readers']
    return {f['key'] for e in readers if e['profile'] == profile for f in e['declared']}


def import_plan(bundle, well_logs):
    """Per asset: what an import uploads (original, profile, declared context, name, stable command,
    origin) or why it cannot (state 'refused', reason). Checks the bundle first; reads nothing else."""
    opened = bundle if isinstance(bundle, Bundle) else open_bundle(bundle)
    digest = hashlib.sha256((opened.path / 'manifest.json').read_bytes()).hexdigest()
    exporter = '%s %s' % (opened.manifest['exporter'].get('name', 'unknown'), opened.manifest['exporter'].get('version', ''))
    steps = []
    for position, asset in enumerate(opened.assets):
        entry = asset.entry
        step = {'position': position, 'asset_id': asset.asset_id, 'revision': asset.revision, 'type': asset.type,
                'command_id': hashlib.sha256(('%s:%d' % (digest, position)).encode()).hexdigest()[:32],
                'origin': {'kind': 'portable-bundle', 'manifest_sha256': digest, 'asset_id': asset.asset_id, 'revision': asset.revision, 'exporter': exporter.strip()[:80]}}
        def refuse(reason): steps.append({**step, 'state': 'refused', 'reason': reason})
        if asset.type == WELL_TABLE:
            refuse(WELL_TABLE_RESTORED); continue  # E162 s2a: its wells are rebuilt from its rows, not from an upload
        if asset.original is None:
            refuse('This bundle carries no original for it (a seismic slice is not the volume)'); continue
        if asset.package is not None:  # E23c: re-import of a package follows E23b2's upload flow (C7)
            refuse(NOT_IMPORTED_PACKAGE); continue
        if asset.type == 'seismic-section' and asset.data.context['origin'] == 'synthetic':
            refuse(NOT_IMPORTED_SYNTHETIC); continue  # E53: a synthetic exists only with its parents
        original = next(f for f in entry['files'] if f['role'] == 'original')
        wire = asset.data._wire_descriptor if asset.data is not None else next(iter(asset.curves.values())).wire_descriptor
        name = entry.get('name') or ((wire.get('display') or {}).get('name') if isinstance(wire.get('display'), dict) else None) or 'Imported ' + asset.type.replace('-', ' ')
        declared, well_log = {}, None
        if asset.type == 'well-log':
            profile = 'las2/1'
        else:
            profile = entry['profile']; context = asset.data.context
            if profile == 'cps3-ascii-grid/1': refuse(NOT_IMPORTED_CPS3); continue
            takes = _declared_keys(profile)
            for key in DECLARABLE.get(asset.type, ()):
                value = context.get(key)
                if isinstance(value, str) and value and value != 'unknown' and (takes is None or key in takes): declared[key] = value
            if takes is not None and 'corners' in takes: declared['corners'] = REGISTRATION[context['registration']]  # E56: ZMAP+ asks it
            for key in DECLARABLE_NUMBERS.get(asset.type, ()):
                if context.get(key) is not None: declared[key] = _decimal(context[key], key)
            link = (entry.get('relationships') or {}).get('well_log')
            if link:
                exported = link if isinstance(link, str) else link.get('asset_id')
                target = well_logs.get(exported) if exported != 'restricted' else None
                if target is None:
                    refuse('It belongs to a well log; name the imported well log for it (well_logs)'); continue
                well_log = {'asset_id': target[0], 'revision': target[1]}
        steps.append({**step, 'state': 'ready', 'original': asset.original, 'profile': profile, 'declared': declared, 'well_log': well_log,
                      'filename': PurePosixPath(original['path']).name, 'name': name[:160]})
        if asset.provenance is not None:  # B2 (E107a): the kept original goes back as the re-uploaded original's attachment, the reading as recorded
            steps[-1]['provenance'] = asset.provenance; steps[-1]['origin'] = {**step['origin'], 'read_by': asset.read_by}
        if recorded_source(wire) is not None:  # E108 S1 (5R-8): the source procedure that made it, as the exporting project recorded it
            steps[-1]['origin'] = {**steps[-1]['origin'], 'sourced_by': recorded_source(wire)}
    return steps


# E30b: Curve.write(depth, {mnemonic: (unit, values)}, depth_unit=...) writes LAS 2.0 for Client.publish_derived.
from .writers import _decimal, write_curves as _write_curves
Curve.write = staticmethod(_write_curves)
