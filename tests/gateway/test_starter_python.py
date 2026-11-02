"""E129 (e) C3 (strategy rev 3, D4, D5; acceptance A1, A2 a, A4, R2-8): an archive pack with the Python target, built
from the real export of the rotated survey, its notebook run by `ophiolite starter python`.

The export is sb's (`ophiolite_opendtect.export` on the fake odbind, in its own process) of the survey variant
`rotated`: the default survey's lines and samples on a grid turned so that x = 500000.375 + 20 (crl - 20) - 15 (inl -
10) and y = 0.125 + 15 (crl - 20) + 20 (inl - 10). The export writes CDP X and Y in hundredths with scalar -100, so the
trace headers hold x - 0.005 and y + 0.005 rounded half to even: the grid's origin is (500000.38, 0.12) and every trace
is on the plane through it. Every expected value is counted by hand from those formulas:

- inline 12, the floor middle of 10-16 step 2; crosslines 20, 22 and 26 (first, floor middle, last of four) at sample
  index 2 of 5: i + c/4 + k/16 = 17.125, 17.625 and 18.625; the inline's sum 4 x 60.625 + 1.25 x 92 = 357.5;
- SYN-A's first station (500010.125, 10.375) is (9.745, 10.255) from the origin: (9.745 x 20 + 10.255 x 15) / 625 =
  0.558 crossline steps of one line and (-9.745 x 15 + 10.255 x 20) / 625 = 0.094 inline steps, so crossline 20.56 and
  inline 10.09; SYN-B's (500075.0, 50.0) is (74.62, 49.88) away: crossline 23.58, inline 9.81. A projection reading x
  for the crossline and y for the inline (the unrotated survey's) would put SYN-A at crossline 20.39, inline 10.41.

A1 runs `ophiolite starter python` of the installed wheel (OPHIOLITE_TEST_WHEEL_PYTHON, its `pack` extra installed;
required with OPHIOLITE_REQUIRE_WHEEL=1) from a folder outside the checkout. The other runs call `starter.python` here
with the notebook run by that interpreter when it is named (the job's own Python need not have matplotlib)."""
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from ophiolite import starter
from test_starter_build import failing
from test_starter_archive_pack import (another, build, client, depth, derive, project, refused, survey_at, ARTEFACTS, RESULT)  # noqa: F401 (project: a fixture)
from test_starter_export import CONNECTOR, FAKE, PACK, made, run, sha

WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
PLAIN = sys.executable  # the connector's interpreter for the import: this one, the fake odbind and the connector on its path
SDK =Path(__file__).resolve().parents[2]
BOTH = ['opendtect', 'python']
READS = ['seismic/Syn.sgy', 'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
PYTHON = [starter.PY_IMPORT, starter.PY_EXPECTED] + READS  # the Python target's artefacts as built
SAMPLES = [{'crossline': 20, 'index': 2, 'value': 17.125}, {'crossline': 22, 'index': 2, 'value': 17.625}, {'crossline': 26, 'index': 2, 'value': 18.625}]
WELLS = [{'name': 'SYN-A', 'inline': 10.09, 'crossline': 20.56}, {'name': 'SYN-B', 'inline': 9.81, 'crossline': 23.58}]


def both(d):
    d['targets'] = list(BOTH)


def depth_both(d):
    depth(d); both(d)


def listing(*targets):
    """E129 (d): a definition edit naming TARGETS."""
    return lambda d: d.update(targets=list(targets))


@pytest.fixture(scope='module')
def rotated(tmp_path_factory):
    """{survey: (definition folder, export OUT)}: the rotated time survey and the depth survey, each exported for a
    definition listing both targets; E129 (d): the rotated survey again for a definition listing OpendTect and ResInsight
    (`resinsight`) and one listing all three (`three`), since an export is bound to its definition's bytes."""
    out = {}
    for survey, edit, variant in (('rotated', both, 'rotated'), ('depth', depth_both, 'depth'), ('resinsight', listing('opendtect', 'resinsight'), 'rotated'),
                                  ('three', listing('opendtect', 'python', 'resinsight'), 'rotated')):
        folder, export = made(tmp_path_factory.mktemp('definition-' + survey), edit=edit), tmp_path_factory.mktemp('export-' + survey)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
            mp.setenv('FAKE_ODBIND_VARIANT', variant)
            run(folder, export)
        out[survey] = folder, export
    return out


@pytest.fixture
def rotated_odbind(tmp_path, monkeypatch):
    """The fake odbind of the rotated survey and the connector on the import's path."""
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR), *([os.environ['PYTHONPATH']] if os.environ.get('PYTHONPATH') else [])]))
    monkeypatch.setenv('FAKE_ODBIND_VARIANT', 'rotated')
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(tmp_path / 'odbind-state.pickle'))
    return tmp_path / 'odbind-state.pickle'


@pytest.fixture
def notebook(monkeypatch):
    """starter.python runs the notebook with sys.executable: the installed wheel's interpreter when it is named."""
    if WHEEL: monkeypatch.setattr(sys, 'executable', WHEEL)
    else: pytest.importorskip('matplotlib'); pytest.importorskip('segyio')


def copied(rotated, survey, where):
    folder, export = rotated[survey]
    shutil.copytree(folder, where / 'definition'); shutil.copytree(export, where / 'export')
    return where / 'definition', where / 'export'


