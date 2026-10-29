"""E128 s2: ophiolite.readers reads the text kinds whole. Every input is a byte literal written here (board ruling
e128s2: no files, nothing copied from a third-party file), and each parity case feeds that same literal to the server's
reader. Every expected value is a literal written from the grammar (E128-readers-S2-COMMIT-STRATEGY.md); the server's
reader is then asked to agree (parity), never used as the expectation."""
from types import MappingProxyType

import pytest

from ophiolite import readers, writers
from ophiolite.readers import Grid, Mesh, ModelSection, ReadRefused, SeismicSection, Sticks, Wavelet

NO_REPAIR = ' No repair was applied.'
GRID_MAX = 4194304
UNKNOWN_SPATIAL = {'crs': 'unknown', 'xy_unit': 'unknown', 'z_unit': 'unknown', 'z_meaning': 'unknown', 'positive': 'unknown',
                   'vertical_datum': 'unknown'}
SPATIAL = {'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'NAP'}


def typed(actual, expected, where):
    """`actual` equals `expected` with the type at every level: a dict expects a read-only mapping, a tuple a tuple."""
    if isinstance(expected, dict):
        assert type(actual) is MappingProxyType, where
        assert list(actual) == list(expected), (where, list(actual), list(expected))
        for key in expected: typed(actual[key], expected[key], where + '.' + key)
    elif isinstance(expected, (tuple, list)):
        assert type(actual) is tuple and len(actual) == len(expected), (where, actual, expected)
        for i, (a, e) in enumerate(zip(actual, expected)): typed(a, e, '%s[%d]' % (where, i))
    else:
        assert type(actual) is type(expected) and actual == expected, (where, actual, expected)


GRID = b'NCOLS 2\nnrows 3\nxllcorner 1000\nyllcorner 2000.5\ncellsize 25\nnodata_value -9999\n1.5 2 3\n-9999 5\n-2.25\n'
STICKS = b'# OpendTect FaultStickSet\n! exported\n10 20 -100 0\n15.5 20 -200 9007199254740993 4\n10,20,-300,0,7\n15 21 -250 9007199254740993\n'
MESH = (b'# ophiolite-mesh 1\r\nattributes phi Sw\r\n# a comment\r\nvertices\r\n0 0 - 0.2 0.5\r\n100 0 -10 - 0.4\r\n0 100 -20 0.1 -\r\n'
        b'100 100 -30 0.3 0.6\r\ntriangles\r\n0 1 2\r\n1 3 2\r\n')
WAVELET = (b'# ophiolite-wavelet 1\nkind ricker\nfrequency_hz 30\ndt 0.001\nt0 -0.001\npolarity impedance-increase-positive\nsamples\n'
           b'-0.5\n1\n-0.5\n')
AXES_TEXT = b'domain time\nfirst_sample 0\nsample_interval 0.004\nsamples 2\ntraces %d\nhorizontal distance\nhorizontal_first 0\nhorizontal_step 25\n'
MODEL = (b'# ophiolite-model-section 1\n' + AXES_TEXT % 3 + b'rocks\n2 3000.5 2300 Delft Sandstone\n1 2000 2100 Rodenrijs  Claystone\n'
         b'grid\n1 1 2\n2 2 1\n')
SEISMIC = (b'# ophiolite-seismic-section 1\n' + AXES_TEXT % 2 + b'origin synthetic\npolarity impedance-increase-positive\ngrid\n'
           b'0.5 -1\n0 2.25\n')
AXES_HEADER = (('domain', ('time',)), ('first_sample', ('0',)), ('sample_interval', ('0.004',)), ('samples', ('2',)), ('traces', ('2',)),
               ('horizontal', ('distance',)), ('horizontal_first', ('0',)), ('horizontal_step', ('25',)))
AXES_2X2 = {'domain': 'time', 'first_sample': 0.0, 'sample_interval': 0.004, 'samples': 2, 'traces': 2, 'horizontal': 'distance',
            'horizontal_first': 0.0, 'horizontal_step': 25.0}
CONTEXT_2X2 = {'type': 'seismic-section', 'domain': 'time', 'first_sample': 0.0, 'sample_interval': 0.004, 'sample_unit': 's', 'samples': 2,
               'traces': 2, 'horizontal': 'distance', 'horizontal_first': 0.0, 'horizontal_step': 25.0, 'horizontal_unit': 'm'}

# name: (profile, bytes, declared, expected): expected is a dict of the family's fields (`context` included) or a refusal
CASES = {
    # --- grids ---
    'grid: corner registration, a mixed-case header kept, nodata missing, values over line breaks': (
        'esri-ascii-grid/1', GRID, SPATIAL,
        {'header': (('NCOLS', '2'), ('nrows', '3'), ('xllcorner', '1000'), ('yllcorner', '2000.5'), ('cellsize', '25'), ('nodata_value', '-9999')),
         'ncols': 2, 'nrows': 3, 'registration': 'corner', 'x': 1000.0, 'y': 2000.5, 'cell_size': 25.0, 'nodata': -9999.0,
         'cells': ((1.5, 2.0), (3.0, None), (5.0, -2.25)),
         'context': {'type': 'regular-grid-surface', **SPATIAL, 'registration': 'corner', 'row_order': 'north-to-south', 'ncols': 2,
                     'nrows': 3, 'cell_size': 25.0, 'x_first_center': 1012.5, 'y_first_center': 2063.0, 'missing_count': 1,
                     'value_range': [-2.25, 5.0]}}),
    'grid: centre registration, no nodata line': (
        'esri-ascii-grid/1', b'ncols 3\nnrows 1\nxllcenter -5\nyllcenter 7\ncellsize 0.5\n4 4 4\n', {},
        {'header': (('ncols', '3'), ('nrows', '1'), ('xllcenter', '-5'), ('yllcenter', '7'), ('cellsize', '0.5')),
         'ncols': 3, 'nrows': 1, 'registration': 'center', 'x': -5.0, 'y': 7.0, 'cell_size': 0.5, 'nodata': None,
         'cells': ((4.0, 4.0, 4.0),),
         'context': {'type': 'regular-grid-surface', **UNKNOWN_SPATIAL, 'registration': 'center', 'row_order': 'north-to-south',
                     'ncols': 3, 'nrows': 1, 'cell_size': 0.5, 'x_first_center': -5.0, 'y_first_center': 7.0, 'missing_count': 0,
                     'value_range': [4.0, 4.0]}}),
    'grid: every cell nodata': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nnodata_value 0\n0\n', {},
        {'header': (('ncols', '1'), ('nrows', '1'), ('xllcorner', '0'), ('yllcorner', '0'), ('cellsize', '1'), ('nodata_value', '0')),
         'ncols': 1, 'nrows': 1, 'registration': 'corner', 'x': 0.0, 'y': 0.0, 'cell_size': 1.0, 'nodata': 0.0, 'cells': ((None,),),
         'context': {'type': 'regular-grid-surface', **UNKNOWN_SPATIAL, 'registration': 'corner', 'row_order': 'north-to-south',
                     'ncols': 1, 'nrows': 1, 'cell_size': 1.0, 'x_first_center': 0.5, 'y_first_center': 0.5, 'missing_count': 1,
                     'value_range': None}}),
    'grid: one value too many': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n2\n3\n', {},
        ('The grid has more values than ncols × nrows.' + NO_REPAIR, 'refused', None, None)),
    'grid: one value too few': (
        'esri-ascii-grid/1', b'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 2 3\n', {},
        ('The grid has 3 values; ncols × nrows is 4.' + NO_REPAIR, 'refused', None, None)),
    'grid: both registration pairs': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\nxllcenter 0\nyllcenter 0\ncellsize 1\n1\n', {},
        ('The grid header must declare cellsize and either xllcorner/yllcorner or xllcenter/yllcenter.' + NO_REPAIR, 'refused', None, None)),
    'grid: a zero cell size': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 0\n1\n', {},
        ('The cell size must be positive.' + NO_REPAIR, 'refused', None, None)),
    'grid: a repeated key in another case': (
        'esri-ascii-grid/1', b'ncols 1\nNCOLS 1\nnrows 1\n', {}, ('Grid header line "NCOLS" is malformed or repeated.' + NO_REPAIR, 'refused', None, None)),
    'grid: a value that is not a number, with its row after the header': (
        'esri-ascii-grid/1', b'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 2\n\n3 x\n', {},
        ('A grid value on data row 3 is not a number.' + NO_REPAIR, 'not-a-number', 'A grid value', 3)),
    'grid: a non-number before a count error is refused for the number': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nx 2\n', {},
        ('A grid value on data row 1 is not a number.' + NO_REPAIR, 'not-a-number', 'A grid value', 1)),
    'grid: more cells than any deployment allows': (
        'esri-ascii-grid/1', b'ncols 2049\nnrows 2048\nxllcorner 0\nyllcorner 0\ncellsize 1\n', {},
        ('The grid must have between 1 and 4194304 cells.' + NO_REPAIR, 'refused', None, None)),
    'grid: a CRS that is not EPSG': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n', {'crs': 'RD'},
        ('Declare the coordinate reference system as EPSG:<code>, or as unknown.' + NO_REPAIR, 'refused', None, None)),
    'grid: a corner pair with a stray yllcenter is corner, its header kept': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\nyllcenter rubbish\ncellsize 2\n5\n', {},
        {'header': (('ncols', '1'), ('nrows', '1'), ('xllcorner', '0'), ('yllcorner', '0'), ('yllcenter', 'rubbish'), ('cellsize', '2')),
         'ncols': 1, 'nrows': 1, 'registration': 'corner', 'x': 0.0, 'y': 0.0, 'cell_size': 2.0, 'nodata': None, 'cells': ((5.0,),),
         'context': {'type': 'regular-grid-surface', **UNKNOWN_SPATIAL, 'registration': 'corner', 'row_order': 'north-to-south',
                     'ncols': 1, 'nrows': 1, 'cell_size': 2.0, 'x_first_center': 1.0, 'y_first_center': 1.0, 'missing_count': 0,
                     'value_range': [5.0, 5.0]}}),
    'grid: a zero cell size before a bad NODATA is refused for the cell size': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 0\nnodata_value bad\n1\n', {},
        ('The cell size must be positive.' + NO_REPAIR, 'refused', None, None)),
    'grid: a bad NODATA with too few values is refused for the NODATA': (
        'esri-ascii-grid/1', b'ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nnodata_value bad\n1\n', {},
        ('The NODATA value is not a number.' + NO_REPAIR, 'not-a-number', 'The NODATA value', None)),
    'grid: a bad token past the count is not a number': (
        'esri-ascii-grid/1', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 x\n', {},
        ('A grid value on data row 1 is not a number.' + NO_REPAIR, 'not-a-number', 'A grid value', 1)),
    'grid: an empty file': ('esri-ascii-grid/1', b'', {}, ('The file is empty.' + NO_REPAIR, 'empty', None, None)),
    # --- meshes ---
    'mesh: CRLF, attributes in attribute order, - for missing z and values, a comment': (
        'mesh-text/1', MESH, SPATIAL,
        {'attributes': ('phi', 'Sw'),
         'vertices': ((0.0, 0.0, None, (0.2, 0.5)), (100.0, 0.0, -10.0, (None, 0.4)), (0.0, 100.0, -20.0, (0.1, None)),
                      (100.0, 100.0, -30.0, (0.3, 0.6))),
         'triangles': ((0, 1, 2), (1, 3, 2)),
         'context': {'type': 'triangulated-surface', **SPATIAL, 'vertex_count': 4, 'triangle_count': 2, 'attributes': ['phi', 'Sw'],
                     'missing_z_count': 1, 'x_range': [0.0, 100.0], 'y_range': [0.0, 100.0], 'z_range': [-30.0, -10.0]}}),
    'mesh: no attributes line': (
        'mesh-text/1', b'# ophiolite-mesh 1\nvertices\n0 0 1\n1 0 2\n0 1 3\ntriangles\n2 1 0\n', {},
        {'attributes': (), 'vertices': ((0.0, 0.0, 1.0, ()), (1.0, 0.0, 2.0, ()), (0.0, 1.0, 3.0, ())), 'triangles': ((2, 1, 0),),
         'context': {'type': 'triangulated-surface', **UNKNOWN_SPATIAL, 'vertex_count': 3, 'triangle_count': 1, 'attributes': [],
                     'missing_z_count': 0, 'x_range': [0.0, 1.0], 'y_range': [0.0, 1.0], 'z_range': [1.0, 3.0]}}),
    'mesh: a BOM, every z missing': (
        'mesh-text/1', '﻿# ophiolite-mesh 1\nvertices\n0 0 -\n1 0 -\n0 1 -\n1 1 -\ntriangles\n0 1 3\n'.encode(), {},
        {'attributes': (), 'vertices': ((0.0, 0.0, None, ()), (1.0, 0.0, None, ()), (0.0, 1.0, None, ()), (1.0, 1.0, None, ())),
         'triangles': ((0, 1, 3),),
         'context': {'type': 'triangulated-surface', **UNKNOWN_SPATIAL, 'vertex_count': 4, 'triangle_count': 1, 'attributes': [],
                     'missing_z_count': 4, 'x_range': [0.0, 1.0], 'y_range': [0.0, 1.0], 'z_range': None}}),
    'mesh: triangles before vertices': (
        'mesh-text/1', b'# ophiolite-mesh 1\ntriangles\n0 1 2\n', {}, ('Line 2: expected "vertices" first.' + NO_REPAIR, 'refused', None, None)),
    'mesh: an index out of range': (
        'mesh-text/1', b'# ophiolite-mesh 1\nvertices\n0 0 1\n1 0 2\n0 1 3\ntriangles\n0 1 3\n', {},
        ('A triangle refers to a vertex that does not exist.' + NO_REPAIR, 'refused', None, None)),
    'mesh: a triangle repeating a vertex': (
        'mesh-text/1', b'# ophiolite-mesh 1\nvertices\n0 0 1\n1 0 2\ntriangles\n0 1 1\n', {},
        ('Line 6: a triangle repeats a vertex.' + NO_REPAIR, 'refused', None, None)),
    'mesh: a vertex short of its attribute value': (
        'mesh-text/1', b'# ophiolite-mesh 1\nattributes a\nvertices\n0 0 1\n', {},
        ('Line 4: a vertex needs x, y, z and 1 attribute values.' + NO_REPAIR, 'refused', None, None)),
    'mesh: a wrong first line': ('mesh-text/1', b'ophiolite-mesh 1\n', {}, ('The first line must be "# ophiolite-mesh 1".' + NO_REPAIR, 'refused', None, None)),
    'mesh: a NUL byte': ('mesh-text/1', b'# ophiolite-mesh 1\n\x00', {}, ('The file contains binary data.' + NO_REPAIR, 'binary', None, None)),
    # --- fault sticks ---
    'sticks: interleaved, comma separated, a node field, the index 9007199254740993, comments': (
        'opendtect-faultsticks/1', STICKS, SPATIAL,
        {'points': ((10.0, 20.0, -100.0, 0, None), (15.5, 20.0, -200.0, 9007199254740993, '4'), (10.0, 20.0, -300.0, 0, '7'),
                    (15.0, 21.0, -250.0, 9007199254740993, None)),
         'context': {'type': 'polyline-set', **SPATIAL, 'attributes': [], 'sticks': 2, 'points': 4, 'x_range': [10.0, 15.5],
                     'y_range': [20.0, 21.0], 'z_range': [-300.0, -100.0]}}),
    'sticks: a one-point stick': (
        'opendtect-faultsticks/1', b'0 0 0 1\n0 0 1 1\n5 5 5 2\n', {}, ('Every stick needs at least two points.' + NO_REPAIR, 'refused', None, None)),
    'sticks: a stick index that is not whole': (
        'opendtect-faultsticks/1', b'0 0 0 1\n0 0 1 1.5\n', {},
        ('Line 2: coordinates must be numbers and the stick index a whole number.' + NO_REPAIR, 'refused', None, None)),
    'sticks: an infinite coordinate': (
        'opendtect-faultsticks/1', b'0 0 inf 1\n', {}, ('Line 1: coordinates must be finite.' + NO_REPAIR, 'refused', None, None)),
    'sticks: three fields': (
        'opendtect-faultsticks/1', b'# only comments\n0 0 0\n', {}, ('Line 2: expected x y z stick-index [node-index].' + NO_REPAIR, 'refused', None, None)),
    'sticks: comments only': (
        'opendtect-faultsticks/1', b'# a\n! b\n', {}, ('The file holds no fault-stick points.' + NO_REPAIR, 'refused', None, None)),
    # --- wavelets ---
    'wavelet: ricker': (
        'wavelet-text/1', WAVELET, {},
        {'header': (('kind', ('ricker',)), ('frequency_hz', ('30',)), ('dt', ('0.001',)), ('t0', ('-0.001',)),
                    ('polarity', ('impedance-increase-positive',))),
         'wavelet_kind': 'ricker', 'dt': 0.001, 't0': -0.001, 'polarity': 'impedance-increase-positive', 'frequency_hz': 30.0,
         'corners_hz': None, 'samples': (-0.5, 1.0, -0.5),
         'context': {'type': 'wavelet', 'kind': 'ricker', 'frequency_hz': 30.0, 'corners_hz': None, 'dt': 0.001, 't0': -0.001,
                     'time_unit': 's', 'polarity': 'impedance-increase-positive', 'sample_count': 3, 'minimum': -0.5, 'maximum': 1.0}}),
    'wavelet: ormsby, header out of order, comments': (
        'wavelet-text/1', b'# ophiolite-wavelet 1\n# a comment\ncorners_hz 5 10 40 60\nkind ormsby\nt0 0\ndt 0.002\npolarity unknown\n'
                          b'samples\n0\n# c\n1\n0\n1\n0\n', {},
        {'header': (('corners_hz', ('5', '10', '40', '60')), ('kind', ('ormsby',)), ('t0', ('0',)), ('dt', ('0.002',)), ('polarity', ('unknown',))),
         'wavelet_kind': 'ormsby', 'dt': 0.002, 't0': 0.0, 'polarity': 'unknown', 'frequency_hz': None, 'corners_hz': (5.0, 10.0, 40.0, 60.0),
         'samples': (0.0, 1.0, 0.0, 1.0, 0.0),
         'context': {'type': 'wavelet', 'kind': 'ormsby', 'frequency_hz': None, 'corners_hz': [5.0, 10.0, 40.0, 60.0], 'dt': 0.002, 't0': 0.0,
                     'time_unit': 's', 'polarity': 'unknown', 'sample_count': 5, 'minimum': 0.0, 'maximum': 1.0}}),
    'wavelet: other, 1e-3 and +0 spellings kept in the header': (
        'wavelet-text/1', b'# ophiolite-wavelet 1\nkind other\ndt 1e-3\nt0 +0\npolarity impedance-increase-negative\nsamples\n1\n2\n3\n', {},
        {'header': (('kind', ('other',)), ('dt', ('1e-3',)), ('t0', ('+0',)), ('polarity', ('impedance-increase-negative',))),
         'wavelet_kind': 'other', 'dt': 0.001, 't0': 0.0, 'polarity': 'impedance-increase-negative', 'frequency_hz': None, 'corners_hz': None,
         'samples': (1.0, 2.0, 3.0),
         'context': {'type': 'wavelet', 'kind': 'other', 'frequency_hz': None, 'corners_hz': None, 'dt': 0.001, 't0': 0.0, 'time_unit': 's',
                     'polarity': 'impedance-increase-negative', 'sample_count': 3, 'minimum': 1.0, 'maximum': 3.0}}),
    'wavelet: frequency_hz on an ormsby': (
        'wavelet-text/1', b'# ophiolite-wavelet 1\nkind ormsby\nfrequency_hz 30\ncorners_hz 5 10 40 60\ndt 0.001\nt0 0\npolarity unknown\n'
                          b'samples\n0\n1\n0\n', {},
        ('Only a Ricker wavelet declares frequency_hz.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: corners not increasing': (
        'wavelet-text/1', b'# ophiolite-wavelet 1\nkind ormsby\ncorners_hz 5 10 10 60\ndt 0.001\nt0 0\npolarity unknown\nsamples\n0\n1\n0\n', {},
        ('The Ormsby corner frequencies must increase.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: dt out of range': (
        'wavelet-text/1', WAVELET.replace(b'dt 0.001', b'dt 0.02'), {},
        ('A wavelet must be sampled every 0.0005 to 0.01 s.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: an unknown header key': (
        'wavelet-text/1', WAVELET.replace(b'samples\n', b'gain 2\nsamples\n'), {}, ('Unknown header field gain.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: a key stated twice': (
        'wavelet-text/1', WAVELET.replace(b'kind ricker\n', b'kind ricker\nkind ricker\n'), {},
        ('Line 3: kind is stated twice.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: an even sample count': (
        'wavelet-text/1', WAVELET + b'0\n', {},
        ('A wavelet has an odd number of samples, so one sample is its centre.' + NO_REPAIR, 'refused', None, None)),
    'wavelet: a sample that is not a number': (
        'wavelet-text/1', WAVELET.replace(b'\n1\n', b'\none\n'), {},
        ('A sample on data row 9 is not a number.' + NO_REPAIR, 'not-a-number', 'A sample', 9)),
    'wavelet: a declaration supplied': (
        'wavelet-text/1', WAVELET, {'crs': 'EPSG:28992'},
        ('This file states its context in its header; nothing is declared beside it.' + NO_REPAIR, 'refused', None, None)),
    # --- model sections ---
    'model: rocks in file order, a name with a double space joined by one': (
        'model-section-text/1', MODEL, {},
        {'header': (('domain', ('time',)), ('first_sample', ('0',)), ('sample_interval', ('0.004',)), ('samples', ('2',)), ('traces', ('3',)),
                    ('horizontal', ('distance',)), ('horizontal_first', ('0',)), ('horizontal_step', ('25',))),
         'axes': {'domain': 'time', 'first_sample': 0.0, 'sample_interval': 0.004, 'samples': 2, 'traces': 3, 'horizontal': 'distance',
                  'horizontal_first': 0.0, 'horizontal_step': 25.0},
         'rocks': ((2, 3000.5, 2300.0, 'Delft Sandstone'), (1, 2000.0, 2100.0, 'Rodenrijs Claystone')),
         'grid': ((1, 1, 2), (2, 2, 1)),
         'context': {'type': 'model-section', 'domain': 'time', 'first_sample': 0.0, 'sample_interval': 0.004, 'sample_unit': 's', 'samples': 2,
                     'traces': 3, 'horizontal': 'distance', 'horizontal_first': 0.0, 'horizontal_step': 25.0, 'horizontal_unit': 'm',
                     'rock_count': 2, 'velocity_unit': 'm/s', 'density_unit': 'kg/m3'}}),
    'model: a grid value naming an unlisted rock': (
        'model-section-text/1', MODEL.replace(b'2 2 1\n', b'2 3 1\n'), {},
        ('Line 15: rock 3 is not listed under rocks.' + NO_REPAIR, 'refused', None, None)),
    'model: a repeated rock': (
        'model-section-text/1', MODEL.replace(b'1 2000 ', b'2 2000 '), {}, ('Rock 2 is listed twice.' + NO_REPAIR, 'refused', None, None)),
    'model: samples that are not a whole number': (
        'model-section-text/1', MODEL.replace(b'samples 2\n', b'samples 2.0\n'), {}, ('samples is a whole number.' + NO_REPAIR, 'refused', None, None)),
    'model: too many grid rows': (
        'model-section-text/1', MODEL + b'1 1 1\n', {},
        ('The grid has more than the 2 rows the header declares.' + NO_REPAIR, 'refused', None, None)),
    'model: a declaration supplied': (
        'model-section-text/1', MODEL, {'xy_unit': 'm'},
        ('This file states its context in its header; nothing is declared beside it.' + NO_REPAIR, 'refused', None, None)),
    # --- seismic sections ---
    'seismic: origin synthetic and a polarity stated': (
        'seismic-section-text/1', SEISMIC, {},
        {'header': AXES_HEADER + (('origin', ('synthetic',)), ('polarity', ('impedance-increase-positive',))),
         'axes': AXES_2X2, 'origin': 'synthetic', 'polarity': 'impedance-increase-positive', 'grid': ((0.5, -1.0), (0.0, 2.25)),
         'context': {**CONTEXT_2X2, 'origin': 'synthetic', 'polarity': 'impedance-increase-positive', 'minimum': -1.0, 'maximum': 2.25}}),
    'seismic: an explicit not-stated origin and no polarity': (
        'seismic-section-text/1', SEISMIC.replace(b'origin synthetic\npolarity impedance-increase-positive\n', b'origin not-stated\n'), {},
        {'header': AXES_HEADER + (('origin', ('not-stated',)),), 'axes': AXES_2X2, 'origin': 'not-stated', 'polarity': None,
         'grid': ((0.5, -1.0), (0.0, 2.25)),
         'context': {**CONTEXT_2X2, 'origin': 'not-stated', 'polarity': 'unknown', 'minimum': -1.0, 'maximum': 2.25}}),
    'seismic: origin and polarity absent, header out of order, 1e-3 and +0 spellings': (
        'seismic-section-text/1', b'# ophiolite-seismic-section 1\ntraces 1\nhorizontal trace-number\nhorizontal_step 1\nsamples 3\ndomain depth\n'
                                  b'sample_interval 1e-3\nfirst_sample +0\nhorizontal_first 1\ngrid\n1\n2\n3\n', {},
        {'header': (('traces', ('1',)), ('horizontal', ('trace-number',)), ('horizontal_step', ('1',)), ('samples', ('3',)), ('domain', ('depth',)),
                    ('sample_interval', ('1e-3',)), ('first_sample', ('+0',)), ('horizontal_first', ('1',))),
         'axes': {'domain': 'depth', 'first_sample': 0.0, 'sample_interval': 0.001, 'samples': 3, 'traces': 1, 'horizontal': 'trace-number',
                  'horizontal_first': 1.0, 'horizontal_step': 1.0},
         'origin': None, 'polarity': None, 'grid': ((1.0,), (2.0,), (3.0,)),
         'context': {'type': 'seismic-section', 'domain': 'depth', 'first_sample': 0.0, 'sample_interval': 0.001, 'sample_unit': 'm', 'samples': 3,
                     'traces': 1, 'horizontal': 'trace-number', 'horizontal_first': 1.0, 'horizontal_step': 1.0, 'horizontal_unit': None,
                     'origin': 'not-stated', 'polarity': 'unknown', 'minimum': 1.0, 'maximum': 3.0}}),
    'seismic: an origin that is neither': (
        'seismic-section-text/1', SEISMIC.replace(b'origin synthetic', b'origin measured'), {},
        ('Declare the origin as synthetic, or leave it out.' + NO_REPAIR, 'refused', None, None)),
    'seismic: a row with the wrong value count': (
        'seismic-section-text/1', SEISMIC.replace(b'0.5 -1\n', b'0.5\n'), {},
        ('Line 13: a grid row has 1 values; the header declares 2 traces.' + NO_REPAIR, 'refused', None, None)),
    'seismic: a declaration supplied': (
        'seismic-section-text/1', SEISMIC, {'crs': 'unknown'},
        ('This file states its context in its header; nothing is declared beside it.' + NO_REPAIR, 'refused', None, None)),
}

ACCEPTED = [name for name, case in CASES.items() if isinstance(case[3], dict)]
REFUSED = [name for name, case in CASES.items() if isinstance(case[3], tuple)]
FAMILY = {'esri-ascii-grid/1': Grid, 'mesh-text/1': Mesh, 'opendtect-faultsticks/1': Sticks, 'wavelet-text/1': Wavelet,
          'model-section-text/1': ModelSection, 'seismic-section-text/1': SeismicSection}


class Version:
    def __init__(self, **attributes): self.__dict__.update(attributes)


def written(tmp_path, raw):
    path = tmp_path / 'input'
    path.write_bytes(raw)
    return path


def freeze(value):
    """A context literal with its lists as tuples, the shape a result holds."""
    if isinstance(value, dict): return {k: freeze(v) for k, v in value.items()}
    if isinstance(value, list): return tuple(freeze(v) for v in value)
    return value


def thawed(value):
    if isinstance(value, MappingProxyType): return {k: thawed(v) for k, v in value.items()}
    if isinstance(value, tuple): return [thawed(v) for v in value]
    return value


def check(result, kind, declared, expected):
    assert type(result) is FAMILY.get(kind, type(result)) and result.kind == kind
    typed(result.declared, dict(declared or {}), 'declared')
    for field, value in expected.items():
        typed(getattr(result, field), freeze(value) if field == 'context' else value, field)


@pytest.mark.parametrize('name', ACCEPTED)
def test_a_file_is_read_whole_with_every_value_and_its_type(tmp_path, name):
    kind, raw, declared, expected = CASES[name]
    path = written(tmp_path, raw)
    for result in (readers.read(path=path, kind=kind, declared=declared), readers.read(Version(path=path, kind=kind, declared=declared))):
        check(result, kind, declared, expected)


@pytest.mark.parametrize('name', REFUSED)
def test_a_file_that_cannot_be_read_whole_is_refused_with_the_sentence_code_field_and_row(tmp_path, name):
    kind, raw, declared, expected = CASES[name]
    with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind=kind, declared=declared)
    error = caught.value
    assert (str(error), error.code, error.field, error.row) == expected


def server_view(result):
    """The SDK result in the shape of the server reader's data."""
    if result.kind == 'esri-ascii-grid/1':
        return {'values': [v for row in result.cells for v in row], 'nodata_value': result.nodata}
    if result.kind == 'mesh-text/1':
        return {'vertices': [[x, y, z] for x, y, z, _ in result.vertices], 'triangles': [list(t) for t in result.triangles],
                'attributes': [{'name': a, 'values': [v[3][k] for v in result.vertices]} for k, a in enumerate(result.attributes)]}
    if result.kind == 'opendtect-faultsticks/1':
        sticks = {}
        for x, y, z, index, _ in result.points: sticks.setdefault(index, []).append({'x': x, 'y': y, 'z': z})
        return {'sticks': [{'index': i, 'points': p} for i, p in sticks.items()]}
    if result.kind == 'wavelet-text/1':
        return {'samples': list(result.samples)}
    if result.kind == 'model-section-text/1':
        return {'rocks': [{'index': i, 'name': name, 'vp': vp, 'density': rho} for i, vp, rho, name in result.rocks],
                'grid': [list(row) for row in result.grid]}
    if result.kind == 'seismic-section-text/1':
        return {'grid': [list(row) for row in result.grid]}
    raise AssertionError(result.kind)


def server(typed_reader, kind, raw, declared):
    return typed_reader.read_typed(kind, raw, declared, max_cells=GRID_MAX, max_encoded=None)


@pytest.mark.parametrize('name', list(CASES))
def test_the_server_reader_agrees_on_every_case(tmp_path, name):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    kind, raw, declared, expected = CASES[name]
    try: theirs = server(typed_reader, kind, raw, declared)
    except typed_reader.TypedReadError as refused: theirs = refused
    try: ours = readers.read(path=written(tmp_path, raw), kind=kind, declared=declared)
    except ReadRefused as refused: ours = refused
    if isinstance(theirs, Exception):
        assert isinstance(ours, ReadRefused), (name, ours)
        assert (str(ours), ours.code, ours.field, ours.row) == (str(theirs), theirs.code, theirs.field, theirs.row)
    else:
        assert not isinstance(ours, Exception), (name, ours)
        context, data, _ = theirs
        assert thawed(ours.context) == context
        assert server_view(ours) == data


def test_the_grid_cap_is_the_largest_a_deployment_allows(tmp_path):
    """2048 × 2048 = 4194304 cells are read on both sides; 2049 × 2048 is a CASES refusal (refused before any value)."""
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    raw = b'ncols 2048\nnrows 2048\nxllcorner 0\nyllcorner 0\ncellsize 1\n' + (b'1 ' * 2047 + b'2\n') * 2048
    result = readers.read(path=written(tmp_path, raw), kind='esri-ascii-grid/1')
    assert (result.ncols, result.nrows, len(result.cells), result.cells[-1][-1], result.context['value_range']) == (2048, 2048, 2048, 2.0, (1.0, 2.0))
    assert server(typed_reader, 'esri-ascii-grid/1', raw, None)[0]['ncols'] == 2048


@pytest.mark.parametrize('count, readable', [(16, True), (17, False)])
def test_a_mesh_holds_sixteen_attributes_not_seventeen(tmp_path, count, readable):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    names = ' '.join('a%d' % i for i in range(count)).encode()
    raw = b'# ophiolite-mesh 1\nattributes ' + names + b'\nvertices\n' + b''.join(b'%d %d 0' % (x, y) + b' 1' * count + b'\n'
                                                                              for x, y in ((0, 0), (1, 0), (0, 1))) + b'triangles\n0 1 2\n'
    if readable:
        typed(readers.read(path=written(tmp_path, raw), kind='mesh-text/1').attributes, tuple('a%d' % i for i in range(16)), 'attributes')
        server(typed_reader, 'mesh-text/1', raw, None)
    else:
        sentence = 'Declare at most 16 distinct attribute names (letters, digits, underscores).' + NO_REPAIR
        with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind='mesh-text/1')
        assert str(caught.value) == sentence
        with pytest.raises(typed_reader.TypedReadError) as theirs: server(typed_reader, 'mesh-text/1', raw, None)
        assert str(theirs.value) == sentence


# S2-D7, disposition 15: a whole number is ASCII [0-9]+, so a Unicode digit (str.isdigit() passes) is refused with the
# site's sentence. Outside parity until carried duty D-29 merges: today the server crashes on '²' (int() raises) and
# reads '٣' as 3.
NON_ASCII_DIGITS = {
    'mesh triangle, ²': ('mesh-text/1', '# ophiolite-mesh 1\nvertices\n0 0 0\n1 0 0\n0 1 0\ntriangles\n0 1 ²\n'.encode(),
                         'Line 7: a triangle is three vertex numbers.' + NO_REPAIR),
    'mesh triangle, ٣': ('mesh-text/1', '# ophiolite-mesh 1\nvertices\n0 0 0\n1 0 0\n0 1 0\n1 1 0\ntriangles\n0 1 ٣\n'.encode(),
                         'Line 8: a triangle is three vertex numbers.' + NO_REPAIR),
    'section samples, ²': ('seismic-section-text/1', SEISMIC.replace(b'samples 2', 'samples ²'.encode()), 'samples is a whole number.' + NO_REPAIR),
    'section traces, ٣': ('model-section-text/1', MODEL.replace(b'traces 3', 'traces ٣'.encode()), 'traces is a whole number.' + NO_REPAIR),
    'rock index, ²': ('model-section-text/1', MODEL.replace(b'\n1 2000', '\n² 2000'.encode()),
                      'Line 12: a rock is an index, a P-wave velocity (m/s), a density (kg/m3) and a name.' + NO_REPAIR),
    'rock index, ٣': ('model-section-text/1', MODEL.replace(b'\n1 2000', '\n٣ 2000'.encode()),
                      'Line 12: a rock is an index, a P-wave velocity (m/s), a density (kg/m3) and a name.' + NO_REPAIR),
    'model grid value, ²': ('model-section-text/1', MODEL.replace(b'2 2 1\n', '2 ² 1\n'.encode()),
                            'Line 15: a grid value is a rock index.' + NO_REPAIR),
    'model grid value, ٣': ('model-section-text/1', MODEL.replace(b'2 2 1\n', '2 ٣ 1\n'.encode()),
                            'Line 15: a grid value is a rock index.' + NO_REPAIR),
}


@pytest.mark.parametrize('name', list(NON_ASCII_DIGITS))
def test_a_unicode_digit_is_not_a_whole_number(tmp_path, name):
    kind, raw, sentence = NON_ASCII_DIGITS[name]
    with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind=kind)
    assert (str(caught.value), caught.value.code) == (sentence, 'refused')


def triangle_mesh(vertices, triangles):
    """A valid mesh of `vertices` vertices on a line pattern and `triangles` triangles over the first three."""
    return (b'# ophiolite-mesh 1\nvertices\n' + b''.join(b'%d %d 0\n' % (i, i % 2) for i in range(vertices))
            + b'triangles\n' + b'0 1 2\n' * triangles)


def wavelet(samples):
    return b'# ophiolite-wavelet 1\nkind other\ndt 0.001\nt0 0\npolarity unknown\nsamples\n' + b''.join(b'%d\n' % (i % 7) for i in range(samples))


def section(samples, traces):
    """A seismic section of `samples` rows of `traces` values."""
    return (b'# ophiolite-seismic-section 1\ndomain time\nfirst_sample 0\nsample_interval 0.004\nsamples %d\ntraces %d\nhorizontal distance\n'
            b'horizontal_first 0\nhorizontal_step 25\ngrid\n' % (samples, traces) + (b' '.join([b'0.5'] * traces) + b'\n') * samples)


def model(rocks, name):
    """A 1 x 1 model section listing `rocks` rocks named `name`, numbered from 0; the grid names rock 0."""
    return (b'# ophiolite-model-section 1\ndomain depth\nfirst_sample 0\nsample_interval 1\nsamples 1\ntraces 1\nhorizontal trace-number\n'
            b'horizontal_first 1\nhorizontal_step 1\nrocks\n' + b''.join(b'%d 2000 2100 %s\n' % (i, name.encode()) for i in range(rocks))
            + b'grid\n0\n')


LIMITS = [  # name, kind, bytes, None if read, else the refusal sentence
    ('200000 vertices', 'mesh-text/1', triangle_mesh(200000, 1), None),
    ('200001 vertices', 'mesh-text/1', triangle_mesh(200001, 1), 'The surface has more than 200000 vertices.'),
    ('400000 triangles', 'mesh-text/1', triangle_mesh(3, 400000), None),
    ('400001 triangles', 'mesh-text/1', triangle_mesh(3, 400001), 'The surface has more than 400000 triangles.'),
    ('20000 sticks', 'opendtect-faultsticks/1', b''.join(b'0 0 0 %d\n0 0 1 %d\n' % (i, i) for i in range(20000)), None),
    ('20001 sticks', 'opendtect-faultsticks/1', b''.join(b'0 0 0 %d\n0 0 1 %d\n' % (i, i) for i in range(20001)),
     'The file holds too many points or sticks.'),
    ('200000 points', 'opendtect-faultsticks/1', b''.join(b'0 0 %d %d\n' % (i, i % 10) for i in range(200000)), None),
    ('200001 points', 'opendtect-faultsticks/1', b''.join(b'0 0 %d %d\n' % (i, i % 10) for i in range(200001)),
     'The file holds too many points or sticks.'),
    ('4095 wavelet samples', 'wavelet-text/1', wavelet(4095), None),
    ('4094 wavelet samples', 'wavelet-text/1', wavelet(4094), 'A wavelet has an odd number of samples, so one sample is its centre.'),
    ('4096 wavelet samples', 'wavelet-text/1', wavelet(4096), 'A wavelet has 3 to 4095 samples.'),  # the count is checked first
    ('2 wavelet samples', 'wavelet-text/1', wavelet(2), 'A wavelet has 3 to 4095 samples.'),
    ('8192 x 1', 'seismic-section-text/1', section(8192, 1), None),
    ('8193 x 1', 'seismic-section-text/1', section(8193, 1), 'A section has 1 to 8192 samples per trace.'),
    ('1 x 4096', 'seismic-section-text/1', section(1, 4096), None),
    ('1 x 4097', 'seismic-section-text/1', section(1, 4097), 'A section has 1 to 4096 traces.'),
    ('1000 x 1000', 'seismic-section-text/1', section(1000, 1000), None),
    ('1001 x 1000', 'seismic-section-text/1', section(1001, 1000), 'A section holds at most 1,000,000 samples.'),
    ('256 rocks', 'model-section-text/1', model(256, 'rock'), None),
    ('257 rocks', 'model-section-text/1', model(257, 'rock'), 'A model lists at most 256 rocks.'),
    ('a 128-character rock name', 'model-section-text/1', model(1, 'n' * 128), None),
    ('a 129-character rock name', 'model-section-text/1', model(1, 'n' * 129), 'Rock 0: a rock name has at most 128 characters.'),
]


@pytest.mark.parametrize('name, kind, raw, sentence', LIMITS, ids=[case[0] for case in LIMITS])
def test_the_limits_are_the_servers(tmp_path, name, kind, raw, sentence):
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    if sentence is None:
        result = readers.read(path=written(tmp_path, raw), kind=kind)
        assert thawed(result.context) == server(typed_reader, kind, raw, None)[0]
    else:
        with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind=kind)
        assert str(caught.value) == sentence + NO_REPAIR
        with pytest.raises(typed_reader.TypedReadError) as theirs: server(typed_reader, kind, raw, None)
        assert str(theirs.value) == sentence + NO_REPAIR


def test_what_a_writer_writes_reads_back_as_given(tmp_path):
    grid = writers.write_grid([1.5, None, 3, 4], ncols=2, nrows=2, x_origin=100, y_origin=200, cell_size=10, **SPATIAL)
    result = readers.read(path=written(tmp_path, grid.bytes), kind=grid.profile, declared=grid.declared)
    typed(result.cells, ((1.5, None), (3.0, 4.0)), 'grid cells')
    typed((result.x, result.y, result.cell_size, result.registration), (100.0, 200.0, 10.0, 'corner'), 'grid origin')
    typed(result.declared, SPATIAL, 'grid declared')
    mesh = writers.write_mesh([(0, 0, 1), (1, 0, None), (0, 1, 3)], [(0, 1, 2)], attributes={'phi': [0.1, None, 0.3]}, **SPATIAL)
    result = readers.read(path=written(tmp_path, mesh.bytes), kind=mesh.profile, declared=mesh.declared)
    typed(result.vertices, ((0.0, 0.0, 1.0, (0.1,)), (1.0, 0.0, None, (None,)), (0.0, 1.0, 3.0, (0.3,))), 'mesh vertices')
    typed(result.triangles, ((0, 1, 2),), 'mesh triangles')
    typed(result.declared, SPATIAL, 'mesh declared')
    sticks = writers.write_sticks([{'index': 3, 'points': [{'x': 1, 'y': 2, 'z': 3}, {'x': 1, 'y': 2, 'z': 4.5}]}], **SPATIAL)
    result = readers.read(path=written(tmp_path, sticks.bytes), kind=sticks.profile, declared=sticks.declared)
    typed(result.points, ((1.0, 2.0, 3.0, 3, None), (1.0, 2.0, 4.5, 3, None)), 'stick points')
    typed(result.declared, SPATIAL, 'sticks declared')
    wave = writers.write_wavelet([0, 1.25, 0], kind='ricker', frequency_hz=25, dt=0.002, t0=-0.002, polarity='unknown')
    result = readers.read(path=written(tmp_path, wave.bytes), kind=wave.profile, declared=wave.declared)
    typed((result.wavelet_kind, result.frequency_hz, result.dt, result.t0, result.polarity, result.samples),
          ('ricker', 25.0, 0.002, -0.002, 'unknown', (0.0, 1.25, 0.0)), 'wavelet')
    rocks = [{'index': 4, 'name': 'Delft Sandstone', 'vp': 3000, 'density': 2300}, {'index': 1, 'name': 'Shale', 'vp': 2500.5, 'density': 2200}]
    axes = dict(domain='depth', first_sample=100, sample_interval=4, horizontal='distance', horizontal_first=0, horizontal_step=12.5)
    rock_model = writers.write_model_section(rocks, [[4, 1], [1, 1]], **axes)
    result = readers.read(path=written(tmp_path, rock_model.bytes), kind=rock_model.profile, declared=rock_model.declared)
    typed(result.rocks, ((4, 3000.0, 2300.0, 'Delft Sandstone'), (1, 2500.5, 2200.0, 'Shale')), 'model rocks')
    typed(result.grid, ((4, 1), (1, 1)), 'model grid')
    typed(result.axes, {'domain': 'depth', 'first_sample': 100.0, 'sample_interval': 4.0, 'samples': 2, 'traces': 2, 'horizontal': 'distance',
                        'horizontal_first': 0.0, 'horizontal_step': 12.5}, 'model axes')
    seismic = writers.write_seismic_section([[0.5, -0.25]], polarity='impedance-increase-negative', origin='synthetic', **axes)
    result = readers.read(path=written(tmp_path, seismic.bytes), kind=seismic.profile, declared=seismic.declared)
    typed((result.grid, result.origin, result.polarity), (((0.5, -0.25),), 'synthetic', 'impedance-increase-negative'), 'seismic')


def test_a_missing_file_is_pythons_error_not_a_refusal(tmp_path):
    with pytest.raises(FileNotFoundError): readers.read(path=tmp_path / 'absent.txt', kind='esri-ascii-grid/1')
