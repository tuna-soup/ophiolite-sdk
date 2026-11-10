"""E144 s1 C2: the deviation-csv/1 evaluators. Carried into the SDK byte for byte, standard library only.

The neutral input (strategy §2): {'depth_unit', 'depth_datum', 'md': Column}, stations in file order; a station's
row is its 1-based data row.
"""
from .engine import Failures

TO_METRES = {'m': 1.0, 'ft': 0.3048}


def station_step(data, parameters, quantities):
    factor = TO_METRES.get(data['depth_unit'])
    if factor is None: return 'no-column'
    md, bound, found = data['md'], parameters['maximum_step'], Failures()
    for i in range(1, len(md)):
        step = (md[i] - md[i - 1]) * factor
        if step > bound: found.add(i + 1, md[i], step)
    return found


EVALUATORS = {'station-step/1': station_step}
