"""E123 s1c C3 (D8, round 2 M6): a Petrel scattered-data map, landed as a grid and as points under the one profile, is
exported with Client.export, opened offline and imported again; each re-uploaded original lands the same data and the same
interpretation as the asset it was exported from.

The bytes are the Connectors' synthetic fixture (`tests/fixtures/petrel_scattered/scattered_grid.txt`), written here as
literals so the SDK lane reads no other component's file; the points case is that file with line 24 one millionth off its
node. The licensed excerpt is Integration data and is checked there (conformance, D75). Every oracle is written by hand."""
import hashlib
import os

import pytest
try:
    from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite.bundle import open_bundle

PROFILE = 'petrel-scattered-data/1'
HEADER = ['# Type: scattered data', '# Version: 6', '# Description: No description', '# Format: free', '# Field: 1 x', '# Field: 2 y',
          '# Field: 3 z meters', '# Field: 4 column', '# Field: 5 row', '# Projection: Local Rectangular', '# Units: meters', '# End:',
          '# Information from grid:', '# Grid_size: 4 x 3', '# Grid_space: 1000.000000,1150.000000,2000.000000,2100.000000',
          '# Scattered data: Not_available', '# Z_field: z', '# Vertical_faults: Not_available', '# History: No history', '# Z_units: meters']
ROWS = ['1000.000000 2000.000000 -1201.250000 1 1', '1100.000000 2000.000000 -1203.500000 3 1', '1150.000000 2000.000000 -1204.125000 4 1',
        '1000.000000 2050.000000 -1210.000000 1 2', '1050.000000 2050.000000 -1211.750000 2 2', '1100.000000 2050.000000 -1212.000000 3 2',
        '1150.000000 2050.000000 -1213.375000 4 2', '1000.000000 2100.000000 -1220.500000 1 3', '1050.000000 2100.000000 -1221.000000 2 3',
        '1100.000000 2100.000000 -1222.625000 3 3']
GRID = ('\n'.join(HEADER + ROWS) + '\n').encode()
POINTS = GRID.replace(b'\n1000.000000 2050.000000 ', b'\n1000.000001 2050.000000 ')
VALUES = [-1220.5, -1221.0, -1222.625, None, -1210.0, -1211.75, -1212.0, -1213.375, -1201.25, None, -1203.5, -1204.125]
DECLARED = {'crs': 'EPSG:23031', 'z_meaning': 'depth', 'positive': 'up'}


def test_the_literals_are_the_connectors_fixture():
    assert (hashlib.sha256(GRID).hexdigest(), len(GRID)) == ('74818308a3470c896b3d76abf0d87e51af51fad3a7df864facd511865a9e8d36', 849)


def landed(c, raw, name):
    return c.upload_data(raw, profile=PROFILE, name=name, attribution='Synthetic', audience=['bob'], rights_confirmed=True, declared=DECLARED, command_id=name)


def test_both_landings_export_open_and_import_again_as_they_were(web, tmp_path):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    grid, points = landed(alice, GRID, 'Scattered grid'), landed(alice, POINTS, 'Scattered points')
    for asset in (grid, points): alice._post('las-uploads', 'share', {'asset_id': asset.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    bundle = bob.export([(grid.asset_id, grid.revision, None), (points.asset_id, points.revision, None)], tmp_path / 'bundle')
    assert (bundle.path / 'assets/0/original.txt').read_bytes() == GRID and (bundle.path / 'assets/1/original.txt').read_bytes() == POINTS
    g, p = open_bundle(bundle.path).assets
    assert (g.type, g.original, p.type, p.original) == ('regular-grid-surface', GRID, 'point-set', POINTS)
    assert g.data.values == VALUES and (g.data.context['ncols'], g.data.context['nrows'], g.data.context['missing_count']) == (4, 3, 2)
    assert p.data.points[3] == [1000.000001, 2050.0, -1210.0] and p.data.context['count'] == 10
    assert p.data.context['fidelity']['decisions'][0] == 'Line 24 is not on the grid the header declares, so the file lands as points.'
    results = bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert [(r['type'], r['state']) for r in results] == [('regular-grid-surface', 'imported'), ('point-set', 'imported')]
    for result, before, raw in zip(results, (grid, points), (GRID, POINTS)):
        destination = result['destination']
        assert destination['revision'] == hashlib.sha256(raw).hexdigest()
        again, first = bob.read_data(destination['asset_id'], destination['revision']), bob.read_data(before.asset_id, before.revision)
        assert again.data['source']['key'] == destination['asset_id'] != before.asset_id  # the importer's own asset
        assert {**again.data, 'source': None} == {**first.data, 'source': None} and again._wire_descriptor['interpretation'] == first._wire_descriptor['interpretation']
        assert {k: again.context[k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive')} == {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'up'}
    assert [r['destination']['revision'] for r in results] == [grid.revision, points.revision]
