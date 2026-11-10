"""E117 s1 C3 (D6): `ophiolite bundle check` says what a project folder holds, in words.

    a  verified: the fixture with a grid, a folder write_folder made, a /1 folder
    b  not verified: the file whose bytes changed, the item whose OSDU kind is wrong, in words; exit 1; no JSON path
    c  --details adds every file's verdict and the code and JSON path; --json is check()'s report
    d  a server bundle's line is the one it was before (dd0d640b8)
"""
import json
import shutil
from importlib.resources import files
from pathlib import Path

import pytest
from ophiolite import cli
from ophiolite.folder import check

VALID = Path(str(files('ophiolite').joinpath('contracts/folders/v1/fixtures/valid')))
SERVER = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles' / '2.0'


def run(capsys, *argv):
    try:
        cli.main(['bundle', 'check', *map(str, argv)]); code = 0
    except SystemExit as stop:
        code = stop.code
    return code, capsys.readouterr().out


def copy(tmp_path, name):
    shutil.copytree(VALID / name, tmp_path / name)
    return tmp_path / name


def edit(folder, change):
    path = folder / 'manifest.json'
    document = json.loads(path.read_text()); change(document); path.write_text(json.dumps(document))


def test_a_verified_folders_say_what_they_hold(tmp_path, capsys):
    assert run(capsys, VALID / 'wells-grid') == (0, 'Project folder verified: 2 items (wells, 4 rows; grid). Checksums show integrity, not authorship.\n')
    assert run(capsys, VALID / 'v1-wells') == (0, 'Project folder verified: 1 item (wells, 4 rows). Checksums show integrity, not authorship.\n')
    pd = pytest.importorskip('pandas'); pytest.importorskip('pyarrow'); pytest.importorskip('pyproj')
    from ophiolite.folder import write_folder
    write_folder(tmp_path / 'out', {'wells': (pd.DataFrame({'id': ['SYN-F1'], 'name': ['F1'], 'x': [217000.5], 'y': [568500.25]}), {'crs': 'EPSG:28992'})})
    assert run(capsys, tmp_path / 'out') == (0, 'Project folder verified: 1 item (wells, 1 row). Checksums show integrity, not authorship.\n')


def test_b_a_changed_file_is_named_by_its_path(tmp_path, capsys):
    folder = copy(tmp_path, 'wells-grid')
    raw = bytearray((folder / 'items/grid.tif').read_bytes()); raw[-1] ^= 1; (folder / 'items/grid.tif').write_bytes(bytes(raw))
    code, out = run(capsys, folder)
    assert (code, out) == (1, 'Project folder not verified: items/grid.tif: its bytes do not match its checksum.\n')


def test_b_a_wrong_osdu_kind_names_the_item_in_words(tmp_path, capsys):
    folder = copy(tmp_path, 'recipe-wells')
    edit(folder, lambda d: d['folder']['items'][0].update(osdu={'kind': 'osdu:wks:work-product-component--WellboreTrajectory:1.4.0'}))
    code, out = run(capsys, folder)
    assert (code, out) == (1, 'Project folder not verified: item 1, items/wells.parquet, its OSDU kind: '
                              'it is not the OSDU statement the export matrix gives its profile.\n')
    assert '$.' not in out and 'osdu-kind' not in out


def test_c_details_and_json(tmp_path, capsys):
    folder = copy(tmp_path, 'recipe-wells')
    edit(folder, lambda d: d['folder']['items'][0].update(osdu={'kind': 'osdu:wks:work-product-component--WellboreTrajectory:1.4.0'}))
    code, out = run(capsys, folder, '--details')
    assert code == 1 and out.splitlines()[1:] == ['  first problem: osdu-kind at $.folder.items[0].osdu']
    code, out = run(capsys, VALID / 'wells-grid', '--details')
    assert (code, out.splitlines()[1:]) == (0, ['  items/wells.parquet (item): ok', '  items/grid.tif (item): ok'])
    code, out = run(capsys, folder, '--json')
    assert code == 1 and json.loads(out) == check(folder)
    assert json.loads(run(capsys, VALID / 'wells-grid', '--json')[1]) == check(VALID / 'wells-grid')


def test_d_a_server_bundle_keeps_its_line(capsys):
    assert run(capsys, SERVER) == (0, 'Bundle verified: 1 exact revisions, 0 curves, 1 other data. Checksums show integrity, not authorship.\n')
