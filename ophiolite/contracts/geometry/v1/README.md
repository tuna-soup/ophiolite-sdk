# Trajectory geometry, version 1 (E110 D11, E119a)

One module holds the trajectory geometry the Platform and the SDK compute with: comparing two surveys
(`trajectory-compare/1`, E110), drawing wellbore paths on the map, and placing a well set member's trajectory in its
surface's world (E119a). This folder holds it.

| File | What it is |
|---|---|
| `trajectory.py` | `ophiolite.trajectory-geometry/1`: `minimum_curvature`, `doglegs_readable`, `interpolate`, `gate` (E110, moved unchanged), `place`, `refusal`, `REFUSALS`, `offset_bound` (E119a slice 2), `crossings`, `nearest`, `REASONS` (E119a slice 3); standard library only (Python 3.10; `math` and nothing else) |
| `fixtures/placement.json` | `place` against closed forms, with the expected world positions (below) |
| `fixtures/crossings.json` | `crossings` against closed forms: the surfaces, the cases and their expected crossings and rows (below) |

**One module, loaded from its source text.** The Platform's `services/project_gateway/trajectory_geometry.py` loads
this file (`compile` + `exec` into a fresh module, as `activity.py` loads `../../procedures/v1/delivery.py`) and
re-exports its names; the SDK's `ophiolite/geometry.py` loads its byte-identical copy from the contract snapshot. The
SDK's `Trajectory.minimum_curvature()` and `transform.vertical_depth` compute through it and give the numbers they gave
before, within 1e-9 m. The Connectors reader keeps its own `minimum_curvature` by ruling R-1 (D4 option a); a Platform
test holds it to this module within 1e-9 m.

**Minimum curvature.** Each station's offsets (east, north, tvd) from the first; angles in degrees. `interpolate`
places a measured depth on the survey's own arc: within a segment the tangent turns along the great circle between
the station tangents. A segment that turns more than 179.9 degrees has no defined arc and is refused (`Unreadable`);
`limit=False` computes it anyway, for the SDK's older calls, which never refused (E119a 4-13).

**Placing a member (`place`, D5 to D7).** Inputs: the trajectory's normalized data (`context`, `stations`), the
member's frame from its well set, and the surface's context. Metres only.
- x = wellhead x + Σ east, y = wellhead y + Σ north, with every azimuth turned by `frame.north.rotation_deg` from the
  survey's north to the frame's grid (for NLOG on a UTM surface: basis `grid:EPSG:28992`, rotation the convergence).
- z is the depth below the frame's datum, positive down: the vertical depth from the depth reference minus the
  reference's `elevation` above `datum`.
- The first station at measured depth 0 is the wellhead. A survey starting deeper needs the frame's `tie_in` at that
  measured depth and starts at its (`east`, `north`, `tvd`); the tie-in's east and north are measured like the
  stations' offsets and turned with them.
- A surface value times `surface_sign` is a depth below the same datum: (`depth`, `down`) gives 1, (`elevation`,
  `up`) gives -1.

