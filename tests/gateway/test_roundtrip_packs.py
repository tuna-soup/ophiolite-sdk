"""E137 s5 C1 (strategy rev 3, R1-12, R1-13, R2-4, R2-5, R2-8, R2-10, R2-11): the live pack driver
(`conformance/roundtrip/live_packs.py`) on synthetic inputs only: its output filter, its archives, its workers and
their cleanup, and one synthetic journey through branches A and C on the fake odbind and the loopback gateway.

A gateway module, as test_roundtrip_oracle.py: it reads the driver, the journey and the fake from the monorepo. Every
name below is synthetic."""
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (the gateway lane's fixtures)
from test_roundtrip_journey import exporter_env, survey, zipped  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def _module(name):
    spec = importlib.util.spec_from_file_location('roundtrip_' + name + '_packs_test', ROOT / 'conformance/roundtrip' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


lp = _module('live_packs')
wf = lp._module('workfolder')
SECRETS = lp.secrets_of([('C', 'Syn Cube · v2'), ('C', 'Syn Cube'), ('W', 'SYN-A'), ('M', 'Syn_Survey/Seismics/Syn_Cube.cbvs')])


# --- the filter ---------------------------------------------------------------------------------------------------

def test_the_filter_replaces_every_form_of_a_name_and_every_long_number():
    """R1-12/R2-10: plain, JSON-escaped only, repr, a member path, overlapping names and numbers. Mutations: drop the
    escaped form (the `\\u00b7` literal survives), sort shortest first (`C2 · v2` half replaced)."""
    escaped = 'cube "Syn Cube \\u00b7 v2" at 1250 ms'
    assert lp.scrub(escaped, SECRETS) == 'cube "C1" at # ms'
    assert lp.scrub("'Syn Cube · v2' and 'Syn Cube' in Syn_Survey/Seismics/Syn_Cube.cbvs", SECRETS) == "'C1' and 'C2' in M1"
    assert lp.scrub('well SYN-A at 7 and 3.25', SECRETS) == 'well W1 at 7 and 3.#'
    assert '\\u00b7' not in lp.scrub(escaped, SECRETS) and 'Syn' not in lp.scrub(escaped, SECRETS)


def test_a_record_prints_only_its_fields_and_classes():
    """R2-4: a sentence field is refused; a step holds a class, never text; an unmatched sentence is `unclassified`.
    Mutation: let `record` take any field (the sentence of the second record is printed)."""
    assert lp.classify('The archive holds more than 8589934592 bytes uncompressed. Nothing was sent.') == 'over the extraction cap'
    assert lp.classify('artefact files/x.sgy: no held custody document has its SHA-256. starter.json was not changed.') == 'no derived custody'
    assert lp.classify('The survey does not state its xy unit, so the fault “SynF” cannot be checked against it.') == 'survey states no meaning'  # E137 s6b D-6
    assert lp.classify("The survey's coordinate system is none stated; the fault “SynF” was exported with EPSG:23031.") == 'meaning differs'
    assert lp.classify('Something odd about SYN-A at 812.5') == 'unclassified'
    line = lp.record({'pack': 'T', 'seconds': 125, 'branches': [{'branch': 'C', 'step': 'export', 'outcome': 'refused', 'class': 'unclassified', 'input': 'filtered'}],
                      'dispositions': [{'kind': 'tops', 'object': 'SYN-A 2019', 'state': 'not placed'}]}, SECRETS)
    assert json.loads(line) == {'pack': 'T', 'seconds': 125, 'branches': [{'branch': 'C', 'step': 'export', 'outcome': 'refused', 'class': 'unclassified', 'input': 'filtered'}],
                                'dispositions': [{'kind': 'tops', 'object': 'W1 #', 'state': 'not placed'}]}
    paths = {**SECRETS, **lp.secrets_of([('X', 'seismic/Syn Cube.sgy')], folders=False)}
    assert json.loads(lp.record({'pack': 'T', 'objects': {'seismic-3d': 1}, 'dispositions': [{'kind': 'seismic-3d', 'file': 'seismic/Syn Cube.sgy'}]}, paths)) == {
        'pack': 'T', 'objects': {'seismic-3d': 1}, 'dispositions': [{'kind': 'seismic-3d', 'file': 'X1'}]}  # the kinds are the record's own words
    crs = {**SECRETS, **lp.secrets_of([('G', 'CRS')])}  # a log named like a word of a class
    assert json.loads(lp.record({'branches': [{'step': 'export', 'class': 'survey CRS the connector cannot send'}], 'pack': 'CRS'}, crs)) == {
        'branches': [{'step': 'export', 'class': 'survey CRS the connector cannot send'}], 'pack': 'G1'}
    with pytest.raises(ValueError): lp.record({'pack': 'T', 'sentence': 'SYN-A'}, SECRETS)
    with pytest.raises(ValueError): lp.record({'pack': 'T', 'branches': [{'step': 'export', 'sentence': 'SYN-A'}]}, SECRETS)


# --- the archives -------------------------------------------------------------------------------------------------

def deposit(path):
    with zipfile.ZipFile(path, 'w') as z:
        for name, raw in [('Syn_Survey/', b''), ('Syn_Survey/.survey', b'Name: Syn_Survey\n'), ('Syn_Survey/.terranubis_key', b'synthetic key'),
                          ('Syn_Survey/Seismics/Syn.cbvs', b'x' * 64), ('Syn_Survey/Surfaces/Syn.fss', b'sticks'), ('Syn_Survey/WellInfo/SYN-A.well', b'w')]:
            z.writestr(name, raw)
    return path


def test_no_archive_the_run_writes_holds_the_key_and_a_whole_deposit_under_the_cap_is_refused(tmp_path):
    """D-2: filtered is every member but the key; subset is the survey's files, its top-level folders and the folders
    named; a whole deposit under the cap is never handed on. Mutation: remove the size assertion in `whole_for_cap`."""
    src = deposit(tmp_path / 'dep.zip')
    assert lp.archive_plan(src, 'filtered') == ['Syn_Survey/', 'Syn_Survey/.survey', 'Syn_Survey/Seismics/Syn.cbvs', 'Syn_Survey/Surfaces/Syn.fss',
                                                'Syn_Survey/WellInfo/SYN-A.well']
    sub = lp.archive_plan(src, 'subset', ('Surfaces',))
    assert sub == ['Syn_Survey/.survey', 'Syn_Survey/Seismics/', 'Syn_Survey/Surfaces/', 'Syn_Survey/Surfaces/Syn.fss', 'Syn_Survey/WellInfo/']
    out = lp.written_archive(src, tmp_path / 'sub.zip', sub)
    with zipfile.ZipFile(out) as z: assert sorted(z.namelist()) == sorted(sub)
    with pytest.raises(AssertionError, match='holds the deposit key'): lp.written_archive(src, tmp_path / 'bad.zip', sub + ['Syn_Survey/.terranubis_key'])
    with pytest.raises(AssertionError, match='within the cap'): lp.whole_for_cap(src, 10 ** 6)
    assert lp.whole_for_cap(src, 10) == src


def test_a_table_is_paired_with_exactly_one_well():
    """R2-6: one match pairs; a name two wells match, and one no well matches, are unresolved."""
    tables = [('S/WellInfo/syn_a_checkshot.txt', ['h', 'd', 't']), ('S/WellInfo/syn-b-syn-bb.txt', ['h', 'd', 't']), ('S/x.txt', ['h', 'd', 't'])]
    assert lp.paired(tables, ['SYN-A', 'SYN-B', 'SYN-BB']) == ({'SYN-A': ('S/WellInfo/syn_a_checkshot.txt', ['h', 'd', 't'])}, 2)


# --- the workers and their cleanup ---------------------------------------------------------------------------------

def folder(tmp_path):
    volume = tmp_path / 'volume'
    volume.mkdir()
    return wf.WorkFolder.create(volume, [tmp_path / 'forbidden'])


def fake_exporter(tmp_path, body):
    script = tmp_path / 'fake-exporter'
    script.write_text('#!/bin/sh\n' + body + '\n')
    script.chmod(0o755)
    return str(script)


def run_of(work, tmp_path):
    env = {**work.child_env(), 'TMPDIR': str(work.path / 'tmp'), 'PYTHONPATH': os.pathsep.join(sys.path)}
    return lp.Run(work, tmp_path / 'record.json.private', env)


def test_a_refusal_prints_its_class_and_an_unmatched_crash_goes_to_the_private_file(tmp_path):
    """R2-4: the exporter's sentence is a class in the row; its text, and a crash's, are in the private file (0600) only."""
    work = folder(tmp_path)
    run = run_of(work, tmp_path)
    stage = work.path / 'stage'
    stage.mkdir()
    python = fake_exporter(tmp_path, 'echo "The seismic cube “Syn Cube” holds 1250 traces." >&2; exit 2')
    assert run.step('C', 'exporter-alone', {'python': python, 'root': '.', 'survey': 'S', 'stage': str(stage), 'objects': {}, 'timeout': 30})[0] == 'refused'
    assert run.step('C', 'no-such-step', {})[0] == 'crash'
    assert [{k: r[k] for k in ('step', 'outcome', 'class')} for r in run.rows] == [
        {'step': 'exporter-alone', 'outcome': 'refused', 'class': 'exporter refused'}, {'step': 'no-such-step', 'outcome': 'crash', 'class': 'crash'}]
    private = tmp_path / 'record.json.private'
    assert stat.S_IMODE(private.stat().st_mode) == 0o600 and 'no step no-such-step' in private.read_text() and 'Syn Cube' in private.read_text()
    assert 'Syn Cube' not in json.dumps(run.rows)
    assert work.close()


def gone(pid):
    try: return open('/proc/%d/stat' % pid).read().rsplit(')', 1)[1].split()[0] == 'Z'
    except OSError: return True


def test_a_timeout_and_a_grandchild_without_the_mark_leave_no_process(tmp_path):
    """R1-13/R2-5/R2-11: a step past its timeout is killed with its group; a grandchild in a session of its own whose
    environment lost the run's mark (as `_notebook` drops OPHIOLITE_*) is still found by TMPDIR and stopped.
    Mutation: drop the TMPDIR mark from `survivors` (the grandchild outlives the run)."""
    work = folder(tmp_path)
    run = run_of(work, tmp_path)
    stage = work.path / 'stage'
    stage.mkdir()
    python = fake_exporter(tmp_path, 'sleep 60')
    assert run.step('C', 'exporter-alone', {'python': python, 'root': '.', 'survey': 'S', 'stage': str(stage), 'objects': {}, 'timeout': 30}, timeout=2) == ('crash', None)
    assert run.rows[-1]['class'] == 'timeout'
    env = {k: v for k, v in run.env.items() if not k.startswith('OPHIOLITE_')}
    pid_file = work.path / 'tmp' / 'grandchild'
    subprocess.run([sys.executable, '-c', 'import subprocess, sys; p = subprocess.Popen(["sleep", "60"], start_new_session=True, cwd="/"); '
                    'open(sys.argv[1], "w").write(str(p.pid))', str(pid_file)], env=env, check=True)
    pid = int(pid_file.read_text())
    assert pid in lp.survivors(work)
    assert lp.stop_survivors(work) and gone(pid)
    assert work.close() and lp.survivors(work) == []


# --- R2-8: one synthetic journey ---------------------------------------------------------------------------------

def osd(tmp_path, records):
    root = tmp_path / 'osd'
    (root / 'build/catalog').mkdir(parents=True)
    (root / 'build/verification').mkdir()
    (root / 'build/catalog/records.json').write_text(json.dumps({'catalog': {'source_commit': None, 'verification_commit': None, 'built_at': '2026-11-02T00:00:00Z',
                                                                            'records_digest': 'd' * 64}, 'records': records}))
    return root


RECORD = {'id': 'ophiolite-synthetic/survey', 'title': 'A synthetic survey', 'origin': {'url': 'https://data.example.org/synthetic'},
          'licence': {'name': 'Apache License 2.0', 'spdx': 'Apache-2.0', 'url': 'https://www.apache.org/licenses/LICENSE-2.0', 'redistribution': 'allowed', 'attribution': 'required'}}


def journey(tmp_path, monkeypatch, service, survey, kinds, targets, token=None, first=(), **edits):  # noqa: F811
    lt = lp._module('live_target')
    from test_roundtrip_oracle import loopback_build
    monkeypatch.setitem(lp.PACKS, 'T', {'kinds': kinds, 'form': 'filtered', 'targets': targets})
    for name, value in edits.items(): monkeypatch.setattr(lp, name, value)
    src = tmp_path / 'syn-survey.zip'
    src.write_bytes(zipped())
    volume = tmp_path / 'volume'
    volume.mkdir()
    env = {**os.environ, **exporter_env(), 'FAKE_ODBIND_STATE': str(tmp_path / 'odbind-state.pickle')}
    env['PYTHONPATH'] = os.pathsep.join([*map(str, first), env['PYTHONPATH'], *sys.path])  # FIRST: a test's own modules ahead
    build = loopback_build(service, survey, [])
    def built(work, origin):
        from ophiolite import Credential
        project = build(work, origin)
        if token: project.credential = Credential.bearer(token)
        return project
    target = lt.LiveTarget(built, {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21}, version='test', host='synthetic', lifespan='off')
    fields, run = lp.pack_run('T', rid=RECORD['id'], deposit=src, volume=volume, python=sys.executable, env=env, osd=osd(tmp_path, [RECORD]), target=target,
                              forbidden=[tmp_path / 'forbidden'])
    return fields, json.loads(lp.record(fields, run.secrets)), volume


def steps(printed): return [(r['branch'], r['step'], r['outcome'], r.get('class')) for r in printed['branches']]


def test_a_synthetic_pack_goes_through_the_chain_on_stand_in_evidence(tmp_path, monkeypatch, service, survey):  # noqa: F811
    """R2-8: A refuses on OSD's own evidence (no verification), C exports, builds, places, runs the notebook and is
    refused at finalise (no derived custody), starter.json unchanged; every expected object has one disposition."""
    fields, printed, volume = journey(tmp_path, monkeypatch, service, survey, ('seismic-3d', 'well'), ['opendtect', 'python'])
    assert steps(printed) == [('A', 'evidence', 'refused', 'no verification of the record'),
                              ('C', 'exporter-alone', 'done', None), ('C', 'exporter-alone', 'done', None), ('C', 'export', 'done', None), ('C', 'build', 'done', None),
                              ('C', 'opendtect', 'done', None), ('C', 'python', 'done', None), ('C', 'finalise', 'refused', 'no derived custody; starter.json unchanged')]
    assert fields['checks'] == {'deposit_unchanged': True, 'no_processes': True, 'work_folder_removed': True} and os.listdir(volume) == []
    assert [{k: d.get(k) for k in ('kind', 'file', 'curve', 'state', 'class', 'differences')} for d in json.loads(json.dumps(fields['dispositions']))] == [
        {'kind': 'seismic-3d', 'file': 'seismic/Syn.sgy', 'curve': None, 'state': 'placed', 'class': None, 'differences': 0},
        {'kind': 'tops', 'file': 'wells/SYN-A-tops.csv', 'curve': None, 'state': 'placed', 'class': None, 'differences': 0},
        {'kind': 'wellbore-logs', 'file': 'wells/SYN-A.las', 'curve': 'curve 1', 'state': 'not placed', 'class': 'already in the survey', 'differences': None},
        {'kind': 'wellbore-logs', 'file': 'wells/SYN-A.las', 'curve': 'curve 2', 'state': 'not placed', 'class': 'already in the survey', 'differences': None},
        {'kind': 'wellbore-paths', 'file': None, 'curve': None, 'state': 'not placed', 'class': 'well path imported by hand', 'differences': None},
        {'kind': 'seismic-3d', 'file': None, 'curve': None, 'state': 'not placed', 'class': 'not in the contents', 'differences': None},
        {'kind': 'horizons', 'file': None, 'curve': None, 'state': 'not placed', 'class': 'not in the contents', 'differences': None}]
    assert 'unclassified' not in json.dumps(printed)  # every sentence met had a class
    assert fields['counts']['differences'] == 0


def test_an_export_refusal_leaves_every_later_step_not_reached(tmp_path, monkeypatch, service, survey):  # noqa: F811
    """R1-7/R2-8: a decision the survey contradicts refuses the export; build, opendtect and finalise are `not reached`."""
    _, printed, _ = journey(tmp_path, monkeypatch, service, survey, ('well',), ['opendtect'], WELL_DECLARED={**lp.WELL_DECLARED, 'units': 'ft'})
    assert steps(printed)[-4:] == [('C', 'export', 'refused', 'decision contradicted by the survey'), ('C', 'build', 'not reached: export refused', None),
                                   ('C', 'opendtect', 'not reached: export refused', None), ('C', 'finalise', 'not reached: export refused', None)]


def test_a_build_refusal_leaves_the_targets_not_reached(tmp_path, monkeypatch, service, survey):  # noqa: F811
    """R2-8: the gateway refuses the build's upload (the run's credential reads only); opendtect and finalise are
    `not reached`, and the run still cleans up."""
    fields, printed, _ = journey(tmp_path, monkeypatch, service, survey, ('seismic-3d',), ['opendtect'], token='oph_api_alice:read')
    assert steps(printed)[-3:] == [('C', 'build', 'refused', 'access refused'), ('C', 'opendtect', 'not reached: build refused', None),
                                   ('C', 'finalise', 'not reached: build refused', None)]
    assert fields['checks'] == {'deposit_unchanged': True, 'no_processes': True, 'work_folder_removed': True}


SLOW_NOTEBOOK = """import os, time
if os.path.exists('open-a-starter-pack.py'): time.sleep(60)  # the notebook's own process outlasts the target's timeout
"""


def test_a_notebook_past_its_timeout_leaves_no_process(tmp_path, monkeypatch, service, survey):  # noqa: F811
    """R2-11: the Python target with a one-second timeout is refused as a timeout; no process of the run survives.
    Item 232: the notebook sleeps 60 s at start (a sitecustomize ahead on its path), so a fast runner cannot finish it
    inside the timeout."""
    slow = tmp_path / 'slow-notebook'
    slow.mkdir()
    (slow / 'sitecustomize.py').write_text(SLOW_NOTEBOOK)
    fields, printed, _ = journey(tmp_path, monkeypatch, service, survey, ('seismic-3d',), ['opendtect', 'python'], first=[slow], TARGET_TIMEOUT=1)
    assert steps(printed)[-2:] == [('C', 'python', 'refused', 'timeout'), ('C', 'finalise', 'not reached: python refused', None)]
    assert fields['checks'] == {'deposit_unchanged': True, 'no_processes': True, 'work_folder_removed': True}


def test_a_connector_refusal_keeps_its_details_privately_and_out_of_the_record(tmp_path, monkeypatch, service, survey):  # noqa: F811
    """E137 s6a C3 (D-3): the import stops writing the cube in its own process; the refusal's details (odbind's error)
    reach the private file through the import's JSON line, the SDK and the worker, and the record prints the class only."""
    import pickle
    marker = 'odbind stopped: synthetic marker zebra'
    (tmp_path / 'odbind-state.pickle').write_bytes(pickle.dumps({'cubes': {}, 'horizons': {}, 'person': {'put_fails': marker}}))
    kept, keep = [], lp.Run.keep
    def keeping(self, step, text):
        kept.append((step, text))
        keep(self, step, text)
    monkeypatch.setattr(lp.Run, 'keep', keeping)
    fields, printed, _ = journey(tmp_path, monkeypatch, service, survey, ('seismic-3d',), ['opendtect'])
    assert steps(printed)[-2:] == [('C', 'opendtect', 'refused', 'opendtect stopped while writing'), ('C', 'finalise', 'not reached: opendtect refused', None)]
    details = [json.loads(text)['details'] for step, text in kept if step == 'opendtect' and text.startswith('{')]
    assert details == [{'error': 'RuntimeError: ' + marker}]
    assert marker not in json.dumps(printed) and marker not in json.dumps(fields, default=str)
    assert fields['checks'] == {'deposit_unchanged': True, 'no_processes': True, 'work_folder_removed': True}


def test_a_log_comparison_keeps_its_samples_privately_and_prints_counts_only(tmp_path, monkeypatch):
    """E137 s6a C4 (D-5): the opendtect step's result names the samples that differ; the worker keeps the whole result
    in the private side file (0600) and its row value carries counts per (kind, file, curve) only."""
    from ophiolite import starter
    sample = {'category': 'values', 'index': 0, 'given': 45.25, 'stored': 45.75}
    entry = {'kind': 'wellbore-logs', 'file': 'wells/SYN-A.las', 'object': 'SYN-A', 'curve': 'GR', 'values': 5, 'differences': 1, 'samples': [sample]}
    result = {'placed': [], 'compared': [entry], 'not_placed': [], 'differences': 1}
    monkeypatch.setattr(starter, 'opendtect', lambda *a, **kw: ({}, result))
    monkeypatch.setattr(lp, '_client', lambda a: None)
    args = tmp_path / '1-opendtect.json'
    args.write_text(json.dumps({'out': 'pack', 'survey': 'S', 'python': 'p', 'timeout': 30}))
    assert lp.worker('opendtect', str(args)) == 0
    side = args.with_suffix('.private.json')
    assert stat.S_IMODE(side.stat().st_mode) == 0o600 and json.loads(side.read_text())['result']['compared'][0]['samples'] == [sample]
    done = json.loads(args.with_suffix('.result.json').read_text())
    assert done['outcome'] == 'done' and done['value']['rows'] == [
        {'kind': 'wellbore-logs', 'file': 'wells/SYN-A.las', 'curve': 'GR', 'values': 5, 'differences': 1, 'how': 'compared'}]
    assert '45.75' not in json.dumps(done)
