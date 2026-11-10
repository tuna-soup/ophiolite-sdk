"""E117 s0 C1: write the project folder fixtures (valid/<name>/, synthetic data only) once; the committed bytes are the
fixtures, and the tests never rebuild them.

    valid/recipe-wells/  /2, writer ophiolite-mapper: v1-wells's recipe, original and lineage, a wells item
    valid/wells-grid/    /2, another writer and no recipe: a wells item with GeoParquet `geometry` and `geo`, and a 2x2
                         GeoTIFF item (EPSG:28992), written here with the standard library
    valid/v1-wells/      /1 as ophiolite-mapper write makes it from a synthetic wells CSV (with the identity tables and the
                         OSDU load manifest every box folder carries since E116 s2/s3)
    valid/v1-las/        /1 as ophiolite-mapper write makes it from the synthetic SYN-W2..W4 LAS files

Run from the Integration root with the lane's Python (pyarrow and pyproj for the /2 Parquet item, lasio for the LAS
folder; the box from its source tree):

    python ophiolite-platform/contracts/folders/v1/fixtures/build.py
"""
import copy
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BOX = ROOT / 'ophiolite-connectors' / 'mapper'
LAS = ROOT / 'ophiolite-connectors' / 'tests' / 'fixtures' / 'mapper' / 'four-wells'
AT = '2026-11-04T09:00:00Z'
BY = 'A. Person'
CSV = b'UWI,NAME,X,Y,TD\nSYN-A1,SYN-A1,217000.5,568500.25,1250.0\nSYN-A2,SYN-A2,217100.0,568600.0,1310.5\n' \
      b'SYN-A3,SYN-A3,217200.0,568700.0,980.0\nSYN-A4,SYN-A4,217300.0,568800.0,1422.0\n'
WELLS = [('SYN-A1', 217000.5, 568500.25, 1250.0), ('SYN-A2', 217100.0, 568600.0, 1310.5), ('SYN-A3', 217200.0, 568700.0, 980.0),
         ('SYN-A4', 217300.0, 568800.0, 1422.0)]
DECLARED = {'crs': 'EPSG:28992', 'depth_unit': 'm', 'depth_kind': 'MD', 'depth_reference': 'unknown'}
PARQUET = 'application/vnd.apache.parquet'
OSDU = {'tag': 'v0.30.1', 'commit': 'ff89d87caa43d05d1341dcaa6d258e1186ec8aa6', 'namespace': 'synthetic'}
NOTICE = ('Checksums show the integrity of this copy, not authorship or scientific correctness. Exported copies cannot be '
          'recalled; holding one grants no new upstream, sharing or AI-training rights.')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def geotiff(values, origin, cell, epsg):
    """A little-endian baseline GeoTIFF: one float32 band in one strip, PixelIsArea, ProjectedCSTypeGeoKey EPSG."""
    rows, cols = len(values), len(values[0])
    data = b''.join(struct.pack('<f', v) for row in values for v in row)
    scale = struct.pack('<3d', cell, cell, 0.0)
    tie = struct.pack('<6d', 0.0, 0.0, 0.0, origin[0], origin[1], 0.0)
    keys = struct.pack('<16H', 1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, epsg)
    extra = [(33550, 12, 3, scale), (33922, 12, 6, tie), (34735, 3, 16, keys)]
    tags = [(256, 3, 1, cols), (257, 3, 1, rows), (258, 3, 1, 32), (259, 3, 1, 1), (262, 3, 1, 1), (273, 4, 1, None),
            (277, 3, 1, 1), (278, 3, 1, rows), (279, 4, 1, len(data)), (284, 3, 1, 1), (339, 3, 1, 3)]
    count = len(tags) + len(extra)
    ifd_at = 8
    blobs_at = ifd_at + 2 + 12 * count + 4
    blobs, offsets = b'', {}
    for tag, _, _, blob in extra:
        offsets[tag] = blobs_at + len(blobs)
        blobs += blob
    data_at = blobs_at + len(blobs)
    entries = []
    for tag, kind, n, value in tags:
        value = data_at if tag == 273 else value
        entries.append((tag, kind, n, struct.pack('<H2x', value) if kind == 3 else struct.pack('<I', value)))
    entries += [(tag, kind, n, struct.pack('<I', offsets[tag])) for tag, kind, n, _ in extra]
    ifd = struct.pack('<H', count) + b''.join(struct.pack('<HHI', t, k, n) + v for t, k, n, v in sorted(entries)) + struct.pack('<I', 0)
    return b'II*\x00' + struct.pack('<I', ifd_at) + ifd + blobs + data


