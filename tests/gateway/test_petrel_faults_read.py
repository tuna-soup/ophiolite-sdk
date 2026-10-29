"""E123 S1f-a C5 (A-f, A-g): Petrel fault sticks with their CRS file, uploaded as a folder through the in-process gateway, are
read by the SDK at the lane: every stick's index, fault name, stick number and points in file order, the one-point stick
kept. A bundle export of the landed set stops before writing anything until S1f-b.

The bytes are the Connectors' synthetic fixture (`tests/fixtures/petrel_faults/faultsticks.txt`), written here as
literals so the SDK lane reads no other component's file; the CRS file is s1b's synthetic companion. The licensed excerpts
are Integration data and are checked there (conformance, D75). Every oracle is written by hand."""
import hashlib
import os

import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web, shared, app, service  # noqa: F401 (fixtures)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential
from test_bundle_petrel_horizon import CRS

PRIMARY = ''.join('INLINE- %s\n' % row for row in (
    '100 200 1000.0 5000.0 1500.0 F_A 1', '100 201 1001.0 5001.0 1510.0 F_A 1', '101 200 1002.0 5002.0 1520.5 F_A 2',
    '101 201 1003.0 5003.0 1530.0 F_A 2', '102 200 2000.0 6000.0 1600.0 Øst_B 1', '100 202 1004.0 5004.0 1540.0 F_A 1',
    '100 203 1005.0 5005.0 1550.0 F_A 1', '103 200 2001.0 6001.0 1610.0 Øst_B 2', '103 201 2002.0 6002.0 1620.0 Øst_B 2')).encode()
STICKS = [
    {'index': 1, 'fault': 'F_A', 'stick': 1, 'points': [{'x': 1000.0, 'y': 5000.0, 'z': 1500.0}, {'x': 1001.0, 'y': 5001.0, 'z': 1510.0}]},
    {'index': 2, 'fault': 'F_A', 'stick': 2, 'points': [{'x': 1002.0, 'y': 5002.0, 'z': 1520.5}, {'x': 1003.0, 'y': 5003.0, 'z': 1530.0}]},
    {'index': 3, 'fault': 'Øst_B', 'stick': 1, 'points': [{'x': 2000.0, 'y': 6000.0, 'z': 1600.0}]},
    {'index': 4, 'fault': 'F_A', 'stick': 1, 'points': [{'x': 1004.0, 'y': 5004.0, 'z': 1540.0}, {'x': 1005.0, 'y': 5005.0, 'z': 1550.0}]},
    {'index': 5, 'fault': 'Øst_B', 'stick': 2, 'points': [{'x': 2001.0, 'y': 6001.0, 'z': 1610.0}, {'x': 2002.0, 'y': 6002.0, 'z': 1620.0}]},
]
DECLARED = {'z_meaning': 'depth', 'z_unit': 'm', 'positive': 'down'}
STATED = ('The CRS file faults.txt.crsmeta.xml states SYN_ED50_UTM31N (Statoil,9000002; datum D_European_1950), not an EPSG '
          'code; the coordinate system is left to the person.')


def test_the_literals_are_the_connectors_fixture():
    assert (hashlib.sha256(PRIMARY).hexdigest(), len(PRIMARY)) == ('9971f7c8ee9c8b6d84d2803dc4d3994987e2d33bcbb8b5fc102939e9acf03771', 396)


def test_the_sdk_reads_every_stick_in_file_order_and_an_export_refuses(web, tmp_path):
    folder = tmp_path / 'faults'; folder.mkdir()
    (folder / 'faults.txt').write_bytes(PRIMARY); (folder / 'faults.txt.crsmeta.xml').write_bytes(CRS)
    alice = Client('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), web.c)
    report = alice.upload(folder, attribution='Synthetic', rights_confirmed=True, declare={'petrel-faultsticks/1': DECLARED})
    primary = next(i for i in report.items if i['role'] == 'primary')
    assert report.ok and (primary['state'], primary['profile']) == ('added', 'petrel-faultsticks/1')
    read = alice.read_data(primary['asset_id'], primary['revision'])
    assert read.data['sticks'] == STICKS
    c = read.context
    assert (c['type'], c['sticks'], c['points'], c['crs'], c['xy_unit']) == ('polyline-set', 5, 9, 'unknown', 'm')
    assert c['fidelity']['decisions'] == [STATED]
    assert read._wire_descriptor['interpretation']['reader'] == 'asset_connectors.petrel_faults/1'
    # A-g, scope guard: the bundle export does not know the profile (`bundle.TYPED_ORIGINALS`) and stops before writing a
    # file, as for every profile it does not list; S1f-b owns the export and turns this into a written bundle.
    with pytest.raises(KeyError, match='petrel-faultsticks/1'):
        alice.export([(primary['asset_id'], primary['revision'], None)], tmp_path / 'out')
    assert not (tmp_path / 'out').exists()
