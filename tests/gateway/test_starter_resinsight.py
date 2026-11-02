"""E129 (d) C3 (strategy rev 3, D5, D6; acceptance A5, R2-9): `ophiolite starter resinsight` on archive packs built from
the real export of the rotated survey (test_starter_python's `rotated` fixture: SYN-A and SYN-B, strategy E6), with the
Connectors interpreter running the packaged launcher and the comparison against the fake `rips` of
ophiolite-connectors/tests/fake_rips and its stand-in ResInsight executable (the launcher starts and stops it).

The Connectors interpreter is a small script in the test's folder: this interpreter with the fake rips and the Connectors
source first on PYTHONPATH (the SDK never imports either). The installed-wheel run takes OPHIOLITE_TEST_WHEEL_PYTHON as
test_starter_python's A1 does (required with OPHIOLITE_REQUIRE_WHEEL=1). The oracle's literals are counted by hand:
7 stations (4 + 3), 181 + 101 samples at 1 m (md 0-180 and 0-100), 14 log values (2 curves x 7 rows, fewer than 50):
4 x 7 + 3 x 282 + 14 = 888 values; tolerances x 2^-5 at 500015 plus the md rounding through the slope, y 2^-18 at 51.25
plus 0.025 x 2^-17, z 2^-16 at 158.75 plus 0.9875 x 2^-16."""
import json
import os
import subprocess
import sys

import pytest

from ophiolite import starter
from test_starter_build import failing
from test_starter_archive_pack import (build, client, derive, project, refused, survey_at, ARTEFACTS, RESULT)  # noqa: F401 (project: a fixture)
from test_starter_export import PACK, ROOT, sha
from test_starter_python import (built, faulted, files, lined, notebook, ran, rotated, rotated_odbind, targets, with_lines, PLAIN, PYTHON, RESINSIGHT, WHEEL)  # noqa: F401 (fixtures)

FAKE_RIPS, CONNECTORS = ROOT / 'ophiolite-connectors/tests/fake_rips', ROOT / 'ophiolite-connectors/src'
ORACLE = {'compared': [
    'cube: false; wells and logs only (rips 2026.9.0.2 has no SEG-Y import)',
    "well paths: 2 read back at ResInsight's 1 m samples, within x 0.0313 m, y 0.00000401 m, z 0.0000303 m of the pack's stations interpolated in md",
    'stations: the 7 of the positions files written to the .dev files ResInsight read, each as written; first and last read back exactly as float32',
    'logs: 1 LAS files on their wells: curves, lengths, null masks and measured depths, then 14 values drawn with random.Random(0), equal as float32; '
    '1 well paths without logs',
    'not seen in what ResInsight holds (it exposes no imported station): a station dropped on the line through its neighbours, or a bend narrower '
    'than the 1 m between two samples',
    'reopened: the same read-back, with no difference, after the project was saved, closed and opened again'], 'values': 888, 'differences': 0, 'seed': 0}


@pytest.fixture
def connectors(tmp_path, monkeypatch):
    """(the Connectors interpreter, the ResInsight executable): scripts in tmp_path over this interpreter, the fake rips
    and the stand-in executable; every switch of the fake off."""
    state = tmp_path / 'servers'
    python = tmp_path / 'connectors-python'
    python.write_text('#!/bin/sh\nPYTHONPATH=%s:%s FAKE_RIPS_STATE=%s DISPLAY=:99 exec %s "$@"\n' % (FAKE_RIPS, CONNECTORS, state, sys.executable))
    exe = tmp_path / 'ResInsight'
    exe.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE_RIPS / 'fake_resinsight.py'))
    for script in (python, exe): script.chmod(0o755)
    for name in ('FAKE_RIPS_INTERRUPT', 'FAKE_RIPS_SHIFT', 'FAKE_RESINSIGHT_VERSION', 'RESINSIGHT_EXECUTABLE', 'OPHIOLITE_RESINSIGHT_PYTHON'):
        monkeypatch.delenv(name, raising=False)
    return str(python), str(exe)


def imported(folder, connectors):
    python, exe = connectors
    return starter.resinsight(folder / 'pack', executable=exe, python=python)


def written(folder):
    return {p: (folder / 'pack' / p).read_bytes() for p in ('starter.json', 'files/' + starter.RI_RESULT) if (folder / 'pack' / p).exists()}


