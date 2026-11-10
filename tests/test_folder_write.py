"""E117 s1 C2 (D4): write_folder — a data frame of wells becomes a checked project folder /2.

    a  the manifest of a four-row frame, frozen without digests; check() and open_bundle read it
    b  the payload: x and y as literals, the WKB decoded by struct to the same literals, every field's metadata, the
       target and declarations metadata, no recipe, the GeoParquet keys; geopandas reads the points in EPSG:28992
    c  refusals before any file, each its sentence
    d  nullable pandas dtypes accepted; a missing optional column written as nulls
    e  a serialization failure, a failed self-check, a failed rename and a competing writer leave nothing behind
    f  E147 s1 C2: write_folder(citation=) against the packaged folder-field fixture (X-2 substitution oracle); without a
       citation the bytes of main; the published default; tampering found by check(); invalid citations refused before
       any staging (X-5)
"""
import copy
import json
import os
import struct
import sys
import tempfile
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest

pd = pytest.importorskip('pandas')
pa = pytest.importorskip('pyarrow')
pq = pytest.importorskip('pyarrow.parquet')

from ophiolite import bundle, folder_write
from ophiolite.errors import Refused
from ophiolite.folder import check, write_folder

AT = '2026-11-04T09:00:00Z'
WRITER = {'name': 'ophiolite-tests', 'version': '1'}
WELLS = [('SYN-F1', 'Synthetic F1', 217000.5, 568500.25, 1250.0), ('SYN-F2', 'Synthetic F2', 217100.0, 568600.0, 1310.5),
         ('SYN-F3', 'Synthetic F3', 217200.0, 568700.0, 980.0), ('SYN-F4', 'Synthetic F4', 217300.0, 568800.0, 1422.0)]
FIELDS = ['id', 'name', 'x', 'y', 'depth', 'operator']


def frame(**columns):
    data = {'id': [w[0] for w in WELLS], 'name': [w[1] for w in WELLS], 'x': [w[2] for w in WELLS], 'y': [w[3] for w in WELLS],
            'depth': [w[4] for w in WELLS]}
    data.update(columns)
    return pd.DataFrame({k: v for k, v in data.items() if v is not None})


def write(tmp_path, data=None, declarations=None, **kwargs):
    kwargs.setdefault('writer', WRITER)
    kwargs.setdefault('created_at', AT)
    return write_folder(tmp_path / 'out', {'wells': (frame() if data is None else data, declarations or {'crs': 'EPSG:28992'})}, **kwargs)


def without_digests(manifest):
    for row in manifest['folder']['files']: row.pop('sha256'), row.pop('bytes')
    return manifest


# ---- a. the manifest ---------------------------------------------------------------------------------------------------

def test_a_the_manifest_of_four_wells(tmp_path):
    report = write(tmp_path)
    assert report == {'ok': True, 'verified': 'bytes', 'schema': 'ophiolite.project-folder/2',
                      'files': [{'path': 'items/wells.parquet', 'role': 'item', 'verdict': 'ok'},
                                {'path': 'lineage/prov.json', 'role': 'lineage-prov', 'verdict': 'ok'}],
                      'items': [{'path': 'items/wells.parquet', 'kind': 'wells', 'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'},
                                 'derived': 'manifest', 'verdict': 'ok'}], 'first_problem': None}
    manifest = json.loads((tmp_path / 'out/manifest.json').read_text())
    assert without_digests(manifest) == {
        'schema': 'ophiolite.portable-bundle/2', 'bundle_version': '2.14.0', 'created_at': AT, 'exporter': WRITER,
        'scope': 'selection', 'selection': [], 'assets': [], 'groups': None, 'recommendations': None,
        'limits': {'max_assets': 128, 'max_file_bytes': 33554432, 'max_total_bytes': 536870912},
        'notice': ('Checksums show the integrity of this copy, not authorship or scientific correctness. Exported copies cannot be '
                   'recalled; holding one grants no new upstream, sharing or AI-training rights.'),
        'folder': {'schema': 'ophiolite.project-folder/2', 'writer': WRITER,
                   'osdu': {'tag': 'v0.30.1', 'commit': 'ff89d87caa43d05d1341dcaa6d258e1186ec8aa6', 'namespace': 'synthetic'},
                   'items': [{'path': 'items/wells.parquet', 'profile': 'ophiolite.table-target/wells/1', 'kind': 'wells',
                              'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'},
                              'declarations': [{'name': 'crs', 'value': 'EPSG:28992'}, {'name': 'depth_unit', 'value': 'm'},
                                               {'name': 'depth_kind', 'value': 'MD'}, {'name': 'depth_reference', 'value': 'unknown'}],
                              'rows': 4}],
                   'files': [{'path': 'items/wells.parquet', 'role': 'item', 'media_type': 'application/vnd.apache.parquet', 'asset': None},
                             {'path': 'lineage/prov.json', 'role': 'lineage-prov', 'media_type': 'application/json', 'asset': None}]}}
    opened = bundle.open_bundle(tmp_path / 'out')
    assert [i['rows'] for i in opened.items] == [4] and opened.unlisted == []
    prov = json.loads((tmp_path / 'out/lineage/prov.json').read_text())
    assert [a['ophiolite:rows_written'] for a in prov['activity'].values()] == [4]
    assert list(prov['agent'].values()) == [{'prov:type': 'prov:SoftwareAgent', 'prov:label': 'ophiolite-tests 1'}]
    assert sorted(os.listdir(tmp_path)) == ['out']  # no staging left


