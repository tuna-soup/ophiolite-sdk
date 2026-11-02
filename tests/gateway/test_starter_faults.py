"""E137 s2 C3 (strategy D-2, D-4, D-5, D-6, F1, A-1, R2-9): a starter pack holds the faults it names.

The real exporter runs on the fake odbind in its own process (as `test_starter_export` runs it); the SDK reads each
fault file back with `ophiolite.faults.read` (the Connectors' rule), requires the export's own spelling, recomputes
its axes and D-4 digest, declares it as `opendtect-faultsticks/1` in time and seconds and lands it through the
Connectors' intake (`test_starter_archive_pack.Intake`). Every expected value is a literal: the fake's stick set SynF
(three sticks of three points, z 0.104, 0.108, 0.112 s) and 3D fault SynF3D (sticks of two, three and four points)."""
import json
import os
import pickle
import shutil

import pytest

from ophiolite import faults, starter, starter_archive as sa
from ophiolite.errors import Refused, ValidationFailed
from test_starter_archive_pack import (CRS, RESULT, another, build, current, nothing_landed, odbind, pack_files, project, qualified, rebound,  # noqa: F401 (fixtures)
                                     replaced_file, survey_at, typed_reader)
from test_starter_build import failing, landed_entry
from test_starter_export import CONTENTS, FAKE, CONNECTOR, made, run

from asset_connectors import faults as connector_faults  # noqa: E402 (the Connectors' reader, F1's twin)

SYNF = [[(500010.0, 20.0, 0.104), (500011.0, 21.0, 0.108), (500012.0, 22.0, 0.112)],
        [(500035.0, 20.0, 0.104), (500036.0, 21.0, 0.108), (500037.0, 22.0, 0.112)],
        [(500060.0, 20.0, 0.104), (500061.0, 21.0, 0.108), (500062.0, 22.0, 0.112)]]
SYNF3D = [[(500100.0, 40.0, 0.1), (500101.0, 41.0, 0.12)],
          [(500125.0, 40.0, 0.124), (500126.0, 41.5, 0.116), (500127.0, 43.0, 0.108)],
          [(500150.0, 40.0, 0.1), (500151.0, 41.0, 0.104), (500152.0, 42.0, 0.108), (500153.0, 43.0, 0.112)]]
SYNF_TEXT = ('# OpendTect FaultStickSet\n'
             '500010.0 20.0 0.104 0\n500011.0 21.0 0.108 0\n500012.0 22.0 0.112 0\n'
             '500035.0 20.0 0.104 1\n500036.0 21.0 0.108 1\n500037.0 22.0 0.112 1\n'
             '500060.0 20.0 0.104 2\n500061.0 21.0 0.108 2\n500062.0 22.0 0.112 2\n')
DIGEST = {'SynF': '653f99965d93988d47684f3de31a84d27174ba244b89bad27eefde6046124f0a',  # ophiolite-opendtect tests/test_export_faults.py
          'SynF3D': '4f7d2494652f452902b2a9e77689b682612d5e193890d6b6d796f27fb8e91afb'}
DECLARED = {'crs': CRS, 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 's', 'positive': 'down', 'vertical_datum': 'unknown'}
FAULT_TOPICS = {'crs': CRS, 'domain': 'time', 'units': 's'}


def sticks_of(literal):
    return [{'index': i, 'points': [{'x': x, 'y': y, 'z': z} for x, y, z in st]} for i, st in enumerate(literal)]


def faulted(d, ids=('SynF', 'SynF3D'), topics=FAULT_TOPICS, keep=None):
    if keep is not None:  # the kept kinds' objects and the archive's own decisions only
        dropped = {x for c in d['contents'] if c['kind'] not in keep for x in c['ids']} - {x for c in d['contents'] if c['kind'] in keep for x in c['ids']}
        d['contents'] = [c for c in d['contents'] if c['kind'] in keep]
        d['decisions'] = [r for r in d['decisions'] if r['subject'] not in dropped]
    d['contents'] += [{'kind': 'faults', 'ids': list(ids)}]
    d['decisions'] += [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ids for t, v in topics.items()]


def exported(folder, out):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        return run(folder, out)


