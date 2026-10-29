"""ophiolite.trajectory-geometry/1 (E119a C1; E110 D11): the trajectory geometry the Platform and the SDK share, one
standard-library module loaded from its source text on both sides (the Platform from `contracts/geometry/v1/`, the
SDK from its byte-identical contract snapshot). It imports nothing but `math`; a test holds its import set to that
literal.

`minimum_curvature`, `doglegs_readable`, `interpolate` and `gate` are E110's (moved unchanged from the Platform's
`trajectory_geometry.py`, which now loads this file): `minimum_curvature` gives each station's offsets from the first,
`interpolate` places measured depths along a survey's own arc (within a segment the tangent turns on the great circle
between the two station tangents), and `gate` is the frame and datum rule of `trajectory-compare/1`. `interpolate`'s
`limit=False` leaves out the 179.9 degree dogleg refusal, for the SDK's older calls that never refused (4-13).

`place` (E119a D5 to D7) puts a well set member's trajectory in its surface's world: x and y in the frame's projected
coordinate system, z the depth below the frame's datum in metres, positive down. Each azimuth gets the frame's
`rotation_deg` added (survey north to the map grid), the start is the wellhead or the frame's tie-in, and a surface
value times `surface_sign` is a depth below the same datum. A trajectory, frame or surface it cannot place is refused
with one key of `REFUSALS`; the keys `gate` already names are `gate`'s. `offset_bound` is the largest distance between
a segment's arc and its chord.

`crossings` (E119a D8, with 5-5 and 5-9) gives every crossing of a placed trajectory with a regular grid surface that it
can prove, each bracketed to 0.01 m in measured depth, or the rows that say why a crossing is not given, one key of
`REASONS` each; `nearest` picks a crossing only when nothing blocks the choice. See README.md."""
import math

DOGLEG_LIMIT = 179.9  # degrees; a segment turning further has no defined arc (antipodal tangents): unreadable
DEPTH_UNITS = ('m', 'ft')


class Unreadable(ValueError):
    """A survey whose arc is not defined (a dogleg beyond DOGLEG_LIMIT)."""


def minimum_curvature(stations):
    """[(east, north, tvd)] offsets of each station from the first, by minimum curvature (angles in degrees)."""
    import math
    out, e, n, v = [(0.0, 0.0, 0.0)], 0.0, 0.0, 0.0
    for s1, s2 in zip(stations, stations[1:]):
        i1, i2, a1, a2 = (math.radians(s1['inclination']), math.radians(s2['inclination']), math.radians(s1['azimuth']), math.radians(s2['azimuth']))
        cos_beta = math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1))
        beta = math.acos(max(-1.0, min(1.0, cos_beta)))
        ratio = 1.0 if beta < 1e-9 else 2 / beta * math.tan(beta / 2)
        half = (s2['md'] - s1['md']) / 2 * ratio
        n += half * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2))
        e += half * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2))
        v += half * (math.cos(i1) + math.cos(i2))
        out.append((e, n, v))
    return out


def _tangent(station):
    """The unit tangent (east, north, down) of a station."""
    i, a = math.radians(station['inclination']), math.radians(station['azimuth'])
    return (math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), math.cos(i))


def _angle(t1, t2):
    return math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(t1, t2)))))


def doglegs_readable(stations):
    """Refuse (Unreadable) a survey with a segment turning more than DOGLEG_LIMIT degrees; 179.9 itself is readable."""
    for s1, s2 in zip(stations, stations[1:]):
        if round(math.degrees(_angle(_tangent(s1), _tangent(s2))), 9) > DOGLEG_LIMIT: raise Unreadable('dogleg')  # 1e-9 degrees: 179.9 stays 179.9