def test_a_the_default_writer_is_the_sdk(tmp_path):
    from ophiolite import __version__
    write_folder(tmp_path / 'out', {'wells': (frame(), {'crs': 'EPSG:28992'})})
    assert json.loads((tmp_path / 'out/manifest.json').read_text())['folder']['writer'] == {'name': 'ophiolite', 'version': __version__}


# ---- b. the payload ----------------------------------------------------------------------------------------------------

def test_b_x_and_y_and_the_wkb_are_the_literal_coordinates(tmp_path):
    write(tmp_path)
    table = pq.read_table(tmp_path / 'out/items/wells.parquet')
    assert table.column('x').to_pylist() == [217000.5, 217100.0, 217200.0, 217300.0]
    assert table.column('y').to_pylist() == [568500.25, 568600.0, 568700.0, 568800.0]
    assert [struct.unpack('<BIdd', raw) for raw in table.column('geometry').to_pylist()] == [
        (1, 1, 217000.5, 568500.25), (1, 1, 217100.0, 568600.0), (1, 1, 217200.0, 568700.0), (1, 1, 217300.0, 568800.0)]
    assert table.column('id').to_pylist() == ['SYN-F1', 'SYN-F2', 'SYN-F3', 'SYN-F4']
    assert table.column('depth').to_pylist() == [1250.0, 1310.5, 980.0, 1422.0]


def test_b_field_and_schema_metadata_and_geoparquet(tmp_path):
    write(tmp_path, declarations={'crs': 'EPSG:28992', 'depth_unit': 'ft'})
    schema = pq.read_schema(tmp_path / 'out/items/wells.parquet')
    assert schema.names == FIELDS + ['geometry']
    assert [str(schema.field(n).type) for n in schema.names] == ['string', 'string', 'double', 'double', 'double', 'string', 'binary']
    assert all(schema.field(n).nullable for n in schema.names)
    assert [schema.field(n).metadata for n in FIELDS] == [
        {b'ophiolite.field': n.encode(), **({b'ophiolite.unit': b'ft'} if n == 'depth' else {})} for n in FIELDS]
    metadata = schema.metadata
    assert sorted(metadata) == [b'geo', b'ophiolite.declarations', b'ophiolite.target'] and b'ophiolite.recipe' not in metadata
    assert metadata[b'ophiolite.target'] == b'wells'
    assert json.loads(metadata[b'ophiolite.declarations']) == {'crs': 'EPSG:28992', 'depth_unit': 'ft', 'depth_kind': 'MD', 'depth_reference': 'unknown'}
    geo = json.loads(metadata[b'geo'])
    assert (geo['version'], geo['primary_column'], sorted(geo['columns'])) == ('1.1.0', 'geometry', ['geometry'])
    column = geo['columns']['geometry']
    assert (column['encoding'], column['geometry_types'], column['crs']['id']) == ('WKB', ['Point'], {'authority': 'EPSG', 'code': 28992})


