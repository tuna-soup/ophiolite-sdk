"""E128 s2: the text kinds (ESRI ASCII grids, meshes, fault sticks, wavelets, model and seismic sections), read whole.

The grammar is the server's (`asset_connectors.typed_reader`, `faults`, `sections`): the same checks in the same order,
with the same sentences, codes, fields and rows, so a file is refused at the same first problem on both sides. What the
server drops is kept here and nowhere else: header text as written, the stick node field, and a section's origin and
polarity left absent. `context` is the server's normalized context, computed here. Standard library only.
"""
import math

from .results import Grid, Mesh, ModelSection, SeismicSection, Sticks, Wavelet
from .tables import ATTRIBUTE, MAX_ATTRIBUTES, _choice, _crs, _free, _number, _refuse, _spatial, _text, _unit

GRID_KEYS = {'ncols', 'nrows', 'xllcorner', 'yllcorner', 'xllcenter', 'yllcenter', 'cellsize', 'nodata_value'}
GRID_MAX = 4 * 1024 * 1024  # the most cells any deployment may allow (project_gateway/limits.py GRID_MAX), S2-D4
MAX_VERTICES, MAX_TRIANGLES = 200000, 400000
STICK_POINTS, STICKS = 200_000, 20_000
WAVELET_SAMPLES, WAVELET_DT = (3, 4095), (0.0005, 0.01)
MAX_SAMPLES, MAX_TRACES, MAX_CELLS = 8192, 4096, 1_000_000
MAX_ROCKS, MAX_NAME = 256, 128
POLARITIES = ('impedance-increase-positive', 'impedance-increase-negative', 'unknown')
POLARITY = 'Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.'
WAVELET_KINDS = ('ricker', 'ormsby', 'other')
AXES = ('domain', 'first_sample', 'sample_interval', 'samples', 'traces', 'horizontal', 'horizontal_first', 'horizontal_step')


def _ints(words, sentence):
    """int() of words that passed str.isdigit(). A whole number is ASCII [0-9]+ (S2-D7, disposition 15): a Unicode
    digit is refused with the site's own sentence, where the server crashes on '²' and reads '٣' until D-29 merges."""
    if not all(w.isascii() for w in words): _refuse(sentence)
    return [int(w) for w in words]


def _extent(xs, ys, zs):
    present = [z for z in zs if z is not None]
    return {'x_range': [min(xs), max(xs)], 'y_range': [min(ys), max(ys)], 'z_range': [min(present), max(present)] if present else None}


def _grid(text, declared):
    """The server's `_grid` at max_cells=GRID_MAX and no max_encoded (nothing is served locally)."""
    lines = text.splitlines()
    head, header, index = {}, [], 0
    while index < len(lines):
        parts = lines[index].split()
        if not parts: index += 1; continue
        key = parts[0].lower()
        if key not in GRID_KEYS: break
        if len(parts) != 2 or key in head: _refuse(f'Grid header line "{parts[0][:20]}" is malformed or repeated.')
        head[key] = parts[1]; header.append((parts[0], parts[1])); index += 1
    try:
        ncols, nrows = int(head['ncols']), int(head['nrows'])
    except (KeyError, ValueError): _refuse('The grid header must declare whole-number ncols and nrows.')
    registration = 'corner' if 'xllcorner' in head and 'yllcorner' in head else 'center' if 'xllcenter' in head and 'yllcenter' in head else None
    if registration is None or ('xllcorner' in head) == ('xllcenter' in head) or 'cellsize' not in head:
        _refuse('The grid header must declare cellsize and either xllcorner/yllcorner or xllcenter/yllcenter.')
    if not (1 <= ncols and 1 <= nrows and ncols * nrows <= GRID_MAX): _refuse(f'The grid must have between 1 and {GRID_MAX} cells.')
    x0 = _number(head['xll' + registration], 'The x origin', 0); y0 = _number(head['yll' + registration], 'The y origin', 0)
    cell = _number(head['cellsize'], 'The cell size', 0)
    if cell <= 0: _refuse('The cell size must be positive.')
    nodata = _number(head['nodata_value'], 'The NODATA value', 0) if 'nodata_value' in head else None
    total, values = ncols * nrows, []
    for row, line in enumerate(lines[index:], 1):
        for token in line.split():
            value = _number(token, 'A grid value', row)
            if len(values) >= total: _refuse('The grid has more values than ncols × nrows.')
            values.append(None if nodata is not None and value == nodata else value)
    if len(values) != total: _refuse(f'The grid has {len(values)} values; ncols × nrows is {total}.')
    present = [v for v in values if v is not None]
    half = cell / 2 if registration == 'corner' else 0.0
    context = {'type': 'regular-grid-surface', 'crs': _crs(declared.get('crs')), 'xy_unit': _unit(declared.get('xy_unit'), 'map unit'),
               'z_unit': _unit(declared.get('z_unit'), 'value unit'),
               'z_meaning': _choice(declared.get('z_meaning'), ['depth', 'elevation', 'time', 'unknown'], 'value meaning'),
               'positive': _choice(declared.get('positive'), ['up', 'down', 'unknown'], 'positive direction'),
               'vertical_datum': _free(declared.get('vertical_datum'), 'vertical datum'),
               'registration': registration, 'row_order': 'north-to-south', 'ncols': ncols, 'nrows': nrows, 'cell_size': cell,
               'x_first_center': x0 + half, 'y_first_center': y0 + half + (nrows - 1) * cell,
               'missing_count': len(values) - len(present),
               'value_range': [min(present), max(present)] if present else None}
    cells = [values[r * ncols:(r + 1) * ncols] for r in range(nrows)]
    return dict(context=context, header=header, ncols=ncols, nrows=nrows, registration=registration, x=x0, y=y0, cell_size=cell,
                nodata=nodata, cells=cells)