@pytest.fixture(scope='module')
def faults_once(tmp_path_factory):
    """One real export of the synthetic survey's cubes, horizon and wells with SynF and SynF3D."""
    folder, out = made(tmp_path_factory.mktemp('definition'), edit=faulted), tmp_path_factory.mktemp('out')
    report, export = exported(folder, out)
    return folder, out, report, export


def staged(tmp_path, faults_once):
    folder, _, _, export = faults_once
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    return stage, json.loads((stage / 'export.json').read_text()), sa.definition(folder / 'definition.json')


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


@pytest.mark.parametrize('text', [
    SYNF_TEXT,
    '! a comment\n1 2 3 7 0\n1,2,4,7\n\n5 6 7 2 1\n5 6 8 2 2\n',
    '1 2 3 0\n',
    '1 2 3\n4 5 6 0\n',
    '1 2 x 0\n1 2 3 0\n',
    '1 2 3 0.5\n',
    '1 2 inf 0\n1 2 3 0\n',
    '# only a banner\n',
    '1 2 3 0\n1 2 4 0\n1 2 3 1\n',
])
def test_the_sdk_reads_fault_sticks_as_the_connectors_do(text):
    """F1: the same literal texts give the same sticks, or the same one sentence. Mutation: `#` lines not skipped (the
    exported file's banner refuses); a stick of one point taken."""
    try: expected = ('sticks', connector_faults.read(text))
    except connector_faults.FaultError as error: expected = ('refused', [str(error)])
    try: got = ('sticks', faults.read(text))
    except ValidationFailed as error: got = ('refused', list(error.violations))
    assert got == expected
    if text == SYNF_TEXT: assert got == ('sticks', sticks_of(SYNF))


def test_each_fault_is_exported_and_read_back_stick_by_stick(faults_once):
    """D-4: the report lists each fault under faults/, export.json states its form, axes and digest, and the SDK's
    reader gives the same axes and digest from the file. Mutations: the digest without the point counts; axes without
    points."""
    _, _, report, export = faults_once
    assert [(f['path'], f['kind'], f['object']) for f in report['files'] if f['kind'] == 'faults'] == [
        ('faults/SynF.dat', 'faults', 'SynF'), ('faults/SynF3D.dat', 'faults', 'SynF3D')]
    doc = json.loads((export / 'files/export.json').read_text())
    assert [f for f in doc['files'] if f['kind'] == 'faults'] == [
        {'path': 'faults/SynF.dat', 'kind': 'faults', 'object': 'SynF', 'form': 'stick set', 'axes': {'sticks': 3, 'points': 9}, 'digest': DIGEST['SynF']},
        {'path': 'faults/SynF3D.dat', 'kind': 'faults', 'object': 'SynF3D', 'form': '3D fault', 'axes': {'sticks': 3, 'points': 9}, 'digest': DIGEST['SynF3D']}]
    assert (export / 'files/faults/SynF.dat').read_text() == SYNF_TEXT
    for name in ('SynF', 'SynF3D'):
        f = {'path': 'faults/%s.dat' % name, 'kind': 'faults', 'object': name}
        assert sa.read_faults(export / 'files' / f['path'], f) == ({'sticks': 3, 'points': 9}, DIGEST[name])


def resticked(path, edit):
    sticks = faults.read(path.read_text())
    sticks = edit(sticks)
    return path.write_text(faults.BANNER + faults.write(sticks))


