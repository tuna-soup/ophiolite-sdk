"""E128 s1: ophiolite.readers reads the CSV kinds and the well location whole. Every input is a byte literal written
here (board RULING e128s1: no files, nothing copied from a third-party file). Every expected value is a literal
written from the grammar (E128-readers-S1-COMMIT-STRATEGY.md); the server's reader is then asked to agree (parity),
never used as the expectation."""
from pathlib import Path
from types import MappingProxyType

import pytest

from ophiolite import readers, writers
from ophiolite.readers import Location, ReadRefused, Table

NO_REPAIR = ' No repair was applied.'


def typed(actual, expected, where):
    """`actual` equals `expected` with the type at every level: a dict expects a read-only mapping, a tuple a tuple."""
    if isinstance(expected, dict):
        assert type(actual) is MappingProxyType, where
        assert list(actual) == list(expected), (where, list(actual), list(expected))
        for key in expected: typed(actual[key], expected[key], where + '.' + key)
    elif isinstance(expected, tuple):
        assert type(actual) is tuple and len(actual) == len(expected), (where, actual, expected)
        for i, (a, e) in enumerate(zip(actual, expected)): typed(a, e, '%s[%d]' % (where, i))
    else:
        assert type(actual) is type(expected) and actual == expected, (where, actual, expected)


TOPS_DECLARED = {'depth_unit': 'm', 'depth_basis': 'same-as-log'}

