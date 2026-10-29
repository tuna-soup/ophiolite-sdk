"""E128 s1: the CSV kinds (well tops, deviation surveys, time-depth tables, point sets) and the well location, read whole.

The grammar is the server's (`asset_connectors.typed_reader`, `time_depth`): the same checks in the same order, with
the same sentences, codes, fields and rows, so a file is refused at the same first problem on both sides. What the
server normalizes away is kept here: column names as written (matched without case), every extra tops column as
text, file order. Cells are stripped of surrounding white space, as the server strips them; an empty cell is None.
`context` is the server's normalized context, computed here. Standard library only; nothing is contacted.
"""
import csv
import io
import json
import math
import re

from .results import Location, Table

MAX_ROWS = 10000
MAX_POINTS, MAX_ATTRIBUTES = 100000, 16
MAX_PAIRS = 100_000
TEXT_LIMIT = 128
ATTRIBUTE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
UNIT = re.compile(r'^[A-Za-z0-9 ./^()\-]{1,32}$')
IDENTITY = ('well', 'wellbore', 'well name', 'well_name', 'uwi')
FIELDS = {'Measured depth': 'md', 'Vertical depth': 'tvd', 'Inclination': 'inclination', 'Azimuth': 'azimuth', 'An attribute': 'attributes',
          'Easting (x)': 'x', 'Northing (y)': 'y', 'TVDSS': 'tvdss'}