@pytest.mark.parametrize('case, reason', [
    ('dropped', 'faults/SynF3D.dat does not hold what export.json states: its axes are {"sticks": 3, "points": 8}, not {"points": 9, "sticks": 3}.'),
    ('swapped', 'faults/SynF3D.dat does not hold what export.json states: its values differ from those odbind gave (digest of the expected representation).'),
    ('digest', 'faults/SynF3D.dat does not hold what export.json states: its values differ from those odbind gave (digest of the expected representation).'),
    ('renumbered', 'faults/SynF3D.dat numbers its sticks other than 0 to 2 in order.'),
    ('spelling', 'faults/SynF3D.dat is not in the form the export writes (its first line, then x y z stick-index, each number in its shortest exact spelling).'),
    ('banner', 'faults/SynF3D.dat is not in the form the export writes (its first line, then x y z stick-index, each number in its shortest exact spelling).'),
])
def test_read_back_refuses_a_fault_that_is_not_what_the_export_states(tmp_path, faults_once, case, reason):
    """D-4, R2-9: a point dropped and two sticks swapped (each rewritten in the export's own spelling and numbering, so
    only the axes or the digest check can refuse), the digest in export.json changed, a well-formed file renumbered 1..n
    and `0.10400` for `0.104` (the geometry kept, so only the index or the canonical-bytes check can refuse), the banner
    dropped. `read_back` reads the stage: export.json holds no file hash, so nothing is resealed at this step; the
    build's own sha256 and bytes (inventory) are checked after it. Mutations: the index check removed (renumbered
    passes); the canonical check removed (spelling passes); the banner left out of the comparison."""
    stage, doc, defn = staged(tmp_path, faults_once)
    sa.read_back(stage, doc, defn)  # unchanged, it passes
    path = stage / 'faults/SynF3D.dat'
    text = path.read_text()
    if case == 'dropped': resticked(path, lambda s: [s[0], {**s[1], 'points': s[1]['points'][:2]}, s[2]])
    if case == 'swapped': resticked(path, lambda s: [{**s[0]}, {**s[2], 'index': 1}, {**s[1], 'index': 2}])
    if case == 'digest': next(f for f in doc['files'] if f['object'] == 'SynF3D')['digest'] = DIGEST['SynF']
    if case == 'renumbered': resticked(path, lambda s: [{**st, 'index': st['index'] + 1} for st in s])
    if case == 'spelling': path.write_text(text.replace(' 0.124 1\n', ' 0.12400 1\n', 1))
    if case == 'banner': path.write_text(text.replace(faults.BANNER, '', 1))
    if case == 'swapped': assert faults.read(path.read_text())[1]['points'][0] == {'x': 500150.0, 'y': 40.0, 'z': 0.1}
    assert refused(sa.read_back, stage, doc, defn) == reason + ' Nothing was sent.'


def test_faults_are_declared_and_agreed_in_time_and_seconds(faults_once):
    """D-5, R2-3: the declaration's z unit is the coordinate's (s), apart from the survey's zunit (ms); a definition
    that says ms or m for a fault refuses by name. Mutations: z_unit from the survey; the agreement skipped."""
    survey = {'crs': CRS, 'zdomain': 'twt', 'zunit': 'ms', 'xyunit': 'm'}
    assert starter.declarations(survey, {'seismic-3d', 'faults'})['faults'] == DECLARED
    defn = sa.definition(faults_once[0] / 'definition.json')
    assert sa.agreed(defn, {'survey': survey}) is None
    for unit in ('ms', 'm'):
        changed = {**defn, 'values': {**defn['values'], ('units', 'SynF'): unit}}
        assert refused(sa.agreed, changed, {'survey': survey}) == (
            "Decision units for SynF is %s; the survey says s. Nothing was sent." % unit)


def test_a_fault_lands_as_opendtect_faultsticks_stick_by_stick(tmp_path, project, monkeypatch):
    """D-4, D-5 (O1 coverage): the Connectors' intake detects each fault file by its first line, reads it with the
    declarations and holds its sticks index by index, point by point. Mutations: the banner dropped (the intake takes no
    profile); the declarations' z unit from the survey (ms)."""
    folder, out = made(tmp_path / 'definition', edit=faulted), tmp_path / 'export'
    exported(folder, out)
    build(folder, out, project)
    landing = json.loads((folder / 'pack/landing.json').read_text())
    for name, literal in (('SynF', SYNF), ('SynF3D', SYNF3D)):
        path = 'faults/%s.dat' % name
        assert (landing['inputs'][path]['profile'], landing['inputs'][path]['output']['kind']) == ('opendtect-faultsticks/1', 'faults')
        profile, declared, context = project.read[name + '.dat']
        assert (profile, declared) == ('opendtect-faultsticks/1', DECLARED)
        assert {k: context[k] for k in ('type', 'crs', 'z_meaning', 'z_unit', 'sticks', 'points')} == {
            'type': 'polyline-set', 'crs': CRS, 'z_meaning': 'time', 'z_unit': 's', 'sticks': 3, 'points': 9}
        asset = project.assets['item-%s-dat' % name]
        assert typed_reader.read_typed(profile, asset['raw'], declared)[1]['sticks'] == sticks_of(literal)


