"""E128 s0: the ophiolite.readers contract. The preservation matrix covers exactly the process kinds and says what each
keeps; the result families have the fields and nested types the strategy fixes; read() refuses a wrong call with one
sentence and opens nothing, and (E128 s3) reaches a reader for every kind; importing the package contacts nothing. Every expected value is a literal written here
from the strategy (E128-readers-COMMIT-STRATEGY.md section 4), never computed from the package."""
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from ophiolite import readers
from ophiolite.errors import Refused
from ophiolite.readers import results

SDK = Path(__file__).resolve().parents[1]

SPATIAL = ('crs', 'xy_unit', 'z_meaning', 'z_unit', 'positive', 'vertical_datum')
AXES = (('domain', 'required'), ('first_sample', 'required'), ('sample_interval', 'required'), ('samples', 'required'),
        ('traces', 'required'), ('horizontal', 'required'), ('horizontal_first', 'required'), ('horizontal_step', 'required'))
TR = 'ophiolite-connectors/src/asset_connectors/typed_reader.py'
SEC = 'ophiolite-connectors/src/asset_connectors/sections.py'


def sources(profile, grammar, kind):
    return {'profile': 'ophiolite-platform/contracts/profiles/v1/' + profile, 'grammar': grammar,
            'declared': 'ophiolite-connectors/src/asset_connectors/readers/registry.json readers[%s].declared' % kind}