def test_b_geopandas_reads_the_points_in_their_coordinate_system(tmp_path):
    geopandas = pytest.importorskip('geopandas')
    write(tmp_path)
    read = geopandas.read_parquet(tmp_path / 'out/items/wells.parquet')
    assert read.crs.to_epsg() == 28992
    assert [(p.x, p.y) for p in read.geometry] == [(217000.5, 568500.25), (217100.0, 568600.0), (217200.0, 568700.0), (217300.0, 568800.0)]
    assert list(pd.read_parquet(tmp_path / 'out/items/wells.parquet', columns=['x', 'y']).itertuples(index=False, name=None))[0] == (217000.5, 568500.25)


# ---- c. refusals before any file -----------------------------------------------------------------------------------------

def _refused(tmp_path, sentence, **kwargs):
    with pytest.raises(Refused) as refused: write(tmp_path, **kwargs)
    assert str(refused.value) == sentence
    assert os.listdir(tmp_path) == []


def test_c_each_refusal_names_its_cause_and_writes_nothing(tmp_path):
    _refused(tmp_path, 'The column id appears twice.', data=pd.DataFrame([[1, 'a', 'b', 2.0, 3.0]], columns=['id', 'id', 'name', 'x', 'y']))
    _refused(tmp_path, 'The required column name is missing.', data=frame(name=None))
    _refused(tmp_path, 'The column x is blank in row 2.', data=frame(x=[217000.5, None, 217200.0, 217300.0]))
    _refused(tmp_path, 'The column name is blank in row 3.', data=frame(name=['A', 'B', '  ', 'D']))
    _refused(tmp_path, 'The column x is not a number in row 1.', data=frame(x=['217000.5', '1', '2', '3']))
    _refused(tmp_path, 'The column y is not finite in row 4.', data=frame(y=[1.0, 2.0, 3.0, float('inf')]))
    _refused(tmp_path, 'The column colour is not a field of wells (id, name, x, y, depth, operator).', data=frame(colour=['r', 'g', 'b', 'k']))
    _refused(tmp_path, "The declaration depth_unit cannot be 'yd'; wells takes m, ft.", declarations={'crs': 'EPSG:28992', 'depth_unit': 'yd'})
    _refused(tmp_path, "Write the coordinate system as EPSG:<code>, not '28992'.", declarations={'crs': '28992'})
    _refused(tmp_path, 'The coordinate system EPSG:99999 is not known to pyproj.', declarations={'crs': 'EPSG:99999'})
    _refused(tmp_path, 'Declare the coordinate system of x and y, for example {"crs": "EPSG:28992"}.', declarations={'depth_unit': 'm'})
    _refused(tmp_path, 'wells declares no azimuth; it declares crs, depth_unit, depth_kind, depth_reference.',
             declarations={'crs': 'EPSG:28992', 'azimuth': 'grid'})
    with pytest.raises(Refused) as refused: write_folder(tmp_path / 'out', {'well-tops': (frame(), {})})
    assert str(refused.value) == 'Well tops and grids are not written yet.' and os.listdir(tmp_path) == []


def test_c_an_existing_destination_is_refused_and_kept(tmp_path):
    (tmp_path / 'out').mkdir(); (tmp_path / 'out/keep.txt').write_text('mine')
    with pytest.raises(Refused) as refused: write(tmp_path)
    assert str(refused.value) == 'The destination already exists; choose a new folder.'
    assert sorted(os.listdir(tmp_path)) == ['out'] and os.listdir(tmp_path / 'out') == ['keep.txt']


def test_c_without_the_extra_the_sentence_names_it(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'pyproj', None)  # import pyproj raises ImportError
    with pytest.raises(Refused) as refused: write(tmp_path)
    assert str(refused.value) == 'Writing a project folder needs pandas, pyarrow and pyproj: pip install "ophiolite[folder]".'
    assert os.listdir(tmp_path) == []


# ---- d. pandas dtypes and optional columns -------------------------------------------------------------------------------