`REFUSALS` holds one sentence per key; `refusal` names the first that applies, in this order: `survey_unit` (survey
not in metres and degrees), `surface_time`, `surface_unit` (surface x, y or z not in metres), `surface_vertical`
(neither depth positive down nor elevation positive up), `crs_mismatch` (surface CRS not the frame's),
`magnetic_north`, `azimuth_reference_unknown`, `azimuth_reference_mismatch` (the survey's north is not the frame's
survey basis), `datum_unknown` (a depth reference or datum empty or `unknown`; `unknown` never matches),
`datum_mismatch` (the survey's depth datum is not the frame's depth reference, or the surface's vertical datum is not
the frame's datum; trimmed and case-folded), `missing_angles`, `start_negative`, `tie_in_at_zero`,
`start_not_at_datum` (measured depth 0 with a vertical depth other than 0), `tie_in_missing`, `tie_in_md`,
`tie_in_tvd` (the survey's own first vertical depth more than 0.01 m from the tie-in's) and `unreadable` (a dogleg
beyond 179.9 degrees). The keys `gate` names are `gate`'s.

**The arc and its chord (`offset_bound`).** A segment `length` metres long turning `dogleg` degrees lies on a circle
of radius R = length/θ; its largest distance from the chord is the sagitta R(1 − cos(θ/2)) = 2·length·sin²(θ/4)/θ:
0 for a straight segment, 0.0654 m at 1° per 30 m, 0.6541 m at 10° and 3.8381 m at 60°.

**The placement fixture.** Wellhead (236512.4, 583104.75) in EPSG:28992; depth reference `KB` 7.92 m above `NAP`.
Each case states its closed form; `place` agrees within 0.01 m, at stations and between them.

| Case | Closed form |
|---|---|
| vertical | x, y the wellhead; z = md − 7.92 (surface in depth, positive down) |
| slant 30°, azimuth 60 | x = x0 + md·sin 30·sin 60; y = y0 + md·sin 30·cos 60; z = md·cos 30 − 7.92 |
| build 10° per 30 m, azimuth 120 | R = 30/rad(10); h = R(1 − cos(md/R)); x = x0 + h·sin 120; y = y0 + h·cos 120; z = R·sin(md/R) − 7.92 |
| convergence +1.5° from true north | the slant at grid azimuth 61.5 |
| tie-in at md 25 with (0.11, −0.07) | x = x0 + 0.11; y = y0 − 0.07; z = 24.98 + (md − 25) − 7.92 |
| tie-in turned with the stations, rotation −2° | the tie-in (3.0, −2.0) turned by −2° (east·cos r + north·sin r, north·cos r − east·sin r), then a 30° slant at grid azimuth 43 |

**Where the path meets a grid surface (`crossings`, D8).** Inputs: the trajectory's normalized data (or `None`), the
member's frame and the surface's normalized data (`context`, `values`; row 0 northmost, node (i, j) at
(`x_first_center` + j·`cell_size`, `y_first_center` − i·`cell_size`), a missing value `None`). The surface is bilinear
over each cell of four nodes, and f(md) = z(md) − S(x, y) compares the path on its own arc with the surface's depth below
the same datum (f > 0: the path is below the surface). A grid of one row or one column has no cell.

The search certifies, it does not sample. The first intervals are at most `STEP_M` = 1 m long, cut at the stations and
at whole metres, and are processed in increasing measured depth; each interval [a, b] (width w, middle c) is judged
from f(c), the cells meeting the disc of radius w/2 around the path at c, the largest gradient G over them, the largest
gradient difference D from the gradient at c, and the segment's dogleg rate κ:
1. The path at c in a cell with a missing corner, or outside the cells: `no-surface-data` between the last depth proven
   and c, and the search ends. A disc that reaches such a cell is split before anything is concluded.
2. f changes by at most L·w/2 on the interval, with L the smaller of 1 + G (the bound B) and |f′(c)| + E, where
   E = κw/2·(1 + G) + D·(|T_h(c)| + κw/2) bounds |f′ − f′(c)| (B′). |f(c)| > L·w/2: no root. Otherwise |f′(c)| > E
   makes f strictly monotone: opposite or zero end values give exactly one root, bisected to a bracket of at most
   `BOUND_M` = 0.01 m; equal signs give none.
3. An interval without a proven root is outside the band when |f(c)| − L·w/2 > 0.01 and near when
   |f(c)| + L·w/2 ≤ 0.01. A root-free interval of width at most `W_MIN` = 0.001 m that is neither is an edge interval
   (counted; it extends no run); one not proven root-free at that width is `uncertain`. Anything else is split.
4. After `MAX_EVAL` = 2^20 evaluations every interval left is `uncertain`.

A root at the shared end of two intervals is found by both, and the two candidates (within 1e-9 m) merge into one
crossing owned by the shallower interval. Adjacent near intervals form a run, reported as `grazing` (shorter than 1 m)
or `along-surface`: "within 0.01 m of the surface from about <a> to about <b>". A run that touches a proven crossing,
is all root-free and is shorter than 1 m is that crossing's own approach to the surface and is not reported; a run of
1 m or longer, or one with an interval not proven root-free, stays a row. With no
crossing and every interval root-free the path is `starts-below` or `ends-above`; with no trajectory it is
`no-trajectory`.

`crossings` returns `crossings` ({`md`, `low`, `high`, `interval`}, `high − low` ≤ 0.01, in increasing md), `rows`
({`reason`, `between`, `sentence`}, one key of `REASONS` each), `coverage` (`full` when every depth to the end is
proven), `evaluations` and `edge_intervals`; a trajectory, frame or surface that cannot be placed gives `refusal`, a key
of `REFUSALS`. `nearest(result, md)` picks the crossing nearest md (the shallower on an exact tie) only with full
coverage and no `uncertain`, `grazing` or `along-surface` row; otherwise it names the reason that blocks it.

`REASONS`: `grazing`, `along-surface`, `uncertain`, `no-surface-data`, `ends-above`, `starts-below`, `no-trajectory`.
E119b's residual reasons copy these seven keys.

**The crossings fixture.** Every case states its closed form; the expected depths come from
`ophiolite-sdk/tests/fixtures/well_geometry/closed_forms.py`, which computes them without this module (where the closed
form is an equation, by bisecting the closed form itself). `crossings` agrees within 0.01 m.

| Case (C4 test) | Closed form |
|---|---|
| vertical 30 m east of a node; slant 30°, azimuth 60 (1) | the 5° slope S = 1192.5 + tan 5·(x − 600000): md = 1200 + 30 tan 5; md = 1200/(cos 30 − tan 5 sin 30 sin 60) |
| build 10° per 30 m from md 1156, azimuth 120 (2) | 1148.5 + R sin(s/R) = 1192.5 + tan 5 sin 120 R(1 − cos(s/R)), R = 30/rad(10) |
| fold (3) | a slant at 60° through S = 550 + \|x − 601000\| (an elevation surface): two crossings |
| three roots in one first interval (4) | f alternating ±0.05 at nodes 0.3 m apart: 4.9, 5.2, 5.5, 5.8; seven rows, so the disc of [5, 6] lies inside the cells and the interval meets the B′ test unsplit |
| close roots (5), near miss (6), midpoint test (7), parallel (8) | f piecewise linear between 1 m nodes |
| a 2 m near run beside a crossing (absorption) | f = −0.5, 0.008, 0.008, 0.008, 0.5 at md 3 to 7: one crossing at 3 + 0.5/0.508, then an `along-surface` row from 4 to 6 + 0.002/0.492 |
| near zero at the stations (9) | an arc 0.301 m below its chord between stations 1e-6 m below the surface |
| steep neighbour cell (10) | a horizontal turn of radius 1 m reaching 0.11 m into a cell ten times as steep |
| a disc touching a hole; a path entering one (11, 12) | the slant passing 0.3 m from a hole's corner; entering the next hole at x = 600600 |
| a root at a grid corner at md 1200.000 (13) | vertical at the node of depth 1192.5 |
| wholly above, wholly below (14); one-row and one-column grids (15) | |
| smooth near miss with its band edge at md 1203.37 (18) | an arc of radius 100 m whose deepest point is 0.009 m above a flat surface |
