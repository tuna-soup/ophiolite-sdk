"""E56: map features read in Python (`FeatureSet`), carried by bundle 2.7, and `declare` answering a file by its path.
The feature-set fixture is the contract's synthetic one (two field outlines, the second without geometry)."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from ophiolite import _core, bundle
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.typed import FeatureSet
from ophiolite.upload_runs import File, Folder, checked_declarations, declared_for
from test_bundle import FIXTURES, typed_items, typed_read


def item(r):
    return {'asset_id': r._wire_descriptor['asset_id'], 'revision': r._wire_descriptor['revision'], 'curves': None}, r


def test_the_fixture_reads_to_two_features_with_their_literal_values():
    features = typed_read('feature-set')
    assert isinstance(features, FeatureSet) and len(features) == 2 and repr(features) == '<FeatureSet 2 features, Polygon, EPSG:23031>'
    assert features.features[0]['geometry']['coordinates'][0][:2] == [[547895.5, 5818925.0], [554184.5, 5818925.0]] and features.features[1]['geometry'] is None
    assert features.features[0]['properties'] == {'FIELD_CODE': 'HORIZON', 'FIELD_NAME': 'Horizon', 'WELLS': 3}
    assert features.fields == [{'name': 'FIELD_CODE', 'source_name': 'FIELD_CODE', 'kind': 'text'}, {'name': 'FIELD_NAME', 'source_name': 'FIELD_NAME', 'kind': 'text'},
                               {'name': 'WELLS', 'source_name': 'WELLS', 'kind': 'integer'}]


def test_to_frame_has_one_row_per_feature_and_the_fields_in_file_order():
    pytest.importorskip('pandas')
    frame = typed_read('feature-set').to_frame()
    assert list(frame.columns) == ['index', 'geometry_type', 'FIELD_CODE', 'FIELD_NAME', 'WELLS']
    assert frame['geometry_type'].tolist()[0] == 'Polygon' and frame['geometry_type'].isna().tolist() == [False, True]
    assert str(frame['WELLS'].dtype) == 'Int64' and frame.attrs['source_names']['WELLS'] == 'WELLS'


def load():
    return (json.loads(FIXTURES.joinpath('feature-set.json').read_bytes()), json.loads(FIXTURES.joinpath('feature-set-data.json').read_bytes()),
            FIXTURES.joinpath('feature-set.original').read_bytes())


def digest(descriptor, data):
    """The served bytes of an edited payload, its digest written into the descriptor, as a tampering server would."""
    import hashlib
    raw = json.dumps(data).encode()
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized')
    rep.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    return raw


@pytest.mark.parametrize('edit, message', [
    (lambda d: d['features'].pop(), 'Features and their context disagree'),
    (lambda d: d['features'][0]['properties'].update(OPERATOR='NAM'), 'a property its context does not list'),
    (lambda d: d['features'][0]['properties'].update(WELLS='3'), 'not of its field kind'),
    (lambda d: d['features'][1].update(index=2), 'indexed in file order from 0'),
    (lambda d: d['context']['fields'].append(dict(d['context']['fields'][0])), 'Field names repeat'),
])
def test_semantic_corruption_with_recomputed_digests_is_refused_offline(edit, message):
    descriptor, data, original = load()
    edit(data)
    with pytest.raises(VerificationFailed, match=message): _core.typed_result(descriptor, digest(descriptor, data), original)


def test_a_shapefile_descriptor_needs_its_package_and_no_recipe_pin():
    descriptor, data, original = load()
    packaged = copy.deepcopy(descriptor); packaged['profile'] = 'esri-shapefile/1'
    with pytest.raises(VerificationFailed): _core.typed_result(packaged, digest(packaged, data), original)


def test_bundle_two_seven_carries_a_feature_set_and_the_released_reader_refuses_it(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', typed_items() + [item(typed_read('feature-set'))])
    assert opened.manifest['bundle_version'] == '2.7.0' and opened.assets[-1].type == 'feature-set'
    layer = opened.assets[-1]
    assert layer.original == FIXTURES.joinpath('feature-set.original').read_bytes() and layer.data.features[0]['properties']['FIELD_CODE'] == 'HORIZON'
    assert [f['path'] for f in layer.entry['files']][0].endswith('original.geojson')
    [step] = [s for s in bundle.import_plan(opened, {}) if s['type'] == 'feature-set']
    assert (step['state'], step['profile'], step['declared']) == ('ready', 'geojson/1', {'crs': 'EPSG:23031'})
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_26', Path(__file__).parent / 'frozen/bundle_2_6.py')
    frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    with pytest.raises(VerificationFailed, match='An asset has an unknown type.'): frozen.open_bundle(opened.path)
    assert bundle.write_bundle(tmp_path / 'old', typed_items()).manifest['bundle_version'] == '2.0.0'  # the minor rises only for the new type


def test_a_shapefile_read_feature_set_is_not_exported(tmp_path):
    r = typed_read('feature-set')
    r._wire_descriptor = {**r._wire_descriptor, 'package': {'recipe': None, 'members': []}}
    with pytest.raises(Refused, match='a Shapefile-read feature set carries its companion files'):
        bundle.write_bundle(tmp_path / 'b', typed_items() + [item(r)])


def files(*paths):
    return [File(p, 1, '0' * 64, None) for p in paths]


def test_a_path_names_one_file_and_wins_over_its_kind_field_by_field():
    folder = Folder('maps', files('maps/a.gpkg', 'maps/b.gpkg', 'other/b.gpkg'))
    declare = {'ogc-geopackage/1': {'crs': 'EPSG:23031', 'layer': 'one'}, 'a.gpkg': {'ogc-geopackage/1': {'layer': 'two'}}}
    checked_declarations(declare, folder)
    a = {'path': 'maps/a.gpkg', 'profile': 'ogc-geopackage/1'}
    assert declared_for(declare, folder.files, a) == {'crs': 'EPSG:23031', 'layer': 'two'}
    assert declared_for(declare, folder.files, {'path': 'maps/b.gpkg', 'profile': 'ogc-geopackage/1'}) == {'crs': 'EPSG:23031', 'layer': 'one'}
    assert declared_for({'a.gpkg': {'ogc-geopackage/1': {'layer': 'two'}}}, folder.files, {'path': 'maps/b.gpkg', 'profile': 'ogc-geopackage/1'}) is None
    with pytest.raises(Refused, match='No file of this upload is named b.gpkg'):  # two files have that name: the path is needed
        checked_declarations({'b.gpkg': {'ogc-geopackage/1': {'layer': 'x'}}}, folder)
    checked_declarations({'maps/b.gpkg': {'ogc-geopackage/1': {'layer': 'x'}}}, folder)
    with pytest.raises(Refused, match='do not take corners'):
        checked_declarations({'a.gpkg': {'ogc-geopackage/1': {'corners': 'centres'}}}, folder)
