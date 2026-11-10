"""E116 s1 C2: bundle 2.12 opens, checks and packs a project folder (ophiolite.project-folder/1 1.1).

A folder ophiolite-mapper writes alone lists no assets and no selection: its source travels as originals/<name>, its
typed table as items/<target>.parquet, both in the manifest's folder block, which the contract's own validator
(contracts/mapper/v1/mapper.py) checks. The frozen 2.11 reader is the reader before this change (acceptance 2 as
amended at the strategy's closure: it refuses a folder the box wrote alone with its own sentence, and reads the core
of a server bundle that carries the block, the folder files listed as unlisted).

    a  2.12 opens a box folder; Bundle.folder lists its files; summary() counts them
    b  the frozen 2.11 reader refuses that folder with its own sentence and writes nothing
    c  a server bundle with a folder block: 2.11 reads its core, the folder files unlisted; 2.12 lists none
    d  a flipped byte, a missing file, a linked items/, a path outside the roles, an oversized file: each refused by path
    e  a folder block below 2.12 is refused; empty assets without a folder block are refused
    f  pack then open round-trips the folder; a zip whose folder block is malformed is refused before any entry is read
    g  E117 s1: 2.14 opens a project folder /2 (Bundle.items), refuses it below 2.14 and beside assets in both entry
       points, verifies it with the traversal check() uses, packs it with its grid, refuses a malformed /2 zip unread
"""
import hashlib
import json
import os
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.errors import VerificationFailed
from test_bundle import rewrite, typed_read
from test_bundle_compat import FROZEN, frozen, item

RECIPE = files('ophiolite').joinpath('contracts/mapper/v1/fixtures/recipe/valid/wells-csv.json').read_bytes()
SYNTHETIC_CSV = b'id,name,x,y\nSYN-A1,Synthetic A1,1000.5,2000.25\nSYN-A2,Synthetic A2,1010.0,2010.0\n'
SYNTHETIC_ITEM = b'PAR1' + bytes(range(256)) * 32 + b'PAR1'  # the SDK verifies bytes; it never parses the table
NO_ASSETS = 'The bundle lists no assets or too many.'


