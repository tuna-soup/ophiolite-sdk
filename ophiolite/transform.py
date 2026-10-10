"""E64: vertical depth from a survey, with a stated origin. Coordinate and unit changes are made by the server
(`transform-preview`, `transform`) so Python and the browser leave the same record; this module adds what needs no
server: depth along a survey by minimum curvature.

`vertical_depth` returns two sources apart and never converts one into the other: `calculated` (minimum curvature
from the survey's angles, interpolated along the arc between stations) and `from_file` (the survey's own vertical depth,
interpolated linearly between stations that state it; a gap where one does not). A start is never assumed: the first
station is at measured depth 0, or the survey states its vertical depth there, or the caller supplies one. Nothing is
extrapolated past the last station, and no datum offset (such as NAP) is applied."""
import math

from .errors import Refused


def _tangent(inclination, azimuth):
    i, a = math.radians(inclination), math.radians(azimuth)
    return (math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), math.cos(i))  # east, north, down


def _angle(t0, t1):
    return math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(t0, t1)))))


def _advance(position, t0, t1, length):
    dogleg = _angle(t0, t1)
    factor = 1.0 if dogleg < 1e-9 else math.tan(dogleg / 2) / (dogleg / 2)
    return tuple(p + length / 2 * (a + b) * factor for p, a, b in zip(position, t0, t1))


def _between(t0, t1, f):
    """The tangent a fraction f along the arc from t0 to t1."""
    dogleg = _angle(t0, t1)
    if dogleg < 1e-9: return t1
    s = math.sin(dogleg)
    return tuple((math.sin((1 - f) * dogleg) * a + math.sin(f * dogleg) * b) / s for a, b in zip(t0, t1))


def vertical_depth(stations, mds, origin_tvd=None, survey_unit='m', log_unit='m'):
    """{'calculated': [...], 'from_file': [...], 'beyond': n, 'notes': [...]} for each measured depth in MDS.

    STATIONS are {'md', 'inclination', 'azimuth'} with an optional 'tvd' (the survey's own). A depth outside the survey
    is None and, past its end, counted in 'beyond'."""
    if survey_unit != log_unit:
        raise Refused('The survey is in %s and the log in %s; change one to match first.' % (survey_unit, log_unit))
    if len(stations) < 2: raise Refused('The survey has one station; vertical depth needs at least two.')
    md = [float(s['md']) for s in stations]
    if any(b <= a for a, b in zip(md, md[1:])): raise Refused('The survey\'s measured depths do not increase, so vertical depth cannot be calculated.')
    if any(s.get('inclination') is None or s.get('azimuth') is None for s in stations):
        raise Refused('A survey station has no inclination or azimuth; the calculation needs every angle.')
    supplied = [s.get('tvd') for s in stations]
    if origin_tvd is not None: start = float(origin_tvd)
    elif supplied[0] is not None: start = float(supplied[0])
    elif md[0] == 0: start = 0.0
    else:
        raise Refused('The survey starts at %g %s and gives no vertical depth there, so its starting depth is not known.'
                      % (md[0], survey_unit))
    tangents = [_tangent(s['inclination'], s['azimuth']) for s in stations]
    positions = [(0.0, 0.0, start)]
    for k in range(1, len(md)):
        positions.append(_advance(positions[-1], tangents[k - 1], tangents[k], md[k] - md[k - 1]))
    notes = ['The survey\'s vertical depth decreases between measured depth %g and %g.' % (md[k - 1], md[k])
             for k in range(1, len(md)) if supplied[k] is not None and supplied[k - 1] is not None and supplied[k] < supplied[k - 1]]
    calculated, from_file, beyond = [], [], 0
    for m in mds:
        if m < md[0] or m > md[-1]:
            beyond += m > md[-1]; calculated.append(None); from_file.append(None); continue
        k = min(next(i for i in range(len(md) - 1, -1, -1) if md[i] <= m), len(md) - 2)
        f = (m - md[k]) / (md[k + 1] - md[k])
        calculated.append(_advance(positions[k], tangents[k], _between(tangents[k], tangents[k + 1], f), m - md[k])[2])
        a, b = supplied[k], supplied[k + 1]
        from_file.append(None if a is None or b is None else a + f * (b - a))
    return {'calculated': calculated, 'from_file': from_file, 'beyond': beyond, 'notes': notes}
