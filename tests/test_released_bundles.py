"""E148 s2 C3 (charter acceptance 3): this SDK reads a frozen bundle at every version its writer emits.

`RELEASED_BUNDLES` is written by hand: one row per bundle version, naming every file of its frozen directory with its
sha256, the frozen writer that wrote it, and literal facts the read yields, among them the feature that made its minor
with one decoded value. It is never derived from the fixture directory. `test_the_bundle_list_is_every_version_the_
writer_emits` compares it with the versions `ophiolite/bundle.py` can reach, so a new minor must bring a row and a
frozen bundle. Each directory was written once by the oldest frozen released writer that emits its version and is never
regenerated: `fixtures/released-bundles/README.md` says how (strategy E148-s2-released-profiles-COMMIT-STRATEGY.md, D1,
D4, R2, R3, R12, R13). Everything there is synthetic."""
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.bundle import open_bundle

RELEASED_DIR = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles'
LAS = {'assets/0/curve-GR.json': '81992992a1a15daac792bebf5979c51e0f8c3c1869a75a125999e6466e38bfba',
       'assets/0/descriptor-GR.json': '7bb6af90ffb90a754b3985f1679eaa16f2a32efa384aef028c6b5d0d0719145d',
       'assets/0/original.las': 'd899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b'}
TOPS = {'assets/0/data.json': 'eae5778eca7ced6e1010cbe7ef342efb23298da1de5a634e9a4c9f3bb70e305b',
        'assets/0/descriptor.json': '2dd7494de3d35cba7f7194759daefea7ad5692e618d0d93e4173f56b5e0917c1',
        'assets/0/original.csv': '7bca6c523913b58113d3fa23aa97424ce907af3b27915c18ada91b845b71a594'}
FIRST_TOP = {'name': 'Top Chalk', 'md': 100.5, 'tvd': None, 'source': 'picked'}
FIRST_STICK = {'index': 3, 'points': [{'x': 500100.5, 'y': 5800200.25, 'z': 1200.0}, {'x': 500110.0, 'y': 5800210.0, 'z': 1350.0}]}
KEPT = 'b8fbf98bcd8695cec9128f1943bc365379bd5e3f5a00bf162abeaf344f4c2da4'
# E182 s2b: the 1.18 / 2.18 descriptor and manifest digests are pinned in a file beside the bundles (no new literal in
# code); their other files are the LAS and tops files above, byte for byte.
SENDER_DIGESTS = json.loads((RELEASED_DIR / 'sender-digests.json').read_text())
STATED_DIGESTS = json.loads((RELEASED_DIR / 'stated-digests.json').read_text())  # E192 s1: 1.19 / 2.19, as for 1.18 / 2.18
LAS_DATA = {name: digest for name, digest in LAS.items() if 'descriptor' not in name}
TOPS_DATA = {name: digest for name, digest in TOPS.items() if 'descriptor' not in name}