DEPTH_TYPES = ('md', 'tvd', 'tvdss', 'unknown')
TIME_KINDS = ('one-way', 'two-way', 'unknown')
TIME_UNITS = ('ms', 's', 'us', 'unknown')
DECIMAL = re.compile(r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')
EXCEL = ('This is an Excel workbook; time-depth tables are read from CSV in this release. Save the sheet as CSV with the '
         'columns depth, time and optionally velocity.')
DLIS = 'This is a DLIS file; DLIS files are not read by this release.'


def _refuse(message, code='refused', field=None, row=None):
    from . import ReadRefused
    raise ReadRefused(message + ' No repair was applied.', code=code, field=field, row=row)


def _text(raw):
    if not raw: _refuse('The file is empty.', 'empty')
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError: _refuse('The file is not UTF-8 text.', 'not-utf8')
    if text.startswith('﻿'): text = text[1:]
    if '\x00' in text: _refuse('The file contains binary data.', 'binary')
    return text


def _number(token, what, row):
    where = f' on data row {row}' if row else ''
    try: value = float(token)
    except ValueError: _refuse(f'{what}{where} is not a number.', 'not-a-number', FIELDS.get(what, what), row or None)
    if not math.isfinite(value): _refuse(f'{what}{where} is not finite.', 'not-finite', FIELDS.get(what, what), row or None)
    return value


def _unit(value, what):
    if value in (None, '', 'unknown'): return 'unknown'
    if not isinstance(value, str) or not UNIT.fullmatch(value): _refuse(f'Declare the {what} as a short unit such as m or ft, or as unknown.', 'declaration', what)
    return value


def _choice(value, allowed, what):
    value = 'unknown' if value in (None, '') else value
    if value not in allowed: _refuse(f'Choose the {what} from: ' + ', '.join(allowed) + '.', 'declaration', what)
    return value


def _free(value, what):
    if value in (None, '', 'unknown'): return 'unknown'
    if not isinstance(value, str) or len(value) > TEXT_LIMIT or any(ord(c) < 32 for c in value): _refuse(f'The {what} must be short plain text.', 'declaration', what)
    return value


def _rows(text, required, optional, extra=False):
    """(header as written, header lowercased, rows of stripped cells in header order), refused as the server's `_rows`."""
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        written = [h.strip() for h in next(reader)]
        header = [h.lower() for h in written]
        if len(set(header)) != len(header): _refuse('The header repeats a column name.', 'header-repeated')
        if not set(required) <= set(header) or (set(header) - set(required) - set(optional) and not extra):
            _refuse('The header must name the columns ' + ', '.join(required) + (' and optionally ' + ', '.join(optional) if optional else '') + '.', 'header-columns')
        rows = []
        for line in reader:
            if not line or all(not cell.strip() for cell in line): continue
            if len(line) != len(header): _refuse(f'Data row {len(rows) + 1} has {len(line)} cells; the header has {len(header)}.', 'cell-count', None, len(rows) + 1)
            rows.append([cell.strip() for cell in line])
            if len(rows) > MAX_ROWS: _refuse(f'The file has more than {MAX_ROWS} data rows.', 'too-many-rows')
    except csv.Error: _refuse('The CSV structure is invalid (check quoting).', 'csv-structure')
    except StopIteration: _refuse('The file has no header row.', 'no-header')
    if not rows: _refuse('The file has no data rows.', 'no-rows')
    return written, header, rows


def _tops(text, declared):
    written, header, rows = _rows(text, ['name', 'md'], ['tvd', 'source'], extra=True)
    at = {name: i for i, name in enumerate(header)}
    for column in header:
        if column in ('name', 'md', 'tvd', 'source'): continue
        values = sorted({row[at[column]] for row in rows if row[at[column]]})
        if column in IDENTITY and len(values) > 1:
            _refuse(f'This file holds tops of {len(values)} wells (column {column}); upload one well\'s tops per file until multi-well tables arrive.', 'several-wells', column)
    kept, mds = [], []
    for i, row in enumerate(rows, 1):
        name = row[at['name']]
        if not name or len(name) > TEXT_LIMIT: _refuse(f'Top name on data row {i} is empty or longer than {TEXT_LIMIT} characters.', 'name-invalid', 'name', i)
        if row[at['md']] == '': _refuse(f'Measured depth on data row {i} is missing; a top needs a depth.', 'missing', 'md', i)
        cells = []
        for column, cell in zip(header, row):
            if column == 'md': cells.append(_number(cell, 'Measured depth', i)); mds.append(cells[-1])
            elif column == 'tvd': cells.append(None if cell == '' else _number(cell, 'Vertical depth', i))
            elif column == 'name': cells.append(cell)
            else: cells.append(cell or None)
        kept.append(cells)
    context = {'type': 'well-tops', 'depth_unit': _unit(declared.get('depth_unit'), 'depth unit'),
               'depth_basis': _choice(declared.get('depth_basis'), ['same-as-log', 'other', 'unknown'], 'depth basis'),
               'count': len(kept), 'tvd_provided': 'tvd' in header, 'md_range': [min(mds), max(mds)]}
    if declared.get('depth_datum') not in (None, ''): context['depth_datum'] = _free(declared['depth_datum'], 'depth datum')
    return written, kept, context


def _trajectory(text, declared):
    written, header, rows = _rows(text, ['md', 'inclination', 'azimuth'], ['tvd'])
    at = {name: i for i, name in enumerate(header)}
    kept, previous, missing = [], None, 0
    for i, row in enumerate(rows, 1):
        if row[at['md']] == '': _refuse(f'Measured depth on data row {i} is missing.', 'missing', 'md', i)
        md = _number(row[at['md']], 'Measured depth', i)
        if previous is not None and md <= previous: _refuse(f'Measured depth on data row {i} does not increase; stations must be in increasing measured depth.', 'not-increasing', 'md', i)
        previous = md
        inc = None if row[at['inclination']] == '' else _number(row[at['inclination']], 'Inclination', i)
        azi = None if row[at['azimuth']] == '' else _number(row[at['azimuth']], 'Azimuth', i)
        if inc is not None and not 0 <= inc <= 180: _refuse(f'Inclination on data row {i} is outside 0–180 degrees.', 'out-of-range', 'inclination', i)
        if azi is not None and not 0 <= azi < 360: _refuse(f'Azimuth on data row {i} is outside 0–360 degrees.', 'out-of-range', 'azimuth', i)
        tvd = None if 'tvd' not in at or row[at['tvd']] == '' else _number(row[at['tvd']], 'Vertical depth', i)
        values = {'md': md, 'inclination': inc, 'azimuth': azi, 'tvd': tvd}
        kept.append([values[column] for column in header])
        missing += inc is None or azi is None
    first, last = kept[0][at['md']], kept[-1][at['md']]
    context = {'type': 'trajectory', 'depth_unit': _unit(declared.get('depth_unit'), 'depth unit'), 'angle_unit': 'deg',
               'azimuth_reference': _choice(declared.get('azimuth_reference'), ['true-north', 'grid-north', 'magnetic-north', 'unknown'], 'azimuth reference'),
               'depth_datum': _free(declared.get('depth_datum'), 'depth datum'),
               'count': len(kept), 'missing_angle_count': missing, 'tvd_provided': 'tvd' in header, 'md_range': [first, last]}
    return written, kept, context


def _td_refuse(message, code='refused', field=None, row=None):
    _refuse(message, code, field, row)


def _td_number(cell, what, row):
    try: value = float(cell)
    except (TypeError, ValueError): _td_refuse(f'{what} on data row {row} is not a number.', 'not-a-number', what.lower(), row)
    if not math.isfinite(value): _td_refuse(f'{what} on data row {row} is not finite.', 'not-finite', what.lower(), row)
    return value


def _td_unit(value):
    if value in (None, '', 'unknown'): return 'unknown'
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9 ./^()\-]{1,32}', value):
        _td_refuse('Declare the depth unit as a short unit such as m or ft, or as unknown.', 'declaration', 'depth unit')
    return value


