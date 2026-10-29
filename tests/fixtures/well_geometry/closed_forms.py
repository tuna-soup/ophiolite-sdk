"""E119a C4: the analytic intersection fixtures and their hand values, from closed forms only.

Standard library, and independent of the product: nothing here imports `ophiolite` or the geometry contract. Each case
states the closed form its expected values come from; where the closed form is an equation with no explicit solution
(the build, the turn into the steep cell, the arc of the near miss) its one root is found here by bisecting the
closed-form expression itself to 1e-12 m. `python closed_forms.py` writes each surface and `cases.json` beside this file
and the contract's `fixtures/crossings.json`; `test_intersection.py` checks that every one equals what this file
computes.

Common to every case: EPSG:23031, depth reference `KB` 7.5 m above `NAP`, survey azimuths on the grid (rotation 0),
z the depth below NAP (positive down) = tvd - 7.5. f(md) = z(md) - S(x, y), S the surface's depth below NAP."""
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CONTRACT = HERE.parents[3] / 'ophiolite-platform' / 'contracts' / 'geometry' / 'v1' / 'fixtures' / 'crossings.json'
SIN, COS, TAN = (lambda d: math.sin(math.radians(d))), (lambda d: math.cos(math.radians(d))), (lambda d: math.tan(math.radians(d)))
WELLHEAD = (600000.0, 5900000.0)
ELEVATION = 7.5
SLOPE = TAN(5)  # the 5 degree slope: the surface deepens to the east by tan 5 per metre


def root(g, low, high):
    """The one root of the closed form G in [LOW, HIGH] (opposite signs), to 1e-12 m."""
    glow = g(low)
    assert glow * g(high) < 0, (low, high)
    while high - low > 1e-12:
        mid = (low + high) / 2
        if (g(mid) < 0) == (glow < 0): low, glow = mid, g(mid)
        else: high = mid
    return (low + high) / 2


def station(md, inclination, azimuth):
    return {'md': md, 'inclination': inclination, 'azimuth': azimuth, 'tvd': None}


