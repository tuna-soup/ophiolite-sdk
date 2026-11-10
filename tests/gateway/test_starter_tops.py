"""E137 s4 C2 (strategy D-4 to D-6, R1-9, R2-8): a definition can hold well tops; their decisions must agree with what
OpendTect's marker depths are (along hole, metres, from the kelly bushing); the SDK reads each tops file back and lands it
as well-tops-csv/1. The exporter is the real one on the fake odbind, in its own process; every expected value is a
literal of the fake's synthetic markers (exception: D75): SYN-A SynTopA 812.5, SynTopB 1040.25, SynTopC 1303; SYN-B
SynTopA 64.75."""
import json
import os
import shutil

import pytest

pytest.importorskip('lasio')

from ophiolite import starter, starter_archive as sa  # noqa: E402
from ophiolite.errors import Refused  # noqa: E402

from test_starter_archive_pack import build, current, nothing_landed, project, typed_reader  # noqa: E402,F401 (fixture)
from test_starter_export import FAKE, CONNECTOR, made, run, tree  # noqa: E402

NOTHING = ' Nothing was sent.'
A_CSV, B_CSV = b'name,md\nSynTopA,812.5\nSynTopB,1040.25\nSynTopC,1303\n', b'name,md\nSynTopA,64.75\n'
DECLARED = {'depth_unit': 'm', 'depth_basis': 'same-as-log', 'depth_datum': 'KB'}
A_CONTEXT = {'type': 'well-tops', 'depth_unit': 'm', 'depth_basis': 'same-as-log', 'count': 3, 'tvd_provided': False,
             'md_range': [812.5, 1303.0], 'depth_datum': 'KB'}
HOW = ("odbind Well.marker_info of well %s, every marker's name and depth along hole in OpendTect's order, written as "
       "well-tops-csv/1 name,md; marker colours not carried")


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as e: fn(*args, **kw)
    return str(e.value)


def topped(d, wells=('SYN-A', 'SYN-B'), **decided):
    """Tops of WELLS; their depth reference KB (the paths' md reference) unless DECIDED says otherwise."""
    d['contents'] += [{'kind': 'tops', 'ids': list(wells)}]
    want = {'depth-reference': 'KB', **decided}
    for r in d['decisions']:
        if r['subject'] in ('SYN-A', 'SYN-B') and r['topic'] in want: r['value'] = want[r['topic']]


def pack(folder, **kw):
    return made(folder, edit=lambda d: topped(d, **kw))


def exported(folder, out):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        return run(folder, out)


@pytest.fixture(scope='module')
def tops_once(tmp_path_factory):
    folder, out = pack(tmp_path_factory.mktemp('definition')), tmp_path_factory.mktemp('out')
    report, export = exported(folder, out)
    return folder, out, report, export


def test_the_export_holds_each_wells_tops_and_says_where_they_came_from(tops_once):
    _, _, report, export = tops_once
    assert (export / 'files/wells/SYN-A-tops.csv').read_bytes() == A_CSV
    assert (export / 'files/wells/SYN-B-tops.csv').read_bytes() == B_CSV
    assert {d['path']: d['how'] for d in report['derived'] if d['path'].endswith('-tops.csv')} == {
        'wells/SYN-A-tops.csv': HOW % 'SYN-A', 'wells/SYN-B-tops.csv': HOW % 'SYN-B'}
    assert [f for f in report['files'] if f['kind'] == 'tops'] == [
        {'path': 'wells/SYN-A-tops.csv', 'kind': 'tops', 'object': 'SYN-A'}, {'path': 'wells/SYN-B-tops.csv', 'kind': 'tops', 'object': 'SYN-B'}]


def test_each_tops_file_lands_as_well_tops_csv_declared_as_the_paths(tmp_path, project):
    """D-5: the declaration projection and the whole landed context, literals. Mutation: depth_basis other."""
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'export'
    exported(folder, out)
    build(folder, out, project)
    profile, sent, landed = project.read['SYN-A-tops.csv']
    assert (profile, {k: sent[k] for k in DECLARED}) == ('well-tops-csv/1', DECLARED)
    assert landed == A_CONTEXT
    data = typed_reader.read_typed(profile, project.assets['item-SYN-A-tops-csv']['raw'], sent)[1]
    assert [(t['name'], t['md']) for t in data['tops']] == [('SynTopA', 812.5), ('SynTopB', 1040.25), ('SynTopC', 1303.0)]