def _td_datum(value):
    if value in (None, '', 'unknown'): return 'unknown'
    if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value): _td_refuse('The datum must be short plain text.', 'declaration', 'datum')
    return value


def _decimal(text, what):
    if not isinstance(text, str) or len(text) > 24 or not DECIMAL.fullmatch(text):
        _td_refuse(f'Declare the {what} as a plain decimal number such as 12.5 (no exponent, a point as decimal mark), or leave it empty.', 'declaration', what)
    return float(text)


def _unread_format(head):
    if head[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' or (head[:4] == b'PK\x03\x04' and b'xl/' in head[:4096]): return EXCEL
    if any(head[at + 4:at + 15] == b'V1.00RECORD' for at in (0, 12)): return DLIS
    return None


def _time_depth(text, declared):
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        written = [h.strip() for h in next(reader)]
        header = [h.lower() for h in written]
        if len(set(header)) != len(header) or header[:2] != ['depth', 'time'] or header[2:] not in ([], ['velocity']):
            _td_refuse('The header must name the columns depth and time, and optionally velocity, in this order.', 'header-columns')
        rows = []
        for line in reader:
            if not line or all(not cell.strip() for cell in line): continue
            if len(line) != len(header): _td_refuse(f'Data row {len(rows) + 1} has {len(line)} cells; the header has {len(header)}.', 'cell-count', None, len(rows) + 1)
            rows.append([cell.strip() for cell in line])
            if len(rows) > MAX_PAIRS: _td_refuse(f'The table has more than {MAX_PAIRS:,} pairs.', 'too-many-rows')
    except csv.Error: _td_refuse('The CSV structure is invalid (check quoting).', 'csv-structure')
    except StopIteration: _td_refuse('The file has no header row.', 'no-header')
    with_velocity = len(header) == 3
    kept = []
    for i, row in enumerate(rows, 1):
        if row[0] == '': _td_refuse(f'Depth on data row {i} is missing; every pair needs a depth.', 'missing', 'depth', i)
        if row[1] == '': _td_refuse(f'Time on data row {i} is missing; every pair needs a time.', 'missing', 'time', i)
        d, t = _td_number(row[0], 'Depth', i), _td_number(row[1], 'Time', i)
        if kept and d <= kept[-1][0]: _td_refuse(f'Depth on data row {i} does not increase; pairs must be in strictly increasing depth.', 'not-increasing', 'depth', i)
        if kept and t <= kept[-1][1]: _td_refuse(f'Time on data row {i} does not increase; pairs must be in strictly increasing time.', 'not-increasing', 'time', i)
        cells = [d, t]
        if with_velocity: cells.append(None if row[2] == '' else _td_number(row[2], 'Velocity', i))
        kept.append(cells)
    if len(kept) < 2: _td_refuse('A time-depth table needs at least two pairs.', 'no-rows')
    elevation = declared.get('seismic_reference_elevation')
    context = {'type': 'time-depth',
               'depth_type': _choice(declared.get('depth_type'), DEPTH_TYPES, 'depth type'),
               'depth_unit': _td_unit(declared.get('depth_unit')),
               'time_kind': _choice(declared.get('time_kind'), TIME_KINDS, 'time kind'),
               'time_unit': _choice(declared.get('time_unit'), TIME_UNITS, 'time unit'),
               'datum': _td_datum(declared.get('datum')),
               'seismic_reference_elevation': None if elevation in (None, '') else _decimal(elevation, 'seismic reference elevation'),
               'count': len(kept), 'depth_range': [kept[0][0], kept[-1][0]], 'time_range': [kept[0][1], kept[-1][1]],
               'velocity_provided': with_velocity}
    return written, kept, context


def _crs(value):
    if value in (None, '', 'unknown'): return 'unknown'
    if not isinstance(value, str) or not re.fullmatch(r'EPSG:[0-9]{4,6}', value): _refuse('Declare the coordinate reference system as EPSG:<code>, or as unknown.')
    return value


def _spatial(declared):
    return {'crs': _crs(declared.get('crs')), 'xy_unit': _unit(declared.get('xy_unit'), 'map unit'), 'z_unit': _unit(declared.get('z_unit'), 'value unit'),
            'z_meaning': _choice(declared.get('z_meaning'), ['depth', 'elevation', 'time', 'unknown'], 'value meaning'),
            'positive': _choice(declared.get('positive'), ['up', 'down', 'unknown'], 'positive direction'),
            'vertical_datum': _free(declared.get('vertical_datum'), 'vertical datum')}


def _points(text, declared):
    """The server's `_points`: the header stripped, not lowercased; rows numbered with blank records counted; every row
    checked as it is read. A row is (x, y[, z], attribute values...) in header order."""
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try: written = [h.strip() for h in next(reader)]
    except (StopIteration, csv.Error): _refuse('The file has no header row.', 'no-header')
    lowered = [h.lower() for h in written]
    if lowered[:2] != ['x', 'y']: _refuse('The first columns must be x and y (then optionally z and attributes).', 'header-columns')
    has_z = len(lowered) > 2 and lowered[2] == 'z'
    attributes = written[3 if has_z else 2:]
    if len(attributes) > MAX_ATTRIBUTES or len(set(lowered)) != len(lowered) or not all(ATTRIBUTE.fullmatch(a) for a in attributes):
        _refuse(f'Use at most {MAX_ATTRIBUTES} distinct attribute columns (letters, digits, underscores).', 'attributes')
    kept = []
    try:
        for row, line in enumerate(reader, 1):
            if not line or all(not c.strip() for c in line): continue
            if len(line) != len(written): _refuse(f'Data row {row} has {len(line)} cells; the header has {len(written)}.', 'cell-count', None, row)
            cells = [c.strip() for c in line]
            if cells[0] == '' or cells[1] == '': _refuse(f'Data row {row} has no x or y.', 'missing', 'x' if cells[0] == '' else 'y', row)
            values = [_number(cells[0], 'x', row), _number(cells[1], 'y', row)]
            if has_z: values.append(None if cells[2] == '' else _number(cells[2], 'z', row))
            values += [None if c == '' else _number(c, 'An attribute', row) for c in cells[3 if has_z else 2:]]
            kept.append(values)
            if len(kept) > MAX_POINTS: _refuse(f'The file has more than {MAX_POINTS} points.', 'too-many-rows')
    except csv.Error: _refuse('The CSV structure is invalid (check quoting).', 'csv-structure')
    if not kept: _refuse('The file has no data rows.', 'no-rows')
    xs, ys = [p[0] for p in kept], [p[1] for p in kept]
    zs = [p[2] for p in kept] if has_z else [None] * len(kept)
    present = [z for z in zs if z is not None]
    context = {'type': 'point-set', **_spatial(declared), 'count': len(kept), 'z_provided': has_z, 'attributes': attributes,
               'missing_z_count': sum(z is None for z in zs) if has_z else 0,
               'x_range': [min(xs), max(xs)], 'y_range': [min(ys), max(ys)], 'z_range': [min(present), max(present)] if present else None}
    return written, kept, context


def _well_location(text, declared):
    """The server's `_well_location`; `elevation_reference` is kept as the JSON gives it, normalized only in `context`."""
    if declared: _refuse('A well location states its CRS in the file; nothing is declared beside it.')
    try: value = json.loads(text, parse_constant=lambda c: _refuse('A well location holds finite numbers only.'))
    except ValueError: _refuse('A well location is one JSON object with x, y, crs and elevation_reference.')  # NaN included (ReadRefused is one)
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'crs', 'elevation_reference'}:
        _refuse('A well location is one JSON object with exactly x, y, crs and elevation_reference.')
    for k in ('x', 'y'):
        if not isinstance(value[k], (int, float)) or isinstance(value[k], bool): _refuse(f'{k} is not a number.')
    x, y = value['x'], value['y']
    if not all(math.isfinite(v) for v in (x, y)): _refuse('Coordinates must be finite.')
    crs = value['crs']
    if not isinstance(crs, str) or not (crs in ('OGC:CRS84', 'unknown') or re.fullmatch(r'EPSG:[0-9]{4,6}', crs)):
        _refuse('State the coordinate reference system as EPSG:<code>, OGC:CRS84 or unknown.')
    if crs in ('OGC:CRS84', 'EPSG:4326') and (abs(x) > 180 or abs(y) > 90):
        _refuse('Longitude and latitude are outside their range for this CRS.')
    reference = _choice(value['elevation_reference'], ['unknown', 'GL', 'KB', 'MSL'], 'elevation reference')
    return Location('well-location/1', {}, {'type': 'well-location', 'crs': crs, 'elevation_reference': reference},
                    float(x), float(y), crs, value['elevation_reference'])


READERS = {'well-tops-csv/1': _tops, 'deviation-csv/1': _trajectory, 'time-depth-csv/1': _time_depth, 'points-csv/1': _points,
           'well-location/1': _well_location}


def _parse(kind, raw, declared):
    """The result of `raw` (bytes) read whole as `kind`, with `declared` as supplied; ReadRefused when it cannot be."""
    declared = declared or {}  # as read_typed: a falsy declaration is none
    if not isinstance(declared, dict): _refuse('Declared context must be an object.')
    if kind == 'time-depth-csv/1':
        sentence = _unread_format(raw[:4096])
        if sentence: _refuse(sentence)
    text = _text(raw)
    if kind == 'well-location/1': return _well_location(text, declared)
    columns, rows, context = READERS[kind](text, declared)
    return Table(kind, dict(declared), context, columns, rows)