def interpolate(stations, mds, limit=True):
    """[(east, north, tvd) | None]: the position of each measured depth along the survey's own arc, from its first
    station; None past its last station (outside). A depth before the first station is outside too. With `limit`
    (the default) a dogleg beyond DOGLEG_LIMIT is refused (Unreadable); without it the arc is computed as it is."""
    if limit: doglegs_readable(stations)
    knots = minimum_curvature(stations)
    out = []
    for md in mds:
        if md < stations[0]['md'] or md > stations[-1]['md']: out.append(None); continue
        k = next(j for j in range(len(stations) - 1) if md <= stations[j + 1]['md']) if len(stations) > 1 else 0
        s1, p1 = stations[k], knots[k]
        if md == s1['md'] or len(stations) == 1: out.append(p1); continue
        s2 = stations[k + 1]
        if md == s2['md']: out.append(knots[k + 1]); continue  # a station's own depth is its own position
        t1, t2 = _tangent(s1), _tangent(s2)
        beta, length = _angle(t1, t2), md - s1['md']
        f = length / (s2['md'] - s1['md'])
        if beta < 1e-9: tf, ratio = t2, 1.0
        else:
            w1, w2 = math.sin((1 - f) * beta) / math.sin(beta), math.sin(f * beta) / math.sin(beta)
            tf = tuple(w1 * x + w2 * y for x, y in zip(t1, t2))
            ratio = 1.0 if f * beta < 1e-9 else 2 / (f * beta) * math.tan(f * beta / 2)
        out.append(tuple(p + length / 2 * ratio * (x + y) for p, x, y in zip(p1, t1, tf)))
    return out


def _datum(value):
    return (value or '').strip().casefold()


def gate(result, reference, same_grid=False):
    """The first reason two surveys are not compared (D3 (i)-(v)), or None. Each side is a mapping with `depth_unit`,
    `angle_unit`, `azimuth_reference`, `depth_datum` and `stations` ({md, inclination, azimuth, tvd?}); `same_grid`
    says the caller found one known projected CRS for two grid-north surveys."""
    sides = (result, reference)
    if any(s['depth_unit'] not in DEPTH_UNITS or s.get('angle_unit', 'deg') != 'deg' for s in sides): return 'unit_unknown'
    if result['depth_unit'] != reference['depth_unit']: return 'unit_mismatch'
    north = {s['azimuth_reference'] for s in sides}
    if 'magnetic-north' in north: return 'magnetic_north'
    if 'unknown' in north or not north <= {'true-north', 'grid-north'}: return 'azimuth_reference_unknown'
    if len(north) > 1: return 'azimuth_reference_mismatch'
    if north == {'grid-north'} and not same_grid: return 'grid_unknown'
    datums = [_datum(s['depth_datum']) for s in sides]
    if any(d in ('', 'unknown') for d in datums): return 'datum_unknown'
    if datums[0] != datums[1]: return 'datum_mismatch'
    if any(st.get('inclination') is None or st.get('azimuth') is None for s in sides for st in s['stations']): return 'missing_angles'
    for s in sides:
        first = s['stations'][0]
        if first['md'] != 0 or first.get('tvd') not in (None, 0): return 'start_not_at_datum'
    return None


# --- E119a C1 (D5 to D7): a member placed in its surface's world ---------------------------------------------------

TIE_IN_TVD_M = 0.01  # D7: a survey's own first vertical depth may differ from the tie-in's by at most this

# Each refusal of `place`, with the sentence a person reads. The keys `gate` names are `gate`'s (6-16); `place` adds the
# coordinate-system, unit and surface keys and the tie-in keys of D7.
REFUSALS = {  # in the order `refusal` checks them
    'survey_unit': 'The survey is not in metres; positions are placed in metres only.',
    'surface_time': 'The surface is in time, not depth; a trajectory is placed against depth or elevation only.',
    'surface_unit': 'The surface is not in metres; its x, y and values must all be in metres.',
    'surface_vertical': 'The surface does not say whether its values are depths positive down or elevations positive up.',
    'crs_mismatch': "The surface's coordinate system is not the frame's.",
    'magnetic_north': 'The survey is referenced to magnetic north; state it against true north or grid north.',
    'azimuth_reference_unknown': 'The survey does not say which north its azimuths are measured from.',
    'azimuth_reference_mismatch': "The survey's north is not the north the frame says the survey uses.",
    'datum_unknown': 'A depth reference or datum is unknown, so the depths cannot be related.',
    'datum_mismatch': "The survey's depth reference is not the frame's, or the surface's datum is not the frame's datum.",
    'missing_angles': 'A survey station has no inclination or azimuth.',
    'start_negative': 'The survey starts at a negative measured depth.',
    'tie_in_at_zero': 'The frame gives a tie-in, but the survey starts at measured depth 0, at the wellhead.',
    'start_not_at_datum': 'The survey starts at measured depth 0 but gives a vertical depth other than 0 there.',
    'tie_in_missing': 'The survey starts below measured depth 0 and the frame gives no tie-in for its first station.',
    'tie_in_md': "The tie-in's measured depth is not the survey's first station.",
    'tie_in_tvd': "The survey's own vertical depth at its first station differs from the tie-in's by more than 0.01 m.",
    'unreadable': 'A segment of the survey turns more than 179.9 degrees, so its path is not defined.',
}