ROWS = {
    'points-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('x', 'y'), 'optional': ('z',), 'extra': 'named-attributes'},
        'sections': (), 'nulls': ('an empty z cell', 'an empty attribute cell'), 'declared': SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('points-csv.json', TR + ':335 _points', 'points-csv/1')},
    'mesh-text/1': {
        'result': 'Mesh',
        'fixed': (('# ophiolite-mesh 1', 'required'), ('attributes', 'optional'), ('vertices', 'required'), ('triangles', 'required')),
        'columns': {'required': ('x', 'y', 'z'), 'optional': (), 'extra': 'named-attributes'},
        'sections': (), 'nulls': ('- for z', '- for an attribute value'), 'declared': SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('mesh-text.json', TR + ':295 _mesh', 'mesh-text/1')},
    'esri-ascii-grid/1': {
        'result': 'Grid',
        'fixed': (('ncols', 'required'), ('nrows', 'required'), ('xllcorner|xllcenter', 'required'), ('yllcorner|yllcenter', 'required'),
                  ('cellsize', 'required'), ('nodata_value', 'optional')),
        'columns': {'required': ('value',), 'optional': (), 'extra': None},
        'sections': (), 'nulls': ('a cell equal to nodata_value',), 'declared': SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('esri-ascii-grid.json', TR + ':230 _grid', 'esri-ascii-grid/1')},
    'well-tops-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('name', 'md'), 'optional': ('tvd', 'source'), 'extra': 'kept'},
        'sections': (), 'nulls': ('an empty tvd cell', 'an empty source cell', 'an empty extra cell'),
        'declared': ('depth_unit', 'depth_basis', 'depth_datum'),
        'parity': 'read_typed', 'outside_parity': ('extra columns, as text',),
        'sources': sources('well-tops-csv.json', TR + ':114 _tops', 'well-tops-csv/1')},
    'deviation-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('md', 'inclination', 'azimuth'), 'optional': ('tvd',), 'extra': 'refused'},
        'sections': (), 'nulls': ('an empty inclination cell', 'an empty azimuth cell', 'an empty tvd cell'),
        'declared': ('depth_unit', 'azimuth_reference', 'depth_datum'),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('deviation-csv.json', TR + ':157 _trajectory', 'deviation-csv/1')},
    'opendtect-faultsticks/1': {
        'result': 'Sticks', 'fixed': (),
        'columns': {'required': ('x', 'y', 'z', 'stick'), 'optional': ('node',), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': SPATIAL,
        'parity': 'read_typed', 'outside_parity': ('the node field, as text',),
        'sources': sources('opendtect-faultsticks.json', TR + ':426 _polylines', 'opendtect-faultsticks/1')},
    'las2/1': {
        'result': 'Las',
        'fixed': (('VERS 1.2, 2.0, or 3.0 in the LAS 2 layout', 'required'), ('WRAP NO, or YES read by the declared curve count', 'required'),
                  ('DLM SPACE or TAB', 'optional')),
        'columns': {'required': (), 'optional': (), 'extra': 'named-curves'},
        'sections': (('~V', 'required'), ('~W', 'required'), ('~C', 'required'), ('~P', 'optional'), ('~O', 'optional'), ('~A', 'required')),
        'nulls': ('a data value equal to the ~W NULL value',), 'declared': (),
        'parity': 'read_las', 'outside_parity': ('~P lines as written', '~O lines as written', 'the descriptions of ~V, ~W and ~C lines'),
        'sources': sources('las2.json', 'ophiolite-connectors/src/asset_connectors/las_reader.py:64 read_las', 'las2/1')},
    'well-location/1': {
        'result': 'Location',
        'fixed': (('x', 'required'), ('y', 'required'), ('crs', 'required'), ('elevation_reference', 'required')),
        'columns': {'required': (), 'optional': (), 'extra': None},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('well-location.json', TR + ':366 _well_location', 'well-location/1')},
    'wavelet-text/1': {
        'result': 'Wavelet',
        'fixed': (('# ophiolite-wavelet 1', 'required'), ('kind', 'required'), ('dt', 'required'), ('t0', 'required'), ('polarity', 'required'),
                  ('frequency_hz', 'optional'), ('corners_hz', 'optional'), ('samples', 'required')),
        'columns': {'required': ('sample',), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('wavelet-text.json', SEC + ':64 read_wavelet', 'wavelet-text/1')},
    'model-section-text/1': {
        'result': 'ModelSection',
        'fixed': (('# ophiolite-model-section 1', 'required'),) + AXES + (('rocks', 'required'), ('grid', 'required')),
        'columns': {'required': ('index', 'vp', 'density', 'name'), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('model-section-text.json', SEC + ':130 read_model_section', 'model-section-text/1')},
    'seismic-section-text/1': {
        'result': 'SeismicSection',
        'fixed': (('# ophiolite-seismic-section 1', 'required'),) + AXES + (('origin', 'optional'), ('polarity', 'optional'), ('grid', 'required')),
        'columns': {'required': ('sample',), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': ('origin and polarity absent stay absent',),
        'sources': sources('seismic-section-text.json', SEC + ':160 read_seismic_section', 'seismic-section-text/1')},
    'time-depth-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('depth', 'time'), 'optional': ('velocity',), 'extra': 'refused'},
        'sections': (), 'nulls': ('an empty velocity cell',),
        'declared': ('depth_type', 'depth_unit', 'time_kind', 'time_unit', 'datum', 'seismic_reference_elevation'),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': sources('time-depth-csv.json', 'ophiolite-connectors/src/asset_connectors/time_depth.py:135 read_csv', 'time-depth-csv/1')},
}

ORDER = ('points-csv/1', 'mesh-text/1', 'esri-ascii-grid/1', 'well-tops-csv/1', 'deviation-csv/1', 'opendtect-faultsticks/1', 'las2/1',
         'well-location/1', 'wavelet-text/1', 'model-section-text/1', 'seismic-section-text/1', 'time-depth-csv/1')

COMMON = ['kind', 'declared', 'context']
FIELDS = {
    'Table': COMMON + ['columns', 'rows'],
    'Grid': COMMON + ['header', 'ncols', 'nrows', 'registration', 'x', 'y', 'cell_size', 'nodata', 'cells'],
    'Mesh': COMMON + ['attributes', 'vertices', 'triangles'],
    'Sticks': COMMON + ['points'],
    'Location': COMMON + ['x', 'y', 'crs', 'elevation_reference'],
    'Wavelet': COMMON + ['header', 'wavelet_kind', 'dt', 't0', 'polarity', 'frequency_hz', 'corners_hz', 'samples'],
    'ModelSection': COMMON + ['header', 'axes', 'rocks', 'grid'],
    'SeismicSection': COMMON + ['header', 'axes', 'origin', 'polarity', 'grid'],
    'Las': COMMON + ['version', 'version_section', 'well', 'curves', 'parameters', 'other', 'null', 'data'],
}


def test_the_matrix_covers_exactly_the_process_kinds_and_states_each_row():
    bundled = json.loads((SDK / 'ophiolite/contracts/procedures/v1/rules.json').read_text())['process_kinds']
    assert bundled[-1] == 'well-residual/1' and tuple(bundled[:-1]) == ORDER
    assert readers.KINDS == ORDER
    assert set(readers.MATRIX) == set(ORDER)
    for kind in ORDER:
        assert readers.MATRIX[kind] == ROWS[kind], kind
        assert list(readers.MATRIX[kind]) == list(ROWS[kind]), kind  # every key, in order


def test_each_family_has_the_fields_of_the_strategy_and_is_frozen():
    assert sorted(cls.__name__ for cls in results.FAMILIES) == sorted(FIELDS)
    for cls in results.FAMILIES:
        assert [f.name for f in dataclasses.fields(cls)] == FIELDS[cls.__name__], cls.__name__
        assert cls.__dataclass_params__.frozen, cls.__name__
    assert {row['result'] for row in readers.MATRIX.values()} == set(FIELDS)


def typed(actual, expected, where):
    """`actual` equals `expected` with the type at every level: a dict expects a read-only mapping, a tuple a tuple."""
    if isinstance(expected, dict):
        assert type(actual) is MappingProxyType, where
        assert list(actual) == list(expected), where
        for key in expected: typed(actual[key], expected[key], where + '.' + key)
    elif isinstance(expected, tuple):
        assert type(actual) is tuple and len(actual) == len(expected), where
        for i, (a, e) in enumerate(zip(actual, expected)): typed(a, e, '%s[%d]' % (where, i))
    else:
        assert type(actual) is type(expected) and actual == expected, (where, actual, expected)


BIG = 9007199254740993  # 2**53 + 1: a float cannot hold it
INSTANCES = [
    (results.Table, dict(columns=['name', 'md', 'tvd', 'source', 'uwi'], rows=[['DCC', 1200.5, None, 'pick', '001'], ['NSB', 0.0, 1190.0, None, '001']]),
     dict(columns=('name', 'md', 'tvd', 'source', 'uwi'), rows=(('DCC', 1200.5, None, 'pick', '001'), ('NSB', 0.0, 1190.0, None, '001')))),
    (results.Grid, dict(header=[['ncols', '2'], ['nrows', '1'], ['xllcorner', '0'], ['yllcorner', '0'], ['cellsize', '25'], ['NODATA_value', '-9999']],
                        ncols=2, nrows=1, registration='corner', x=0.0, y=0.0, cell_size=25.0, nodata=-9999.0, cells=[[1.5, None]]),
     dict(header=(('ncols', '2'), ('nrows', '1'), ('xllcorner', '0'), ('yllcorner', '0'), ('cellsize', '25'), ('NODATA_value', '-9999')),
          ncols=2, nrows=1, registration='corner', x=0.0, y=0.0, cell_size=25.0, nodata=-9999.0, cells=((1.5, None),))),
    (results.Mesh, dict(attributes=['porosity', 'ntg'], vertices=[[0.0, 0.0, None, [0.2, None]], [1.0, 0.0, -10.0, [0.25, 0.5]], [0.0, 1.0, -11.0, [0.0, 0.0]]],
                        triangles=[[0, 1, 2]]),
     dict(attributes=('porosity', 'ntg'), vertices=((0.0, 0.0, None, (0.2, None)), (1.0, 0.0, -10.0, (0.25, 0.5)), (0.0, 1.0, -11.0, (0.0, 0.0))),
          triangles=((0, 1, 2),))),
    (results.Sticks, dict(points=[[1.0, 2.0, 3.0, BIG, '7'], [1.0, 2.0, 4.0, 2, None], [1.5, 2.0, 3.5, BIG, '8']]),
     dict(points=((1.0, 2.0, 3.0, BIG, '7'), (1.0, 2.0, 4.0, 2, None), (1.5, 2.0, 3.5, BIG, '8')))),
    (results.Location, dict(x=155000.0, y=463000.0, crs='EPSG:28992', elevation_reference={'kind': 'kelly-bushing', 'value': 12.5}),
     dict(x=155000.0, y=463000.0, crs='EPSG:28992', elevation_reference={'kind': 'kelly-bushing', 'value': 12.5})),
    (results.Wavelet, dict(header=[['kind', ['ormsby']], ['corners_hz', ['5', '10', '40', '60']]], wavelet_kind='ormsby', dt=0.002, t0=-0.002,
                           polarity='unknown', frequency_hz=None, corners_hz=[5.0, 10.0, 40.0, 60.0], samples=[0.0, 1.0, 0.0]),
     dict(header=(('kind', ('ormsby',)), ('corners_hz', ('5', '10', '40', '60'))), wavelet_kind='ormsby', dt=0.002, t0=-0.002,
          polarity='unknown', frequency_hz=None, corners_hz=(5.0, 10.0, 40.0, 60.0), samples=(0.0, 1.0, 0.0))),
    (results.ModelSection, dict(header=[['domain', ['depth']]], axes={'domain': 'depth', 'samples': 2, 'traces': 1, 'sample_interval': 4.0},
                                rocks=[[1, 2500.0, 2300.0, 'shale'], [BIG, 3000.0, 2400.0, 'tight sand']], grid=[[1], [BIG]]),
     dict(header=(('domain', ('depth',)),), axes={'domain': 'depth', 'samples': 2, 'traces': 1, 'sample_interval': 4.0},
          rocks=((1, 2500.0, 2300.0, 'shale'), (BIG, 3000.0, 2400.0, 'tight sand')), grid=((1,), (BIG,)))),
    (results.SeismicSection, dict(header=[], axes={'domain': 'time', 'samples': 1, 'traces': 2}, origin=None, polarity=None, grid=[[0.0, -1.5]]),
     dict(header=(), axes={'domain': 'time', 'samples': 1, 'traces': 2}, origin=None, polarity=None, grid=((0.0, -1.5),))),
    (results.Las, dict(version='1.20', version_section=[['VERS', '', '1.20', ''], ['WRAP', '', 'NO', '']], well=[['NULL', '', '-999.2500', 'null value']],
                       curves=[['DEPT', 'M', '', 'depth'], ['GR', 'GAPI', '', 'gamma'], ['GR', 'GAPI', '', 'gamma, second run']],
                       parameters=[], other=None, null='-999.2500', data=[[1000.0, 55.5, None]]),
     dict(version='1.20', version_section=(('VERS', '', '1.20', ''), ('WRAP', '', 'NO', '')), well=(('NULL', '', '-999.2500', 'null value'),),
          curves=(('DEPT', 'M', '', 'depth'), ('GR', 'GAPI', '', 'gamma'), ('GR', 'GAPI', '', 'gamma, second run')),
          parameters=(), other=None, null='-999.2500', data=((1000.0, 55.5, None),))),
]


@pytest.mark.parametrize('cls,given,expected', INSTANCES, ids=[i[0].__name__ for i in INSTANCES])
def test_a_result_keeps_every_value_with_its_type_and_shares_nothing(cls, given, expected):
    declared = {'depth_unit': 'm', 'depth_basis': 'unknown'}
    context = {'type': 'example', 'count': 2}
    result = cls(kind='example/1', declared=declared, context=context, **given)
    typed(result.declared, {'depth_unit': 'm', 'depth_basis': 'unknown'}, 'declared')
    typed(result.context, {'type': 'example', 'count': 2}, 'context')
    for name, value in expected.items(): typed(getattr(result, name), value, name)
    declared['depth_unit'] = 'ft'; del declared['depth_basis']; context['count'] = 3
    assert dict(result.declared) == {'depth_unit': 'm', 'depth_basis': 'unknown'} and result.context['count'] == 2
    with pytest.raises(TypeError): result.declared['depth_unit'] = 'ft'
    with pytest.raises(dataclasses.FrozenInstanceError): result.kind = 'other/1'


OPENED = []  # file-system events while `watching` is set; the hook stays installed for the process and does nothing otherwise
WATCH = [False]


def _hook(event, args):
    if WATCH[0] and event in ('open', 'os.listdir', 'os.scandir'): OPENED.append((event, args[0] if args else None))


sys.addaudithook(_hook)


def refused(**call):
    """The ReadRefused of read(**call), with every file-system event recorded while it ran."""
    OPENED.clear(); WATCH[0] = True
    try:
        with pytest.raises(readers.ReadRefused) as caught: readers.read(**call)
    finally: WATCH[0] = False
    assert OPENED == [], OPENED
    assert isinstance(caught.value, Refused)
    return caught.value


class Version:
    def __init__(self, **attributes): self.__dict__.update(attributes)


# E128 s3: the last kind is read (test_readers_las.py has its grammar); both call forms reach its reader
LAS = b'~Version\nVERS. 2.0 : v\nWRAP. NO : w\n~Well\nNULL. -999.25 : n\n~Curve\nDEPT.M : d\nGR.GAPI : g\n~A\n1500 -999.25\n1500.5 7\n'


def test_a_las_file_is_read_through_both_call_forms(tmp_path):
    path = tmp_path / 'well.las'; path.write_bytes(LAS)
    for result in (readers.read(path=path, kind='las2/1', declared={'crs': 'EPSG:28992'}),
                   readers.read(Version(path=path, kind='las2/1', declared={'crs': 'EPSG:28992'}))):
        assert type(result) is results.Las and result.kind == 'las2/1'
        assert (dict(result.declared), dict(result.context), result.version, result.null) == (
            {'crs': 'EPSG:28992'}, {'version': '2.0', 'layout': 'las2', 'delimiter': 'space'}, '2.0', '-999.25')
        assert (result.curves, result.data) == ((('DEPT', 'M', '', 'd'), ('GR', 'GAPI', '', 'g')), ((1500.0, None), (1500.5, 7.0)))


ARGUMENTS = 'Give read() a version, or a path and its kind, not both.'
CASES = [
    ('neither form', dict(), ARGUMENTS, 'arguments', 'version'),
    ('path without kind', dict(path='a.csv'), ARGUMENTS, 'arguments', 'kind'),
    ('kind without path', dict(kind='points-csv/1'), ARGUMENTS, 'arguments', 'path'),
    ('a version without kind', dict(version=Version(path='a.csv', declared={})), ARGUMENTS, 'arguments', 'version'),
    ('both forms, empty declarations', dict(version=Version(path='a.csv', kind='points-csv/1', declared={}), declared={}), ARGUMENTS, 'arguments', 'version'),
    ('both forms, a path', dict(version=Version(path='a.csv', kind='points-csv/1', declared={}), path='b.csv'), ARGUMENTS, 'arguments', 'version'),
    ('the residual kind', dict(path='r.json', kind='well-residual/1'),
     'A well-residual/1 version is read with ophiolite.residuals, not ophiolite.readers.', 'residual-kind', 'kind'),
    ('an unknown kind', dict(path='a.csv', kind='segy/1'),
     'segy/1 is not a kind ophiolite.readers reads; it reads the 12 process kinds in ophiolite.readers.KINDS.', 'not-a-process-kind', 'kind'),
    ('a kind that is not text', dict(path='a.csv', kind=['points-csv/1']),
     "['points-csv/1'] is not a kind ophiolite.readers reads; it reads the 12 process kinds in ophiolite.readers.KINDS.", 'not-a-process-kind', 'kind'),
]


@pytest.mark.parametrize('name,call,sentence,code,field', CASES, ids=[c[0] for c in CASES])
def test_a_wrong_call_is_refused_with_its_sentence_code_and_field(name, call, sentence, code, field):
    error = refused(**call)
    assert (str(error), error.code, error.field, error.row) == (sentence, code, field, None)


PROBE = r'''
import os, sys
from pathlib import Path
home = Path(os.environ['HOME']).resolve()
for relative in ('.ophiolite/credentials', '.config/ophiolite/projects/canary.json'):
    (home / relative).parent.mkdir(parents=True, exist_ok=True); (home / relative).write_text('canary')
def audit(event, args):
    if event.startswith('socket.'): raise AssertionError('import attempted network: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).absolute()
        if path == home or home in path.parents: raise AssertionError('import opened under HOME: %s' % path)
sys.addaudithook(audit)
sys.path.insert(0, os.environ['SDK_SOURCE'])
import ophiolite.readers
assert Path(ophiolite.readers.__file__).resolve().is_relative_to(Path(os.environ['SDK_SOURCE']).resolve()), ophiolite.readers.__file__
loaded = sorted(m for m in ('httpx', 'ophiolite.client', 'ophiolite.procedures', 'asset_connectors', 'lasio', 'numpy') if m in sys.modules)
assert not loaded, loaded
print('readers import PASS')
'''


def test_importing_the_readers_contacts_nothing_and_loads_no_client(tmp_path):
    home = tmp_path / 'home'; home.mkdir(); cwd = tmp_path / 'empty'; cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ('TOKEN', 'CREDENTIAL', 'SECRET', 'PYTHONPATH'))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_CACHE_HOME=str(home / '.cache'), PYTHONDONTWRITEBYTECODE='1',
               SDK_SOURCE=str(SDK))
    result = subprocess.run([sys.executable, '-I', '-c', PROBE], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stdout.strip() == 'readers import PASS', result.stdout + result.stderr
