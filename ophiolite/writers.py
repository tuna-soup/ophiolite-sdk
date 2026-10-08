"""E30b: write a result made in Python as the exact file an upload of that type would be.

Each writer returns a `WrittenOriginal` — the bytes, the profile, the declarations the server records
beside them and a file name — in the grammar the Connectors readers parse, so `Client.publish_derived`
publishes exactly what you computed. Nothing is inferred: every declaration a type needs is a keyword
argument you must give (write "unknown" when it is unknown), and a value the file format cannot carry
(a NODATA or null marker equal to a real value, a missing coordinate) is refused, never altered.
Numbers are written in their shortest exact decimal spelling. Importing this module contacts nothing.
"""
import math
from decimal import Decimal
from dataclasses import dataclass, field
from .errors import ValidationFailed


@dataclass(frozen=True)
class WrittenOriginal:
    bytes: bytes
    profile: str
    declared: dict = field(default_factory=dict)
    filename: str = 'derived'


def _number(value, what):
    try: value = float(value)
    except (TypeError, ValueError): raise ValidationFailed([f'{what} must be a number.']) from None
    if not math.isfinite(value): raise ValidationFailed([f'{what} must be finite.'])
    text = repr(value)  # the shortest spelling that reads back as exactly this float
    return text[:-2] if text.endswith('.0') else text


def _optional(value, what, missing=''):
    return missing if value is None else _number(value, what)


def _required(**declared):
    missing = [name.replace('_', ' ') for name, value in declared.items() if value is None]
    if missing: raise ValidationFailed(['Declare the ' + ', '.join(missing) + ' (write "unknown" when it is not known); nothing is inferred.'])
    return {k: v for k, v in declared.items() if v != 'unknown'}


def _cell(text, what):
    text = str(text)
    if any(c in text for c in ',"\r\n'): raise ValidationFailed([f'{what} cannot contain commas, quotes or line breaks.'])
    return text


def _names(attributes, reserved):
    names = list(attributes or {})
    if any(n.lower() in reserved for n in names) or len({n.lower() for n in names}) != len(names):
        raise ValidationFailed(['Attribute names must be distinct and not ' + ', '.join(sorted(reserved)) + '.'])
    if any(not n.replace('_', 'a').isalnum() for n in names): raise ValidationFailed(['Attribute names use letters, digits and underscores only.'])
    return names


def write_tops(tops, *, depth_unit=None, depth_basis=None, filename='tops.csv'):
    """Well tops CSV: `tops` is a sequence of {name, md, tvd?, source?} in the order to keep."""
    declared = _required(depth_unit=depth_unit, depth_basis=depth_basis)
    tops = list(tops)
    if not tops: raise ValidationFailed(['Write at least one top.'])
    with_tvd = any(t.get('tvd') is not None for t in tops); with_source = any(t.get('source') for t in tops)
    lines = [','.join(['name', 'md'] + (['tvd'] if with_tvd else []) + (['source'] if with_source else []))]
    for t in tops:
        row = [_cell(t['name'], 'A top name'), _number(t['md'], 'A measured depth')]
        if with_tvd: row.append(_optional(t.get('tvd'), 'A vertical depth'))
        if with_source: row.append(_cell(t.get('source') or '', 'A source label'))
        lines.append(','.join(row))
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'well-tops-csv/1', declared, filename)


def write_survey(stations, *, depth_unit=None, azimuth_reference=None, depth_datum=None, filename='survey.csv'):
    """Deviation survey CSV: {md, inclination, azimuth, tvd?} in increasing measured depth; a missing angle is None."""
    declared = _required(depth_unit=depth_unit, azimuth_reference=azimuth_reference, depth_datum=depth_datum)
    stations = list(stations)
    if not stations: raise ValidationFailed(['Write at least one station.'])
    with_tvd = any(s.get('tvd') is not None for s in stations)
    lines = ['md,inclination,azimuth' + (',tvd' if with_tvd else '')]
    for s in stations:
        row = [_number(s['md'], 'A measured depth'), _optional(s.get('inclination'), 'An inclination'), _optional(s.get('azimuth'), 'An azimuth')]
        if with_tvd: row.append(_optional(s.get('tvd'), 'A vertical depth'))
        lines.append(','.join(row))
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'deviation-csv/1', declared, filename)