# name: (kind, bytes, declared, expected) where expected is {columns, rows, context} or a refusal (sentence, code, field, row)
CASES = {
    # --- well tops ---
    'tops: name, md, tvd, source, an extra kept as text': (
        'well-tops-csv/1', b'Name,MD,tvd,Source,UWI\nNorth Sea Group,1200.5,,pick,001\nDCC,0,1190,,001\n', TOPS_DECLARED,
        {'columns': ('Name', 'MD', 'tvd', 'Source', 'UWI'),
         'rows': (('North Sea Group', 1200.5, None, 'pick', '001'), ('DCC', 0.0, 1190.0, None, '001')),
         'context': {'type': 'well-tops', 'depth_unit': 'm', 'depth_basis': 'same-as-log', 'count': 2, 'tvd_provided': True,
                     'md_range': [0.0, 1200.5]}}),
    'tops: a BOM, CRLF, a quoted name with a comma, a blank line, a depth datum': (
        'well-tops-csv/1', '﻿name,md\r\n"Rijnland, Upper",1500\r\n\r\n  NSB  , 1450.25 \r\n'.encode(),
        {'depth_unit': 'ft', 'depth_datum': 'rotary table'},
        {'columns': ('name', 'md'), 'rows': (('Rijnland, Upper', 1500.0), ('NSB', 1450.25)),
         'context': {'type': 'well-tops', 'depth_unit': 'ft', 'depth_basis': 'unknown', 'count': 2, 'tvd_provided': False,
                     'md_range': [1450.25, 1500.0], 'depth_datum': 'rotary table'}}),
    'tops: no declarations, repeated names in file order': (
        'well-tops-csv/1', b'name,md\nDCC,1300\nNSB,1200\nDCC,1250\n', None,
        {'columns': ('name', 'md'), 'rows': (('DCC', 1300.0), ('NSB', 1200.0), ('DCC', 1250.0)),
         'context': {'type': 'well-tops', 'depth_unit': 'unknown', 'depth_basis': 'unknown', 'count': 3, 'tvd_provided': False,
                     'md_range': [1200.0, 1300.0]}}),
    'tops: an empty tvd column is a tvd column, falsy declarations are none': (
        'well-tops-csv/1', b'name,md,tvd\nDCC,1300,\nNSB,1200,\n', [],
        {'columns': ('name', 'md', 'tvd'), 'rows': (('DCC', 1300.0, None), ('NSB', 1200.0, None)),
         'context': {'type': 'well-tops', 'depth_unit': 'unknown', 'depth_basis': 'unknown', 'count': 2, 'tvd_provided': True,
                     'md_range': [1200.0, 1300.0]}}),
    'tops: a wrong cell count after a non-number is refused for the cell count': (
        'well-tops-csv/1', b'name,md\nDCC,x\nNSB,1,2\n', {}, ('Data row 2 has 3 cells; the header has 2.' + NO_REPAIR, 'cell-count', None, 2)),
    'tops: a row after a blank line is numbered among the rows read': (
        'well-tops-csv/1', b'name,md\nDCC,1\n\nNSB,a\n', {}, ('Measured depth on data row 2 is not a number.' + NO_REPAIR, 'not-a-number', 'md', 2)),
    'tops: a broken quote in the header': (
        'well-tops-csv/1', b'"name,md\nDCC,1\n', {}, ('The CSV structure is invalid (check quoting).' + NO_REPAIR, 'csv-structure', None, None)),
    'tops: several wells': (
        'well-tops-csv/1', b'well,name,md\nA-1,DCC,1300\nB-2,DCC,1250\n', {},
        ('This file holds tops of 2 wells (column well); upload one well\'s tops per file until multi-well tables arrive.' + NO_REPAIR,
         'several-wells', 'well', None)),
    'tops: a row with an empty name and an empty md fails at the name': (
        'well-tops-csv/1', b'name,md,source\nDCC,1300,\n,,pick\n', {}, ('Top name on data row 2 is empty or longer than 128 characters.' + NO_REPAIR, 'name-invalid', 'name', 2)),
    'tops: a missing md': (
        'well-tops-csv/1', b'name,md\nDCC,\n', {}, ('Measured depth on data row 1 is missing; a top needs a depth.' + NO_REPAIR, 'missing', 'md', 1)),
    'tops: md not finite': (
        'well-tops-csv/1', b'name,md\nDCC,inf\n', {}, ('Measured depth on data row 1 is not finite.' + NO_REPAIR, 'not-finite', 'md', 1)),
    'tops: a repeated header in another case': (
        'well-tops-csv/1', b'name,md,MD\nDCC,1,2\n', {}, ('The header repeats a column name.' + NO_REPAIR, 'header-repeated', None, None)),
    'tops: no md column': (
        'well-tops-csv/1', b'name,depth\nDCC,1\n', {},
        ('The header must name the columns name, md and optionally tvd, source.' + NO_REPAIR, 'header-columns', None, None)),
    'tops: a wrong cell count': (
        'well-tops-csv/1', b'name,md\nDCC,1\nNSB,2,3\n', {}, ('Data row 2 has 3 cells; the header has 2.' + NO_REPAIR, 'cell-count', None, 2)),
    'tops: a header only': ('well-tops-csv/1', b'name,md\n', {}, ('The file has no data rows.' + NO_REPAIR, 'no-rows', None, None)),
    'tops: an empty file': ('well-tops-csv/1', b'', {}, ('The file is empty.' + NO_REPAIR, 'empty', None, None)),
    'tops: not UTF-8': ('well-tops-csv/1', b'name,md\n\xff,1\n', {}, ('The file is not UTF-8 text.' + NO_REPAIR, 'not-utf8', None, None)),
    'tops: a NUL byte': ('well-tops-csv/1', b'name,md\nD\x00CC,1\n', {}, ('The file contains binary data.' + NO_REPAIR, 'binary', None, None)),
    'tops: broken quoting': ('well-tops-csv/1', b'name,md\n"DCC,1\n', {}, ('The CSV structure is invalid (check quoting).' + NO_REPAIR, 'csv-structure', None, None)),
    'tops: a depth unit that is not a unit': (
        'well-tops-csv/1', b'name,md\nDCC,1\n', {'depth_unit': 'metres; really'},
        ('Declare the depth unit as a short unit such as m or ft, or as unknown.' + NO_REPAIR, 'declaration', 'depth unit', None)),
    'tops: a depth basis outside the list': (
        'well-tops-csv/1', b'name,md\nDCC,1\n', {'depth_basis': 'kelly'},
        ('Choose the depth basis from: same-as-log, other, unknown.' + NO_REPAIR, 'declaration', 'depth basis', None)),
    'tops: declarations that are not an object': (
        'well-tops-csv/1', b'name,md\nDCC,1\n', ['m'], ('Declared context must be an object.' + NO_REPAIR, 'refused', None, None)),
    # --- deviation surveys ---
    'deviation: columns in another order, empty angles, tvd': (
        'deviation-csv/1', b'azimuth,MD,inclination,tvd\n0,0,0,0\n,30,2.5,\n359.5,60,,59.9\n',
        {'depth_unit': 'm', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
        {'columns': ('azimuth', 'MD', 'inclination', 'tvd'), 'rows': ((0.0, 0.0, 0.0, 0.0), (None, 30.0, 2.5, None), (359.5, 60.0, None, 59.9)),
         'context': {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB',
                     'count': 3, 'missing_angle_count': 2, 'tvd_provided': True, 'md_range': [0.0, 60.0]}}),
    'deviation: md that does not increase': (
        'deviation-csv/1', b'md,inclination,azimuth\n10,0,0\n10,1,1\n', {},
        ('Measured depth on data row 2 does not increase; stations must be in increasing measured depth.' + NO_REPAIR, 'not-increasing', 'md', 2)),
    'deviation: an inclination out of range': (
        'deviation-csv/1', b'md,inclination,azimuth\n10,181,0\n', {},
        ('Inclination on data row 1 is outside 0–180 degrees.' + NO_REPAIR, 'out-of-range', 'inclination', 1)),
    'deviation: an azimuth of 360': (
        'deviation-csv/1', b'md,inclination,azimuth\n10,1,360\n', {}, ('Azimuth on data row 1 is outside 0–360 degrees.' + NO_REPAIR, 'out-of-range', 'azimuth', 1)),
    'deviation: an extra column': (
        'deviation-csv/1', b'md,inclination,azimuth,dls\n10,1,1,0\n', {},
        ('The header must name the columns md, inclination, azimuth and optionally tvd.' + NO_REPAIR, 'header-columns', None, None)),
    'deviation: an azimuth reference outside the list': (
        'deviation-csv/1', b'md,inclination,azimuth\n10,1,1\n', {'azimuth_reference': 'north'},
        ('Choose the azimuth reference from: true-north, grid-north, magnetic-north, unknown.' + NO_REPAIR, 'declaration', 'azimuth reference', None)),
    # --- time-depth tables ---
    'time-depth: velocity with an empty cell, every declaration': (
        'time-depth-csv/1', b'Depth,Time,Velocity\r\n100,0.1,2000\r\n250.5,0.2,\r\n',
        {'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 's', 'datum': 'MSL', 'seismic_reference_elevation': '12.5'},
        {'columns': ('Depth', 'Time', 'Velocity'), 'rows': ((100.0, 0.1, 2000.0), (250.5, 0.2, None)),
         'context': {'type': 'time-depth', 'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 's', 'datum': 'MSL',
                     'seismic_reference_elevation': 12.5, 'count': 2, 'depth_range': [100.0, 250.5], 'time_range': [0.1, 0.2],
                     'velocity_provided': True}}),
    'time-depth: no velocity, no declarations': (
        'time-depth-csv/1', b'depth,time\n0,0\n10,5\n', {},
        {'columns': ('depth', 'time'), 'rows': ((0.0, 0.0), (10.0, 5.0)),
         'context': {'type': 'time-depth', 'depth_type': 'unknown', 'depth_unit': 'unknown', 'time_kind': 'unknown', 'time_unit': 'unknown',
                     'datum': 'unknown', 'seismic_reference_elevation': None, 'count': 2, 'depth_range': [0.0, 10.0], 'time_range': [0.0, 5.0],
                     'velocity_provided': False}}),
    'time-depth: a DLIS storage unit label': (
        'time-depth-csv/1', b'   1V1.00RECORD8192Default Storage Set', {},
        ('This is a DLIS file; DLIS files are not read by this release.' + NO_REPAIR, 'refused', None, None)),
    'time-depth: a wrong cell count after a non-number is refused for the cell count': (
        'time-depth-csv/1', b'depth,time\n0,x\n1,2,3\n', {}, ('Data row 2 has 3 cells; the header has 2.' + NO_REPAIR, 'cell-count', None, 2)),
    'time-depth: columns out of order': (
        'time-depth-csv/1', b'time,depth\n0,0\n1,1\n', {},
        ('The header must name the columns depth and time, and optionally velocity, in this order.' + NO_REPAIR, 'header-columns', None, None)),
    'time-depth: a time that does not increase': (
        'time-depth-csv/1', b'depth,time\n0,5\n10,5\n', {},
        ('Time on data row 2 does not increase; pairs must be in strictly increasing time.' + NO_REPAIR, 'not-increasing', 'time', 2)),
    'time-depth: one pair': ('time-depth-csv/1', b'depth,time\n0,5\n', {}, ('A time-depth table needs at least two pairs.' + NO_REPAIR, 'no-rows', None, None)),
    'time-depth: a missing time': (
        'time-depth-csv/1', b'depth,time\n0,\n1,2\n', {}, ('Time on data row 1 is missing; every pair needs a time.' + NO_REPAIR, 'missing', 'time', 1)),
    'time-depth: an Excel workbook': (
        'time-depth-csv/1', b'PK\x03\x04' + b'\x00' * 26 + b'xl/workbook.xml', {},
        ('This is an Excel workbook; time-depth tables are read from CSV in this release. Save the sheet as CSV with the columns depth, time '
         'and optionally velocity.' + NO_REPAIR, 'refused', None, None)),
    'time-depth: an elevation with an exponent': (
        'time-depth-csv/1', b'depth,time\n0,0\n1,1\n', {'seismic_reference_elevation': '1e3'},
        ('Declare the seismic reference elevation as a plain decimal number such as 12.5 (no exponent, a point as decimal mark), or leave it empty.'
         + NO_REPAIR, 'declaration', 'seismic reference elevation', None)),
    # --- point sets ---
    'points: a mixed-case header, z, attributes as written, empty z and attribute cells': (
        'points-csv/1', b'X,Y,Z,Depth_m,porosity\n100.5,200,-5,1,\n101,201.25,,2,0.25\n',
        {'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up'},
        {'columns': ('X', 'Y', 'Z', 'Depth_m', 'porosity'), 'rows': ((100.5, 200.0, -5.0, 1.0, None), (101.0, 201.25, None, 2.0, 0.25)),
         'context': {'type': 'point-set', 'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up',
                     'vertical_datum': 'unknown', 'count': 2, 'z_provided': True, 'attributes': ['Depth_m', 'porosity'], 'missing_z_count': 1,
                     'x_range': [100.5, 101.0], 'y_range': [200.0, 201.25], 'z_range': [-5.0, -5.0]}}),
    'points: no z, the third column an attribute': (
        'points-csv/1', b'x,y,depth\n1,2,3\n0,5,\n', {},
        {'columns': ('x', 'y', 'depth'), 'rows': ((1.0, 2.0, 3.0), (0.0, 5.0, None)),
         'context': {'type': 'point-set', 'crs': 'unknown', 'xy_unit': 'unknown', 'z_unit': 'unknown', 'z_meaning': 'unknown',
                     'positive': 'unknown', 'vertical_datum': 'unknown', 'count': 2, 'z_provided': False, 'attributes': ['depth'],
                     'missing_z_count': 0, 'x_range': [0.0, 1.0], 'y_range': [2.0, 5.0], 'z_range': None}}),
    'points: a missing y': (
        'points-csv/1', b'x,y\n1,2\n3,\n', {}, ('Data row 2 has no x or y.' + NO_REPAIR, 'missing', 'y', 2)),
    'points: a non-number before a wrong cell count is refused for the number': (
        'points-csv/1', b'x,y\n1,a\n2,3,4\n', {}, ('y on data row 1 is not a number.' + NO_REPAIR, 'not-a-number', 'y', 1)),
    'points: a row after a blank line is numbered with the blank line counted': (
        'points-csv/1', b'x,y\n1,2\n\n3,a\n', {}, ('y on data row 3 is not a number.' + NO_REPAIR, 'not-a-number', 'y', 3)),
    'points: a broken quote in the header is no header': (
        'points-csv/1', b'"x,y\n1,2\n', {}, ('The file has no header row.' + NO_REPAIR, 'no-header', None, None)),
    'points: an attribute repeated in another case': (
        'points-csv/1', b'x,y,phi,PHI\n1,2,3,4\n', {},
        ('Use at most 16 distinct attribute columns (letters, digits, underscores).' + NO_REPAIR, 'attributes', None, None)),
    'points: y first': (
        'points-csv/1', b'y,x\n1,2\n', {}, ('The first columns must be x and y (then optionally z and attributes).' + NO_REPAIR, 'header-columns', None, None)),
    'points: a CRS that is not EPSG': (
        'points-csv/1', b'x,y\n1,2\n', {'crs': 'RD New'},
        ('Declare the coordinate reference system as EPSG:<code>, or as unknown.' + NO_REPAIR, 'refused', None, None)),
    # --- well locations (result literals in LOCATIONS) ---
    'location: a declaration beside the file': (
        'well-location/1', b'{"x": 1, "y": 2, "crs": "unknown", "elevation_reference": "KB"}', {'crs': 'EPSG:28992'},
        ('A well location states its CRS in the file; nothing is declared beside it.' + NO_REPAIR, 'refused', None, None)),
    'location: NaN ends as the JSON sentence': (
        'well-location/1', b'{"x": NaN, "y": 1, "crs": "unknown", "elevation_reference": "KB"}', {},
        ('A well location is one JSON object with x, y, crs and elevation_reference.' + NO_REPAIR, 'refused', None, None)),
    'location: 1e999 is not finite': (
        'well-location/1', b'{"x": 1e999, "y": 1, "crs": "unknown", "elevation_reference": "KB"}', {},
        ('Coordinates must be finite.' + NO_REPAIR, 'refused', None, None)),
    'location: an extra key': (
        'well-location/1', b'{"x": 1, "y": 2, "crs": "unknown", "elevation_reference": "KB", "name": "A-1"}', {},
        ('A well location is one JSON object with exactly x, y, crs and elevation_reference.' + NO_REPAIR, 'refused', None, None)),
    'location: a bool coordinate': (
        'well-location/1', b'{"x": 1, "y": true, "crs": "unknown", "elevation_reference": "KB"}', {},
        ('y is not a number.' + NO_REPAIR, 'refused', None, None)),
    'location: CRS84 out of range': (
        'well-location/1', b'{"x": 52, "y": 95, "crs": "OGC:CRS84", "elevation_reference": "KB"}', {},
        ('Longitude and latitude are outside their range for this CRS.' + NO_REPAIR, 'refused', None, None)),
    'location: an elevation reference outside the list': (
        'well-location/1', b'{"x": 1, "y": 2, "crs": "unknown", "elevation_reference": "RT"}', {},
        ('Choose the elevation reference from: unknown, GL, KB, MSL.' + NO_REPAIR, 'declaration', 'elevation reference', None)),
    'time-depth: a time unit outside the list': (
        'time-depth-csv/1', b'depth,time\n0,0\n1,1\n', {'time_unit': 'msec'},
        ('Choose the time unit from: ms, s, us, unknown.' + NO_REPAIR, 'declaration', 'time unit', None)),
}

# name: (bytes, x, y, crs, elevation_reference as given, the normalized elevation reference in context)
LOCATIONS = {
    'location: integers become floats, null is kept and is unknown in context': (
        b'{"x": 4, "y": 52.5, "crs": "EPSG:4326", "elevation_reference": null}', 4.0, 52.5, 'EPSG:4326', None, 'unknown'),
    'location: an empty reference is kept as written': (
        b'{"elevation_reference": "", "crs": "unknown", "y": -1.5e3, "x": 155000.25}', 155000.25, -1500.0, 'unknown', '', 'unknown'),
    'location: CRS84 at the edge, KB': (
        b'\xef\xbb\xbf{"x": -180, "y": 90, "crs": "OGC:CRS84", "elevation_reference": "KB"}\n', -180.0, 90.0, 'OGC:CRS84', 'KB', 'KB'),
}

ACCEPTED = [name for name, case in CASES.items() if isinstance(case[3], dict)]
REFUSED = [name for name, case in CASES.items() if isinstance(case[3], tuple)]


def written(tmp_path, raw):
    path = tmp_path / 'input'
    path.write_bytes(raw)
    return path


@pytest.mark.parametrize('name', ACCEPTED)
def test_a_file_is_read_whole_with_every_value_and_its_type(tmp_path, name):
    kind, raw, declared, expected = CASES[name]
    path = written(tmp_path, raw)
    for result in (readers.read(path=path, kind=kind, declared=declared), readers.read(Version(path=path, kind=kind, declared=declared))):
        assert type(result) is Table and result.kind == kind
        typed(result.declared, dict(declared or {}), 'declared')
        typed(result.columns, expected['columns'], 'columns')
        typed(result.rows, expected['rows'], 'rows')
        typed(result.context, freeze(expected['context']), 'context')


class Version:
    def __init__(self, **attributes): self.__dict__.update(attributes)


@pytest.mark.parametrize('name', list(LOCATIONS))
def test_a_well_location_is_read_with_its_reference_as_given(tmp_path, name):
    raw, x, y, crs, reference, normalized = LOCATIONS[name]
    path = written(tmp_path, raw)
    for result in (readers.read(path=path, kind='well-location/1'), readers.read(Version(path=path, kind='well-location/1', declared={}))):
        assert type(result) is Location and result.kind == 'well-location/1'
        typed(result.declared, {}, 'declared')
        typed(result.context, {'type': 'well-location', 'crs': crs, 'elevation_reference': normalized}, 'context')
        typed((result.x, result.y, result.crs, result.elevation_reference), (x, y, crs, reference), 'fields')
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    context, data, _ = typed_reader.read_typed('well-location/1', raw)
    assert thawed(result.context) == context and {'x': result.x, 'y': result.y} == data


def test_a_version_passes_its_declarations(tmp_path):
    """The version form reads `version.declared`, not the call's: a declared depth unit reaches the result and its context."""
    path = written(tmp_path, b'name,md\nDCC,1\n')
    result = readers.read(Version(path=path, kind='well-tops-csv/1', declared={'depth_unit': 'ft', 'depth_datum': 'KB'}))
    typed(result.declared, {'depth_unit': 'ft', 'depth_datum': 'KB'}, 'declared')
    typed(result.context, {'type': 'well-tops', 'depth_unit': 'ft', 'depth_basis': 'unknown', 'count': 1, 'tvd_provided': False,
                           'md_range': (1.0, 1.0), 'depth_datum': 'KB'}, 'context')


def freeze(value):
    """The context literal with its lists as tuples, the shape a result holds."""
    if isinstance(value, dict): return {k: freeze(v) for k, v in value.items()}
    if isinstance(value, list): return tuple(freeze(v) for v in value)
    return value


@pytest.mark.parametrize('name', REFUSED)
def test_a_file_that_cannot_be_read_whole_is_refused_with_the_sentence_code_field_and_row(tmp_path, name):
    kind, raw, declared, expected = CASES[name]
    with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind=kind, declared=declared)
    error = caught.value
    assert (str(error), error.code, error.field, error.row) == expected


def server_view(result):
    """The SDK result in the shape of the server reader's data (main strategy D1: parity over this projection)."""
    columns = [c.lower() for c in result.columns]
    rows = [dict(zip(columns, row)) for row in result.rows]
    if result.kind == 'well-tops-csv/1':
        return {'tops': [{'name': r['name'], 'md': r['md'], 'tvd': r.get('tvd'), 'source': r.get('source')} for r in rows]}
    if result.kind == 'deviation-csv/1':
        return {'stations': [{'md': r['md'], 'inclination': r['inclination'], 'azimuth': r['azimuth'], 'tvd': r.get('tvd')} for r in rows]}
    if result.kind == 'time-depth-csv/1':
        return {'depth': [r['depth'] for r in rows], 'time': [r['time'] for r in rows],
                'velocity': [r['velocity'] for r in rows] if 'velocity' in columns else None}
    if result.kind == 'points-csv/1':
        start = 3 if result.context['z_provided'] else 2
        return {'points': [[row[0], row[1], row[2] if start == 3 else None] for row in result.rows],
                'attributes': [{'name': name, 'values': [row[start + k] for row in result.rows]} for k, name in enumerate(result.columns[start:])]}
    raise AssertionError(result.kind)


def thawed(value):
    if isinstance(value, MappingProxyType): return {k: thawed(v) for k, v in value.items()}
    if isinstance(value, tuple): return [thawed(v) for v in value]
    return value


@pytest.mark.parametrize('name', list(CASES))
def test_the_server_reader_agrees_on_every_case(tmp_path, name):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    kind, raw, declared, expected = CASES[name]
    try: server = typed_reader.read_typed(kind, raw, declared)
    except typed_reader.TypedReadError as refused: server = refused
    try: ours = readers.read(path=written(tmp_path, raw), kind=kind, declared=declared)
    except ReadRefused as refused: ours = refused
    if isinstance(server, Exception):
        assert isinstance(ours, ReadRefused), (name, ours)
        assert (str(ours), ours.code, ours.field, ours.row) == (str(server), server.code, server.field, server.row)
    else:
        assert not isinstance(ours, Exception), (name, ours)
        context, data, _ = server
        assert thawed(ours.context) == context
        assert server_view(ours) == data


LIMITS = [  # kind, header, one row from its index, the last row read, the limit, the refusal at limit + 1
    ('well-tops-csv/1', b'name,md\n', lambda i: b'T%d,%d\n' % (i, i), ('T9999', 9999.0), 10000, 'The file has more than 10000 data rows.'),
    ('deviation-csv/1', b'md,inclination,azimuth\n', lambda i: b'%d,1,2\n' % i, (9999.0, 1.0, 2.0), 10000, 'The file has more than 10000 data rows.'),
    ('time-depth-csv/1', b'depth,time\n', lambda i: b'%d,%d\n' % (i, i), (99999.0, 99999.0), 100000,
     'The table has more than 100,000 pairs.'),
    ('points-csv/1', b'x,y\n', lambda i: b'%d,%d\n' % (i, i), (99999.0, 99999.0), 100000, 'The file has more than 100000 points.'),
]


def test_a_point_set_holds_sixteen_attributes_not_seventeen(tmp_path):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    names = [b'a%d' % i for i in range(17)]
    for count in (16, 17):
        raw = b','.join([b'x', b'y'] + names[:count]) + b'\n' + b','.join([b'1'] * (count + 2)) + b'\n'
        if count == 16:
            result = readers.read(path=written(tmp_path, raw), kind='points-csv/1')
            typed(result.context['attributes'], tuple('a%d' % i for i in range(16)), 'attributes')
            assert typed_reader.read_typed('points-csv/1', raw)[0]['attributes'] == ['a%d' % i for i in range(16)]
        else:
            with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind='points-csv/1')
            assert caught.value.code == 'attributes'
            with pytest.raises(typed_reader.TypedReadError): typed_reader.read_typed('points-csv/1', raw)


