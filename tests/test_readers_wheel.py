"""E128 s4 (acceptance 7): from an installed wheel, outside this checkout, `ophiolite procedures run` runs a process
procedure whose entry reads its input with ophiolite.readers, and its output is a literal written here
(E128-readers-S4-COMMIT-STRATEGY.md S4-D8). `ENTRY` is the example of the user page "Read your procedure's inputs"
(web/docs/src/content/docs/guides/read-your-procedures-inputs.md); tools/test_readers_page.py holds the two equal."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_init_wheel import ROOT, clean_env, installed_outside

WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')

ENTRY = '''\
"""Shale volume from gamma ray: read the log with ophiolite.readers, write a derived curve."""
from ophiolite import procedure, readers
from ophiolite.writers import write_curves


@procedure
def shale_volume(inputs, settings):
    log = readers.read(inputs['log'][0])
    names = [curve[0] for curve in log.curves]
    depth = [row[0] for row in log.data]
    gamma = [row[names.index('GR')] for row in log.data]
    known = [value for value in gamma if value is not None]
    low, high = min(known), max(known)
    shale = [None if value is None else round((value - low) / (high - low), 4) for value in gamma]
    return {'vsh': write_curves(depth, {'VSH': ('v/v', shale)}, depth_unit=log.curves[0][1], well='DERIVED')}
'''

MANIFEST = {'schema': 'ophiolite.procedure/1', 'name': 'shale-volume', 'label': 'Shale volume from gamma ray', 'version': 1,
            'version_label': 'First release', 'step': 'process',
            'inputs': [{'slot': 'log', 'label': 'Log with a gamma ray curve', 'class': 'version', 'kinds': ['las2/1'], 'cardinality': 'one'}],
            'outputs': [{'role': 'vsh', 'label': 'Shale volume', 'class': 'version', 'kind': 'las2/1'}],
            'settings': [], 'entry': 'entry:shale_volume', 'requires': [], 'licence': 'MIT'}

# GR is the third curve and RHOB's values differ from it, so reading by position cannot give this output; the GR NULL
# at 1000.5 m is carried to the output as its NULL.
LOG = (b'~Version\nVERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\nWRAP.   NO : One line per depth step\n'
       b'~Well\nSTRT.m 1000.0 :\nSTOP.m 1001.5 :\nSTEP.m 0.5 :\nNULL.   -999.2500 : Null value\nWELL.   W-1 : Well\n'
       b'~Curve\nDEPT.m      : Depth\nRHOB.g/cc   : Bulk density\nGR.gAPI     : Gamma ray\n'
       b'~A\n1000.0 2.45 40.0\n1000.5 2.50 -999.2500\n1001.0 2.55 120.0\n1001.5 2.60 60.0\n')

# By hand: GR 40, NULL, 120, 60 gives low 40 and high 120, so VSH 0, NULL, 1 and (60 - 40) / 80 = 0.25.
OUTPUT = (b'~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.m 1000 : start\nSTOP.m 1001.5 : stop\nSTEP.m 0.5 : step\n'
          b'NULL. -999.25 : missing\nWELL. DERIVED : well\n~Curve\nDEPT.m : depth\nVSH.v/v : VSH\n~ASCII\n'
          b'1000 0\n1000.5 -999.25\n1001 1\n1001.5 0.25\n')


def child_env():
    """What the run's child inherits: no PYTHONPATH, no OPHIOLITE_* (test_init_wheel.clean_env)."""
    return clean_env()


def test_the_installed_wheel_runs_a_procedure_that_reads_with_ophiolite_readers(tmp_path):
    """T-W. Mutations: Mw1 the entry reads GR by position 1 (RHOB) -> other values, red; Mw2 the child is given
    PYTHONPATH=<checkout>/ophiolite-sdk -> it imports the checkout's readers, the path assertion is red; Mw3 the entry
    writes 0.0 for a missing gamma ray -> the NULL row is 0.0, red."""
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    assert installed_outside(WHEEL, tmp_path)
    folder = tmp_path / 'shale-volume'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps(MANIFEST, indent=2))
    (folder / 'entry.py').write_text(ENTRY + "\nprint('readers from', readers.__file__)\n")
    (tmp_path / 'log.las').write_bytes(LOG)
    done = subprocess.run([WHEEL, '-m', 'ophiolite', 'procedures', 'run', str(folder), '--output', str(tmp_path / 'out'),
                           '--input', 'log=' + str(tmp_path / 'log.las'), '--kind', 'log=las2/1', '--json'],
                          cwd=tmp_path, env=child_env(), capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    site = subprocess.run([WHEEL, '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], cwd=tmp_path, env=clean_env(),
                          capture_output=True, text=True).stdout.strip()
    said = [line for line in (tmp_path / 'out' / 'log.txt').read_text().splitlines() if line.startswith('readers from ')]
    assert said == ['readers from ' + str(Path(site) / 'ophiolite' / 'readers' / '__init__.py')], (said, site)
    record = json.loads((tmp_path / 'out' / 'run.json').read_text())
    written = tmp_path / 'out' / record['outputs']['vsh']['file']
    assert written.read_bytes() == OUTPUT
