"""E129 (e): the pack mode of the notebook gallery (strategy rev 3, D1, D3, D6; acceptance A3's guard, A6 and R2-7).

`ophiolite.gallery.pack()` returns the starter pack folder only after blocking the process's network, and refuses with
OPHIOLITE_URL set or without OPHIOLITE_PACK; it runs in a child process here, so this process keeps its network.
`ophiolite.testing.synthetic_pack` writes a rotated cube in the export's SEG-Y form that `starter_archive.read_cube`
reads back, and its `expected.json` comes from `starter.expected` (D1), checked against values counted by hand from
the pack's formulas: x = 431000 + 15 (c - 200) - 20 (i - 100), y = 6500000 + 20 (c - 200) + 15 (i - 100), sample
(i - 100) + (c - 200) / 4 + k / 16. segyio is only in the `pack` extra and `dev` (A6). Nothing here needs the `pack`
extra or reads above the SDK tree; the notebook's runs and the image lock are in tests/gateway/test_pack_notebook.py."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from ophiolite import gallery, starter, starter_archive, testing
from ophiolite.errors import Refused

SDK = Path(__file__).resolve().parents[1]


def child(code, env=None, cwd=None):
    """CODE in a fresh interpreter importing this checkout's SDK, OPHIOLITE_* from ENV only."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}
    environment.update(PYTHONPATH=os.pathsep.join([str(SDK)] + ([os.environ['PYTHONPATH']] if os.environ.get('PYTHONPATH') else [])), **(env or {}))
    return subprocess.run([sys.executable, '-c', code], env=environment, cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.fixture
def listening():
    """A local listening TCP socket: (host, port)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0)); server.listen(4)
    yield server.getsockname()
    server.close()


# --- D3: the guard -------------------------------------------------------------------------------------------------

CONNECT = '''
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
def attempts():
    yield 'create_connection', lambda: socket.create_connection((host, port), timeout=5).close()
    yield 'socket', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
    yield 'getaddrinfo', lambda: socket.getaddrinfo('localhost', port)
'''


def test_pack_blocks_the_network_of_its_process_before_it_returns_the_folder(tmp_path, listening):
    code = ('import sys; sys.argv[1:] = %r\n' % [listening[0], str(listening[1])] + CONNECT +
            'import socket as s0\nfrom ophiolite.gallery import pack\nfor name, attempt in attempts(): attempt()\n'
            'print("before:", "connected")\nfolder = pack()\nprint("folder:", folder)\nfor name, attempt in attempts():\n'
            '    try: attempt(); print(name, "connected")\n    except Exception as e: print(name, type(e).__name__, e)\n'
            'import socket\nprint("unix:", socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).family.name)\n')
    done = child(code, env={'OPHIOLITE_PACK': str(tmp_path)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ['before: connected', 'folder: %s' % tmp_path,
                                        'create_connection Refused network blocked: this notebook reads the pack folder only',
                                        'socket Refused network blocked: this notebook reads the pack folder only',
                                        'getaddrinfo Refused network blocked: this notebook reads the pack folder only',
                                        'unix: AF_UNIX']


@pytest.mark.parametrize('env, sentence', [
    ({'OPHIOLITE_PACK': 'pack', 'OPHIOLITE_URL': 'https://gateway.example.org'}, 'This notebook reads the starter pack folder only; unset OPHIOLITE_URL.'),
    ({}, 'Set OPHIOLITE_PACK to the folder of a starter pack you downloaded.'),
], ids=['with-a-project-address', 'without-a-pack'])
def test_pack_refuses_a_project_address_and_a_missing_pack_and_blocks_nothing(env, sentence, listening):
    code = ('import socket\nfrom ophiolite.gallery import pack\ntry: pack()\nexcept Exception as e: print(type(e).__name__, e)\n'
            'socket.create_connection(%r, timeout=5).close(); print("still connects")\n' % (tuple(listening),))
    done = child(code, env=env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ['Refused ' + sentence, 'still connects']
    assert (gallery.PACK_WITH_URL, gallery.PACK_UNSET) == ('This notebook reads the starter pack folder only; unset OPHIOLITE_URL.',
                                                           'Set OPHIOLITE_PACK to the folder of a starter pack you downloaded.')


# --- D1 and synthetic_pack -------------------------------------------------------------------------------------------

EXPECTED = {
    'schema': 'ophiolite.starter-python-expected/1', 'cube': 'seismic/Syn.sgy', 'inline': 102, 'crosslines': [200, 206, 2], 'z': [100, 4000, 6],
    # inline 102, middle sample k = 2: 2 + (c - 200) / 4 + 2 / 16 at crosslines 200, 202 (floor middle of 4) and 206
    'samples': [{'crossline': 200, 'index': 2, 'value': 2.125}, {'crossline': 202, 'index': 2, 'value': 2.625}, {'crossline': 206, 'index': 2, 'value': 3.625}],
    # per trace 6 * 2 + 1.5 (c - 200) + 15 / 16; over c = 200..206 step 2: 4 * 12.9375 + 1.5 * 12
    'inline_sum': 69.75,
    # SYN-A (431020, 6500050): 20 and 50 m from the origin; along the crosslines (15, 20) / 25 m per line: 2.08; along the
    # inlines (-20, 15): 0.56. SYN-B (431060, 6500100): 4.64 and 0.48.
    'wells': [{'name': 'SYN-A', 'positions': 'wells/SYN-A-positions.csv', 'x': 431020.0, 'y': 6500050.0, 'inline': 100.56, 'crossline': 202.08,
               'las': 'wells/SYN-A.las', 'curves': 2, 'depth': [10.0, 10.6]},
              {'name': 'SYN-B', 'positions': 'wells/SYN-B-positions.csv', 'x': 431060.0, 'y': 6500100.0, 'inline': 100.48, 'crossline': 204.64,
               'las': None, 'curves': None, 'depth': None}]}


def test_synthetic_pack_writes_the_exports_segy_and_d1s_expected_values(tmp_path):
    folder = testing.synthetic_pack(tmp_path / 'pack')
    assert folder == tmp_path / 'pack'
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()) == [
        'files/seismic/Syn.sgy', 'files/targets/python/expected.json', 'files/wells/SYN-A-positions.csv', 'files/wells/SYN-A.las', 'files/wells/SYN-B-positions.csv']
    raw = (folder / 'files/targets/python/expected.json').read_bytes()
    assert json.loads(raw) == EXPECTED and raw == starter.dumped(EXPECTED)
    # the export's own reader takes the cube: its axes, and the D9 digest of the samples written
    axes = {'inline': [100, 104, 2], 'crossline': [200, 206, 2], 'z': [100, 4000, 6]}
    f = {'path': 'seismic/Syn.sgy', 'kind': 'seismic-3d', 'object': 'Syn', 'axes': axes}
    got, digest = starter_archive.read_cube(folder / 'files/seismic/Syn.sgy', f)
    import struct
    want = hashlib.sha256(starter_archive.head('seismic-3d', 'Syn', axes))
    for i in (100, 102, 104):
        for c in (200, 202, 204, 206):
            x, y = testing.pack_position(i, c)
            want.update(struct.pack('>iiqq', i, c, round(x * 100), round(y * 100)) + struct.pack('>6f', *(testing.pack_sample(i, c, k) for k in range(6))))
    assert (got, digest) == (axes, want.hexdigest())
    assert testing.pack_position(100, 200) == (431000.0, 6500000.0) and testing.pack_position(102, 202) == (430990.0, 6500070.0)


def cube(tmp_path, name, inlines, position=testing.pack_position):
    path = tmp_path / 'files' / 'seismic' / name
    testing.pack_segy(path, inlines=inlines, position=position)
    return {'path': 'seismic/' + name, 'kind': 'seismic-3d', 'object': name[:-4], 'local': path}


def test_the_first_cube_in_path_order_and_the_floor_middle_of_an_even_inline_range(tmp_path):
    """R2-7: four inlines 100-106 (the floor middle is 102, not 104); the second cube is listed first in derived[] and is
    not chosen."""
    first, second = cube(tmp_path, 'A.sgy', [100, 106, 2]), cube(tmp_path, 'B.sgy', [100, 104, 2])
    found = starter.expected([second, first])
    assert (found['cube'], found['inline'], found['crosslines']) == ('seismic/A.sgy', 102, [200, 206, 2])
    assert found['wells'] == [] and found['samples'][1] == {'crossline': 202, 'index': 2, 'value': 2.625}


@pytest.mark.parametrize('inlines, position', [
    ([100, 104, 2], lambda i, c: (431000.0 + 15.0 * (c - 200) + 30.0 * (i - 100), 6500000.0 + 20.0 * (c - 200) + 40.0 * (i - 100))),  # collinear
    ([100, 100, 2], testing.pack_position),  # one inline
], ids=['collinear-positions', 'one-inline'])
def test_trace_headers_spanning_no_area_are_refused(tmp_path, inlines, position):
    with pytest.raises(Refused) as caught: starter.expected([cube(tmp_path, 'A.sgy', inlines, position)])
    assert str(caught.value) == "The cube's corners do not span an area; the Python target cannot place wells on it." + starter.NOT_WRITTEN


def test_an_export_without_a_cube_is_refused_for_the_python_target(tmp_path):
    with pytest.raises(Refused) as caught: starter.expected([])
    assert str(caught.value) == 'The Python target reads a cube or a 2D line; this export has neither.' + starter.NOT_WRITTEN


def test_the_las_facts_are_read_from_its_curve_and_well_sections(tmp_path):
    p = tmp_path / 'w.las'
    p.write_text(testing.PACK_LAS)
    assert starter.las_facts(p) == (2, [10.0, 10.6])


# The notebook's own run on synthetic_pack (D2: A2 b, A3, R2-10) needs the `pack` extra: tests/gateway/test_pack_notebook.py.


# --- A6: segyio only in the pack extra and dev -----------------------------------------------------------------------

def names(requirements):
    import re
    return {re.split(r'[<>=!~\[ ;@]', r.strip(), 1)[0].lower() for r in requirements if r.strip() and not r.strip().startswith('#')}


def test_segyio_is_only_in_the_pack_extra_and_dev():
    project = tomllib.loads((SDK / 'pyproject.toml').read_text())['project']
    extras = project['optional-dependencies']
    assert 'segyio' not in names(project['dependencies'])
    assert {name for name, reqs in extras.items() if 'segyio' in names(reqs)} == {'pack', 'dev'}
    assert extras['pack'] == ['segyio==1.9.14', 'lasio>=0.32', 'numpy', 'matplotlib'] and 'segyio==1.9.14' in extras['dev']
    lock = SDK / 'ophiolite/templates/notebook/requirements.lock'  # the image lock: tests/gateway/test_pack_notebook.py
    assert 'segyio' not in names(lock.read_text().splitlines()), lock