def test_the_declarations_of_every_other_kind_are_unchanged():
    survey = {'crs': 'EPSG:32631', 'xyunit': 'm', 'zdomain': 'twt', 'zunit': 'ms', 'depth_unit': 'm'}
    got = starter.declarations(survey, {'seismic-3d'})
    assert got.pop('tops') == DECLARED
    assert got == {'seismic-3d': {'crs': 'EPSG:32631', 'z_domain': 'time'}, 'seismic-2d': {'crs': 'EPSG:32631', 'z_domain': 'time'},
                   'horizons': {'crs': 'EPSG:32631', 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 'ms', 'positive': 'down'},
                   'wellbore-paths': {'crs': 'EPSG:32631', 'xy_unit': 'm', 'depth_unit': 'm', 'tvdss_datum': 'MSL', 'md_reference': 'KB'},
                   'wellbore-logs': {},
                   'faults': {'crs': 'EPSG:32631', 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 's', 'positive': 'down', 'vertical_datum': 'unknown'}}


def test_tops_without_the_wells_path_are_refused_before_extraction(tmp_path):
    def edit(d):
        topped(d)
        d['contents'] = [c if c['kind'] != 'wellbore-paths' else {**c, 'ids': ['SYN-A']} for c in d['contents']]
    folder = made(tmp_path / 'definition', edit=edit)
    assert refused(exported, folder, tmp_path / 'out') == "The well tops of SYN-B need the well's path in the pack: list SYN-B under wellbore-paths too." + NOTHING
    assert not (tmp_path / 'out/derived.json').exists()


@pytest.mark.parametrize('decided, sentence', [
    ({'depth-reference': 'SRD'}, 'Decision depth-reference for SYN-A is SRD; the survey says KB.'),
    ({'depth-kind': 'TVDSS'}, 'Decision depth-kind for SYN-A is TVDSS; the survey says MD.'),
    ({'units': 'ft'}, 'Decision units for SYN-A is ft; the survey says m.'),
], ids=['depth-reference', 'depth-kind', 'units'])
def test_a_decision_that_disagrees_with_opendtects_marker_depths_is_refused(tmp_path, decided, sentence):
    """D-4. Mutation: the tops branch of `agreed` removed (SRD and TVDSS land)."""
    out = tmp_path / 'out'
    assert refused(exported, pack(tmp_path / 'definition', **decided), out) == sentence + NOTHING
    assert not (out / 'derived.json').exists()


def staged(tmp_path, export):
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    return stage, json.loads((stage / 'export.json').read_text())


def test_a_tops_file_whose_depth_changed_is_refused_by_its_digest_on_read_back(tmp_path, tops_once):
    """R1-9: read_back called directly, export.json's digest and count unchanged, one md changed. Mutation: read_tops
    returning the stated digest."""
    folder, _, _, export = tops_once
    stage, doc = staged(tmp_path, export)
    p = stage / 'wells/SYN-A-tops.csv'
    p.write_bytes(p.read_bytes().replace(b'SynTopB,1040.25', b'SynTopB,1040.5'))
    assert refused(sa.read_back, stage, doc, sa.definition(folder / 'definition.json')) == (
        'wells/SYN-A-tops.csv does not hold what export.json states: its values differ from those odbind gave (digest of the '
        'expected representation).' + NOTHING)


def test_a_tops_file_of_another_count_is_refused_on_read_back(tmp_path, tops_once):
    """R2-8: one row dropped; export.json still says three."""
    folder, _, _, export = tops_once
    stage, doc = staged(tmp_path, export)
    p = stage / 'wells/SYN-A-tops.csv'
    p.write_bytes(p.read_bytes().replace(b'SynTopC,1303\n', b''))
    assert refused(sa.read_back, stage, doc, sa.definition(folder / 'definition.json')) == (
        'wells/SYN-A-tops.csv does not hold what export.json states: its axes are {"count": 2}, not {"count": 3}.' + NOTHING)