# version -> (frozen writer, {file: sha256}, bundle_version, asset count, first asset type, feature key, decoded value)
RELEASED_BUNDLES = {
    '1.0': ('bundle_1_0', {**LAS, 'manifest.json': '2ee1ccdaa7bf473830a19d21b25c5a217090ee867679317d26fd6f1e75c69864'},
            '1.0.0', 1, 'well-log', 'curve GR', [0.0, 10.0, None, 30.0, 40.0]),
    '1.1': ('bundle_2_1', {**LAS, 'manifest.json': '495fd1d8dcb49077b4b71ba4b98b5953df5dd2f9949c5e76c58b25d1870d5976'},
            '1.1.0', 1, 'well-log', 'observation group', ('Synthetic group', [0])),
    '1.10': ('bundle_2_10', {**LAS, 'manifest.json': '095fac24ebff7575070f4ed67e7bd57de845f85c55b961ead788066ef78cff50'},
             '1.10.0', 1, 'well-log', 'source record', ('upload', 'wells/tops.csv')),
    '2.0': ('bundle_2_1', {**TOPS, 'manifest.json': '6429ba2a0ab4ddde90f3cf0610d1a1f9d5ddca4c2a63c99239a8a48a4504ecc2'},
            '2.0.0', 1, 'well-tops', 'first top', FIRST_TOP),
    '2.1': ('bundle_2_1', {**TOPS, 'manifest.json': 'b705374f59f38053f4211a0ced394da7448ba8e0c02e92b263a9ffb02a9e0da4'},
            '2.1.0', 1, 'well-tops', 'observation group', ('Synthetic group', [0])),
    '2.2': ('bundle_2_2', {'assets/0/data.json': '90acd93fb33b361e86d6d35a00fe54656f5e7efafe2f4c9acdff547f340b04ee',
                           'assets/0/descriptor.json': '5c4d540d62d4216dfa351e5db991a574ff9c0672887b9a23b5aff096e7a02c5f',
                           'assets/0/original.csv': '9f0095c2dfdc7fd26ad36f47c5c924bd6ea091848557168c9e6a31d0b50f753b',
                           'manifest.json': '68856aeba568b30ebfa7914e44dea933f4feb269f38625c03e3549c76a590077'},
            '2.2.0', 1, 'point-set', 'first point', [1.0, 2.0, 3.0]),
    '2.3': ('bundle_2_4', {'assets/0/data.json': '94ed84297e96cda60ea2481898e50946b81e93d9a45c7ef259574e244cb28da2',
                           'assets/0/descriptor.json': 'b9948460670bfa22ebab3bf928bea0d7950b77366787c3bdc257176512954271',
                           'assets/0/original.txt': '937325c602a1a388ac2320f09e539a6b8d180d24ee12c29bd021c617543d9a04',
                           'manifest.json': '9f2ac44ef973a325e6808c9a562bc044b266623ec212e78b204f37227c230101'},
            '2.3.0', 1, 'polyline-set', 'first stick', FIRST_STICK),
    '2.4': ('bundle_2_4', {**TOPS, 'manifest.json': '236d13ebf3db4212f268fb1b41e8ae3f5ec3c87bb6150ac27762698a002e43ca'},
            '2.4.0', 1, 'well-tops', 'entities', ([('well-1', 'well', 'Synthetic W'), ('wellbore-1', 'wellbore', 'W-1 main')], 2, ['synthetic-tops'])),
    '2.5': ('bundle_2_5', {'assets/0/data.json': '675f4ed50f7c0ab849b2a4eadd297069d52c420e330e2ac9fed924d3abeb2134',
                           'assets/0/descriptor.json': '25372636160b51211e78550893815620a0214edf4ed3f3ca63da8deca17ec0f3',
                           'assets/0/original.txt': 'a3b2d7369010aa033155be3335b85382312cc498b5859ebd74289824d2eacb65',
                           'manifest.json': '21fe042d608f04916d978dda534ab50f73c8b157d280feb2ab573cbd4b79499b'},
            '2.5.0', 1, 'wavelet', 'first sample', (-0.004, -0.25)),
    '2.6': ('bundle_2_6', {'assets/0/data.json': '979d58a4364d3e6d976bb725ec179c50496ee74c4be94cbd7b3a1cc097bd9564',
                           'assets/0/descriptor.json': '72a6340977c22d20c80687db26ca9578b30a306f85cb3caaee7408e196bf01bb',
                           'assets/0/original.csv': 'a30abdd45ee6439775469cb92e020fe6a1731003959f44c7c0fbef3cfcc6583b',
                           'manifest.json': 'f600267e8fc9bc237ce732e774d98ae271c1418d477cd98af66db4bf903e167f'},
            '2.6.0', 1, 'time-depth', 'first pair', (0.0, 0.0, 0.0)),
    '2.7': ('bundle_2_7', {'assets/0/data.json': '33b2e0914114c2cf29ce40e875c51047279e0531f56e97dd85249e9b91fa4a15',
                           'assets/0/descriptor.json': '3fa57e06cc9d48f315b25a79ad5fdedcbe7a78ee17ec16b5f3f8e571b0122c43',
                           'assets/0/original.geojson': '26c66c9fa30d2077262e218ee9108f84264bdaf0846a75443b601b5ec5974bcc',
                           'manifest.json': 'fa7af9557b8764109a0ebda79165c35ee87691a6075f60503e54394659015c0b'},
            '2.7.0', 1, 'feature-set', 'first feature', ('Polygon', {'FIELD_CODE': 'HORIZON', 'FIELD_NAME': 'Horizon', 'WELLS': 3})),
    '2.8': ('bundle_2_8', {'assets/0/companion-1.bin': '6489d726f942856ef6da89b2167abe7f45868e25a6fcdd2281caa0453dcbbf8f',
                           'assets/0/companion-2.bin': 'ceda4ac1bdf098795e4480b1cd42c7fe0abe660b08129046e4fac0fa9089e42d',
                           'assets/0/companion-3.bin': '7c62dd78ea12b12595071c45e68f3ba278c61005e5b6cd1f84ea21202c22e12a',
                           'assets/0/data.json': 'efc4834a6e305e9bf7804086551fa98fa3eb1f3b778b47e928282892f8cfd44d',
                           'assets/0/descriptor.json': '9000d09de08828a60dac1c6283538209691c9da8ba047669aa55d4ee8b68d04a',
                           'assets/0/interpretation.json': '2ae6604cdcebf1690d6e9f187d9b02c582dd2b89fe219b2bc4dc12313f47f70a',
                           'assets/0/original.shp': '26c66c9fa30d2077262e218ee9108f84264bdaf0846a75443b601b5ec5974bcc',
                           'assets/0/package.json': 'aad9877ac65ffb9de30e3de43113a9dc9fd970e5a3004a02cf260d456fcf71dc',
                           'manifest.json': 'e00895328edb1fe83fecb6f147cacc9ffb42fab39909831c1bce3348ba511357'},
            '2.8.0', 1, 'feature-set', 'package members',
            [('fields.dbf', 'companion'), ('fields.prj', 'crs-metadata'), ('fields.shp', 'primary'), ('fields.shx', 'companion')]),
    '2.9': ('bundle_2_9', {'assets/0/curve-GR.json': '81992992a1a15daac792bebf5979c51e0f8c3c1869a75a125999e6466e38bfba',
                           'assets/0/descriptor-GR.json': 'af3fa23d800626c19c2c343c1ab2b9adb1e6fb54a0dc6a9ba44a1de188578741',
                           'assets/0/original.las': 'd899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b',
                           'assets/0/provenance.txt': KEPT,
                           'manifest.json': '68cdc8a445fd19997d52eb7d7d2aa33026cc5a245800f83ce91108c6644c5fb6'},
            '2.9.0', 1, 'well-log', 'kept original', (KEPT, KEPT, 'Synthetic report reader')),
    '2.10': ('bundle_2_10', {**TOPS, 'manifest.json': '113f315af7c70e3a46ae4a574adcf3b35faf87bbe79df51ff5d287fb27c45c9c'},
             '2.10.0', 1, 'well-tops', 'source record', ('upload', 'wells/tops.csv')),
    '2.11': ('ophiolite/bundle.py', {'assets/0/companion-1.bin': '44c92e0137e916f4aa7485687d092820fdd0eaabffff11581f4b66a0c0eb78a3',
                                     'assets/0/data.json': '1cb42e2ea8f9e7b3364c3dbaaf336913756c5c38fc7445759035e4cd60e96dfc',
                                     'assets/0/descriptor.json': '58ccb8d40cbde35b038eca3fdfa4d4a495d059e3c6919b0aeac9eb907fde91ed',
                                     'assets/0/interpretation.json': '102608bf8aa28bcf06fcd5524d8d28d6c7dcfc27e555553545f2bfe360187b7a',
                                     'assets/0/original.txt': '937325c602a1a388ac2320f09e539a6b8d180d24ee12c29bd021c617543d9a04',
                                     'assets/0/package.json': '7cfd17a391395c4631e69d2ba74eaa222ca5dc1bb3936ce68c92ba001bbf5baa',
                                     'manifest.json': 'e2bb2a93bd0639f20b6989b3ff37966477f35e3964c367959420f8e2dffb0aee'},
             '2.11.0', 1, 'polyline-set', 'packaged sticks', ([('faults.crs', 'crs-metadata'), ('faults.txt', 'primary')], FIRST_STICK)),
    '2.17': ('ophiolite/bundle.py', {'assets/0/descriptor.json': '145edcb478b6dafe5c2f71dffa2ada87182d6379e89708ca51bd2ed074fc45ba',
                                     'assets/0/original.json': '283412683d43b035e2ecb23168ea2194c935269f73bb32fde965f6852cee06a9',
                                     'manifest.json': '385271f36760039adbbe212299d8aee47b95a351bb81cf0ece653062821f754a'},
             '2.17.0', 1, 'well-table', 'wells table', (['S-1', 'S-2'], ['id', 'name', 'x', 'y'])),
    '1.18': ('ophiolite/bundle.py', {**LAS_DATA, **SENDER_DIGESTS['1.18']}, '1.18.0', 1, 'well-log', 'sender', ('reported', 'qgis-plugin', 'qgis')),
    '2.18': ('ophiolite/bundle.py', {**TOPS_DATA, **SENDER_DIGESTS['2.18']}, '2.18.0', 1, 'well-tops', 'sender', ('not reported', None, None)),
    '1.19': ('ophiolite/bundle.py', {**LAS_DATA, **STATED_DIGESTS['1.19']}, '1.19.0', 1, 'well-log', 'stated parents', [('synthetic-design', 'r-design-1')]),
    '2.19': ('ophiolite/bundle.py', {**TOPS_DATA, **STATED_DIGESTS['2.19']}, '2.19.0', 1, 'well-tops', 'stated parents',
             [('synthetic-design', 'r-design-1'), ('synthetic-model', 'r-model-2')]),
}