def test_d_nullable_dtypes_and_a_missing_optional_column(tmp_path):
    data = frame(id=pd.array(['SYN-F1', 'SYN-F2', 'SYN-F3', 'SYN-F4'], dtype='string'),
                 x=pd.array([217000, 217100, 217200, 217300], dtype='Int64'), depth=pd.array([1250.0, None, 980.0, None], dtype='Float64'))
    assert write(tmp_path, data=data)['ok']
    table = pq.read_table(tmp_path / 'out/items/wells.parquet')
    assert table.column('x').to_pylist() == [217000.0, 217100.0, 217200.0, 217300.0]
    assert table.column('depth').to_pylist() == [1250.0, None, 980.0, None]
    assert table.column('operator').to_pylist() == [None, None, None, None]  # not in the frame: written as nulls


# ---- e. failures leave nothing -------------------------------------------------------------------------------------------

def test_e_a_serialization_failure_leaves_nothing(tmp_path, monkeypatch):
    def broken(*args, **kwargs): raise OSError('disk full')
    monkeypatch.setattr(pq, 'write_table', broken)
    with pytest.raises(OSError): write(tmp_path)
    assert os.listdir(tmp_path) == []


def test_e_a_failed_self_check_leaves_nothing(tmp_path, monkeypatch):
    real = folder_write._put
    def corrupt(root, relative, raw):  # the manifest is told one digest, the disk holds other bytes
        row = real(root, relative, raw)
        return {**row, 'sha256': '0' * 64} if relative == folder_write.ITEM else row
    monkeypatch.setattr(folder_write, '_put', corrupt)
    with pytest.raises(Refused) as refused: write(tmp_path)
    assert str(refused.value) == 'The folder written did not pass its own check (file-digest at items/wells.parquet); nothing was kept.'
    assert os.listdir(tmp_path) == []


def test_e_a_failed_rename_leaves_neither_the_folder_nor_staging(tmp_path, monkeypatch):
    def broken(source, target): raise OSError('rename refused')
    monkeypatch.setattr(folder_write.os, 'replace', broken)
    with pytest.raises(OSError): write(tmp_path)
    assert os.listdir(tmp_path) == []


def test_e_a_folder_created_during_the_write_is_never_overwritten(tmp_path, monkeypatch):
    real = folder_write.os.mkdir
    def competitor(path, *args):  # another writer takes the name between the check and the claim
        if str(path) == str(tmp_path / 'out'):
            real(path); (tmp_path / 'out/theirs.txt').write_text('theirs')
        return real(path, *args)
    monkeypatch.setattr(folder_write.os, 'mkdir', competitor)
    with pytest.raises(Refused) as refused: write(tmp_path)
    assert str(refused.value) == 'The destination already exists; choose a new folder.'
    assert sorted(os.listdir(tmp_path)) == ['out'] and os.listdir(tmp_path / 'out') == ['theirs.txt']
    assert check(tmp_path / 'out')['first_problem']['code'] == 'file-missing'


# ---- f. a cited folder (E147 s1 C2; strategy E147-s1-folder-descriptors-COMMIT-STRATEGY.md D2, X-2, X-5, X-8, X-10) --

FIELD = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/folder-field')))
# examples/folders/build.py's frame, writer and time: the folder-field fixture is that example, cited.
EXAMPLE_AT = '2026-11-04T12:00:00Z'
EXAMPLE_WRITER = {'name': 'ophiolite-examples', 'version': '1'}
EXAMPLE_WELLS = [('SYN-F1', 'Synthetic field 1', 150000.0, 450000.0, 1200.0),
                 ('SYN-F2', 'Synthetic field 2', 150750.5, 450250.0, 1325.5),
                 ('SYN-F3', 'Synthetic field 3', 151500.0, 449500.25, 980.0),
                 ('SYN-F4', 'Synthetic field 4', 152250.0, 450750.0, 1410.0)]
DESCRIPTORS = ['ro-crate-metadata.json', 'croissant.json', 'datacite.json']
ITEM, LINEAGE = folder_write.ITEM, folder_write.LINEAGE


def fixture(name):
    return json.loads((FIELD / name).read_text())


def citation(**changes):
    """The fixture's citation as a caller gives it: no schema, doi, descriptors, and no published (X-8: the default)."""
    given = {k: v for k, v in fixture('manifest.json')['citation'].items() if k not in ('schema', 'doi', 'descriptors', 'published')}
    given.update(changes)
    return {k: v for k, v in given.items() if v is not DROP}


