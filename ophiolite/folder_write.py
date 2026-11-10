"""A data frame of wells becomes a checked project folder /2 (E117 s1 C2, D4). Needs the `folder` extra (pandas, pyarrow,
pyproj); imported lazily by `ophiolite.folder.write_folder` and by nothing else.

    from ophiolite.folder import write_folder
    report = write_folder('field/', {'wells': (frame, {'crs': 'EPSG:28992'})})    # ophiolite.folder.check's report

The payload follows contracts/folders/v1/README.md: one column per field of targets/v1/wells.json in its order
(identifier, name and text as strings, numbers and coordinates as float64, every column nullable), `ophiolite.field` on
each and `ophiolite.unit` on `depth`, schema metadata `ophiolite.target` and `ophiolite.declarations`, a `geometry`
column of WKB points with GeoParquet 1.1.0 `geo` metadata whose `crs` is the PROJJSON of the declared system. Beside the
item the folder holds `lineage/prov.json` (the block's files need two rows; amendment A1): the item, one write activity
with its row count, and the writer. Every refusal comes before any file exists; the folder is written in a staging
directory beside `out`, must pass `check()`, and only then takes the name `out` (claimed with mkdir, never overwritten).

With `citation=` (E147 s1 D2) the manifest is 2.15 and carries the citation block after `folder`, and the folder holds
the three descriptors the contract writes from it (contracts/descriptors/v1/descriptors.py documents()). The caller
gives the block's own fields; the writer adds `schema`, `doi` (null) and `descriptors`, and `published` defaults to the
date of `created_at`. Without a citation every byte is as before.
"""
import copy
import hashlib
import json
import math
import numbers
import os
import re
import shutil
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import bundle
from ._version import __version__
from .errors import Refused

EXTRA = 'Writing a project folder needs pandas, pyarrow and pyproj: pip install "ophiolite[folder]".'
TARGET = 'wells'
PROFILE = 'ophiolite.table-target/wells/1'
ITEM, LINEAGE = 'items/wells.parquet', 'lineage/prov.json'
PARQUET = 'application/vnd.apache.parquet'
STRING_KINDS = ('identifier', 'name', 'text', 'reference')
EXISTS = 'The destination already exists; choose a new folder.'
# The citation fields a caller gives, in the block's order; schema, doi and descriptors are the writer's (D2).
CITATION_FIELDS = ('title', 'description', 'published', 'version', 'creators', 'publisher', 'licence', 'notice')
RESOURCE_TYPE = 'Project folder'


def _libraries():
    try:
        import pandas
        import pyarrow
        import pyarrow.parquet
        import pyproj
    except ImportError:
        raise Refused(EXTRA) from None
    return pandas, pyarrow, pyproj


def _target(contract):
    return contract.TARGETS[TARGET]


def _blank(pandas, value):
    if value is None or value is pandas.NA: return True
    try:
        if pandas.isna(value): return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def _columns(pandas, frame, fields):
    """The frame's values per target field, refused with a sentence naming the column and the first row."""
    if not isinstance(frame, pandas.DataFrame): raise Refused('Give the wells as a pandas DataFrame.')
    labels = [str(label) for label in frame.columns]
    repeated = next((label for i, label in enumerate(labels) if label in labels[:i]), None)
    if repeated is not None: raise Refused('The column %s appears twice.' % repeated)
    names = [f['name'] for f in fields]
    unknown = next((label for label in labels if label not in names), None)
    if unknown is not None: raise Refused('The column %s is not a field of wells (%s).' % (unknown, ', '.join(names)))
    columns = {}
    for f in fields:
        name = f['name']
        if name not in labels:
            if f['required']: raise Refused('The required column %s is missing.' % name)
            columns[name] = [None] * len(frame)
            continue
        values = []
        for row, value in enumerate(frame.iloc[:, labels.index(name)].tolist(), start=1):
            if _blank(pandas, value):
                if f['required']: raise Refused('The column %s is blank in row %d.' % (name, row))
                values.append(None)
            elif f['kind'] in STRING_KINDS:
                if not isinstance(value, str): raise Refused('The column %s is not text in row %d.' % (name, row))
                values.append(value)
            else:
                if isinstance(value, bool) or not isinstance(value, numbers.Real): raise Refused('The column %s is not a number in row %d.' % (name, row))
                if not math.isfinite(float(value)): raise Refused('The column %s is not finite in row %d.' % (name, row))
                values.append(float(value))
        columns[name] = values
    return columns