def _kind(basis):
    return 'true-north' if basis == 'true-north' else 'grid-north'


def refusal(trajectory, frame, surface):
    """The first key of REFUSALS that keeps TRAJECTORY ({'context', 'stations'}) from being placed by FRAME (a well set
    member's frame) against SURFACE (a surface's context), or None."""
    context, stations = trajectory['context'], trajectory['stations']
    if context.get('depth_unit') != 'm' or context.get('angle_unit', 'deg') != 'deg': return 'survey_unit'
    if surface.get('z_meaning') == 'time': return 'surface_time'
    if surface.get('xy_unit') != 'm' or surface.get('z_unit') != 'm': return 'surface_unit'
    if (surface.get('z_meaning'), surface.get('positive')) not in (('depth', 'down'), ('elevation', 'up')): return 'surface_vertical'
    if surface.get('crs') != frame['crs']: return 'crs_mismatch'
    north = context.get('azimuth_reference')
    if north == 'magnetic-north': return 'magnetic_north'
    if north not in ('true-north', 'grid-north'): return 'azimuth_reference_unknown'
    if north != _kind(frame['north']['survey_basis']): return 'azimuth_reference_mismatch'
    reference = frame['depth_reference']
    pairs = [(context.get('depth_datum'), reference['name']), (surface.get('vertical_datum'), reference['datum'])]
    if any(_datum(d) in ('', 'unknown') for pair in pairs for d in pair): return 'datum_unknown'
    if any(_datum(a) != _datum(b) for a, b in pairs): return 'datum_mismatch'
    if any(s.get('inclination') is None or s.get('azimuth') is None for s in stations): return 'missing_angles'
    first, tie_in = stations[0], frame.get('tie_in')
    if first['md'] < 0: return 'start_negative'
    if first['md'] == 0:
        if tie_in is not None: return 'tie_in_at_zero'
        if first.get('tvd') not in (None, 0): return 'start_not_at_datum'
    else:
        if tie_in is None: return 'tie_in_missing'
        if tie_in['md'] != first['md']: return 'tie_in_md'
        if first.get('tvd') is not None and abs(first['tvd'] - tie_in['tvd']) > TIE_IN_TVD_M: return 'tie_in_tvd'
    try: doglegs_readable(stations)
    except Unreadable: return 'unreadable'
    return None


def _turned(trajectory, frame):
    """The stations with each azimuth turned by the frame's rotation, and the world point (x, y, z) of the first."""
    rotation = frame['north']['rotation_deg']
    turned = [dict(s, azimuth=s['azimuth'] + rotation) for s in trajectory['stations']]
    tie_in = frame.get('tie_in')
    east, north, tvd = (tie_in['east'], tie_in['north'], tie_in['tvd']) if tie_in is not None else (0.0, 0.0, 0.0)
    r = math.radians(rotation)
    east, north = east * math.cos(r) + north * math.sin(r), north * math.cos(r) - east * math.sin(r)
    return turned, (frame['wellhead']['x'] + east, frame['wellhead']['y'] + north, tvd - frame['depth_reference']['elevation'])


def place(trajectory, frame, surface, mds=()):
    """TRAJECTORY placed in SURFACE's world by FRAME (D5 to D7), or refused.

    Refused: {'reason': <a key of REFUSALS>}. Placed: {'reason': None, 'stations': [(md, x, y, z)] per station,
    'positions': [(x, y, z) | None] per depth in MDS (None outside the survey), 'surface_sign': 1 | -1}. x and y are in
    the frame's coordinate system: the wellhead plus the offsets, each azimuth turned by `rotation_deg` from the survey's
    north to the grid. z is the depth below the frame's datum, positive down: the vertical depth from the depth reference
    minus the reference's elevation above the datum. The start is the wellhead at measured depth 0, or the tie-in's
    (east, north, tvd) at the first station, turned like the stations. A surface value times `surface_sign` is a depth
    below the same datum ((depth, down) gives 1, (elevation, up) gives -1)."""
    reason = refusal(trajectory, frame, surface)
    if reason is not None: return {'reason': reason}
    turned, (x0, y0, z0) = _turned(trajectory, frame)
    world = lambda p: (x0 + p[0], y0 + p[1], z0 + p[2])  # noqa: E731
    knots = minimum_curvature(turned)
    return {'reason': None, 'stations': [(s['md'], *world(p)) for s, p in zip(turned, knots)],
            'positions': [None if p is None else world(p) for p in interpolate(turned, mds)],
            'surface_sign': 1 if surface['z_meaning'] == 'depth' else -1}