@pytest.mark.parametrize('raw, sentence', [
    (b'name,depth\nSynTopA,812.5\n', 'wells/X-tops.csv does not start name,md or does not end with a line end.'),
    (b'name,md\nSynTopA,812.5', 'wells/X-tops.csv does not start name,md or does not end with a line end.'),
    (b'name,md\nSynTopA,812.5,1\n', "wells/X-tops.csv has a row not of the form name,md with a finite depth: 'SynTopA,812.5,1'."),
    (b'name,md\nSynTopA,nan\n', "wells/X-tops.csv has a row not of the form name,md with a finite depth: 'SynTopA,nan'."),
    (b'name,md\nSynTopA,1e400\n', "wells/X-tops.csv has a row not of the form name,md with a finite depth: 'SynTopA,1e400'."),
    (b'name,md\n,812.5\n', "wells/X-tops.csv has a row not of the form name,md with a finite depth: ',812.5'."),
], ids=['header', 'no-line-end', 'three-cells', 'nan', 'overflow', 'no-name'])
def test_read_tops_refuses_a_file_not_of_its_form(tmp_path, raw, sentence):
    """R2-8: each refusal by its literal sentence."""
    (tmp_path / 'x.csv').write_bytes(raw)
    assert refused(sa.read_tops, tmp_path / 'x.csv', {'path': 'wells/X-tops.csv', 'kind': 'tops', 'object': 'X'}) == sentence + NOTHING


def test_a_refused_export_keeps_the_previous_export(tmp_path):
    out = tmp_path / 'out'
    exported(pack(tmp_path / 'good'), out)
    before = (out / 'derived.json').read_bytes()
    assert refused(exported, pack(tmp_path / 'bad', **{'depth-reference': 'SRD'}), out) == 'Decision depth-reference for SYN-A is SRD; the survey says KB.' + NOTHING
    assert (out / 'derived.json').read_bytes() == before


def test_an_export_interrupted_while_reading_tops_back_resumes_to_the_same_bytes(tmp_path, monkeypatch, tops_once):
    """Acceptance 8: interrupted inside the read-back of the second tops file; the rerun equals an uninterrupted export."""
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'out'
    calls, real = [], sa.read_tops
    def interrupted(path, f):
        calls.append(1)
        if len(calls) == 2: raise OSError('interrupted')
        return real(path, f)
    monkeypatch.setitem(sa.READERS, 'tops', interrupted)
    with pytest.raises(OSError): exported(folder, out)
    monkeypatch.undo()
    assert not (out / 'derived.json').exists()
    report, export = exported(folder, out)
    assert {k: v for k, v in report.items() if k != 'definition'} == {k: v for k, v in tops_once[2].items() if k != 'definition'}
    assert tree(export / 'files') == tree(tops_once[3] / 'files')


def test_a_changed_tops_byte_refuses_the_build_naming_it(tmp_path, project):
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'export'
    exported(folder, out)
    p = current(out) / 'files/wells/SYN-B-tops.csv'
    p.write_bytes(p.read_bytes().replace(b'64.75', b'64.5'))
    assert refused(build, folder, out, project) == (
        'wells/SYN-B-tops.csv in the export at %s is not the file its report names: its SHA-256 differs.' % out + starter.NOT_WRITTEN)
    nothing_landed(folder, project)


# --- C3: the OpenDTect qualification end to end, the Python and ResInsight targets (D-7, D-7a, D-9, R2-1, R2-2, R2-7) ---

import pickle  # noqa: E402
import sys  # noqa: E402

from test_starter_archive_pack import RESULT, derive, odbind, pack_files, qualified, survey_at  # noqa: E402,F401 (fixture)
from test_starter_build import failing  # noqa: E402
from test_starter_python import PYTHON, ROTATED_ORACLE, built, files, notebook, ran, targets  # noqa: E402,F401 (fixture)
from test_starter_resinsight import ORACLE, connectors, imported, written  # noqa: E402,F401 (fixture)

TOPS = ['wells/SYN-A-tops.csv', 'wells/SYN-B-tops.csv']
STEP = ('Import files/wells/%s-tops.csv in OpendTect as the markers of the well “%s”: Survey > Manage > Wells, select the '
        'well, Edit Markers, Import ...; File header Fixed size, 1 line; Define ...: Field separator Comma, Depth col:2 MD, '
        'Unit m (Meter), Marker name col:1; OK; Existing markers Replace; Import, then OK. OpendTect cannot create a marker '
        'from Python.')
TOPS_PLACED = ['well tops files/wells/SYN-A-tops.csv (item item-SYN-A-tops-csv at r1) imported by you into OpendTect as “SYN-A”: '
               '3 tops, 0 differences (0 missing, 0 extra)',
               'well tops files/wells/SYN-B-tops.csv (item item-SYN-B-tops-csv at r1) imported by you into OpendTect as “SYN-B”: '
               '1 tops, 0 differences (0 missing, 0 extra)']
