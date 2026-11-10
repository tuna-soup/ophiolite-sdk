"""E117 (D6): the project folder journey, from an installed SDK wheel in a clean environment without pandas or pyarrow.

The journey of the epic, by slice; only the steps that exist run, none is stubbed or skipped:

    s0  import ophiolite.folder; check() a valid /2 folder and a damaged one, with their frozen reports   (this test)
    s1  pip install 'ophiolite[folder]'; write_folder('field/', {'wells': frame}); ophiolite bundle check field/
        in plain words; pandas.read_parquet('field/items/wells.parquet')                               (this test)
    s2  GDAL reads the GeoParquet geometry (R-5); well tops and a grid join the folder; QGIS opens the wells layer and the grid on a WGS84 basemap
    s3  ophiolite-mapper writes /2; a frozen pre-extension reader, a /1-only reader and a /2 reader each read it
    s4  the NLOG, synthetic and Volve-or-synthetic example folders, the page linked from docs/ and the public SDK

OPHIOLITE_TEST_WHEEL_PYTHON is the base wheel's interpreter (Visual builds build/sdk-wheel with no extras).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
SCRIPT = r'''
import importlib.util, json, shutil, sys, tempfile
from importlib.resources import files
from pathlib import Path
assert importlib.util.find_spec('pandas') is None and importlib.util.find_spec('pyarrow') is None, 'not a clean environment'
import ophiolite
from ophiolite.folder import check
valid = Path(str(files('ophiolite').joinpath('contracts/folders/v1/fixtures/valid/wells-grid')))
with tempfile.TemporaryDirectory() as work:
    damaged = Path(work) / 'damaged'
    shutil.copytree(valid, damaged)
    raw = bytearray((damaged / 'items/grid.tif').read_bytes()); raw[-1] ^= 0x01
    (damaged / 'items/grid.tif').write_bytes(bytes(raw))
    print(json.dumps({'where': ophiolite.__file__, 'valid': check(valid), 'damaged': check(damaged),
                      'loaded': sorted(m for m in ('pandas', 'pyarrow', 'numpy') if m in sys.modules)}))
'''
WELLS = {'path': 'items/wells.parquet', 'kind': 'wells', 'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'}, 'derived': 'manifest'}
GRID = {'path': 'items/grid.tif', 'kind': 'grid', 'osdu': {'kind': 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'}, 'derived': 'manifest'}


def test_s0_check_runs_from_the_installed_wheel_without_pandas_or_pyarrow(tmp_path):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    done = subprocess.run([WHEEL, '-I', '-c', SCRIPT], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert 'site-packages' in result['where'] and result['loaded'] == []
    assert result['valid'] == {'ok': True, 'verified': 'bytes', 'schema': 'ophiolite.project-folder/2',
                               'files': [{'path': 'items/wells.parquet', 'role': 'item', 'verdict': 'ok'},
                                         {'path': 'items/grid.tif', 'role': 'item', 'verdict': 'ok'}],
                               'items': [{**WELLS, 'verdict': 'ok'}, {**GRID, 'verdict': 'ok'}], 'first_problem': None}
    assert result['damaged'] == {'ok': False, 'verified': 'bytes', 'schema': 'ophiolite.project-folder/2',
                                 'files': [{'path': 'items/wells.parquet', 'role': 'item', 'verdict': 'ok'},
                                           {'path': 'items/grid.tif', 'role': 'item', 'verdict': 'file-digest'}],
                                 'items': [{**WELLS, 'verdict': 'ok'}, {**GRID, 'verdict': 'file-digest'}],
                                 'first_problem': {'code': 'file-digest', 'path': 'items/grid.tif'}}


WITHOUT = r'''
import importlib.util, json
from ophiolite.errors import Refused
from ophiolite.folder import write_folder
try:
    write_folder('field', {'wells': (None, {'crs': 'EPSG:28992'})}); said = None
except Refused as refused:
    said = str(refused)
print(json.dumps({'said': said, 'found': [m for m in ('pandas', 'pyarrow', 'pyproj') if importlib.util.find_spec(m)]}))
'''
WITH = r'''
import json, pandas, pyarrow, pyproj
from ophiolite.folder import write_folder
frame = pandas.DataFrame({'id': ['SYN-J1', 'SYN-J2'], 'name': ['Journey 1', 'Journey 2'], 'x': [150000.0, 150500.5], 'y': [450000.0, 450250.25]})
report = write_folder('field', {'wells': (frame, {'crs': 'EPSG:28992'})})
read = pandas.read_parquet('field/items/wells.parquet')
print(json.dumps({'ok': report['ok'], 'rows': [list(r) for r in read[['id', 'x', 'y']].itertuples(index=False, name=None)],
                  'versions': {'pandas': pandas.__version__, 'pyarrow': pyarrow.__version__, 'pyproj': pyproj.__version__}}))
'''


def test_s1_write_check_and_read_from_the_wheel_with_the_folder_extra(tmp_path):
    """D8: a clean venv from the lane's wheel refuses with the extra's sentence; with ophiolite[folder] it writes,
    `ophiolite bundle check` says what the folder holds, and pandas reads the wells back. Needs the package index."""
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
        pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
    [wheel] = Path(dist).glob('ophiolite-*.whl')
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    run = lambda *argv, timeout=120: subprocess.run([str(a) for a in argv], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=timeout)
    made = run(sys.executable, '-m', 'venv', tmp_path / 'venv')
    assert made.returncode == 0, made.stderr
    python, command = tmp_path / 'venv/bin/python', tmp_path / 'venv/bin/ophiolite'
    pip = lambda target: run(python, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', target, timeout=600)
    done = pip(wheel)
    assert done.returncode == 0, done.stderr
    done = run(python, '-I', '-c', WITHOUT)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {'said': 'Writing a project folder needs pandas, pyarrow and pyproj: pip install "ophiolite[folder]".', 'found': []}
    assert not (tmp_path / 'field').exists()
    done = pip('%s[folder]' % wheel)
    assert done.returncode == 0, done.stderr
    done = run(python, '-I', '-c', WITH)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert (result['ok'], result['rows']) == (True, [['SYN-J1', 150000.0, 450000.0], ['SYN-J2', 150500.5, 450250.25]])
    done = run(command, 'bundle', 'check', 'field')
    assert (done.returncode, done.stdout) == (0, 'Project folder verified: 1 item (wells, 2 rows). Checksums show integrity, not authorship.\n'), done.stderr
    print('E117 s1 journey: the folder extra installed %s' % json.dumps(result['versions'], sort_keys=True))
