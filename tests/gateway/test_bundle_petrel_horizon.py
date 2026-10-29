"""E123 s1b C3 (R10, U9): a Petrel horizon export with inline and crossline, exported through the in-process gateway with
Client.export and opened offline, keeps the original bytes, the CRS companion and the interpretation.

The bytes are the Connectors' synthetic fixture (`tests/fixtures/petrel_horizon/`), written here as literals so the SDK lane
reads no other component's file; the licensed excerpt is Integration data and is checked there (conformance, D75). Every
oracle is written by hand: the two digests, the six points and their inline and crossline numbers, the undecided coordinate
system and the sentence that keeps what the CRS file states."""
import hashlib
import os

import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web, shared, app, service  # noqa: F401 (fixtures)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential
from ophiolite.bundle import open_bundle

PRIMARY = b''.join(b'INLINE :    %d XLINE :    %d    %s   %s      %s\n' % row for row in (
    (101, 201, b'500000.00000', b'6000000.00000', b'1000.00000'), (101, 202, b'500025.00000', b'6000000.00000', b'1001.50000'),
    (101, 203, b'500050.00000', b'6000000.00000', b'1003.25000'), (102, 201, b'500000.00000', b'6000025.00000', b'1002.00000'),
    (102, 202, b'500025.00000', b'6000025.00000', b'1004.75000'), (102, 203, b'500050.00000', b'6000025.00000', b'1006.00000')))
CRS = (b'<?xml version="1.0" encoding="utf-8"?><!--INFO: Synthetic, written by hand for E123 s1b: the shape of an Ocean spatial '
       b'companion that states no EPSG code.--><SpatialCompanion version="1.0"><IEarlyBoundCoordinateReferenceSystem '
       b'name="SYN_ED50_UTM31N_T1" crsType="Projected" engine="ESRI"><AuthorityCode>Statoil,9000001</AuthorityCode>'
       b'<ILateBoundCoordinateReferenceSystem name="SYN_ED50_UTM31N"><AuthorityCode>Statoil,9000002</AuthorityCode><WKT>'
       b'PROJCS["SYN_ED50_UTM31N",GEOGCS["GCS_European_1950",DATUM["D_European_1950",SPHEROID["International_1924",6378388.0,'
       b'297.0]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.017453292519943295]],PROJECTION["Transverse_Mercator"],'
       b'PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",3.0],'
       b'PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1]]</WKT>'
       b'</ILateBoundCoordinateReferenceSystem></IEarlyBoundCoordinateReferenceSystem><Info history="Synthetic" />'
       b'</SpatialCompanion>\n')
STATED = ('The CRS file horizon.txt.crsmeta.xml states SYN_ED50_UTM31N (Statoil,9000002; datum D_European_1950), not an EPSG '
          'code; the coordinate system is left to the person.')


def test_the_literals_are_the_connectors_fixture():
    assert (hashlib.sha256(PRIMARY).hexdigest(), len(PRIMARY)) == ('f632827f1506e37bf932afcd05c0336e4a614cfa24827ec94853ed1872124cf1', 474)
    assert (hashlib.sha256(CRS).hexdigest(), len(CRS)) == ('db9e6ae92a283df452b1bbd09feb0d3299ba562507dc43062cdc2ad71a2f2543', 981)


def test_an_exported_horizon_keeps_its_original_its_crs_file_and_its_interpretation(web, tmp_path):
    folder = tmp_path / 'horizon'; folder.mkdir()
    (folder / 'horizon.txt').write_bytes(PRIMARY); (folder / 'horizon.txt.crsmeta.xml').write_bytes(CRS)
    alice = Client('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), web.c)
    report = alice.upload(folder, attribution='Synthetic', rights_confirmed=True)
    primary = next(i for i in report.items if i['role'] == 'primary')
    assert report.ok and primary['state'] == 'added' and primary['revision'] == hashlib.sha256(PRIMARY).hexdigest()
    exported = alice.export([(primary['asset_id'], primary['revision'], None)], tmp_path / 'out')
    assert (exported.path / 'assets/0/original.txt').read_bytes() == PRIMARY
    [a] = open_bundle(exported.path).assets
    assert a.original == PRIMARY and a.package.companions == {'horizon.txt.crsmeta.xml': CRS}
    c = a.data.context
    assert (a.data.version, c['count'], c['xy_unit'], c['crs'], c['z_unit']) == (2, 6, 'm', 'unknown', 'unknown')
    assert a.data.points == [[500000.0, 6000000.0, 1000.0], [500025.0, 6000000.0, 1001.5], [500050.0, 6000000.0, 1003.25],
                             [500000.0, 6000025.0, 1002.0], [500025.0, 6000025.0, 1004.75], [500050.0, 6000025.0, 1006.0]]
    assert {x['name']: x['values'] for x in a.data.data['attributes']} == {'INLINE': [101, 101, 101, 102, 102, 102], 'XLINE': [201, 202, 203, 201, 202, 203]}
    crs = next(d for d in a.package.decisions if d['field'] == 'crs')
    assert (crs['status'], crs['observations']) == ('needs-decision', [])
    interpretation = a.package.interpretation
    assert (interpretation['schema'], interpretation['recipe']['document']['profile']) == ('ophiolite.recipe-execution/1', 'petrel-horizon-ilxl/1')
    assert c['fidelity']['comments'] == [STATED]
