"""E213 s1 C1 (M5): a GOCAD TSurf landed as a triangulated surface is exported with Client.export, opened offline and
imported again; the bundle carries `original.ts` byte for byte and the re-uploaded original lands the same vertices,
triangles and interpretation as the asset it was exported from.

The bytes are the Connectors' synthetic fixture (`tests/fixtures/gocad/tsurf_full.ts`), written here as literals so the
SDK lane reads no other component's file. Every oracle is written by hand."""
import hashlib
import os

import pytest
try:
    from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite.bundle import open_bundle

PROFILE = 'gocad-ascii/1'
LINES = ['GOCAD TSurf 1', 'HEADER {', 'name:synthetic_top', 'mesh:on', '}', 'GOCAD_ORIGINAL_COORDINATE_SYSTEM', 'NAME "EPSG:32616 synthetic"',
         'AXIS_NAME "X" "Y" "Z"', 'AXIS_UNIT "m" "m" "m"', 'ZPOSITIVE Elevation', 'END_ORIGINAL_COORDINATE_SYSTEM', 'PROPERTIES porosity',
         'NO_DATA_VALUES -99999', 'ESIZES 1', 'TFACE', 'PVRTX 3 1000.5 2000.25 -1500.0 0.21', 'PVRTX 1 1010.5 2003.75 -1502.5 -99999',
         'PVRTX 2 1003.0 2011.5 -1498.0 0.18', 'TRGL 3 1 2', 'TFACE', 'PVRTX 5 1013.0 2015.0 -1503.25 0.25', 'PATOM 6 1 0.3', 'TRGL 2 6 5',
         'TRGL 3 2 5', 'END']
RAW = ('\n'.join(LINES) + '\n').encode()
VERTICES = [[1000.5, 2000.25, -1500.0], [1010.5, 2003.75, -1502.5], [1003.0, 2011.5, -1498.0], [1013.0, 2015.0, -1503.25],
            [1010.5, 2003.75, -1502.5]]
DECLARED = {'z_meaning': 'elevation'}


def test_the_literals_are_the_connectors_fixture():
    assert (hashlib.sha256(RAW).hexdigest(), len(RAW)) == ('71881e7c1a600c30ba1fd22df61cedb8405cc7af79544ec4d000388aaad7f24b', 467)


def test_a_tsurf_exports_opens_and_imports_again_as_it_was(web, tmp_path):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    surface = alice.upload_data(RAW, profile=PROFILE, name='Top', attribution='Synthetic', audience=['bob'], rights_confirmed=True,
                                declared=DECLARED, command_id='gocad-top')
    alice._post('las-uploads', 'share', {'asset_id': surface.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    bundle = bob.export([(surface.asset_id, surface.revision, None)], tmp_path / 'bundle')
    assert (bundle.path / 'assets/0/original.ts').read_bytes() == RAW
    [opened] = open_bundle(bundle.path).assets
    assert (opened.type, opened.original) == ('triangulated-surface', RAW)
    assert opened.data.vertices == VERTICES and opened.data.triangles == [[0, 1, 2], [2, 4, 3], [0, 2, 3]]
    [result] = bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert (result['type'], result['state']) == ('triangulated-surface', 'imported')
    destination = result['destination']
    assert destination['revision'] == hashlib.sha256(RAW).hexdigest() == surface.revision
    again, first = bob.read_data(destination['asset_id'], destination['revision']), bob.read_data(surface.asset_id, surface.revision)
    assert {**again.data, 'source': None} == {**first.data, 'source': None} and again._wire_descriptor['interpretation'] == first._wire_descriptor['interpretation']
    assert {k: again.context[k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive')} == {
        'crs': 'EPSG:32616', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up'}