MARKERS = {'SYN-A': [('SynTopC', 1303), ('SynTopA', 812.5), ('SynTopB', 1040.25)], 'SYN-B': [('SynTopA', 64.75)]}  # another order


def person(state, markers):
    """The person's import in OpendTect: each well's markers (name, dah); the fake keeps them in its state file."""
    stored = pickle.loads(state.read_bytes()) if state.exists() else {'cubes': {}, 'horizons': {}}
    stored['person'] = {'markers': {w: [{'name': n, 'color': '#123456', 'dah': d} for n, d in ms] for w, ms in markers.items()}}
    state.write_bytes(pickle.dumps(stored))


def stepped(lines):
    """The oracle's lines of the tops' steps, each step a `starter.bounded` run of lines (one long sentence is split)."""
    out, inside = [], False
    for line in lines:
        inside = line.startswith('not placed: well tops of ') or (inside and line.startswith(starter.MORE))
        if inside: out.append(line)
    return out


def tops_rows(result):
    return [e for e in result['placed'] + result['compared'] if e['kind'] == 'tops']


def row(well, n, item, **counts):
    c = {'missing': 0, 'extra': 0, **counts}
    return {'kind': 'tops', 'file': 'wells/%s-tops.csv' % well, 'item': item, 'version': 'r1', 'object': well, 'values': n,
            'differences': c['missing'] + c['extra'], 'missing': c['missing'], 'extra': c['extra'], 'moves': [], 'outcome': 'by you'}


def test_the_qualification_states_the_tops_step_then_records_them_placed_by_you_and_finalises(tmp_path, project, odbind):
    """R2-2: export -> build -> `starter opendtect` on a destination without markers (the step, nothing compared, the
    oracle says it) -> the person's import (markers written into the fake) -> `starter opendtect` again (placed by you,
    the comparison rows, the oracle's tops lines) -> `starter finalise`. Mutations: tops left out of `--compare` (the
    second run refuses NOT_READ_BACK); `_compared_line` without its tops branch (the generic "moved" line); an extra
    marker not failing the oracle."""
    folder, export = pack(tmp_path / 'definition'), tmp_path / 'export'
    exported(folder, export)
    build(folder, export, project)
    survey = survey_at(tmp_path)
    person(odbind, {})
    doc, result = qualified(folder, survey, project)
    assert tops_rows(result) == []
    assert [n for n in result['not_placed'] if n['kind'] == 'tops'] == [
        {'kind': 'tops', 'object': w, 'file': 'wells/%s-tops.csv' % w, 'reason': STEP % (w, w)} for w in ('SYN-A', 'SYN-B')]
    assert stepped(doc['targets'][0]['oracle']['compared']) == [
        line for w in ('SYN-A', 'SYN-B') for line in starter.bounded('not placed: well tops of %s: ' % w + STEP % (w, w))]
    person(odbind, MARKERS)
    doc, result = qualified(folder, survey, project)
    assert tops_rows(result) == [row('SYN-A', 3, 'item-SYN-A-tops-csv'), row('SYN-B', 1, 'item-SYN-B-tops-csv')]
    assert [e['kind'] for e in result['placed']][-2:] == ['tops', 'tops'] and result['differences'] == 0
    assert [n for n in result['not_placed'] if n['kind'] == 'tops'] == []
    oracle = doc['targets'][0]['oracle']
    assert [line for line in oracle['compared'] if line.startswith('well tops ')] == TOPS_PLACED and oracle['differences'] == 0
    assert json.loads((folder / 'pack/files' / RESULT).read_text()) == result
    derive(folder)
    final = starter.finalise(folder / 'pack', folder / 'custody')
    assert final['targets'][0]['oracle'] == oracle
    person(odbind, {**MARKERS, 'SYN-A': MARKERS['SYN-A'] + [('SynTopD', 1500.0)]})
    doc, result = qualified(folder, survey, project)
    assert [(e['object'], e['differences'], e['extra']) for e in tops_rows(result)] == [('SYN-B', 0, 0), ('SYN-A', 1, 1)]  # placed, then compared
    assert result['differences'] == 1 and doc['targets'][0]['oracle']['compared'][0] == starter.FAILED % 1
    assert [n['reason'] for n in result['not_placed'] if n['kind'] == 'tops'] == [
        STEP % ('SYN-A', 'SYN-A') + " The well holds 4 markers; 0 of the pack's 3 tops are not among them and 1 of its markers are not the pack's."]