DROP = object()  # citation(notice=DROP): leave the field out


def write_example(tmp_path, name='out', **kwargs):
    frame = pd.DataFrame({'id': [w[0] for w in EXAMPLE_WELLS], 'name': [w[1] for w in EXAMPLE_WELLS],
                          'x': [w[2] for w in EXAMPLE_WELLS], 'y': [w[3] for w in EXAMPLE_WELLS],
                          'depth': [w[4] for w in EXAMPLE_WELLS], 'operator': ['Ophiolite examples'] * len(EXAMPLE_WELLS)})
    return write_folder(tmp_path / name, {'wells': (frame, {'crs': 'EPSG:28992'})}, writer=EXAMPLE_WRITER,
                        created_at=EXAMPLE_AT, **kwargs)


def substituted(folder):
    """The fixture with every value that depends on the Parquet bytes taken from FOLDER's manifest (X-2): pyarrow may
    write other bytes. Returns ({name: expected}, [the places substituted])."""
    rows = {r['path']: r for r in json.loads((folder / 'manifest.json').read_text())['folder']['files']}
    old = {r['path']: r for r in fixture('manifest.json')['folder']['files']}
    places = []
    manifest = fixture('manifest.json')
    for i, row in enumerate(manifest['folder']['files']):
        row['sha256'], row['bytes'] = rows[row['path']]['sha256'], rows[row['path']]['bytes']
        places += [f'manifest.json $.folder.files[{i}].sha256', f'manifest.json $.folder.files[{i}].bytes']
    lineage = (FIELD / LINEAGE).read_text().replace(old[ITEM]['sha256'], rows[ITEM]['sha256'])
    places.append('lineage/prov.json the item digest')
    ro = fixture('ro-crate-metadata.json')
    for node in ro['@graph']:
        if node['@id'] in rows:
            node['sha256'], node['contentSize'] = rows[node['@id']]['sha256'], str(rows[node['@id']]['bytes'])
            places += [f'ro-crate-metadata.json {node["@id"]} sha256', f'ro-crate-metadata.json {node["@id"]} contentSize']
    cr = fixture('croissant.json')
    for entry in cr['distribution']:
        entry['sha256'], entry['contentSize'] = rows[entry['@id']]['sha256'], f'{rows[entry["@id"]]["bytes"]} B'
        places += [f'croissant.json {entry["@id"]} sha256', f'croissant.json {entry["@id"]} contentSize']
    dc = fixture('datacite.json')
    dc['sizes'] = [f'{sum(r["bytes"] for r in rows.values())} bytes']
    places.append('datacite.json sizes')
    return {'manifest.json': manifest, LINEAGE: lineage, 'ro-crate-metadata.json': ro, 'croissant.json': cr, 'datacite.json': dc}, places


def test_f_a_cited_write_is_the_folder_field_fixture(tmp_path):
    report = write_example(tmp_path, citation=citation())
    assert report['ok'] and report['files'] == [
        {'path': 'items/wells.parquet', 'role': 'item', 'verdict': 'ok'}, {'path': 'lineage/prov.json', 'role': 'lineage-prov', 'verdict': 'ok'},
        {'path': 'ro-crate-metadata.json', 'role': 'citation-descriptor', 'verdict': 'ok'},
        {'path': 'croissant.json', 'role': 'citation-descriptor', 'verdict': 'ok'},
        {'path': 'datacite.json', 'role': 'citation-descriptor', 'verdict': 'ok'}]
    out = tmp_path / 'out'
    want, places = substituted(out)
    assert places == [
        'manifest.json $.folder.files[0].sha256', 'manifest.json $.folder.files[0].bytes',
        'manifest.json $.folder.files[1].sha256', 'manifest.json $.folder.files[1].bytes', 'lineage/prov.json the item digest',
        'ro-crate-metadata.json items/wells.parquet sha256', 'ro-crate-metadata.json items/wells.parquet contentSize',
        'ro-crate-metadata.json lineage/prov.json sha256', 'ro-crate-metadata.json lineage/prov.json contentSize',
        'croissant.json items/wells.parquet sha256', 'croissant.json items/wells.parquet contentSize',
        'croissant.json lineage/prov.json sha256', 'croissant.json lineage/prov.json contentSize', 'datacite.json sizes']
    assert (out / 'manifest.json').read_text() == json.dumps(want['manifest.json'], indent=2) + '\n'
    assert want['manifest.json']['citation']['published'] == '2026-11-04'  # X-8: the date of created_at, not given
    assert (out / LINEAGE).read_text() == want[LINEAGE]
    for name in DESCRIPTORS:
        raw = (out / name).read_bytes()
        assert json.loads(raw) == want[name], name
        assert raw == (json.dumps(want[name], indent=2, ensure_ascii=False) + '\n').encode('utf-8'), name
    assert sorted(os.listdir(tmp_path)) == ['out']