def write_grid(values, *, ncols, nrows, x_origin, y_origin, cell_size, registration='corner', nodata=-9999.0,
               crs=None, xy_unit=None, z_unit=None, z_meaning=None, positive=None, vertical_datum=None, filename='surface.asc'):
    """ESRI ASCII grid: `values` row by row from the north (first row is the northernmost), None for a missing
    cell. `x_origin`/`y_origin` are the lower-left corner (registration 'corner') or lower-left cell centre ('center')."""
    declared = _required(crs=crs, xy_unit=xy_unit, z_unit=z_unit, z_meaning=z_meaning, positive=positive, vertical_datum=vertical_datum)
    if registration not in ('corner', 'center'): raise ValidationFailed(['Registration is corner or center.'])
    values = [v for row in values for v in (row if isinstance(row, (list, tuple)) else [row])]
    if len(values) != ncols * nrows: raise ValidationFailed([f'The grid needs ncols × nrows = {ncols * nrows} values; {len(values)} were given.'])
    if float(cell_size) <= 0: raise ValidationFailed(['The cell size must be positive.'])
    marker = float(nodata)
    if any(v is not None and float(v) == marker for v in values): raise ValidationFailed([f'A real value equals the NODATA marker {nodata}; choose another marker.'])
    head = [f'ncols {int(ncols)}', f'nrows {int(nrows)}', f'xll{registration} {_number(x_origin, "The x origin")}', f'yll{registration} {_number(y_origin, "The y origin")}',
            f'cellsize {_number(cell_size, "The cell size")}', f'NODATA_value {_number(marker, "The NODATA marker")}']
    rows = [' '.join(_number(marker, '') if v is None else _number(v, 'A grid value') for v in values[r * ncols:(r + 1) * ncols]) for r in range(nrows)]
    return WrittenOriginal(('\n'.join(head + rows) + '\n').encode(), 'esri-ascii-grid/1', declared, filename)


def write_mesh(vertices, triangles, *, attributes=None, crs=None, xy_unit=None, z_unit=None, z_meaning=None, positive=None, vertical_datum=None, filename='surface.mesh'):
    """ophiolite-mesh text: vertices (x, y, z or None), triangles (three zero-based vertex numbers, as given), and
    optional per-vertex attributes {name: [values]} (None for missing)."""
    declared = _required(crs=crs, xy_unit=xy_unit, z_unit=z_unit, z_meaning=z_meaning, positive=positive, vertical_datum=vertical_datum)
    vertices, triangles = list(vertices), list(triangles)
    names = _names(attributes, set())
    if not vertices or not triangles: raise ValidationFailed(['A surface needs vertices and triangles.'])
    if any(len(attributes[n]) != len(vertices) for n in names): raise ValidationFailed(['Every attribute needs one value per vertex.'])
    lines = ['# ophiolite-mesh 1'] + (['attributes ' + ' '.join(names)] if names else []) + ['vertices']
    for i, v in enumerate(vertices):
        if v[0] is None or v[1] is None: raise ValidationFailed([f'Vertex {i} has no x or y.'])
        cells = [_number(v[0], 'x'), _number(v[1], 'y'), '-' if v[2] is None else _number(v[2], 'z')]
        cells += ['-' if attributes[n][i] is None else _number(attributes[n][i], 'An attribute value') for n in names]
        lines.append(' '.join(cells))
    lines.append('triangles')
    for t in triangles:
        t = [int(i) for i in t]
        if len(t) != 3 or len(set(t)) != 3 or any(not 0 <= i < len(vertices) for i in t): raise ValidationFailed(['A triangle is three distinct existing vertex numbers.'])
        lines.append(' '.join(map(str, t)))
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'mesh-text/1', declared, filename)