def offset_bound(dogleg, length):
    """The largest distance in metres between a segment's circular arc, LENGTH metres long and turning DOGLEG degrees,
    and its chord: the sagitta R(1 - cos(theta/2)) with R = length/theta, written 2 length sin^2(theta/4)/theta so that
    a straight segment gives 0."""
    theta = math.radians(abs(dogleg))
    if theta == 0: return 0.0
    return 2 * length * math.sin(theta / 4) ** 2 / theta


# --- E119a C4 (D8, amended by 5-5, 5-9): where the placed trajectory meets a grid surface ------------------------

STEP_M = 1.0  # the first intervals: at most this long, between stations and whole multiples of it
BOUND_M = 0.01  # a crossing's bracket, and the band a proximity claim is about
MAX_EVAL = 2 ** 20  # evaluations of f per wellbore; past it every unclassified interval is uncertain
W_MIN = 0.001  # 5-5: a root-free interval this narrow that is neither near nor outside the band is an edge interval
MERGE_M = 1e-9  # 5-9: two candidates this close are one root, owned by the shallower interval

# The reasons a crossing is not given, one sentence each ({a}, {b}: measured depths in metres). E119b copies the keys.
REASONS = {
    'grazing': 'The path comes within 0.01 m of the surface from about {a} m to about {b} m; no crossing is proven.',
    'along-surface': 'The path runs within 0.01 m of the surface from about {a} m to about {b} m; no crossing is proven.',
    'uncertain': 'A crossing is possible between {a} m and {b} m but could not be proven.',
    'no-surface-data': 'The surface has no data on the path between {a} m and {b} m.',
    'ends-above': 'The path ends above the surface and never crosses it.',
    'starts-below': 'The path starts below the surface and never crosses it.',
    'no-trajectory': 'The wellbore has no trajectory, so there is nothing to intersect.',
}
COVERAGE_UNCERTAIN = "The surface's coverage could not be proven near {a} m."  # an `uncertain` row of a disc at its limit


class _Path:
    """The placed survey on its own arc: per segment the start point, the two tangents, the dogleg and the length."""

    def __init__(self, trajectory, frame):
        turned, (x0, y0, z0) = _turned(trajectory, frame)
        knots = [(x0 + e, y0 + n, z0 + v) for e, n, v in minimum_curvature(turned)]
        self.mds = [s['md'] for s in turned]
        self.segments = []
        for k, (s1, s2) in enumerate(zip(turned, turned[1:])):
            t1, t2 = _tangent(s1), _tangent(s2)
            self.segments.append((s1['md'], s2['md'], knots[k], knots[k + 1], t1, t2, _angle(t1, t2)))

    def at(self, k, md):
        """(point, unit tangent, dogleg rate) at MD on segment K, as `interpolate` places it."""
        md1, md2, p1, p2, t1, t2, beta = self.segments[k]
        length = md - md1
        if beta < 1e-9: tf, ratio, rate = t2, 1.0, 0.0
        else:
            f = length / (md2 - md1)
            w1, w2 = math.sin((1 - f) * beta) / math.sin(beta), math.sin(f * beta) / math.sin(beta)
            tf = tuple(w1 * x + w2 * y for x, y in zip(t1, t2))
            ratio, rate = 1.0 if f * beta < 1e-9 else 2 / (f * beta) * math.tan(f * beta / 2), beta / (md2 - md1)
        if md == md1: point = p1
        elif md == md2: point = p2
        else: point = tuple(p + length / 2 * ratio * (x + y) for p, x, y in zip(p1, t1, tf))
        return point, tf, rate


