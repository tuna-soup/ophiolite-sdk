"""E56 C5, in-process gateway lane: the Journey's code route run as written. `client.upload` sends a Shapefile zip (the
browser and the SDK unzip; the gateway stores the `.shp` with its members), a ZMAP+ grid answered by kind, and GeoPackages
answered by path; a question a file asks only once it is read is answered from `declare` and the file sent again (N8).
The files are the committed NLOG crops (Platform `tests/fixtures/e56_grids_gis`, NOTICE)."""
import hashlib
import zipfile

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401
from test_intake_live import keyed_client, requests
from project_gateway.tests.test_package_profiles import F, two_layers
from ophiolite.errors import Refused
from ophiolite.typed import FeatureSet, GridSurface

LOOSE = ('fields.shp', 'fields.shx', 'fields.dbf', 'fields.prj', 'fields.cst')


def folder(tmp_path, monkeypatch):
    """The Journey's working folder: fields.zip as NLOG serves the layer, and the cropped 11-ro grid."""
    with zipfile.ZipFile(tmp_path / 'fields.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in LOOSE: z.writestr(name, (F / name).read_bytes())
    (tmp_path / '11-ro.zmap').write_bytes((F / '11-ro-crop.zmap').read_bytes())
    monkeypatch.chdir(tmp_path)


def test_the_journey_example_lands_the_shapefile_zip_and_the_grid(keyed, tmp_path, monkeypatch):
    folder(tmp_path, monkeypatch)
    client = keyed_client(keyed)
    # the Journey's code route, as the guide writes it (L1: `declare` is keyed by kind); a kind with declared fields is
    # asked before it is read, so the Shapefile's kind is named too: a crs that agrees with its .prj (K4)
    declare = {'esri-shapefile/1': {'crs': 'EPSG:23031'}, 'zmap-plus-grid/1': {'corners': 'centres'}}
    report = client.upload('fields.zip', attribution='NLOG.NL, nlog.nl', rights_confirmed=True, audience=['bob'], declare=declare)
    assert report.ok and sorted((i['path'], i['role'], i['state']) for i in report.items) == [
        ('fields.cst', 'companion', 'added'), ('fields.dbf', 'companion', 'added'), ('fields.prj', 'crs-metadata', 'added'),
        ('fields.shp', 'primary', 'added'), ('fields.shx', 'companion', 'added')]
    shp = next(i for i in report.items if i['role'] == 'primary')
    features = client.read_data(shp['asset_id'], shp['revision'])
    assert isinstance(features, FeatureSet) and len(features) == 5 and features.original == (F / 'fields.shp').read_bytes()
    assert (features.context['crs'], features.context['encoding']) == ('EPSG:23031', 'iso8859-1')
    assert features._wire_descriptor['package']['recipe'] is None and shp['revision'] == hashlib.sha256((F / 'fields.shp').read_bytes()).hexdigest()
    grid = client.upload('11-ro.zmap', attribution='NLOG.NL, nlog.nl', rights_confirmed=True, audience=['bob'], declare=declare)
    item = grid.items[0]
    assert grid.ok and item['state'] == 'added'
    surface = client.read_data(item['asset_id'], item['revision'])
    assert isinstance(surface, GridSurface) and surface.to_numpy().shape == (40, 30)


def test_an_open_file_is_refused_with_a_clear_message(keyed, tmp_path, monkeypatch):
    folder(tmp_path, monkeypatch)
    client = keyed_client(keyed)
    sent = requests(keyed)
    with open('fields.zip', 'rb') as stream, pytest.raises(Refused, match='an open file is not read. Nothing was sent.'):
        client.upload(stream, attribution='NLOG.NL', rights_confirmed=True)
    assert sent == []


def test_a_layer_asked_only_after_the_file_is_read_is_answered_and_sent_again(keyed, tmp_path):
    client = keyed_client(keyed)
    two_layers(tmp_path)  # writes tmp_path/two.gpkg
    sent = requests(keyed)
    first = client.upload(tmp_path / 'two.gpkg', attribution='NLOG.NL', rights_confirmed=True, declare={'ogc-geopackage/1': {}})
    item = first.items[0]
    assert (item['state'], item['reason_code']) == ('needs-decision', 'needs-declarations')
    assert next(a for a in item['asks'] if a['key'] == 'layer')['choices'] == {'gdw_ng_field_utm': 'Fields', 't_two': 'Two fields'}
    assert [s[1]['mode'] for s in sent if s[0] == 'file'] == ['head', 'head', 'body']  # asked at the head, then once read
    del sent[:]
    second = client.upload(tmp_path / 'two.gpkg', attribution='NLOG.NL', rights_confirmed=True, declare={'ogc-geopackage/1': {'layer': 't_two'}})
    assert second.view['run_id'] == first.view['run_id'] and second.ok  # the unfinished upload of the same file, answered
    assert [s[1]['mode'] for s in sent if s[0] == 'file'] == ['head', 'body']
    layer = client.read_data(second.items[0]['asset_id'], second.items[0]['revision'])
    assert sorted(f['properties']['FIELD_CODE'] for f in layer.features) == ['BKL', 'DKK'] and layer.context['layer_title'] == 'Two fields'


def test_two_geopackages_land_each_with_the_layer_its_path_names(keyed, tmp_path):
    client = keyed_client(keyed)
    drop = tmp_path / 'maps'; drop.mkdir()
    (drop / 'a.gpkg').write_bytes(two_layers(tmp_path))
    (tmp_path / 'b').mkdir(); (drop / 'b.gpkg').write_bytes(two_layers(tmp_path / 'b', title='Second copy'))  # other bytes: not the same file
    report = client.upload(drop, attribution='NLOG.NL', rights_confirmed=True,
                           declare={'ogc-geopackage/1': {'crs': 'unknown'}, 'a.gpkg': {'ogc-geopackage/1': {'layer': 'gdw_ng_field_utm'}},
                                    'maps/b.gpkg': {'ogc-geopackage/1': {'layer': 't_two'}}})
    assert report.ok, [(i['path'], i['state'], i['technical']) for i in report.items]
    codes = {i['path']: sorted(f['properties']['FIELD_CODE'] for f in client.read_data(i['asset_id'], i['revision']).features) for i in report.items}
    assert codes == {'maps/a.gpkg': ['BKL', 'DKK', 'HORIZON', 'SEB', 'SPG'], 'maps/b.gpkg': ['BKL', 'DKK']}
    with pytest.raises(Refused, match='No file of this upload is named c.gpkg'):
        client.upload(drop, attribution='NLOG.NL', rights_confirmed=True, declare={'c.gpkg': {'ogc-geopackage/1': {'layer': 't_two'}}})