def test_f_without_a_citation_the_bytes_are_mains(tmp_path):
    write_example(tmp_path, 'plain')
    write_example(tmp_path, 'cited', citation=citation())
    plain, cited = tmp_path / 'plain', tmp_path / 'cited'
    for name in (ITEM, LINEAGE): assert (plain / name).read_bytes() == (cited / name).read_bytes(), name
    manifest = substituted(plain)[0]['manifest.json']
    del manifest['citation']
    manifest['bundle_version'] = '2.14.0'  # = examples/folders/synthetic-field/manifest.json, written by main's writer
    assert (plain / 'manifest.json').read_text() == json.dumps(manifest, indent=2) + '\n'
    assert sorted(os.listdir(plain)) == ['items', 'lineage', 'manifest.json']


def test_f_a_cited_folder_opens_packs_and_reads(tmp_path):
    write_example(tmp_path, citation=citation())
    opened = bundle.open_bundle(tmp_path / 'out')
    assert opened.unlisted == [] and [i['rows'] for i in opened.items] == [4]
    bundle.pack(tmp_path / 'out', tmp_path / 'field.zip')
    with zipfile.ZipFile(tmp_path / 'field.zip') as packed:
        assert sorted(packed.namelist()) == sorted(DESCRIPTORS + [ITEM, LINEAGE, 'manifest.json'])
    assert pd.read_parquet(tmp_path / 'out' / ITEM)['id'].tolist() == ['SYN-F1', 'SYN-F2', 'SYN-F3', 'SYN-F4']
    geopandas = pytest.importorskip('geopandas')
    points = geopandas.read_parquet(tmp_path / 'out' / ITEM)
    assert points.crs.to_epsg() == 28992 and (points.geometry.x.tolist(), points.geometry.y.tolist()) == (
        [150000.0, 150750.5, 151500.0, 152250.0], [450000.0, 450250.0, 449500.25, 450750.0])


def test_f_a_given_published_date_and_an_open_licence_are_kept(tmp_path):
    write_example(tmp_path, citation=citation(published='2026-10-01', licence={'spdx': 'CC-BY-4.0'}, notice=DROP))
    out = tmp_path / 'out'
    block = json.loads((out / 'manifest.json').read_text())['citation']
    assert (block['published'], block['licence'], 'notice' in block) == ('2026-10-01', {'spdx': 'CC-BY-4.0'}, False)
    root = next(n for n in json.loads((out / 'ro-crate-metadata.json').read_text())['@graph'] if n['@id'] == './')
    assert (root['datePublished'], root['license']) == ('2026-10-01', {'@id': 'https://spdx.org/licenses/CC-BY-4.0'})
    assert json.loads((out / 'croissant.json').read_text())['license'] == 'https://spdx.org/licenses/CC-BY-4.0'
    datacite = json.loads((out / 'datacite.json').read_text())
    assert datacite['dates'] == [{'date': '2026-10-01', 'dateType': 'Issued'}]
    assert datacite['rightsList'] == [{'rights': 'Creative Commons Attribution 4.0 International',
                                       'rightsUri': 'https://spdx.org/licenses/CC-BY-4.0', 'rightsIdentifier': 'CC-BY-4.0',
                                       'rightsIdentifierScheme': 'SPDX', 'schemeUri': 'https://spdx.org/licenses/'}]