def built(rotated, where, project, survey='rotated'):
    folder, export = copied(rotated, survey, where)
    build(folder, export, project)
    return folder


def ran(folder):
    return starter.python(folder / 'pack')


def files(folder):
    return {p: (folder / 'pack' / p).read_bytes() for p in ('starter.json', 'files/' + starter.PY_RESULT) if (folder / 'pack' / p).exists()}


def targets(folder):
    return {t['application']: t for t in json.loads((folder / 'pack/starter.json').read_text())['targets']}


# --- the build: D1's expected values, D4's targets ---------------------------------------------------------------------

def test_build_adds_the_python_target_with_the_notebook_its_expected_values_and_the_files_it_reads(rotated, tmp_path, project):
    folder = built(rotated, tmp_path, project)
    doc = json.loads((folder / 'pack/starter.json').read_text())
    opendtect, python = doc['targets']
    assert opendtect['application'] == 'opendtect' and [a['path'] for a in opendtect['artefacts']] == ARTEFACTS and opendtect['oracle'] == starter.ORACLE_OPENDTECT
    assert (python['application'], python['import'], python['oracle']) == ('python', starter.PY_IMPORT, starter.ORACLE_PYTHON)
    assert [a['path'] for a in python['artefacts']] == PYTHON
    shared = {a['path']: a for a in opendtect['artefacts']}
    assert all(a == shared[a['path']] for a in python['artefacts'] if a['path'] in READS)  # one artefact, listed by both
    notebook = (folder / 'pack/files' / starter.PY_IMPORT).read_bytes()
    assert notebook == (SDK / 'ophiolite/templates/starter-pack/open-a-starter-pack.ipynb').read_bytes()
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert expected == {'schema': 'ophiolite.starter-python-expected/1', 'cube': 'seismic/Syn.sgy', 'inline': 12, 'crosslines': [20, 26, 2], 'z': [100, 4000, 5],
                        'samples': SAMPLES, 'inline_sum': 357.5,
                        'wells': [{'name': 'SYN-A', 'positions': 'wells/SYN-A-positions.csv', 'x': 500010.125, 'y': 10.375, 'inline': 10.09, 'crossline': 20.56,
                                   'las': 'wells/SYN-A.las', 'curves': 2, 'depth': [100.0, 100.9]},
                                  {'name': 'SYN-B', 'positions': 'wells/SYN-B-positions.csv', 'x': 500075.0, 'y': 50.0, 'inline': 9.81, 'crossline': 23.58,
                                   'las': None, 'curves': None, 'depth': None}]}
    starter.shaped(doc)


def test_the_python_target_on_an_export_without_a_cube_is_refused_by_build(rotated, tmp_path, project):
    folder, export = copied(rotated, 'depth', tmp_path)
    assert refused(build, folder, export, project) == starter.NO_CUBE + starter.NOT_WRITTEN
    assert project.read == {} and not (folder / 'pack/starter.json').exists()


def collinear(target, report):
    """The cube's trace headers moved onto one line (x = 500000 + 3 n, y = 4 n, n the trace's number), in hundredths."""
    path = target / 'files/seismic/Syn.sgy'
    raw = bytearray(path.read_bytes())
    count = struct.unpack_from('>H', raw, 3220)[0]
    for n, at in enumerate(range(3600, len(raw), 240 + 4 * count)):
        struct.pack_into('>ii', raw, at + 180, 50000000 + 300 * n, 400 * n)
    path.write_bytes(bytes(raw))
    d = next(d for d in report['derived'] if d['path'] == 'seismic/Syn.sgy')
    d.update(sha256=sha(bytes(raw)), bytes=len(raw))


def test_trace_headers_spanning_no_area_are_refused_by_build(rotated, tmp_path, project):
    folder, export = copied(rotated, 'rotated', tmp_path)
    another(export, 'collinear', collinear)
    assert refused(build, folder, export, project) == starter.FLAT + starter.NOT_WRITTEN
    assert project.read == {} and not (folder / 'pack/starter.json').exists()


# --- A1: the installed wheel's ophiolite starter python, from a folder outside the checkout ----------------------------