def _row(path, role, media_type, raw):
    return {'path': path, 'role': role, 'media_type': media_type, 'asset': None, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _block(contents):
    roles = {'recipe.json': ('recipe', 'application/json'), 'lineage/prov.json': ('lineage-prov', 'application/json')}
    rows = [_row(path, *roles.get(path, ('original', 'text/csv') if path.startswith('originals/') else ('item', 'application/vnd.apache.parquet')), raw)
            for path, raw in contents.items()]
    return {'schema': 'ophiolite.project-folder/1', 'mapper': 'ophiolite-mapper 0.2.0',
            'recipe': {'path': 'recipe.json', 'sha256': hashlib.sha256(contents['recipe.json']).hexdigest()},
            'osdu': {'tag': 'v0.30.1', 'commit': 'ff89d87caa43d05d1341dcaa6d258e1186ec8aa6', 'namespace': '{{NAMESPACE}}'}, 'files': rows}


def _write(root, contents):
    for path, raw in contents.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(raw)


def box_folder(root, recipe=RECIPE):
    """A folder as the box writes it: no assets, no selection, the folder block (synthetic bytes)."""
    contents = {'recipe.json': recipe, 'originals/wells.csv': SYNTHETIC_CSV, 'items/wells.parquet': SYNTHETIC_ITEM,
                'lineage/prov.json': b'{"prefix": {"ophiolite": "https://ophiolite.dev/ns/"}}\n'}
    root.mkdir(parents=True)
    _write(root, contents)
    manifest = {'schema': bundle.SCHEMA_2, 'bundle_version': '2.12.0', 'created_at': '2026-11-02T20:00:00Z',
                'exporter': {'name': 'ophiolite-mapper', 'version': '0.2.0'}, 'scope': 'selection', 'selection': [], 'assets': [],
                'groups': None, 'recommendations': None,
                'limits': {'max_assets': bundle.MAX_ASSETS, 'max_file_bytes': bundle.MAX_FILE_BYTES, 'max_total_bytes': bundle.MAX_TOTAL_BYTES},
                'notice': bundle.NOTICE, 'folder': _block(contents)}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root


def _tree(root):
    return sorted((p.relative_to(root).as_posix(), p.read_bytes()) for p in root.rglob('*') if p.is_file())


def test_the_frozen_two_eleven_reader_is_the_released_file():  # the reader before 2.12, at main 7d76a75bd
    from test_bundle_compat import _history
    history = _history()
    released = history.show(Path(__file__).parents[1], '7d76a75bd1ec170422bcddb24f4fd989141e466b', 'ophiolite/bundle.py')
    if released is not None: assert released == (FROZEN / 'bundle_2_11.py').read_bytes()
    else: assert not history.FULL, history.missing('7d76a75bd')
    assert hashlib.sha256((FROZEN / 'bundle_2_11.py').read_bytes()).hexdigest() == 'e9e0de15d28e165626cc689310d986029af1619a8b7a572f063f657e889f4b31'


def test_a_two_twelve_opens_a_box_folder(tmp_path):
    opened = bundle.open_bundle(box_folder(tmp_path / 'box'))
    assert opened.assets == [] and opened.unlisted == []
    assert [(row['path'], row['role']) for row in opened.folder] == [
        ('recipe.json', 'recipe'), ('originals/wells.csv', 'original'), ('items/wells.parquet', 'item'), ('lineage/prov.json', 'lineage-prov')]
    assert opened.summary()['folder_files'] == 4 and opened.summary()['assets'] == 0
    assert 'folder_files' not in bundle.write_bundle(tmp_path / 'server', [item(typed_read('tops'))]).summary()


def test_b_the_frozen_two_eleven_reader_refuses_a_box_folder_and_writes_nothing(tmp_path):
    root = box_folder(tmp_path / 'box')
    before = _tree(tmp_path)
    with pytest.raises(VerificationFailed) as refused: frozen(11).open_bundle(root)
    assert str(refused.value) == NO_ASSETS
    assert _tree(tmp_path) == before


def server_with_folder(root):
    """A server bundle (one exact revision of well tops) that also carries a folder block of a recipe and its lineage."""
    opened = bundle.write_bundle(root, [item(typed_read('tops'))])
    contents = {'recipe.json': RECIPE, 'lineage/prov.json': b'{}\n'}
    _write(opened.path, contents)
    rewrite(opened.path, lambda m: m.update(bundle_version='2.12.0', folder=_block(contents)))
    return opened.path


def test_c_a_server_bundle_with_a_folder_block_keeps_its_core_for_the_frozen_reader(tmp_path):
    root = server_with_folder(tmp_path / 'server')
    released = frozen(11).open_bundle(root)
    assert [a.type for a in released.assets] == ['well-tops']
    assert released.unlisted == ['lineage/prov.json', 'recipe.json']
    current = bundle.open_bundle(root)
    assert [a.type for a in current.assets] == ['well-tops'] and current.unlisted == []
    assert [row['path'] for row in current.folder] == ['recipe.json', 'lineage/prov.json']


def _flip(path):
    raw = bytearray(path.read_bytes()); raw[len(raw) // 2] ^= 0x01; path.write_bytes(bytes(raw))


def _link_items(root):
    os.rename(root / 'items', root / 'items-real')
    os.symlink('items-real', root / 'items')


def _outside(root):
    os.rename(root / 'originals/wells.csv', root / 'wells.csv')
    rewrite(root, lambda m: m['folder']['files'][1].update(path='wells.csv'))


def _other_target(root):
    """The recipe's bytes match their row, but its target is not the item's."""
    recipe = json.loads(RECIPE); recipe['target']['id'] = 'tops'; raw = json.dumps(recipe).encode()
    (root / 'recipe.json').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    rewrite(root, lambda m: (m['folder']['files'][0].update(sha256=digest, bytes=len(raw)), m['folder']['recipe'].update(sha256=digest)))


DEFECTS = {
    'flipped-byte': (lambda root: _flip(root / 'items/wells.parquet'), 'The folder file items/wells.parquet does not match its checksum.'),
    'missing-file': (lambda root: (root / 'originals/wells.csv').unlink(), 'The folder file originals/wells.csv is missing or has the wrong size.'),
    'linked-items': (_link_items, 'The folder file items/wells.parquet is a link or lies under one.'),
    'outside-the-roles': (_outside, 'The project folder block is not valid (schema-pattern at $.folder.files[1].path).'),
    'item-of-another-target': (_other_target, 'The project folder block is not valid (item-target at $.folder.files[2].path).'),
}


@pytest.mark.parametrize('defect', sorted(DEFECTS))
def test_d_each_folder_defect_is_refused_by_path(tmp_path, defect):
    root = box_folder(tmp_path / 'box')
    change, sentence = DEFECTS[defect]
    change(root)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == sentence


def test_d_a_folder_file_over_the_file_limit_is_refused_by_path(tmp_path, monkeypatch):
    root = box_folder(tmp_path / 'box')
    assert len(SYNTHETIC_ITEM) > max(len(RECIPE), len(SYNTHETIC_CSV))
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', len(SYNTHETIC_ITEM) - 1)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'The folder file items/wells.parquet exceeds the supported size.'


def test_e_a_folder_needs_two_twelve_and_empty_assets_need_a_folder(tmp_path):
    root = box_folder(tmp_path / 'box')
    rewrite(root, lambda m: m.update(bundle_version='2.11.0'))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle.FOLDER_NEEDS_MINOR == 'A project folder needs bundle version 2.12.'
    rewrite(root, lambda m: (m.update(bundle_version='2.12.0'), m.pop('folder')))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == NO_ASSETS


def test_f_pack_round_trips_the_folder(tmp_path):
    root = box_folder(tmp_path / 'box')
    archive = bundle.pack(root, tmp_path / 'box.zip')
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == ['manifest.json', 'items/wells.parquet', 'lineage/prov.json', 'originals/wells.csv', 'recipe.json']
    opened = bundle.open_bundle(archive)
    assert [row['path'] for row in opened.folder] == [row['path'] for row in bundle.open_bundle(root).folder]
    assert _tree(opened.path) == _tree(root)
    opened.close()


def test_f_a_zip_with_a_malformed_folder_block_is_refused_before_any_entry_is_read(tmp_path, monkeypatch):
    root = box_folder(tmp_path / 'box')
    archive = bundle.pack(root, tmp_path / 'box.zip')
    with zipfile.ZipFile(archive) as z: entries = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(entries['manifest.json']); manifest['folder']['files'][2]['role'] = 'original'
    entries['manifest.json'] = json.dumps(manifest).encode()
    broken = tmp_path / 'broken.zip'
    with zipfile.ZipFile(broken, 'w') as z:
        for name, raw in entries.items(): z.writestr(name, raw)
    read, real = [], zipfile.ZipFile.open
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda self, name, *a, **k: (read.append(getattr(name, 'filename', name)), real(self, name, *a, **k))[1])
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(broken)
    assert str(refused.value) == 'The project folder block is not valid (media-type at $.folder.files[2].media_type).'
    assert read == ['manifest.json']


# ---- g. E117 s1 C1: bundle 2.14 reads a project folder /2 (contracts/folders/v1), through the traversal check() uses ----

VALID_2 = Path(str(files('ophiolite').joinpath('contracts/folders/v1/fixtures/valid')))
WELLS_2 = {'path': 'items/wells.parquet', 'profile': 'ophiolite.table-target/wells/1', 'kind': 'wells',
           'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'}, 'rows': 4}