def trajectory(*stations):
    return {'context': {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
            'stations': list(stations)}


def frame(x=WELLHEAD[0], y=WELLHEAD[1], tie_in=None):
    return {'crs': 'EPSG:23031', 'wellhead': {'x': x, 'y': y}, 'depth_reference': {'name': 'KB', 'elevation': ELEVATION, 'datum': 'NAP'},
            'north': {'survey_basis': 'grid:EPSG:23031', 'rotation_deg': 0}, 'tie_in': tie_in, 'source': 'closed form'}


def grid(x0, y0, h, ncols, nrows, depth, elevation=False, missing=()):
    """A regular grid surface (normalized data) with node (i, j) at (x0 + j h, y0 - i h) and value DEPTH(x, y) (a depth
    below NAP), stored as an elevation (the negative) when ELEVATION; nodes in MISSING have no value."""
    values = []
    for i in range(nrows):
        for j in range(ncols):
            d = None if (i, j) in missing else depth(x0 + j * h, y0 - i * h)
            values.append(None if d is None else (-d if elevation else d))
    context = {'type': 'regular-grid-surface', 'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm',
               'z_meaning': 'elevation' if elevation else 'depth', 'positive': 'up' if elevation else 'down', 'vertical_datum': 'NAP',
               'registration': 'center', 'row_order': 'north-to-south', 'ncols': ncols, 'nrows': nrows, 'cell_size': h,
               'x_first_center': x0, 'y_first_center': y0, 'missing_count': len(missing)}
    return {'context': context, 'values': values, 'nodata_value': None}


def slope_depth(x, y): return 1192.5 + SLOPE * (x - WELLHEAD[0])


# The surfaces. Node rows run north to south.
SLOPE_GRID = dict(x0=599000.0, y0=5901000.0, h=100.0, ncols=21, nrows=21)  # the wellhead node is (10, 10), depth 1192.5
HOLES = ((8, 15), (6, 17))  # nodes (600500, 5900200) and (600700, 5900400): the four cells around each have no data
FOLD_A = 550.0  # the fold's crest: S = 550 + |x - 601000| (flanks of 45 degrees), stored as an elevation
FLAT = 1000.0


def horizontal(nodes_f, x0, h, ncols, z=-ELEVATION, nrows=3):
    """A surface for a horizontal path at depth Z heading east from the wellhead: f at node j is NODES_F(j), so the
    surface's depth there is z - f, constant north to south (NROWS rows, odd, centred on the path)."""
    return grid(x0, WELLHEAD[1] + nrows // 2 * h, h, ncols, nrows, lambda x, y: z - nodes_f(round((x - x0) / h)))


EAST = trajectory(station(0, 90, 90), station(10, 90, 90))  # horizontal, east, md = x - 600000


def cases():
    out = []

    def case(name, test, closed_form, survey, frame_, surface, crossings=(), reasons=(), between=None, extra=None):
        out.append(dict({'name': name, 'test': test, 'closed_form': closed_form, 'trajectory': survey, 'frame': frame_, 'surface': surface,
                         'crossings': list(crossings), 'reasons': list(reasons), 'between': between}, **(extra or {})))

    slope = 'slope-5deg'
    vertical = trajectory(station(0, 0, 0), station(2000, 0, 0))
    case('vertical, 30 m east of a node', 1, 'z = md - 7.5 = 1192.5 + 30 tan 5: md = 1200 + 30 tan 5', vertical, frame(WELLHEAD[0] + 30),
         slope, [1200 + 30 * SLOPE])
    slant = 1200 / (COS(30) - SLOPE * SIN(30) * SIN(60))
    case('slant 30 degrees, azimuth 60', 1, 'md cos 30 - 7.5 = 1192.5 + tan 5 md sin 30 sin 60', trajectory(station(0, 30, 60), station(2000, 30, 60)),
         frame(), slope, [slant])
    r, kop = 30 / math.radians(10), 1156.0  # the build: 10 degrees per 30 m from a kick-off at md 1156, azimuth 120
    build = kop + root(lambda s: kop - ELEVATION + r * math.sin(s / r) - 1192.5 - SLOPE * SIN(120) * r * (1 - math.cos(s / r)), 30, 60)
    case('build 10 degrees per 30 m, azimuth 120', 2,
         'R = 30/rad(10); s = md - 1156: 1148.5 + R sin(s/R) = 1192.5 + tan 5 sin 120 R (1 - cos(s/R)), on the segment from 1186 to 1216',
         trajectory(station(0, 0, 120), station(kop, 0, 120), *[station(kop + 30 * k, 10 * k, 120) for k in range(1, 5)], station(kop + 300, 40, 120)),
         frame(), slope, [build])
    fold_c = 1000 / SIN(60)
    case('fold: a slant through a crest', 3,
         'z = md cos 60 - 7.5, x = 600000 + md sin 60; S = 550 + |x - 601000|: md = 1007.5 + 550 over (cos 60 + sin 60), and (992.5 - 550) over (sin 60 - cos 60)',
         trajectory(station(0, 60, 90), station(1400, 60, 90)), frame(), 'fold',
         [(1007.5 + FOLD_A) / (COS(60) + SIN(60)), (992.5 - FOLD_A) / (SIN(60) - COS(60))], extra={'crest_md': fold_c})
    case('three roots in one first interval', 4, 'f alternates -0.05, +0.05 at nodes 0.3 m apart: roots at the midpoints 4.9, 5.2, 5.5, 5.8',
         EAST, frame(), 'three-roots', [4.9, 5.2, 5.5, 5.8])
    d_a, d_b = 0.0125 / 0.975, 0.00125 / 0.9975
    case('roots 0.05 m apart', 5, 'f = 0.5 at every node but -d at x = 600005.41 (1 m nodes): roots at 5.41 -/+ d/(0.5 + d) = 5.385, 5.435',
         EAST, frame(), 'close-0.05', [5.41 - d_a / (0.5 + d_a), 5.41 + d_a / (0.5 + d_a)])
    case('roots 0.005 m apart', 5, 'as above with d/(0.5 + d) = 0.0025: roots 5.4075, 5.4125 (two crossings, or a grazing or uncertain row; never one)',
         EAST, frame(), 'close-0.005', [5.41 - d_b / (0.5 + d_b), 5.41 + d_b / (0.5 + d_b)])
    case('near miss at 0.008 m', 6, 'f = 0.008 + 0.492 |x - 600005.41|: within 0.01 m for |md - 5.41| <= 0.002/0.492',
         EAST, frame(), 'near-miss', [], ['grazing', 'starts-below'], [5.41 - 0.002 / 0.492, 5.41 + 0.002 / 0.492])
    case('midpoint 0.0099 m, ends 0.012 m', 7,
         'f = 0.0099 + |md - t|, t = 5.5 + 1/512: 0.0099 at the middle of [5.5, 5.5 + 1/256] and 0.01185 at its ends; within 0.01 m only for |md - t| <= 0.0001, narrower than W_MIN, so never certified near',
         EAST, frame(), 'proximity', [], ['starts-below'])
    case('parallel at 0.008 m over 3 m', 8, 'f = 0.008 for x in [600004, 600007], 0.5 at the other nodes: within 0.01 m for md in [4 - 0.002/0.492, 7 + 0.002/0.492]',
         EAST, frame(), 'parallel', [], ['along-surface', 'starts-below'], [4 - 0.002 / 0.492, 7 + 0.002 / 0.492])
    case('a 2 m near run beside a crossing', 'absorption',
         'f = -0.5 at x = 600003, 0.008 at 600004 to 600006, 0.5 at 600007: one crossing at 3 + 0.5/0.508 (the monotone interval [3, 4]); '
         'f stays within 0.01 m from there to 6 + 0.002/0.492, a root-free near run from the crossing interval\'s end 4 that is longer than STEP_M, so it stays a row (D8 step 3, amended at slice 3)',
         EAST, frame(), 'approach-long', [3 + 0.5 / 0.508], ['along-surface'], [4.0, 6 + 0.002 / 0.492])
    zero = 1e-6 / COS(87.7)
    case('near zero at the stations, 0.3 m between', 9,
         'tie-in md 990 at tvd 1000; inclination 87.7 to md 1000, an arc to 92.3 at md 1030 (sagitta 0.301 m), then straight: the flat surface is 1e-6 m above z(1000) = z(1030); crossings at 1000 - 1e-6/cos 87.7 and 1030 + 1e-6/cos 87.7',
         trajectory(station(990, 87.7, 90), station(1000, 87.7, 90), station(1030, 92.3, 90), station(1040, 92.3, 90)),
         frame(tie_in={'md': 990, 'tvd': 1000, 'east': 0, 'north': 0}), 'near-zero', [1000 - zero, 1030 + zero])
    m1 = 1000.5 - math.pi / 4  # the turn: horizontal, radius 1 m, azimuth 45 to 315 between m1 and m1 + pi/2; its apex md 1000.5
    psi = math.acos(math.cos(0.5) + 0.015)
    case('arc into a steep neighbour cell', 10,
         'horizontal turn of radius 1 m, apex at md 1000.5 where x = Cx + 1; x = Cx + cos(md - 1000.5); the cell column at Cx + cos 0.5 + 0.01 changes the gradient from 1 to 10; f = 0.05 - 10 (x - column) east of it: crossings at 1000.5 -/+ acos(cos 0.5 + 0.015)',
         trajectory(station(990, 90, 45), station(m1, 90, 45), station(m1 + math.pi / 2, 90, 315), station(1010, 90, 315)),
         frame(tie_in={'md': 990, 'tvd': 1000, 'east': 0, 'north': 0}), 'steep-neighbour', [1000.5 - psi, 1000.5 + psi])
    hx, hy = hole_wellhead()
    crossing = (1200 + SLOPE * (hx - WELLHEAD[0])) / (COS(30) - SLOPE * SIN(30) * SIN(60))
    entry = (600600 - hx) / (SIN(30) * SIN(60))  # the west edge of the second hole's cells; y there is inside them
    case('disc touches a hole the path never enters', 11,
         'slant 30, azimuth 60, passing 0.3 m north-west of the corner (600400, 5900300) of the first hole at md 1000; crossing as the slant',
         trajectory(station(0, 30, 60), station(1455, 30, 60)), frame(hx, hy), 'hole', [crossing])
    case('path enters a hole', 12, 'as test 11 to md 1600: no surface data from x = 600600, md = (600600 - x0)/(sin 30 sin 60)',
         trajectory(station(0, 30, 60), station(1600, 30, 60)), frame(hx, hy), 'hole', [crossing], ['no-surface-data'], extra={'entry_md': entry})
    case('root at a grid corner on a first-interval end', 13, 'vertical at the node of depth 1192.5: md 1200.000', vertical, frame(), slope, [1200.0])
    case('wholly above', 14, 'vertical to md 1000: z <= 992.5 < 1192.5', trajectory(station(0, 0, 0), station(1000, 0, 0)), frame(), slope, [], ['ends-above'])
    case('wholly below', 14, 'vertical from a tie-in at md 1300, tvd 1300: z >= 1292.5 > 1192.5', trajectory(station(1300, 0, 0), station(2000, 0, 0)),
         frame(tie_in={'md': 1300, 'tvd': 1300, 'east': 0, 'north': 0}), slope, [], ['starts-below'])
    case('one-row grid', 15, 'no cell', vertical, frame(), 'one-row', [], ['no-surface-data'], [0.0, 0.5])
    case('one-column grid', 15, 'no cell', vertical, frame(), 'one-column', [], ['no-surface-data'], [0.0, 0.5])
    theta_a, kappa, band = 90 - math.degrees(0.01 * (1203.37 + 100 * math.acos(1 - 0.001 / 100) - 1190)), 0.01, 100 * math.acos(1 - 0.001 / 100)
    m90 = 1203.37 + band
    case('smooth near miss with its band edge at md 1203.37', 18,
         'tie-in md 1100 at tvd 1100; straight at inclination 90 - deg(0.01 (m90 - 1190)) to md 1190, an arc of radius 100 m (0.01 rad/m) through 90 degrees at m90 = 1203.37 + 100 acos(1 - 0.001/100) to md 1220, then straight; the flat surface is 0.009 m below the arc\'s deepest point: |f| <= 0.01 exactly for md in [1203.37, 1203.37 + 2 (m90 - 1203.37)]',
         trajectory(station(1100, theta_a, 90), station(1190, theta_a, 90), station(1220, 90 + math.degrees(kappa * (1220 - m90)), 90), station(1240, 90 + math.degrees(kappa * (1220 - m90)), 90)),
         frame(tie_in={'md': 1100, 'tvd': 1100, 'east': 0, 'north': 0}), 'near-miss-smooth', [], ['grazing', 'ends-above'], [1203.37, 1203.37 + 2 * band])
    return out


def hole_wellhead():
    """The slant's wellhead: 500 m (md 1000) south-west along azimuth 60 of the point 0.3 m north-west of the corner."""
    qx, qy = 600400 - 0.3 * COS(60), 5900300 + 0.3 * SIN(60)
    return qx - 500 * SIN(60), qy - 500 * COS(60)


def surfaces():
    """The named surfaces of the cases."""
    near18_z = 1100 - ELEVATION + 90 * COS(near18_theta()) + (1 - SIN(near18_theta())) / 0.01 + 0.009
    zero_z = 1000 - ELEVATION + 10 * COS(87.7) - 1e-6
    m1 = 1000.5 - math.pi / 4
    p1 = (WELLHEAD[0] + (m1 - 990) * SIN(45), WELLHEAD[1] + (m1 - 990) * COS(45))
    column = p1[0] - COS(45) + math.cos(0.5) + 0.01  # centre x = p1 x - cos 45 (radius 1, to the left of azimuth 45)
    d_a, d_b = 0.0125 / 0.975, 0.00125 / 0.9975
    return {
        'slope-5deg': grid(**SLOPE_GRID, depth=slope_depth),
        'hole': grid(**SLOPE_GRID, depth=slope_depth, missing=HOLES),
        'fold': grid(599500.0, 5900100.0, 50.0, 41, 5, lambda x, y: FOLD_A + abs(x - 601000), elevation=True),
        'three-roots': horizontal(lambda j: {27: 0.05, 28: -0.05, 29: 0.05}.get(j, -0.05), 599996.95, 0.3, 50, nrows=7),  # +-0.9 m: the disc of [5, 6] fits
        'close-0.05': horizontal(lambda j: -d_a if j == 9 else 0.5, 599996.41, 1.0, 16),
        'close-0.005': horizontal(lambda j: -d_b if j == 9 else 0.5, 599996.41, 1.0, 16),
        'near-miss': horizontal(lambda j: 0.008 if j == 9 else 0.5, 599996.41, 1.0, 16),
        'proximity': horizontal(lambda j: 0.0099 + abs(j - 9), 600005.5 + 1 / 512 - 9, 1.0, 16),
        'parallel': horizontal(lambda j: 0.008 if 8 <= j <= 11 else 0.5, 599996.0, 1.0, 16),
        'approach-long': horizontal(lambda j: -0.5 if j <= 7 else (0.008 if j <= 10 else 0.5), 599996.0, 1.0, 16),
        'near-zero': grid(**SLOPE_GRID, depth=lambda x, y: zero_z),
        'steep-neighbour': grid(column - 12, WELLHEAD[1] + 20, 1.0, 16, 26,
                                lambda x, y: (1000 - ELEVATION) - (0.05 + (column - x) if x <= column else 0.05 - 10 * (x - column))),
        'one-row': grid(599800.0, 5900000.0, 100.0, 5, 1, slope_depth),
        'one-column': grid(600000.0, 5900200.0, 100.0, 1, 5, slope_depth),
        'near-miss-smooth': grid(**SLOPE_GRID, depth=lambda x, y: near18_z),
    }


def near18_theta():
    return 90 - math.degrees(0.01 * (1203.37 + 100 * math.acos(1 - 0.001 / 100) - 1190))


def document():
    return {'schema': 'ophiolite.trajectory-geometry-fixture/1',
            'note': 'E119a C4: crossings() against closed forms (ophiolite-sdk/tests/fixtures/well_geometry/closed_forms.py states each). '
                    'Expected measured depths within 0.01 m; `reasons` are the rows in order; `between` the literal ends where a row has them.',
            'surfaces': surfaces(), 'cases': cases()}


def files():
    """{path: text} of everything this file writes: the contract's fixture, and here each surface (`<name>.json`, the
    surface's normalized data) and `cases.json` (each case naming its surface)."""
    dump = lambda value: json.dumps(value, indent=1) + '\n'  # noqa: E731
    out = {CONTRACT: dump(document())}
    for name, surface in surfaces().items(): out[HERE / (name + '.json')] = dump(surface)
    out[HERE / 'cases.json'] = dump({'schema': 'ophiolite.trajectory-geometry-fixture/1', 'note': document()['note'], 'cases': cases()})
    return out


def main():
    for path, text in files().items():
        path.write_text(text, encoding='utf-8')
        print('wrote', path.name, len(text), 'bytes')


if __name__ == '__main__':
    main()
