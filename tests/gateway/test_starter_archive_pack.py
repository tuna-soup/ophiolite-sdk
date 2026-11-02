"""E129 sc C1 (strategy rev 3, D1-D4, D6's build half; acceptance A1 and A2 for the built pack): `ophiolite starter
build DEFINITION --export OUT` lands the derived files of sb's export of the synthetic survey archive.

The export is the real one (`ophiolite_opendtect.export` on the fake odbind of `ophiolite-opendtect/tests/fake_odbind`,
in its own process, as test_starter_export runs it), for a time survey and for a depth/metre survey. The project's
intake is the Connectors' own: each uploaded file is detected by `detect.detect` and read by the real reader of its
profile (`typed_reader.read_typed` for segy/1, points-csv/1 and well-path-positions-csv/1; `las_reader` for las2/1)
with the declarations the upload carried, so a file or a declaration the intake would refuse is not landed. Nothing of
the starter fake's manufactured upload results is used. Every expected value is a literal counted by hand from the sb
fixture's formulas. `osd validate` on these packs is in the Platform suite
(ophiolite-platform/services/project_gateway/tests/test_starter_archive_osd.py, which imports the helpers here), since
it skips without an OSD checkout and this gateway lane fails on any skip. A gateway module: it reads the connector and
the fixtures from the monorepo, above the SDK tree."""
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ophiolite import fidelity, starter, starter_archive as sa
from ophiolite.errors import PermissionRefused, Refused
from ophiolite.upload_runs import Report, UploadRuns
from test_starter_build import COUNTS, failing, landed_entry, result, rule_h, ARCHIVE as ZIP, CUBE, LAS
from test_starter_export import ARCHIVE, FAKE, CONNECTOR, PACK, RID, ROOT, decisions, made, run, sha

pytest.importorskip('numpy')
pytest.importorskip('pyproj')
pytest.importorskip('lasio')
from asset_connectors import detect, las_reader, typed_reader  # noqa: E402 (the Connectors' intake readers)