def _declarations(contract, pyproj, given):
    """Every declaration of the target, in its order: crs as given (required), the others as given or the target's default."""
    if not isinstance(given, dict): raise Refused('Give the declarations as a dict, for example {"crs": "EPSG:28992"}.')
    declared = _target(contract)['declarations']
    names = [d['name'] for d in declared]
    unknown = next((name for name in given if name not in names), None)
    if unknown is not None: raise Refused('wells declares no %s; it declares %s.' % (unknown, ', '.join(names)))
    if given.get('crs') is None: raise Refused('Declare the coordinate system of x and y, for example {"crs": "EPSG:28992"}.')
    values = {}
    for d in declared:
        value = given.get(d['name'], d['default'])
        if not contract._value_ok(PROFILE, d['name'], value):
            if d['kind'] == 'crs': raise Refused('Write the coordinate system as EPSG:<code>, not %r.' % (value,))
            raise Refused('The declaration %s cannot be %r; wells takes %s.' % (d['name'], value, ', '.join(v['value'] for v in d['values'])))
        values[d['name']] = value
    try: crs = pyproj.CRS.from_epsg(int(values['crs'].split(':')[1]))
    except pyproj.exceptions.CRSError: raise Refused('The coordinate system %s is not known to pyproj.' % values['crs']) from None
    return values, crs


def _parquet(pyarrow, fields, columns, declarations, crs):
    import pyarrow.parquet
    schema_fields, arrays = [], []
    for f in fields:
        metadata = {'ophiolite.field': f['name']}
        if f['name'] == 'depth': metadata['ophiolite.unit'] = declarations['depth_unit']
        kind = pyarrow.string() if f['kind'] in STRING_KINDS else pyarrow.float64()
        schema_fields.append(pyarrow.field(f['name'], kind, nullable=True, metadata=metadata))
        arrays.append(pyarrow.array(columns[f['name']], type=kind))
    schema_fields.append(pyarrow.field('geometry', pyarrow.binary(), nullable=True))
    arrays.append(pyarrow.array([struct.pack('<BIdd', 1, 1, x, y) for x, y in zip(columns['x'], columns['y'])], type=pyarrow.binary()))
    metadata = {'ophiolite.target': TARGET, 'ophiolite.declarations': json.dumps(declarations, sort_keys=True),
                'geo': json.dumps({'version': '1.1.0', 'primary_column': 'geometry', 'columns': {'geometry': {
                    'encoding': 'WKB', 'geometry_types': ['Point'], 'crs': crs.to_json_dict()}}}, sort_keys=True)}
    table = pyarrow.Table.from_arrays(arrays, schema=pyarrow.schema(schema_fields, metadata=metadata))
    sink = pyarrow.BufferOutputStream()
    pyarrow.parquet.write_table(table, sink, compression='zstd')
    return sink.getvalue().to_pybytes()


def _lineage(item_sha, rows, writer, at):
    """PROV-JSON in the shape ophiolite-mapper writes (lineage/prov.json): the item, the write and who wrote it."""
    item, write = 'ophiolite:sha256-' + item_sha, 'ophiolite:write-' + item_sha
    agent = 'ophiolite:' + ''.join(c if c.isalnum() or c in '.-' else '-' for c in '%s-%s' % (writer['name'], writer['version']))
    return {'prefix': {'ophiolite': 'https://ophiolite.dev/ns/'},
            'entity': {item: {'prov:label': ITEM, 'prov:type': 'ophiolite:item'}},
            'activity': {write: {'prov:startTime': at, 'prov:endTime': at, 'prov:type': 'ophiolite:write',
                                 'ophiolite:rows_written': rows, 'ophiolite:rows_left_out': 0}},
            'agent': {agent: {'prov:type': 'prov:SoftwareAgent', 'prov:label': '%s %s' % (writer['name'], writer['version'])}},
            'wasGeneratedBy': {'_:generated-1': {'prov:entity': item, 'prov:activity': write}},
            'wasAssociatedWith': {'_:associated-1': {'prov:activity': write, 'prov:agent': agent}}}