def _mesh(text, declared):
    """The server's `_mesh`."""
    lines = [l.strip() for l in text.splitlines()]
    if not lines or lines[0] != '# ophiolite-mesh 1': _refuse('The first line must be "# ophiolite-mesh 1".')
    attributes, section, vertices, triangles = [], None, [], []
    for number, line in enumerate(lines[1:], 2):
        if not line or line.startswith('#'): continue
        words = line.split()
        if words[0] == 'attributes' and section is None:
            attributes = words[1:]
            if len(attributes) > MAX_ATTRIBUTES or len(set(attributes)) != len(attributes) or not all(ATTRIBUTE.fullmatch(a) for a in attributes):
                _refuse(f'Declare at most {MAX_ATTRIBUTES} distinct attribute names (letters, digits, underscores).')
            continue
        if words == ['vertices'] and section is None: section = 'vertices'; continue
        if words == ['triangles'] and section == 'vertices': section = 'triangles'; continue
        if section == 'vertices':
            if len(words) != 3 + len(attributes): _refuse(f'Line {number}: a vertex needs x, y, z and {len(attributes)} attribute values.')
            x, y = _number(words[0], 'x', number), _number(words[1], 'y', number)
            z = None if words[2] == '-' else _number(words[2], 'z', number)
            values = [None if w == '-' else _number(w, 'An attribute', number) for w in words[3:]]
            vertices.append((x, y, z, values))
            if len(vertices) > MAX_VERTICES: _refuse(f'The surface has more than {MAX_VERTICES} vertices.')
        elif section == 'triangles':
            if len(words) != 3 or not all(w.isdigit() for w in words): _refuse(f'Line {number}: a triangle is three vertex numbers.')
            triangle = _ints(words, f'Line {number}: a triangle is three vertex numbers.')
            if len(set(triangle)) != 3: _refuse(f'Line {number}: a triangle repeats a vertex.')
            triangles.append(triangle)
            if len(triangles) > MAX_TRIANGLES: _refuse(f'The surface has more than {MAX_TRIANGLES} triangles.')
        else: _refuse(f'Line {number}: expected "vertices" first.')
    if not vertices or not triangles: _refuse('The surface needs vertices and triangles.')
    if any(i >= len(vertices) for t in triangles for i in t): _refuse('A triangle refers to a vertex that does not exist.')
    xs, ys, zs = [v[0] for v in vertices], [v[1] for v in vertices], [v[2] for v in vertices]
    context = {'type': 'triangulated-surface', **_spatial(declared), 'vertex_count': len(vertices), 'triangle_count': len(triangles),
               'attributes': attributes, 'missing_z_count': sum(z is None for z in zs), **_extent(xs, ys, zs)}
    return dict(context=context, attributes=attributes, vertices=vertices, triangles=triangles)