def write_points(points, *, attributes=None, crs=None, xy_unit=None, z_unit=None, z_meaning=None, positive=None, vertical_datum=None, filename='points.csv'):
    """Point set CSV: (x, y) or (x, y, z-or-None) per point, optional numeric attributes {name: [values]}."""
    declared = _required(crs=crs, xy_unit=xy_unit, z_unit=z_unit, z_meaning=z_meaning, positive=positive, vertical_datum=vertical_datum)
    points = list(points)
    names = _names(attributes, {'x', 'y', 'z'})
    if not points: raise ValidationFailed(['Write at least one point.'])
    if any(len(attributes[n]) != len(points) for n in names): raise ValidationFailed(['Every attribute needs one value per point.'])
    with_z = any(len(p) > 2 for p in points)
    lines = [','.join(['x', 'y'] + (['z'] if with_z else []) + names)]
    for i, p in enumerate(points):
        if p[0] is None or p[1] is None: raise ValidationFailed([f'Point {i} has no x or y.'])
        cells = [_number(p[0], 'x'), _number(p[1], 'y')] + ([_optional(p[2] if len(p) > 2 else None, 'z')] if with_z else [])
        cells += [_optional(attributes[n][i], 'An attribute value') for n in names]
        lines.append(','.join(cells))
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'points-csv/1', declared, filename)


def write_sticks(sticks, *, crs=None, xy_unit=None, z_unit=None, z_meaning=None, positive=None, vertical_datum=None, filename='faults.txt'):
    """OpendTect FaultStickSet ASCII (`x y z stick-index`): `sticks` is [{index, points: [(x, y, z)]}] with at
    least two points each; a missing coordinate cannot be written and is refused."""
    declared = _required(crs=crs, xy_unit=xy_unit, z_unit=z_unit, z_meaning=z_meaning, positive=positive, vertical_datum=vertical_datum)
    from .faults import write
    return WrittenOriginal(write(sticks).encode(), 'opendtect-faultsticks/1', declared, filename)


def write_curves(depth, curves, *, depth_unit=None, well='DERIVED', null_marker=-999.25, filename='derived.las', notes=()):
    """LAS 2.0 text: one depth axis (never missing) and 1-63 curves {mnemonic: (unit, values)}; None is missing.
    A real sample equal to `null_marker` would read back as missing, so it is refused. `notes` (E52) are lines of an
    ~Other section, such as `petrophysics.calculation_record(...)`: one printable ASCII line each, written as the server writes them."""
    notes = list(notes)
    if any(not isinstance(n, str) or not n.strip() or not n.isascii() or not n.isprintable() or n.lstrip().startswith(('~', '#')) for n in notes):
        raise ValidationFailed(['Each note is one line of printable ASCII text that does not start with ~ or #.'])
    if depth_unit is None: raise ValidationFailed(['Declare the depth unit; nothing is inferred.'])
    depth = list(depth); names = list(curves)
    if not depth: raise ValidationFailed(['Write at least one depth sample.'])
    if not 1 <= len(names) <= 63 or len({n.upper() for n in names}) != len(names) or any(not n or not n.replace('_', 'a').isalnum() or n.lower() in ('dept', 'id') for n in names):
        raise ValidationFailed(['Write 1-63 distinct curves named with letters, digits and underscores (not DEPT or id).'])
    marker = float(null_marker)
    for n in names:
        unit, values = curves[n]
        if len(values) != len(depth): raise ValidationFailed([f'Curve {n} needs one value per depth.'])
        if any(v is not None and float(v) == marker for v in values): raise ValidationFailed([f'Curve {n} has a real value equal to the null marker {null_marker}; choose another marker.'])
    if any(d is None for d in depth): raise ValidationFailed(['Depth cannot be missing.'])
    step = depth[1] - depth[0] if len(depth) > 1 else 0
    regular = len(depth) > 1 and all(abs((depth[i + 1] - depth[i]) - step) < 1e-9 for i in range(len(depth) - 1))
    unit_text = lambda u: '' if u in (None, 'unknown') else str(u)
    lines = ['~Version', 'VERS. 2.0 : LAS', 'WRAP. NO : rows', '~Well',
             f'STRT.{unit_text(depth_unit)} {_number(depth[0], "Depth")} : start', f'STOP.{unit_text(depth_unit)} {_number(depth[-1], "Depth")} : stop',
             f'STEP.{unit_text(depth_unit)} {_number(step if regular else 0, "Step")} : step', f'NULL. {_number(marker, "The null marker")} : missing',
             f'WELL. {_cell(well, "The well name")} : well', '~Curve', f'DEPT.{unit_text(depth_unit)} : depth']
    lines += [f'{n}.{unit_text(curves[n][0])} : {n}' for n in names]
    if notes: lines += ['~Other', *[' ' + n for n in notes]]
    lines.append('~ASCII')
    for i, d in enumerate(depth):
        lines.append(' '.join([_number(d, 'Depth')] + [_number(marker, '') if curves[n][1][i] is None else _number(curves[n][1][i], 'A sample') for n in names]))
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'las2/1', {}, filename)


