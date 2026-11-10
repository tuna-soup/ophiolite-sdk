"""E147 s2 C2 (strategy E147-s2-export-descriptors D5, C2): write_bundle writes a citation and its descriptors.

With a citation, the bundle is schema 2 at 2.15 (or the content's own minor above it), every file row states its media
type, and the descriptors the citation lists are written into the staging folder before the manifest and before the
bundle checks itself, so a failure leaves nothing. Without one the bytes are main's: the digests below were taken from
the tree before C2 with `created_at` and `exporter.version` fixed (they change with the clock and the release).

    X-2  the bundle-wells fixture's read with its citation (prov.json left out) gives the fixture's rows and the
         contract's documents from the fixture's files; against the fixture's own documents the whole difference is
         the prov.json node and the keywords
    a    every uncited export kind keeps its bytes
    b    the version: 2.15 for a LAS-only or a 2.8 package export; 2.16 when a profile is 16
    b2   E147 s2b: a typed table (tops, deviation survey, time-depth, point set) is a Croissant record set read by
         jsonPath from its data.json, and its bundle is 2.16; a tampered path is refused, in words by default
    c    the media types of the emitted rows, and the resource type of a mixed bundle
    d    a failing write leaves no destination and no staging folder
    e    open_bundle refuses a tampered or a missing descriptor of a written bundle
"""
import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.bundle import DescriptorRefused, open_bundle
from test_bundle import typed_read
from test_bundle_compat import KINDS, item, reprofiled
from test_bundle_package import item as package_item, recipe_read, shapefile_read, written as package_written
from test_bundle_provenance import las_bundle, read_on_a_computer

WELLS = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/bundle-wells')))
FIXTURE = json.loads((WELLS / 'manifest.json').read_text())
CITATION = {k: v for k, v in FIXTURE['citation'].items() if k != 'prov'}
NAMES = ('ro-crate-metadata.json', 'croissant.json', 'datacite.json')
CONTRACT = bundle._descriptors_contract()


class WellsRead:
    """The bundle-wells fixture's asset as Client.read serves it (its original, descriptor and curve bytes)."""
    def __init__(self):
        self.artifact = (WELLS / 'assets/0/original.las').read_bytes()
        self._wire_descriptors = [json.loads((WELLS / 'assets/0/descriptor-GR.json').read_bytes())]
        self._wire_curve_bytes = [(WELLS / 'assets/0/curve-GR.json').read_bytes()]
        self._wire_curves = [json.loads(self._wire_curve_bytes[0])]


