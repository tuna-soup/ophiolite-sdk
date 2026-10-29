"""E128 s4: the residual entry's readers (`residuals.read_tops`, `read_survey`, `read_grid`) and the fixture server's
`testing.read_las` are views over ophiolite.readers (E128-readers-S4-COMMIT-STRATEGY.md). Every input is a byte literal
written here or an E119b fixture; every expected value is a literal written from the old readers' output (probe 5 of
the lane) or the readers' sentence. The server's reader is then given the same bytes and asked to agree (parity), never
used as the expectation."""
import json
from pathlib import Path

import pytest

from ophiolite import residuals, testing, writers
from ophiolite.procedures import LocalVersion, NotRun
from ophiolite.readers import ReadRefused

from test_reference_residual import FLAT, FakeProject, bore, grid_original, member, rev, three_members

NO_REPAIR = ' No repair was applied.'
GRID_MAX = 4194304
HERE = Path(__file__).parent / 'fixtures' / 'well_geometry'
SPATIAL = {'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'NAP'}
DECLARED_SURVEY = {'depth_unit': 'm', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'}

TOPS = b'name,md,quality\nNSB,1100.5,good\nDCC,1210,\n'
TOPS_MD_FIRST = b'MD,Name\n1100.5,NSB\n1210,DCC\n'
SURVEY = b'md,inclination,azimuth,tvd\n0,0,0,0\n100,,,\n200,1.5,45,199.9\n'
SURVEY_NO_TVD = b'md,inclination,azimuth\n0,0,0\n100,2,90\n'
GRID = b'ncols 3\nnrows 2\nxllcorner 1000\nyllcorner 2000\ncellsize 25\nNODATA_value -9999\n1 2 3\n4 -9999 6.5\n'
LAS = (b'~Version\nVERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\nWRAP.   NO : One line per depth step\n'
       b'~Well\nSTRT.m 1000.0 :\nSTOP.m 1001.0 :\nSTEP.m 0.5 :\nNULL.   -999.2500 : Null value\nWELL.   W-1 : Well\n'
       b'~Curve\nDEPT.m      : Depth\nRHOB.g/cc   : Bulk density\nGR.gAPI     : Gamma ray\n'
       b'~A\n1000.0 2.45 40.0\n1000.5 2.50 -999.2500\n1001.0 2.55 120.0\n')

TOPS_READ = [{'name': 'NSB', 'md': 1100.5}, {'name': 'DCC', 'md': 1210.0}]
SURVEY_READ = {'context': {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
               'stations': [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': 0.0},
                            {'md': 100.0, 'inclination': None, 'azimuth': None, 'tvd': None},
                            {'md': 200.0, 'inclination': 1.5, 'azimuth': 45.0, 'tvd': 199.9}]}
SURVEY_NO_TVD_READ = {'context': {'type': 'trajectory', 'depth_unit': 'unknown', 'angle_unit': 'deg', 'azimuth_reference': 'unknown',
                                  'depth_datum': 'unknown'},
                      'stations': [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}, {'md': 100.0, 'inclination': 2.0, 'azimuth': 90.0, 'tvd': None}]}
GRID_READ = {'context': {'type': 'regular-grid-surface', 'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down',
                         'vertical_datum': 'NAP', 'registration': 'corner', 'row_order': 'north-to-south', 'ncols': 3, 'nrows': 2, 'cell_size': 25.0,
                         'x_first_center': 1012.5, 'y_first_center': 2037.5},
             'values': [1.0, 2.0, 3.0, 4.0, None, 6.5]}
LAS_READ = {'null': '-999.2500', 'index': 'DEPT', 'curves': {'DEPT': 'm', 'RHOB': 'g/cc', 'GR': 'gAPI'},
            'columns': {'DEPT': [1000.0, 1000.5, 1001.0], 'RHOB': [2.45, 2.5, 2.55], 'GR': [40.0, None, 120.0]}}


def plain(actual, expected, where):
    """`actual` equals `expected` with the type at every level: a dict expects a dict, a list a list (never a tuple or a
    read-only mapping), in the same key order."""
    if isinstance(expected, dict):
        assert type(actual) is dict, (where, type(actual))
        assert list(actual) == list(expected), (where, list(actual), list(expected))
        for key in expected: plain(actual[key], expected[key], where + '.' + key)
    elif isinstance(expected, list):
        assert type(actual) is list and len(actual) == len(expected), (where, actual, expected)
        for i, (a, e) in enumerate(zip(actual, expected)): plain(a, e, '%s[%d]' % (where, i))
    else:
        assert type(actual) is type(expected) and actual == expected, (where, actual, expected)


def written(tmp_path, raw, name='input'):
    path = tmp_path / name
    path.write_bytes(raw)
    return path


# ---------------------------------------------------------------- T-V1 and T-V2: keys, container types and the old values

def test_each_view_returns_the_old_shape_and_values(tmp_path):
    """T-V1/T-V2. Mutations: Mk1 the survey context copies the whole normalized context -> extra keys, red; Mk2 the grid
    context in another key order -> red; Mk4 `stations` left as the rows' tuples -> red; Mv2 `tvd` taken from `md` ->
    red on station 3; Mv3 values flattened by column -> [1, 4, 2, ...], red."""
    plain(residuals.read_tops(written(tmp_path, TOPS)), TOPS_READ, 'tops')
    plain(residuals.read_survey(written(tmp_path, SURVEY), DECLARED_SURVEY), SURVEY_READ, 'survey')
    plain(residuals.read_survey(written(tmp_path, SURVEY_NO_TVD), {}), SURVEY_NO_TVD_READ, 'survey without tvd')
    plain(residuals.read_grid(written(tmp_path, GRID), SPATIAL), GRID_READ, 'grid')


def test_tops_columns_are_found_by_name(tmp_path):
    """T-V2. Mutation Mv1: the tops view maps by column position -> name and md swap on this file, red."""
    plain(residuals.read_tops(written(tmp_path, TOPS_MD_FIRST)), TOPS_READ, 'tops, md first')


def test_read_las_keeps_the_null_as_written_and_reads_curves_by_order():
    """T-V1/T-V2. Mutations: Mk3 `columns` is the rows (the result's data) -> red; Mk5 a column left a tuple -> red; Mv4
    `null` as str(float(null)) -> '-999.25', red only because the literal is written -999.2500."""
    plain(testing.read_las(LAS), LAS_READ, 'las')


def test_read_las_lets_a_refusal_through():
    """S4-D2: the fixture helper is not the residual entry, so its refusal stays a ReadRefused."""
    with pytest.raises(ReadRefused):
        testing.read_las(LAS.replace(b'2.50 -999.2500', b'2.50'))


# ---------------------------------------------------------------- T-V3: refusals carry the readers' sentence

REFUSED = {
    'tops, more cells than the header': ('tops', b'name,md\nDCC,1,2\n', None, 'Data row 1 has 3 cells; the header has 2.'),
    'tops, a trailing comma': ('tops', b'name,md\nDCC,1003.25,\n', None, 'Data row 1 has 3 cells; the header has 2.'),
    'tops, an empty name': ('tops', b'name,md\n,1\n', None, 'Top name on data row 1 is empty or longer than 128 characters.'),
    'tops, a repeated header name': ('tops', b'name,md,name\nA,1,B\n', None, 'The header repeats a column name.'),
    'tops, two wells': ('tops', b'name,md,well\nDCC,1,A\nDCC,2,B\n', None,
                        "This file holds tops of 2 wells (column well); upload one well's tops per file until multi-well tables arrive."),
    'tops, a tvd not a number': ('tops', b'name,md,tvd\nA,1,x\n', None, 'Vertical depth on data row 1 is not a number.'),
    'tops, header only': ('tops', b'name,md\n', None, 'The file has no data rows.'),
    'tops, a 129-character name': ('tops', b'name,md\n' + b'N' * 129 + b',1\n', None, 'Top name on data row 1 is empty or longer than 128 characters.'),
    'tops, a short row under an extra column': ('tops', b'name,md,quality\nA,1\n', None, 'Data row 1 has 2 cells; the header has 3.'),
    'tops, md not a number': ('tops', b'name,md\nA,x\n', None, 'Measured depth on data row 1 is not a number.'),
    'survey, an unknown column': ('survey', b'md,inclination,azimuth,extra\n0,0,0,x\n', {},
                                  'The header must name the columns md, inclination, azimuth and optionally tvd.'),
    'survey, md not increasing': ('survey', b'md,inclination,azimuth\n100,0,0\n0,0,0\n', {},
                                  'Measured depth on data row 2 does not increase; stations must be in increasing measured depth.'),
    'survey, inclination outside 0-180': ('survey', b'md,inclination,azimuth\n0,200,0\n', {}, 'Inclination on data row 1 is outside 0–180 degrees.'),
    'survey, azimuth outside 0-360': ('survey', b'md,inclination,azimuth\n0,0,400\n', {}, 'Azimuth on data row 1 is outside 0–360 degrees.'),
    'survey, a declared value outside the vocabulary': ('survey', SURVEY_NO_TVD, {'azimuth_reference': 'Grid-North'},
                                                        'Choose the azimuth reference from: true-north, grid-north, magnetic-north, unknown.'),
    'grid, a declared crs in lower case': ('grid', GRID, {**SPATIAL, 'crs': 'epsg:28992'}, 'Declare the coordinate reference system as EPSG:<code>, or as unknown.'),
    'grid, a declared meaning in capitals': ('grid', GRID, {**SPATIAL, 'z_meaning': 'Depth'}, 'Choose the value meaning from: depth, elevation, time, unknown.'),
    'grid, a declared direction in capitals': ('grid', GRID, {**SPATIAL, 'positive': 'DOWN'}, 'Choose the positive direction from: up, down, unknown.'),
    'grid, cell size 0': ('grid', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 0\n1\n', {}, 'The cell size must be positive.'),
    'grid, a negative cell size': ('grid', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize -1\n1\n', {}, 'The cell size must be positive.'),
    'grid, a repeated header key': ('grid', b'ncols 1\nncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n', {},
                                    'Grid header line "ncols" is malformed or repeated.'),
    'grid, an extra token on a header line': ('grid', b'ncols 1 x\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n', {},
                                              'Grid header line "ncols" is malformed or repeated.'),
    'grid, ncols not a whole number': ('grid', b'ncols 1.0\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n', {},
                                       'The grid header must declare whole-number ncols and nrows.'),
    'grid, more cells than the limit': ('grid', b'ncols 2049\nnrows 2049\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n', {},
                                        'The grid must have between 1 and 4194304 cells.'),
}
VIEWS = {'tops': lambda path, declared: residuals.read_tops(path), 'survey': residuals.read_survey, 'grid': residuals.read_grid}
KINDS = {'tops': 'well-tops-csv/1', 'survey': 'deviation-csv/1', 'grid': 'esri-ascii-grid/1'}


@pytest.mark.parametrize('name', list(REFUSED))
def test_a_view_refuses_with_the_readers_sentence(tmp_path, name):
    """T-V3. Mutations: Mr1 the view catches the refusal and returns [] -> no raise, red; Mr2 the view lets ReadRefused
    through -> not Unreadable, red; Mr3 the tops view keeps the old `_csv` -> the trailing-comma row reads, red."""
    view, raw, declared, sentence = REFUSED[name]
    with pytest.raises(residuals.Unreadable) as refused:
        VIEWS[view](written(tmp_path, raw), declared)
    assert str(refused.value) == sentence + NO_REPAIR
    assert type(refused.value.__cause__) is ReadRefused


def local_inputs(tmp_path, tops=b'name,md\nNSB,900\nDCC,1003.25\n', survey=None):
    """The four inputs of a residual entry for one cored member, as `LocalVersion`s naming their project versions."""
    survey = survey or writers.write_survey([{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None},
                                             {'md': 2000.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}],
                                            depth_unit='m', azimuth_reference='grid-north', depth_datum='KB').bytes
    trajectory = {'asset_id': 'path-1', 'revision': rev(1001)}
    selection = written(tmp_path, json.dumps({'members': [member(1, trajectory)]}).encode(), 'selection.json')
    grid = {k: FLAT['context'][k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum')}
    return {'selection': [LocalVersion(str(selection), 'well-set/1', {}, 'set-1', rev(9))],
            'tops': [LocalVersion(str(written(tmp_path, tops, 'tops.csv')), 'well-tops-csv/1', {}, 'tops-1', rev(1), bore(1))],
            'trajectories': [LocalVersion(str(written(tmp_path, survey, 'survey.csv')), 'deviation-csv/1', dict(DECLARED_SURVEY), 'path-1', rev(1001))],
            'surface': [LocalVersion(str(written(tmp_path, grid_original(FLAT), 'grid.asc')), 'esri-ascii-grid/1', grid, 'grid-1', rev(2000))]}


SETTINGS = {'formation': 'DCC', 'display_unit': 'm'}


def test_the_entry_reads_through_the_views_and_refuses_a_bad_tops_file(tmp_path):
    """T-V3: `from_inputs` computes on good inputs and raises the view's Unreadable for a trailing-comma tops file."""
    document = residuals.from_inputs(local_inputs(tmp_path), SETTINGS)
    assert [(r['wellbore'], r['reason']) for r in document['rows']] == [(bore(1), None)]
    assert document['rows'][0]['residual'] == pytest.approx(3.25, abs=1e-6)
    with pytest.raises(residuals.Unreadable) as refused:
        residuals.from_inputs(local_inputs(tmp_path, tops=b'name,md\nDCC,1003.25,\n'), SETTINGS)
    assert str(refused.value) == 'Data row 1 has 3 cells; the header has 2.' + NO_REPAIR


def test_a_run_of_the_reference_procedure_reports_the_view_refusal(tmp_path, monkeypatch):
    """T-V3 (round 1, 3e): the run's record of the child's exception (procedures.py `fail('raised', ...)`) names
    Unreadable and the readers' sentence. Mutation Mr2 (ReadRefused through the view) -> type 'ReadRefused', red."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    client = FakeProject()
    client.procedure_register(residuals.reference_path())
    selection, _ = three_members(client)
    profile, typed, _, context = client.versions[('tops-1', rev(1))]
    client.versions[('tops-1', rev(1))] = (profile, typed, b'name,md\nNSB,900\nDCC,1003.25,\n', context)
    with pytest.raises(NotRun) as refused:
        residuals.run(client, 'residual-at-wells', tmp_path / 'out', '@%s:%s' % (selection['asset_id'], selection['revision']),
                      '@grid-1:' + rev(2000), 'DCC', version=1, yes=True)
    assert refused.value.code == 'raised'
    assert (refused.value.details['type'], refused.value.details['message']) == ('Unreadable', 'Data row 2 has 3 cells; the header has 2.' + NO_REPAIR)
    assert not (tmp_path / 'out').exists()


# ---------------------------------------------------------------- T-V4: parity with the server's reader, and per-file limits

def server(typed_reader, kind, raw, declared):
    return typed_reader.read_typed(kind, raw, declared, max_cells=GRID_MAX, max_encoded=None)


def e119b_inputs():
    """E119b's tops tables (test_residuals.py), its 21 trajectories written as surveys and its grid fixtures with and
    without a BOM (probe 2: the old readers and the views agree on all 53)."""
    yield 'tops vertical', 'tops', b'name,md\nNSB,1100\nDCC,1210\n', None
    yield 'tops twice', 'tops', b'name,md\nDCC,1300\nNSB,1200\nDCC,1250\nDCC,1250\n', None
    for case in json.loads((HERE / 'cases.json').read_text())['cases']:
        yield 'survey ' + case['name'], 'survey', writers.write_survey(case['trajectory']['stations'], **DECLARED_SURVEY).bytes, dict(DECLARED_SURVEY)
    for path in sorted(HERE.glob('*.json')):
        fixture = json.loads(path.read_text())
        if path.name == 'cases.json' or fixture.get('context', {}).get('type') != 'regular-grid-surface': continue
        declared = {k: fixture['context'][k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum')}
        yield 'grid ' + path.name, 'grid', grid_original(fixture), declared
        yield 'grid with a BOM ' + path.name, 'grid', b'\xef\xbb\xbf' + grid_original(fixture), declared


PARITY = {name: (view, raw, declared) for name, view, raw, declared in e119b_inputs()}


def test_the_e119b_inputs_are_all_present():
    assert [sum(n.startswith(p) for n in PARITY) for p in ('tops ', 'survey ', 'grid ')] == [2, 21, 30]


@pytest.mark.parametrize('name', list(PARITY))
def test_a_view_agrees_with_the_server_reader(tmp_path, name):
    """T-V4 (S4-D6). Mutation Mp1: a station's azimuth set to its inclination -> red on every deviated case."""
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    view, raw, declared = PARITY[name]
    ours = VIEWS[view](written(tmp_path, raw), declared)
    context, data, _ = server(typed_reader, KINDS[view], raw, declared or {})
    if view == 'tops':
        assert ours == [{'name': t['name'], 'md': t['md']} for t in data['tops']]
    elif view == 'survey':
        assert ours['stations'] == data['stations'] and ours['context'] == {k: context[k] for k in residuals.SURVEY_CONTEXT}
    else:
        assert ours['values'] == data['values'] and ours['context'] == {k: context[k] for k in residuals.GRID_CONTEXT}


@pytest.mark.parametrize('name', list(REFUSED))
def test_the_server_reader_refuses_what_a_view_refuses(tmp_path, name):
    """T-V4 (S4-D6): each refusal of T-V3 is the server's too, with the same sentence (both end in the no-repair words)."""
    typed_reader = pytest.importorskip('asset_connectors.typed_reader')
    view, raw, declared, sentence = REFUSED[name]
    try:
        VIEWS[view](written(tmp_path, raw), declared)
    except residuals.Unreadable as refused:
        ours = str(refused)
    with pytest.raises(typed_reader.TypedReadError) as theirs:
        server(typed_reader, KINDS[view], raw, declared or {})
    assert ours == sentence + NO_REPAIR and str(theirs.value) == sentence + NO_REPAIR


def rows(header, row, count):
    return (header + ''.join(row % i for i in range(count))).encode()


@pytest.mark.parametrize('view', ['tops', 'survey'])
def test_ten_thousand_rows_read_and_one_more_is_refused(tmp_path, view):
    """T-V4 (S4-D5): the per-file limit of the readers reaches the residual entry, through the view and through
    `from_inputs`. A per-file limit, not D-17 6-8's limit on required rows across members. Mutations: Ml1 MAX_ROWS + 1 in
    readers/tables.py -> 10,001 reads, red; Ml2 the view keeps the first 10,000 rows -> 10,001 reads silently, red."""
    header, row = ('name,md\n', 'NSB,%d\n') if view == 'tops' else ('md,inclination,azimuth\n', '%d,0,0\n')
    read = VIEWS[view](written(tmp_path, rows(header, row, 10000)), {})
    assert len(read if view == 'tops' else read['stations']) == 10000
    refused = 'The file has more than 10000 data rows.' + NO_REPAIR
    with pytest.raises(residuals.Unreadable, match='^' + refused + '$'):
        VIEWS[view](written(tmp_path, rows(header, row, 10001)), {})
    given = {view: rows(header, row, 10000)} if view == 'tops' else {'survey': rows(header, row, 10000)}
    document = residuals.from_inputs(local_inputs(tmp_path, **given), SETTINGS)
    assert len(document['rows']) == 1
    given = {view: rows(header, row, 10001)}
    with pytest.raises(residuals.Unreadable, match='^' + refused + '$'):
        residuals.from_inputs(local_inputs(tmp_path, **given), SETTINGS)