# --- E53: a wavelet, a rock model section and a seismic section, in the Connectors' text formats ------------------
# Each file states its own context in its header, so nothing is declared beside it. Pass the SDK's own object (from
# ophiolite.synthetics or read_data) and its context is used; any keyword you give replaces that field.
POLARITY = 'Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.'


def _given(source, key, value):
    return value if value is not None else (getattr(source, 'context', None) or {}).get(key)


def _declared(value, sentence):
    if value is None: raise ValidationFailed([sentence])
    return value


def _axes(source, grid, domain, first_sample, sample_interval, horizontal, horizontal_first, horizontal_step):
    domain = _declared(_given(source, 'domain', domain), 'Declare whether the vertical axis is time or depth; nothing is inferred.')
    if domain not in ('time', 'depth'): raise ValidationFailed(['Declare whether the vertical axis is time or depth; nothing is inferred.'])
    interval = _number(_declared(_given(source, 'sample_interval', sample_interval), 'Declare the sample interval; nothing is inferred.'), 'The sample interval')
    if float(interval) <= 0: raise ValidationFailed(['The sample interval must be positive.'])
    first = _number(_declared(_given(source, 'first_sample', first_sample), 'Declare the first sample (first_sample); nothing is inferred.'), 'The first sample')
    horizontal = _declared(_given(source, 'horizontal', horizontal), 'Declare the horizontal axis as distance or trace-number.')
    if horizontal not in ('distance', 'trace-number'): raise ValidationFailed(['Declare the horizontal axis as distance or trace-number.'])
    h_first, h_step = _given(source, 'horizontal_first', horizontal_first), _given(source, 'horizontal_step', horizontal_step)
    if h_first is None or h_step is None: raise ValidationFailed(['Declare horizontal_first and horizontal_step.'])
    h_first, h_step = _number(h_first, 'The first horizontal position'), _number(h_step, 'The horizontal step')
    if float(h_step) <= 0: raise ValidationFailed(['The horizontal step must be positive.'])
    grid = [list(row) for row in grid]
    if not grid or not grid[0] or any(len(row) != len(grid[0]) for row in grid): raise ValidationFailed(['Every grid row needs one value per trace.'])
    samples, traces = len(grid), len(grid[0])
    if samples > 8192 or traces > 4096: raise ValidationFailed(['A section has at most 8192 samples per trace and 4096 traces.'])
    if samples * traces > 1_000_000: raise ValidationFailed(['A section holds at most 1,000,000 samples.'])
    return grid, [f'domain {domain}', f'first_sample {first}', f'sample_interval {interval}', f'samples {samples}', f'traces {traces}',
                  f'horizontal {horizontal}', f'horizontal_first {h_first}', f'horizontal_step {h_step}']