def _tampered(tmp_path, change):
    write_example(tmp_path, citation=citation())
    change(tmp_path / 'out')
    return check(tmp_path / 'out')['first_problem']


def _edit(folder, name, change):
    document = json.loads((folder / name).read_text())
    change(document)
    (folder / name).write_text(json.dumps(document))


def test_f_check_finds_a_removed_descriptor(tmp_path):
    assert _tampered(tmp_path, lambda out: (out / 'croissant.json').unlink()) == {'code': 'file-missing', 'path': 'croissant.json'}


def test_f_check_finds_a_digest_copied_from_the_lineage(tmp_path):
    def copy_digest(out):
        lineage = json.loads((out / 'manifest.json').read_text())['folder']['files'][1]['sha256']
        _edit(out, 'ro-crate-metadata.json', lambda d: next(n for n in d['@graph'] if n['@id'] == ITEM).update(sha256=lineage))
    problem = _tampered(tmp_path, copy_digest)
    assert (problem['code'], problem['path']) == ('descriptor-disagrees', 'ro-crate-metadata.json:$.@graph[@id=items/wells.parquet].sha256')


def test_f_check_finds_a_manifest_licence_the_descriptors_do_not_give(tmp_path):
    def licence(out):
        def cc0(manifest):
            manifest['citation']['licence'] = {'spdx': 'CC0-1.0'}
            del manifest['citation']['notice']
        _edit(out, 'manifest.json', cc0)
    problem = _tampered(tmp_path, licence)
    assert (problem['code'], problem['path']) == ('descriptor-disagrees', 'ro-crate-metadata.json:$.@graph[@id=./].license')


INVALID = [
    (citation(licence={'spdx': 'CC-BY-3.0'}, notice=DROP), 'The citation is not valid (citation-schema at $.citation.licence.spdx).'),
    (citation(notice=DROP), 'The citation is not valid (citation-schema at $.citation.notice).'),
    (citation(licence={'spdx': 'CC-BY-4.0'}), 'The citation is not valid (notice-without-null-licence at $.citation.notice).'),
    (citation(creators=[{'name': 'Ada Synthetic', 'kind': 'person', 'identifier': 'https://ror.org/0abcdef99'}]),
     'The citation is not valid (citation-schema at $.citation.creators[0].identifier).'),
    (dict(citation(), doi=None),
     "The citation does not take doi: the writer adds schema, doi and descriptors, and a folder's provenance is its lineage."),
    (citation(published='2026-02-30'), 'The citation is not valid (citation-schema at $.citation.published).'),
    (citation(publisher={'name': 'Another Survey Organisation', 'identifier': 'https://ror.org/0abcdef12'}),
     'The citation is not valid (citation-schema at $.citation.publisher.name).'),
    (citation(prov={'path': 'prov.json', 'sha256': '0' * 64, 'bytes': 1}),
     "The citation does not take prov: the writer adds schema, doi and descriptors, and a folder's provenance is its lineage."),
    (dict(citation(), doi=None, descriptors=['croissant.json']),
     "The citation does not take descriptors, doi: the writer adds schema, doi and descriptors, and a folder's provenance is "
     "its lineage."),
    (dict(citation(), schema='ophiolite.citation/1', keywords=['wells']),
     "The citation does not take keywords, schema: the writer adds schema, doi and descriptors, and a folder's provenance is "
     "its lineage."),
    (['Synthetic field'], 'Give the citation as a dict: title, creators, publisher and licence.'),
]


@pytest.mark.parametrize('given,sentence', INVALID, ids=[s[:60] for _, s in INVALID])
def test_f_an_invalid_citation_is_refused_before_any_staging(tmp_path, monkeypatch, given, sentence):
    calls = []
    real_mkdtemp, real_put = tempfile.mkdtemp, folder_write._put
    monkeypatch.setattr(folder_write.tempfile, 'mkdtemp', lambda *a, **k: calls.append('mkdtemp') or real_mkdtemp(*a, **k))
    monkeypatch.setattr(folder_write, '_put', lambda *a: calls.append('_put') or real_put(*a))
    with pytest.raises(Refused) as refused: write_example(tmp_path, citation=copy.deepcopy(given))
    assert str(refused.value) == sentence
    assert calls == [] and os.listdir(tmp_path) == []
