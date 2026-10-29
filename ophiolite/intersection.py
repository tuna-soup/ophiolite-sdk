"""E119a slice 3: where a well set member's trajectory meets a grid surface, every crossing that can be proved, or the
reason none is given.

`crossings(bound, surface)` takes a member bound with `client.well_sets.bind` and the surface it was bound to, read
with `client.read_data` (a regular grid surface), and runs the one trajectory geometry's `crossings`
(`ophiolite/contracts/geometry/v1/trajectory.py`, the Platform's byte for byte). Each crossing is bracketed to 0.01 m of
measured depth (`md`, `low`, `high`). Where a crossing cannot be proved, a row names one of `REASONS`: `grazing` and
`along-surface` ("within 0.01 m of the surface from about <a> to about <b>"), `uncertain`, `no-surface-data`,
`ends-above`, `starts-below`, and `no-trajectory` for a member without a trajectory (pass `None`). `nearest(result, md)`
picks the crossing nearest a measured depth, and only when the coverage is full and no row blocks the choice; otherwise
it names the reason. Nothing here contacts a server."""
from . import geometry
from .errors import Refused
from .well_sets import _survey


def crossings(bound, surface, max_eval=None):
    """Every crossing of BOUND's trajectory (a `Bound`, or None for a member without one) with SURFACE (a grid surface
    read with `client.read_data`, or its normalized data): {'crossings', 'rows', 'coverage', 'evaluations',
    'edge_intervals', 'refusal': None}. Refuses, with the geometry's sentence, a surface the member cannot be placed
    against (details reason "geometry:<key>")."""
    data = surface.data if hasattr(surface, 'data') else surface
    if not isinstance(data, dict) or not isinstance(data.get('context'), dict) or 'values' not in data:
        raise Refused('Give the surface as read with client.read_data (a regular grid surface).')
    if data['context'].get('type', 'regular-grid-surface') != 'regular-grid-surface':
        raise Refused('Crossings are computed against a regular grid surface only.')
    module = geometry.contract()
    if bound is None: return module.crossings(None, None, data)
    result = module.crossings(_survey(bound.trajectory), bound.frame, data, **({} if max_eval is None else {'max_eval': max_eval}))
    if result['refusal'] is not None:
        raise Refused(module.REFUSALS[result['refusal']], details={'reason': 'geometry:' + result['refusal']})
    return result


def nearest(result, md):
    """The crossing of RESULT nearest measured depth MD (the shallower on an exact tie): {'index', 'crossing', 'reason':
    None}; or {'index': None, 'crossing': None, 'reason': <the REASONS key that blocks the choice>}."""
    return geometry.contract().nearest(result, md)


def reasons():
    """{key: sentence} for every reason a crossing is not given ({a} and {b} are measured depths)."""
    return dict(geometry.contract().REASONS)