def write_wavelet(wavelet, *, kind=None, dt=None, t0=None, polarity=None, frequency_hz=None, corners_hz=None, filename='wavelet.txt'):
    """`# ophiolite-wavelet 1`: the samples every `dt` seconds from `t0`, the kind (ricker with `frequency_hz`, ormsby
    with four `corners_hz`, or other) and the polarity. 3-4095 samples, an odd count, sampled every 0.0005-0.01 s."""
    kind = _declared(_given(wavelet, 'kind', kind), 'Declare the wavelet kind as ricker, ormsby or other.')
    if kind not in ('ricker', 'ormsby', 'other'): raise ValidationFailed(['Declare the wavelet kind as ricker, ormsby or other.'])
    dt = _declared(_given(wavelet, 'dt', dt), 'Declare the sample interval; nothing is inferred.')
    t0 = _declared(_given(wavelet, 't0', t0), 'Declare the time of the first sample (t0); nothing is inferred.')
    polarity = _declared(_given(wavelet, 'polarity', polarity), POLARITY)
    if polarity not in ('impedance-increase-positive', 'impedance-increase-negative', 'unknown'): raise ValidationFailed([POLARITY])
    dt_text = _number(dt, 'The sample interval')
    if not 0.0005 <= float(dt_text) <= 0.01: raise ValidationFailed(['A wavelet must be sampled every 0.0005 to 0.01 s.'])
    samples = list(getattr(wavelet, 'samples', wavelet))
    if not 3 <= len(samples) <= 4095: raise ValidationFailed(['A wavelet has 3 to 4095 samples.'])
    if len(samples) % 2 == 0: raise ValidationFailed(['A wavelet has an odd number of samples, so one sample is its centre.'])
    lines = ['# ophiolite-wavelet 1', f'kind {kind}']
    frequency, corners = _given(wavelet, 'frequency_hz', frequency_hz), _given(wavelet, 'corners_hz', corners_hz)
    if (kind == 'ricker') != (frequency is not None) or (kind == 'ormsby') != (corners is not None):
        raise ValidationFailed(['A Ricker wavelet declares frequency_hz, an Ormsby wavelet four corners_hz, and no other kind either.'])
    if frequency is not None: lines.append(f'frequency_hz {_number(frequency, "The frequency")}')
    if corners is not None:
        if len(corners) != 4: raise ValidationFailed(['An Ormsby wavelet declares corners_hz as four frequencies.'])
        lines.append('corners_hz ' + ' '.join(_number(f, 'A corner frequency') for f in corners))
    lines += [f'dt {dt_text}', f't0 {_number(t0, "The first time")}', f'polarity {polarity}', 'samples']
    lines += [_number(v, 'A sample') for v in samples]
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'wavelet-text/1', {}, filename)


def write_model_section(model, grid=None, *, domain=None, first_sample=None, sample_interval=None, horizontal=None, horizontal_first=None,
                        horizontal_step=None, filename='model.txt'):
    """`# ophiolite-model-section 1`: rocks (index, P-wave velocity m/s, density kg/m3, name) and a grid of rock indices,
    one row per vertical sample. `model` is a ModelSection, or the rocks list with `grid` beside it."""
    rocks = list(getattr(model, 'rocks', model)); grid = getattr(model, 'grid', None) if grid is None else grid
    if grid is None: raise ValidationFailed(['Give the grid of rock indices.'])
    grid, header = _axes(model, grid, domain, first_sample, sample_interval, horizontal, horizontal_first, horizontal_step)
    if not 1 <= len(rocks) <= 256: raise ValidationFailed(['A model lists 1 to 256 rocks.'])
    lines, indices = ['# ophiolite-model-section 1', *header, 'rocks'], set()
    for rock in rocks:
        index, name = rock.get('index'), rock.get('name')
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in indices: raise ValidationFailed(['Give every rock its own whole-number index.'])
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or any(c in name for c in '\r\n') or name != ' '.join(name.split()):
            raise ValidationFailed(['Give every rock a name (up to 128 characters, one line, single spaces).'])
        vp, density = _number(rock.get('vp'), 'A P-wave velocity'), _number(rock.get('density'), 'A density')
        if float(vp) <= 0 or float(density) <= 0: raise ValidationFailed([f'Rock {index}: the P-wave velocity and density must be positive.'])
        indices.add(index); lines.append(f'{index} {vp} {density} {name}')
    if any(isinstance(v, bool) or v not in indices for row in grid for v in row): raise ValidationFailed(['Every grid cell names a listed rock.'])
    lines += ['grid', *(' '.join(str(v) for v in row) for row in grid)]
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'model-section-text/1', {}, filename)