def python_too(d):
    d['targets'] = ['opendtect', 'python']


def features(export):
    return [(f['properties']['kind'], f['properties']['name']) for f in json.loads((export / 'files/outline.geojson').read_text())['features']]


@pytest.mark.parametrize('keep, outlined', [
    ((), None),
    (('wellbore-paths',), None),
    (('horizons',), None),
    (('seismic-3d',), [('survey-3d', 'Syn'), ('survey-3d', 'Syn2')]),
])
def test_faults_need_a_cube_or_a_line_for_the_python_target(tmp_path, project, keep, outlined):
    """D-6 (O6): faults add no outline feature and no Python reading. A pack with the Python target of faults alone,
    with a well or with a horizon refuses with the existing NO_CUBE sentence and writes no pack document; with a cube
    its outline is exactly the cube's (with a 2D line: the fifth combination, below). Mutation: a fault outlined (an
    extra feature); faults counted as the Python target's cube."""
    def edit(d):
        faulted(d, keep=keep)
        python_too(d)
    folder, out = made(tmp_path / 'definition', edit=edit), tmp_path / 'out'
    _, export = exported(folder, out)
    if outlined is None:
        assert refused(build, folder, out, project) == starter.NO_CUBE + starter.NOT_WRITTEN
        assert not (folder / 'pack/starter.json').exists()
    else:
        build(folder, out, project)
        assert features(export) == outlined


def test_faults_beside_a_2d_line_are_outlined_by_the_line_only(tmp_path, project):
    """D-6, the fifth combination: a 2D line gives the outline its one feature and the Python target its reading."""
    from test_starter_lines import lined

    def edit(d):
        faulted(d, keep=())
        lined(d, ('Syn2D/L1',))
        python_too(d)
    folder, out = made(tmp_path / 'definition', edit=edit), tmp_path / 'out'
    report, export = exported(folder, out)
    assert [(f['kind'], f['object']) for f in report['files']] == [('seismic-2d', 'Syn2D/L1'), ('faults', 'SynF'), ('faults', 'SynF3D')]
    build(folder, out, project)
    assert features(export) == [('survey-2d', 'Syn2D/L1')]


def test_an_opendtect_only_pack_of_faults_alone_has_an_empty_outline(tmp_path, project):
    """A-2 (measured in C3): without the Python target NO_CUBE does not apply, so faults alone build with no outline
    feature, as a pack of horizons alone already does on main. Pinned here so a change is seen, not decided."""
    folder, out = made(tmp_path / 'definition', edit=lambda d: faulted(d, keep=())), tmp_path / 'out'
    _, export = exported(folder, out)
    build(folder, out, project)
    assert features(export) == []
    assert (folder / 'pack/starter.json').exists()


def test_a_changed_fault_byte_refuses_naming_it(tmp_path, project):
    """Cov (recovery, O1): one byte of a fault file changed after the export; the build refuses by its path and lands
    nothing."""
    folder, export = made(tmp_path / 'definition', edit=faulted), tmp_path / 'export'
    exported(folder, export)
    p = current(export) / 'files/faults/SynF3D.dat'
    p.write_bytes(p.read_bytes().replace(b' 0.124 1', b' 0.125 1'))
    assert refused(build, folder, export, project) == (
        'faults/SynF3D.dat in the export at %s is not the file its report names: its SHA-256 differs.' % export + starter.NOT_WRITTEN)
    nothing_landed(folder, project)