def test_starter_python_of_the_installed_wheel_runs_the_notebook_on_the_rotated_pack(rotated, tmp_path, project):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    folder = built(rotated, tmp_path / 'built', project)
    before = targets(folder)['opendtect']
    (tmp_path / 'outside').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_') and k != 'PYTHONPATH'}
    done = subprocess.run([WHEEL, '-c', 'import sys; from ophiolite.cli import entrypoint; sys.argv[0] = "ophiolite"; entrypoint()', 'starter', 'python',
                           str(folder / 'pack'), '--keep', str(tmp_path / 'outside/kept'), '--json'],
                          cwd=tmp_path / 'outside', env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr
    where = subprocess.run([WHEEL, '-c', 'import ophiolite; print(ophiolite.__file__)'], cwd=tmp_path / 'outside', env=env, capture_output=True, text=True).stdout.strip()
    assert 'site-packages' in where and not where.startswith(str(SDK))  # the installed wheel, not this checkout
    result = json.loads((folder / 'pack/files' / starter.PY_RESULT).read_text())
    assert (result['inline'], result['samples'], result['inline_sum'], result['without_logs'], result['differences']) == (12, SAMPLES, 357.5, ['SYN-B'], [])
    assert [{k: w[k] for k in ('name', 'inline', 'crossline')} for w in result['wells']] == WELLS
    assert [(w['curves'], w['depth']) for w in result['wells']] == [(2, [100.0, 100.9]), (None, None)]
    plotted = result['plotted']  # read back from the figure (R2-6)
    assert (plotted['xlim'], plotted['ylim']) == ([20.0, 26.0], [116.0, 100.0])
    assert plotted['image'] == {'shape': [5, 4], 'values': [17.125, 17.625, 18.625], 'extent': [20.0, 26.0, 116.0, 100.0], 'origin': 'upper'}
    assert plotted['wells'] == pytest.approx({'SYN-A': 20.558, 'SYN-B': 23.585}, abs=0.001)
    assert (tmp_path / 'outside/kept/open-a-starter-pack.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    after = targets(folder)
    assert after['opendtect'] == before  # never touched
    raw = (folder / 'pack/files' / starter.PY_RESULT).read_bytes()
    assert raw == starter.dumped(result) and [a['path'] for a in after['python']['artefacts']] == PYTHON + [starter.PY_RESULT]
    assert after['python']['artefacts'][-1] == {'path': starter.PY_RESULT, 'sha256': sha(raw), 'bytes': len(raw)}
    assert after['python']['oracle'] == {'compared': [
        'inline 12: 3 samples and the inline sum read with segyio',
        'well SYN-A: projected to inline 10.09, crossline 20.56; 2 curves from 100.0 to 100.9 read with lasio',
        'well SYN-B: projected to inline 9.81, crossline 23.58; positions only',
        'plotted: the inline image and 2 well lines, read back from the figure'], 'values': 11, 'differences': 0, 'seed': 0}  # 3 samples, the sum, 2 x 2 projections, SYN-A's curves and depth range
    assert json.loads(done.stdout)['oracle'] == after['python']['oracle']


# --- A2 (a): a changed pack file is refused before the notebook runs -----------------------------------------------------

def sampled_byte(folder):
    """One byte of the sampled trace (inline 12, crossline 22: the sixth trace) changed."""
    path = folder / 'pack/files/seismic/Syn.sgy'
    raw = bytearray(path.read_bytes())
    count = struct.unpack_from('>H', raw, 3220)[0]
    raw[3600 + 5 * (240 + 4 * count) + 240 + 4 * 2] ^= 1
    path.write_bytes(bytes(raw))
    return 'seismic/Syn.sgy'


def first_row(folder):
    path = folder / 'pack/files/wells/SYN-A-positions.csv'
    lines = path.read_text().splitlines(keepends=True)
    lines[1] = lines[1].replace('500010.125', '500035.125', 1)
    path.write_text(''.join(lines))
    return 'wells/SYN-A-positions.csv'


@pytest.mark.parametrize('change', [sampled_byte, first_row], ids=['sampled-trace', 'first-station'])
def test_a_changed_file_is_refused_naming_it_before_the_notebook_runs(rotated, tmp_path, project, monkeypatch, change):
    folder = built(rotated, tmp_path, project)
    before = files(folder)
    monkeypatch.setattr(starter, '_notebook', lambda *a, **k: pytest.fail('the notebook ran'))
    path = change(folder)
    assert refused(ran, folder) == 'artefact %s: the file in files/ is not the one starter.json names.' % path + starter.UNCHANGED
    assert files(folder) == before


# --- A4: an interrupted run resumes to the same bytes; each target keeps the other's -------------------------------------

def test_an_interrupted_run_resumes_to_the_bytes_of_an_uninterrupted_one(rotated, tmp_path, project, monkeypatch, notebook):
    whole = built(rotated, tmp_path / 'whole', project)
    ran(whole)
    expected = files(whole)
    project.__init__()
    cut = built(rotated, tmp_path / 'cut', project)
    fired = failing(monkeypatch, lambda path, raw: path.name == 'starter.json')
    with pytest.raises(OSError): ran(cut)
    assert fired and (cut / 'pack/files' / starter.PY_RESULT).read_bytes() == expected['files/' + starter.PY_RESULT]
    assert targets(cut)['python']['oracle'] == starter.ORACLE_PYTHON  # the result first, starter.json not yet
    monkeypatch.undo()
    if WHEEL: monkeypatch.setattr(sys, 'executable', WHEEL)
    ran(cut)
    assert files(cut) == expected
    mtimes = [(cut / 'pack' / p).stat().st_mtime_ns for p in expected]
    ran(cut)  # a completed rerun changes nothing
    assert files(cut) == expected and [(cut / 'pack' / p).stat().st_mtime_ns for p in expected] == mtimes


@pytest.mark.parametrize('order', ['python-then-opendtect', 'opendtect-then-python'])
def test_each_target_keeps_the_other_targets_result_oracle_and_artefacts(rotated, tmp_path, project, rotated_odbind, notebook, order):
    folder = built(rotated, tmp_path, project)
    survey = survey_at(tmp_path)
    first, second = order.split('-then-')
    run_of = {'python': lambda: ran(folder), 'opendtect': lambda: starter.opendtect(client(project), folder / 'pack', survey, python=PLAIN)}
    run_of[first]()
    kept = json.dumps(targets(folder)[first], sort_keys=True)
    result = {'python': 'files/' + starter.PY_RESULT, 'opendtect': 'files/' + RESULT}[first]
    raw = (folder / 'pack' / result).read_bytes()
    run_of[second]()
    after = targets(folder)
    assert json.dumps(after[first], sort_keys=True) == kept and (folder / 'pack' / result).read_bytes() == raw
    assert not starter.nothing_yet(after['python']) and not starter.nothing_yet(after['opendtect'])


# --- R2-8: a shared path changed in one target only ----------------------------------------------------------------------

@pytest.mark.parametrize('change', ['bytes', 'key'])
def test_a_shared_path_changed_in_the_second_target_only_is_refused(rotated, tmp_path, project, rotated_odbind, change):
    folder = built(rotated, tmp_path, project)
    document = folder / 'pack/starter.json'
    doc = json.loads(document.read_text())
    second = next(a for a in doc['targets'][1]['artefacts'] if a['path'] == 'wells/SYN-A.las')
    if change == 'bytes': second.update(bytes=second['bytes'] + 1)
    else: second['key'] = 'mirror/%s/%s/derived-SYN-A.las' % (PACK.rsplit('/', 1)[0], second['sha256'])
    edited = starter.dumped(doc)
    document.write_bytes(edited)
    derive(folder)
    sentence = starter.SHARED % 'wells/SYN-A.las' + starter.UNCHANGED
    assert refused(ran, folder) == sentence
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == sentence
    assert refused(starter.opendtect, client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN) == sentence
    assert document.read_bytes() == edited and not (folder / 'pack/files' / starter.PY_RESULT).exists()


# --- D4: finalise needs both targets run, and writes one key per shared path ---------------------------------------------

def test_finalise_refuses_before_the_notebook_ran_and_then_keys_every_occurrence(rotated, tmp_path, project, rotated_odbind, notebook):
    folder = built(rotated, tmp_path, project)
    starter.opendtect(client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN)
    derive(folder)
    before = (folder / 'pack/starter.json').read_bytes()
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == (
        'The Python target of %s has not been run yet (its oracle says "nothing yet"): run ophiolite starter python on it first.' % PACK + starter.UNCHANGED)
    assert (folder / 'pack/starter.json').read_bytes() == before
    ran(folder)
    derive(folder)
    doc = starter.finalise(folder / 'pack', folder / 'custody')
    keys = {}
    for a in (a for t in doc['targets'] for a in t['artefacts']):
        assert keys.setdefault(a['path'], a['key']) == a['key'] and a['key'].endswith('/' + a['sha256'] + '/derived-' + a['path'].rsplit('/', 1)[-1])
    assert sorted(keys) == sorted(set(ARTEFACTS + [RESULT] + PYTHON + [starter.PY_RESULT]))


# --- E129 (d) C1: the ResInsight target in the build (strategy rev 3, D1-D4; A1, A2, A6) ---------------------------------

WELL_FILES = ['wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
RESINSIGHT = [starter.RI_IMPORT] + WELL_FILES  # the ResInsight target's artefacts as built
D3 = ('The pack definition targets must be ["opendtect"], ["opendtect", "python"], ["opendtect", "resinsight"] or ["opendtect", "python", '
      '"resinsight"] for an archive in this version.' + starter.NOTHING_SENT)


def launcher(folder):
    """The built import.py's embedded bindings (PACK, FILES), read by running it as a module (its main does not run)."""
    import runpy
    return runpy.run_path(str(folder / 'pack/files' / starter.RI_IMPORT), run_name='launcher')


@pytest.mark.parametrize('survey, applications', [('resinsight', ['opendtect', 'resinsight']), ('three', ['opendtect', 'python', 'resinsight'])])
def test_the_resinsight_target_is_built_with_its_launcher_and_the_well_files_it_reads(rotated, tmp_path, project, survey, applications):
    folder = built(rotated, tmp_path, project, survey)
    doc = json.loads((folder / 'pack/starter.json').read_text())
    assert [t['application'] for t in doc['targets']] == applications
    entry = doc['targets'][-1]
    assert sorted(entry) == ['application', 'artefacts', 'import', 'oracle', 'version']  # exactly the schema's five keys (D2: no cube key)
    assert (entry['version'], entry['import']) == ('2026.09.0 (rips 2026.9.0.2)', 'targets/resinsight/import.py')
    assert entry['oracle']['compared'][0] == 'cube: false; wells and logs only (rips 2026.9.0.2 has no SEG-Y import)'
    assert entry['oracle'] == starter.ORACLE_RESINSIGHT and starter.nothing_yet(entry) and starter.not_imported(doc)
    assert [a['path'] for a in entry['artefacts']] == RESINSIGHT
    shared = {a['path']: a for a in doc['targets'][0]['artefacts']}
    assert all(a == shared[a['path']] for a in entry['artefacts'] if a['path'] in WELL_FILES)  # one artefact, listed by every target
    assert (doc['recipe']['tools']['resinsight'], doc['recipe']['tools']['rips']) == ('2026.09.0', '2026.9.0.2')
    derived = {d['path']: d for d in doc['derived']}
    bindings = launcher(folder)
    assert bindings['PACK'] == PACK
    assert bindings['FILES'] == {'wells/SYN-A-positions.csv': {'sha256': derived['wells/SYN-A-positions.csv']['sha256'], 'bytes': derived['wells/SYN-A-positions.csv']['bytes'], 'kind': 'wellbore-paths', 'object': 'SYN-A'},
                                 'wells/SYN-A.las': {'sha256': derived['wells/SYN-A.las']['sha256'], 'bytes': derived['wells/SYN-A.las']['bytes'], 'kind': 'wellbore-logs', 'object': 'SYN-A'},
                                 'wells/SYN-B-positions.csv': {'sha256': derived['wells/SYN-B-positions.csv']['sha256'], 'bytes': derived['wells/SYN-B-positions.csv']['bytes'], 'kind': 'wellbore-paths', 'object': 'SYN-B'}}
    starter.shaped(doc)


def test_one_and_two_target_packs_are_unchanged_by_the_third_target(rotated, tmp_path, project):
    """A1: the two-target pack is the three-target pack without its ResInsight entry, launcher and the two tool versions,
    byte for byte (the pre-(d) tests of one- and two-target packs keep their literals)."""
    two = built(rotated, tmp_path / 'two', project)
    project.__init__()
    three = built(rotated, tmp_path / 'three', project, 'three')
    doc = json.loads((three / 'pack/starter.json').read_text())
    assert doc['targets'].pop()['application'] == 'resinsight'
    doc['recipe']['tools'].pop('resinsight'); doc['recipe']['tools'].pop('rips')
    assert starter.dumped(doc) == (two / 'pack/starter.json').read_bytes()
    def tree(folder): return {p.relative_to(folder / 'pack/files').as_posix(): p.read_bytes() for p in sorted((folder / 'pack/files').rglob('*')) if p.is_file()}
    made3 = tree(three)
    assert made3.pop(starter.RI_IMPORT) and made3 == tree(two)


@pytest.mark.parametrize('targets', [['resinsight'], ['opendtect', 'resinsight', 'python'], ['opendtect', 'resinsight', 'resinsight'],
                                     ['python', 'resinsight'], ['opendtect', 'petrel']])
def test_other_target_lists_are_refused_with_the_d3_sentence(rotated, tmp_path, project, targets):
    folder, export = copied(rotated, 'resinsight', tmp_path)
    definition = json.loads((folder / 'definition.json').read_text())
    definition['targets'] = targets
    (folder / 'definition.json').write_text(json.dumps(definition))
    assert refused(build, folder, export, project) == D3
    assert project.read == {} and not (folder / 'pack/starter.json').exists()


def no_wells(target, report):
    """The export without its well files: neither derived nor listed."""
    report['derived'] = [d for d in report['derived'] if not d['path'].startswith('wells/')]
    report['files'] = [f for f in report['files'] if not f['path'].startswith('wells/')]


def test_an_export_without_well_paths_refuses_the_resinsight_target(rotated, tmp_path, project):
    folder, export = copied(rotated, 'resinsight', tmp_path)
    another(export, 'no-wells', no_wells)
    assert refused(build, folder, export, project) == 'The ResInsight target reads well paths; this export has none.' + starter.NOT_WRITTEN
    assert project.read == {} and not (folder / 'pack/starter.json').exists()


def trap(where):
    """A path where importing rips or the Connectors module leaves a mark and fails: the launcher must refuse first."""
    for name in ('rips', 'asset_connectors'):
        (where / name).mkdir(parents=True)
        (where / name / '__init__.py').write_text('from pathlib import Path\nPath(%r).write_text("imported")\nraise ImportError("trap")\n' % str(where / (name + '.imported')))
    return where


@pytest.mark.parametrize('path', WELL_FILES)
def test_the_launcher_refuses_a_changed_well_file_before_any_rips_import(rotated, tmp_path, project, path):
    folder = built(rotated, tmp_path, project, 'resinsight')
    marks = trap(tmp_path / 'trap')
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}, 'PYTHONPATH': str(marks)}
    script = [sys.executable, str(folder / 'pack/files' / starter.RI_IMPORT), str(folder / 'pack'), str(tmp_path / 'project')]
    untouched = subprocess.run(script, env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert untouched.returncode == 2 and untouched.stderr.strip() == starter.NO_CONNECTORS and (marks / 'asset_connectors.imported').exists()
    (marks / 'asset_connectors.imported').unlink()
    local = folder / 'pack/files' / path
    local.write_bytes(local.read_bytes().replace(b'0', b'1', 1))
    done = subprocess.run(script, env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert (done.returncode, done.stderr.strip()) == (2, '%s is not the file this pack names: its SHA-256 differs; nothing was imported.' % path)
    assert not (marks / 'asset_connectors.imported').exists() and not (marks / 'rips.imported').exists() and not (tmp_path / 'project').exists()


def test_finalise_refuses_a_pack_listing_resinsight_before_its_import(rotated, tmp_path, project, rotated_odbind):
    folder = built(rotated, tmp_path, project, 'resinsight')
    starter.opendtect(client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN)
    derive(folder)
    before = (folder / 'pack/starter.json').read_bytes()
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == (
        'The ResInsight target of %s has not been imported and compared yet (its oracle says "nothing yet"): run ophiolite starter resinsight on it first.' % PACK
        + starter.UNCHANGED)
    assert (folder / 'pack/starter.json').read_bytes() == before


# --- E137 s1 C4 (D-4, R1-14, R1-17, R2-9): packs with 2D lines -----------------------------------------------------------

LINE_IDS = ('Syn2D/L2', 'Other/L1')  # two names: the fake intake keys a file by its name
WELL_KINDS = [{'kind': 'wellbore-paths', 'ids': ['SYN-A', 'SYN-B']}, {'kind': 'wellbore-logs', 'ids': ['SYN-A', 'SYN-B']}]


def with_lines(contents, targets, ids=LINE_IDS):
    """A definition edit: CONTENTS (and their decisions) with the 2D lines IDS, listing TARGETS."""
    def edit(d):
        kept = {x for c in contents for x in c['ids']}
        d['contents'] = json.loads(json.dumps(contents)) + [{'kind': 'seismic-2d', 'ids': list(ids)}]
        d['decisions'] = [r for r in d['decisions'] if r['subject'] in kept or r['subject'] == 'syn-survey.zip'] + [
            {'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ids
            for t, v in (('crs', 'EPSG:32631'), ('domain', 'time'), ('units', 'ms'), ('nulls', 'non-finite refused'))]
        d['targets'] = list(targets)
    return edit


@pytest.fixture(scope='module')
def lined(tmp_path_factory):
    """{case: (definition folder, export OUT)}: lines only; lines and wells without a cube; the cube, horizon, wells and
    lines; the edge survey's unsorted line `Mix/U` alone (trace numbers 7, 3, 9, 1, 5 in file order)."""
    from test_starter_export import CONTENTS
    out = {}
    for case, contents, listed, ids in (('lines', [], BOTH, LINE_IDS), ('lines-wells', WELL_KINDS, BOTH + ['resinsight'], LINE_IDS),
                                        ('cube-lines', CONTENTS, BOTH + ['resinsight'], LINE_IDS), ('unsorted', [], BOTH, ('Mix/U',))):
        folder, export = made(tmp_path_factory.mktemp('definition-' + case), edit=with_lines(contents, listed, ids)), tmp_path_factory.mktemp('export-' + case)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
            if case == 'unsorted': mp.setenv('FAKE_ODBIND_VARIANT', 'edge')
            else: mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
            run(folder, export)
        out[case] = folder, export
    return out


def line_values(path, obj, first, start):
    """The expected values of the fake's line with trace numbers FIRST..FIRST+4 (source points 1.5, 2, none, 3.5, 4;
    samples trc / 4 + k / 8 at z 100, 104 ... 116 ms): the middle sample (k = 2) of its first, middle and last trace
    is trc / 4 + 1 / 4, and its sum over the five traces is the sum of 5 trc / 4 + 10 / 8."""
    numbers = list(range(first, first + 5))
    return {'path': path, 'object': obj, 'traces': 5, 'numbers': numbers, 'source_points': [1.5, 2.0, None, 3.5, 4.0],
            'x': [500001.0, 500013.5, 500026.0, 500038.5, 500051.0], 'y': [100.0, 106.25, 112.5, 118.75, 125.0], 'z': [100, 4000, 5],
            'samples': [{'trace': t, 'index': 2, 'value': start + (t - first) / 4} for t in (first, first + 2, first + 4)],
            'sum': sum(t / 4 * 5 for t in numbers) + 5 * 10 / 8}


LINES_EXPECTED = [dict(line_values('seismic2d/Other/L1.sgy', 'Other/L1', 301, 75.5), sha256='adf64fb1589aa05e3fe517d1545b9d1a0ec70d0f46c22e394f40f991559e20e1'),
                  dict(line_values('seismic2d/Syn2D/L2.sgy', 'Syn2D/L2', 201, 50.5), sha256='470897e15cab9a27557069eece938c52117c06d8556ebf666ce656983c460ba8')]
LINES_SAID = ['line %s: 5 trace numbers, source points, x and y, Z, 3 samples, the sum and the SHA-256 of every sample read with segyio' % o for o in ('Other/L1', 'Syn2D/L2')]
NO_PLANE = {'cube': None, 'inline': None, 'crosslines': None, 'z': None, 'samples': [], 'inline_sum': None}
PLOTTED_LINE = {'object': 'Other/L1', 'shape': [5, 5], 'values': [75.5, 76.0, 76.5], 'extent': [0.0, 4.0, 116.0, 100.0], 'origin': 'upper'}


def test_a_pack_of_lines_only_expects_each_line_and_the_notebook_agrees(lined, tmp_path, project, notebook):
    """D-4, R1-14: /2 with no cube, each line's numbers, source points, x and y in file order, Z, three samples, the sum
    and the samples' SHA-256; the notebook reads them with segyio and agrees. Mutations: the line's numbers sorted by
    value, an absent source point read as 0, the line left out of the Python target's artefacts."""
    folder = built(lined, tmp_path, project, 'lines')
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert expected == {'schema': 'ophiolite.starter-python-expected/2', **NO_PLANE, 'wells': [], 'not_computed': starter.NO_PLANE, 'lines': LINES_EXPECTED}
    assert [a['path'] for a in targets(folder)['python']['artefacts']] == [starter.PY_IMPORT, starter.PY_EXPECTED, 'seismic2d/Syn2D/L2.sgy', 'seismic2d/Other/L1.sgy']  # the derived order
    doc, result = ran(folder)
    assert (result['differences'], result['plotted'], [line['numbers'] for line in result['lines']]) == ([], {'line': PLOTTED_LINE}, [[301, 302, 303, 304, 305], [201, 202, 203, 204, 205]])
    assert targets(folder)['python']['oracle'] == {'compared': LINES_SAID + ['plotted: line Other/L1, read back from the figure'],
                                                   'values': 56, 'differences': 0, 'seed': 0}  # per line 4 x 5 + 3 (Z) + 3 samples + the sum and the SHA-256


def test_lines_and_wells_without_a_cube_read_the_wells_at_their_own_positions(lined, tmp_path, project, notebook):
    """R2-9: no cube, so no plane: each well's inline and crossline are null, `not_computed` says why, and the notebook
    reads the wells' logs and the lines and agrees."""
    folder = built(lined, tmp_path, project, 'lines-wells')
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert expected == {'schema': 'ophiolite.starter-python-expected/2', **NO_PLANE, 'wells': [
        {'name': 'SYN-A', 'positions': 'wells/SYN-A-positions.csv', 'x': 500010.125, 'y': 10.375, 'inline': None, 'crossline': None,
         'las': 'wells/SYN-A.las', 'curves': 2, 'depth': [100.0, 100.9]},
        {'name': 'SYN-B', 'positions': 'wells/SYN-B-positions.csv', 'x': 500075.0, 'y': 50.0, 'inline': None, 'crossline': None,
         'las': None, 'curves': None, 'depth': None}], 'not_computed': starter.NO_PLANE, 'lines': LINES_EXPECTED}
    doc, result = ran(folder)
    assert (result['differences'], result['without_logs'], result['wells']) == ([], ['SYN-B'], [
        {'name': 'SYN-A', 'inline': None, 'crossline': None, 'curves': 2, 'depth': [100.0, 100.9]},
        {'name': 'SYN-B', 'inline': None, 'crossline': None, 'curves': None, 'depth': None}])
    assert targets(folder)['python']['oracle'] == {'compared': [
        'well SYN-A: not projected (no cube); 2 curves from 100.0 to 100.9 read with lasio', 'well SYN-B: not projected (no cube); positions only',
        *LINES_SAID, 'plotted: line Other/L1, read back from the figure'], 'values': 59, 'differences': 0, 'seed': 0}


def test_a_cube_with_lines_carries_both_and_a_pack_without_lines_keeps_v1(lined, rotated, tmp_path, project, notebook):
    """R1-17: the cube's values as /1 has them, the lines after them, under /2; the notebook agrees with both. The
    rotated pack (no lines) is still /1 with exactly /1's keys."""
    folder = built(lined, tmp_path / 'lined', project, 'cube-lines')
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert list(expected) == ['schema', 'cube', 'inline', 'crosslines', 'z', 'samples', 'inline_sum', 'wells', 'lines']
    assert (expected['schema'], expected['cube'], expected['inline'], expected['samples'], expected['inline_sum'], expected['lines']) == (
        'ophiolite.starter-python-expected/2', 'seismic/Syn.sgy', 12, SAMPLES, 357.5, LINES_EXPECTED)
    assert [(w['name'], w['inline'], w['crossline']) for w in expected['wells']] == [('SYN-A', 10.41, 20.39), ('SYN-B', 12.0, 22.98)]
    doc, result = ran(folder)
    assert result['differences'] == [] and result['plotted']['line'] == PLOTTED_LINE and result['plotted']['image']['values'] == [17.125, 17.625, 18.625]
    assert targets(folder)['python']['oracle']['values'] == 11 + 2 * 28  # the cube's 11 (as A1 counts them) and each line's 28
    project.__init__()
    plain = built(rotated, tmp_path / 'plain', project)
    v1 = json.loads((plain / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert v1['schema'] == 'ophiolite.starter-python-expected/1' and list(v1) == ['schema', 'cube', 'inline', 'crosslines', 'z', 'samples', 'inline_sum', 'wells']


@pytest.mark.parametrize('key, change, said', [
    ('numbers', lambda line: line['numbers'].reverse(), 'the numbers of line Other/L1'),
    ('source_points', lambda line: line['source_points'].__setitem__(2, 0.0), 'the source points of line Other/L1'),
    ('x', lambda line: line['x'].__setitem__(4, 500051.01), 'the x of line Other/L1'),
    ('sha256', lambda line: line.__setitem__('sha256', '0' * 64), 'the sha256 of line Other/L1'),
])
def test_the_notebook_names_a_line_value_that_differs_from_expected(lined, tmp_path, project, key, change, said):
    """The notebook's own comparison, on a pack whose expected.json was changed after the build (the notebook run
    directly, as test_pack_notebook runs it): each changed value is named and the notebook fails."""
    from test_pack_notebook import notebook as run_notebook
    folder = built(lined, tmp_path / 'built', project, 'lines')
    path = folder / 'pack/files' / starter.PY_EXPECTED
    expected = json.loads(path.read_text())
    change(expected['lines'][0])
    path.write_text(json.dumps(expected))
    done, result = run_notebook(tmp_path, pack=folder / 'pack')
    assert done.returncode != 0 and result['differences'] == [said]


def test_an_unsorted_line_is_expected_and_read_in_file_order(lined, tmp_path, project, notebook):
    """R1-3, R1-14: the edge survey's `Mix/U` keeps its file order (trace numbers 7, 3, 9, 1, 5, source points equal to
    them, x 500000 + 10 trc) in expected.json and in what the notebook reads. Mutation: the numbers or positions
    sorted by trace number."""
    folder = built(lined, tmp_path, project, 'unsorted')
    (line,) = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())['lines']
    assert (line['numbers'], line['source_points'], line['x'], line['y']) == (
        [7, 3, 9, 1, 5], [7.0, 3.0, 9.0, 1.0, 5.0], [500070.0, 500030.0, 500090.0, 500010.0, 500050.0], [70.0, 30.0, 90.0, 10.0, 50.0])
    assert line['samples'] == [{'trace': 7, 'index': 1, 'value': 1.875}, {'trace': 9, 'index': 1, 'value': 2.375}, {'trace': 5, 'index': 1, 'value': 1.375}]
    doc, result = ran(folder)
    assert result['differences'] == [] and result['lines'][0]['numbers'] == [7, 3, 9, 1, 5]


# --- E137 s2 C4 (D-8): a pack with faults says the notebook does not draw them ---------------------------------------

PY_FAULTS = 'faults: not drawn; the pack notebook does not read fault sticks'
ROTATED_ORACLE = ['inline 12: 3 samples and the inline sum read with segyio',
                  'well SYN-A: projected to inline 10.09, crossline 20.56; 2 curves from 100.0 to 100.9 read with lasio',
                  'well SYN-B: projected to inline 9.81, crossline 23.58; positions only',
                  'plotted: the inline image and 2 well lines, read back from the figure']


def with_faults(d):
    """A definition edit: the rotated pack's contents, SynF and SynF3D (time, seconds), all three targets."""
    d['contents'] += [{'kind': 'faults', 'ids': ['SynF', 'SynF3D']}]
    d['decisions'] += [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ('SynF', 'SynF3D')
                       for t, v in (('crs', 'EPSG:32631'), ('domain', 'time'), ('units', 's'))]
    d['targets'] = ['opendtect', 'python', 'resinsight']


@pytest.fixture(scope='module')
def faulted(tmp_path_factory):
    """{'faults': (definition folder, export OUT)}: the rotated survey with its faults, for all three targets."""
    folder, export = made(tmp_path_factory.mktemp('definition-faults'), edit=with_faults), tmp_path_factory.mktemp('export-faults')
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.setenv('FAKE_ODBIND_VARIANT', 'rotated')
        run(folder, export)
    return {'faults': (folder, export)}


def test_a_pack_with_faults_says_the_notebook_does_not_draw_them_before_after_and_on_a_rerun(faulted, rotated, tmp_path, project, notebook):
    """D-8: the statement is the Python oracle's last line before the notebook runs, after it, and after a rerun that
    reopens the saved result (`_held_python` gives the same oracle); expected.json is the pack's without faults byte for
    byte, and the faults are not the target's artefacts. Mutations: the statement only in the waiting oracle;
    `python_oracle` without it (a rerun refuses or the oracle loses it)."""
    folder = built(faulted, tmp_path / 'faults', project, 'faults')
    python = targets(folder)['python']
    assert python['oracle'] == {**starter.ORACLE_PYTHON, 'compared': [*starter.ORACLE_PYTHON['compared'], PY_FAULTS]}
    assert [a['path'] for a in python['artefacts']] == PYTHON
    expected = (folder / 'pack/files' / starter.PY_EXPECTED).read_bytes()
    ran(folder)
    assert targets(folder)['python']['oracle'] == {'compared': ROTATED_ORACLE + [PY_FAULTS], 'values': 11, 'differences': 0, 'seed': 0}
    kept = files(folder)
    ran(folder)  # a completed rerun reopens the result starter.json names
    assert files(folder) == kept
    project.__init__()
    plain = built(rotated, tmp_path / 'plain', project)
    assert (plain / 'pack/files' / starter.PY_EXPECTED).read_bytes() == expected
    assert targets(plain)['python']['oracle'] == starter.ORACLE_PYTHON  # a pack without faults keeps its oracle


def test_the_fidelity_rows_of_faults_are_their_landings(faulted, tmp_path, project):
    """D-8 (O2): fidelity/1 keeps its meaning; a fault's row is its landing (converted, its output) and says nothing of
    an application. It has no representative values: fidelity gives them for curves and point sets, not polylines."""
    from test_starter_archive_pack import FIDELITY
    folder = built(faulted, tmp_path, project, 'faults')
    rows = {i['name']: i for i in json.loads((folder / 'pack' / FIDELITY).read_text())['inputs']}
    assert [(set(rows[p]), rows[p]['result']) for p in ('faults/SynF.dat', 'faults/SynF3D.dat')] == [({'sha256', 'name', 'result', 'output'}, 'converted')] * 2
    assert not any(word in json.dumps(rows['faults/SynF.dat']) for word in ('ResInsight', 'rips', 'notebook', 'OpendTect'))