def wells_parquet(geometry, recipe_sha=None):
    """The wells target's columns in its order and types (§1a), with field and schema metadata; GEOMETRY adds WKB points
    and GeoParquet 1.1.0 `geo` metadata whose crs is the PROJJSON of EPSG:28992."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    target = json.loads((HERE.parents[2] / 'targets' / 'v1' / 'wells.json').read_text(encoding='utf-8'))
    declarations = {k: DECLARED[k] for k in ('crs', 'depth_unit')}
    by_name = {'id': 0, 'name': 0, 'x': 1, 'y': 2, 'depth': 3}
    fields, columns = [], []
    for f in target['fields']:
        string = f['kind'] in ('identifier', 'name', 'text', 'reference')
        metadata = {'ophiolite.field': f['name']}
        if f['name'] == 'depth': metadata['ophiolite.unit'] = 'm'
        fields.append(pa.field(f['name'], pa.string() if string else pa.float64(), nullable=True, metadata=metadata))
        columns.append([w[by_name[f['name']]] if f['name'] in by_name else None for w in WELLS])
    schema_metadata = {'ophiolite.target': 'wells', 'ophiolite.declarations': json.dumps(declarations, sort_keys=True)}
    if recipe_sha: schema_metadata['ophiolite.recipe'] = 'sha256:' + recipe_sha
    if geometry:
        from pyproj import CRS
        fields.append(pa.field('geometry', pa.binary(), nullable=True))
        columns.append([struct.pack('<BIdd', 1, 1, w[1], w[2]) for w in WELLS])
        schema_metadata['geo'] = json.dumps({'version': '1.1.0', 'primary_column': 'geometry', 'columns': {'geometry': {
            'encoding': 'WKB', 'geometry_types': ['Point'], 'crs': CRS.from_epsg(28992).to_json_dict()}}}, sort_keys=True)
    table = pa.Table.from_arrays([pa.array(c, type=s.type) for c, s in zip(columns, fields)], schema=pa.schema(fields, metadata=schema_metadata))
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression='zstd')
    return sink.getvalue().to_pybytes()


def manifest(block, exporter):
    return {'schema': 'ophiolite.portable-bundle/2', 'bundle_version': '2.14.0', 'created_at': AT, 'exporter': exporter,  # E117 s1: /2 needs 2.14
            'scope': 'selection', 'selection': [], 'assets': [], 'groups': None, 'recommendations': None,
            'limits': {'max_assets': 128, 'max_file_bytes': 33554432, 'max_total_bytes': 536870912}, 'notice': NOTICE, 'folder': block}


def write_folder(name, contents, rows_of, block):
    out = HERE / 'valid' / name
    if out.exists(): shutil.rmtree(out)
    for path, raw in contents.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(raw)
    block['files'] = [{'path': p, 'role': rows_of[p][0], 'media_type': rows_of[p][1], 'asset': None, 'sha256': sha(raw), 'bytes': len(raw)}
                      for p, raw in contents.items()]
    if 'recipe' in block: block['recipe']['sha256'] = sha(contents['recipe.json'])
    exporter = dict(block['writer'])
    (out / 'manifest.json').write_text(json.dumps(manifest(block, exporter), indent=2) + '\n', encoding='utf-8')


def wells_item(rows=4):
    return {'path': 'items/wells.parquet', 'profile': 'ophiolite.table-target/wells/1', 'kind': 'wells',
            'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'},
            'declarations': [{'name': 'crs', 'value': 'EPSG:28992'}, {'name': 'depth_unit', 'value': 'm'}], 'rows': rows}


def v2_folders():
    """recipe-wells takes v1-wells's recipe, original and lineage as they are (what the box will write as /2 in s3)."""
    v1 = HERE / 'valid' / 'v1-wells'
    recipe, prov = (v1 / 'recipe.json').read_bytes(), (v1 / 'lineage' / 'prov.json').read_bytes()
    write_folder('recipe-wells', {'recipe.json': recipe, 'originals/wells.csv': CSV, 'items/wells.parquet': wells_parquet(False, sha(recipe)),
                                  'lineage/prov.json': prov},
                 {'recipe.json': ('recipe', 'application/json'), 'originals/wells.csv': ('original', 'text/csv'),
                  'items/wells.parquet': ('item', PARQUET), 'lineage/prov.json': ('lineage-prov', 'application/json')},
                 {'schema': 'ophiolite.project-folder/2', 'writer': {'name': 'ophiolite-mapper', 'version': '0.3.0'},
                  'recipe': {'path': 'recipe.json', 'sha256': ''}, 'osdu': dict(OSDU), 'items': [wells_item()], 'files': []})
    grid = {'path': 'items/grid.tif', 'profile': 'geotiff/1', 'kind': 'grid', 'osdu': {'kind': 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'},
            'declarations': [{'name': 'crs', 'value': 'EPSG:28992'}], 'rows': None}
    write_folder('wells-grid', {'items/wells.parquet': wells_parquet(True), 'items/grid.tif': geotiff([[-1210.5, -1212.0], [-1208.25, -1209.75]], (217000.0, 568900.0), 250.0, 28992)},
                 {'items/wells.parquet': ('item', PARQUET), 'items/grid.tif': ('item', 'image/tiff')},
                 {'schema': 'ophiolite.project-folder/2', 'writer': {'name': 'ophiolite-fixtures', 'version': '1.0.0'},
                  'osdu': dict(OSDU), 'items': [wells_item(), grid], 'files': []})


def _decision(action, **extra):
    return {'by': BY, 'at': AT, 'action': action, **extra}


def v1_folders(work):
    """The two /1 folders, through the box's own inspect and write (as test_mapper_write and test_mapper_las drive it)."""
    sys.path.insert(0, str(BOX / 'src'))
    from ophiolite_mapper import cli, inspect
    source = work / 'wells.csv'
    source.write_bytes(CSV)
    recipe, _ = inspect.inspect(str(source), 'wells', str(work / 'recipe.json'))
    chosen = {'id': 'UWI', 'name': 'NAME', 'x': 'X', 'y': 'Y', 'depth': 'TD'}
    for row in recipe['fields']:
        row['decision'] = _decision('choose', column=chosen[row['field']]) if row['field'] in chosen else _decision('leave-unmapped')
    for row in recipe['declarations']:
        if row['name'] in DECLARED: row['value'], row['decision'] = DECLARED[row['name']], _decision('accept')
        else: row['decision'] = _decision('leave-unmapped') if row['value'] is not None else None
    recipe['identity'] = {'basis': 'external', 'column': 'UWI', 'decision': _decision('accept')}
    recipe['osdu']['namespace'] = 'synthetic'
    folders = {'v1-wells': (recipe, work / 'wells-recipe.json')}
    logs = work / 'logs'
    logs.mkdir()
    for path in sorted(LAS.glob('syn-*.las')): shutil.copyfile(path, logs / path.name)
    las, _ = inspect.inspect(str(logs), None, str(work / 'las-recipe.json'))
    for row in las['wells']:
        row['decision'] = _decision('new-entity' if row['match'] == 'exact' else 'reject-alias' if row['spelling'] == 'SYN_W4' else 'accept-alias')
    las['identity']['decision'] = _decision('accept')
    las['osdu']['namespace'] = 'synthetic'
    folders['v1-las'] = (las, work / 'las-recipe.json')
    for name, (decided, path) in folders.items():
        path.write_text(json.dumps(decided, indent=2), encoding='utf-8')
        out = HERE / 'valid' / name
        if out.exists(): shutil.rmtree(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if cli.main(['write', str(path), '--out', str(out)]) != 0: raise SystemExit(f'the box refused {name}')


if __name__ == '__main__':
    import tempfile
    with tempfile.TemporaryDirectory() as work: v1_folders(Path(work))
    v2_folders()