@pytest.mark.parametrize('kind, header, line, last, limit, sentence', LIMITS)
def test_the_row_limits_are_the_servers(tmp_path, kind, header, line, last, limit, sentence):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    raw = header + b''.join(line(i) for i in range(limit))
    result = readers.read(path=written(tmp_path, raw), kind=kind)
    assert len(result.rows) == limit and result.rows[-1] == last
    assert typed_reader.read_typed(kind, raw)[0]['count'] == limit
    raw += line(limit)
    with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind=kind)
    assert (str(caught.value), caught.value.code) == (sentence + NO_REPAIR, 'too-many-rows')
    with pytest.raises(typed_reader.TypedReadError) as server: typed_reader.read_typed(kind, raw)
    assert (str(server.value), server.value.code) == (sentence + NO_REPAIR, 'too-many-rows')


def test_what_a_writer_writes_reads_back_as_given(tmp_path):
    tops = writers.write_tops([{'name': 'DCC', 'md': 1200.5, 'tvd': 1190.25, 'source': 'pick'}, {'name': 'NSB', 'md': 1300}],
                              depth_unit='m', depth_basis='unknown')
    result = readers.read(path=written(tmp_path, tops.bytes), kind=tops.profile, declared=tops.declared)
    typed(result.rows, (('DCC', 1200.5, 1190.25, 'pick'), ('NSB', 1300.0, None, None)), 'tops rows')
    typed(result.declared, {'depth_unit': 'm'}, 'tops declared')
    survey = writers.write_survey([{'md': 0, 'inclination': 0, 'azimuth': 0}, {'md': 30, 'inclination': None, 'azimuth': 45.5, 'tvd': 29.9}],
                                  depth_unit='ft', azimuth_reference='true-north', depth_datum='unknown')
    result = readers.read(path=written(tmp_path, survey.bytes), kind=survey.profile, declared=survey.declared)
    typed(result.rows, ((0.0, 0.0, 0.0, None), (30.0, None, 45.5, 29.9)), 'survey rows')
    typed(result.context['azimuth_reference'], 'true-north', 'survey reference')
    pairs = writers.write_time_depth([(100, 0.1, 2000), (250.5, 0.2, None)], depth_type='md', depth_unit='m', time_kind='one-way',
                                     time_unit='s', seismic_reference_elevation=12.5)
    result = readers.read(path=written(tmp_path, pairs.bytes), kind=pairs.profile, declared=pairs.declared)
    typed(result.rows, ((100.0, 0.1, 2000.0), (250.5, 0.2, None)), 'time-depth rows')
    typed(result.declared, {'depth_type': 'md', 'depth_unit': 'm', 'time_kind': 'one-way', 'time_unit': 's', 'seismic_reference_elevation': '12.5'},
          'time-depth declared')
    points = writers.write_points([(1.5, 2, -3), (4, 5, None)], attributes={'phi': [0.25, None]}, crs='EPSG:28992', xy_unit='m',
                                  z_unit='m', z_meaning='depth', positive='down', vertical_datum='NAP')
    result = readers.read(path=written(tmp_path, points.bytes), kind=points.profile, declared=points.declared)
    typed(result.columns, ('x', 'y', 'z', 'phi'), 'points columns')
    typed(result.rows, ((1.5, 2.0, -3.0, 0.25), (4.0, 5.0, None, None)), 'points rows')
    typed(result.declared, {'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down',
                            'vertical_datum': 'NAP'}, 'points declared')
    location = writers.write_location(4.5, 52, crs='EPSG:4326', elevation_reference='GL')
    result = readers.read(path=written(tmp_path, location.bytes), kind=location.profile, declared=location.declared)
    typed((result.x, result.y, result.crs, result.elevation_reference), (4.5, 52.0, 'EPSG:4326', 'GL'), 'location')


def test_a_missing_file_is_pythons_error_not_a_refusal(tmp_path):
    with pytest.raises(FileNotFoundError): readers.read(path=tmp_path / 'absent.csv', kind='well-tops-csv/1')
