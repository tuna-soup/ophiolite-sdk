"""E140 s2 C4 (D-M, R14, R15): reading a starter cube back checks its grid as the traces stream, keeps every check it made
when it held the whole trace list, and is bounded in process memory whatever the trace count.

Same defects, same sentences (R14): the files below are written trace by trace here (never by the exporter). A regular
grid and a one-trace grid return the axes by hand; uneven inline spacing, uneven crossline spacing, a grid that is not
full, two adjacent traces swapped, an inline missing a crossline, an inline with another crossline set and a repeated
trace are each refused with the sentence the list comparison gave. A grid defect early in the file and a sample that is
not finite later still name the sample, as when the grid was compared at the end.

Process peak (R15): each measurement runs in its own Python process and reports the growth of `VmHWM`
(/proc/self/status) from the value read after the interpreter, the imports and the arguments are ready, so setup is left
out the same way every time. 600,000 traces of one float sample each: a regular 600 x 1,000 grid, a 1,000 x 600 grid
stored in shuffled order (refused, after the whole file is read) and an elongated 1 x 600,000 grid. The ceiling is
48 MiB per read. The comparator is `scanned`'s list from before C4: one (inline, crossline) tuple per trace, then a
second list of the full grid to compare with. Each test first asserts the comparator exceeds the ceiling by 1.5 x (so
the ceiling is known to catch it), then that the reader stays under it.

Measured (MiB, delta VmHWM). On the parent a75c170cd: comparator 146.3 / 148.4 / 147.1 (regular, shuffled, elongated;
it ran the list-building reader underneath), reader 106.9 / 106.9 / 106.1. With C4: comparator 106.9 / 107.1 / 105.7,
reader 0.0 / 0.0 / 0.0.

The same defect cases also pass against the parent's list-building `scanned` (run once with it swapped in), so the
sentences are the ones it gave.

Mutations (each applied, red, restored): a per-trace list reintroduced in `scanned` (the three peaks); the inline
spacing check dropped (uneven inline spacing passes); the first inline's crossline spacing unchecked (uneven crossline
spacing on one inline passes; with more inlines the later ones still catch it); only the inline order compared (the
differing crossline set passes); the grid refused as soon as it breaks (the later sample is no longer named)."""
import os
import random
import struct
import subprocess
import sys

import pytest

from ophiolite import starter_archive
from ophiolite.errors import Refused

MIB = 1 << 20
CEILING = 48 * MIB
SHAPES = {'regular': (600, 1000, False), 'shuffled': (1000, 600, True), 'elongated': (1, 600_000, False)}
NOT_A_GRID = 'seismic/C.sgy is not the SEG-Y the export writes: the traces are not a full inline-major grid. Nothing was sent.'
ENTRY = {'path': 'seismic/C.sgy', 'kind': 'seismic-3d', 'object': 'C', 'axes': {}}


def write(path, traces, values=None):
    """Format 5, revision 1, fixed length, scalar -100, one sample a trace; TRACES [(inline, crossline)] written one at
    a time (an iterable, never a whole file in memory). VALUES {position: sample} replaces a trace's sample."""
    binary = bytearray(400)
    struct.pack_into('>H', binary, 16, 4000); struct.pack_into('>H', binary, 20, 1); struct.pack_into('>h', binary, 24, 5)
    struct.pack_into('>H', binary, 300, 0x0100); struct.pack_into('>h', binary, 302, 1)
    head = bytearray(240)
    struct.pack_into('>h', head, 70, -100); struct.pack_into('>h', head, 108, 0); struct.pack_into('>HH', head, 114, 1, 4000)
    with open(path, 'wb') as out:
        out.write(b' ' * 3200 + bytes(binary))
        for n, (i, c) in enumerate(traces):
            struct.pack_into('>iiii', head, 180, 100 * i, 100 * c, i, c)
            out.write(bytes(head) + struct.pack('>f', (values or {}).get(n, float(n))))
    return path


def grid(inlines, crosslines):
    return [(i, c) for i in inlines for c in crosslines]


def read(path):
    try: return starter_archive.read_cube(path, ENTRY)[0]
    except Refused as refused: return str(refused)


# --- same defects, same sentences (R14) --------------------------------------------------------------------------------