def test_starter_resinsight_writes_the_result_then_the_oracle_counted_by_hand(rotated, tmp_path, project, connectors):
    folder = built(rotated, tmp_path, project, 'resinsight')
    before = targets(folder)['opendtect']
    doc, result = imported(folder, connectors)
    raw = (folder / 'pack/files' / starter.RI_RESULT).read_bytes()
    assert json.loads(raw) == result and raw == (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    assert (result['format'], result['cube'], result['reopened'], result['differences']) == ('ophiolite.resinsight-starter-result/1', False, True, 0)
    assert (result['resinsight'], result['rips'], result['stations'], result['samples'], result['without_logs']) == ('2026.9.0', '2026.9.0.2', 7, 14, ['SYN-B'])
    assert [(w['name'], w['stations'], w['samples'], [l['curves'] for l in w['logs']]) for w in result['wells']] == [
        ('SYN-A', 4, 181, [['DEPT', 'DT', 'GR']]), ('SYN-B', 3, 101, [])]
    after = targets(folder)
    assert after['opendtect'] == before and after['resinsight']['oracle'] == ORACLE
    assert all(len(line) <= 300 for line in ORACLE['compared'])
    assert [a['path'] for a in after['resinsight']['artefacts']] == RESINSIGHT + [starter.RI_RESULT]
    assert after['resinsight']['artefacts'][-1] == {'path': starter.RI_RESULT, 'sha256': sha(raw), 'bytes': len(raw)}
    started = [json.loads(line) for line in (tmp_path / 'servers/starts.jsonl').read_text().splitlines()]
    assert len(started) == 2 and all(not os.path.exists('/proc/%d' % s['pid']) for s in started)  # the launcher's and the comparison's, both stopped
    kept = written(folder)
    imported(folder, connectors)  # a completed rerun changes nothing
    assert written(folder) == kept


def test_without_a_connectors_interpreter_nothing_runs(rotated, tmp_path, project):
    folder = built(rotated, tmp_path, project, 'resinsight')
    before = written(folder)
    assert refused(starter.resinsight, folder / 'pack') == starter.NO_RI_PYTHON
    assert written(folder) == before


def test_an_interrupted_run_resumes_to_the_bytes_of_an_uninterrupted_one(rotated, tmp_path, project, connectors, monkeypatch):
    whole = built(rotated, tmp_path / 'whole', project, 'resinsight')
    imported(whole, connectors)
    expected = written(whole)
    project.__init__()
    cut = built(rotated, tmp_path / 'cut', project, 'resinsight')
    fired = failing(monkeypatch, lambda path, raw: path.name == 'starter.json')
    with pytest.raises(OSError): imported(cut, connectors)
    assert fired and (cut / 'pack/files' / starter.RI_RESULT).read_bytes() == expected['files/' + starter.RI_RESULT]
    assert targets(cut)['resinsight']['oracle'] == starter.ORACLE_RESINSIGHT  # the result first, starter.json not yet
    monkeypatch.undo()
    imported(cut, connectors)
    assert written(cut) == expected


def test_a_launcher_interrupted_between_the_path_and_the_log_import_reruns_to_the_same_bytes(rotated, tmp_path, project, connectors, monkeypatch):
    whole = built(rotated, tmp_path / 'whole', project, 'resinsight')
    imported(whole, connectors)
    expected = written(whole)
    project.__init__()
    cut = built(rotated, tmp_path / 'cut', project, 'resinsight')
    before = written(cut)
    monkeypatch.setenv('FAKE_RIPS_INTERRUPT', 'import_well_log_files')
    assert refused(imported, cut, connectors) == 'The ResInsight import stopped (exit status -2): KeyboardInterrupt' + starter.UNCHANGED  # SIGINT, as Python exits on one
    assert written(cut) == before
    monkeypatch.delenv('FAKE_RIPS_INTERRUPT')
    imported(cut, connectors)
    assert written(cut) == expected


@pytest.mark.parametrize('order', [['opendtect', 'python', 'resinsight'], ['resinsight', 'python']], ids=['opendtect-python-resinsight', 'resinsight-python'])
def test_each_target_keeps_the_other_targets_entries(rotated, tmp_path, project, rotated_odbind, notebook, connectors, order):
    folder = built(rotated, tmp_path, project, 'three')
    run_of = {'python': lambda: ran(folder), 'resinsight': lambda: imported(folder, connectors),
              'opendtect': lambda: starter.opendtect(client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN)}
    for n, application in enumerate(order):
        kept = {a: json.dumps(t, sort_keys=True) for a, t in targets(folder).items() if a != application}
        run_of[application]()
        after = targets(folder)
        assert {a: json.dumps(after[a], sort_keys=True) for a in kept} == kept, application
        assert not starter.nothing_yet(after[application])


@pytest.mark.parametrize('change', ['bytes', 'key'])
def test_a_shared_path_changed_in_the_resinsight_target_only_is_refused(rotated, tmp_path, project, connectors, change):
    folder = built(rotated, tmp_path, project, 'resinsight')
    document = folder / 'pack/starter.json'
    doc = json.loads(document.read_text())
    ri = next(t for t in doc['targets'] if t['application'] == 'resinsight')
    occurrence = next(a for a in ri['artefacts'] if a['path'] == 'wells/SYN-A-positions.csv')
    if change == 'bytes': occurrence.update(bytes=occurrence['bytes'] + 1)
    else: occurrence['key'] = 'mirror/%s/%s/derived-SYN-A-positions.csv' % (PACK.rsplit('/', 1)[0], occurrence['sha256'])
    edited = starter.dumped(doc)
    document.write_bytes(edited)
    assert refused(imported, folder, connectors) == starter.SHARED % 'wells/SYN-A-positions.csv' + starter.UNCHANGED
    assert document.read_bytes() == edited and not (folder / 'pack/files' / starter.RI_RESULT).exists() and not (tmp_path / 'servers').exists()


def test_a_comparison_with_a_difference_installs_no_oracle_and_finalise_still_refuses(rotated, tmp_path, project, rotated_odbind, connectors, monkeypatch):
    """R2-9 through the command (the installed wheel's when OPHIOLITE_TEST_WHEEL_PYTHON names it): SYN-A's head read back
    1 m east, a geometry difference, not an inventory one."""
    folder = built(rotated, tmp_path, project, 'resinsight')
    starter.opendtect(client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN)
    before = written(folder)
    python, exe = connectors
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}, 'FAKE_RIPS_SHIFT': 'SYN-A:0:x:1.0'}
    if WHEEL: env.pop('PYTHONPATH', None)
    done = subprocess.run([WHEEL or sys.executable, '-c', 'import sys; from ophiolite.cli import entrypoint; sys.argv[0] = "ophiolite"; entrypoint()',
                           'starter', 'resinsight', str(folder / 'pack'), '--resinsight', exe, '--resinsight-python', python],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 1, done.stderr
    said = done.stderr.strip().splitlines()[-1]
    assert said.startswith('ResInsight read the pack back with ') and ' differences; the first: well path SYN-A: x at md 0.0 is 500011.125, ' in said, said
    assert said.endswith(starter.UNCHANGED) and written(folder) == before
    assert targets(folder)['resinsight']['oracle'] == starter.ORACLE_RESINSIGHT
    derive(folder)
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == starter.NOT_IMPORTED % PACK + starter.UNCHANGED


def test_finalise_after_the_import_keys_every_artefact(rotated, tmp_path, project, rotated_odbind, connectors):
    folder = built(rotated, tmp_path, project, 'resinsight')
    starter.opendtect(client(project), folder / 'pack', survey_at(tmp_path), python=PLAIN)
    imported(folder, connectors)
    derive(folder)
    doc = starter.finalise(folder / 'pack', folder / 'custody')
    keys = {}
    for a in (a for t in doc['targets'] for a in t['artefacts']):
        assert keys.setdefault(a['path'], a['key']) == a['key'] and a['key'].endswith('/' + a['sha256'] + '/derived-' + a['path'].rsplit('/', 1)[-1])
    assert sorted(keys) == sorted(set(ARTEFACTS + [RESULT] + RESINSIGHT + [starter.RI_RESULT]))


def test_starter_resinsight_of_the_installed_wheel(rotated, tmp_path, project, connectors):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    folder = built(rotated, tmp_path / 'built', project, 'resinsight')
    python, exe = connectors
    (tmp_path / 'outside').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_') and k != 'PYTHONPATH'}
    done = subprocess.run([WHEEL, '-c', 'import sys; from ophiolite.cli import entrypoint; sys.argv[0] = "ophiolite"; entrypoint()', 'starter', 'resinsight',
                           str(folder / 'pack'), '--resinsight', exe, '--resinsight-python', python, '--json'],
                          cwd=tmp_path / 'outside', env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr
    where = subprocess.run([WHEEL, '-c', 'import ophiolite; print(ophiolite.__file__)'], cwd=tmp_path / 'outside', env=env, capture_output=True, text=True).stdout.strip()
    assert 'site-packages' in where and not where.startswith(str(ROOT / 'ophiolite-sdk'))  # the installed wheel (CI's venv lives under build/), not this checkout's SDK
    assert json.loads(done.stdout)['oracle'] == targets(folder)['resinsight']['oracle'] == ORACLE


# --- E137 s1 C4 (D-4, R1-15, R1-18, R1-19): a pack with 2D lines says ResInsight does not place them -----------------------

def test_a_pack_with_lines_states_them_not_placed_before_and_after_the_comparison(lined, tmp_path, project, connectors):
    """The statement is in starter.json's ResInsight oracle beside the cube's (not in fidelity.json, whose rows describe
    Ophiolite's conversion), in the launcher's text, after a passing comparison and after a rerun. Mutations: the
    statement only in the waiting oracle (gone after the comparison); the launcher's text unchanged for lines."""
    folder = built(lined, tmp_path, project, 'lines-wells')
    waiting = targets(folder)['resinsight']['oracle']
    assert waiting['compared'][:2] == ['cube: false; wells and logs only (rips 2026.9.0.2 has no SEG-Y import)', 'lines: not placed; rips 2026.9.0.2 has no seismic API']
    launcher = (folder / 'pack/files' / starter.RI_IMPORT).read_text()
    assert "\nThe pack's 2D lines are not imported: ResInsight cannot import seismic lines in this version.\n" in launcher
    assert [a['path'] for a in targets(folder)['resinsight']['artefacts']] == [starter.RI_IMPORT] + [
        'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']  # the lines are not its artefacts
    imported(folder, connectors)
    oracle = targets(folder)['resinsight']['oracle']
    assert oracle == {**ORACLE, 'compared': [ORACLE['compared'][0], 'lines: not placed; rips 2026.9.0.2 has no seismic API', *ORACLE['compared'][1:]]}
    kept = written(folder)
    imported(folder, connectors)  # a completed rerun keeps it
    assert written(folder) == kept
    rotated_launcher = starter.resinsight_import({'id': PACK}, {})
    assert b'2D lines' not in rotated_launcher  # a pack without lines keeps its launcher bytes


def test_a_resinsight_pack_of_lines_without_well_paths_is_refused(tmp_path, project, monkeypatch):
    """D-4: NO_PATHS is kept for a pack of lines only."""
    from test_starter_export import CONNECTOR, FAKE, made, run
    folder, export = made(tmp_path / 'definition', edit=with_lines([], ['opendtect', 'resinsight'])), tmp_path / 'export'
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    run(folder, export)
    assert refused(build, folder, export, project) == starter.NO_PATHS + starter.NOT_WRITTEN
    assert project.read == {}


# --- E137 s2 C4 (D-8, R2-12): a pack with faults says ResInsight does not place them ---------------------------------------

FAULTS_SAID = 'faults: not placed; rips 2026.9.0.2 has no fault-stick import'
RI_FAULTS = "\nThis version of ResInsight cannot import fault sticks; the pack's faults are not imported.\n"


def test_a_pack_with_faults_states_them_not_placed_before_after_and_on_a_rerun(faulted, tmp_path, project, connectors):
    """The statement is in starter.json's ResInsight oracle after the cube's (a technical record, R2-12), in the
    launcher's text, after a passing comparison and after a completed rerun (bytes unchanged); the faults are not the
    target's artefacts. Mutations: the statement only in the waiting oracle; the launcher unchanged for faults."""
    folder = built(faulted, tmp_path, project, 'faults')
    waiting = targets(folder)['resinsight']['oracle']
    assert waiting == {**starter.ORACLE_RESINSIGHT, 'compared': [starter.ORACLE_RESINSIGHT['compared'][0], FAULTS_SAID, *starter.ORACLE_RESINSIGHT['compared'][1:]]}
    assert RI_FAULTS in (folder / 'pack/files' / starter.RI_IMPORT).read_text()
    assert [a['path'] for a in targets(folder)['resinsight']['artefacts']] == RESINSIGHT
    imported(folder, connectors)
    assert targets(folder)['resinsight']['oracle'] == {**ORACLE, 'compared': [ORACLE['compared'][0], FAULTS_SAID, *ORACLE['compared'][1:]]}
    kept = written(folder)
    imported(folder, connectors)
    assert written(folder) == kept
    assert b'fault sticks' not in starter.resinsight_import({'id': PACK}, {})  # a pack without faults keeps its launcher bytes