class _Grid:
    """The bilinear surface over the grid's nodes (row 0 northmost), as a depth below the frame's datum (`sign`)."""

    def __init__(self, grid):
        c, values = grid['context'], grid['values']
        self.ncols, self.nrows, self.h = c['ncols'], c['nrows'], float(c['cell_size'])
        self.x0, self.y0 = c['x_first_center'], c['y_first_center']
        self.sign = 1 if c.get('z_meaning') == 'depth' else -1
        nodata = grid.get('nodata_value')
        ok = lambda v: v is not None and math.isfinite(v) and v != nodata  # noqa: E731
        self.z = [self.sign * v if ok(v) else None for v in values]
        self.east, self.south = self.x0 + (self.ncols - 1) * self.h, self.y0 - (self.nrows - 1) * self.h

    def node(self, i, j):
        return self.z[i * self.ncols + j]

    def corners(self, i, j):
        """(NW, NE, SW, SE) of cell (i, j), or None when one is missing."""
        found = (self.node(i, j), self.node(i, j + 1), self.node(i + 1, j), self.node(i + 1, j + 1))
        return None if any(v is None for v in found) else found

    def locate(self, x, y):
        """(i, j, s, t) of the cell holding (x, y) (s east, t south, from 0 to 1), or None outside the cells."""
        if self.ncols < 2 or self.nrows < 2: return None
        u, v = (x - self.x0) / self.h, (self.y0 - y) / self.h
        if not (0 <= u <= self.ncols - 1 and 0 <= v <= self.nrows - 1): return None
        j, i = min(int(u), self.ncols - 2), min(int(v), self.nrows - 2)
        return i, j, u - j, v - i

    def gradient(self, corners, s, t):
        nw, ne, sw, se = corners
        return (((ne - nw) * (1 - t) + (se - sw) * t) / self.h, -((sw - nw) * (1 - s) + (se - ne) * s) / self.h)

    def value(self, corners, s, t):
        nw, ne, sw, se = corners
        return nw * (1 - s) * (1 - t) + ne * s * (1 - t) + sw * (1 - s) * t + se * s * t

    def disc(self, x, y, r):
        """The corner gradients of every cell meeting the open disc of radius R around (x, y), or None when the disc
        reaches a cell with a missing corner or beyond the cells."""
        if self.ncols < 2 or self.nrows < 2 or x - r < self.x0 or x + r > self.east or y + r > self.y0 or y - r < self.south: return None
        found = []
        for i in range(max(0, int((self.y0 - y - r) / self.h)), min(self.nrows - 2, int((self.y0 - y + r) / self.h)) + 1):
            for j in range(max(0, int((x - r - self.x0) / self.h)), min(self.ncols - 2, int((x + r - self.x0) / self.h)) + 1):
                left, top = self.x0 + j * self.h, self.y0 - i * self.h
                dx, dy = max(left - x, 0.0, x - left - self.h), max(y - top, 0.0, top - self.h - y)
                if dx * dx + dy * dy >= r * r: continue  # touching the rim only: no point of the path is inside the cell
                corners = self.corners(i, j)
                if corners is None: return None
                found.extend(self.gradient(corners, s, t) for s in (0, 1) for t in (0, 1))
        return found