def _put(root, relative, raw):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as out: out.write(raw)
    return {'path': relative, 'asset': None, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _citation(descriptors, given, at):
    """The citation block from the caller's fields, checked as the contract checks it (validate_block, folder)."""
    if not isinstance(given, dict): raise Refused('Give the citation as a dict: title, creators, publisher and licence.')
    other = sorted(str(key) for key in set(given) - set(CITATION_FIELDS))
    if other:
        raise Refused('The citation does not take %s: the writer adds schema, doi and descriptors, and a folder\'s '
                      'provenance is its lineage.' % ', '.join(other))
    fields = copy.deepcopy(given)
    fields.setdefault('published', at[:10])
    block = {'schema': descriptors.CITATION, **{key: fields[key] for key in CITATION_FIELDS if key in fields},
             'doi': None, 'descriptors': list(descriptors.NAMES)}
    try: descriptors.validate_block(block, folder=True)
    except descriptors.CitationError as error:
        raise Refused('The citation is not valid (%s at %s).' % (error.code, error.path)) from None
    return block


def write_folder(out, items, *, writer=None, namespace='synthetic', created_at=None, citation=None):
    """Write ITEMS ({'wells': (frame, declarations)}) as a project folder /2 at OUT, a new directory. Returns check(OUT).
    Refuses, before any file exists, what the wells target does not admit and a citation the contract does not;
    never overwrites. CITATION: the block's own fields (title, creators, publisher, licence; optionally description,
    version, notice, published), written with its three descriptors."""
    from .folder import check
    pandas, pyarrow, pyproj = _libraries()
    out = Path(out)
    if out.exists() or out.is_symlink(): raise Refused(EXISTS)
    if not out.parent.is_dir(): raise Refused('The folder %s does not exist; create it first.' % out.parent)
    if not isinstance(items, dict) or not items: raise Refused('Give the items to write, for example {"wells": (frame, {"crs": "EPSG:28992"})}.')
    if set(items) != {TARGET}: raise Refused('Well tops and grids are not written yet.')
    contract = bundle._folders_contract()
    writer = dict(writer) if writer is not None else {'name': 'ophiolite', 'version': __version__}
    if set(writer) != {'name', 'version'} or not all(isinstance(v, str) and 0 < len(v) <= 80 for v in writer.values()):
        raise Refused('Name the writer as {"name": ..., "version": ...}, each 1 to 80 characters.')
    if writer['name'] == contract.MAPPER_WRITER: raise Refused('ophiolite-mapper writes its own folders, with a recipe; name another writer.')
    if not isinstance(namespace, str) or not re.fullmatch(contract.SCHEMA['properties']['osdu']['properties']['namespace']['pattern'], namespace):
        raise Refused('The OSDU namespace %r is not a namespace (letters, digits and hyphens, at most 64).' % (namespace,))
    at = created_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try: frame, given = items[TARGET]
    except (TypeError, ValueError): raise Refused('Give the wells as (frame, declarations).') from None
    fields = _target(contract)['fields']
    columns = _columns(pandas, frame, fields)
    declarations, crs = _declarations(contract, pyproj, given)
    rows = len(frame)
    raw = _parquet(pyarrow, fields, columns, declarations, crs)  # before any file: a serialization failure leaves nothing
    descriptors = bundle._descriptors_contract() if citation is not None else None
    cited = _citation(descriptors, citation, at) if citation is not None else None

    staging = Path(tempfile.mkdtemp(prefix='.' + out.name + '.staging-', dir=out.parent)); os.chmod(staging, 0o700)
    claimed = False
    try:
        item_row = {**_put(staging, ITEM, raw), 'role': 'item', 'media_type': PARQUET}
        lineage = (json.dumps(_lineage(item_row['sha256'], rows, writer, at), indent=2) + '\n').encode()
        lineage_row = {**_put(staging, LINEAGE, lineage), 'role': 'lineage-prov', 'media_type': 'application/json'}
        files = [{k: row[k] for k in ('path', 'role', 'media_type', 'asset', 'sha256', 'bytes')} for row in (item_row, lineage_row)]
        osdu = contract.SCHEMA['properties']['osdu']['properties']
        block = {'schema': bundle.FOLDER_2, 'writer': writer,
                 'osdu': {'tag': osdu['tag']['const'], 'commit': osdu['commit']['const'], 'namespace': namespace},
                 'items': [{'path': ITEM, 'profile': PROFILE, 'kind': contract.KINDS[PROFILE]['kind'], 'osdu': contract.osdu_of(PROFILE),
                            'declarations': [{'name': k, 'value': v} for k, v in declarations.items()], 'rows': rows}],
                 'files': files}
        manifest = {'schema': bundle.SCHEMA_2, 'bundle_version': '2.%d.0' % contract.MINOR[bundle.FOLDER_2], 'created_at': at,
                    'exporter': dict(writer), 'scope': 'selection', 'selection': [], 'assets': [], 'groups': None, 'recommendations': None,
                    'limits': {'max_assets': bundle.MAX_ASSETS, 'max_file_bytes': bundle.MAX_FILE_BYTES, 'max_total_bytes': bundle.MAX_TOTAL_BYTES},
                    'notice': bundle.NOTICE, 'folder': block}
        if cited is not None:
            manifest['bundle_version'] = '2.%d.0' % descriptors.MINOR
            manifest['citation'] = cited
            for name, document in descriptors.documents(*descriptors.inputs(manifest), RESOURCE_TYPE).items():
                _put(staging, name, descriptors.serialize(document))
        _put(staging, 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        report = check(staging)  # the folder checks as a reader would before it becomes visible
        if not report['ok']:
            problem = report['first_problem']
            raise Refused('The folder written did not pass its own check (%s at %s); nothing was kept.' % (problem['code'], problem['path']))
        try: os.mkdir(out, 0o700)
        except FileExistsError: raise Refused(EXISTS) from None
        claimed = True
        os.replace(staging, out)
        claimed = False
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if claimed:
            try: os.rmdir(out)  # only the empty directory this call claimed
            except OSError: pass
        raise
    return check(out)