GRID_2 = {'path': 'items/grid.tif', 'profile': 'geotiff/1', 'kind': 'grid',
          'osdu': {'kind': 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'}, 'declarations': [{'name': 'crs', 'value': 'EPSG:28992'}], 'rows': None}
DECLARED_2 = [{'name': 'crs', 'value': 'EPSG:28992'}, {'name': 'depth_unit', 'value': 'm'}]


def _copy_2(tmp_path, name):
    import shutil
    shutil.copytree(VALID_2 / name, tmp_path / name)
    return tmp_path / name


def test_g_bundle_items_of_the_folder_fixtures(tmp_path):
    assert bundle.open_bundle(VALID_2 / 'wells-grid').items == [{**WELLS_2, 'declarations': DECLARED_2}, GRID_2]
    assert bundle.open_bundle(VALID_2 / 'recipe-wells').items == [{**WELLS_2, 'declarations': DECLARED_2}]
    assert bundle.open_bundle(VALID_2 / 'v1-wells').items == [{**WELLS_2, 'declarations': [
        *DECLARED_2, {'name': 'depth_kind', 'value': 'MD'}, {'name': 'depth_reference', 'value': 'unknown'}]}]  # translate_1, from the recipe
    assert bundle.open_bundle(VALID_2 / 'v1-las').items == [{
        'path': 'items/well-log.parquet', 'profile': 'las2/1', 'kind': 'well-log',
        'osdu': {'kind': 'osdu:wks:work-product-component--WellLog:1.5.0'}, 'declarations': [], 'rows': 19}]
    assert bundle.open_bundle(box_folder(tmp_path / 'box')).items == [
        {**WELLS_2, 'declarations': DECLARED_2, 'rows': None}]  # a lineage without activity: no row count, never a refusal


@pytest.mark.parametrize('version', ['2.12.0', '2.13.0'])
def test_g_a_folder_2_below_two_fourteen_is_refused_by_both_entry_points(tmp_path, version):
    from ophiolite.folder import check
    root = _copy_2(tmp_path, 'wells-grid')
    rewrite(root, lambda m: m.update(bundle_version=version))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'A project folder of format /2 needs bundle version 2.14.'
    assert check(root)['first_problem'] == {'code': 'manifest-invalid', 'path': '$.bundle_version'}
    rewrite(root, lambda m: m.update(bundle_version='2.14.0'))
    assert check(root)['ok'] and len(bundle.open_bundle(root).folder) == 2
    assert json.loads((VALID_2 / 'v1-wells/manifest.json').read_text())['bundle_version'] == '2.12.0'  # /1 keeps 2.12
    assert len(bundle.open_bundle(VALID_2 / 'v1-wells').folder) == 8


def test_g_a_folder_2_beside_server_assets_is_refused_by_both_entry_points(tmp_path):
    from ophiolite.folder import check
    root = _copy_2(tmp_path, 'wells-grid')
    representation = {'path': 'assets/0/data.parquet', 'role': 'representation', 'media_type': 'application/vnd.apache.parquet',
                      'asset': 0, 'sha256': 'a' * 64, 'bytes': 1}
    rewrite(root, lambda m: (m.update(assets=[{'files': []}]), m['folder']['files'].append(representation)))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'A /2 folder beside server assets is not read yet.'
    assert check(root)['first_problem'] == {'code': 'assets-unsupported', 'path': '$.assets', 'sentence': 'A /2 folder beside server assets is not read yet.'}


def test_g_one_byte_of_a_folder_2_item_changed_at_equal_size_is_refused_by_path(tmp_path):
    root = _copy_2(tmp_path, 'wells-grid')
    _flip(root / 'items/wells.parquet')
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'The folder file items/wells.parquet does not match its checksum.'


def test_g_folder_verdicts_reports_every_file():
    rows = json.loads((VALID_2 / 'wells-grid/manifest.json').read_text())['folder']['files']
    sizes = sum(row['bytes'] for row in rows)
    assert bundle.folder_verdicts(VALID_2 / 'wells-grid', rows, 0) == (['ok', 'ok'], sizes)
    broken = [{**rows[0], 'sha256': '0' * 64}, {**rows[1], 'path': 'items/absent.tif'}]
    assert bundle.folder_verdicts(VALID_2 / 'wells-grid', broken, 0) == (['file-digest', 'file-missing'], sizes)


def test_g_pack_round_trips_a_folder_2_with_its_grid(tmp_path):
    archive = bundle.pack(VALID_2 / 'wells-grid', tmp_path / 'grid.zip')
    with zipfile.ZipFile(archive) as z: assert z.namelist() == ['manifest.json', 'items/grid.tif', 'items/wells.parquet']
    opened = bundle.open_bundle(archive)
    assert opened.items == bundle.open_bundle(VALID_2 / 'wells-grid').items and _tree(opened.path) == _tree(VALID_2 / 'wells-grid')
    opened.close()


def test_g_a_zip_with_a_malformed_folder_2_block_is_refused_before_any_entry_is_read(tmp_path, monkeypatch):
    archive = bundle.pack(VALID_2 / 'wells-grid', tmp_path / 'grid.zip')
    with zipfile.ZipFile(archive) as z: entries = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(entries['manifest.json']); manifest['folder']['items'][1]['rows'] = 4
    entries['manifest.json'] = json.dumps(manifest).encode()
    broken = tmp_path / 'broken.zip'
    with zipfile.ZipFile(broken, 'w') as z:
        for name, raw in entries.items(): z.writestr(name, raw)
    read, real = [], zipfile.ZipFile.open
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda self, name, *a, **k: (read.append(getattr(name, 'filename', name)), real(self, name, *a, **k))[1])
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(broken)
    assert str(refused.value) == 'The project folder block is not valid (rows-type at $.folder.items[1].rows).'
    assert read == ['manifest.json']