def _search(trajectory, frame, grid, max_eval=MAX_EVAL):
    """D8's certified search over the placed TRAJECTORY against GRID ({'context', 'values'}), before candidates merge.

    Intervals are processed in increasing measured depth. Returns {'refusal', 'candidates' (every root found, with the
    interval that found it; a root at a shared endpoint is found by both), 'intervals' ([a, b, kind, root_free, f(c)],
    kind one of crossing, near, edge, outside, uncertain, coverage), 'stop' (None or [last md proven valid, md]),
    'evaluations', 'surface_sign'}."""
    reason = refusal(trajectory, frame, grid['context'])
    if reason is not None: return {'refusal': reason}
    path, surface = _Path(trajectory, frame), _Grid(grid)
    first = []
    for k, (md1, md2) in enumerate(zip(path.mds, path.mds[1:])):
        if md2 <= md1: continue
        cuts = [md1] + [n * STEP_M for n in range(math.floor(md1 / STEP_M) + 1, math.ceil(md2 / STEP_M)) if md1 < n * STEP_M < md2] + [md2]
        first.extend((a, b, k) for a, b in zip(cuts, cuts[1:]))
    stack, out, candidates = first[::-1], [], []
    state = {'evaluations': 0}
    last_valid, stop = path.mds[0], None

    def f(k, md):
        state['evaluations'] += 1
        (x, y, z), _, _ = path.at(k, md)
        where = surface.locate(x, y)
        corners = None if where is None else surface.corners(where[0], where[1])
        return None if corners is None else z - surface.value(corners, where[2], where[3])

    while stack:
        if state['evaluations'] >= max_eval:  # D8 step 4: the cap
            out.extend([a, b, 'uncertain', False, None] for a, b, _ in stack[::-1]); stack = []; break
        a, b, k = stack.pop()
        c, w = (a + b) / 2, b - a
        state['evaluations'] += 1
        (x, y, z), tangent, rate = path.at(k, c)
        where = surface.locate(x, y)
        corners = None if where is None else surface.corners(where[0], where[1])
        if corners is None:  # step 1: the path itself is where the surface has no data
            stop = [last_valid, c]; break
        gradients = surface.disc(x, y, w / 2)
        if gradients is None:  # the disc reaches a hole or the edge: split before any certificate
            if a < c < b: stack.extend([(c, b, k), (a, c, k)])
            else: out.append([a, b, 'coverage', False, None])
            continue
        g = surface.gradient(corners, where[2], where[3])
        big_g = max(math.hypot(gx, gy) for gx, gy in gradients)
        big_d = max(math.hypot(gx - g[0], gy - g[1]) for gx, gy in gradients)
        l1, fc = 1 + big_g, z - surface.value(corners, where[2], where[3])
        slope = tangent[2] - (g[0] * tangent[0] + g[1] * tangent[1])  # f'(c)
        bound = rate * w / 2 * (1 + big_g) + big_d * (math.hypot(tangent[0], tangent[1]) + rate * w / 2)  # B': |f' - f'(c)| <= bound
        reach = min(l1, abs(slope) + bound) * w / 2  # |f - f(c)| on [a, b]: by B (L1), or by B' (|f'| <= |f'(c)| + bound)
        root_free = abs(fc) > reach  # step 2
        if not root_free:
            if abs(slope) > bound:  # strictly monotone on [a, b]
                fa, fb = f(k, a), f(k, b)
                if fa == 0 or fb == 0 or (fa < 0) != (fb < 0):
                    candidates.append(_bisect(f, k, a, b, fa, fb)); out.append([a, b, 'crossing', False, fc]); last_valid = b
                    continue
                root_free = True
        if root_free and abs(fc) - reach > BOUND_M: kind = 'outside'  # step 3: proximity
        elif abs(fc) + reach <= BOUND_M: kind = 'near'
        elif w <= W_MIN: kind = 'edge' if root_free else 'uncertain'  # 5-5
        elif a < c < b: stack.extend([(c, b, k), (a, c, k)]); continue
        else: kind = 'uncertain'
        out.append([a, b, kind, root_free, fc]); last_valid = b
    return {'refusal': None, 'candidates': candidates, 'intervals': out, 'stop': stop,
            'evaluations': state['evaluations'], 'surface_sign': surface.sign}


def _bisect(f, k, a, b, fa, fb):
    """The one root of a monotone interval, bracketed to at most BOUND_M: {'md', 'low', 'high', 'interval'}."""
    found = {'interval': [a, b]}
    if fa == 0 or fb == 0:
        md = a if fa == 0 else b
        return dict(found, md=md, low=md, high=md)
    low, high, flow, fhigh = a, b, fa, fb
    while high - low > BOUND_M:
        mid = (low + high) / 2
        fm = f(k, mid)
        if fm == 0: return dict(found, md=mid, low=mid, high=mid)
        if (fm < 0) == (flow < 0): low, flow = mid, fm
        else: high, fhigh = mid, fm
    md = min(high, max(low, low - flow * (high - low) / (fhigh - flow)))  # the chord within the bracket
    return dict(found, md=md, low=low, high=high)


def _merge(candidates):
    """5-9: candidates within MERGE_M are one crossing, attributed to the shallower interval (found first)."""
    merged = []
    for candidate in sorted(candidates, key=lambda c: (c['md'], c['interval'][0])):
        if merged and candidate['md'] - merged[-1]['md'] <= MERGE_M: continue
        merged.append(candidate)
    return merged


def _row(reason, a=None, b=None, sentence=None):
    text = (sentence or REASONS[reason]).format(a='%.2f' % a if a is not None else '', b='%.2f' % b if b is not None else '')
    return {'reason': reason, 'between': None if a is None else [a, b], 'sentence': text}