def test_a_full_grid_returns_its_axes(tmp_path):
    assert read(write(tmp_path / 'C.sgy', grid([10, 12, 14], [3, 6, 9, 12]))) == \
        {'inline': [10, 14, 2], 'crossline': [3, 12, 3], 'z': [0, 4000, 1]}
    assert read(write(tmp_path / 'D.sgy', [(7, 9)])) == {'inline': [7, 7, 1], 'crossline': [9, 9, 1], 'z': [0, 4000, 1]}
    assert read(write(tmp_path / 'E.sgy', grid([1], [5, 6, 7]))) == {'inline': [1, 1, 1], 'crossline': [5, 7, 1], 'z': [0, 4000, 1]}


@pytest.mark.parametrize('traces', [
    pytest.param(grid([1, 2, 4], [1, 2, 3]), id='uneven-inline-spacing'),
    pytest.param(grid([1, 2, 3], [1, 2, 4]), id='uneven-crossline-spacing'),
    pytest.param(grid([1], [1, 2, 4]), id='uneven-crossline-spacing-one-inline'),
    pytest.param(grid([1, 2], [1, 2, 3])[:-1], id='not-full'),
    pytest.param([(1, 1), (1, 3), (1, 2), (2, 1), (2, 2), (2, 3)], id='swapped-adjacent'),
    pytest.param([(1, 1), (1, 2), (1, 3), (2, 1), (2, 3), (3, 1), (3, 2), (3, 3)], id='inline-missing-a-crossline'),
    pytest.param([(1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (2, 4)], id='differing-crossline-set'),
    pytest.param([(1, 1), (1, 2), (1, 2), (2, 1), (2, 2)], id='repeated-trace'),
    pytest.param([(2, 1), (2, 2), (1, 1), (1, 2)], id='inlines-decreasing'),
])
def test_a_grid_defect_is_refused_as_before(tmp_path, traces):
    assert read(write(tmp_path / 'C.sgy', traces)) == NOT_A_GRID


def test_a_later_defect_of_another_kind_is_still_the_one_named(tmp_path):
    traces = [(1, 1), (1, 3), (1, 2), (2, 1), (2, 2), (2, 3)]
    assert read(write(tmp_path / 'C.sgy', traces, {5: float('nan')})) == \
        'seismic/C.sgy is not the SEG-Y the export writes: a sample is not finite. Nothing was sent.'


# --- process peak (R15) ------------------------------------------------------------------------------------------------

PROBE = r'''
import sys
from ophiolite import starter_archive
from ophiolite.errors import Refused

def hwm():
    with open('/proc/self/status') as status:
        return next(int(line.split()[1]) * 1024 for line in status if line.startswith('VmHWM:'))

path, mode = sys.argv[1], sys.argv[2]
entry = {'path': 'seismic/C.sgy', 'kind': 'seismic-3d', 'object': 'C', 'axes': {}}
base = hwm()
traces = None
try:
    if mode == 'lists':  # the comparator: the per-trace list scanned kept before C4, then the full grid it was compared with
        traces = []
        starter_archive.scanned(path, 'seismic/C.sgy', lambda i, c, x, y, samples: traces.append((i, c)))
    else:
        starter_archive.read_cube(path, entry)
except Refused:
    pass
if traces is not None:
    inlines, crosslines = sorted({i for i, _ in traces}), sorted({c for _, c in traces})
    same = traces == [(i, c) for i in inlines for c in crosslines]
print(hwm() - base)
'''


def shaped(path, inlines, crosslines, shuffled):
    order = list(range(inlines * crosslines))
    if shuffled: random.Random(140).shuffle(order)
    return write(path, ((1 + n // crosslines, 1 + n % crosslines) for n in order))


def peak(path, mode):
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
    done = subprocess.run([sys.executable, '-c', PROBE, str(path), mode], capture_output=True, text=True, env=env, timeout=600)
    assert done.returncode == 0, done.stderr
    return int(done.stdout.split()[-1])


@pytest.mark.parametrize('shape', list(SHAPES))
def test_a_cube_read_back_stays_under_the_ceiling(tmp_path, shape):
    path = shaped(tmp_path / 'C.sgy', *SHAPES[shape])
    comparator, reader = peak(path, 'lists'), peak(path, 'read')
    print('%s: comparator %.1f MiB, reader %.1f MiB' % (shape, comparator / MIB, reader / MIB))
    assert comparator > 1.5 * CEILING, comparator
    assert reader < CEILING, reader