def write_seismic_section(section, *, domain=None, first_sample=None, sample_interval=None, horizontal=None, horizontal_first=None,
                          horizontal_step=None, polarity=None, origin=None, filename='section.txt'):
    """`# ophiolite-seismic-section 1`: every sample, one row per vertical sample and one value per trace. `origin` is
    'synthetic' for a section computed from a rock model and a wavelet (published with both as parents), else left out."""
    grid, header = _axes(section, getattr(section, 'grid', section), domain, first_sample, sample_interval, horizontal, horizontal_first, horizontal_step)
    polarity = _declared(_given(section, 'polarity', polarity), POLARITY)
    if polarity not in ('impedance-increase-positive', 'impedance-increase-negative', 'unknown'): raise ValidationFailed([POLARITY])
    origin = _given(section, 'origin', origin)
    if origin not in (None, 'not-stated', 'synthetic'): raise ValidationFailed(['Declare the origin as synthetic, or leave it out.'])
    lines = ['# ophiolite-seismic-section 1', *header, *(['origin synthetic'] if origin == 'synthetic' else []), f'polarity {polarity}', 'grid']
    lines += [' '.join(_number(v, 'A sample') for v in row) for row in grid]
    return WrittenOriginal(('\n'.join(lines) + '\n').encode(), 'seismic-section-text/1', {}, filename)




# E57: time-depth tables. The declarations are the reader's choices; `_decimal` is the one canonical spelling of a declared
# number (the Connectors `time_depth.decimal`): the shortest that reads back as the same float, never an exponent.
DEPTH_TYPES = ('md', 'tvd', 'tvdss', 'unknown')
TIME_KINDS = ('one-way', 'two-way', 'unknown')
TIME_UNITS = ('ms', 's', 'us', 'unknown')


def _decimal(value, what):
    try: value = float(value)
    except (TypeError, ValueError): raise ValidationFailed([f'{what} must be a number.']) from None
    if not math.isfinite(value): raise ValidationFailed([f'{what} must be finite.'])
    text = repr(value)
    if 'e' in text or 'E' in text: text = format(Decimal(text), 'f')
    if '.' in text: text = text.rstrip('0')
    text = text.rstrip('.')
    return '0' if text == '-0' else text


def _choice(value, allowed, what):
    if value not in allowed: raise ValidationFailed([f'Choose the {what} from: ' + ', '.join(allowed) + '.'])
    return value


def write_time_depth(pairs, *, depth_type=None, depth_unit=None, time_kind=None, time_unit=None, datum=None, seismic_reference_elevation=None,
                     filename='time-depth.csv'):
    """Time-depth CSV (checkshots, a velocity table): `pairs` is a sequence of (depth, time) or (depth, time, velocity) in
    strictly increasing depth and time; a missing velocity is None. Every declaration but the datum and the seismic
    reference elevation is required ("unknown" allowed). Lines end in CRLF (RFC 4180)."""
    _required(depth_type=depth_type, depth_unit=depth_unit, time_kind=time_kind, time_unit=time_unit)
    declared = {'depth_type': _choice(depth_type, DEPTH_TYPES, 'depth type'), 'depth_unit': depth_unit,
                'time_kind': _choice(time_kind, TIME_KINDS, 'time kind'), 'time_unit': _choice(time_unit, TIME_UNITS, 'time unit')}
    if datum is not None: declared['datum'] = _cell(datum, 'The datum')
    if seismic_reference_elevation is not None: declared['seismic_reference_elevation'] = _decimal(seismic_reference_elevation, 'The seismic reference elevation')
    declared = {k: v for k, v in declared.items() if v != 'unknown'}
    pairs = [tuple(p) for p in pairs]
    if len(pairs) < 2: raise ValidationFailed(['Write at least two pairs.'])
    if len(pairs) > 100_000: raise ValidationFailed(['Write at most 100,000 pairs.'])
    with_velocity = any(len(p) > 2 and p[2] is not None for p in pairs)
    lines, previous = ['depth,time' + (',velocity' if with_velocity else '')], None
    for i, p in enumerate(pairs, 1):
        depth, time = float(_decimal(p[0], 'A depth')), float(_decimal(p[1], 'A time'))
        if previous and depth <= previous[0]: raise ValidationFailed([f'Depth of pair {i} does not increase; pairs must be in strictly increasing depth.'])
        if previous and time <= previous[1]: raise ValidationFailed([f'Time of pair {i} does not increase; pairs must be in strictly increasing time.'])
        row = [_decimal(depth, 'A depth'), _decimal(time, 'A time')]
        if with_velocity: row.append('' if len(p) < 3 or p[2] is None else _decimal(p[2], 'A velocity'))
        lines.append(','.join(row)); previous = (depth, time)
    return WrittenOriginal(('\r\n'.join(lines) + '\r\n').encode(), 'time-depth-csv/1', declared, filename)