def placed_by_you(where, project, monkeypatch):
    """A pack with tops in WHERE whose tops the person has imported; its own fake state file."""
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(where / 'state.pickle'))
    folder, export = pack(where / 'definition'), where / 'export'
    exported(folder, export)
    build(folder, export, project)
    person(where / 'state.pickle', MARKERS)
    return folder, survey_at(where)


def test_a_completed_rerun_with_tops_placed_by_you_changes_nothing(tmp_path, project, odbind, monkeypatch):
    """R2-2: the saved result (tops rows with `moves: []`) is accepted by `_held_result`; the rerun leaves every byte and
    mtime. Mutation: `moves` dropped from the connector's tops row (the rerun refuses: the saved result is not of its shape)."""
    folder, survey = placed_by_you(tmp_path, project, monkeypatch)
    _, result = qualified(folder, survey, project)
    assert [e['outcome'] for e in tops_rows(result)] == ['by you', 'by you']
    kept = [folder / 'pack/starter.json', folder / 'pack/files' / RESULT]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in kept]
    qualified(folder, survey, project)
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in kept] == before


def test_an_interrupted_qualification_with_tops_resumes_to_the_same_bytes(tmp_path, project, monkeypatch):
    """R2-2 (`test_starter_archive_pack.py`'s interrupted qualification, with tops placed by you): stopped between
    result.json and starter.json, the resume reads the saved result and ends at an uninterrupted run's bytes."""
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
    doc, _ = qualified(folder, survey, project)
    assert pack_files(folder) == expected
    assert [line for line in doc['targets'][0]['oracle']['compared'] if line.startswith('well tops ')] == TOPS_PLACED


TOPS_EXPECTED = [{'well': 'SYN-A', 'path': TOPS[0], 'tops': [['SynTopA', 812.5], ['SynTopB', 1040.25], ['SynTopC', 1303.0]]},
                 {'well': 'SYN-B', 'path': TOPS[1], 'tops': [['SynTopA', 64.75]]}]
TOPS_SAID = ['Tops SYN-A: 3 tops checked', 'Tops SYN-B: 1 tops checked']
RI_TOPS_SAID = 'Well tops: not placed; this starter does not import well tops into ResInsight'
RI_TOPS = "\nThis starter does not import well tops into ResInsight; the pack's well tops are not imported.\n"


def three(d):
    topped(d); d['targets'] = ['opendtect', 'python', 'resinsight']


@pytest.fixture(scope='module')
def targeted(tmp_path_factory):
    """{'cube': (definition folder, export OUT)}: the rotated survey with SYN-A's and SYN-B's tops, all three targets."""
    folder, export = made(tmp_path_factory.mktemp('definition-three'), edit=three), tmp_path_factory.mktemp('export-three')
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.setenv('FAKE_ODBIND_VARIANT', 'rotated')
        run(folder, export)
    return {'cube': (folder, export)}


def test_the_notebook_checks_every_top_and_says_so_after_the_run_and_a_rerun(targeted, tmp_path, project, notebook):
    """D-9: expected.json gains `tops` last, the tops files join the Python target's reads, the waiting oracle is the
    pack's without tops; the notebook passes, its result names each well's top count and the oracle says each well's
    tops checked, two values per top and one per well, also after a rerun (bytes unchanged). Mutations: the tops paths
    not in the target's reads; the oracle lines left out."""
    folder = built(targeted, tmp_path, project, 'cube')
    python = targets(folder)['python']
    assert python['oracle'] == starter.ORACLE_PYTHON
    assert [a['path'] for a in python['artefacts']] == PYTHON[:4] + [TOPS[0]] + PYTHON[4:] + [TOPS[1]]  # the derived order: a well's tops after its path
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert list(expected)[-1] == 'tops' and expected['tops'] == TOPS_EXPECTED and expected['schema'] == 'ophiolite.starter-python-expected/1'
    doc, result = ran(folder)
    assert result['differences'] == [] and result['tops'] == [{'well': 'SYN-A', 'path': TOPS[0], 'tops': 3}, {'well': 'SYN-B', 'path': TOPS[1], 'tops': 1}]
    assert targets(folder)['python']['oracle'] == {'compared': ROTATED_ORACLE + TOPS_SAID, 'values': 11 + 7 + 3, 'differences': 0, 'seed': 0}
    kept = files(folder)
    ran(folder)
    assert files(folder) == kept


