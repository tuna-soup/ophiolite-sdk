"""E117 s1 C4 (D7): the synthetic-field example project folder of the Integration tree (examples/folders/).

    a  check() verifies the committed folder byte for byte
    b  pandas reads the four synthetic wells with their frozen ids and coordinates; geopandas reads four points in EPSG:28992
    c  build.py --check rebuilds the same content (manifest without digests, lineage, decoded Parquet)

A monorepo read, so it lives in tests/gateway (tools/test_sdk_tests_stay_in_tree.py); it skips where no Integration checkout
holds the SDK.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ophiolite.folder import check

EXAMPLES = Path(__file__).resolve().parents[3] / 'examples' / 'folders'
FOLDER = EXAMPLES / 'synthetic-field'
WELLS = [('SYN-F1', 'Synthetic field 1', 150000.0, 450000.0, 1200.0), ('SYN-F2', 'Synthetic field 2', 150750.5, 450250.0, 1325.5),
         ('SYN-F3', 'Synthetic field 3', 151500.0, 449500.25, 980.0), ('SYN-F4', 'Synthetic field 4', 152250.0, 450750.0, 1410.0)]

pytestmark = pytest.mark.skipif(not (EXAMPLES / 'build.py').is_file(), reason='no Integration checkout around the SDK')


def test_a_check_verifies_the_committed_folder():
    assert check(FOLDER) == {'ok': True, 'verified': 'bytes', 'schema': 'ophiolite.project-folder/2',
                             'files': [{'path': 'items/wells.parquet', 'role': 'item', 'verdict': 'ok'},
                                       {'path': 'lineage/prov.json', 'role': 'lineage-prov', 'verdict': 'ok'}],
                             'items': [{'path': 'items/wells.parquet', 'kind': 'wells', 'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'},
                                        'derived': 'manifest', 'verdict': 'ok'}], 'first_problem': None}
    manifest = json.loads((FOLDER / 'manifest.json').read_text())
    assert (manifest['bundle_version'], manifest['created_at'], manifest['folder']['writer']) == (
        '2.14.0', '2026-11-04T12:00:00Z', {'name': 'ophiolite-examples', 'version': '1'})


def test_b_pandas_and_geopandas_read_the_wells():
    pd = pytest.importorskip('pandas'); pytest.importorskip('pyarrow')
    frame = pd.read_parquet(FOLDER / 'items/wells.parquet')
    assert list(frame[['id', 'name', 'x', 'y', 'depth']].itertuples(index=False, name=None)) == WELLS
    assert list(frame['operator']) == ['Ophiolite examples'] * 4
    gpd = pytest.importorskip('geopandas')
    points = gpd.read_parquet(FOLDER / 'items/wells.parquet')
    assert points.crs.to_epsg() == 28992 and list(points.geom_type) == ['Point'] * 4
    assert [(p.x, p.y) for p in points.geometry] == [(w[2], w[3]) for w in WELLS]


def test_c_build_check_rebuilds_the_same_content():
    for module in ('pandas', 'pyarrow', 'pyproj'): pytest.importorskip(module)
    done = subprocess.run([sys.executable, str(EXAMPLES / 'build.py'), '--check'], capture_output=True, text=True, timeout=120)
    assert (done.returncode, done.stdout) == (0, 'synthetic-field: committed folder ok=True, rebuild same content=True\n'), done.stderr