HOST = ROOT / 'ophiolite-opendtect/src/ophiolite_opendtect/data/host.json'
FIDELITY = 'fidelity/ophiolite-synthetic__survey__starter.json'
TIME = ['seismic/Syn.sgy', 'seismic/Syn2.sgy', 'horizons/Top.csv', 'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
DEPTH = ['horizons/Top.csv', 'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
KIND = {'seismic': 'seismic-3d', 'horizons': 'horizons', 'wells': 'wellbore-paths'}
CRS = 'EPSG:32631'
DECLARED = {  # D4, per derived file, from the export's survey (EPSG:32631, xy m, depth m) and its Z domain
    'time': {'segy/1': {'crs': CRS, 'z_domain': 'time'},
             'points-csv/1': {'crs': CRS, 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 'ms', 'positive': 'down'}},
    'depth': {'points-csv/1': {'crs': CRS, 'xy_unit': 'm', 'z_meaning': 'depth', 'z_unit': 'm', 'positive': 'down'}}}
PATH_DECLARED = {'crs': CRS, 'xy_unit': 'm', 'depth_unit': 'm', 'tvdss_datum': 'MSL', 'md_reference': 'KB'}  # E129 (f) Q6: from OpendTect's KB
MADE = ['targets/opendtect/import.py', 'ATTRIBUTION.md']
ARTEFACTS = MADE + TIME  # C3b (OSD custody caveat): each derived file is also the artefact at its one path, under files/


def kind_of(path):
    return 'wellbore-logs' if path.endswith('.las') else KIND[path.split('/')[0]]


# --- the project, with the Connectors' intake -------------------------------------------------------------------------

def intake(profile, raw, declared):
    """What the intake reads of RAW as PROFILE with DECLARED: (context, curves) where curves is [(mnemonic, unit, depths,
    values)] for a LAS file and None otherwise. A refusal raises the reader's own error."""
    if profile == 'las2/1':
        if declared: raise typed_reader.TypedReadError('LAS files take no declarations.')
        las_reader.las_policy(raw)
        las_reader.las2_sections(raw.decode('utf-8'))
        las = las_reader.read_las(raw)
        depths = [float(v) for v in las.curves[0].data]
        curves = [(c.mnemonic, c.unit, depths, [None if math.isnan(v) else float(v) for v in c.data]) for c in las.curves[1:]]
        return {'type': 'well-log', 'curves': [c[0] for c in curves], 'samples': len(depths)}, curves
    context, _, _ = typed_reader.read_typed(profile, raw, declared)
    return context, None


class Intake:
    """One project: upload runs whose files are detected and read by the Connectors' readers before they land. `read`
    holds {file name: (profile, declared, context)} of every file the intake took; `taken` every file started."""
    url, project = 'https://gateway.example.org', 'p-archive'

    def __init__(self):
        self.runs, self.assets, self.taken, self.read = {}, {}, set(), {}
        self.provenance_reads = []  # (asset, revision) of every provenance read (C3)

    def start(self, body):
        (listed,) = body['files']
        assert listed['path'] not in self.taken, 'sent again: %s' % listed['path']
        self.taken.add(listed['path'])
        run = 'run-%d' % (len(self.runs) + 1)
        self.runs[run] = {'name': listed['path'], 'sha256': listed['sha256'], 'bytes': listed['bytes'], 'state': 'open', 'declared': None,
                          'row': None, 'profile': None, 'sentence': None}
        return {'run_id': run}

    def unfinished(self, folder):
        (f,) = folder.files
        return next((run for run, r in self.runs.items() if r['name'] == f.path and r['state'] == 'open'), None)

    def decide(self, run, ordinals, action, values):
        self.runs[run]['declared'] = {k: str(v) for k, v in values.items()}

    def send(self, run, folder):
        r = self.runs[run]
        if r['state'] == 'open':
            raw = folder.files[0].whole()
            entry = detect.detect(raw[:detect.HEAD], r['name'])
            r['profile'] = entry and entry['profile']
            if entry and entry['declared'] and r['declared'] is None: return self.status(run, needs=True)
            try: context, curves = intake(r['profile'], raw, r['declared'] or {})
            except (typed_reader.TypedReadError, las_reader.LASPolicyError, ValueError) as e:
                r.update(state='closed', sentence=str(e)); return self.status(run)
            self.read[r['name']] = (r['profile'], r['declared'], context)
            asset = 'item-' + r['name'].replace('.', '-')
            a = self.assets.setdefault(asset, {'name': r['name'], 'revisions': [], 'content': sha(raw), 'context': context, 'curves': curves,
                                               'profile': r['profile'], 'raw': raw, 'declared': r['declared'] or {}})
            a['revisions'].append('r%d' % (len(a['revisions']) + 1))
            r.update(state='closed', row={'asset_id': asset, 'revision': a['revisions'][-1]})
        return self.status(run)

    def status(self, run, needs=False):
        r = self.runs[run]
        state = 'needs-decision' if needs else 'added' if r['row'] else 'not-landed' if r['sentence'] else 'waiting'
        row = {'ordinal': 0, 'path': r['name'], 'bytes': r['bytes'], 'sha256': r['sha256'], 'role': 'primary', 'profile': r['profile'], 'state': state,
               'reason_code': 'needs-declarations' if needs else None, 'declared': r['declared'], 'sentence': r['sentence'], **(r['row'] or {})}
        counts = {k: 0 for k in COUNTS}
        counts[{'needs-decision': 'needs_decision', 'added': 'added', 'waiting': 'waiting', 'not-landed': 'not_read'}[state]] = 1
        return Report({'run_id': run, 'state': r['state'], 'label': 'Finished' if r['state'] == 'closed' else 'Open', 'folder_name': r['name'],
                       'files': 1, 'counts': counts, 'items': [row]})

    # the reads, as fidelity.landed calls them, of what the intake read
    def assets_(self):
        for asset, a in sorted(self.assets.items()):
            yield {'asset_id': asset, 'revision': a['revisions'][-1], 'curves': [c[0] for c in a['curves']] if a['curves'] else []}

    def provenance(self, asset, revision):
        self.provenance_reads.append((asset, revision))
        return NS(record={'content': {'content_sha256': self.assets[asset]['content']}})

    def describe(self, asset, revision, curve):
        return NS(interpretation=NS(reader='asset_connectors.las_reader/1'), scientific=NS(sample_count=self.assets[asset]['context']['samples']))

    def read_(self, asset, revision, curves):
        return NS(curves=[NS(curve=m, axis=depths, values=values, unit=unit) for m, unit, depths, values in self.assets[asset]['curves'] if m in curves])

    def read_data(self, asset, revision):
        a = self.assets[asset]; context = a['context']
        # E139 s2: a point set's points as the reader read them (the pack compares them with its file, S2-12)
        points = typed_reader.read_typed(a['profile'], a['raw'], a['declared'])[1]['points'] if context['type'] == 'point-set' else None
        return NS(type=context['type'], points=points, descriptor=NS(interpretation=NS(reader=typed_reader.interpretation(typed_reader.PROFILES[a['profile']])['reader'])))


@pytest.fixture
def project(monkeypatch):
    p = Intake()
    monkeypatch.setattr(UploadRuns, 'unfinished', lambda self, folder, declared=None: p.unfinished(folder))
    monkeypatch.setattr(UploadRuns, '_call', lambda self, op, body, model=None, retry=True: p.start(body) if op == 'start' else pytest.fail(op))
    monkeypatch.setattr(UploadRuns, 'decide', lambda self, run, ordinals, action, values=None: p.decide(run, ordinals, action, values))
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, folder, progress=None, passes=3: p.send(run, folder))
    monkeypatch.setattr(UploadRuns, 'status', lambda self, run: p.status(run))
    return p


def client(p, limits=None):
    """The project as the SDK client the pack reads it with; LIMITS, when given, is what its capabilities state (E139)."""
    return NS(url=p.url, project=p.project, assets=p.assets_, provenance=p.provenance, describe=p.describe, read=p.read_, read_data=p.read_data,
              **({'served_limits': lambda: limits} if limits is not None else {}))


def build(folder, export, p, pack='pack', limits=None):
    return starter.build(client(p, limits), folder / 'definition.json', folder / pack, catalogue=folder / 'records.json', verification=folder / 'verification',
                         custody=folder / 'custody', export=export)


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


# --- the exports ------------------------------------------------------------------------------------------------------

def depth(d):
    d['decisions'] = decisions(volume={'crs': CRS, 'domain': 'depth', 'units': 'm'})
    d['decisions'] += [{'topic': 'velocity', 'subject': x, 'value': 'none: the survey is in depth', 'source': 'data'} for x in ('Syn', 'Syn2', 'Top')]


@pytest.fixture(scope='module')
def exports(tmp_path_factory):
    """{survey: (definition folder, export OUT)} of one real export each, of a time and of a depth/metre survey."""
    out = {}
    for survey, edit, variant in (('time', None, None), ('depth', depth, 'depth')):
        folder, export = made(tmp_path_factory.mktemp('definition-' + survey), edit=edit), tmp_path_factory.mktemp('export-' + survey)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
            if variant: mp.setenv('FAKE_ODBIND_VARIANT', variant)
            else: mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
            run(folder, export)
        out[survey] = folder, export
    return out


def copied(exports, survey, tmp_path):
    """A copy of one export and its definition folder, for a test that changes them."""
    folder, export = exports[survey]
    shutil.copytree(folder, tmp_path / 'definition'); shutil.copytree(export, tmp_path / 'export')
    return tmp_path / 'definition', tmp_path / 'export'


def current(export):
    return export / json.loads((export / 'derived.json').read_text())['export']


def another(export, name, change=None):
    """A copy of the current export folder as exports/NAME, CHANGE(folder, report) applied, the pointer moved to it."""
    target = export / 'exports' / name
    shutil.copytree(current(export), target)
    report = json.loads((target / 'derived.json').read_text())
    if change: change(target, report)
    (target / 'derived.json').write_bytes(starter.dumped(report))
    (export / 'derived.json').write_text(json.dumps({'export': 'exports/' + name}))
    return target


def replaced_file(path, raw):
    """A change for `another`: the derived file PATH holds RAW, and the report says so."""
    def change(target, report):
        (target / 'files' / path).write_bytes(raw)
        d = next(d for d in report['derived'] if d['path'] == path)
        d.update(sha256=sha(raw), bytes=len(raw))
    return change


# --- A1: each derived file through the real readers -------------------------------------------------------------------

@pytest.mark.parametrize('survey', ['time', 'depth'])
def test_build_lands_each_derived_file_through_the_real_readers(exports, tmp_path, project, survey):
    folder, export = copied(exports, survey, tmp_path)
    doc = build(folder, export, project)
    paths = TIME if survey == 'time' else DEPTH
    report = json.loads((current(export) / 'derived.json').read_text())
    archive = sha((folder / 'inputs' / ARCHIVE).read_bytes())
    assert json.loads((folder / 'pack/starter.json').read_text()) == doc and doc['unpublished'] is True and doc['id'] == PACK
    assert [d['path'] for d in doc['derived']] == paths and doc['derived'] == report['derived'] and {d['from'] for d in doc['derived']} == {archive}
    assert 'outline.geojson' not in json.dumps(doc) and doc['inputs'] == [{'name': ARCHIVE, 'sha256': archive, 'bytes': (folder / 'inputs' / ARCHIVE).stat().st_size,
                                                                           'held': {'as': 'verified', 'verifier_run': {'checked_at': '2026-10-29T00:00:00Z', 'tool_version': '0.9.0'},
                                                                                    'path': 'data/' + ARCHIVE}}]
    # one landed entry per derived file, keyed on its path, carrying `from`; one row each, none for the archive or the outline
    landing = json.loads((folder / 'pack/landing.json').read_text())
    assert list(landing['inputs']) == paths
    assert [(e['state'], e['from'], e['profile'], e['output']['kind']) for e in landing['inputs'].values()] == [
        ('landed', archive, starter.EXPORT_PROFILE[kind_of(p)], kind_of(p)) for p in paths]
    fd = json.loads((folder / 'pack' / FIDELITY).read_text())
    assert [(i['name'], i['sha256'], i['result'], i['output']['kind']) for i in fd['inputs']] == [(d['path'], d['sha256'], 'converted', kind_of(d['path'])) for d in doc['derived']]
    assert archive not in {i['sha256'] for i in fd['inputs']} and fd['record'] == RID
    # what the real readers took, with D4's declarations
    names = {p: p.rsplit('/', 1)[1] for p in paths}
    assert sorted(project.read) == sorted(names.values())
    for p in paths:
        profile, declared, context = project.read[names[p]]
        assert profile == starter.EXPORT_PROFILE[kind_of(p)]
        want = PATH_DECLARED if kind_of(p) == 'wellbore-paths' else None if kind_of(p) == 'wellbore-logs' else DECLARED[survey][profile]
        assert declared == want, p
    if survey == 'time':
        for name, traces, interval, first in (('Syn.sgy', 16, 4.0, 100), ('Syn2.sgy', 4, 2.0, 102)):
            c = project.read[name][2]
            assert (c['type'], c['traces'], c['sample_interval'], c['first_sample'], c['z_domain'], c['crs'], c['sample_unit']) == ('seismic-volume', traces, interval, first, 'time', CRS, 'ms')
    c = project.read['Top.csv'][2]
    assert (c['type'], c['count'], c['missing_z_count'], c['attributes'], c['crs'], c['xy_unit'], c['positive']) == ('point-set', 16, 1, ['inline', 'crossline'], CRS, 'm', 'down')
    assert (c['z_meaning'], c['z_unit']) == (('time', 'ms') if survey == 'time' else ('depth', 'm'))
    for name, count, md in (('SYN-A-positions.csv', 4, [0.0, 180.0]), ('SYN-B-positions.csv', 3, [0.0, 100.0])):
        c = project.read[name][2]
        assert (c['type'], c['count'], c['md_range'], c['crs'], c['depth_unit'], c['tvdss_datum'], c['md_reference']) == ('well-path', count, md, CRS, 'm', 'MSL', 'KB')
    assert project.read['SYN-A.las'][2] == {'type': 'well-log', 'curves': ['DT', 'GR'], 'samples': 7}
    las = next(i for i in fd['inputs'] if i['name'] == 'wells/SYN-A.las')
    assert las['representative'] == [{'field': 'DT@100.15', 'value': 120.25, 'unit': 'us/ft'}, {'field': 'GR@100.15', 'value': 60.5, 'unit': 'API'},
                                     {'field': 'samples', 'value': 7, 'unit': None}]
    # D6's build half: the OpendTect target; the archive's log-step decision is the pack's (rule (e) subjects)
    (target,) = doc['targets']
    assert (target['application'], target['version'], target['import'], target['oracle']) == ('opendtect', '7.0.10', 'targets/opendtect/import.py', starter.ORACLE_OPENDTECT)
    assert [a['path'] for a in target['artefacts']] == MADE + paths and not any('key' in a for a in target['artefacts'])
    for a in target['artefacts']:
        raw = (folder / 'pack/files' / a['path']).read_bytes()
        assert (a['sha256'], a['bytes']) == (sha(raw), len(raw))
    # one path per derived file: derived[] and the artefact agree, and its bytes sit nowhere else in the pack
    assert [{k: a[k] for k in ('path', 'sha256', 'bytes')} for a in target['artefacts'][len(MADE):]] == [{k: d[k] for k in ('path', 'sha256', 'bytes')} for d in doc['derived']]
    every = [p for p in (folder / 'pack').rglob('*') if p.is_file()]
    for d in doc['derived']:
        assert [p.relative_to(folder / 'pack').as_posix() for p in every if sha(p.read_bytes()) == d['sha256']] == ['files/' + d['path']]
    assert [d for d in doc['decisions'] if d['subject'] == 'pack'] == [{'topic': 'units', 'subject': 'pack', 'value': '0.15', 'source': 'chosen', 'note': 'the log step in metres'}]
    assert not any(d['subject'] == ARCHIVE for d in doc['decisions'])
    starter.shaped(doc)
    assert starter.fidelity_of(doc, folder / 'pack') is None
    assert starter.complete(doc, starter.UNCHANGED)


def test_the_pinned_opendtect_release_is_the_connectors(tmp_path):
    assert json.loads(HOST.read_text())['opendtect']['release'] == starter.OPENDTECT_RELEASE == '7.0.10'


TOP_DECLARED = {'crs': CRS, 'xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 'ms', 'positive': 'down'}
PACK_FILES = {  # what import.py carries per file (C3): the report's kind and object, the declarations the build landed it with
    'seismic/Syn.sgy': {'kind': 'seismic-3d', 'object': 'Syn', 'declared': {'crs': CRS, 'z_domain': 'time'}},
    'seismic/Syn2.sgy': {'kind': 'seismic-3d', 'object': 'Syn2', 'declared': {'crs': CRS, 'z_domain': 'time'}},
    'horizons/Top.csv': {'kind': 'horizons', 'object': 'Top', 'declared': TOP_DECLARED},
    'wells/SYN-A-positions.csv': {'kind': 'wellbore-paths', 'object': 'SYN-A', 'declared': PATH_DECLARED},
    'wells/SYN-A.las': {'kind': 'wellbore-logs', 'object': 'SYN-A', 'declared': {}},
    'wells/SYN-B-positions.csv': {'kind': 'wellbore-paths', 'object': 'SYN-B', 'declared': PATH_DECLARED}}
NOT_READ = [{'kind': 'wellbore-logs', 'name': 'SYN-B', 'reason': 'the well has no logs'}]


def test_the_import_artefact_launches_the_installed_connector_with_the_packs_files(exports, tmp_path, project):
    """C3 replaces C1's placeholder: import.py carries the pack's id, files and the export's not_read entries and calls
    the installed connector; without it, it says which Python to use and places nothing. The derived files are in the
    pack folder at their paths, where the import reads them."""
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    script = folder / 'pack/files/targets/opendtect/import.py'
    carried = {'__name__': 'the_pack_import'}
    exec(compile(script.read_text(), str(script), 'exec'), carried)
    assert (carried['PACK'], carried['FILES'], carried['NOT_READ']) == (PACK, PACK_FILES, NOT_READ)
    assert 'from ophiolite_opendtect import starter_import' in script.read_text() and 'starter_import.main(sys.argv[1:], pack=PACK, files=FILES, not_read=NOT_READ)' in script.read_text()
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and done.stderr.strip() == starter.NO_CONNECTOR == \
        'Run this import with the Python the OpendTect connector (ophiolite-opendtect) is installed in; nothing was placed.'
    for path in TIME:
        assert (folder / 'pack/files' / path).read_bytes() == (current(export) / 'files' / path).read_bytes()
        assert not (folder / 'pack' / path).exists()  # C3b: never a second copy outside files/


# --- A1: B5, a horizon over 100,000 nodes ----------------------------------------------------------------------------

def grid_csv(inlines, crosslines):
    """A synthetic points-csv/1 horizon on a regular grid: x 500000 + 25 c, y 25 i, z 1000 + i + c / 4."""
    rows = ['x,y,z,inline,crossline'] + ['%d.00,%d.00,%r,%d,%d' % (500000 + 25 * c, 25 * i, 1000 + i + c / 4, i, c) for i in range(inlines) for c in range(crosslines)]
    return ''.join(r + '\n' for r in rows).encode('ascii')


def test_a_horizon_over_100000_nodes_is_a_failed_row_and_is_not_uploaded(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    big = grid_csv(317, 317)  # 100,489 nodes
    with pytest.raises(typed_reader.TypedReadError) as caught: typed_reader.read_typed('points-csv/1', big, DECLARED['time']['points-csv/1'])
    assert str(caught.value) == 'This horizon has 100489 nodes; this deployment accepts at most 100000. Nothing was added.' and starter.MAX_NODES == typed_reader.MAX_POINTS == 100000
    another(export, 'big-1', replaced_file('horizons/Top.csv', big))
    doc = build(folder, export, project)
    fd = json.loads((folder / 'pack' / FIDELITY).read_text())
    assert [i for i in fd['inputs'] if i['name'] == 'horizons/Top.csv'] == [
        {'sha256': sha(big), 'name': 'horizons/Top.csv', 'result': 'failed', 'reason': 'This horizon has more nodes than Ophiolite takes (100,000).'}]
    assert 'Top.csv' not in project.taken and 'horizons/Top.csv' not in json.loads((folder / 'pack/landing.json').read_text())['inputs']
    assert sorted(project.taken) == ['SYN-A-positions.csv', 'SYN-A.las', 'SYN-B-positions.csv', 'Syn.sgy', 'Syn2.sgy']
    assert [d['path'] for d in doc['derived']] == TIME and starter.fidelity_of(doc, folder / 'pack') is None


def test_a_horizon_of_exactly_100000_nodes_lands(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    edge = grid_csv(250, 400)
    another(export, 'edge-1', replaced_file('horizons/Top.csv', edge))
    build(folder, export, project)
    assert project.read['Top.csv'][2]['count'] == 100000
    fd = json.loads((folder / 'pack' / FIDELITY).read_text())
    assert next(i for i in fd['inputs'] if i['name'] == 'horizons/Top.csv')['result'] == 'converted'


# --- E139 s2 (S2-7, S2-12): the deployment's M, and the read-back compared with the file ---------------------------------
# The two tests above are a client that states no horizon_nodes (MAX_NODES, 100,000, as before E139). Here the deployment
# states M = 16, not the default; horizons of M-1, M and M+1 nodes. Mutation: build comparing with MAX_NODES (17 lands),
# the sentence without the number (it names 100,000), or `>=` for `>` (16 fails).

@pytest.mark.parametrize('grid, nodes', [((3, 5), 15), ((4, 4), 16), ((1, 17), 17)])
def test_a_horizon_is_landed_up_to_the_deployments_m_and_over_it_is_a_failed_row_naming_m(exports, tmp_path, project, grid, nodes):
    folder, export = copied(exports, 'time', tmp_path)
    another(export, 'm-1', replaced_file('horizons/Top.csv', grid_csv(*grid)))
    build(folder, export, project, limits={'upload_bytes': 1, 'file_bytes': 1, 'horizon_nodes': 16})
    row = next(i for i in json.loads((folder / 'pack' / FIDELITY).read_text())['inputs'] if i['name'] == 'horizons/Top.csv')
    others = ['SYN-A-positions.csv', 'SYN-A.las', 'SYN-B-positions.csv', 'Syn.sgy', 'Syn2.sgy']
    if nodes > 16:
        assert row['result'] == 'failed' and row['reason'] == 'This horizon has more nodes than Ophiolite takes (16).'
        assert sorted(project.taken) == others and 'horizons/Top.csv' not in json.loads((folder / 'pack/landing.json').read_text())['inputs']
    else:
        assert row['result'] == 'converted' and project.read['Top.csv'][2]['count'] == nodes and sorted(project.taken) == sorted(others + ['Top.csv'])


def test_the_too_many_sentence_names_the_number_it_was_compared_with():
    assert starter.TOO_MANY_NODES.format(starter.MAX_NODES) == 'This horizon has more nodes than Ophiolite takes (100,000).'
    assert starter.TOO_MANY_NODES.format(1_000_000) == 'This horizon has more nodes than Ophiolite takes (1,000,000).'
    assert starter.horizon_nodes(NS(served_limits=lambda: {'horizon_nodes': 250_000})) == 250_000
    assert starter.horizon_nodes(NS(served_limits=lambda: {'upload_bytes': 1})) == starter.horizon_nodes(NS()) == 100_000


def test_a_landed_horizon_records_its_read_back_compared_with_its_file_in_order(exports, tmp_path, project):
    """S2-12: the first and last Z and the comparison are the Top row's representative values (Top: 16 nodes, z 1000 + i
    + c / 4 at inline i, crossline c, as grid_csv writes it). Mutation: the comparison taken from the read itself."""
    folder, export = copied(exports, 'time', tmp_path)
    another(export, 'rb-1', replaced_file('horizons/Top.csv', grid_csv(4, 4)))
    build(folder, export, project)
    row = next(i for i in json.loads((folder / 'pack' / FIDELITY).read_text())['inputs'] if i['name'] == 'horizons/Top.csv')
    assert row['representative'] == [{'field': 'Z of node 1', 'value': 1000.0, 'unit': 'ms'}, {'field': 'Z of node 16', 'value': 1003.75, 'unit': 'ms'},
                                     {'field': 'nodes compared with the file in order (the first, the last, and from node 1)', 'value': '16 of 16 equal', 'unit': None}]


@pytest.mark.parametrize('change', ['one value', 'the order', 'one node fewer'])
def test_a_horizon_that_reads_back_otherwise_refuses_and_writes_no_pack(exports, tmp_path, project, monkeypatch, change):
    folder, export = copied(exports, 'time', tmp_path)
    another(export, 'rb-2', replaced_file('horizons/Top.csv', grid_csv(4, 4)))
    real = Intake.read_data
    def served(self, asset, revision):
        read = real(self, asset, revision)
        if read.points is not None:
            p = [list(q) for q in read.points]
            if change == 'one value': p[9][2] += 0.25
            elif change == 'the order': p[3], p[4] = p[4], p[3]
            else: p = p[:-1]
            read.points = p
        return read
    monkeypatch.setattr(Intake, 'read_data', served)
    node = {'one value': 10, 'the order': 4, 'one node fewer': 16}[change]
    assert refused(build, folder, export, project) == 'horizons/Top.csv reads back from Ophiolite with another value than its file at node %d.' % node + starter.NOT_WRITTEN
    assert not (folder / 'pack/starter.json').exists() and not (folder / 'pack' / FIDELITY).exists()


@pytest.mark.parametrize('results, sentence', [
    ([{'sha256': CUBE, 'name': 'Syn.sgy', 'result': 'failed', 'reason': 'This horizon has more nodes than Ophiolite takes (100,000).'}, result(LAS, 'SYN-A.las', 'wellbore-logs')], None),
    ([{'sha256': ZIP, 'name': 'survey.zip', 'result': 'failed', 'reason': 'Not added.'}], 'fidelity fidelity/x.json: input survey.zip is failed.'),
    ([{'sha256': CUBE, 'name': 'Syn.sgy', 'result': 'skipped'}, result(LAS, 'SYN-A.las', 'wellbore-logs')], 'fidelity fidelity/x.json: input Syn.sgy is skipped.'),
], ids=['a-derived-file-failed-with-its-reason', 'a-pack-input-failed', 'a-derived-file-skipped'])
def test_rule_h_takes_a_failed_derived_file_and_nothing_else(tmp_path, results, sentence):
    assert rule_h(tmp_path, results) == (None if sentence is None else sentence + starter.UNCHANGED)


# --- A1: mutations, each refused with nothing landed -----------------------------------------------------------------

def nothing_landed(folder, project):
    assert project.taken == set() and not (folder / 'pack/landing.json').exists() and not (folder / 'pack/starter.json').exists()


def test_a_changed_derived_byte_refuses_naming_it(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    p = current(export) / 'files/wells/SYN-B-positions.csv'
    p.write_bytes(p.read_bytes().replace(b'89.75', b'89.76'))
    assert refused(build, folder, export, project) == 'wells/SYN-B-positions.csv in the export at %s is not the file its report names: its SHA-256 differs.' % export + starter.NOT_WRITTEN
    nothing_landed(folder, project)


def test_an_absent_derived_file_refuses_naming_it(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    (current(export) / 'files/horizons/Top.csv').unlink()
    assert refused(build, folder, export, project) == 'horizons/Top.csv is missing from the export at %s.' % export + starter.NOT_WRITTEN
    nothing_landed(folder, project)


SENTENCE = 'The export at %s is not of this definition and archive; run ophiolite starter export again.'
REPORTS = {
    'another definition': lambda folder, export: made(folder, edit=lambda d: d.update(title='Another definition')),
    'another archive': lambda folder, export: another(export, 'other-archive-1', lambda t, r: r['archive'].update(sha256='0' * 64)),
    'another record': lambda folder, export: another(export, 'other-record-1', lambda t, r: r.update(record_id='ophiolite-synthetic/other')),
    'another format': lambda folder, export: another(export, 'other-format-1', lambda t, r: r.update(format='ophiolite.starter-export/2')),
    'the outline as a derived file': lambda folder, export: another(export, 'outline-1', lambda t, r: r['derived'].append(
        {'path': 'outline.geojson', 'sha256': sha((t / 'files/outline.geojson').read_bytes()), 'bytes': (t / 'files/outline.geojson').stat().st_size,
         'from': r['archive']['sha256'], 'how': 'the outline'})),
    'a pointer outside exports': lambda folder, export: (export / 'derived.json').write_text(json.dumps({'export': '../elsewhere'})),
    'a pointer with more': lambda folder, export: (export / 'derived.json').write_text(json.dumps({'export': json.loads((export / 'derived.json').read_text())['export'], 'more': 1})),
    'no pointer': lambda folder, export: (export / 'derived.json').unlink(),
}


@pytest.mark.parametrize('case', sorted(REPORTS))
def test_a_report_of_another_definition_or_archive_refuses(exports, tmp_path, project, case):
    folder, export = copied(exports, 'time', tmp_path)
    REPORTS[case](folder, export)
    assert refused(build, folder, export, project) == SENTENCE % export + starter.NOT_WRITTEN
    nothing_landed(folder, project)


def test_a_definition_without_export_and_an_export_without_archive_refuse(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    assert refused(build, folder, None, project) == starter.ARCHIVE_NEEDS_EXPORT + starter.NOTHING_SENT
    nothing_landed(folder, project)


def test_a_survey_in_another_z_unit_refuses_before_landing(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    another(export, 'seconds-1', lambda t, r: r['survey'].update(zunit='s'))
    made(folder, edit=lambda d: [x.update(value='s') for x in d['decisions'] if x['topic'] == 'units' and x['subject'] in ('Syn', 'Syn2', 'Top')])
    # the definition changed, so the report (made of the old one) is refused first; with the report re-bound the domain refuses
    bound = sha((folder / 'definition.json').read_bytes())
    report = json.loads((current(export) / 'derived.json').read_text()); report['definition'] = bound
    (current(export) / 'derived.json').write_bytes(starter.dumped(report))
    assert refused(build, folder, export, project) == "The export's survey is in twt s; horizons and cubes are landed in time (ms) or depth (m) only." + starter.NOT_WRITTEN
    nothing_landed(folder, project)


# --- A1 / D3: the export bound by content across an interrupted build ------------------------------------------------

def interrupted(exports, tmp_path, project, monkeypatch):
    folder, export = copied(exports, 'time', tmp_path)
    fired = failing(monkeypatch, landed_entry('seismic/Syn2.sgy'))
    with pytest.raises(OSError): build(folder, export, project)
    assert fired and json.loads((folder / 'pack/landing.json').read_text())['bindings']['export']['derived'][2][0] == 'horizons/Top.csv'
    monkeypatch.undo()
    return folder, export


def rebound(project, monkeypatch):
    """The project fixture's patches again (undone with the failing write)."""
    monkeypatch.setattr(UploadRuns, 'unfinished', lambda self, folder, declared=None: project.unfinished(folder))
    monkeypatch.setattr(UploadRuns, '_call', lambda self, op, body, model=None, retry=True: project.start(body) if op == 'start' else pytest.fail(op))
    monkeypatch.setattr(UploadRuns, 'decide', lambda self, run, ordinals, action, values=None: project.decide(run, ordinals, action, values))
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, folder, progress=None, passes=3: project.send(run, folder))
    monkeypatch.setattr(UploadRuns, 'status', lambda self, run: project.status(run))


CHANGES = {
    'the report': lambda t, r: r['not_read'][0].update(reason='another reason'),
    'the inventory': replaced_file('horizons/Top.csv', None),
}


@pytest.mark.parametrize('case', ['the report', 'the inventory'])
def test_a_resume_after_the_export_changed_with_the_same_paths_refuses(exports, tmp_path, project, monkeypatch, case):
    folder, export = interrupted(exports, tmp_path, project, monkeypatch)
    rebound(project, monkeypatch)
    if case == 'the report': change = CHANGES[case]
    else:
        raw = (current(export) / 'files/horizons/Top.csv').read_bytes().replace(b',105.0,10,20', b',105.5,10,20')
        change = replaced_file('horizons/Top.csv', raw)
    before = (folder / 'pack/landing.json').read_bytes()
    another(export, 'changed-1', change)
    assert refused(build, folder, export, project) == starter.BINDING % 'The export' + starter.NOT_WRITTEN
    assert (folder / 'pack/landing.json').read_bytes() == before and sorted(project.taken) == ['Syn.sgy', 'Syn2.sgy']


def test_an_equivalent_export_in_another_folder_continues_to_the_same_bytes(exports, tmp_path, project, monkeypatch):
    (tmp_path / 'whole').mkdir(); (tmp_path / 'cut').mkdir()
    folder, export = copied(exports, 'time', tmp_path / 'whole')
    build(folder, export, project)
    expected = {p: (folder / 'pack' / p).read_bytes() for p in ('starter.json', FIDELITY)}
    project.__init__()
    folder, export = interrupted(exports, tmp_path / 'cut', project, monkeypatch)
    rebound(project, monkeypatch)
    another(export, 'equivalent-1')
    build(folder, export, project)
    assert {p: (folder / 'pack' / p).read_bytes() for p in expected} == expected
    assert sorted(project.taken) == sorted(p.rsplit('/', 1)[1] for p in TIME)


# --- one path per derived file (OSD custody caveat; osd validate's own check is in the Platform suite) ---------------

def test_a_derived_file_at_a_second_path_is_refused_by_build_and_by_finalise(exports, tmp_path, project, odbind):
    """C3b (OSD custody caveat: one custody document per digest): the same bytes never sit at two paths of a pack. An
    export naming the horizon's bytes at a second path is refused by build before anything is sent; a built pack edited
    to carry them at a second artefact path is refused by finalise."""
    folder, export = copied(exports, 'time', tmp_path / 'export')

    def twice(target, report):
        shutil.copyfile(target / 'files/horizons/Top.csv', target / 'files/horizons/Top-copy.csv')
        report['files'].append({**next(f for f in report['files'] if f['path'] == 'horizons/Top.csv'), 'path': 'horizons/Top-copy.csv'})
        report['derived'].append({**next(d for d in report['derived'] if d['path'] == 'horizons/Top.csv'), 'path': 'horizons/Top-copy.csv'})
    another(export, 'twice', twice)
    assert refused(build, folder, export, project) == (
        'The derived file horizons/Top-copy.csv has the same bytes as horizons/Top.csv; a file has one path in a pack (the mirror holds one copy '
        'per SHA-256). Nothing was written.')
    assert project.read == {} and not (folder / 'pack/starter.json').exists()

    folder, export = copied(exports, 'time', tmp_path / 'pack')
    build(folder, export, project)
    qualified(folder, survey_at(tmp_path / 'pack'), project)
    document = folder / 'pack/starter.json'
    doc = json.loads(document.read_text())
    top = next(d for d in doc['derived'] if d['path'] == 'horizons/Top.csv')
    shutil.copyfile(folder / 'pack/files/horizons/Top.csv', folder / 'pack/files/targets/opendtect/Top-copy.csv')
    doc['targets'][0]['artefacts'].append({'path': 'targets/opendtect/Top-copy.csv', 'sha256': top['sha256'], 'bytes': top['bytes']})
    edited = starter.dumped(doc)
    document.write_bytes(edited)
    # finalise refuses it with the custody documents held and leaves starter.json as it was (osd validate refuses it too
    # since OSD H7: test_starter_archive_osd.py)
    derive(folder)
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == (
        'targets/opendtect/Top-copy.csv has the same bytes as horizons/Top.csv; an artefact must be made, not copied.' + starter.UNCHANGED)
    assert document.read_bytes() == edited


# --- C3 (D6-D8): the import from pack files and the qualification; A4, A6 and A2 after import and finalise ---------
#
# import.py runs in its own process, as in OpendTect's Python, on the fake odbind of ophiolite-opendtect/tests/fake_odbind
# (FAKE_ODBIND_STATE keeps what it writes between the import and the read-back); the survey is the fake's Syn_Survey
# (EPSG:32631, TWT ms, inlines 10-16 step 2, crosslines 20-26 step 2, Z 100-116 step 4), which already holds cubes
# Syn and Syn2 and horizon Top of its own. The fake keeps a written horizon's Z per inline in 65534 steps of that
# inline's range (matrix z_storage): stored = low + round((z - low) / step) * step as float32, step = range / 65534.

SURVEY = 'Syn_Survey'
RESULT = 'targets/opendtect/result.json'
OUTSIDE = "This seismic volume is not on the OpendTect survey's sampling yet."  # Syn2: Z 102-110 step 2 on a survey of step 4
GUI = 'OpendTect 7.0.10 cannot create a well from Python; import this well path in OpendTect (Survey > Import > Wells).'
EXISTS = 'A log of this name is already on the well in the OpendTect survey; it is not overwritten.'
# E129 (f): the fake's SYN-A already holds GR and DT of its own, so the pack's SYN-A.las (curves DT, GR) places nothing
# there; each well path says the GUI step
NOT_PLACED = [{'kind': 'seismic-3d', 'object': 'Syn2', 'reason': OUTSIDE},
              {'kind': 'wellbore-paths', 'object': 'SYN-A', 'file': 'wells/SYN-A-positions.csv', 'reason': GUI},
              {'kind': 'wellbore-logs', 'object': 'SYN-A', 'file': 'wells/SYN-A.las', 'curve': 'DT', 'reason': EXISTS},
              {'kind': 'wellbore-logs', 'object': 'SYN-A', 'file': 'wells/SYN-A.las', 'curve': 'GR', 'reason': EXISTS},
              {'kind': 'wellbore-paths', 'object': 'SYN-B', 'file': 'wells/SYN-B-positions.csv', 'reason': GUI},
              {'kind': 'wellbore-logs', 'object': 'SYN-B', 'reason': 'the well has no logs'}]
# Top: Z = 100 + 4 (i - 10) + c / 4, so every inline spans 1.5 ms over crosslines 20-26 (step 1.5 / 65534 ms); the nodes
# a quarter and a half of the way (c = 22, 24) move, the inline's two ends do not; (12, 24) has no value
MOVES = [{'inline': 10, 'crossline': 22, 'given': 105.5, 'stored': 105.50000762939453}, {'inline': 10, 'crossline': 24, 'given': 106.0, 'stored': 105.99999237060547},
         {'inline': 12, 'crossline': 22, 'given': 113.5, 'stored': 113.50000762939453},
         {'inline': 14, 'crossline': 22, 'given': 121.5, 'stored': 121.50000762939453}, {'inline': 14, 'crossline': 24, 'given': 122.0, 'stored': 121.99999237060547},
         {'inline': 16, 'crossline': 22, 'given': 129.5, 'stored': 129.50001525878906}, {'inline': 16, 'crossline': 24, 'given': 130.0, 'stored': 129.99998474121094}]
COMPARED = ['seismic cube seismic/Syn.sgy (item item-Syn-sgy at r1) into OpendTect as “Syn · Ophiolite v1”: 80 values, 0 differences, 0 moved',
            'horizon horizons/Top.csv (item item-Top-csv at r1) into OpendTect as “Top · Ophiolite v1”: 16 values, 0 differences, 7 moved',
            'not placed: seismic cube Syn2: ' + OUTSIDE, 'not placed: well path SYN-A: ' + GUI,
            'not placed: log SYN-A DT: ' + EXISTS, 'not placed: log SYN-A GR: ' + EXISTS,
            'not placed: well path SYN-B: ' + GUI, 'not placed: log SYN-B: the well has no logs']


@pytest.fixture
def odbind(tmp_path, monkeypatch):
    """The fake odbind and the connector on the import's path; the file that keeps what it writes."""
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(tmp_path / 'odbind-state.pickle'))
    return tmp_path / 'odbind-state.pickle'


def survey_at(where):
    folder = where / 'root' / SURVEY
    folder.mkdir(parents=True)
    (folder / '.survey').write_text('Name: Syn_Survey\n')
    (folder / '.defs').write_text('Depth in feet: No\n')  # E129 (f): a metre survey, as logs need (wells.FEET)
    return folder


def qualified(folder, survey, p):
    return starter.opendtect(client(p), folder / 'pack', survey, python=sys.executable)


def pack_files(folder):
    return {p: (folder / 'pack' / p).read_bytes() for p in ('starter.json', 'files/' + RESULT)}


def test_the_import_places_the_cube_and_the_horizon_and_the_qualification_writes_result_and_oracle(exports, tmp_path, project, odbind):
    """A4: export -> build (real readers) -> import.py from the pack's files -> the qualification at the pinned versions."""
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    survey = survey_at(tmp_path)
    project.provenance_reads.clear()
    doc, result = qualified(folder, survey, project)
    placed =[{k: v for k, v in p.items() if k != 'digest'} for p in result['placed']]
    assert placed == [
        {'kind': 'seismic-3d', 'file': 'seismic/Syn.sgy', 'item': 'item-Syn-sgy', 'version': 'r1', 'object': 'Syn · Ophiolite v1', 'values': 80, 'differences': 0, 'moves': []},
        {'kind': 'horizons', 'file': 'horizons/Top.csv', 'item': 'item-Top-csv', 'version': 'r1', 'object': 'Top · Ophiolite v1', 'values': 16, 'differences': 0, 'moves': MOVES}]
    assert all(starter.SHA256.fullmatch(p['digest']) for p in result['placed'])  # 4 x 4 x 5 samples bit for bit; 4 x 4 nodes, (12, 24) null in both
    assert result['not_placed'] == NOT_PLACED and result['survey'] == SURVEY and result['pack'] == PACK
    assert (result['version'], result['compared'], result['differences'], 'ticket' in result) == (2, [], 0, False)  # R2-4: no ticket
    raw = (folder / 'pack/files' / RESULT).read_bytes()
    assert json.loads(raw) == result and raw == starter.dumped(result)
    (target,) = doc['targets']
    assert target['oracle'] == {'compared': COMPARED, 'values': 96, 'differences': 0, 'seed': 0}
    assert [a['path'] for a in target['artefacts']] == ARTEFACTS + [RESULT] and target['artefacts'][-1] == {'path': RESULT, 'sha256': sha(raw), 'bytes': len(raw)}
    assert json.loads((folder / 'pack/starter.json').read_text()) == doc
    starter.shaped(doc)
    # each landed item was read at its pinned version: its provenance holds exactly the pack's file
    assert project.provenance_reads == [('item-Syn-sgy', 'r1'), ('item-Top-csv', 'r1')]


def test_a_null_only_boundary_row_is_kept_as_nulls(exports, tmp_path, project, odbind):
    folder, export = copied(exports, 'time', tmp_path)
    raw = (current(export) / 'files/horizons/Top.csv').read_bytes()
    rows = raw.decode().splitlines()
    nulled = [r if not r.endswith((',16,20', ',16,22', ',16,24', ',16,26')) else ','.join(r.split(',')[:2] + [''] + r.split(',')[3:]) for r in rows]
    assert sum(r.split(',')[2] == '' for r in nulled[1:]) == 5  # (12, 24) and all of inline 16
    another(export, 'nullrow-1', replaced_file('horizons/Top.csv', ''.join(r + '\n' for r in nulled).encode()))
    build(folder, export, project)
    doc, result = qualified(folder, survey_at(tmp_path), project)
    (horizon,) = [p for p in result['placed'] if p['kind'] == 'horizons']
    assert (horizon['values'], horizon['differences'], horizon['moves']) == (16, 0, MOVES[:5])  # inline 16 read back as four nulls, not cut off
    assert doc['targets'][0]['oracle']['compared'][1].endswith(': 16 values, 0 differences, 5 moved')


def test_a_horizon_not_landed_in_ophiolite_is_placed_and_compared_with_the_packs_file(exports, tmp_path, project, odbind, monkeypatch):
    """B5: a horizon over the node limit has a failed row and no item; the import still places it from the pack."""
    monkeypatch.setattr(starter, 'MAX_NODES', 15)  # Top has 16 nodes
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    assert 'Top.csv' not in project.taken
    doc, result = qualified(folder, survey_at(tmp_path), project)
    (horizon,) = [p for p in result['placed'] if p['kind'] == 'horizons']
    assert (horizon['item'], horizon['version'], horizon['values'], horizon['differences'], horizon['moves']) == (None, None, 16, 0, MOVES)
    assert doc['targets'][0]['oracle']['compared'][1] == \
        'horizon horizons/Top.csv (not landed in Ophiolite) into OpendTect as “Top · Ophiolite v1”: 16 values, 0 differences, 7 moved'


def test_no_survey_refuses_with_the_gui_step_and_places_nothing(exports, tmp_path, project, odbind):
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    before = (folder / 'pack/starter.json').read_bytes()
    survey = tmp_path / 'root' / SURVEY
    assert refused(qualified, folder, survey, project) == (
        'The import refused: There is no OpendTect survey at %s. Make it in OpendTect first (Survey > Select/Setup, then Create New Survey) '
        "on this pack's sampling: inlines 10-16 step 2, crosslines 20-26 step 2, Z 100-116 ms step 4 (as in seismic/Syn.sgy), coordinate "
        'system EPSG:32631; then run the import again. Nothing was placed.' % survey + starter.UNCHANGED)
    assert not odbind.exists() and not survey.exists() and (folder / 'pack/starter.json').read_bytes() == before
    assert not (folder / 'pack/files' / RESULT).exists()


def test_a_changed_pack_file_refuses_before_anything_is_placed(exports, tmp_path, project, odbind):
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    p = folder / 'pack/files/horizons/Top.csv'
    p.write_bytes(p.read_bytes().replace(b',105.0,10,20', b',105.25,10,20'))
    # C3b: the derived file is an artefact, so the qualification's own artefact check names it before the import runs
    # (the import's check of the same file is test_starter_import.py's 'a changed file')
    assert refused(qualified, folder, survey_at(tmp_path), project) == (
        'artefact horizons/Top.csv: the file in files/ is not the one starter.json names.' + starter.UNCHANGED)
    assert not odbind.exists()


def test_permission_loss_on_a_landed_item_writes_neither_result_nor_starter_json(exports, tmp_path, project, odbind, monkeypatch):
    """As E125's horizon get: the server's refusal is passed on (exit 3), and nothing of the pack is written."""
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    before = (folder / 'pack/starter.json').read_bytes()
    def denied(asset, revision): raise PermissionRefused('You cannot see this item in the project.')
    c = client(project); c.provenance = denied
    with pytest.raises(PermissionRefused): starter.opendtect(c, folder / 'pack', survey_at(tmp_path), python=sys.executable)
    assert (folder / 'pack/starter.json').read_bytes() == before and not (folder / 'pack/files' / RESULT).exists()


def test_finalise_before_the_import_refuses(exports, tmp_path, project):
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    before = (folder / 'pack/starter.json').read_bytes()
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == (
        'The OpendTect target of %s has not been imported and compared yet (its oracle says "nothing yet"): run ophiolite starter opendtect on it first.'
        % PACK + starter.UNCHANGED)
    assert (folder / 'pack/starter.json').read_bytes() == before


# --- A6: an interrupted qualification resumes to the same bytes; a completed rerun changes nothing ---------------------

def uninterrupted(exports, where, project):
    folder, export = copied(exports, 'time', where)
    build(folder, export, project)
    qualified(folder, survey_at(where), project)
    return pack_files(folder)


@pytest.mark.parametrize('stop', ['before the result', 'between the result and starter.json'])
def test_an_interrupted_qualification_resumes_through_already_to_the_same_bytes(exports, tmp_path, project, monkeypatch, stop):
    (tmp_path / 'whole').mkdir(); (tmp_path / 'cut').mkdir()
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(tmp_path / 'whole/state.pickle'))
    expected = uninterrupted(exports, tmp_path / 'whole', project)
    project.__init__()
    monkeypatch.setenv('FAKE_ODBIND_STATE', str(tmp_path / 'cut/state.pickle'))
    folder, export = copied(exports, 'time', tmp_path / 'cut')
    build(folder, export, project)
    survey = survey_at(tmp_path / 'cut')
    fired = failing(monkeypatch, lambda path, raw: path.name == ('result.json' if stop == 'before the result' else 'starter.json'))
    with pytest.raises(OSError): qualified(folder, survey, project)
    assert fired
    record = json.loads((survey / 'Ophiolite' / ('starter-%s-horizons.json' % PACK.replace('/', '__'))).read_text())
    assert [(o['name'], o['item']) for o in record['objects'].values()] == [('Top · Ophiolite v1', 'horizons/Top.csv')]  # recorded before the stop
    assert json.loads((folder / 'pack/starter.json').read_text())['targets'][0]['oracle'] == starter.ORACLE_OPENDTECT
    state = (tmp_path / 'cut/state.pickle').read_bytes()
    doc, result = qualified(folder, survey, project)
    assert (tmp_path / 'cut/state.pickle').read_bytes() == state  # every object answered `already`: nothing written again
    assert pack_files(folder) == expected
    assert [p['moves'] for p in result['placed']] == [[], MOVES] and result['not_placed'] == NOT_PLACED


def test_a_completed_rerun_changes_nothing(exports, tmp_path, project, odbind):
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    survey = survey_at(tmp_path)
    qualified(folder, survey, project)
    files = [folder / 'pack/starter.json', folder / 'pack/files' / RESULT, odbind]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
    qualified(folder, survey, project)
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in files] == before


def test_a_resume_refuses_a_starter_json_whose_oracle_is_not_its_results(exports, tmp_path, project, odbind):
    folder, export = copied(exports, 'time', tmp_path)
    build(folder, export, project)
    survey = survey_at(tmp_path)
    qualified(folder, survey, project)
    p = folder / 'pack/starter.json'
    doc = json.loads(p.read_text()); doc['targets'][0]['oracle']['differences'] = 1
    p.write_bytes(starter.dumped(doc))
    before = pack_files(folder)
    assert refused(qualified, folder, survey, project) == starter.RESULT_NOT_NAMED
    assert pack_files(folder) == before


# --- the custody documents finalise reads (also used by the Platform suite's osd validate tests) ----------------------

def derive(folder):
    """The derived custody documents an upload of pack/files writes (custody/<sha256>.json), as test_starter_build's."""
    doc = json.loads((folder / 'pack/starter.json').read_text())
    for a in (a for t in doc['targets'] for a in t['artefacts']):  # E129 (e): a path two targets share has one document
        path = 'derived-' + a['path'].rsplit('/', 1)[-1]
        key = 'mirror/%s/%s/%s' % (RID, a['sha256'], path)
        (folder / 'custody' / (a['sha256'] + '.json')).write_text(json.dumps({
            'format': 'osd.custody/2', 'record_id': RID, 'path': path, 'origin_href': None, 'key': key, 'href': 'https://mirror.example.org/' + key,
            'sha256': a['sha256'], 'bytes': a['bytes'], 'copied_at': '2026-10-29T02:00:00Z', 'licence': {k: v for k, v in doc['licence'].items() if k != 'sources'},
            'licence_text_sha256': None, 'attribution': ['Made by the starter recipe.'], 'takedown': 'https://example.org/takedown', 'removal': {'state': 'held'},
            'derived': {'pack_id': PACK, 'recipe_id': doc['recipe']['id'], 'from': sorted({i['sha256'] for i in doc['inputs']})}}))