def _members(opened):
    return sorted((m['name'], m['role']) for m in opened.assets[0].package.members)


FEATURES = {  # feature key -> the one read of the opened bundle that yields its decoded value
    'curve GR': lambda b: list(b.assets[0].curves['GR'].values),
    'observation group': lambda b: (b.groups[0]['name'], b.groups[0]['members']),
    'source record': lambda b: (b.assets[0].source_record['identity']['source_system'], b.assets[0].source_record['identity']['source_object_id']['path']),
    'first top': lambda b: b.assets[0].data.tops[0],
    'first point': lambda b: list(b.assets[0].data.points[0]),
    'first stick': lambda b: b.assets[0].data.sticks[0],
    'entities': lambda b: ([(e.entity_id, e.kind, e.name) for e in b.entities], len(b.relationships),
                           [a.asset_id for a in b.assets_of(b.entity('wellbore-1'))]),
    'first sample': lambda b: (b.assets[0].data.times[0], b.assets[0].data.samples[0]),
    'first pair': lambda b: tuple(b.assets[0].data.pairs[0]),
    'first feature': lambda b: (b.assets[0].data.features[0]['geometry']['type'], b.assets[0].data.features[0]['properties']),
    'package members': _members,
    'kept original': lambda b: (hashlib.sha256(b.assets[0].provenance).hexdigest(), b.assets[0].read_by['kept'], b.assets[0].read_by['label']),
    'packaged sticks': lambda b: (_members(b), b.assets[0].data.sticks[0]),
    'wells table': lambda b: ([w['well_id'] for w in b.assets[0].data.wells], [c['name'] for c in b.assets[0].data.source_schema]),
    'sender': lambda b: (b.assets[0].sender['state'], (b.assets[0].sender['client'] or {}).get('product'), (b.assets[0].sender['host'] or {}).get('name')),
    'stated parents': lambda b: [(p['key'], p['revision']) for p in b.assets[0].stated_parents],
}


