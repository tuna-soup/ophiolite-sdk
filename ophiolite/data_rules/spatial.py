"""E144 s2 C2: the spatial evaluators (snapshot 1.3.0). Carried into the SDK byte for byte, standard library only.

The neutral inputs (strategy §3), one per read context type; `system` is the declared system's entry of
coordinate-systems.json, or None when the system is unknown, uncatalogued or the axes are unknown:
  regular-grid-surface  {'system', 'ncols', 'nrows', 'x_first', 'y_first', 'cell', 'present': bytearray, row-major
                        from the north row}
  point-set             {'system', 'x': Column, 'y': Column}
  feature-set           {'system', 'swap': bool, 'features': [[(x, y), ...] or None, ...]}
  seismic-line          {'system', 'numbers': [int], 'x': Column, 'y': Column}
A node's row is its 1-based position: grid cell index, point, feature or trace in file order.
"""
import math

from .engine import Failures


def inside(system):
    """The test `(x, y) -> bool` of the system's box: a geographic system's area of use [west, south, east, north] in
    degrees, across 180 degrees when west exceeds east; a projected system's native extent [minx, miny, maxx, maxy] in
    its own units. Edges are inside; a non-finite coordinate is outside."""
    finite = math.isfinite
    if system['geographic']:
        west, south, east, north = system['area_of_use']
        if west > east:
            return lambda x, y: finite(x) and finite(y) and south <= y <= north and (x >= west or x <= east)
    else:
        west, south, east, north = system['native_extent']
    return lambda x, y: finite(x) and finite(y) and west <= x <= east and south <= y <= north


def _where(x, y):
    return '%r %r' % (float(x), float(y))


def _nodes(data):
    """(row, x, y) of every node of a grid, point set or line, in row order."""
    if 'present' in data:
        ncols, x_first, y_first, cell, present = data['ncols'], data['x_first'], data['y_first'], data['cell'], data['present']
        for i in range(data['ncols'] * data['nrows']):
            if present[i]:
                r, c = divmod(i, ncols)
                yield i + 1, x_first + c * cell, y_first - r * cell
        return
    for k, (x, y) in enumerate(zip(data['x'], data['y'])):
        yield k + 1, x, y


def in_area_of_use(data, parameters, quantities):
    if data['system'] is None: return 'no-column'
    test, found = inside(data['system']), Failures()
    if 'features' in data:
        swap = data['swap']
        for row, positions in enumerate(data['features'], start=1):
            for x, y in positions or ():
                if not (test(y, x) if swap else test(x, y)):
                    found.add(row, None, _where(x, y))  # the feature counts once, at its first outside position
                    break
        return found
    for row, x, y in _nodes(data):
        if not test(x, y): found.add(row, None, _where(x, y))
    return found


def trace_order(data, parameters, quantities):
    numbers, found = data['numbers'], Failures()
    direction = -1 if numbers and numbers[-1] < numbers[0] else 1  # one trace, or the same first and last: increasing
    for i in range(1, len(numbers)):
        if (numbers[i] - numbers[i - 1]) * direction <= 0: found.add(i + 1, None, numbers[i])
    return found


def geometry_present(data, parameters, quantities):
    found = Failures()
    for row, positions in enumerate(data['features'], start=1):
        if positions is None: found.add(row, None, None)
    return found


EVALUATORS = {'geometry-present/1': geometry_present, 'in-area-of-use/1': in_area_of_use, 'trace-order/1': trace_order}