@pytest.mark.parametrize('change, said', [
    (lambda t: t.replace(b'SynTopB,1040.25', b'SynTopB,1040.5'), ['top 2 (SynTopB) of SYN-A']),
    (lambda t: t.replace(b'SynTopB,1040.25', b'SynTopX,1040.25'), ['top 2 (SynTopB) of SYN-A']),
    (lambda t: t[:t.rindex(b'SynTopC,1303\n')], ['the number of tops of SYN-A']),
], ids=['changed-md', 'changed-name', 'removed-top'])
def test_the_notebook_names_a_top_that_differs_from_expected(targeted, tmp_path, project, change, said):
    """D-9: the notebook run directly on the pack with SYN-A's tops file changed after the build while expected.json
    keeps the original tops: the specific top, or the count, is named and the notebook fails. Mutation: the notebook
    comparing names only (the changed md passes)."""
    from test_pack_notebook import notebook as run_notebook
    folder = built(targeted, tmp_path / 'built', project, 'cube')
    p = folder / 'pack/files' / TOPS[0]
    p.write_bytes(change(p.read_bytes()))
    done, result = run_notebook(tmp_path, pack=folder / 'pack')
    assert done.returncode != 0 and result['differences'] == said


def test_resinsight_states_the_tops_not_placed_before_after_and_on_a_rerun(targeted, tmp_path, project, connectors):
    """D-9: TOPS_LINE after the cube's line in the waiting oracle, after a passing comparison and after a rerun (bytes
    unchanged); the launcher says it; the tops are not the target's artefacts. Mutation: TOPS_LINE only in the waiting
    oracle (the comparison's oracle loses it)."""
    from test_starter_python import RESINSIGHT
    folder = built(targeted, tmp_path, project, 'cube')
    ri = targets(folder)['resinsight']
    assert ri['oracle'] == {**starter.ORACLE_RESINSIGHT, 'compared': [starter.ORACLE_RESINSIGHT['compared'][0], RI_TOPS_SAID, *starter.ORACLE_RESINSIGHT['compared'][1:]]}
    assert RI_TOPS in (folder / 'pack/files' / starter.RI_IMPORT).read_text()
    assert [a['path'] for a in ri['artefacts']] == RESINSIGHT
    imported(folder, connectors)
    assert targets(folder)['resinsight']['oracle'] == {**ORACLE, 'compared': [ORACLE['compared'][0], RI_TOPS_SAID, *ORACLE['compared'][1:]]}
    kept = written(folder)
    imported(folder, connectors)
    assert written(folder) == kept


def test_a_pack_of_tops_and_paths_only_is_refused_by_the_python_target(tmp_path, project):
    """R2-7: the Python target still reads a cube or a 2D line; such a pack is refused at the build with NO_CUBE."""
    def edit(d):
        topped(d)
        keep = {'wellbore-paths', 'tops'}
        dropped = {x for c in d['contents'] if c['kind'] not in keep for x in c['ids']} - {x for c in d['contents'] if c['kind'] in keep for x in c['ids']}
        d['contents'] = [c for c in d['contents'] if c['kind'] in keep]
        d['decisions'] = [r for r in d['decisions'] if r['subject'] not in dropped]
        d['targets'] = ['opendtect', 'python']
    folder, out = made(tmp_path / 'definition', edit=edit), tmp_path / 'export'
    exported(folder, out)
    assert refused(build, folder, out, project) == starter.NO_CUBE + starter.NOT_WRITTEN
    nothing_landed(folder, project)


def test_a_pack_without_tops_keeps_its_expected_values_oracles_and_launcher(project):
    """R1-5: no `tops` key, no tops statement in either oracle or the launcher, and a result without `tops` is accepted."""
    assert starter.resinsight_waiting(False, False, False, starter.holds_tops({'derived': [{'path': 'wells/SYN-A-positions.csv'},
                                                                                            {'path': 'wells/SYN-A.las'}]})) == starter.ORACLE_RESINSIGHT
    assert RI_TOPS.strip().encode() not in starter.resinsight_import({'id': 'x'}, {})
    assert starter.holds_tops({'derived': [{'path': 'wells/SYN-A-tops.csv'}]})
    assert starter.said_not_placed(False, False, False) == []