def crossings(trajectory, frame, grid, max_eval=MAX_EVAL):
    """Every crossing of TRAJECTORY ({'context', 'stations'} or None), placed by FRAME, with GRID ({'context', 'values'},
    a regular grid surface), or the reasons none can be proved (D8).

    Returns {'refusal': a key of REFUSALS or None, 'crossings': [{'md', 'low', 'high', 'interval'}] in increasing md
    (`high - low` at most BOUND_M), 'rows': [{'reason': a key of REASONS, 'between': [a, b] or None, 'sentence'}],
    'coverage': 'full' (every depth to the end proven), 'partial' or 'none', 'evaluations', 'edge_intervals'}."""
    if trajectory is None:
        return {'refusal': None, 'crossings': [], 'rows': [_row('no-trajectory')], 'coverage': 'none', 'evaluations': 0, 'edge_intervals': 0}
    found = _search(trajectory, frame, grid, max_eval)
    if found['refusal'] is not None:
        return {'refusal': found['refusal'], 'crossings': [], 'rows': [], 'coverage': 'none', 'evaluations': 0, 'edge_intervals': 0}
    intervals, rows = found['intervals'], []
    merged = _merge(found['candidates'])
    i = 0
    while i < len(intervals):
        a, b, kind, root_free, _ = intervals[i]
        j = i
        if kind in ('near', 'edge'):
            while j + 1 < len(intervals) and intervals[j + 1][2] in ('near', 'edge'): j += 1
            near = [iv for iv in intervals[i:j + 1] if iv[2] == 'near']
            if near:
                start, end = near[0][0], near[-1][1]
                touches = (i > 0 and intervals[i - 1][2] == 'crossing') or (j + 1 < len(intervals) and intervals[j + 1][2] == 'crossing')
                if not (touches and all(iv[3] for iv in near) and end - start < STEP_M):  # else the crossing's own approach
                    rows.append(_row('grazing' if end - start < STEP_M else 'along-surface', start, end))
        elif kind in ('uncertain', 'coverage'):
            while j + 1 < len(intervals) and intervals[j + 1][2] == kind: j += 1
            end = intervals[j][1]
            rows.append(_row('uncertain', a, end) if kind == 'uncertain' else _row('uncertain', a, end, COVERAGE_UNCERTAIN))
        i = j + 1
    if found['stop'] is not None: rows.append(_row('no-surface-data', *found['stop']))
    full = found['stop'] is None and not any(r['reason'] == 'uncertain' for r in rows)
    if not merged and full and all(iv[3] for iv in intervals if iv[2] != 'outside') and intervals:
        rows.append(_row('starts-below' if intervals[0][4] > 0 else 'ends-above'))  # every interval to the end: no root
    public = [{'md': c['md'], 'low': c['low'], 'high': c['high'], 'interval': c['interval']} for c in merged]
    return {'refusal': None, 'crossings': public, 'rows': rows, 'coverage': 'full' if full else 'partial',
            'evaluations': found['evaluations'], 'edge_intervals': sum(1 for iv in intervals if iv[2] == 'edge')}


def nearest(result, md):
    """The crossing of RESULT (from `crossings`) nearest measured depth MD, the shallower on an exact tie: {'index',
    'crossing', 'reason': None}; or {'index': None, 'crossing': None, 'reason': <the key that blocks a choice>}. It
    picks only with full coverage and no `uncertain`, `grazing` or `along-surface` row."""
    blocked = lambda reason: {'index': None, 'crossing': None, 'reason': reason}  # noqa: E731
    if result.get('refusal'): return blocked(result['refusal'])
    if result['coverage'] != 'full':
        return blocked(next((r['reason'] for r in result['rows'] if r['reason'] in ('no-surface-data', 'uncertain', 'no-trajectory')), 'uncertain'))
    for row in result['rows']:
        if row['reason'] in ('uncertain', 'grazing', 'along-surface'): return blocked(row['reason'])
    if not result['crossings']: return blocked(result['rows'][0]['reason'] if result['rows'] else 'uncertain')
    index = min(range(len(result['crossings'])), key=lambda n: (abs(result['crossings'][n]['md'] - md), result['crossings'][n]['md']))
    return {'index': index, 'crossing': result['crossings'][index], 'reason': None}
