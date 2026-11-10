"""E144 s1 C2: the well-tops-csv/1 evaluators. Carried into the SDK byte for byte, standard library only.

The neutral input (strategy §2): {'depth_unit', 'depth_datum', 'tops': [{'name', 'md'}]}, in file order; a
top's row is its 1-based data row.
"""
from .engine import Failures


def _key(name):
    return ' '.join(name.split()).casefold()


def tops_unique_name(data, parameters, quantities):
    seen, found = set(), Failures()
    for row, top in enumerate(data['tops'], start=1):
        key = _key(top['name'])
        if key in seen: found.add(row, top['md'], top['name'])
        seen.add(key)
    return found


EVALUATORS = {'tops-unique-name/1': tops_unique_name}

# E144 s1b: project-context rules, run over the context the project found (engine.context_results).
FOOT = 0.3048  # exactly, as trajectories.py
METRES = {'m': 1.0, 'ft': FOOT}


def _stated(datum):
    return isinstance(datum, str) and datum.strip() != '' and datum.strip().casefold() != 'unknown'


def top_on_path(data, parameters, quantities, context):
    """Each top's MD (in m) within [first, last] station MD (in m) of the context path, both ends included. A unit other
    than m or ft on either side, or two stated datums that differ, is no context to compare with."""
    path = context['path']
    if data['depth_unit'] not in METRES or path['depth_unit'] not in METRES: return 'no-context'
    datum, theirs = data.get('depth_datum'), path.get('datum')
    if _stated(datum) and _stated(theirs) and datum.strip().casefold() != theirs.strip().casefold(): return 'no-context'
    scale, along = METRES[data['depth_unit']], METRES[path['depth_unit']]
    first, last, found = path['first'] * along, path['last'] * along, Failures()
    for row, top in enumerate(data['tops'], start=1):
        md = top['md']
        if md is None or md != md: continue
        if not first <= md * scale <= last: found.add(row, md, md)
    return found


CONTEXT_EVALUATORS = {'top-on-path/1': top_on_path}