def las_item(read=None):
    read = read or WellsRead(); d = read._wire_descriptors[0]
    return {'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, read


def cited(path, items, citation=CITATION):
    return bundle.write_bundle(path, items, citation=citation)


def load(path): return json.loads(Path(path).read_text())


def rows(opened, index=0):
    return [(f['path'], f['role'], f['media_type']) for f in opened.manifest['assets'][index]['files']]


# ---- X-2: the fixture's read gives the fixture's rows and the contract's documents ------------------------------------

def test_x2_the_fixture_read_gives_the_fixture_rows_and_the_contract_documents(tmp_path):
    opened = cited(tmp_path / 'b', [las_item()])
    manifest = opened.manifest
    assert (manifest['schema'], manifest['bundle_version'], manifest['citation']) == (bundle.SCHEMA_2, '2.15.0', CITATION)
    assert manifest['assets'][0]['type'] == 'well-log'
    assert manifest['assets'][0]['files'] == FIXTURE['assets'][0]['files']  # paths, roles, media types, digests, sizes
    expected = CONTRACT.documents(*CONTRACT.inputs(dict(FIXTURE, citation=CITATION)), 'Well log bundle')
    assert sorted(expected) == sorted(NAMES)
    for name in NAMES:
        raw = (tmp_path / 'b' / name).read_bytes()
        assert raw == CONTRACT.serialize(expected[name]), name
    assert sorted(p.name for p in (tmp_path / 'b').iterdir()) == ['assets', 'croissant.json', 'datacite.json', 'manifest.json', 'ro-crate-metadata.json']
    assert opened.unlisted == []


def test_x2_against_the_fixture_documents_only_prov_and_the_keywords_differ(tmp_path):
    cited(tmp_path / 'b', [las_item()])
    crate = load(WELLS / 'ro-crate-metadata.json')
    crate['@graph'] = [node for node in crate['@graph'] if node['@id'] != 'prov.json']
    [root] = [node for node in crate['@graph'] if node['@id'] == './']
    root['hasPart'] = [part for part in root['hasPart'] if part != {'@id': 'prov.json'}]
    assert root.pop('keywords') == ['well log', 'gamma ray', 'synthetic']
    croissant = load(WELLS / 'croissant.json')
    assert croissant.pop('keywords') == ['well log', 'gamma ray', 'synthetic']
    assert load(tmp_path / 'b/ro-crate-metadata.json') == crate
    assert load(tmp_path / 'b/croissant.json') == croissant
    assert load(tmp_path / 'b/datacite.json') == load(WELLS / 'datacite.json')


# ---- a. an uncited export keeps main's bytes ------------------------------------------------------------------------

UNCITED = {  # sha256 over (path, bytes) of every file, manifest created_at and exporter.version fixed; taken before C2
    'curve-only': '93c82df8dd35a43a289f9b9c83929949f64684f6cd414968031e01d9ac5ba1d3',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 8b648cdc... with the pair removed
    'well-tops': 'dbe270f36493a853f3117b992e9ff3ad29e285985b53b19d34f0ca8dddfb1f2e',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 66d1fe00... with the pair removed
    'trajectory': 'd79232afc5c15faf6de596037035fba36c7ff8304da76696533470db202fdbe1',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; dc560361... with the pair removed
    'grid': 'ed07c324088892cb7d995271a4b42b1e427f44cd7aadf0fc6e48a0a067dae06a',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 18c15929... with the pair removed
    'mesh': 'ff5fb2f73a719b7c0f9d80ec9c1590fa83e5b686ada9a7fff29df67f4f9a0175',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 5e117c7a... with the pair removed
    'point-set': '1eda0cdf3fba534420a14996ddebd5f32bd5f13c1f19c9f70d14df564039cce1',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 1d0db366... with the pair removed
    'fault-sticks': 'c72a318873347642a5a398e0e935ceb7d063a773b369bba95c9a9dbcc71e4922',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 3a9b98a4... with the pair removed
    'slices': '3962086b8dd3b874a3dcaea46575150e7019e72e62aa4aa91077ca54e3a3cf4f',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; e145364d... with the pair removed
    'entity-graph': 'b36949c57e12d8a12d32ca61707f39278b5fe8227d3255901156607089a5a7be',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 95e7a460... with the pair removed
    'wavelet': '0de481fa47e67f4d08fef987fd4eb8b4ff2d85f015e45c3e4802b33d8cbfd9f2',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 6b26db27... with the pair removed
    'model-section': '23b346482193368231ef5ea2f686845505c0b9aee2c338da41090cd0321a90d0',  # E168 s0: its fixture gains osdu_kind/osdu_kind_reason; 9ab9cc5e... with the pair removed
    'seismic-section': '994bb2537fcb44888b1cf44165c7ceb88f2533de9946fb28441523b711fa2016',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 9fec3e68... with the pair removed
    'time-depth': 'a160de10c39300026c038df1acc32fd60416ba7b312f18d2da46c15053faf2cf',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; c5dc1c59... with the pair removed
    'geojson-feature-set': 'ac82f2093d4107778f132fb1b80a720f0ff1b56a2155de486e798d22089089e5',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; b25aab5d... with the pair removed
    'geopackage-feature-set': 'e901147cf279df766c76c0226f983d40089818f829a73e72e46884331284da1f',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 5bdd6edc... with the pair removed
    'zmap-grid': 'd4be160c35629668d1ca8f3ab060805f24d3ecae88f508d57e9cf69cb48500e9',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 89975014... with the pair removed
    'cps3-grid': '722afab49767fefda7c9fd7db20c226fa6209bab5f324f7c84b2b4c196c94e4f',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; 85e55229... with the pair removed
    'irap-grid': '1050a4fe7a7836ed6867942f98b1dde0cb8a537c7139694d75bb4c3cce3a19e7',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; de78eb67... with the pair removed
    'kept-original': 'd7d4bd3af84275a6a43c9901275d222919ae67d5b4ebfcd35098b2eb9e382705',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; dc5587ef... with the pair removed
    'shapefile-package': '052b8170ca36da67aea30fd92a5fb1aafbd46ee9f017ee07f8aa9782655f160a',  # E168 s0: the descriptor gains osdu_kind/osdu_kind_reason; cf40e2d3... with the pair removed
}


def tree_digest(root):
    root = Path(root); h = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        raw = path.read_bytes()
        if path.name == 'manifest.json':
            manifest = json.loads(raw); manifest['created_at'] = 'fixed'; manifest['exporter']['version'] = 'fixed'
            raw = (json.dumps(manifest, indent=2) + '\n').encode()
        h.update(path.relative_to(root).as_posix().encode() + b'\0' + raw + b'\0')
    return h.hexdigest()


def uncited_writers():
    writers = {name: write for name, (write, _) in KINDS.items()}
    writers['kept-original'] = lambda p: las_bundle(p.parent, p.name)
    writers['shapefile-package'] = lambda p: package_written(p.parent, shapefile_read(), p.name)
    return writers


def test_a_the_frozen_list_covers_every_kind():
    assert sorted(UNCITED) == sorted(uncited_writers())


@pytest.mark.parametrize('kind', sorted(uncited_writers()))
def test_a_an_uncited_export_keeps_main_s_bytes(tmp_path, kind):
    uncited_writers()[kind](tmp_path / kind)
    manifest = load(tmp_path / kind / 'manifest.json')
    assert 'citation' not in manifest and all('media_type' not in f for a in manifest['assets'] for f in a['files'])
    assert tree_digest(tmp_path / kind) == UNCITED[kind]


# ---- b. the version -------------------------------------------------------------------------------------------------

def test_b_a_cited_export_is_2_15_and_a_package_export_goes_from_2_8_to_2_15(tmp_path):
    assert package_written(tmp_path, name='uncited').manifest['bundle_version'] == '2.8.0'
    opened = cited(tmp_path / 'package', [package_item(recipe_read())])
    assert (opened.manifest['schema'], opened.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.15.0')


def test_b_a_profile_above_15_keeps_its_own_minor(tmp_path, monkeypatch):
    monkeypatch.setitem(bundle.NEWER_PROFILES, 'las2/1', 16)
    assert cited(tmp_path / 'b', [las_item()]).manifest['bundle_version'] == '2.16.0'


# ---- b2. E147 s2b: a typed table is a record set, and its bundle is 2.16 ------------------------------------------------

def field(table, name, kind, path, data='assets/0/data.json'):
    return {'@type': 'cr:Field', '@id': f'{table}/{name}', 'name': name, 'dataType': kind,
            'source': {'fileObject': {'@id': data}, 'extract': {'jsonPath': path}}}


TOPS_SET = {'@type': 'cr:RecordSet', '@id': 'assets/0/well-tops', 'name': 'assets/0/well-tops', 'field': [
    field('assets/0/well-tops', 'name', 'sc:Text', '$.tops[*].name'), field('assets/0/well-tops', 'md', 'sc:Float', '$.tops[*].md'),
    field('assets/0/well-tops', 'tvd', 'sc:Float', '$.tops[*].tvd'), field('assets/0/well-tops', 'source', 'sc:Text', '$.tops[*].source')]}
TABLE_PATHS = {  # fixture -> (record set id, [(field, json path)]): literals, never read from BUNDLE_TABLES
    'trajectory': ('assets/0/deviation-survey', [('md', '$.stations[*].md'), ('inclination', '$.stations[*].inclination'),
                                                 ('azimuth', '$.stations[*].azimuth'), ('tvd', '$.stations[*].tvd')]),
    'time-depth': ('assets/0/time-depth', [('depth', '$.depth[*]'), ('time', '$.time[*]')]),
    'points': ('assets/0/point-set', [('x', '$.points[*][0]'), ('y', '$.points[*][1]'), ('z', '$.points[*][2]')])}
TAMPERED = '$.recordSet[@id=assets/0/well-tops].field[@id=assets/0/well-tops/md].source.extract.jsonPath'


def test_b2_a_cited_tops_export_is_2_16_and_its_croissant_holds_the_tops_record_set(tmp_path):
    """Mutations: never 16 (2.15.0); the writer's gate on `type` (a tops profile outside the tables stays 15 below)."""
    opened = cited(tmp_path / 'b', [item(typed_read('tops'))])
    assert (opened.manifest['schema'], opened.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.16.0')
    assert load(tmp_path / 'b/croissant.json')['recordSet'] == [TOPS_SET]
    reopened = open_bundle(tmp_path / 'b')
    assert reopened.unlisted == [] and reopened.citation == [{'path': n, 'role': 'citation-descriptor'} for n in NAMES]


@pytest.mark.parametrize('name', sorted(TABLE_PATHS))
def test_b2_each_table_kind_is_2_16_with_its_record_set(tmp_path, name):
    cited(tmp_path / 'b', [item(typed_read(name))])
    assert load(tmp_path / 'b/manifest.json')['bundle_version'] == '2.16.0'
    (record_set,) = load(tmp_path / 'b/croissant.json')['recordSet']
    ident, paths = TABLE_PATHS[name]
    assert record_set['@id'] == ident
    assert [(f['name'], f['source']['extract']) for f in record_set['field']] == [(n, {'jsonPath': p}) for n, p in paths]


def test_b2_two_tops_exports_give_two_record_sets_each_reading_its_own_file(tmp_path):
    cited(tmp_path / 'b', [item(typed_read('tops')), item(typed_read('tops'))])
    sets = load(tmp_path / 'b/croissant.json')['recordSet']
    assert [s['@id'] for s in sets] == ['assets/0/well-tops', 'assets/1/well-tops']
    assert [{f['source']['fileObject']['@id'] for f in s['field']} for s in sets] == [{'assets/0/data.json'}, {'assets/1/data.json'}]


def test_b2_a_point_set_under_a_profile_outside_the_tables_stays_2_15(tmp_path):
    """Mutation: the gate keyed by the asset's type (point-set) instead of its profile (petrel-points-attributes/1)."""
    read = recipe_read()
    assert (read._wire_descriptor['profile'], read._wire_descriptor['scientific']['type']) == ('petrel-points-attributes/1', 'point-set')
    cited(tmp_path / 'b', [package_item(read)])
    assert load(tmp_path / 'b/manifest.json')['bundle_version'] == '2.15.0'
    assert 'recordSet' not in load(tmp_path / 'b/croissant.json')


def test_b2_a_table_profile_above_16_keeps_its_own_minor(tmp_path, monkeypatch):
    """Y-10. Mutation: a table bundle clamped to 16 (`min` for `max`, or `minor = TABLES_MINOR`)."""
    monkeypatch.setitem(bundle.NEWER_PROFILES, 'well-tops-csv/1', 17)
    assert cited(tmp_path / 'b', [item(typed_read('tops'))]).manifest['bundle_version'] == '2.17.0'


def test_b2_a_well_log_beside_a_table_is_2_16_and_alone_stays_2_15(tmp_path):
    """Mutation: always 16 for a cited bundle."""
    assert cited(tmp_path / 'log', [las_item()]).manifest['bundle_version'] == '2.15.0'
    opened = cited(tmp_path / 'both', [las_item(), item(typed_read('tops'))])
    assert opened.manifest['bundle_version'] == '2.16.0'
    assert [s['@id'] for s in load(tmp_path / 'both/croissant.json')['recordSet']] == ['assets/1/well-tops']


def tampered_tops(tmp_path):
    cited(tmp_path / 'b', [item(typed_read('tops'))])
    doc = load(tmp_path / 'b/croissant.json'); doc['recordSet'][0]['field'][1]['source']['extract']['jsonPath'] = '$.tops[*].tvd'
    (tmp_path / 'b/croissant.json').write_bytes(CONTRACT.serialize(doc))
    return tmp_path / 'b'


def test_b2_a_tampered_json_path_is_refused_naming_the_path(tmp_path):
    with pytest.raises(DescriptorRefused) as refused: open_bundle(tampered_tops(tmp_path))
    assert (refused.value.code, refused.value.file, refused.value.json_path) == ('descriptor-disagrees', 'croissant.json', TAMPERED)


def test_b2_the_cli_names_the_tables_in_words_and_the_place_only_with_details(tmp_path):
    """Y-14."""
    from test_bundle_descriptors import run
    folder = tampered_tops(tmp_path)
    line = 'Bundle not verified: the tables in croissant.json disagrees with the manifest.\n'
    assert run('bundle', 'check', str(folder)) == (1, line)
    assert run('bundle', 'check', '--details', str(folder)) == (1, line + '  first problem: descriptor-disagrees at croissant.json:' + TAMPERED + '\n')


# ---- c. media types and the resource type ---------------------------------------------------------------------------

def test_c_a_package_export_states_its_companions_as_bytes(tmp_path):
    assert rows(cited(tmp_path / 'b', [package_item(recipe_read())])) == [
        ('assets/0/original.txt', 'original', 'text/plain'), ('assets/0/descriptor.json', 'descriptor', 'application/json'),
        ('assets/0/data.json', 'normalized', 'application/json'), ('assets/0/package.json', 'package', 'application/json'),
        ('assets/0/companion-1.bin', 'companion', 'application/octet-stream'),
        ('assets/0/companion-2.bin', 'companion', 'application/octet-stream'),
        ('assets/0/interpretation.json', 'interpretation', 'application/json')]


def kept_as(name):
    read = read_on_a_computer(WellsRead())
    read._wire_descriptors[0]['acquisition']['read_by']['original']['name'] = name
    return las_item(read)


@pytest.mark.parametrize('name, kept', [('report.las', ('assets/0/provenance.las', 'provenance', 'text/plain')),
                                        ('report', ('assets/0/provenance.bin', 'provenance', 'application/octet-stream'))])
def test_c_a_kept_original_states_its_suffix_s_type(tmp_path, name, kept):
    assert rows(cited(tmp_path / 'b', [kept_as(name)]))[-1] == kept


def test_c_an_original_with_an_unlisted_suffix_is_bytes_and_a_csv_is_csv(tmp_path):
    geopackage = reprofiled('feature-set', 'ogc-geopackage/1', 'application/geopackage+sqlite3')
    opened = cited(tmp_path / 'b', [item(geopackage), item(typed_read('tops'))])
    assert rows(opened, 0)[0] == ('assets/0/original.gpkg', 'original', 'application/octet-stream')
    assert rows(opened, 1)[0] == ('assets/1/original.csv', 'original', 'text/csv')


def test_c_a_well_log_and_a_grid_are_a_dataset_bundle(tmp_path):
    opened = cited(tmp_path / 'b', [las_item(), item(typed_read('grid'))])
    assert rows(opened, 1)[0] == ('assets/1/original.asc', 'original', 'text/plain')
    assert load(tmp_path / 'b/datacite.json')['types'] == {'resourceTypeGeneral': 'Dataset', 'resourceType': 'Dataset bundle'}
    # a well-log-only bundle is a 'Well log bundle': X-2's datacite.json equals the fixture's


# ---- d. a failing write leaves nothing ------------------------------------------------------------------------------

def leftovers(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir())


def test_d_documents_raising_leaves_no_destination_and_no_staging(tmp_path, monkeypatch):
    def broken(*args): raise RuntimeError('documents failed')
    monkeypatch.setattr(CONTRACT, 'documents', broken)
    with pytest.raises(RuntimeError, match='documents failed'): cited(tmp_path / 'b', [las_item()])
    assert leftovers(tmp_path) == []


def test_d_a_forged_descriptor_fails_the_self_check_and_leaves_nothing(tmp_path, monkeypatch):
    real = CONTRACT.documents
    def forged(*args):
        documents = real(*args); documents['croissant.json']['license'] = 'https://spdx.org/licenses/CC0-1.0'
        return documents
    monkeypatch.setattr(CONTRACT, 'documents', forged)
    with pytest.raises(DescriptorRefused) as refused: cited(tmp_path / 'b', [las_item()])
    assert (refused.value.code, refused.value.file) == ('descriptor-disagrees', 'croissant.json')
    assert leftovers(tmp_path) == []


# ---- e. open_bundle on a written bundle -----------------------------------------------------------------------------

def test_e_a_tampered_licence_is_refused_as_disagreeing(tmp_path):
    cited(tmp_path / 'b', [las_item()])
    doc = load(tmp_path / 'b/croissant.json'); doc['license'] = 'https://spdx.org/licenses/CC0-1.0'
    (tmp_path / 'b/croissant.json').write_bytes(CONTRACT.serialize(doc))
    with pytest.raises(DescriptorRefused) as refused: open_bundle(tmp_path / 'b')
    assert (refused.value.code, refused.value.file) == ('descriptor-disagrees', 'croissant.json')


def test_e_a_removed_descriptor_is_refused_as_missing(tmp_path):
    cited(tmp_path / 'b', [las_item()])
    (tmp_path / 'b/datacite.json').unlink()
    with pytest.raises(DescriptorRefused) as refused: open_bundle(tmp_path / 'b')
    assert (refused.value.code, refused.value.file) == ('file-missing', 'datacite.json')