def _stick_points(text):
    """faults.read, keeping every point in file order with its stick index and node field (the server groups and drops it)."""
    points, sticks = [], {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('!'): continue
        parts = stripped.replace(',', ' ').split()
        if len(parts) not in (4, 5): _refuse('Line %d: expected x y z stick-index [node-index].' % number)
        try:
            x, y, z = (float(v) for v in parts[:3]); index = int(parts[3])
        except ValueError: _refuse('Line %d: coordinates must be numbers and the stick index a whole number.' % number)
        if not all(math.isfinite(v) for v in (x, y, z)): _refuse('Line %d: coordinates must be finite.' % number)
        sticks[index] = sticks.get(index, 0) + 1
        points.append((x, y, z, index, parts[4] if len(parts) == 5 else None))
        if len(points) > STICK_POINTS or len(sticks) > STICKS: _refuse('The file holds too many points or sticks.')
    if not sticks: _refuse('The file holds no fault-stick points.')
    if any(count < 2 for count in sticks.values()): _refuse('Every stick needs at least two points.')
    return points


def _grouped(points):
    """The server's sticks: first-appearance order, points in file order."""
    sticks = {}
    for x, y, z, index, _ in points: sticks.setdefault(index, []).append({'x': x, 'y': y, 'z': z})
    return [{'index': i, 'points': p} for i, p in sticks.items()]


def _sticks(text, declared):
    """The server's `_polylines`, with its write-back check (faults.round_trip; S2-D5)."""
    points = _stick_points(text)
    written = ''.join('%s %s %s %d\n' % (repr(x), repr(y), repr(z), index) for x, y, z, index, _ in points)
    if _grouped(_stick_points(written)) != _grouped(points): _refuse('The fault sticks do not survive writing back in the same form.')
    context = {'type': 'polyline-set', **_spatial(declared), 'attributes': [], 'sticks': len(_grouped(points)), 'points': len(points),
               **_extent([p[0] for p in points], [p[1] for p in points], [p[2] for p in points])}
    return dict(context=context, points=points)


def _stated(declared):
    """read_typed's check for the section kinds, after the text is decoded: the file states its own context."""
    if declared: _refuse('This file states its context in its header; nothing is declared beside it.')


def _header(lines, first, sections):
    """sections._header: the `key value` lines up to the first section word; (fields in file order, index of section)."""
    if not lines or lines[0].strip() != first: _refuse(f'The first line must be "{first}".')
    fields = {}
    for index, line in enumerate(lines[1:], 1):
        words = line.split()
        if not words or words[0].startswith('#'): continue
        if words == [words[0]] and words[0] in sections: return fields, index
        if len(words) < 2: _refuse(f'Line {index + 1}: a header line is a name and a value.')
        if words[0] in fields: _refuse(f'Line {index + 1}: {words[0]} is stated twice.')
        fields[words[0]] = words[1:]
    _refuse('The file has no ' + ' or '.join(f'"{s}"' for s in sections) + ' section.')


def _rows(lines, start):
    for index in range(start, len(lines)):
        words = lines[index].split()
        if words and not words[0].startswith('#'): yield index + 1, words


def _one(fields, key, missing):
    if key not in fields: _refuse(missing)
    if len(fields[key]) != 1: _refuse(f'{key} takes one value.')
    return fields[key][0]


def _count(token, what):
    if not token.isdigit(): _refuse(f'{what} is a whole number.')
    return _ints([token], f'{what} is a whole number.')[0]


def _wavelet(text, declared):
    """sections.read_wavelet."""
    _stated(declared)
    lines = text.splitlines()
    fields, start = _header(lines, '# ophiolite-wavelet 1', ('samples',))
    unknown = sorted(set(fields) - {'kind', 'frequency_hz', 'corners_hz', 'dt', 't0', 'polarity'})
    if unknown: _refuse(f'Unknown header field {unknown[0]}.')
    kind = _one(fields, 'kind', 'Declare the wavelet kind as ricker, ormsby or other.')
    if kind not in WAVELET_KINDS: _refuse('Declare the wavelet kind as ricker, ormsby or other.')
    dt = _number(_one(fields, 'dt', 'Declare the sample interval; nothing is inferred.'), 'dt', None)
    if not WAVELET_DT[0] <= dt <= WAVELET_DT[1]: _refuse('A wavelet must be sampled every 0.0005 to 0.01 s.')
    t0 = _number(_one(fields, 't0', 'Declare the time of the first sample (t0); nothing is inferred.'), 't0', None)
    polarity = _one(fields, 'polarity', POLARITY)
    if polarity not in POLARITIES: _refuse(POLARITY)
    frequency, corners = None, None
    if kind == 'ricker':
        frequency = _number(_one(fields, 'frequency_hz', 'A Ricker wavelet declares its frequency_hz.'), 'frequency_hz', None)
        if frequency <= 0: _refuse('The frequency must be positive.')
    elif 'frequency_hz' in fields: _refuse('Only a Ricker wavelet declares frequency_hz.')
    if kind == 'ormsby':
        if len(fields.get('corners_hz', [])) != 4: _refuse('An Ormsby wavelet declares corners_hz as four frequencies.')
        corners = [_number(w, 'A corner frequency', None) for w in fields['corners_hz']]
        if not 0 <= corners[0] < corners[1] < corners[2] < corners[3]: _refuse('The Ormsby corner frequencies must increase.')
    elif 'corners_hz' in fields: _refuse('Only an Ormsby wavelet declares corners_hz.')
    samples = []
    for row, words in _rows(lines, start + 1):
        if len(words) != 1: _refuse(f'Line {row}: a wavelet sample is one number.')
        samples.append(_number(words[0], 'A sample', row))
        if len(samples) > WAVELET_SAMPLES[1]: _refuse('A wavelet has 3 to 4095 samples.')
    if len(samples) < WAVELET_SAMPLES[0]: _refuse('A wavelet has 3 to 4095 samples.')
    if len(samples) % 2 == 0: _refuse('A wavelet has an odd number of samples, so one sample is its centre.')
    context = {'type': 'wavelet', 'kind': kind, 'frequency_hz': frequency, 'corners_hz': corners, 'dt': dt, 't0': t0,
               'time_unit': 's', 'polarity': polarity, 'sample_count': len(samples), 'minimum': min(samples), 'maximum': max(samples)}
    return dict(context=context, header=list(fields.items()), wavelet_kind=kind, dt=dt, t0=t0, polarity=polarity,
                frequency_hz=frequency, corners_hz=corners, samples=samples)


def _axes(fields):
    """sections._axes, as the server's context keys (units included)."""
    domain = _one(fields, 'domain', 'Declare whether the vertical axis is time or depth; nothing is inferred.')
    if domain not in ('time', 'depth'): _refuse('Declare whether the vertical axis is time or depth; nothing is inferred.')
    interval = _number(_one(fields, 'sample_interval', 'Declare the sample interval; nothing is inferred.'), 'sample_interval', None)
    if interval <= 0: _refuse('The sample interval must be positive.')
    first = _number(_one(fields, 'first_sample', 'Declare the first sample (first_sample); nothing is inferred.'), 'first_sample', None)
    samples = _count(_one(fields, 'samples', 'Declare the number of samples per trace.'), 'samples')
    traces = _count(_one(fields, 'traces', 'Declare the number of traces.'), 'traces')
    if not 1 <= samples <= MAX_SAMPLES: _refuse(f'A section has 1 to {MAX_SAMPLES} samples per trace.')
    if not 1 <= traces <= MAX_TRACES: _refuse(f'A section has 1 to {MAX_TRACES} traces.')
    if samples * traces > MAX_CELLS: _refuse('A section holds at most 1,000,000 samples.')
    horizontal = _one(fields, 'horizontal', 'Declare the horizontal axis as distance or trace-number.')
    if horizontal not in ('distance', 'trace-number'): _refuse('Declare the horizontal axis as distance or trace-number.')
    h_first = _number(_one(fields, 'horizontal_first', 'Declare horizontal_first and horizontal_step.'), 'horizontal_first', None)
    h_step = _number(_one(fields, 'horizontal_step', 'Declare horizontal_first and horizontal_step.'), 'horizontal_step', None)
    if h_step <= 0: _refuse('The horizontal step must be positive.')
    return {'domain': domain, 'first_sample': first, 'sample_interval': interval, 'sample_unit': 's' if domain == 'time' else 'm',
            'samples': samples, 'traces': traces, 'horizontal': horizontal, 'horizontal_first': h_first, 'horizontal_step': h_step,
            'horizontal_unit': 'm' if horizontal == 'distance' else None}


def _stated_axes(axes):
    """The family's `axes`: the eight header keys only (S2-D2); the units are the context's."""
    return {k: axes[k] for k in AXES}


def _section_grid(lines, start, axes, value):
    grid = []
    for row, words in _rows(lines, start):
        if len(grid) == axes['samples']: _refuse(f'The grid has more than the {axes["samples"]} rows the header declares.')
        if len(words) != axes['traces']: _refuse(f'Line {row}: a grid row has {len(words)} values; the header declares {axes["traces"]} traces.')
        grid.append([value(w, row) for w in words])
    if len(grid) != axes['samples']: _refuse(f'The grid has {len(grid)} rows; the header declares {axes["samples"]} samples.')
    return grid


def _model_section(text, declared):
    """sections.read_model_section."""
    _stated(declared)
    lines = text.splitlines()
    fields, start = _header(lines, '# ophiolite-model-section 1', ('rocks',))
    unknown = sorted(set(fields) - set(AXES))
    if unknown: _refuse(f'Unknown header field {unknown[0]}.')
    axes = _axes(fields)
    rocks, grid_at = {}, None
    for row, words in _rows(lines, start + 1):
        if words == ['grid']: grid_at = row; break
        sentence = f'Line {row}: a rock is an index, a P-wave velocity (m/s), a density (kg/m3) and a name.'
        if len(words) < 4 or not words[0].isdigit(): _refuse(sentence)
        index = _ints(words[:1], sentence)[0]
        if index in rocks: _refuse(f'Rock {index} is listed twice.')
        vp, rho = _number(words[1], 'A P-wave velocity', row), _number(words[2], 'A density', row)
        if len(' '.join(words[3:])) > MAX_NAME: _refuse(f'Rock {index}: a rock name has at most {MAX_NAME} characters.')
        if vp <= 0 or rho <= 0: _refuse(f'Rock {index}: the P-wave velocity and density must be positive.')
        rocks[index] = (index, vp, rho, ' '.join(words[3:]))
        if len(rocks) > MAX_ROCKS: _refuse(f'A model lists at most {MAX_ROCKS} rocks.')
    if not rocks: _refuse('List at least one rock under "rocks".')
    if grid_at is None: _refuse('The file has no "grid" section.')

    def rock(token, row):
        if not token.isdigit(): _refuse(f'Line {row}: a grid value is a rock index.')
        index = _ints([token], f'Line {row}: a grid value is a rock index.')[0]
        if index not in rocks: _refuse(f'Line {row}: rock {index} is not listed under rocks.')
        return index
    grid = _section_grid(lines, grid_at, axes, rock)
    context = {'type': 'model-section', **axes, 'rock_count': len(rocks), 'velocity_unit': 'm/s', 'density_unit': 'kg/m3'}
    return dict(context=context, header=list(fields.items()), axes=_stated_axes(axes), rocks=list(rocks.values()), grid=grid)


def _seismic_section(text, declared):
    """sections.read_seismic_section, keeping an absent origin or polarity as None (the context says not-stated, unknown)."""
    _stated(declared)
    lines = text.splitlines()
    fields, start = _header(lines, '# ophiolite-seismic-section 1', ('grid',))
    unknown = sorted(set(fields) - set(AXES) - {'origin', 'polarity'})
    if unknown: _refuse(f'Unknown header field {unknown[0]}.')
    axes = _axes(fields)
    origin = _one(fields, 'origin', '') if 'origin' in fields else None
    if origin not in ('synthetic', 'not-stated', None): _refuse('Declare the origin as synthetic, or leave it out.')
    polarity = _one(fields, 'polarity', '') if 'polarity' in fields else None
    if polarity not in POLARITIES + (None,): _refuse(POLARITY)
    grid = _section_grid(lines, start + 1, axes, lambda token, row: _number(token, 'A sample', row))
    values = [v for r in grid for v in r]
    context = {'type': 'seismic-section', **axes, 'origin': origin or 'not-stated', 'polarity': polarity or 'unknown',
               'minimum': min(values), 'maximum': max(values)}
    return dict(context=context, header=list(fields.items()), axes=_stated_axes(axes), origin=origin, polarity=polarity, grid=grid)


READERS = {'esri-ascii-grid/1': (_grid, Grid), 'mesh-text/1': (_mesh, Mesh), 'opendtect-faultsticks/1': (_sticks, Sticks),
           'wavelet-text/1': (_wavelet, Wavelet), 'model-section-text/1': (_model_section, ModelSection),
           'seismic-section-text/1': (_seismic_section, SeismicSection)}


def _parse(kind, raw, declared):
    """The result of `raw` (bytes) read whole as `kind`, with `declared` as supplied; ReadRefused when it cannot be."""
    declared = declared or {}  # as read_typed: a falsy declaration is none
    if not isinstance(declared, dict): _refuse('Declared context must be an object.')
    text = _text(raw)
    reader, family = READERS[kind]
    return family(kind=kind, declared=dict(declared), **reader(text, declared))
