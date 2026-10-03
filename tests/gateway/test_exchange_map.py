"""E70a C4: `get` receives a scalar map through the existing export route (maps/export) with an access key: a
GeoTIFF generated from the stored map, checked for project, asset, revision and representation before any digest.
The map is a real import (Maps.import_map, as test_snapshot_storage_independence.py does) into a gateway that has
maps configured; keys are made by a browser session of that gateway (test_access_key_chain.keyed resolves them)."""
import base64
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from ophiolite import Client, Credential
from ophiolite import exchange

np = pytest.importorskip('numpy'); rasterio = pytest.importorskip('rasterio')


@pytest.fixture
def mapped(keyed, service, tmp_path):
    from starlette.testclient import TestClient
    from rasterio.transform import from_origin
    from project_gateway.app import create_app
    from project_gateway.maps import Maps
    from project_gateway.models import Import
    from project_gateway.tests.test_identity import identity
    from scalar_maps.gateway_maps import MapAdapters
    web = keyed
    maps = Maps(web.a.sources.platform, web.a.journal, None, lambda scene: scene, MapAdapters())
    application = create_app(web.a.sources.platform, ORIGIN, maps=maps, organizations=service, identity=identity(service), sources=web.a.sources)
    path = tmp_path / 'surface.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1, dtype='float64', crs='EPSG:32631',
                       transform=from_origin(500000, 5800000, 25, 25), nodata=-9999) as ds:
        ds.write(np.array([[1., 2.], [-9999., 4.]]), 1)
    with TestClient(application, base_url=ORIGIN) as c:
        gateway = SimpleNamespace(app=application, c=c, maps=maps)
        imported = maps.import_map(Import(project_id='p', command_id=str(uuid.uuid4()), name='Top Chalk', unit='m',
                                          geotiff=base64.b64encode(path.read_bytes()).decode()), 'alice')
        yield gateway, imported['asset']['asset_id']


def key(gateway, person, scope):
    token, csrf = gateway.app.state.sessions.create(person, None, person)
    gateway.c.cookies.set('ab_session', token)
    made = gateway.c.post('/api/v1/access-keys/create', json={'project_id': 'p', 'label': 'Map ' + scope, 'scope': scope, 'days': 30},
                          headers={'X-CSRF-Token': csrf, 'Origin': ORIGIN})
    assert made.status_code == 200, made.text
    gateway.app.state.sessions.remove(token); gateway.c.cookies.clear()
    return Client(ORIGIN, 'p', Credential.bearer(made.json()['key']), gateway.c)


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    return caught.value


def test_a_read_key_and_a_write_key_both_receive_the_exact_map(mapped, tmp_path):
    gateway, asset = mapped
    for scope in ('read', 'write'):  # first: the premise of Verdict 4 (a key, not a session, may export)
        ex = key(gateway, 'alice', scope).exchange(tmp_path / ('w-' + scope)); out = tmp_path / ('map-' + scope)
        got = ex.get(asset, output=out)
        assert (got.outcome, got.sentence) == ('got', 'Got Top Chalk, version 1. You now hold it; saved in %s. It is a GeoTIFF generated from the stored map, '
                                                      'not the file that was imported.' % out)
        manifest = json.loads((out / 'manifest.json').read_text())
        assert hashlib.sha256((out / 'map.tif').read_bytes()).hexdigest() == manifest['files']['map.tif']
        assert hashlib.sha256((out / 'source.txt').read_bytes()).hexdigest() == manifest['files']['source.txt']
        with rasterio.open(out / 'map.tif') as ds: first_row = ds.read(1)[0].tolist()
        assert first_row == [1.0, 2.0]
        assert ex.held()[asset]['number'] == 1 and ex.get(asset, output=out).outcome == 'already-latest'


def tampered(monkeypatch, client, change):
    original = client._post_bytes
    def post(area, operation, raw, **options):
        reply = original(area, operation, raw, **options)
        return change(reply, original) if (area, operation) == ('maps', 'export') else reply
    monkeypatch.setattr(client, '_post_bytes', post)


def altered_raster(reply, original):
    raw = bytearray(base64.b64decode(reply['raster'])); raw[-1] ^= 0xFF
    return {**reply, 'raster': base64.b64encode(bytes(raw)).decode()}  # valid base64, other bytes


@pytest.mark.parametrize('change', [
    pytest.param(lambda r, o: {**r, 'asset': 'other', 'reference': {**r['reference'], 'asset_id': 'other'}}, id='another-asset'),
    pytest.param(lambda r, o: {**r, 'reference': {**r['reference'], 'project_id': 'q'}}, id='another-project'),
    pytest.param(lambda r, o: {**r, 'revision': '2', 'reference': {**r['reference'], 'revision': '2'}}, id='wrong-revision-matching-raster'),
    pytest.param(lambda r, o: {**r, 'representation': 'derived'}, id='another-representation'),
    pytest.param(lambda r, o: {**r, 'source_text': r['source_text'] + ' '}, id='changed-source'),
    pytest.param(altered_raster, id='altered-bytes-valid-base64'),
    pytest.param(lambda r, o: {**r, 'raster': r['raster'][:-3] + '!!!'}, id='malformed-base64')])
def test_a_substituted_or_altered_map_is_damaged_and_nothing_is_kept(mapped, tmp_path, monkeypatch, change):
    gateway, asset = mapped
    client = key(gateway, 'alice', 'read')
    tampered(monkeypatch, client, change)
    ex = client.exchange(tmp_path / 'w')
    caught = refused('damaged', lambda: ex.get(asset, output=tmp_path / 'map'))
    assert caught.sentence == 'The data did not match its fingerprint. Nothing was kept.'
    assert not (tmp_path / 'map').exists() and ex.held() == {}


def test_an_archived_map_is_unavailable_and_a_restored_one_is_listed_with_its_number(mapped, tmp_path):
    from project_gateway import lifecycle
    gateway, asset = mapped
    ex = key(gateway, 'alice', 'read').exchange(tmp_path / 'w')
    ex.check(); ex.get(asset, output=tmp_path / 'map')
    ref = {'project_id': 'p', 'asset_id': asset, 'revision': '1'}
    lifecycle.change(gateway.maps, {'reference': ref, 'action': 'archive', 'command_id': str(uuid.uuid4())}, 'alice')
    unavailable = refused('map-unavailable', lambda: ex.get(asset, output=tmp_path / 'map'))
    assert unavailable.sentence == 'That version of the map is not available (it may be withdrawn or not the one you hold).'
    assert ex.held()[asset]['number'] == 1 and (tmp_path / 'map/map.tif').exists()
    lifecycle.change(gateway.maps, {'reference': {**ref, 'revision': '2'}, 'action': 'restore', 'restore_revision': '1', 'command_id': str(uuid.uuid4())}, 'alice')
    checked = ex.check()
    assert (checked.outcome, checked.sentence) == ('updates', '1 newer: Top Chalk, version 3.')  # no who or when for a map
    assert ex.get(asset, output=tmp_path / 'map').sentence.startswith('Got Top Chalk, version 3.')
