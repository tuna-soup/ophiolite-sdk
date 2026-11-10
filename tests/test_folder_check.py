"""E117 s0 C3 (D4): ophiolite.folder.check — a byte-level literal report for a server bundle, a /1 folder and a /2 folder.

    a  the frozen report of every valid fixture folder (contracts/folders/v1/fixtures/valid) and of a server bundle
    b  /2: a missing file, a file link, a directory link, a size mismatch, a file over MAX_FILE_BYTES, a total over
       MAX_TOTAL_BYTES, an unlisted file, one byte changed at equal size — each named in first_problem
    c  /2: a block the validator refuses names its code and place; nothing is read
    d  /1 and server bundles go through open_bundle unchanged; /1 items come from the verified recipe
    e  check never imports pandas or pyarrow
"""
import json
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.folder import check

VALID = Path(str(files('ophiolite').joinpath('contracts/folders/v1/fixtures/valid')))
SERVER = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles' / '2.0'
WELLS = {'path': 'items/wells.parquet', 'kind': 'wells', 'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'}}
GRID = {'path': 'items/grid.tif', 'kind': 'grid', 'osdu': {'kind': 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'}}
IDENTITY = [('identity/entities.parquet', 'identity-entities'), ('identity/aliases.parquet', 'identity-aliases'),
            ('identity/relationships.parquet', 'identity-relationships')]


def report(schema, rows, items, problem=None, verdicts=None):
    verdicts = verdicts or {}
    return {'ok': problem is None, 'verified': 'bytes', 'schema': schema,
            'files': [{'path': p, 'role': r, 'verdict': verdicts.get(p, 'ok')} for p, r in rows], 'items': items, 'first_problem': problem}


def copy(tmp_path, name):
    shutil.copytree(VALID / name, tmp_path / name)
    return tmp_path / name


# ---- a. frozen reports ------------------------------------------------------------------------------------------------

def test_a_the_reports_of_the_valid_folders_and_of_a_server_bundle():
    assert check(VALID / 'recipe-wells') == report('ophiolite.project-folder/2', [
        ('recipe.json', 'recipe'), ('originals/wells.csv', 'original'), ('items/wells.parquet', 'item'), ('lineage/prov.json', 'lineage-prov')],
        [{**WELLS, 'derived': 'manifest', 'verdict': 'ok'}])
    assert check(VALID / 'wells-grid') == report('ophiolite.project-folder/2', [('items/wells.parquet', 'item'), ('items/grid.tif', 'item')],
                                                 [{**WELLS, 'derived': 'manifest', 'verdict': 'ok'}, {**GRID, 'derived': 'manifest', 'verdict': 'ok'}])
    assert check(VALID / 'v1-wells') == report('ophiolite.project-folder/1', [
        ('recipe.json', 'recipe'), ('originals/wells.csv', 'original'), ('items/wells.parquet', 'item'), *IDENTITY,
        ('lineage/prov.json', 'lineage-prov'), ('osdu/manifest.json', 'osdu-manifest')], [{**WELLS, 'derived': 'recipe', 'verdict': 'ok'}])
    assert check(VALID / 'v1-las') == report('ophiolite.project-folder/1', [
        ('recipe.json', 'recipe'), *[(f'originals/{n}.las', 'original') for n in ('syn-w2', 'syn-w2b', 'syn-w3', 'syn-w4', 'syn-w4b')],
        ('items/well-log.parquet', 'item'), *IDENTITY, ('lineage/prov.json', 'lineage-prov'), ('osdu/manifest.json', 'osdu-manifest')],
        [{'path': 'items/well-log.parquet', 'kind': 'well-log', 'osdu': {'kind': 'osdu:wks:work-product-component--WellLog:1.5.0'},
          'derived': 'recipe', 'verdict': 'ok'}])
    assert check(SERVER) == report(None, [('assets/0/original.csv', 'original'), ('assets/0/descriptor.json', 'descriptor'),
                                          ('assets/0/data.json', 'normalized')], [])


# ---- b. every file fault of a /2 folder, by path ----------------------------------------------------------------------

GRID_ROWS = [('items/wells.parquet', 'item'), ('items/grid.tif', 'item')]


def _grid_report(path, code, extra=()):
    rows = GRID_ROWS + list(extra)
    verdicts = {path: code}
    items = [{**WELLS, 'derived': 'manifest', 'verdict': verdicts.get(WELLS['path'], 'ok')},
             {**GRID, 'derived': 'manifest', 'verdict': verdicts.get(GRID['path'], 'ok')}]
    return report('ophiolite.project-folder/2', rows, items, {'code': code, 'path': path}, verdicts)


def test_b_a_missing_file(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    (folder / 'items/grid.tif').unlink()
    assert check(folder) == _grid_report('items/grid.tif', 'file-missing')


def test_b_a_file_link_with_the_right_bytes(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    outside = tmp_path / 'outside.tif'
    shutil.move(folder / 'items/grid.tif', outside)
    (folder / 'items/grid.tif').symlink_to(outside)
    assert check(folder) == _grid_report('items/grid.tif', 'file-link')


def test_b_a_directory_link_with_the_right_bytes(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    shutil.move(folder / 'items', tmp_path / 'elsewhere')
    (folder / 'items').symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    result = check(folder)
    assert result['first_problem'] == {'code': 'file-link', 'path': 'items/wells.parquet'}
    assert [f['verdict'] for f in result['files']] == ['file-link', 'file-link']


def test_b_a_size_mismatch(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    with open(folder / 'items/grid.tif', 'ab') as handle: handle.write(b'\0')
    assert check(folder) == _grid_report('items/grid.tif', 'file-size')


def _manifest_edit(folder, change):
    path = folder / 'manifest.json'
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


def test_b_a_file_listed_over_the_file_limit(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    _manifest_edit(folder, lambda d: d['folder']['files'][1].update(bytes=bundle.MAX_FILE_BYTES + 1))
    assert bundle.MAX_FILE_BYTES == 33554432
    assert check(folder) == _grid_report('items/grid.tif', 'file-too-large')


def test_b_a_total_over_the_bundle_limit(tmp_path, monkeypatch):
    folder = copy(tmp_path, 'wells-grid')
    size = (folder / 'items/wells.parquet').stat().st_size
    monkeypatch.setattr(bundle, 'MAX_TOTAL_BYTES', size + 1)  # the second file crosses it
    assert check(folder) == _grid_report('items/grid.tif', 'total-too-large')


def test_b_an_unlisted_file(tmp_path):
    folder = copy(tmp_path, 'wells-grid')
    (folder / 'items/notes.txt').write_text('not listed')
    result = check(folder)
    assert result == {**_grid_report('items/notes.txt', 'file-unlisted', [('items/notes.txt', None)]),
                      'items': [{**WELLS, 'derived': 'manifest', 'verdict': 'ok'}, {**GRID, 'derived': 'manifest', 'verdict': 'ok'}]}


def test_b_one_byte_of_an_item_changed_at_equal_size_names_that_file(tmp_path):
    folder = copy(tmp_path, 'recipe-wells')
    target = folder / 'items/wells.parquet'
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    target.write_bytes(bytes(raw))
    recipe_before = (VALID / 'recipe-wells/recipe.json').read_bytes()
    result = check(folder)
    assert result['first_problem'] == {'code': 'file-digest', 'path': 'items/wells.parquet'}
    assert [(f['path'], f['verdict']) for f in result['files']] == [
        ('recipe.json', 'ok'), ('originals/wells.csv', 'ok'), ('items/wells.parquet', 'file-digest'), ('lineage/prov.json', 'ok')]
    assert result['items'][0]['verdict'] == 'file-digest' and (folder / 'recipe.json').read_bytes() == recipe_before


# ---- c. the block's own rules -----------------------------------------------------------------------------------------

def test_c_a_block_the_validator_refuses_names_its_code_and_place(tmp_path):
    folder = copy(tmp_path, 'recipe-wells')
    _manifest_edit(folder, lambda d: d['folder']['items'][0].update(osdu={'kind': 'osdu:wks:work-product-component--WellboreTrajectory:1.4.0'}))
    (folder / 'items/wells.parquet').unlink()  # never reached: the block is refused first
    assert check(folder) == report('ophiolite.project-folder/2', [], [], {'code': 'osdu-kind', 'path': '$.folder.items[0].osdu'})


def test_c_no_manifest_and_not_a_folder(tmp_path):
    assert check(tmp_path) == report(None, [], [], {'code': 'file-missing', 'path': 'manifest.json'})
    assert check(tmp_path / 'absent') == report(None, [], [], {'code': 'not-a-folder', 'path': None, 'sentence': 'A project folder is a directory.'})


# ---- d. /1 and server bundles through open_bundle ---------------------------------------------------------------------

def test_d_a_v1_folder_with_a_changed_byte_is_refused_by_open_bundle_by_path(tmp_path):
    folder = copy(tmp_path, 'v1-wells')
    target = folder / 'items/wells.parquet'
    raw = bytearray(target.read_bytes())
    raw[10] ^= 0x01
    target.write_bytes(bytes(raw))
    assert check(folder) == report('ophiolite.project-folder/1', [], [], {
        'code': 'bundle-refused', 'path': None, 'sentence': 'The folder file items/wells.parquet does not match its checksum.'})


def test_d_an_unlisted_file_beside_a_server_bundle_is_named(tmp_path):
    shutil.copytree(SERVER, tmp_path / 'server')
    (tmp_path / 'server/extra.txt').write_text('x')
    result = check(tmp_path / 'server')
    assert result['first_problem'] == {'code': 'file-unlisted', 'path': 'extra.txt'} and not result['ok']
    assert result['files'][-1] == {'path': 'extra.txt', 'role': None, 'verdict': 'file-unlisted'}


# ---- e. no table library --------------------------------------------------------------------------------------------

def test_e_check_imports_neither_pandas_nor_pyarrow():
    code = ('import sys\nfrom ophiolite.folder import check\n'
            'for name in sys.argv[1:]: assert check(name)["ok"], name\n'
            'print(sorted(m for m in ("pandas", "pyarrow", "numpy") if m in sys.modules))')
    done = subprocess.run([sys.executable, '-c', code, *(str(VALID / n) for n in ('recipe-wells', 'wells-grid', 'v1-wells', 'v1-las'))],
                          capture_output=True, text=True, env={**os.environ}, timeout=60)
    assert (done.returncode, done.stdout.strip()) == (0, '[]'), done.stderr
