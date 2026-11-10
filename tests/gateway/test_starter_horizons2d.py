"""E137 s6b C3 (strategy D-1', D-2, D-3, D-7): a definition names a 2D horizon under `horizons`; the export writes one
points-csv/1 file per line with a defined pick, the SDK reads each back against export.json and lands it with the 3D
horizons' declarations, and ResInsight and Python say they do not place or read 2D horizons.

The expected texts and digests are the connector's own literals (ophiolite-opendtect tests/test_export_horizons2d.py)."""
import json
import os
import shutil

import pytest

from ophiolite import starter, starter_archive as sa
from ophiolite.errors import Refused
from test_starter_archive_pack import CRS, build, odbind, project  # noqa: F401 (fixtures)
from test_starter_export import CONNECTOR, FAKE, VOLUME, made, run

L2_TEXT = 'x,y,z,trace\n500001.0,10.0,2000.0999755859375,201\n'
L1_TEXT = 'x,y,z,trace\n500100.125,20.0,1500.25,101\n500112.5,20.5,1504.5,102\n500137.5,21.5,1508.75,104\n'
L2_DIGEST = '65ca97ad98408388e02fea999ff2ae05d50f5e6f353277fecdd61e2ea846cf08'
L1_DIGEST = 'acabe2a775e148f3dd38af9883e2e2d3a20ea0c72b7c0c6a22f824d0cb584a96'
FILES = ['horizons2d/Syn2DH/L2.csv', 'horizons2d/Syn2DH/L1.csv']
DECLARED = {'crs': CRS, 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 'ms', 'positive': 'down'}


def with_2d(d):
    for c in d['contents']:
        if c['kind'] == 'horizons': c['ids'] = c['ids'] + ['Syn2DH']
    d['decisions'] += [{'topic': t, 'subject': 'Syn2DH', 'value': v, 'source': 'data'} for t, v in dict(VOLUME, nulls=sa.NULLS['horizons']).items()]


def exported(folder, out):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        return run(folder, out)


@pytest.fixture(scope='module')
def once(tmp_path_factory):
    """One real export of the synthetic survey with the 3D horizon Top and the 2D horizon Syn2DH."""
    folder, out = made(tmp_path_factory.mktemp('definition'), edit=with_2d), tmp_path_factory.mktemp('out')
    report, export = exported(folder, out)
    return folder, out, report, export


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


def test_each_line_is_reported_with_its_form_line_and_how(once):
    """D-1', D-3. Catches: a 2D line reported without `form` (it would read as 3D); its `how` the 3D sentence; the
    empty line dropped from the report."""
    _, _, report, export = once
    assert [f for f in report['files'] if f.get('form')] == [
        {'path': FILES[0], 'kind': 'horizons', 'object': 'Syn2DH', 'form': '2d', 'line': 'L2'},
        {'path': FILES[1], 'kind': 'horizons', 'object': 'Syn2DH', 'form': '2d', 'line': 'L1'}]
    how = {d['path']: d['how'] for d in report['derived']}
    assert how[FILES[1]] == ('odbind Horizon2D.getz and getxy of line L1 of the 2D horizon Syn2DH, written as points-csv/1 x,y,z,trace, '
                             'its defined picks in trace order, unchanged')
    assert report['horizons2d'] == {'Syn2DH': {'empty_lines': ['SynH2Db']}}
    assert [(export / 'files' / p).read_text() for p in FILES] == [L2_TEXT, L1_TEXT]


def test_the_sdk_reads_each_line_back_as_export_json_states_it(once):
    """D-2. Catches: the form dispatch dropped (the 3D reader refuses the header); a digest of anything but the bytes."""
    _, _, _, export = once
    for path, count, digest in ((FILES[0], 1, L2_DIGEST), (FILES[1], 3, L1_DIGEST)):
        f = {'path': path, 'kind': 'horizons', 'object': 'Syn2DH', 'form': '2d'}
        assert sa.READERS['horizons'](export / 'files' / path, f) == ({'count': count}, digest)


def staged(tmp_path, once):
    folder, _, _, export = once
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    return stage, json.loads((stage / 'export.json').read_text()), sa.definition(folder / 'definition.json')


@pytest.mark.parametrize('edit, reason', [
    (lambda t: t.replace('1504.5', '1504.25'), 'Syn2DH'),
    (lambda t: t.replace('x,y,z,trace', 'x,y,z,inline'), 'does not start x,y,z,trace'),
    (lambda t: t.replace(',104\n', ',101\n'), 'in trace order'),
    (lambda t: t.replace('1508.75', '1508.7'), 'in trace order'),
    (lambda t: t + '500150.0,22.0,1510.0,105\n', 'Syn2DH'),
])
def test_read_back_refuses_a_line_that_is_not_what_the_export_states(tmp_path, once, edit, reason):
    """Catches: a moved z or an extra row accepted (digest, count); another header; a trace twice or out of order; a z
    no float32 holds."""
    stage, doc, defn = staged(tmp_path, once)
    p = stage / FILES[1]
    p.write_text(edit(p.read_text()))
    assert reason in refused(sa.read_back, stage, doc, defn)


def test_a_2d_line_lands_as_points_with_its_trace_and_the_horizons_declarations(tmp_path, project):
    """D-1', D-4. Catches: a 2D line landed under another profile; its declarations other than the 3D horizons'; the
    `trace` column lost."""
    folder, out = made(tmp_path / 'definition', edit=with_2d), tmp_path / 'export'
    exported(folder, out)
    build(folder, out, project)
    landing = json.loads((folder / 'pack/landing.json').read_text())
    for path in FILES:
        assert (landing['inputs'][path]['profile'], landing['inputs'][path]['output']['kind']) == ('points-csv/1', 'horizons')
    profile, declared, _ = project.read[FILES[1].rsplit('/', 1)[1]]
    assert (profile, declared) == ('points-csv/1', DECLARED)
    pack = json.loads((folder / 'pack/starter.json').read_text())
    assert [d['path'] for d in pack['derived'] if d['path'].startswith('horizons2d/')] == FILES


