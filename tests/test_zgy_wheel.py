"""E123 SZ C3 test 8 (B3): the packaged "Read a ZGY cube on your computer" ships in the built wheel, and in the core-only
wheel venv (no pyzgy, no numpy) its run is refused before it starts, naming pyzgy, while `zgy.read` gives the
missing-package sentence. The real conversion from the dev install is test_zgy.py's packaged-procedure test."""
import os
import subprocess
from pathlib import Path

CUBE = Path(__file__).resolve().parent / 'fixtures' / 'zgy' / 'small-32bit.zgy'
SCRIPT = r'''
import importlib.util, sys, sysconfig
from pathlib import Path
assert importlib.util.find_spec('openzgy') is None and importlib.util.find_spec('segyio') is None
from ophiolite import procedures, zgy
assert Path(sysconfig.get_paths()['purelib']).resolve() in zgy.PROCEDURE.parents, zgy.PROCEDURE
assert sorted(p.name for p in zgy.PROCEDURE.iterdir() if p.suffix in ('.json', '.py', '.md')) == ['README.md', 'procedure.json', 'procedure.py']
settings = ['crs=EPSG:23031', 'z_domain=time', 'horizontal_unit=m']
try: procedures.run(zgy.PROCEDURE, Path(sys.argv[2]), {'file': [sys.argv[1]]}, settings=settings)
except procedures.NotRun as error: assert error.code == 'requires-missing' and 'pyzgy' in str(error), (error.code, str(error))
else: raise AssertionError('ran without pyzgy')
assert not Path(sys.argv[2]).exists()
try: zgy.read(sys.argv[1], crs='EPSG:23031', z_domain='time', horizontal_unit='m')
except procedures.Stopped as stop: assert stop.sentence == zgy.MISSING and not stop.asks, stop.sentence
else: raise AssertionError('read without pyzgy')
'''


def test_the_core_wheel_ships_the_procedure_and_names_the_missing_extra(tmp_path):
    python = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    assert python, 'Provide the base-only installed-wheel interpreter'
    result = subprocess.run([python, '-I', '-c', SCRIPT, str(CUBE), str(tmp_path / 'out')], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
