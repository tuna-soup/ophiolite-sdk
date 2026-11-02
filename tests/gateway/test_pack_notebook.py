"""E129 (e): the open-a-starter-pack notebook run on `ophiolite.testing.synthetic_pack` (strategy rev 3, D2; acceptance
A2 b, A3, R2-10), and the deployment lock half of A6.

These tests run the packaged notebook script as a program, which needs the `pack` extra (segyio, lasio, numpy,
matplotlib): with the installed wheel's interpreter when OPHIOLITE_TEST_WHEEL_PYTHON names one (the gateway lane's has
the extra; required with OPHIOLITE_REQUIRE_WHEEL=1), else this interpreter on this checkout when it has the extra. They
live under tests/gateway because the unit lane's wheel is base-only and the deployment lock lies above the SDK tree;
tests/test_pack_mode.py keeps the pack mode's own tests."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ophiolite import testing
from test_pack_mode import EXPECTED, names

SDK = Path(__file__).resolve().parents[2]
MONOREPO = SDK.parent
WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
SCRIPT = SDK / 'ophiolite/templates/starter-pack/open-a-starter-pack.py'
STAND_IN = '''import os, socket, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]
del sys.modules['segyio']
import segyio as real
opened = real.open
def open(*args, **kwargs):
    socket.create_connection(('127.0.0.1', int(os.environ['STAND_IN_PORT'])), timeout=5).close()  # before delegating
    return opened(*args, **kwargs)
real.open = open
sys.modules['segyio'] = real
'''


def pack_extra():
    """The interpreter that runs the notebook has the `pack` extra, or the test fails (OPHIOLITE_REQUIRE_WHEEL=1) or skips."""
    if WHEEL: return
    if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter with the pack extra')
    for name in ('segyio', 'lasio', 'numpy', 'matplotlib'): pytest.importorskip(name)


def notebook(tmp_path, pack=None, script=None, path=(), env=None):
    """The packaged notebook script run as a program in an empty folder: with the installed wheel's interpreter when
    OPHIOLITE_TEST_WHEEL_PYTHON names one (its `pack` extra installed), else this interpreter on this checkout.
    Returns (process, the notebook's JSON or None)."""
    pack_extra()
    work = tmp_path / 'run'
    work.mkdir()
    (work / 'notebook.py').write_text(script if script is not None else SCRIPT.read_text())
    environment = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_') and k != 'PYTHONPATH'}
    environment.update(HOME=str(tmp_path), MPLBACKEND='Agg', PYTHONPATH=os.pathsep.join([*map(str, path), *([] if WHEEL else [str(SDK)])]),
                       **({'OPHIOLITE_PACK': str(pack)} if pack else {}), **(env or {}))
    done = subprocess.run([WHEEL or sys.executable, 'notebook.py'], cwd=work, env=environment, capture_output=True, text=True, timeout=300)
    result = work / 'open-a-starter-pack.json'
    return done, json.loads(result.read_text()) if result.is_file() else None


def last_line(done):
    return done.stderr.strip().splitlines()[-1]


def test_the_notebook_reads_synthetic_pack_and_agrees_with_its_expected_values(tmp_path):
    done, result = notebook(tmp_path, testing.synthetic_pack(tmp_path / 'pack'))
    assert done.returncode == 0, done.stderr
    assert 'SYN-B: positions only; the pack holds no log for it' in done.stdout
    assert done.stdout.strip().endswith('Agrees with expected.json: inline 102, 3 samples, the inline sum and 2 wells')
    assert (tmp_path / 'run/open-a-starter-pack.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    assert (result['inline'], result['samples'], result['inline_sum'], result['without_logs'], result['differences']) == (102, EXPECTED['samples'], 69.75, ['SYN-B'], [])
    assert [(w['name'], w['inline'], w['crossline'], w['curves'], w['depth']) for w in result['wells']] == [
        ('SYN-A', 100.56, 202.08, 2, [10.0, 10.6]), ('SYN-B', 100.48, 204.64, None, None)]
    plotted = result['plotted']  # read back from the axes and the image artist (R2-6)
    assert (plotted['xlim'], plotted['ylim']) == ([200.0, 206.0], [120.0, 100.0])
    assert plotted['image'] == {'shape': [6, 4], 'values': [2.125, 2.625, 3.625], 'extent': [200.0, 206.0, 120.0, 100.0], 'origin': 'upper'}
    assert plotted['wells'] == pytest.approx({'SYN-A': 202.08, 'SYN-B': 204.64}, abs=1e-9)


def moved(i, c, k):
    """The sampled trace's middle sample raised by 0.5 and its next sample lowered by 0.5: the inline's sum is unchanged."""
    return testing.pack_sample(i, c, k) + ((0.5 if k == 2 else -0.5 if k == 3 else 0.0) if (i, c) == (102, 202) else 0.0)


def unsampled(i, c, k):
    """A sample of a trace the expected values do not sample (crossline 204) raised by 0.25."""
    return testing.pack_sample(i, c, k) + (0.25 if (i, c, k) == (102, 204, 0) else 0.0)


@pytest.mark.parametrize('change, named', [
    (lambda f: testing.pack_segy(f / 'files/seismic/Syn.sgy', sample=moved), 'the sample at crossline 202'),
    (lambda f: testing.pack_segy(f / 'files/seismic/Syn.sgy', sample=unsampled), 'inline_sum'),
    # SYN-A's first station one crossline spacing (25 m along (0.6, 0.8)) further
    (lambda f: (f / 'files/wells/SYN-A-positions.csv').write_text((f / 'files/wells/SYN-A-positions.csv').read_text().replace('0.0,431020.0,6500050.0,', '0.0,431035.0,6500070.0,', 1)), 'the projection of SYN-A'),
    (lambda f: (f / 'files/wells/SYN-A.las').write_text(testing.PACK_LAS.replace(' GR.API : GR\n', ' GR.API : GR\n RHOB.G/C3 : RHOB\n').replace(' 50.5\n', ' 50.5 2.3\n').replace(' 51.0\n', ' 51.0 2.3\n').replace(' 52.0\n', ' 52.0 2.3\n').replace(' -999.25\n10.6', ' -999.25 2.3\n10.6').replace(' 54.5\n', ' 54.5 2.3\n')), 'the curve count of SYN-A'),
    (lambda f: (f / 'files/wells/SYN-A.las').write_text(testing.PACK_LAS.replace('STOP.M 10.6', 'STOP.M 10.75')), 'the depth range of SYN-A'),
], ids=['sampled-trace', 'unsampled-trace', 'first-station', 'las-curves', 'las-depth'])
def test_each_change_to_the_pack_fails_exactly_its_own_comparison(tmp_path, change, named):
    folder = testing.synthetic_pack(tmp_path / 'pack')
    change(folder)
    done, result = notebook(tmp_path, folder)
    assert done.returncode != 0 and last_line(done) == 'AssertionError: Differs from expected.json: ' + named, done.stderr
    assert result['differences'] == [named]


def test_collinear_trace_headers_are_refused_by_the_notebook(tmp_path):
    folder = testing.synthetic_pack(tmp_path / 'pack')
    testing.pack_segy(folder / 'files/seismic/Syn.sgy', position=lambda i, c: (431000.0 + 15.0 * (c - 200) + 30.0 * (i - 100), 6500000.0 + 20.0 * (c - 200) + 40.0 * (i - 100)))
    done, result = notebook(tmp_path, folder)
    assert done.returncode != 0 and last_line(done) == "ValueError: The cube's corners do not span an area; the Python target cannot place wells on it." and result is None


def test_a_reader_that_reaches_the_network_fails_the_notebook_and_reaches_it_without_pack(tmp_path):
    """A3: a stand-in segyio first on the path connects to a local listening socket before it delegates to segyio.
    The notebook refuses it with the guard's sentence; the same notebook with pack() replaced by reading OPHIOLITE_PACK
    directly connects and passes, so the stand-in does reach the network when nothing blocks it."""
    (tmp_path / 'stand-in/segyio').mkdir(parents=True)
    (tmp_path / 'stand-in/segyio/__init__.py').write_text(STAND_IN)
    folder = testing.synthetic_pack(tmp_path / 'pack')
    server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(4); server.settimeout(0)
    try:
        port = {'STAND_IN_PORT': str(server.getsockname()[1])}
        (tmp_path / 'a').mkdir(); (tmp_path / 'b').mkdir()
        done, result = notebook(tmp_path / 'a', folder, path=[tmp_path / 'stand-in'], env=port)
        assert done.returncode != 0 and last_line(done).endswith('network blocked: this notebook reads the pack folder only') and result is None, done.stderr
        with pytest.raises(BlockingIOError): server.accept()  # nothing reached the listener
        script = SCRIPT.read_text()
        assert script.count('folder = pack()') == 1
        unguarded = script.replace('folder = pack()', "import os, pathlib; folder = pathlib.Path(os.environ['OPHIOLITE_PACK'])")
        done, result = notebook(tmp_path / 'b', folder, script=unguarded, path=[tmp_path / 'stand-in'], env=port)
        assert done.returncode == 0 and result['differences'] == [], done.stderr
        server.accept()[0].close()  # the stand-in connected
    finally:
        server.close()


@pytest.mark.parametrize('env, sentence', [
    ({'OPHIOLITE_URL': 'https://gateway.example.org'}, 'This notebook reads the starter pack folder only; unset OPHIOLITE_URL.'),
    ({}, 'Set OPHIOLITE_PACK to the folder of a starter pack you downloaded.'),
], ids=['with-a-project-address', 'without-a-pack'])
def test_the_notebook_refuses_a_project_address_and_a_missing_pack(tmp_path, env, sentence):
    folder = testing.synthetic_pack(tmp_path / 'pack')
    done, result = notebook(tmp_path, folder if env else None, env=env)
    assert done.returncode != 0 and last_line(done).endswith(sentence) and result is None, done.stderr


def test_segyio_is_not_in_the_image_lock():
    """A6, the deployment half (the SDK's own extras and notebook lock: tests/test_pack_mode.py)."""
    lock = MONOREPO / 'deployment/package/requirements.lock'
    assert 'segyio' not in names(lock.read_text().splitlines()), lock