@pytest.mark.parametrize('version', list(RELEASED_BUNDLES))
def test_each_released_bundle_is_read_by_this_sdk(version):
    writer, files, bundle_version, count, first_type, feature, value = RELEASED_BUNDLES[version]
    root = RELEASED_DIR / version
    assert root.is_dir(), 'the frozen bundle %s is missing' % version
    present = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    assert present == sorted(files)
    for name, digest in files.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    opened = open_bundle(root)
    assert opened.manifest['bundle_version'] == bundle_version and opened.unlisted == []
    assert len(opened.assets) == count and opened.assets[0].type == first_type
    assert FEATURES[feature](opened) == value


def test_the_fixture_directory_holds_exactly_the_listed_versions():
    assert sorted(p.name for p in RELEASED_DIR.iterdir() if p.is_dir()) == sorted(RELEASED_BUNDLES)


def reachable_versions():
    """The versions write_bundle can emit, from its constants and its major rule (E8). The minor is the largest of the
    content's minors (bundle.py write_bundle: observations 1, a graph 4, NEWER_TYPES, NEWER_PROFILES, a package, a kept
    original, a source record, a sender), so each one is reachable alone. Major 2 is forced by typed assets, a graph or a
    kept original; a curve-only export stays major 1 and reaches only the minors that need none of those."""
    source = inspect.getsource(bundle.write_bundle)
    assert "or bool(graph)  # entities need 2.4" in source  # the major rule this computation restates
    assert "typed_bundle or any(getattr(read, 'provenance', None) is not None" in source
    assert "minor = max([1 if observations else 0, 4 if graph else 0]" in source
    two = ({0, 1, 4} | set(bundle.NEWER_TYPES.values()) | set(bundle.NEWER_PROFILES.values())
           | {bundle.PACKAGE_MINOR, bundle.PROVENANCE_MINOR, bundle.SOURCE_RECORD_MINOR, bundle.SENDER_MINOR, bundle.STATED_MINOR})
    one = {0, 1, bundle.SOURCE_RECORD_MINOR, bundle.SENDER_MINOR, bundle.STATED_MINOR}  # no typed asset, no graph, no kept original, no package (typed only)
    return {'1.%d' % m for m in one} | {'2.%d' % m for m in two}


def test_the_bundle_list_is_every_version_the_writer_emits():
    assert reachable_versions() == set(RELEASED_BUNDLES)
    assert set(RELEASED_BUNDLES) == {'1.0', '1.1', '1.10', '1.18', '1.19'} | {'2.%d' % m for m in range(12)} | {'2.17', '2.18', '2.19'}  # R2: 15 versions; E162 s2a: 2.17; E182 s2b: 1.18, 2.18; E192 s1: 1.19, 2.19