def test_a_resume_after_a_fault_file_changed_refuses(tmp_path, project, monkeypatch):
    """Cov (recovery, O1): a build interrupted after SynF landed, then the export changed (SynF3D rewritten, its sha256
    and bytes resealed in the report); the resume refuses with the binding sentence and the landing record stays as it
    was. Mutation: the binding without the derived files' digests (the resume lands the changed file)."""
    folder, export = made(tmp_path / 'definition', edit=faulted), tmp_path / 'export'
    exported(folder, export)
    fired = failing(monkeypatch, landed_entry('faults/SynF.dat'))
    with pytest.raises(OSError): build(folder, export, project)
    assert fired
    monkeypatch.undo()
    rebound(project, monkeypatch)
    raw = (current(export) / 'files/faults/SynF3D.dat').read_bytes().replace(b' 0.124 1', b' 0.125 1')
    before = (folder / 'pack/landing.json').read_bytes()
    another(export, 'changed-1', replaced_file('faults/SynF3D.dat', raw))
    assert refused(build, folder, export, project) == starter.BINDING % 'The export' + starter.NOT_WRITTEN
    assert (folder / 'pack/landing.json').read_bytes() == before and 'SynF3D.dat' not in project.taken


assert [c['kind'] for c in CONTENTS] == ['seismic-3d', 'horizons', 'wellbore-paths', 'wellbore-logs']  # `faulted(keep=)` names these


# --- C5 (D-7, R2-1, R2-5): `ophiolite starter opendtect` on a pack with faults -----------------------------------------
#
# The fake survey's faults are the person's (PERSON in the fake's FAKE_ODBIND_STATE file, as OpendTect's GUI would leave
# them): none at first, then SynF and SynF3D imported as stick sets of the pack's coordinates.

STEP = ('Import files/faults/%s.dat in OpendTect (Survey > Import > FaultStickSets > ASCII 3D > Single 3D FaultStickSet, '
        'header 1 line, stick index in column 4, time in seconds) and name it “%s”; OpendTect cannot create a fault from '
        'Python.')
FAULT_LINES = ['fault files/faults/SynF.dat (item item-SynF-dat at r1) imported by you into OpendTect as “SynF”: 27 values, 0 differences '
               '(largest x 0 m, y 0 m, z 0 s)',
               'fault files/faults/SynF3D.dat (item item-SynF3D-dat at r1) imported by you into OpendTect as “SynF3D”: 27 values, 0 differences '
               '(largest x 0 m, y 0 m, z 0 s)']


def person(state, **sets):
    """The person's import in OpendTect: stick sets of these names and sticks ({x, y, z} lists per stick), no 3D fault."""
    stored = pickle.loads(state.read_bytes()) if state.exists() else {'cubes': {}, 'horizons': {}}
    stored['person'] = {'sticksets': {name: [dict(zip('xyz', zip(*stick))) for stick in sticks] for name, sticks in sets.items()}, 'faults3d': {}}
    state.write_bytes(pickle.dumps(stored))


def fault_rows(result):
    return [e for e in result['placed'] + result['compared'] if e['kind'] == 'faults']