def test_resinsight_and_python_say_they_do_not_place_or_read_2d_horizons():
    """D-7. Catches: a pack with 2D horizons whose oracles are silent about them."""
    assert starter.H2D_RI_LINE in starter.resinsight_waiting(False, h2d=True)['compared']
    assert starter.H2D_RI_LINE not in starter.resinsight_waiting(False)['compared']
    assert starter.python_waiting(False, h2d=True)['compared'][-1] == starter.PY_H2D_LINE
    assert starter.python_waiting(False) == starter.ORACLE_PYTHON


def test_a_line_of_100001_picks_reads_back_and_is_admitted_as_point_columns(tmp_path):
    """E139 switch, D-1'. Catches: a long line refused by the SDK reader; the trace column lost or read as z above
    100,000 nodes (the admission's point-columns/1 scan of the same bytes)."""
    import hashlib
    from asset_connectors import point_rows
    path = tmp_path / 'L.csv'  # the exporter's form (connector test_export_horizons2d.py), written here
    path.write_bytes(('x,y,z,trace\n' + ''.join('%r,10.0,1500.25,%d\n' % (500000.0 + k, k + 1) for k in range(100_001))).encode())
    assert sa.READERS['horizons'](path, {'path': 'horizons2d/Syn2DH/L.csv', 'kind': 'horizons', 'form': '2d'}) == (
        {'count': 100_001}, hashlib.sha256(path.read_bytes()).hexdigest())
    found = point_rows.scan(path.read_bytes(), {'crs': CRS, 'z_unit': 'ms'}, 200_000)
    assert (found.count, found.names, found.has_z) == (100_001, ['x', 'y', 'z', 'trace'], True)


H2D_LINES = ['2D horizon line “L2” files/horizons2d/Syn2DH/L2.csv (item item-L2-csv at r1) imported by you into OpendTect as “Syn2DH”: 3 values, '
             '0 differences (largest x/y 0 m, z 0 ms)',
             '2D horizon line “L1” files/horizons2d/Syn2DH/L1.csv (item item-L1-csv at r1) imported by you into OpendTect as “Syn2DH”: 9 values, '
             '0 differences (largest x/y 0 m, z 0 ms)']
NAN = float('nan')
THEIRS = [{'line': 'L2', 'trace': [201, 202, 203], 'x': [500001.0, 500013.5, 500026.0], 'y': [10.0, 10.25, 10.5], 'z': [2000.0999755859375, NAN, 1e30]},
          {'line': 'L1', 'trace': [101, 102, 103, 104], 'x': [500100.125, 500112.5, 500125.0, 500137.5], 'y': [20.0, 20.5, 21.0, 21.5],
           'z': [1500.25, 1504.5, NAN, 1508.75]}]


def person(state, lines):
    """The destination survey's line geometries and, when LINES, the person's import of Syn2DH in OpendTect's GUI."""
    import pickle
    import numpy as np
    stored = pickle.loads(state.read_bytes()) if state.exists() else {'cubes': {}, 'horizons': {}}
    stored['geometries'] = {d['line']: {'trc': np.array(d['trace'], dtype=np.int32), 'ref': np.ones(len(d['trace']), dtype=np.float32),
                                        'x': np.array(d['x']), 'y': np.array(d['y'])} for d in THEIRS}
    stored['person'] = {'horizons2d': {'Syn2DH': lines} if lines else {}}
    state.write_bytes(pickle.dumps(stored))


def test_the_qualification_states_the_2d_step_then_records_each_line_placed_by_you(tmp_path, project, odbind):
    """D-5 (R1-4): the step first (nothing compared), then the person's import read back: `starter opendtect` keeps
    each line's row in result.json and writes its line into the oracle. Mutations: the connector's comparison row
    dropped (NOT_READ_BACK); `_compared_line` without its 2D branch (the generic "… 0 moved")."""
    from test_starter_faults import qualified, survey_at
    folder, out = made(tmp_path / 'definition', edit=with_2d), tmp_path / 'export'
    exported(folder, out)
    build(folder, out, project)
    survey = survey_at(tmp_path)
    person(odbind, None)
    _, result = qualified(folder, survey, project)
    step = 'Import opendtect-import/Syn2DH.txt in OpendTect (Survey > Import > Horizons > ASCII 2D > Single 2D Horizon'
    assert [(n['file'], n['reason'].startswith(step)) for n in result['not_placed'] if n.get('line')] == [
        ('horizons2d/Syn2DH/L2.csv', True), ('horizons2d/Syn2DH/L1.csv', True)]
    assert (folder / 'pack/opendtect-import/Syn2DH.txt').read_text().startswith('line,trace,x,y,z\nL2,201,500001.0,10.0,2000.0999755859375\n')
    person(odbind, THEIRS)
    doc, result = qualified(folder, survey, project)
    rows = [e for e in result['placed'] if e.get('form') == '2d']
    assert [(e['file'], e['line'], e['picks'], e['differences'], e['outcome']) for e in rows] == [
        ('horizons2d/Syn2DH/L2.csv', 'L2', 1, 0, 'by you'), ('horizons2d/Syn2DH/L1.csv', 'L1', 3, 0, 'by you')]
    assert [line for line in doc['targets'][0]['oracle']['compared'] if line.startswith('2D horizon line')] == H2D_LINES
