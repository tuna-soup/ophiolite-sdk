"""E108 S4 (D12 a'-b'', R4-7', S4R2-4 to S4R2-6): the vendor-files example procedure's own parsers, called directly on the
committed fixtures. ZMAP+ → ESRI equals the registered ESRI crop node for node; IRAP → ESRI within the twin's 5e-4; the
emitted header is node-registered (`xllcenter 538750`, `yllcenter 6159500`, `cellsize 250`); the tops of both wells are
literal; every declaration is forwarded from the settings; rotated, unevenly spaced, extent-disagreeing and malformed
inputs stop the run with a sentence that names no path."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from ophiolite.procedures import LocalSystem

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/procedures/vendor-files'
SHAPES = ROOT / 'tests/fixtures/vendor-shapes'
CROPS = ROOT / 'conformance/fixtures/grids_gis/crops'
# In tests/gateway, not tests/: the unit lane and sdk-export qualify run ophiolite-sdk/ extracted alone, where the example and
# its fixtures are absent, and RequiredCases refuses a skip; the gateway lane runs in the one tree (E108 S4).
SETTINGS = {'well': 'HON-GT-01', 'tops_file': 'tops.txt', 'zmap_file': 'surface.zmap', 'irap_file': 'surface.irap', 'crs': 'EPSG:23031',
            'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'}
DECLARED = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'}  # E119a D10
REFUSED = 'This grid is rotated or unevenly spaced; this procedure does not read it.'
HON = [('NU', '0'), ('NM', '220'), ('NL', '240'), ('NMRF', '260'), ('NLFF', '340'), ('NLLFC', '380'), ('CKHM', '660'), ('CKGR', '678'),
       ('CKTXM', '1120'), ('CKTXG', '1173'), ('KNGLU', '1205'), ('KNGLM', '1389'), ('KNGLG', '1497'), ('KNGLL', '1650'), ('KNNSL', '1831'),
       ('KNNCU', '1967.6'), ('KNNC', '1978.72'), ('KNNSB', '2138.13'), ('KNNC', '2281.06'), ('KNNSR', '2435.95'), ('SLDNR', '2466.86'),
       ('SLDND', '2557.9'), ('SLDNA', '2620.22'), ('AT', '3135.6')]  # nlog-tops.xlsx, HON-GT-01 (README hand counts)


def module():
    spec = importlib.util.spec_from_file_location('e108_vendor_files', EXAMPLE / 'vendor_files.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def folder(tmp_path):
    here = tmp_path / 'export'
    here.mkdir()
    shutil.copyfile(SHAPES / 'nlog-tops-petrel.txt', here / 'tops.txt')
    shutil.copyfile(CROPS / '11-ro-crop.zmap', here / 'surface.zmap')
    shutil.copyfile(CROPS / '11-ro-crop-synthetic.irap', here / 'surface.irap')
    return here


def fetch(folder, **changed):
    return module().fetch({'folder': LocalSystem({'folder': str(folder)})}, {**SETTINGS, **changed})


def esri(raw):
    lines = raw.decode('ascii').splitlines()
    head = dict(l.split() for l in lines[:6])
    return head, [[None if t == head['NODATA_value'] else float(t) for t in l.split()] for l in lines[6:]]


def refused(folder, sentence, **changed):
    with pytest.raises(ValueError) as stopped: fetch(folder, **changed)
    assert str(stopped.value) == sentence and str(folder) not in str(stopped.value)


def test_zmap_becomes_the_registered_esri_crop_node_for_node(folder):
    out = fetch(folder)['surface_zmap']
    head, rows = esri(out.bytes)
    assert head == {'ncols': '30', 'nrows': '40', 'xllcenter': '538750', 'yllcenter': '6159500', 'cellsize': '250', 'NODATA_value': '-99999'}
    crop_head, crop = esri((CROPS / '11-ro-crop.asc').read_bytes())
    assert (crop_head['xllcenter'], crop_head['yllcenter'], crop_head['cellsize']) == ('538750', '6159500', '250')
    assert rows == crop  # node for node, nulls included (480)
    assert sum(v is None for row in rows for v in row) == 480 and rows[5][0] == -3944.5833 and rows[39][29] == -4650.1465
    assert (out.profile, out.declared, out.filename) == ('esri-ascii-grid/1', DECLARED, 'surface-from-zmap.asc')


def test_irap_becomes_the_same_grid_within_the_float32_bound(folder):
    out = fetch(folder)['surface_irap']
    head, rows = esri(out.bytes)
    assert head == {'ncols': '30', 'nrows': '40', 'xllcenter': '538750', 'yllcenter': '6159500', 'cellsize': '250', 'NODATA_value': '-99999'}
    _, crop = esri((CROPS / '11-ro-crop.asc').read_bytes())
    assert [[v is None for v in row] for row in rows] == [[v is None for v in row] for row in crop]
    assert max(abs(a - b) for ra, rb in zip(rows, crop) for a, b in zip(ra, rb) if a is not None) <= 5e-4
    assert abs(rows[39][0] - -4136.8589) <= 5e-4  # the IRAP file's first node is the south-west one
    assert out.declared == DECLARED


def test_the_tops_of_each_well_in_file_order(folder):
    out = fetch(folder)['tops']
    assert (out.profile, out.declared, out.filename) == ('well-tops-csv/1', {'depth_unit': 'm'}, 'tops.csv')  # an unknown basis is not declared (S4R-2)
    assert out.bytes.decode() == 'name,md\n' + ''.join('%s,%s\n' % pick for pick in HON)
    other = fetch(folder, well='NLW-GT-01')['tops'].bytes.decode().splitlines()
    assert len(other) == 1 + 37 and other[1:3] == ['NU,0', 'NUOT,223'] and other[-1] == 'RBSHR,4356'
    assert [l for l in other if l.startswith('KNNC,')] == ['KNNC,2060.88', 'KNNC,2299.68']


@pytest.mark.parametrize('key, value', [('crs', 'EPSG:25831'), ('xy_unit', 'ft'), ('z_unit', 'ft'), ('z_meaning', 'depth'),
                                        ('positive', 'down'), ('vertical_datum', 'MSL')])
def test_each_declaration_is_forwarded_from_the_settings(folder, key, value):
    made = fetch(folder, **{key: value})
    for role in ('surface_zmap', 'surface_irap'):
        assert made[role].declared == {**DECLARED, key: value}


def test_a_rotated_grid_is_refused(folder):
    shutil.copyfile(SHAPES / 'refuse-rotated.irap', folder / 'rotated.irap')
    refused(folder, REFUSED, irap_file='rotated.irap')


def test_an_unevenly_spaced_grid_is_refused(folder):
    shutil.copyfile(SHAPES / 'refuse-unequal.zmap', folder / 'unequal.zmap')
    refused(folder, REFUSED, zmap_file='unequal.zmap')


def test_a_grid_whose_stated_spacing_disagrees_with_its_extents_is_refused(folder):
    shutil.copyfile(SHAPES / 'refuse-extent.zmap', folder / 'extent.zmap')
    refused(folder, REFUSED, zmap_file='extent.zmap')


def test_a_zmap_with_too_few_or_too_many_nodes_is_refused(folder):
    text = (CROPS / '11-ro-crop.zmap').read_text()
    (folder / 'short.zmap').write_text(text.rstrip('\n').rsplit(' ', 1)[0] + '\n')
    refused(folder, 'The ZMAP+ file holds 1199 nodes; its header says 1200.', zmap_file='short.zmap')
    (folder / 'long.zmap').write_text(text + '     -4000.0000\n')
    refused(folder, 'The ZMAP+ file holds 1201 nodes; its header says 1200.', zmap_file='long.zmap')


def test_a_truncated_irap_is_refused(folder):
    lines = (CROPS / '11-ro-crop-synthetic.irap').read_text().splitlines()
    (folder / 'short.irap').write_text('\n'.join(lines[:-1]) + '\n')
    with pytest.raises(ValueError, match=r'^The IRAP file holds \d+ nodes; its header says 1200\.$'): fetch(folder, irap_file='short.irap')


@pytest.mark.parametrize('row, sentence', [
    ('"HON-GT-01" "XX"', 'Pick 25 of the tops file does not have one value for each of its 3 columns.'),
    ('"HON-GT-01" Top Chalk 812.5', 'Pick 25 of the tops file does not have one value for each of its 3 columns.'),
    ('"HON-GT-01" "XX" -999', 'The pick XX of HON-GT-01 has no MD (-999).')])
def test_a_malformed_or_null_pick_is_refused(folder, row, sentence):
    lines = (SHAPES / 'nlog-tops-petrel.txt').read_text().splitlines()
    lines.insert(7 + 24, row)  # after the last HON-GT-01 pick
    (folder / 'tops.txt').write_text('\n'.join(lines) + '\n')
    refused(folder, sentence)


def test_an_unknown_well_or_a_file_outside_the_folder_or_a_missing_file_is_refused(folder):
    refused(folder, 'The tops file has no picks for the well HON-GT-03.', well='HON-GT-03')
    refused(folder, 'A file name setting names a file inside the folder, without a path.', zmap_file='../surface.zmap')
    refused(folder, 'The folder has no file named absent.zmap that can be read.', zmap_file='absent.zmap')


CLAIM = 'Read from files in the shapes of a Petrel well-tops export, IRAP classic ASCII and ZMAP+; not tested with Petrel or Kingdom.'


@pytest.mark.parametrize('path', ['tests/fixtures/vendor-shapes/README.md', 'examples/procedures/vendor-files/README.md'])
def test_the_claim_sentence_stands_and_no_compatibility_is_claimed(path):
    """Commit 5 test 5 (D12 e, 4-5): both READMEs carry the claim sentence and make no compatibility assertion about
    Petrel or Kingdom ("compatible", "works with", "tested with" outside the claim's own "not tested with",
    "interoperab..."). The release note is checked once at S4-4 (a nightly release folds pending notes away). Wording
    check, no mutation."""
    flat = ' '.join((ROOT / path).read_text().split())
    assert CLAIM in flat
    lowered = flat.replace(CLAIM, '').lower()
    for phrase in ('compatib', 'works with', 'tested with', 'interoperab', 'certified', 'supports petrel', 'supports kingdom'):
        assert phrase not in lowered, (path, phrase)