def test_the_qualification_states_each_faults_step_then_records_it_placed_by_you(tmp_path, project, odbind):
    """O3: the step first (nothing compared, the oracle says it), then the person's import read back: `starter opendtect`
    itself keeps the import's `by you` and the comparison's keys in result.json and writes the fault lines of D-7 (c) into
    the oracle. Mutations: the compare row's `outcome` dropped; `_compared_line` without its fault branch (the generic
    line: "… 0 moved"); a moved point not failing the oracle."""
    folder, export = made(tmp_path / 'definition', edit=faulted), tmp_path / 'export'
    exported(folder, export)
    build(folder, export, project)
    survey = survey_at(tmp_path)
    person(odbind)
    doc, result = qualified(folder, survey, project)
    assert fault_rows(result) == []
    assert [n for n in result['not_placed'] if n['kind'] == 'faults'] == [
        {'kind': 'faults', 'object': name, 'file': 'faults/%s.dat' % name, 'reason': STEP % (name, name)} for name in ('SynF', 'SynF3D')]
    assert ['not placed: fault %s: ' % name + STEP % (name, name) for name in ('SynF', 'SynF3D')] == [
        line for line in doc['targets'][0]['oracle']['compared'] if line.startswith(('not placed: fault ', 'fault '))]
    person(odbind, SynF=SYNF, SynF3D=SYNF3D)
    doc, result = qualified(folder, survey, project)
    assert fault_rows(result) == [
        {'kind': 'faults', 'file': 'faults/%s.dat' % name, 'item': 'item-%s-dat' % name, 'version': 'r1', 'object': name, 'form': 'stick set', 'sticks': 3,
         'points': 9, 'values': 27, 'differences': 0, 'largest': {'x': 0.0, 'y': 0.0, 'z': 0.0}, 'moves': [], 'outcome': 'by you'} for name in ('SynF', 'SynF3D')]
    assert [e['kind'] for e in result['placed']][-2:] == ['faults', 'faults'] and result['differences'] == 0
    assert [n for n in result['not_placed'] if n['kind'] == 'faults'] == []
    oracle = doc['targets'][0]['oracle']
    assert [line for line in oracle['compared'] if line.startswith('fault ')] == FAULT_LINES and oracle['differences'] == 0
    assert json.loads((folder / 'pack/files' / RESULT).read_text()) == result
    moved = [[(x + 0.01, y, z) if (i, j) == (2, 1) else (x, y, z) for j, (x, y, z) in enumerate(st)] for i, st in enumerate(SYNF)]
    person(odbind, SynF=moved, SynF3D=SYNF3D)
    doc, result = qualified(folder, survey, project)
    assert [(e['object'], e['differences']) for e in result['compared'] if e['kind'] == 'faults'] == [('SynF', 1)] and result['differences'] == 1
    assert doc['targets'][0]['oracle']['compared'][0] == starter.FAILED % 1
    assert [n['reason'] for n in result['not_placed'] if n['kind'] == 'faults'] == [
        'The fault stick set “SynF” in the survey is not files/faults/SynF.dat: its stick 2 point 1 x is 500061.01, the file 500061.0.']


def placed_by_you(where, project, monkeypatch):
    """A pack with faults in WHERE whose faults the person has imported; its own fake state file."""
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(where / 'state.pickle'))
    folder, export = made(where / 'definition', edit=faulted), where / 'export'
    exported(folder, export)
    build(folder, export, project)
    person(where / 'state.pickle', SynF=SYNF, SynF3D=SYNF3D)
    return folder, survey_at(where)


def test_a_completed_rerun_with_faults_placed_by_you_changes_nothing(tmp_path, project, odbind, monkeypatch):
    """R2-1, R2-5: the saved result (fault rows with `moves: []`) is accepted by `_held_result` and the rerun gives the
    same bytes, untouched. Mutation: `moves` dropped from the connector's fault row (the rerun refuses: the saved result
    is not of its shape)."""
    folder, survey = placed_by_you(tmp_path, project, monkeypatch)
    _, result = qualified(folder, survey, project)
    assert [e['outcome'] for e in fault_rows(result)] == ['by you', 'by you']
    files = [folder / 'pack/starter.json', folder / 'pack/files' / RESULT]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
    qualified(folder, survey, project)
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in files] == before


def test_an_interrupted_qualification_with_faults_resumes_to_the_same_bytes(tmp_path, project, monkeypatch):
    """R2-1, R2-5 (`test_starter_archive_pack.py`'s interrupted qualification, with faults placed by you): stopped
    between result.json and starter.json, the resume reads the saved result (`_held_result`) and ends at an
    uninterrupted run's bytes. Mutation: `moves` dropped from the fault row (the resume refuses)."""
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    (tmp_path / 'whole').mkdir(); (tmp_path / 'cut').mkdir()
    folder, survey = placed_by_you(tmp_path / 'whole', project, monkeypatch)
    qualified(folder, survey, project)
    expected = pack_files(folder)
    project.__init__()
    folder, survey = placed_by_you(tmp_path / 'cut', project, monkeypatch)
    fired = failing(monkeypatch, lambda path, raw: path.name == 'starter.json')
    with pytest.raises(OSError): qualified(folder, survey, project)
    assert fired and (folder / 'pack/files' / RESULT).exists()
    monkeypatch.undo()
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(tmp_path / 'cut/state.pickle'))
    doc, result = qualified(folder, survey, project)
    assert pack_files(folder) == expected
    assert [line for line in doc['targets'][0]['oracle']['compared'] if line.startswith('fault ')] == FAULT_LINES
