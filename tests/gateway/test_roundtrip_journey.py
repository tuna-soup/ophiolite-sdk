"""E138 s0 C3 (strategy rev 3 §5, D5-D7, D9; acceptance 2 and acceptance 3's storage part; R1-1, R1-13 to R1-19,
R2-2, R2-3, R2-6, R2-10, R2-11): the synthetic journey, OpendTect to Ophiolite to Python.

The survey is the fake odbind of `ophiolite-opendtect/tests/fake_odbind`, unchanged, with its own formulas and
variants. The exporter is the real one, run as a child process with the fake and the connector on its PYTHONPATH (as
test_starter_export.py's `real` fixture runs it); nothing here imports either (the E125 licence boundary). The project is the in-process gateway of the gateway lane (`web` of
project_gateway's one-API matrix over HTTP, the Connectors' intake), built on `test_applications.app` with the work
folder as its folder, so its journal is `<work>/journal` and its payloads `<work>/payloads` (D7, R2-3). The oracle
below, the journey's expected side, is the fake's formulas transcribed by hand as independent literals; it imports
neither the fake, `ophiolite_opendtect`, `starter_archive` nor numpy (R1-14). A gateway module: it reads the journey and the fake from the monorepo, above the SDK tree."""
import gc
import hashlib
import importlib.util
import io
import json
import math
import os
import struct
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (the gateway lane's fixtures)
from project_gateway.tests import test_applications, test_retained_applications, test_one_api_matrix
from project_gateway.tests.conftest import schema_for
from project_gateway.retained_assets import RetainedAssets

ROOT = Path(__file__).resolve().parents[3]
FAKE, CONNECTOR = ROOT / 'ophiolite-opendtect/tests/fake_odbind', ROOT / 'ophiolite-opendtect/src'
spec = importlib.util.spec_from_file_location('roundtrip_journey', ROOT / 'conformance/roundtrip/journey.py')
journey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = journey
spec.loader.exec_module(journey)
ev = journey.ev

# --- the oracle: the fake's survey, transcribed by hand from its source as independent literals (R1-14) -----------
# Syn_Survey, EPSG:32631, TWT ms; x = 500000.375 + 25 (c - 20), y = 0.125 + 25 (i - 10); Syn on inlines 10-16 step 2,
# crosslines 20-26 step 2, Z 100-116 step 4, sample i + c/4 + k/16; Syn2 on 12-14 step 2, 22-24 step 2, Z 102-110 step 2,
# sample -(i + c/8 + k/32); Top Z = 100 + 4 (i - 10) + c/4, no value at (12, 24); variant `nan`: Syn (12, 22, 1) NaN.
GR = [None, 60.5, 61.0, 62.0, 63.5, 64.0, None]
DT = [None, 120.25, 121.5, 122.0, 123.75, 124.5, 125.0]
MD = [100.0, 100.15, 100.3, 100.45, 100.6, 100.75, 100.9]


def x_of(c): return 500000.375 + 25.0 * (c - 20)
def y_of(i): return 0.125 + 25.0 * (i - 10)
def syn(i, c, k): return i + c / 4 + k / 16
def syn2(i, c, k): return -(i + c / 8 + k / 32)
def top(i, c): return None if (i, c) == (12, 24) else 100.0 + 4 * (i - 10) + c / 4


TRACKS = {  # (md, x, y, tvdss) per station
    'SYN-A': [(0.0, 500010.125, 10.375, -20.0), (60.0, 500010.125, 10.375, 40.0), (120.0, 500012.5, 11.0, 99.5), (180.0, 500015.0, 12.25, 158.75)],
    'SYN-B': [(0.0, 500075.0, 50.0, -10.0), (50.0, 500075.0, 50.0, 40.0), (100.0, 500076.5, 51.25, 89.75)],
    'SYN-C': [(0.0, 500100.25, 75.5, -15.0), (80.0, 500100.25, 75.5, 65.0), (160.0, 500101.0, 76.0, 144.5)],
    'SYN-D': [(0.0, 500125.75, 100.25, -12.5), (90.0, 500125.75, 100.25, 77.5), (180.0, 500127.25, 101.5, 167.0)],
    'SYN E/5 (b)': [(0.0, 500050.5, 125.0, -11.0), (70.0, 500050.5, 125.0, 59.0), (140.0, 500051.0, 125.75, 128.5)]}
CENTS_X = {20: 50000038, 22: 50005038, 24: 50010038, 26: 50015038}  # x_of(c), half-even hundredths
CENTS_Y = {10: 12, 12: 5012, 14: 10012, 16: 15012}  # y_of(i)
AXES = {'Syn': 'inline 10-16 step 2; crossline 20-26 step 2; z 100-116 step 4', 'Syn2': 'inline 12-14 step 2; crossline 22-24 step 2; z 102-110 step 2'}
GRIDS = {'Syn': ((10, 12, 14, 16), (20, 22, 24, 26), 5, syn), 'Syn2': ((12, 14), (22, 24), 5, syn2)}
WELLS = ['SYN E/5 (b)', 'SYN-A', 'SYN-B', 'SYN-C', 'SYN-D']
STATIONS = {'SYN-A': 4, 'SYN-B': 3, 'SYN-C': 3, 'SYN-D': 3, 'SYN E/5 (b)': 3}
LOGS = {'SYN-A/GR': ('API', [1, 2, 3, 4, 5]), 'SYN-A/DT': ('us/ft', [1, 2, 3, 4, 5, 6])}  # unit, finite sample positions
OBJECTS = [('seismic-3d', 'Syn'), ('seismic-3d', 'Syn2'), ('horizon-3d', 'Top')] + [('well-path', w) for w in WELLS] + \
          [('well-head', w) for w in WELLS] + [('well-log', 'SYN-A/GR'), ('well-log', 'SYN-A/DT')]
OPHIOLITE = ('opendtect-to-project', 'project-to-sdk')
# E138 s2: the fake's four 2D lines (fake_odbind LINE, LINES2D; seismic2d.py `samples`), transcribed by hand: five
# traces each, source points 1.5, 2.0, absent, 3.5, 4.0, x 500001 + 12.5 n, y 100 + 6.25 n, TWT 100-116 step 4, the
# sample of trace number t at index k t/4 + k/8; listed in the CLI's order (datasets sorted, lines as stored)
LINE_REF = [1.5, 2.0, None, 3.5, 4.0]
LINE_X = [500001.0, 500013.5, 500026.0, 500038.5, 500051.0]
LINE_Y = [100.0, 106.25, 112.5, 118.75, 125.0]
LINES = {'Other/L1': [301, 302, 303, 304, 305], 'Syn2D/L1': [101, 102, 103, 104, 105], 'Syn2D/L2': [201, 202, 203, 204, 205], 'Syn^2D/L 1.a': [101, 102, 103, 104, 105]}
LINE_OBJECTS = [('line-2d', n) for n in LINES]
# E138 s3 (R2-3): the fake's fault stick set SynF (three sticks of three points, x 500010 + 25 s + k, y 20 + k, z 0.104
# + 0.004 k s) and 3D fault SynF3D (sticks of 2, 3 and 4 points), transcribed by hand from fake_odbind STICKSETS and
# FAULTS3D: 6 sticks, 18 points; z in seconds; listed in the read CLI's order (3D faults first)
SYNF = [(s, [(500010.0 + 25.0 * s, 20.0, 0.104), (500011.0 + 25.0 * s, 21.0, 0.108), (500012.0 + 25.0 * s, 22.0, 0.112)]) for s in range(3)]
SYNF3D = [(0, [(500100.0, 40.0, 0.1), (500101.0, 41.0, 0.12)]), (1, [(500125.0, 40.0, 0.124), (500126.0, 41.5, 0.116), (500127.0, 43.0, 0.108)]),
          (2, [(500150.0, 40.0, 0.1), (500151.0, 41.0, 0.104), (500152.0, 42.0, 0.108), (500153.0, 43.0, 0.112)])]
FAULTS = {'SynF3D': SYNF3D, 'SynF': SYNF}
FAULT_OBJECTS = [('fault-sticks', n) for n in FAULTS]
OBJECTS = OBJECTS + FAULT_OBJECTS


def fault_source(sticks): return {'sticks': [(i, list(points)) for i, points in sticks], 'unit': 's', 'domain': 'time'}
# §2's fault encodings, written here by hand (not compare.py's): indices in file order as >i; (index, count) pairs in
# ascending index as >ii; per stick in file order >ii index and count, then >ddd per point (R2-6)
def order(sticks): return hashlib.sha256(b''.join(struct.pack('>i', i) for i, _ in sticks)).hexdigest()
def per_stick(sticks): return hashlib.sha256(b''.join(struct.pack('>ii', i, len(p)) for i, p in sorted(sticks))).hexdigest()
def sticks_digest(sticks):
    return hashlib.sha256(b''.join(struct.pack('>ii', i, len(p)) + b''.join(struct.pack('>ddd', *v) for v in p) for i, p in sticks)).hexdigest()


def line_sample(t, k): return t / 4 + k / 8


def literal_line(trc, ref=None, x=None, y=None, z=(100.0, 4.0), count=5):
    """A line in journey.py's literal shape; x and y default to the four lines' (or `small`'s 500000 + 10 t, 10 t)."""
    ref = LINE_REF if ref is None else ref
    x = x or (LINE_X if len(trc) == 5 else [500000.0 + 10.0 * t for t in trc])
    y = y or (LINE_Y if len(trc) == 5 else [10.0 * t for t in trc])
    return {'traces': [(t, r, a, b, [line_sample(t, k) for k in range(count)]) for t, r, a, b in zip(trc, ref, x, y)], 'z': z, 'unit': 'ms', 'domain': 'time'}


def oracle(lines=False):
    """The journey's expected side, from the literals above only (with LINES, the four 2D lines too)."""
    objects = {}
    if lines:
        for name, trc in LINES.items(): objects[('line-2d', name)] = literal_line(trc)
    for cube, (inlines, crosslines, count, f) in GRIDS.items():
        objects[('seismic-3d', cube)] = {'traces': {(i, c): (x_of(c), y_of(i), [f(i, c, k) for k in range(count)]) for i in inlines for c in crosslines},
                                         'count': count, 'axes': AXES[cube], 'unit': 'ms'}
    objects[('horizon-3d', 'Top')] = {(i, c): (x_of(c), y_of(i), top(i, c)) for i in (10, 12, 14, 16) for c in (20, 22, 24, 26)}
    for well, track in TRACKS.items(): objects[('well-path', well)] = {'stations': list(track), 'head': track[0][1:3]}
    objects[('well-log', 'SYN-A')] = {'GR': ('API', list(GR), list(MD)), 'DT': ('us/ft', list(DT), list(MD))}
    for name, sticks in FAULTS.items(): objects[('fault-sticks', name)] = fault_source(sticks)
    return {'enumerated': list(OBJECTS) + (list(LINE_OBJECTS) if lines else []), 'objects': objects}


def clean_states(objects=OBJECTS):
    """§5: every mandatory row; QGIS and ResInsight wait on their tools; the whole kinds wait on E137. E138 s2: a line's
    two judged legs within, its QGIS row waiting on the tool, its ResInsight row unsupported. E138 s3: a fault set's
    two judged legs equal (lossless, design 4), its QGIS row waiting on the tool, its ResInsight row unsupported."""
    out = {}
    for kind, obj in objects:
        for leg in ev.PER_OBJECT[kind]:
            exact = (kind, leg) == ('seismic-3d', 'project-to-sdk') or kind == 'fault-sticks'
            out[(kind, obj, leg)] = {'project-to-qgis': 'not-yet', 'project-to-resinsight': 'not-yet'}.get(leg, 'equal' if exact else 'within')
        for leg in ev.UNSUPPORTED.get(kind, ()): out[(kind, obj, leg)] = 'unsupported'  # E139 s2 (S2-7), E138 s2 D4: no route, composed every run
    listed = {k for k, _ in objects}
    for kind in ('seismic-3d', 'horizon-3d', 'well-path', 'well-head', 'well-log', 'horizon-2d', 'line-2d', 'fault-sticks'):
        if kind not in listed: out[(kind, '*', '*')] = 'absent'  # E138 s1 D4: the enumeration lists none
    out[('time-depth', '*', '*')] = 'not-yet'
    return out


CLEAN = clean_states()


def states(report): return {(r['kind'], r['object'], r['leg']): r['state'] for r in report['rows']}
def the(report, kind, obj, leg): return next(r for r in report['rows'] if (r['kind'], r['object'], r['leg']) == (kind, obj, leg))
def q(r, name): return next(x for x in r['quantities'] if x['name'] == name)


def zipped():
    """The survey archive: Syn_Survey/ with its .survey and .defs (the fake holds the rest)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, raw in [('Syn_Survey/', b''), ('Syn_Survey/.survey', b'Name: Syn_Survey\nSeismic Reference Datum: 0\n'), ('Syn_Survey/.defs', b'Depth in feet: No\n')]:
            info = zipfile.ZipInfo(name, (2026, 10, 31, 0, 0, 0))
            if name.endswith('/'): info.external_attr = 0o40755 << 16
            z.writestr(info, raw)
    return out.getvalue()


@pytest.fixture
def survey(monkeypatch):
    """No variant and no fake state inherited; the exporter's environment is set per run (`exporter_env`)."""
    for name in ('FAKE_ODBIND_VARIANT', 'FAKE_ODBIND_STATE'): monkeypatch.delenv(name, raising=False)
    return monkeypatch


def exporter_env(variant=None):
    """The child exporter's PYTHONPATH (the fake odbind, then the connector) and the fake's variant."""
    return {'PYTHONPATH': os.pathsep.join([str(FAKE), str(CONNECTOR)]), **({'FAKE_ODBIND_VARIANT': variant} if variant else {})}


class Project:
    """The in-process gateway on the work folder: `test_applications.app` with WORK as its folder, then `shared` and
    `web` as the gateway lane builds them."""
    def __init__(self, work, service, monkeypatch):
        self.work = work
        monkeypatch.setenv('OPHIOLITE_PAYLOAD_STORE', 'local:%s' % (work / 'payloads'))  # R2-3: before the application is built
        self._app = test_applications.app.__wrapped__(work)
        a = next(self._app)
        try:
            self._web = test_one_api_matrix.web.__wrapped__(test_retained_applications.shared.__wrapped__(a), service, monkeypatch)
            self.web = next(self._web)
        except BaseException:
            self._finish(self._app); raise
        self.client = client(self.web, 'alice', 'delegate')
        self.tools = {'opendtect-to-project': {'name': 'ophiolite-gateway', 'version': 'in-process', 'host': 'synthetic'},
                      'project-to-sdk': {'name': 'ophiolite-sdk', 'version': 'checkout', 'host': 'synthetic'}}

    def payload_stores(self):
        """Every payload store the project's retained assets resolved."""
        journal = self.web.a.journal
        return [(o.payloads.kind, o.payloads.root) for o in gc.get_objects() if isinstance(o, RetainedAssets) and o.journal is journal]

    def storage(self):
        db = self.web.a.journal.db
        if getattr(db, 'engine', 'sqlite') == 'postgres':
            assert db.schema == schema_for(self.work / 'journal')
            return {'engine': 'postgres', 'dsn': os.environ['TEST_ORG_DATABASE_URL'], 'schema': db.schema}
        return {'engine': 'sqlite', 'path': str(self.web.a.journal.path)}

    @staticmethod
    def _finish(generator):
        try: next(generator)
        except StopIteration: pass

    def close(self):
        self._finish(self._web); self._finish(self._app)


class Target:
    def __init__(self, service, monkeypatch):
        self.service, self.monkeypatch, self.projects = service, monkeypatch, []

    def open(self, work):
        self.projects.append(Project(work, self.service, self.monkeypatch))
        return self.projects[-1]


@pytest.fixture
def journey_run(survey, service, tmp_path):
    """run(**kw) -> (report, target): one journey of the synthetic archive on a volume of the test's own."""
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    def run(target=None, variant=None, the_oracle=None, **kw):
        target = target or Target(service, survey)
        run.target = target
        return journey.run(archive, volume, target, oracle=the_oracle or oracle(), python=sys.executable, exporter_env=exporter_env(variant),
                           forbidden=[tmp_path / 'forbidden'], host='synthetic', **kw), target
    run.volume, run.monkeypatch, run.archive = volume, survey, archive
    return run


def storage_gone(work):
    """D7, checked again here: no schema of the work folder's journal and none of its tables, and no journal file."""
    left = 0
    if os.environ.get('TEST_ORG_DATABASE_URL'):
        import psycopg
        with psycopg.connect(os.environ['TEST_ORG_DATABASE_URL'], autocommit=True) as db:
            schema = schema_for(work / 'journal')
            left = db.execute('SELECT count(*) FROM information_schema.schemata WHERE schema_name=%s', (schema,)).fetchone()[0]
            left += db.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s', (schema,)).fetchone()[0]
    return left == 0 and not os.path.lexists(work / 'journal')


def gone(run, target):
    """The work folder, the volume's only child, is gone, and so is the project's storage."""
    (project,) = target.projects
    return os.listdir(run.volume) == [] and not project.work.exists() and storage_gone(project.work)


def digest(cube):
    """The oracle's samples_sha256: float32 big-endian, inline-major, crossline, z, from D5's literal formula."""
    inlines, crosslines, count, f = GRIDS[cube]
    return hashlib.sha256(b''.join(struct.pack('>f', f(i, c, k)) for i in inlines for c in crosslines for k in range(count))).hexdigest()


def mask(defined):
    """The oracle's null mask: one byte per position, 1 where defined."""
    return hashlib.sha256(bytes(1 if d else 0 for d in defined)).hexdigest()


def coordinates_off(report):
    """The oracle's coordinate check (R1-14): every x and y example of a gridded row against the literal hundredths."""
    out = set()
    for r in report['rows']:
        for x in r['examples']:
            if r['kind'] in ('seismic-3d', 'horizon-3d') and x['quantity'] in ('x', 'y'):
                i, c = (int(v) for v in x['at'].split(','))
                want = CENTS_X[c] if x['quantity'] == 'x' else CENTS_Y[i]
                if x['observed'] is None or round(x['observed'] * 100) != want: out.add((r['kind'], r['object'], r['leg'], x['quantity']))
    return out


def expect(report, changed):
    """R2-11: the rows a mutation reaches are CHANGED; every other row is as in the clean run."""
    assert states(report) == {**CLEAN, **changed}
    return report


def disagreeing(r): return sorted(x['name'] for x in r['quantities'] if x['state'] != 'agree')


# --- acceptance 2: the clean run ----------------------------------------------------------------------------------

def check_clean(report, target, run, clean=None, objects=OBJECTS, selected=None):
    assert ev.evaluate(report) == []
    assert report['run']['work_folder_removed'] is True and report['run']['storage_removed'] is True and gone(run, target)
    assert report['dataset'] == {'id': 'synthetic-s0', 'archive_sha256': hashlib.sha256(zipped()).hexdigest(), 'synthetic': True}
    assert sorted((o['kind'], o['object']) for o in report['inventory']['enumerated']) == sorted(objects)
    assert sorted((o['kind'], o['object']) for o in report['inventory']['selected']) == sorted(selected or objects)
    assert states(report) == (clean or CLEAN)
    assert coordinates_off(report) == set()
    # §5's values, from D5's literals
    assert (syn(10, 20, 0), syn(16, 26, 4), syn2(12, 22, 0), syn2(14, 24, 4), top(10, 20), top(16, 26)) == (15.0, 22.75, -14.75, -17.125, 105.0, 130.5)
    first = lambda r, at: {x['at']: x['observed'] for x in r['examples'] if x['quantity'] == 'x'}[at]
    assert first(the(report, 'seismic-3d', 'Syn', 'opendtect-to-project'), '10,20') == first(the(report, 'seismic-3d', 'Syn2', 'opendtect-to-project'), '12,22') - 50.0 == 500000.38
    for cube, traces in (('Syn', 16), ('Syn2', 4)):
        for leg in OPHIOLITE:
            r = the(report, 'seismic-3d', cube, leg)
            assert [(x['name'], x['expected'], x['observed']) for x in r['quantities'] if x['mode'] != 'tolerance'] == [
                ('traces', traces, traces), ('samples per trace', 5, 5), ('axes', AXES[cube], AXES[cube]), ('unit', 'ms', 'ms'),
                ('samples_sha256', digest(cube), digest(cube)), ('null mask', 'none', 'none')]
        to_project = the(report, 'seismic-3d', cube, 'opendtect-to-project')
        assert sum(1 for x in to_project['examples'] if x['quantity'] == 'x') == traces and q(to_project, 'x')['largest']['value'] == 0.0
    assert the(report, 'seismic-3d', 'Syn', 'opendtect-to-project')['examples'][0]['at'] == '10,20'
    for leg in OPHIOLITE:
        r = the(report, 'horizon-3d', 'Top', leg)
        assert (q(r, 'nodes')['observed'], q(r, 'defined nodes')['observed']) == (16, 15)
        z = {x['at']: (x['expected'], x['observed']) for x in r['examples'] if x['quantity'] == 'z'}
        assert len(z) == 15 and '12,24' not in z and z['10,20'] == (105.0, 105.0) and z['16,26'] == (130.5, 130.5)
        assert q(r, 'null mask')['expected'] == q(r, 'null mask')['observed'] == mask([(i, c) != (12, 24) for i in (10, 12, 14, 16) for c in (20, 22, 24, 26)])
    for well, count in STATIONS.items():
        for leg in OPHIOLITE: assert q(the(report, 'well-path', well, leg), 'stations')['observed'] == count
    for log, (unit, finite_at) in LOGS.items():
        for leg in OPHIOLITE:
            r = the(report, 'well-log', log, leg)
            assert (q(r, 'samples')['observed'], q(r, 'unit')['observed']) == (7, unit)
            values = {int(x['at']): x['observed'] for x in r['examples'] if x['quantity'] == 'values'}
            assert sorted(k for k, v in values.items() if v is not None) == finite_at
            assert q(r, 'null mask')['observed'] == mask([k in finite_at for k in range(7)])
        depth = {int(x['at']): x['observed'] for x in the(report, 'well-log', log, 'opendtect-to-project')['examples'] if x['quantity'] == 'depth'}
        assert [depth[k] for k in range(7)] == [100.0, 100.15, 100.3, 100.45, 100.6, 100.75, 100.9]
    gr = {int(x['at']): x['observed'] for x in the(report, 'well-log', 'SYN-A/GR', 'project-to-sdk')['examples'] if x['quantity'] == 'values'}
    assert [gr.get(k) for k in range(7)] == [None, 60.5, 61.0, 62.0, 63.5, 64.0, None]
    dt = {int(x['at']): x['observed'] for x in the(report, 'well-log', 'SYN-A/DT', 'project-to-sdk')['examples'] if x['quantity'] == 'values'}
    assert [dt.get(k) for k in range(7)] == [None, 120.25, 121.5, 122.0, 123.75, 124.5, 125.0]
    for well, stations in TRACKS.items():
        md = {int(x['at']): x['observed'] for x in the(report, 'well-path', well, 'project-to-sdk')['examples'] if x['quantity'] == 'md'}
        assert (md[0], md[len(stations) - 1]) == (stations[0][0], stations[-1][0])
    # E138 s3 (R2-3): 6 sticks, 18 points; SynF 3 x 3, SynF3D 2 + 3 + 4; the digests from the literals, by hand
    assert sum(len(s) for s in FAULTS.values()) == 6 and sum(len(p) for s in FAULTS.values() for _, p in s) == 18
    for name, sticks in FAULTS.items():
        n = sum(len(p) for _, p in sticks)
        for leg in OPHIOLITE:
            r = the(report, 'fault-sticks', name, leg)
            original = [('original_sha256', q(r, 'original_sha256')['expected'], q(r, 'original_sha256')['expected'])] if leg == 'project-to-sdk' else []
            assert [(x['name'], x['expected'], x['observed']) for x in r['quantities'] if x['mode'] != 'tolerance'] == original + [
                ('sticks', len(sticks), len(sticks)), ('points', n, n), ('stick order', order(sticks), order(sticks)),
                ('points per stick', per_stick(sticks), per_stick(sticks)), ('sticks_sha256', sticks_digest(sticks), sticks_digest(sticks)),
                ('unit', 's', 's'), ('domain', 'time', 'time')]
            assert all(q(r, c)['over_budget'] == 0 and q(r, c)['compared'] == n for c in 'xyz')


def test_the_clean_synthetic_run_is_judged_clean_with_the_hand_counted_values(journey_run, monkeypatch):
    """Acceptance 2 with D7 on the managed schema and R2-3's store check; D9: the parent never opens a bundle."""
    seen = {}
    def after(client, receipts):
        (project,) = journey_run.target.projects
        seen['stores'] = {(kind, str(root)) for kind, root in project.payload_stores()}
        seen['work'] = project.work
        seen['payloads'] = [p for p in (project.work / 'payloads').rglob('*') if p.is_file()]
        seen['engine'] = project.storage()['engine']
    monkeypatch.setattr(journey, 'offline_read', lambda *a, **k: pytest.fail('leg 2 is read in the offline process only'))  # R2-6
    report, target = journey_run(hooks={'after_landing': after})
    check_clean(report, target, journey_run)
    assert seen['stores'] == {('local', str(seen['work'] / 'payloads'))} and seen['payloads']
    assert seen['engine'] == 'postgres'  # the gateway lane's journal; the SQLite journal is the next test
    # E138 s1 D3 and mutation 16: both digests unchanged; the process tree sampled in each phase, in phase order
    memory = report['run']['memory']
    assert report['run']['survey_unchanged'] is True and report['run']['archive_unchanged'] is True and 'stopped' not in report['run']
    # adhoc-contract-weights: this process counts by its growth since the sampler started, so a phase with no child
    # and no growth samples 0; the online and offline phases have their children
    tree = memory['tree_max_kib']
    assert list(tree) == ['online', 'tools', 'close', 'offline'] and tree['online'] > 0 and tree['offline'] > 0 and min(tree.values()) >= 0
    assert set(memory['maxrss_kib']) == {'journey', 'largest child'} and memory['within_target'] is True
    # E138 s5 T8 (D5): no definition, the kind's one not-yet row (CLEAN) and the counts that say so
    assert report['time_depth'] == {'definition': False, 'models': 0, 'survey_wells': 5, 'outside': 0}
    assert the(report, 'time-depth', '*', '*')['evidence'] == {'waits_on': 'E137 s3'} and not any(f['step'].startswith('time-depth') for f in report['findings'])


def test_the_tree_counts_the_runs_growth_and_children_not_the_sessions_earlier_heap():
    """adhoc-contract-weights (7 Nov): four sightings above the 2 GB target were the pytest session's heap (1.31 GB of
    1.37 GB after 71 gateway files). Held: 64 MiB of earlier heap, then the sampler, then 32 MiB of the run's own and a
    child of 48 MiB; the tree counts the 32 and the 48, and BASE 0 counts the earlier heap too."""
    class Work:
        def survivors(self): return []
    import subprocess
    earlier = bytearray(64 << 20); earlier[::4096] = b'\1' * len(earlier[::4096])
    sampler = journey.Sampler(Work())
    assert abs(sampler.base - journey.own_rss_kib()) < 4096
    own = bytearray(32 << 20); own[::4096] = b'\1' * len(own[::4096])
    child = subprocess.Popen([sys.executable, '-c', 'import sys\nb = bytearray(48 << 20)\nb[::4096] = b"\\1" * len(b[::4096])\n'
                              'print(flush=True)\nsys.stdin.read()'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        child.stdout.readline()
        with open('/proc/%d/status' % child.pid) as f:
            child_kib = int(next(l for l in f if l.startswith('VmRSS:')).split()[1])
        tree, whole = journey.tree_rss_kib(Work(), sampler.base), journey.tree_rss_kib(Work())
        # adhoc-hardening-1108: the 32 MiB may reuse pages the session already freed and still holds (hosted: child
        # 59132, tree 72020, growth 12888 KiB), so only the child is promised below and the 32 MiB only above
        assert child_kib > 48 << 10 and child_kib - 4096 < tree < (32 << 10) + child_kib + (16 << 10)
        assert abs(whole - tree - sampler.base) < 4096 and whole > tree + (64 << 10)
    finally:
        child.stdin.close(); child.wait(10)
    del earlier, own


@pytest.mark.sqlite_journal
def test_the_clean_run_on_a_sqlite_journal_removes_the_journal_file(journey_run):
    """D7 without the managed schema: the journal is the SQLite file `<work>/journal`, removed and checked."""
    seen = {}
    def after(client, receipts):
        (project,) = journey_run.target.projects
        seen['storage'] = project.storage(); seen['work'] = project.work
    report, target = journey_run(hooks={'after_landing': after})
    assert seen['storage'] == {'engine': 'sqlite', 'path': str(seen['work'] / 'journal')}
    check_clean(report, target, journey_run)


# --- R2-3: the payload store -----------------------------------------------------------------------------------

def files_outside(tmp_path, volume):
    return sorted(str(p) for p in tmp_path.rglob('*') if volume not in p.parents and p != volume)


@pytest.mark.parametrize('setting', ['outside local path', 's3'])
def test_an_inherited_payload_setting_writes_nothing_outside_the_work_folder(journey_run, tmp_path, setting):
    outside = tmp_path / 'outside-payloads'
    if setting == 's3':
        credentials = tmp_path / 's3.json'
        credentials.write_text(json.dumps({'access_key': 'synthetic-access', 'secret_key': 'synthetic-access'})); credentials.chmod(0o600)
        journey_run.monkeypatch.setenv('OPHIOLITE_PAYLOAD_STORE', 's3:https://s3.example.invalid/bucket/prefix')
        journey_run.monkeypatch.setenv('OPHIOLITE_PAYLOAD_STORE_CREDENTIALS', str(credentials))
    else:
        journey_run.monkeypatch.setenv('OPHIOLITE_PAYLOAD_STORE', 'local:%s' % outside)
    before = files_outside(tmp_path, journey_run.volume)
    report, target = journey_run()
    check_clean(report, target, journey_run)
    assert files_outside(tmp_path, journey_run.volume) == before and not outside.exists()


def test_a_project_whose_store_is_outside_the_work_folder_is_refused_before_anything_is_sent(journey_run, service, tmp_path):
    outside = tmp_path / 'outside-payloads'
    sent = []
    class Leaky(Target):
        def open(self, work):
            project = super().open(work)
            project.payload_stores = lambda: [('local', outside)]  # as if the override had come after the build
            return project
    with pytest.raises(journey.wf.Refused, match='not in the work folder') as refused:
        journey_run(target=Leaky(service, journey_run.monkeypatch), hooks={'landed': lambda path, raw: sent.append(path)})
    assert sent == [] and refused.value.roundtrip_run == {'work_folder_removed': True, 'storage_removed': True}
    assert not outside.exists() and os.listdir(journey_run.volume) == []
    assert storage_gone(journey_run.target.projects[0].work)


# --- R2-6: the offline reader ---------------------------------------------------------------------------------

def test_the_offline_reader_cannot_reach_the_network_and_its_rows_come_only_from_it(journey_run):
    """§5 mutation 11: a reader that tries the network inside D9's subprocess raises there; every to-sdk row fails."""
    report, target = journey_run(hooks={'offline_probe': 'https://workspace.example/'})
    sdk = {k for k, v in CLEAN.items() if k[2] == 'project-to-sdk'}
    expect(report, {k: 'failed' for k in sdk})
    for kind, obj, leg in sdk:
        assert 'E138 offline reader: no network connection is allowed' in the(report, kind, obj, leg)['evidence']['error']
    assert gone(journey_run, target)


# --- §5 mutations, each with the rows it reaches (R2-11) -----------------------------------------------------

def replacing(path, old, new):
    """A landed hook that changes one exact text of one file, and proves the text was there."""
    def landed(entry, raw):
        if entry != path: return raw
        assert raw.count(old) == 1, (entry, old)
        return raw.replace(old, new)
    return landed


def both(kind, obj, state): return {(kind, obj, leg): state for leg in OPHIOLITE}


def sgy_samples(raw, f):
    """Every trace's five float32 samples through F (big-endian, after the 3600-byte headers and the 240-byte trace header)."""
    out, n = bytearray(raw), (len(raw) - 3600) // 260
    for t in range(n):
        at = 3600 + 260 * t + 240
        out[at:at + 20] = f(at, out[at:at + 20])
    return bytes(out)


def test_mutation_1_one_sample_not_among_the_examples_disagrees_through_the_digest(journey_run):
    at = 3600 + 10 * 260 + 240 + 2 * 4  # inline 14, crossline 24 (trace 10, inline-major), sample 2
    def landed(entry, raw):
        if entry != 'seismic/Syn.sgy': return raw
        (v,) = struct.unpack_from('>f', raw, at)
        assert v == syn(14, 24, 2) == 20.125
        return raw[:at] + struct.pack('>f', v + 1.0) + raw[at + 4:]
    report, _ = journey_run(hooks={'landed': landed})
    expect(report, both('seismic-3d', 'Syn', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'seismic-3d', 'Syn', leg)
        assert disagreeing(r) == ['samples_sha256'] and q(r, 'samples_sha256')['expected'] == digest('Syn')


def test_mutation_2_one_coordinate_two_quanta_off_disagrees_over_its_budget(journey_run):
    report, _ = journey_run(hooks={'landed': replacing('horizons/Top.csv', b'500000.38,100.12,121.0,14,20', b'500000.40,100.12,121.0,14,20')})
    expect(report, both('horizon-3d', 'Top', 'disagree'))
    for leg in OPHIOLITE:
        x = q(the(report, 'horizon-3d', 'Top', leg), 'x')
        assert disagreeing(the(report, 'horizon-3d', 'Top', leg)) == ['x'] and x['largest']['at'] == '14,20'
        assert round(x['largest']['value'], 6) == 0.02 and x['over_budget'] == 1


def test_mutation_3_a_well_not_uploaded_fails_its_rows_and_the_journey_continues(journey_run):
    report, _ = journey_run(hooks={'landed': lambda entry, raw: None if entry == 'wells/SYN-B-positions.csv' else raw})
    expect(report, {**both('well-path', 'SYN-B', 'failed'), ('well-head', 'SYN-B', 'opendtect-to-project'): 'failed'})
    for leg in ('opendtect-to-project', 'project-to-sdk'):
        assert the(report, 'well-path', 'SYN-B', leg)['evidence']['error'] == 'The project lists no item named “well-path SYN-B”.'
    assert ev.evaluate(report) == []  # a failed row is a finding of the report, not a fault of it


def test_mutation_4_shared_rounding_is_caught_by_the_oracle_not_by_the_comparator(journey_run, monkeypatch):
    """R1-14, R2-8: the landed coordinates and the comparator's source side both round to tenths. The exporter is a
    child process this test does not patch, so the tenths are written into the landed files (every gridded x and y);
    the comparator applies the same quantisation to both sides (compare.py:87), so it cannot see the change; the
    oracle's literal hundredths can."""
    def tenths(n): return 10 * int((Decimal(n) / 10).quantize(Decimal(1), rounding='ROUND_HALF_EVEN'))  # n hundredths
    def quantised(v, quantum):
        scale = round(1 / float(quantum))
        return int((Decimal(float(v)) * 10).quantize(Decimal(1), rounding='ROUND_HALF_EVEN')) * scale // 10 if scale >= 10 else original(v, quantum)
    def landed(entry, raw):
        if entry.endswith('.sgy'):
            out = bytearray(raw)
            for t in range((len(raw) - 3600) // 260):
                th = 3600 + 260 * t
                assert struct.unpack_from('>h', raw, th + 70)[0] == -100
                for o in (72, 76, 180, 184): struct.pack_into('>i', out, th + o, tenths(struct.unpack_from('>i', raw, th + o)[0]))
            return bytes(out)
        if entry == 'horizons/Top.csv':
            head, *lines = raw.decode().splitlines()
            fix = lambda v: '%.2f' % (tenths(round(Decimal(v) * 100)) / 100)
            return '\n'.join([head] + [','.join([fix(p[0]), fix(p[1])] + p[2:]) for p in (l.split(',') for l in lines)]).encode() + b'\n'
        return raw
    original = journey.cmp.quantised
    monkeypatch.setattr(journey.cmp, 'quantised', quantised)
    report, _ = journey_run(hooks={'landed': landed})
    expect(report, {})
    assert coordinates_off(report) == {(kind, obj, leg, xy) for kind, obj, leg in [
        ('horizon-3d', 'Top', 'opendtect-to-project'), ('horizon-3d', 'Top', 'project-to-sdk'),
        ('seismic-3d', 'Syn', 'opendtect-to-project'), ('seismic-3d', 'Syn2', 'opendtect-to-project')] for xy in ('x', 'y')}


C_POSITIONS = b'md,x,y,tvdss\n0.0,500100.25,75.5,-15.0\n80.0,500100.25,75.5,65.0\n160.0,500101.0,76.0,144.5\n'
D_POSITIONS = b'md,x,y,tvdss\n0.0,500125.75,100.25,-12.5\n90.0,500125.75,100.25,77.5\n180.0,500127.25,101.5,167.0\n'


def test_mutation_5_two_same_sized_wells_swapped_disagree_with_their_counts_equal(journey_run):
    swap = {'wells/SYN-C-positions.csv': (C_POSITIONS, D_POSITIONS), 'wells/SYN-D-positions.csv': (D_POSITIONS, C_POSITIONS)}
    def landed(entry, raw):
        if entry not in swap: return raw
        assert raw == swap[entry][0]
        return swap[entry][1]
    report, _ = journey_run(hooks={'landed': landed})
    changed = {}
    for well in ('SYN-C', 'SYN-D'):
        changed.update(both('well-path', well, 'disagree')); changed[('well-head', well, 'opendtect-to-project')] = 'disagree'
    expect(report, changed)
    for well in ('SYN-C', 'SYN-D'):
        for leg in OPHIOLITE:
            r = the(report, 'well-path', well, leg)
            assert disagreeing(r) == ['md', 'tvdss', 'x', 'y'] and q(r, 'stations')['state'] == 'agree'
        assert disagreeing(the(report, 'well-head', well, 'opendtect-to-project')) == ['x', 'y']


def test_mutation_6a_horizon_axes_swapped_hold_positions_on_one_side(journey_run):
    def landed(entry, raw):
        if entry != 'horizons/Top.csv': return raw
        head, *lines = raw.decode().splitlines()
        assert head == 'x,y,z,inline,crossline'
        return '\n'.join([head] + [','.join(p[:3] + [p[4], p[3]]) for p in (l.split(',') for l in lines)]).encode() + b'\n'
    report, _ = journey_run(hooks={'landed': landed})
    expect(report, both('horizon-3d', 'Top', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'horizon-3d', 'Top', leg)
        assert q(r, 'nodes')['state'] == 'agree' and any(x['state'] == 'missing' or x.get('unmatched') for x in r['quantities'] if x['name'] in ('x', 'y', 'z'))


def test_mutation_6b_traces_reversed_in_z_disagree_on_the_digest(journey_run):
    def landed(entry, raw):
        if entry != 'seismic/Syn.sgy': return raw
        return sgy_samples(raw, lambda at, s: b''.join(s[k:k + 4] for k in range(16, -1, -4)))
    report, _ = journey_run(hooks={'landed': landed})
    expect(report, both('seismic-3d', 'Syn', 'disagree'))
    for leg in OPHIOLITE: assert 'samples_sha256' in disagreeing(the(report, 'seismic-3d', 'Syn', leg))


def test_mutation_7_a_log_unit_written_otherwise_disagrees_on_unit(journey_run):
    report, _ = journey_run(hooks={'landed': replacing('wells/SYN-A.las', b' GR.API : GR', b' GR.gAPI : GR')})
    expect(report, both('well-log', 'SYN-A/GR', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'well-log', 'SYN-A/GR', leg)
        assert disagreeing(r) == ['unit'] and (q(r, 'unit')['expected'], q(r, 'unit')['observed']) == ('API', 'gAPI')


def test_mutation_8_a_null_moved_with_its_count_unchanged_disagrees_on_the_null_mask(journey_run):
    def landed(entry, raw):  # LAS columns: DEPT, DT, GR
        raw = replacing('wells/SYN-A.las', b'100.75 124.5 64.0\n', b'100.75 124.5 -999.25\n')(entry, raw)
        return replacing('wells/SYN-A.las', b'100.9 125.0 -999.25\n', b'100.9 125.0 64.0\n')(entry, raw)
    report, _ = journey_run(hooks={'landed': landed})
    expect(report, both('well-log', 'SYN-A/GR', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'well-log', 'SYN-A/GR', leg)
        assert 'null mask' in disagreeing(r) and q(r, 'samples')['state'] == 'agree'
        assert q(r, 'null mask')['observed'] == mask([k in (1, 2, 3, 4, 6) for k in range(7)])


@pytest.mark.parametrize('variant, cube, sentence', [
    ('multicomponent', 'Syn2', 'The cube “Syn2” has 2 components; only single-component cubes are exported.'),
    ('nan', 'Syn', 'The cube “Syn” holds a sample that is not a finite value (inline 12, crossline 22).')])
def test_mutation_9_a_refused_cube_fails_its_rows_and_the_journey_continues(journey_run, variant, cube, sentence):
    report, target = journey_run(variant=variant)  # the fake's own variant, in the exporter's environment only
    expect(report, both('seismic-3d', cube, 'failed'))
    for leg in OPHIOLITE: assert the(report, 'seismic-3d', cube, leg)['evidence']['error'] == sentence
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_mutation_10_a_second_revision_of_the_same_asset_does_not_move_the_pinned_reads(journey_run, tmp_path):
    trap = {}
    def after(client, unit, receipt, held):  # E138 s1 D2: each object is read back as soon as it lands
        if unit != ('horizon-3d', 'Top'): return
        asset, first = receipt
        raw = held.read_bytes()
        assert raw.count(b',105.0,10,20') == 1
        second = client.upload_data(raw.replace(b',105.0,10,20', b',110.0,10,20'), profile='points-csv/1', name='horizon-3d Top',
                                    attribution='Synthetic round trip', audience=[], rights_confirmed=True, filename='Top.csv',
                                    declared={'crs': 'EPSG:32631','xy_unit': 'm', 'z_meaning': 'time', 'z_unit': 'ms', 'positive': 'down'},
                                    append_to=asset, expected_parent=first)
        (item,) = [i for i in client.assets() if i['asset_id'] == asset]
        client.download_original(asset, item['revision'], tmp_path / 'current.csv')  # the unpinned read: whatever is current
        trap.update(first=first, second=second, item=item, current=(tmp_path / 'current.csv').read_bytes())
    report, _ = journey_run(hooks={'object_landed': after})
    # the trap is live: same asset, a new current revision, and the unpinned read sees the changed z
    assert trap['second'].asset_id == trap['item']['asset_id'] and trap['second'].revision != trap['first']
    assert trap['item']['revision'] == trap['second'].revision and b',110.0,10,20' in trap['current']
    # and both legs read the first revision
    expect(report, {})
    for leg in OPHIOLITE:
        r = the(report, 'horizon-3d', 'Top', leg)
        assert r['evidence']['revision'] == trap['first']
        assert {x['at']: x['observed'] for x in r['examples'] if x['quantity'] == 'z'}['10,20'] == 105.0


# --- cleanup (R1-17) -------------------------------------------------------------------------------------------

def test_an_interrupt_after_the_first_upload_still_removes_the_work_folder_and_the_storage(journey_run):
    def uploaded(kind, obj): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt) as stopped:
        journey_run(hooks={'uploaded': uploaded})
    assert stopped.value.roundtrip_run == {'work_folder_removed': True, 'storage_removed': True}
    assert gone(journey_run, journey_run.target)


def test_an_extraction_failing_after_one_member_still_removes_the_work_folder_and_the_storage(journey_run, monkeypatch):
    def extractall(self, path=None, members=None, pwd=None):
        self.extract(self.infolist()[1], path)
        assert any(Path(path).rglob('.survey'))
        raise OSError('E138 test: the volume filled during extraction')
    monkeypatch.setattr(zipfile.ZipFile, 'extractall', extractall)
    with pytest.raises(OSError, match='volume filled') as stopped:
        journey_run()
    assert stopped.value.roundtrip_run == {'work_folder_removed': True, 'storage_removed': True}
    assert gone(journey_run, journey_run.target)


def test_a_drop_schema_that_does_nothing_leaves_storage_removed_false_and_the_report_refused(journey_run, monkeypatch):
    real = journey.drop_schema
    monkeypatch.setattr(journey, 'drop_schema', lambda db, schema: None)
    try:
        report, target = journey_run()
        assert report['run']['storage_removed'] is False and report['run']['work_folder_removed'] is True
        assert 'The run did not verify its storage removed, so the report is not clean.' in ev.evaluate(report)
        assert not storage_gone(target.projects[0].work)
    finally:
        import psycopg
        with psycopg.connect(os.environ['TEST_ORG_DATABASE_URL'], autocommit=True) as db: real(db, schema_for(journey_run.target.projects[0].work / 'journal'))
    assert storage_gone(target.projects[0].work)


# --- E138 s1 §5 mutations on the journey (strategy rev 5 D2-D4, D10) ------------------------------------------------

@pytest.mark.parametrize('change', ['survey file changed', 'survey file added', 'survey file deleted', 'archive bytes', 'archive mtime'])
def test_mutation_5_a_changed_survey_or_deposit_stops_the_run_with_no_judged_row(journey_run, change):
    """D3 (R1-13): the second digests differ, so the run stops: its sentence, no row, the work folder removed."""
    def survey(root):
        folder = Path(root) / 'Syn_Survey'
        if change == 'survey file changed': (folder / '.defs').write_bytes(b'Depth in feet: Yes\n')
        if change == 'survey file added': (folder / 'Proc').mkdir(); (folder / 'Proc' / 'new.par').write_bytes(b'')
        if change == 'survey file deleted': (folder / '.defs').unlink()
        if change == 'archive bytes': journey_run.archive.write_bytes(journey_run.archive.read_bytes()[:-1] + b'\0')
        if change == 'archive mtime': st = journey_run.archive.stat(); os.utime(journey_run.archive, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    report, target = journey_run(hooks={'survey': survey})
    assert report['run']['stopped'] == {'sentence': journey.SURVEY_CHANGED, 'differing': 1}
    assert report['rows'] == [] and report['findings'] == [] and ev.evaluate(report) == [] and ev.verdict(report, []) == 'stopped'
    assert (report['run']['survey_unchanged'], report['run']['archive_unchanged']) == ((False, True) if change.startswith('survey') else (True, False))
    assert gone(journey_run, target)


def test_mutation_5_a_failure_before_the_second_digest_writes_a_stopped_report(journey_run, service, tmp_path, capsys):
    def survey(root): raise OSError('E138 test: the volume went away')
    out = tmp_path / 'report.json'
    target = Target(service, journey_run.monkeypatch)
    code = journey.journey_main(journey_run.archive, journey_run.volume, target, oracle(), out, python=sys.executable, dataset='synthetic-s0', live=False,
                                exporter_env=exporter_env(), forbidden=[tmp_path / 'forbidden'], host='synthetic', hooks={'survey': survey})
    report = json.loads(out.read_text())
    assert code == 1 and report['run']['stopped'] == {'sentence': 'The run stopped before its second digest (OSError).', 'differing': 0}
    assert 'survey_unchanged' not in report['run'] and report['rows'] == [] and ev.evaluate(report) == []
    assert report['run']['work_folder_removed'] is True and report['run']['storage_removed'] is True and gone(journey_run, target)
    assert (out.stat().st_mode & 0o777) == 0o600 and 'journey: stopped: ' in capsys.readouterr().out


def waiting_oracle(not_listed=()):
    """The literal oracle with a listing of three 2D horizons (R2-2; lines are judged since E138 s2, fault sets since
    E138 s3, so the kind that waits is horizon-2d alone) and, maybe, kinds the survey could not list."""
    out = oracle()
    out['identities'] = [{'kind': 'horizon-2d', 'reported': ['horizon-2d'], 'object': n} for n in ('Sticks A', 'Sticks B', 'Faults A')]
    if not_listed: out['not_listed'] = [{'kind': k, 'class': 'read error'} for k in not_listed]
    return out


def test_mutations_11_and_12_each_listed_identity_waits_and_an_unlisted_kind_is_failed(journey_run):
    report, target = journey_run(the_oracle=waiting_oracle(['line-2d']))
    identities = {('horizon-2d', 'Sticks A', '*'): 'not-yet', ('horizon-2d', 'Sticks B', '*'): 'not-yet', ('horizon-2d', 'Faults A', '*'): 'not-yet'}
    clean = {k: s for k, s in CLEAN.items() if k[0] not in ('line-2d', 'horizon-2d')}
    assert states(report) == {**clean, **identities, ('line-2d', '*', '*'): 'failed'} and ev.evaluate(report) == []
    assert [the(report, *k)['evidence'] for k in identities] == [{'waits_on': 'E137 s6'}] * 3
    assert the(report, 'line-2d', '*', '*')['evidence'] == {'class': 'read error'}
    assert report['inventory']['not_listed'] == [{'kind': 'line-2d', 'class': 'read error'}]
    assert len(report['inventory']['enumerated']) == len(OBJECTS) + 3 and len(report['inventory']['selected']) == len(OBJECTS)
    assert gone(journey_run, target)


def test_f10_a_fault_set_the_export_never_saw_is_an_inventory_problem(journey_run):
    """E138 s3 F10 (s1 D4's coverage rule): a listed fault set the oracle does not enumerate stays in the inventory and
    has no row, so the evaluator finds its rows missing; nothing else changes."""
    the_oracle = oracle()
    the_oracle['identities'] = [{'kind': 'fault-sticks', 'reported': ['fault-sticks'], 'object': n} for n in ('SynF', 'SynF3D', 'SynF unseen')]
    report, target = journey_run(the_oracle=the_oracle)
    assert states(report) == CLEAN and {'kind': 'fault-sticks', 'object': 'SynF unseen'} in report['inventory']['enumerated']
    assert ev.evaluate(report) == ['fault-sticks SynF unseen %s: missing (a mandatory leg).' % leg for leg in ev.PER_OBJECT['fault-sticks']] + [
        'fault-sticks SynF unseen project-to-resinsight: missing (a leg with no route is stated as unsupported).',
        'The selected objects are not the enumerated ones less those whose every row waits (%d selected, %d expected).' % (len(OBJECTS), len(OBJECTS) + 1)]
    assert gone(journey_run, target)


def test_f11_a_run_with_no_fault_identity_writes_no_fault_finding_and_keeps_the_absent_row(journey_run):
    the_oracle = oracle()
    the_oracle['enumerated'] = [o for o in the_oracle['enumerated'] if o[0] != 'fault-sticks']
    report, target = journey_run(the_oracle=the_oracle)
    assert states(report) == clean_states([o for o in OBJECTS if o[0] != 'fault-sticks']) and ev.evaluate(report) == []
    assert the(report, 'fault-sticks', '*', '*')['evidence'] == {'enumeration': 'Fault3D.names, FaultStickSet.names'}
    assert report['findings'] == [] and journey.fault_findings([{'kind': 'fault-sticks', 'object': '*', 'leg': '*'}]) == []


def test_mutation_13_a_live_report_numbers_its_objects_and_keeps_no_name_or_refusal_words(journey_run):
    """D10 (R2-6): the exporter's refusal names Syn2; the report keeps its class, numbers the objects, and holds none
    of the survey's names, the refusal's words or a value of an example."""
    report, target = journey_run(variant='multicomponent', synthetic=False, journey='live-s1')
    text = json.dumps(report)
    for planted in ('Syn2', 'SYN-', 'SYN E', 'Top', 'Syn_Survey', 'GR', 'components; only', '500000', '“'):
        assert planted not in text, planted
    cubes = [r for r in report['rows'] if r['kind'] == 'seismic-3d' and r['leg'] in OPHIOLITE]
    assert sorted({r['object'] for r in cubes}) == ['seismic-3d #1', 'seismic-3d #2']
    assert {(r['object'], r['state'], r['evidence'].get('class')) for r in cubes if r['state'] == 'failed'} == {('seismic-3d #2', 'failed', 'components')}
    assert [f['class'] for f in report['findings']] == ['components', 'components', 'no route'] and {f['owner'] for f in report['findings']} == {'E129'}
    assert all(r['examples'] == [] for r in report['rows']) and gone(journey_run, target)


def traces_of(raw):
    head, width = raw[:3600], 260
    return head, [raw[at:at + width] for at in range(3600, len(raw), width)]


def test_mutation_4_a_permutation_of_intact_traces_passes_and_a_doubled_position_fails(journey_run):
    """D2 (R2-3): the cube is compared keyed by (inline, crossline), one inline at a time; traces in any order pass by
    design. A trace position written twice is a structure refusal of class `duplicate trace position`."""
    def reversed_traces(entry, raw):
        if entry != 'seismic/Syn.sgy': return raw
        head, traces = traces_of(raw)
        return head + b''.join(reversed(traces))
    report, _ = journey_run(hooks={'landed': reversed_traces})
    assert states(report)[('seismic-3d', 'Syn', 'opendtect-to-project')] == 'within'
    r = the(report, 'seismic-3d', 'Syn', 'opendtect-to-project')
    assert q(r, 'samples_sha256')['observed'] == digest('Syn') and q(r, 'traces')['observed'] == 16


def segy(traces, count=2):
    """A SEG-Y rev 1 file of float samples, as export.py lays it out: TRACES [(inline, crossline, x, y, [sample])]."""
    head = bytearray(3600)
    struct.pack_into('>H', head, 3216, 4000); struct.pack_into('>H', head, 3220, count); struct.pack_into('>h', head, 3224, 5)
    out = bytes(head)
    for i, c, x, y, samples in traces:
        th = bytearray(240)
        struct.pack_into('>h', th, 70, -100); struct.pack_into('>i', th, 180, round(x * 100)); struct.pack_into('>i', th, 184, round(y * 100))
        struct.pack_into('>i', th, 188, i); struct.pack_into('>i', th, 192, c); struct.pack_into('>h', th, 108, 100)
        out += bytes(th) + struct.pack('>%df' % count, *samples)
    return out


def test_mutation_4_the_journey_s_reader_holds_a_cube_by_position_one_inline_at_a_time(tmp_path):
    """D2: the landed file is read through an index of its trace headers (the gateway refuses a file with a position
    written twice before leg 1 reads it, so the reader's own refusal is shown on a file written here)."""
    path = tmp_path / 'c.sgy'
    path.write_bytes(segy([(12, 22, 1.0, 2.0, [3.0, 4.0]), (10, 20, 1.5, 2.5, [5.0, 6.0]), (10, 22, 0.5, 0.25, [7.0, 8.0])]))
    z, inlines, parts = journey.segy_parts(path)
    assert z == [100, 104.0, 4.0] and inlines == [10, 12]
    assert list(parts) == [(10, {(10, 20): (1.5, 2.5, [5.0, 6.0]), (10, 22): (0.5, 0.25, [7.0, 8.0])}), (12, {(12, 22): (1.0, 2.0, [3.0, 4.0])})]
    path.write_bytes(segy([(10, 20, 1.0, 2.0, [3.0, 4.0]), (12, 22, 1.0, 2.0, [3.0, 4.0]), (10, 20, 1.5, 2.5, [5.0, 6.0])]))
    with pytest.raises(journey.cmp.Duplicate) as doubled:
        list(journey.segy_parts(path)[2])
    assert journey.class_of(doubled.value) == 'duplicate trace position'
    assert journey.failed('seismic-3d', 'c', 'opendtect-to-project', None, doubled.value)['evidence'] == {
        'error': 'A trace position appears twice on one side.', 'class': 'duplicate trace position'}


def test_mutation_4_inlines_out_of_order_or_twice_on_one_side_are_refused():
    one = lambda *inlines: iter([(i, {}) for i in inlines])
    assert [i for i, _ in journey.merged(one(10, 14), one(12, 14))] == [10, 12, 14]
    with pytest.raises(journey.cmp.Duplicate): list(journey.merged(one(10, 10), one()))
    with pytest.raises(ValueError, match='ascending'): list(journey.merged(one(), one(12, 10)))


def test_a_log_is_read_by_its_las_mnemonic_in_capitals():
    """C3 live run: a mixed-case or spaced log name is read by the mnemonic the exporter writes and the project's LAS
    reader names (in capitals), never by its own name."""
    assert journey.mnemonic_of('P-wave Velocity') == 'P_WAVE_VELOCITY' and journey.mnemonic_of('GR') == 'GR'
    text = '~Curve\n DEPT.M : measured depth\n Gamma_ray.API : Gamma ray\n~ASCII\n10.0 50.5\n10.5 -999.25\n'
    depths, curves = journey.read_las(text)
    assert depths == [10.0, 10.5] and list(curves) == ['GAMMA_RAY'] and curves[journey.mnemonic_of('Gamma ray')][0] == 'API'


def test_the_data_root_gets_the_installation_omf_before_the_first_read(tmp_path):
    """C3 live run: odbind opens a data root only with its `.omf`; an extracted archive has none."""
    appl, root = tmp_path / 'appl', tmp_path / 'root'
    (appl / 'data').mkdir(parents=True); root.mkdir()
    (appl / 'data' / 'omf').write_text('template')
    journey.data_root(root, {})
    assert not (root / '.omf').exists()
    journey.data_root(root, {'DTECT_APPL': str(appl)})
    assert (root / '.omf').read_text() == 'template'
    (root / '.omf').write_text('own')
    journey.data_root(root, {'DTECT_APPL': str(appl)})
    assert (root / '.omf').read_text() == 'own'


# --- E138 s2: 2D lines (strategy rev 3 §2, §5, D1-D6) ------------------------------------------------------------

LINE_LEGS = ('opendtect-to-project', 'project-to-sdk')
EDGE_FRACTIONS = [0.10000000149011612, 0.0, None, -2.25]  # odbind's float32 of 0.1, written by hand
LONG = literal_line(list(range(1, 1026)), ref=[float(t) for t in range(1, 1026)], x=[500000.0 + 12.5 * t for t in range(1, 1026)],
                    y=[200.0 + 0.5 * t for t in range(1, 1026)], count=3)


def line_oracle(sources):
    """A literal oracle of 2D lines only: SOURCES {name: literal line, or None for a line the exporter refuses}."""
    return {'enumerated': [('line-2d', n) for n in sources], 'objects': {('line-2d', n): s for n, s in sources.items() if s is not None}}


def lines_run(journey_run, sources=None, **kw):
    """One journey of the lines SOURCES (default the four), its report checked by the evaluator."""
    report, target = journey_run(the_oracle=line_oracle(sources or {n: literal_line(t) for n, t in LINES.items()}), **kw)
    assert ev.evaluate(report) == [] and gone(journey_run, target)
    return report


def line_clean(names=LINES): return clean_states([('line-2d', n) for n in names])


def line_digest(trc, count=5):
    """The oracle's samples_sha256 of a line: float32 big-endian in sorted trace-number order, from the literal formula."""
    return hashlib.sha256(b''.join(struct.pack('>f', line_sample(t, k)) for t in sorted(trc) for k in range(count))).hexdigest()


def numbers(trc): return hashlib.sha256(b''.join(struct.pack('>i', t) for t in trc)).hexdigest()


def at_trace(n, count=5): return 3600 + n * (240 + 4 * count)


def on_line(name, change):
    """A `landed` hook (before the upload: both legs see it) changing the bytes of line NAME's file by CHANGE(bytearray)."""
    def landed(entry, raw):
        if entry != 'seismic2d/%s.sgy' % name: return raw
        out = bytearray(raw); change(out)
        return bytes(out)
    return landed


def downloaded(name_trc, change):
    """A `downloaded` hook (after the download: leg 1 only) changing the held file whose first trace number is NAME_TRC."""
    def hook(path):
        out = bytearray(path.read_bytes())
        if struct.unpack_from('>i', out, at_trace(0, struct.unpack_from('>H', out, 3220)[0]) + 20)[0] != name_trc: return
        change(out); path.write_bytes(bytes(out))
    return hook


def line_expect(report, changed, names=LINES):
    assert states(report) == {**line_clean(names), **changed}
    return report


def both_line(name, state): return {('line-2d', name, leg): state for leg in LINE_LEGS}


def test_the_clean_synthetic_run_with_the_four_lines_meets_the_hand_counted_record(journey_run):
    """§5 clean: every s1 row unchanged, each line's two judged legs within with the hand-counted values, its QGIS row
    waiting on the tool, its ResInsight row unsupported, and the three run-level findings once each (R2-5)."""
    report, target = journey_run(the_oracle=oracle(lines=True))
    check_clean(report, target, journey_run, clean=clean_states(OBJECTS + LINE_OBJECTS), objects=OBJECTS + LINE_OBJECTS)
    for name, trc in LINES.items():
        for leg in LINE_LEGS:
            r = the(report, 'line-2d', name, leg)
            exact = {x['name']: (x['expected'], x['observed']) for x in r['quantities'] if x['mode'] != 'tolerance'}
            assert exact['traces'] == (5, 5) and exact['order'] == exact['trace numbers'] == (numbers(trc), numbers(trc))
            assert exact['axes'] == ('100.0/4.0/5', '100.0/4.0/5') and exact['unit'] == ('ms', 'ms')
            assert exact['samples_sha256'] == (line_digest(trc), line_digest(trc)) and exact['null mask'] == ('none', 'none')
            for name_ in ('source points', 'x', 'y'):
                t = q(r, name_)
                assert (t['positions'], t['compared'], t['over_budget'], t['unmatched']) == (5, 5, 0, 0)
            points = {x['at']: (x['expected'], x['observed']) for x in r['examples'] if x['quantity'] == 'source points'}
            assert [points.get(str(t)) for t in trc] == [None if v is None else (v, v) for v in LINE_REF]  # absent on both sides: compared, no example
            if leg == 'project-to-sdk':
                assert exact['domain'] == ('time', 'time') and exact['original axes'] == ('100.0/4.0/5', '100.0/4.0/5')
                assert exact['original_sha256'][0] == exact['original_sha256'][1]
        assert the(report, 'line-2d', name, 'project-to-qgis')['evidence'] == {'waits_on': 'tool qgis'}
        assert the(report, 'line-2d', name, 'project-to-resinsight')['evidence'] == {'route': 'none'}
    routes = [f for f in report['findings'] if f['class'] == 'no route']
    assert [(f['step'], f['owner'], f['numbers'].split(':')[0]) for f in routes] == [
        ('line-2d project-to-qgis', 'E46', '4 lines'), ('line-2d project-to-resinsight', 'E129', '4 lines'), ('line-2d project-to-sdk', 'E51', '4 lines'),
        ('fault-sticks project-to-resinsight', 'E129', '2 sets')]  # E138 s3: the fault sets' one route finding
    assert report['findings'] == routes


def test_mutation_l16_a_run_without_a_line_writes_no_route_finding_and_keeps_its_absent_row(journey_run):
    """R2-11: the line-free enumeration keeps `line-2d * *` absent and emits no line finding."""
    report, target = journey_run()
    assert states(report)[('line-2d', '*', '*')] == 'absent' and [f['step'] for f in report['findings']] == ['fault-sticks project-to-resinsight']
    assert journey.line_findings([{'kind': 'line-2d', 'object': '*', 'leg': '*'}]) == []


def test_mutation_l1_one_x_two_quanta_off_disagrees_on_x_alone_on_both_legs(journey_run):
    def change(raw): struct.pack_into('>i', raw, at_trace(0) + 180, struct.unpack_from('>i', raw, at_trace(0) + 180)[0] + 2)
    report = lines_run(journey_run, hooks={'landed': on_line('Syn2D/L1', change)})
    line_expect(report, both_line('Syn2D/L1', 'disagree'))
    for leg in LINE_LEGS:
        r = the(report, 'line-2d', 'Syn2D/L1', leg)
        assert disagreeing(r) == ['x'] and (q(r, 'x')['over_budget'], q(r, 'x')['largest']['at']) == (1, '101')


def swap(a, b, count=5):
    def change(raw):
        w = 240 + 4 * count
        x, y = raw[at_trace(a, count):at_trace(a, count) + w], raw[at_trace(b, count):at_trace(b, count) + w]
        raw[at_trace(a, count):at_trace(a, count) + w], raw[at_trace(b, count):at_trace(b, count) + w] = y, x
    return change


def test_mutation_l2_two_traces_swapped_disagree_on_order_alone(journey_run):
    report = lines_run(journey_run, hooks={'landed': on_line('Syn2D/L1', swap(0, 3))})
    line_expect(report, both_line('Syn2D/L1', 'disagree'))
    for leg in LINE_LEGS:
        r = the(report, 'line-2d', 'Syn2D/L1', leg)
        assert disagreeing(r) == ['order'] and q(r, 'order')['observed'] == numbers([104, 102, 103, 101, 105])
        assert q(r, 'samples_sha256')['observed'] == line_digest(LINES['Syn2D/L1'])


def test_mutation_l3_a_reader_ignoring_the_source_point_scalar_disagrees_on_leg_1(journey_run, monkeypatch):
    """1.5 and 3.5 are written (15, -10) and (35, -10), the absent one (0, 0): read unscaled, 3 of 5 are over."""
    monkeypatch.setattr(journey, 'source_point', lambda value, scalar: float(value))
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])})
    line_expect(report, {('line-2d', 'Syn2D/L1', 'opendtect-to-project'): 'disagree'}, names=['Syn2D/L1'])
    r = the(report, 'line-2d', 'Syn2D/L1', 'opendtect-to-project')
    assert disagreeing(r) == ['source points'] and q(r, 'source points')['over_budget'] == 3


def test_mutation_l4_one_sample_s_last_mantissa_bit_disagrees_on_the_digest_alone(journey_run):
    def change(raw): raw[at_trace(2) + 240 + 4 * 3 + 3] ^= 1
    report = lines_run(journey_run, hooks={'landed': on_line('Other/L1', change)})
    line_expect(report, both_line('Other/L1', 'disagree'))
    for leg in LINE_LEGS: assert disagreeing(the(report, 'line-2d', 'Other/L1', leg)) == ['samples_sha256']


def test_mutation_l5_the_last_trace_dropped_disagrees_on_its_counts_and_leaves_its_positions_unmatched(journey_run):
    """R2-9: traces, order, trace numbers and the digest differ; source points, x and y hold the dropped trace on one
    side only (1 of 5 unmatched, over)."""
    def landed(entry, raw): return raw[:at_trace(4)] if entry == 'seismic2d/Syn2D/L2.sgy' else raw
    report = lines_run(journey_run, hooks={'landed': landed})
    line_expect(report, both_line('Syn2D/L2', 'disagree'))
    for leg in LINE_LEGS:
        r = the(report, 'line-2d', 'Syn2D/L2', leg)
        assert disagreeing(r) == ['order', 'samples_sha256', 'source points', 'trace numbers', 'traces', 'x', 'y']
        assert q(r, 'traces')['observed'] == 4
        for name in ('source points', 'x', 'y'): assert (q(r, name)['positions'], q(r, name)['unmatched'], q(r, name)['over_budget']) == (5, 1, 1)


def test_mutation_l6_a_trace_number_twice_is_the_reader_s_refusal_owned_by_e137(journey_run, tmp_path):
    """The reader directly (intake refuses a duplicate before upload, segy_line.py), then the downloaded input: leg 1
    failed with `duplicate trace position`, owner E137; the SDK leg (the project's original) within."""
    path = tmp_path / 'l.sgy'
    raw = bytearray(line_file([(1, (1, 1)), (2, (2, 1)), (1, (3, 1))]))
    path.write_bytes(bytes(raw))
    with open(path, 'rb') as f, pytest.raises(journey.cmp.Duplicate) as doubled: journey.segy_line_parts(f)
    assert journey.class_of(doubled.value) == 'duplicate trace position'
    def change(out): struct.pack_into('>i', out, at_trace(4) + 20, 101)
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])}, hooks={'downloaded': downloaded(101, change)})
    line_expect(report, {('line-2d', 'Syn2D/L1', 'opendtect-to-project'): 'failed'}, names=['Syn2D/L1'])
    assert the(report, 'line-2d', 'Syn2D/L1', 'opendtect-to-project')['evidence']['class'] == 'duplicate trace position'
    assert [f['owner'] for f in report['findings'] if f.get('class') == 'duplicate trace position'] == ['E137']


def test_c2_a_landed_line_the_project_cannot_read_back_fails_both_legs_owned_by_e139(journey_run, monkeypatch):
    """C2 (the live run: a landed line above 32 MiB is read whole by the project and refused): both judged legs
    `failed` with the SDK's refusal, the revision kept, both owned by E139; the other line stays within."""
    import ophiolite
    real = ophiolite.Client.read_data
    def read_data(self, asset, revision):
        if any(i['asset_id'] == asset and i['name'] == 'line-2d Syn2D/L2' for i in self.assets()):
            raise ophiolite.errors.IntegrityConflict('Stored data failed an integrity check. Ask the deployment administrator.')
        return real(self, asset, revision)
    monkeypatch.setattr(ophiolite.Client, 'read_data', read_data)
    sources = {n: literal_line(LINES[n]) for n in ('Syn2D/L1', 'Syn2D/L2')}
    report = lines_run(journey_run, sources=sources)
    line_expect(report, both_line('Syn2D/L2', 'failed'), names=sources)
    for leg in LINE_LEGS:
        r = the(report, 'line-2d', 'Syn2D/L2', leg)
        assert r['evidence']['class'] == 'other' and r['evidence']['revision']
    assert [f['owner'] for f in report['findings'] if f.get('class') == 'other'] == ['E139', 'E139']


def test_mutation_l7_the_delay_moved_disagrees_on_the_axes(journey_run):
    """Every trace's delay + 4 ms: leg 1's axes; the SDK's context and its original say 104 too (R2-4: both)."""
    def change(raw):
        for n in range(5): struct.pack_into('>h', raw, at_trace(n) + 108, 104)
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])}, hooks={'landed': on_line('Syn2D/L1', change)})
    line_expect(report, both_line('Syn2D/L1', 'disagree'), names=['Syn2D/L1'])
    assert disagreeing(the(report, 'line-2d', 'Syn2D/L1', 'opendtect-to-project')) == ['axes']
    r = the(report, 'line-2d', 'Syn2D/L1', 'project-to-sdk')
    assert disagreeing(r) == ['axes', 'original axes'] and q(r, 'axes')['observed'] == q(r, 'original axes')['observed'] == '104.0/4.0/5'


def sdk_changed(change):
    def hook(read): change(read); return read
    return hook


def test_mutation_l8_the_sdk_leg_reads_the_descriptor_s_geometry(journey_run):
    """A source point changed in the SDK's geometry only (after its own verification): the SDK leg disagrees on
    source points alone, leg 1 stays within; a leg reading geometry from the file would stay green."""
    def change(read): read.data['geometry'][1][1] = 9.0
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])}, hooks={'sdk_line': sdk_changed(change)})
    line_expect(report, {('line-2d', 'Syn2D/L1', 'project-to-sdk'): 'disagree'}, names=['Syn2D/L1'])
    r = the(report, 'line-2d', 'Syn2D/L1', 'project-to-sdk')
    assert disagreeing(r) == ['source points'] and (q(r, 'source points')['over_budget'], q(r, 'source points')['largest']['at']) == (1, '102')
    assert [f['owner'] for f in report['findings'] if f.get('class') is None] == ['E51']


@pytest.mark.parametrize('field, value, quantity', [('first_sample', 104.0, 'axes'), ('sample_interval', 8.0, 'axes'), ('samples', 4, 'axes'),
                                                    ('z_domain', 'depth', 'domain'), ('sample_unit', 'm', 'unit')])
def test_mutations_r2_7_and_l17_a_descriptor_only_change_disagrees_on_its_quantity_alone(journey_run, field, value, quantity):
    """R2-7, L17: one SDK context field changed, the original's bytes valid: only that quantity on the SDK leg; the
    original's axes, read by the journey, agree."""
    def change(read): read.context[field] = value
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])}, hooks={'sdk_line': sdk_changed(change)})
    line_expect(report, {('line-2d', 'Syn2D/L1', 'project-to-sdk'): 'disagree'}, names=['Syn2D/L1'])
    assert disagreeing(the(report, 'line-2d', 'Syn2D/L1', 'project-to-sdk')) == [quantity]


def test_mutation_l9_a_line_s_qgis_row_dropped_or_stated_unsupported_is_refused(journey_run):
    report = lines_run(journey_run, sources={'Syn2D/L1': literal_line(LINES['Syn2D/L1'])})
    rows = report['rows']
    dropped = {**report, 'rows': [r for r in rows if (r['kind'], r['leg']) != ('line-2d', 'project-to-qgis')]}
    assert 'line-2d Syn2D/L1 project-to-qgis: missing (a mandatory leg).' in ev.evaluate(dropped)
    unsupported = {**report, 'rows': [dict(r, state='unsupported', evidence={'route': 'none'}) if r['leg'] == 'project-to-qgis' else r for r in rows]}
    assert 'line-2d Syn2D/L1 project-to-qgis: a mandatory leg cannot be unsupported.' in ev.evaluate(unsupported)


EDGE_REFUSED = {'Edge/two': 'components', 'Edge/nan': 'undefined samples', 'Edge/undefined': 'undefined samples', 'Edge/dupe': 'other',
                'Edge/half': 'sampling', 'Edge/sp5': 'other', 'Edge/far': 'other', 'Edge/absent65': 'other'}


def test_mutation_l10_the_exporter_s_line_refusals_fail_both_legs_owned_by_e137_and_f32stop_lands(journey_run):
    """R2-10: each refused line fails its two judged legs with the exporter's class (EXPORTER_SAID's three templates,
    else `other`), both owned by E137; its QGIS row still waits on the tool (R2-6, with a tools object) and its
    ResInsight row is unsupported. Edge/f32stop, one float32 step past its last sample, lands within."""
    sources = {**{n: None for n in EDGE_REFUSED}, 'Edge/f32stop': literal_line([1, 2], ref=[1.0, 2.0], count=3)}
    tools = journey.SecondTools(host='synthetic', stray_roots=[])
    report = lines_run(journey_run, sources=sources, variant='edge', tools=tools)
    line_expect(report, {k: 'failed' for n in EDGE_REFUSED for k in both_line(n, 'failed')}, names=sources)
    for name, cls in EDGE_REFUSED.items():
        for leg in LINE_LEGS: assert the(report, 'line-2d', name, leg)['evidence']['class'] == cls, name
    refused = [f for f in report['findings'] if f.get('class') != 'no route']
    assert len(refused) == 2 * len(EDGE_REFUSED) and {f['owner'] for f in refused} == {'E137'}
    assert the(report, 'line-2d', 'Edge/f32stop', 'project-to-sdk')['state'] == 'within'
    assert q(the(report, 'line-2d', 'Edge/f32stop', 'opendtect-to-project'), 'axes')['observed'] == '100.0/4.0/3'


@pytest.mark.parametrize('double', [None, 'float64', 'zero read as absent'])
def test_mutation_l13_fractional_source_points_compare_as_float32(journey_run, monkeypatch, double):
    """R1-4: Edge/fractions (0.1, a present zero, absent, -2.25) within on both legs; a float64 comparison puts 1 of 4
    over on both, a reader taking (0, 1) for absent 1 of 4 on leg 1."""
    sources = {'Edge/fractions': literal_line([1, 2, 3, 4], ref=EDGE_FRACTIONS, count=3)}
    if double == 'float64': monkeypatch.setattr(journey.cmp, 'float32', lambda v: v)
    if double == 'zero read as absent': monkeypatch.setattr(journey, 'source_point', lambda value, scalar: None if value == 0 else journey._scaled(value, scalar))
    report = lines_run(journey_run, sources=sources, variant='edge')
    legs = {None: (), 'float64': LINE_LEGS, 'zero read as absent': ('opendtect-to-project',)}[double]
    line_expect(report, {('line-2d', 'Edge/fractions', leg): 'disagree' for leg in legs}, names=sources)
    for leg in legs:
        r = the(report, 'line-2d', 'Edge/fractions', leg)
        largest = q(r, 'source points')['largest']
        assert disagreeing(r) == ['source points'] and q(r, 'source points')['over_budget'] == 1
        assert (largest['at'], largest['value'] is None) == (('1', False) if double == 'float64' else ('2', True))


def renumber_last(out): struct.pack_into('>i', out, at_trace(1024, 3) + 20, 3)
def last_sample(raw): raw[at_trace(1024, 3) + 240 + 8] ^= 1


@pytest.mark.parametrize('mutation', [None, 'swap across 1,024', 'duplicate across chunks', 'last chunk sample'])
def test_mutations_l14_l15_a_line_of_1025_traces_is_keyed_across_its_chunks(journey_run, mutation):
    """R1-5: Long/L (one chunk past 1,024): clean within; ordinals 1 and 1,025 swapped disagree on order alone; trace
    1,025 renumbered 3 in the downloaded file is a duplicate across chunks (leg 1 failed, E137); one sample of the last
    trace changed disagrees on the digest alone."""
    sources = {'Long/L': LONG}
    hooks = {None: {}, 'swap across 1,024': {'landed': on_line('Long/L', swap(0, 1024, 3))}, 'duplicate across chunks': {'downloaded': downloaded(1, renumber_last)},
             'last chunk sample': {'landed': on_line('Long/L', last_sample)}}[mutation]
    report = lines_run(journey_run, sources=sources, variant='long', hooks=hooks)
    if mutation is None:
        line_expect(report, {}, names=sources)
        assert q(the(report, 'line-2d', 'Long/L', 'project-to-sdk'), 'traces')['observed'] == 1025
    elif mutation == 'duplicate across chunks':
        line_expect(report, {('line-2d', 'Long/L', 'opendtect-to-project'): 'failed'}, names=sources)
        assert the(report, 'line-2d', 'Long/L', 'opendtect-to-project')['evidence']['class'] == 'duplicate trace position'
        assert [f['owner'] for f in report['findings'] if f.get('class') == 'duplicate trace position'] == ['E137']
    else:
        line_expect(report, both_line('Long/L', 'disagree'), names=sources)
        for leg in LINE_LEGS: assert disagreeing(the(report, 'line-2d', 'Long/L', leg)) == (['order'] if mutation.startswith('swap') else ['samples_sha256'])


class Chunked(dict):
    """R2-8: a literal line oracle handing its lines over as the read CLI does (`line_chunks`, at most 1,024 traces),
    with the chunks in the order ORDER and, maybe, one trace number rewritten (REWRITE (chunk, index, number))."""
    def __init__(self, sources, order=None, rewrite=None):
        super().__init__(line_oracle(sources))
        self.order, self.rewrite = order, rewrite

    def line_chunks(self, name):
        src = self['objects'][('line-2d', name)]
        traces = src['traces']
        chunks = [{'first': n, 'trc': [t[0] for t in traces[n:n + 1024]], 'ref': [t[1] for t in traces[n:n + 1024]], 'x': [t[2] for t in traces[n:n + 1024]],
                   'y': [t[3] for t in traces[n:n + 1024]], 'samples': [[t[4] for t in traces[n:n + 1024]]]} for n in range(0, len(traces), 1024)]
        if self.rewrite: chunks[self.rewrite[0]]['trc'][self.rewrite[1]] = self.rewrite[2]
        if self.order: chunks = [chunks[n] for n in self.order]
        header = {'z': [src['z'][0], None, src['z'][1]], 'zunit': src['unit'], 'zdomain': 'twt'}
        return header, iter(chunks)


@pytest.mark.parametrize('chunks', ['as the CLI writes them', 'reversed', 'a trace number repeated'])
def test_mutation_r2_8_the_oracle_s_chunks_are_keyed_over_the_whole_line(journey_run, chunks):
    """The expected side's chunks: in the CLI's order within; reversed, only `order` disagrees on both legs; a trace
    number repeated in the second chunk is a duplicate across chunks (both legs failed, its class)."""
    sources = {'Long/L': LONG}
    the_oracle = {'as the CLI writes them': Chunked(sources), 'reversed': Chunked(sources, order=[1, 0]), 'a trace number repeated': Chunked(sources, rewrite=(1, 0, 3))}[chunks]
    report, _ = journey_run(the_oracle=the_oracle, variant='long')
    assert ev.evaluate(report) == []
    changed = {'as the CLI writes them': {}, 'reversed': both_line('Long/L', 'disagree'), 'a trace number repeated': both_line('Long/L', 'failed')}[chunks]
    assert states(report) == {**line_clean(sources), **changed}
    for leg in LINE_LEGS:
        r = the(report, 'line-2d', 'Long/L', leg)
        if chunks == 'reversed': assert disagreeing(r) == ['order']
        if chunks == 'a trace number repeated': assert r['evidence']['class'] == 'duplicate trace position'


@pytest.mark.parametrize('when', ['after the spool is written', 'during the keyed digest'])
def test_mutation_r2_12_an_interrupt_after_the_spool_or_during_the_keyed_digest_still_removes_everything(journey_run, monkeypatch, when):
    seen, hooks = [], {}
    if when == 'after the spool is written':
        def spooled(path): seen.append(path.exists()); raise KeyboardInterrupt
        hooks = {'line_spooled': spooled}
    else:
        real = journey.Line.digests
        def digests(self):
            if str(getattr(self.source, 'name', '')).endswith('.f32'): seen.append(os.path.exists(self.source.name)); raise KeyboardInterrupt
            return real(self)
        monkeypatch.setattr(journey.Line, 'digests', digests)
    with pytest.raises(KeyboardInterrupt) as stopped:
        journey_run(the_oracle=line_oracle({'Syn2D/L1': literal_line(LINES['Syn2D/L1'])}), hooks=hooks)
    assert seen == [True] and stopped.value.roundtrip_run == {'work_folder_removed': True, 'storage_removed': True}
    assert gone(journey_run, journey_run.target)


def line_file(traces, interval=4000, count=2, delay=100):
    """A segy-line/1 file written here (independent of the exporter): TRACES [(trace number, (source point value,
    scalar))], x = 500000 + 10 t, y = 10 t (hundredths, scalar -100), samples t + k / 4."""
    head = bytearray(3600)
    struct.pack_into('>H', head, 3216, interval); struct.pack_into('>H', head, 3220, count); struct.pack_into('>h', head, 3224, 5)
    out = bytes(head)
    for t, (sp, scalar) in traces:
        th = bytearray(240)
        struct.pack_into('>i', th, 20, t); struct.pack_into('>h', th, 70, -100); struct.pack_into('>h', th, 108, delay)
        struct.pack_into('>i', th, 180, (500000 + 10 * t) * 100); struct.pack_into('>i', th, 184, 10 * t * 100)
        struct.pack_into('>i', th, 196, sp); struct.pack_into('>h', th, 200, scalar)
        out += bytes(th) + struct.pack('>%df' % count, *(t + k / 4 for k in range(count)))
    return out


def test_mutation_l12_two_differently_sampled_lines_keep_their_own_axes_through_both_comparisons():
    """R2-2: a 4 ms and an 8 ms line of the same traces and samples, each through leg 1's reader and the SDK leg's
    comparison; judged against the other line's expected side, only the axes disagree."""
    table = ev.load()
    traces = [(1, (15, -10)), (2, (0, 0)), (3, (0, 1))]
    expected = {}
    for interval in (4000, 8000):
        raw = line_file(traces, interval=interval)
        src = journey.Line(io.BytesIO(raw), 2, '100.0/%r/2' % (interval / 1000), 'ms', 'time')
        for n, (t, _) in enumerate(traces): src.add(t, [1.5, None, 0.0][n], 500000.0 + 10 * t, 10.0 * t, at_trace(n, 2) + 240)
        expected[interval] = src
    for interval, other in ((4000, 8000), (8000, 4000)):
        raw = line_file(traces, interval=interval)
        leg1 = journey.compared(table, 'line-2d', 'L', 'opendtect-to-project', None, journey.line_pairs(expected[interval], journey.segy_line_parts(io.BytesIO(raw), 'ms')), True)
        assert leg1['state'] == 'within', leg1
        read = type('Read', (), {'context': {'first_sample': 100.0, 'sample_interval': interval / 1000, 'samples': 2, 'sample_unit': 'ms', 'z_domain': 'time'},
                                 'original': raw, 'geometry': [[t, [1.5, None, 0.0][n], 500000.0 + 10 * t, 10.0 * t] for n, (t, _) in enumerate(traces)]})()
        sha = hashlib.sha256(raw).hexdigest()
        assert journey.judge_sdk_line(table, expected[interval], read, sha, None, True, {'revision': 'r'}, 'L')['state'] == 'within'
        assert disagreeing(journey.compared(table, 'line-2d', 'L', 'opendtect-to-project', None,
                                            journey.line_pairs(expected[other], journey.segy_line_parts(io.BytesIO(raw), 'ms')), True)) == ['axes']
        assert disagreeing(journey.judge_sdk_line(table, expected[other], read, sha, None, True, {'revision': 'r'}, 'L')) == ['axes', 'original axes']


# --- E138 s5 C1: every write of a cube is bounded (strategy rev 2 §2, §5 C1a-C1i, D1) ------------------------------
# export.py's float32 SEG-Y of the fake's cubes, counted by hand: 3,600 header bytes, then per trace 240 + 4 x 5 samples
SEGY_BYTES = {'Syn': 3600 + 16 * (240 + 4 * 5), 'Syn2': 3600 + 4 * (240 + 4 * 5)}
assert SEGY_BYTES == {'Syn': 7760, 'Syn2': 4640}


def too_large(report, cube, bound, phase, limit, observed):
    """Both judged legs of CUBE failed by BOUND at PHASE with its numbers, and one E140 finding for the cube."""
    for leg in OPHIOLITE:
        r = the(report, 'seismic-3d', cube, leg)
        assert r['state'] == 'failed' and r['evidence']['class'] == 'too large', r
        assert r['evidence']['too_large'] == {'bound': bound, 'phase': phase, 'limit': limit, 'observed': observed}
    assert [f for f in report['findings'] if f['step'].startswith('seismic-3d %s ' % cube)] == [
        {'step': 'seismic-3d %s opendtect-to-project' % cube, 'owner': 'E140', 'sent': None, 'class': 'too large',
         'numbers': '%s at %s: %d above %d' % (bound, phase, observed, limit)}]


def watched(more=None):
    """(seen, hooks): the uploads, and at each upload the stages left in the exports folder (only the current one)."""
    seen = {'uploaded': [], 'stages': []}
    def settled(root): seen['work'] = Path(root).parent
    def uploaded(kind, obj):
        seen['uploaded'].append((kind, obj))
        seen['stages'].append(sorted(p.name for p in (seen['work'] / 'exports').iterdir() if p.is_dir()))
    return seen, {'settled': settled, 'uploaded': uploaded, **(more or {})}


@pytest.mark.parametrize('traces', [None, '17'])  # C1b: a trace bound above the cube's 16 traces, so the bytes alone decide
def test_s5_c1a_a_cube_above_file_bytes_is_too_large_unlanded_and_the_run_goes_on(journey_run, traces):
    journey_run.monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', '6000')
    if traces: journey_run.monkeypatch.setenv('OPHIOLITE_MAX_SEISMIC_TRACES', traces)
    seen, hooks = watched()
    report, target = journey_run(hooks=hooks)
    expect(report, both('seismic-3d', 'Syn', 'failed'))
    too_large(report, 'Syn', 'file_bytes', 'export', 6000, 6001)  # the cap stopped the child one byte past the bound
    assert ('seismic-3d', 'Syn') not in seen['uploaded'] and ('seismic-3d', 'Syn2') in seen['uploaded']
    assert all(len(stages) == 1 for stages in seen['stages'])  # the stopped cube's stage and partial file are gone
    assert ev.evaluate(report) == [] and gone(journey_run, target)
    if traces: return
    # C1h: the evaluator holds the bound to its row: not above its limit, or on another kind, is a problem
    bad = json.loads(json.dumps(report))
    the(bad, 'seismic-3d', 'Syn', 'project-to-sdk')['evidence']['too_large']['observed'] = 6000
    well = the(bad, 'well-path', 'SYN-A', 'opendtect-to-project')
    well.update(state='failed', quantities=[], examples=[], evidence={'error': 'x', 'class': 'too large', 'too_large': dict(the(report, 'seismic-3d', 'Syn', 'project-to-sdk')['evidence']['too_large'])})
    del the(bad, 'seismic-3d', 'Syn', 'opendtect-to-project')['evidence']['too_large']
    problems = ev.evaluate(bad)
    assert [p for p in problems if 'too large' in p or 'bound' in p] == [
        'seismic-3d Syn opendtect-to-project: too large without the bound, phase and numbers it was stopped at.',
        'seismic-3d Syn project-to-sdk: only a failed cube observed above its bound carries the bound (too large).',
        'well-path SYN-A opendtect-to-project: only a failed cube observed above its bound carries the bound (too large).'], problems


@pytest.mark.parametrize('file_bytes, lands', [(SEGY_BYTES['Syn'], True), (SEGY_BYTES['Syn'] - 1, False)])
def test_s5_c1c_a_cube_of_exactly_file_bytes_lands_and_one_byte_more_is_too_large(journey_run, file_bytes, lands):
    journey_run.monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(file_bytes))
    report, target = journey_run()
    if lands: expect(report, {})
    else:
        expect(report, both('seismic-3d', 'Syn', 'failed'))
        too_large(report, 'Syn', 'file_bytes', 'export', file_bytes, file_bytes + 1)
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_c1d_a_cube_above_max_traces_is_too_large_before_it_is_uploaded(journey_run):
    journey_run.monkeypatch.setenv('OPHIOLITE_MAX_SEISMIC_TRACES', '10')  # Syn holds 16 traces, Syn2 4
    seen, hooks = watched()
    report, target = journey_run(hooks=hooks)
    expect(report, both('seismic-3d', 'Syn', 'failed'))
    too_large(report, 'Syn', 'max_traces', 'export', 10, 16)
    assert ('seismic-3d', 'Syn') not in seen['uploaded'] and ('seismic-3d', 'Syn2') in seen['uploaded']
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def used(work):
    """Bytes the run holds in its work folder beside the unpacked survey: exports, landed and saved files, payloads."""
    return sum(p.stat().st_size for p in Path(work).rglob('*') if p.is_file() and not p.is_symlink() and 'survey' not in p.relative_to(work).parts[:1])


# E138 s5 C1e: the bytes the volume gives the run's files beyond what it holds at the first measurement. Measured on
# the default fake (2 Nov 2026), the folder then holds 9,039, 20,803, 28,563, 31,725 and 37,647 bytes more at the next
# five: Syn's SDK export needs 7,760 within 42,000 - 28,563, Syn2's export 4,640 within 42,000 - 31,725, and Syn2's
# landing 11,600, above 42,000 - 37,647
BUDGET = 42_000


def test_s5_c1e_retained_artifacts_count_against_a_later_cube(journey_run):
    """The allowance is measured live (free bytes = the budget less what the work folder holds), so Syn's payloads and
    saved slices, still held, leave too little for Syn2's landing, the sixth measurement (each cube: export,
    landing, download, SDK export); Syn passes every phase with the same budget."""
    seen, calls = {}, []
    def settled(root): seen['work'] = Path(root).parent
    def free():
        calls.append(used(seen['work']))
        return journey.RESERVE + BUDGET - (calls[-1] - calls[0])
    report, target = journey_run(hooks={'settled': settled, 'free_bytes': free})
    need = math.ceil(journey.LANDING_FACTOR * SEGY_BYTES['Syn2'])
    assert len(calls) == 6 and calls[5] - calls[0] > BUDGET - need  # Syn's held files take what Syn2's landing needed
    expect(report, both('seismic-3d', 'Syn2', 'failed'))
    too_large(report, 'Syn2', 'volume', 'landing', BUDGET - (calls[5] - calls[0]), need)
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_c1e_no_allowance_before_a_phase_stops_the_run_and_says_why(journey_run):
    count = []
    def empty(): count.append(1); return journey.RESERVE + (10 ** 9 if len(count) < 2 else 0)
    with pytest.raises(journey.wf.VolumeExhausted) as stopped:
        journey_run(hooks={'free_bytes': empty})
    assert stopped.value.roundtrip_run == {'work_folder_removed': True, 'storage_removed': True}
    assert gone(journey_run, journey_run.target)
    stop = journey.stopped_report(stopped.value, journey_run.archive, dataset='synthetic-s0', synthetic=True, journey='synthetic-s0', host='synthetic')
    assert stop['run']['stopped']['sentence'] == journey.VOLUME_GONE % (journey.RESERVE, journey.RESERVE)
    assert ev.verdict(stop, ev.evaluate(stop)) == 'stopped'


FAKE_EXPORT = '''import sys, time
from pathlib import Path
stage, how = Path(sys.argv[3]), sys.argv[sys.argv.index('--objects') + 1]
if how == '"slow"':
    (stage / 'part.sgy').write_bytes(b'x' * 5); time.sleep(30)
(stage / 'part.sgy').write_bytes(b'x' * (100 if how == '"big"' else 5))
print('The fake exporter refuses this object.', file=sys.stderr); sys.exit(2)
'''


@pytest.mark.parametrize('how', ['big', 'small', 'slow'])
def test_s5_c1g_the_cap_stops_only_what_it_bounds(tmp_path, how):
    """C1a, C1g at the child: a file stopped at the cap is TooLarge whatever the child printed; a refusal below it
    stays the exporter's; a timeout under the cap stays a timeout and the child's group is killed."""
    pkg = tmp_path / 'fake-exporter' / 'ophiolite_opendtect'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text(''); (pkg / 'export.py').write_text(FAKE_EXPORT)
    volume = tmp_path / 'cap-volume'; volume.mkdir()
    work = journey.wf.WorkFolder.create(volume, [tmp_path / 'forbidden'])
    try:
        stage = work.path / 'exports' / '0'
        stage.mkdir(parents=True)
        env = {**os.environ, 'PYTHONPATH': str(tmp_path / 'fake-exporter')}
        call = lambda: journey.export_child(work, sys.executable, env, work.path, 'S', stage, how, 0.15, 3, ('file_bytes', 50))  # noqa: E731
        if how == 'big':
            with pytest.raises(journey.wf.TooLarge) as big: call()
            assert big.value.evidence() == {'bound': 'file_bytes', 'phase': 'export', 'limit': 50, 'observed': 51}
            assert (stage / 'part.sgy').stat().st_size == 51
        elif how == 'small':
            with pytest.raises(journey.Refusal, match='The fake exporter refuses this object.'): call()
        else:
            with pytest.raises(journey.subprocess.TimeoutExpired): call()
            assert work.survivors() == []
    finally:
        assert work.close()
    assert os.listdir(volume) == []


# --- E138 s5 C2: time-depth models go round (§5 T1-T14), from hand-written tables beside the survey ---------------
TD_A = b'depth,time\n100.0,0.1\n200.0,0.18\n300.0,0.25\n400.0,0.31\n'  # §5: comma, header line 1
TD_B = b'checkshots, hand written\r\nTWT\tMD\tnote\r\n5.0\t50.0\tx\r\n9.0\t90.0\ty\r\n\r\n12.0\t120.0\tz\r\n'  # tab, header line 2, ms
TD_PAIRS = {'SYN-A': [(100.0, 0.1), (200.0, 0.18), (300.0, 0.25), (400.0, 0.31)], 'SYN-B': [(50.0, 5.0), (90.0, 9.0), (120.0, 12.0)]}
TD_LANDED = {'SYN-A': TD_A, 'SYN-B': b'depth,time\n50.0,5.0\n90.0,9.0\n120.0,12.0\n'}  # time-depth-csv/1, each cell's text unchanged
TD_MEMBERS = {'checkshots/A.csv': TD_A, 'checkshots/B.txt': TD_B}
TD_WRONG = 'The time-depth model of %s: %s on data row 3 does not increase; pairs must be in strictly increasing %s. No repair was applied. Nothing was sent.'
TD_ROUTE = 'the starter imports no time-depth model into ResInsight'


def td_entry(member, header_line, delimiter, depth, time, unit='s'):
    return {'member': member, 'header_line': header_line, 'delimiter': delimiter, 'depth': depth, 'time': time,
            'decisions': {'domain': 'one-way time in %s' % unit, 'depth-kind': 'TVDSS', 'units': 'm', 'vertical-datum': 'MSL'}}


TD_DEF = {'SYN-A': td_entry('checkshots/A.csv', 1, 'comma', 'depth', 'time'), 'SYN-B': td_entry('checkshots/B.txt', 2, 'tab', 'MD', 'TWT', 'ms')}
TD_DECLARED = {'SYN-A': ('tvdss', 'm', 'one-way', 's', 'MSL'), 'SYN-B': ('tvdss', 'm', 'one-way', 'ms', 'MSL')}


def td_pairs_digest(pairs): return hashlib.sha256(b''.join(struct.pack('>dd', d, t) for d, t in pairs)).hexdigest()


def td_archive(members):
    """zipped() with MEMBERS ({name: bytes}) beside the survey folder."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zipped())) as src, zipfile.ZipFile(out, 'w') as z:
        for info in src.infolist(): z.writestr(info, src.read(info))
        for name, raw in members.items(): z.writestr(zipfile.ZipInfo(name, (2026, 11, 2, 0, 0, 0)), raw)
    return out.getvalue()


def td_run(journey_run, definition=TD_DEF, members=TD_MEMBERS, **kw):
    journey_run.archive.write_bytes(td_archive(members))
    return journey_run(time_depth=definition, **kw)


def td_clean(models=('SYN-A', 'SYN-B'), wells=3):
    """§5: every s4 row as CLEAN; each model's two judged legs equal and its ResInsight leg unsupported; the kind-level
    row unsupported when some survey well has no defined table, and no not-yet row."""
    out = {k: s for k, s in CLEAN.items() if k[0] != 'time-depth'}
    for m in models: out.update({('time-depth', m, 'opendtect-to-project'): 'equal', ('time-depth', m, 'project-to-sdk'): 'equal',
                                 ('time-depth', m, 'project-to-resinsight'): 'unsupported'})
    if wells: out[('time-depth', '*', '*')] = 'unsupported'
    return out


def td_expect(report, changed, **kw):
    assert states(report) == {**td_clean(**kw), **changed}
    return report


def td_both(well, state): return {('time-depth', well, leg): state for leg in OPHIOLITE}


def td_findings(report): return [f for f in report['findings'] if f['step'].startswith('time-depth')]


def td_values(r): return [(x['name'], x['expected'], x['observed']) for x in r['quantities'] if x['mode'] != 'tolerance']


def test_s5_c2_the_clean_run_with_two_tables_meets_the_hand_counted_record(journey_run):
    """§5 acceptance: 2 models x 2 legs equal (pairs and declarations), 2 ResInsight unsupported, one kind-level row of
    3 wells, one E129 finding, `time_depth` {true, 2, 5}; every s4 row unchanged; T13 on the clean report."""
    uploads = []
    report, target = td_run(journey_run, hooks={'td_uploading': uploads.append})
    assert ev.evaluate(report) == [] and gone(journey_run, target)
    td_expect(report, {})
    assert uploads == ['SYN-A', 'SYN-B']
    assert report['time_depth'] == {'definition': True, 'models': 2, 'survey_wells': 5, 'outside': 0}
    assert the(report, 'time-depth', '*', '*')['evidence'] == {'route': 'none', 'wells': 3}
    assert td_findings(report) == [{'step': 'time-depth project-to-resinsight', 'numbers': '2 models: ' + TD_ROUTE, 'owner': 'E129', 'sent': None, 'class': 'no route'}]
    for well, pairs in TD_PAIRS.items():
        n, digest_ = len(pairs), td_pairs_digest(pairs)
        leg1 = the(report, 'time-depth', well, 'opendtect-to-project')
        assert td_values(leg1) == [('pairs', n, n), ('pairs_sha256', digest_, digest_)] + [
            (k, v, v) for k, v in zip(('depth_type', 'depth_unit', 'time_kind', 'time_unit', 'datum'), TD_DECLARED[well])]
        sdk = the(report, 'time-depth', well, 'project-to-sdk')
        original = hashlib.sha256(TD_LANDED[well]).hexdigest()
        assert td_values(sdk) == [('original_sha256', original, original), ('pairs', n, n), ('pairs_sha256', digest_, digest_)]
        for r in (leg1, sdk):
            assert all(q(r, c)['over_budget'] == 0 and q(r, c)['compared'] == n and q(r, c)['budget'] == 0.0 for c in ('depth', 'time'))
            assert [(x['at'], x['expected']) for x in r['examples'] if x['quantity'] == 'depth'] == [(str(k + 1), d) for k, (d, _) in enumerate(pairs)]
        assert the(report, 'time-depth', well, 'project-to-resinsight')['evidence'] == {'route': 'none'}
    # T13: one model's SDK row removed and the kind-level count changed to 2, two problems, each naming its cause
    broken = json.loads(json.dumps(report))
    broken['rows'] = [r for r in broken['rows'] if (r['kind'], r['object'], r['leg']) != ('time-depth', 'SYN-B', 'project-to-sdk')]
    the(broken, 'time-depth', '*', '*')['evidence']['wells'] = 2
    problems = ev.evaluate(broken)
    assert len(problems) == 2, problems
    assert any('time-depth SYN-B project-to-sdk: missing (a mandatory leg)' in p for p in problems)
    assert any(p.startswith('time-depth * *:') and 'wells 3' in p for p in problems)


def test_s5_t1_one_time_1e_9_off_disagrees_on_the_digest_and_its_time_on_both_legs(journey_run):
    hooks = {'td_landed': lambda well, body: body.replace(b'200.0,0.18\n', b'200.0,0.180000001\n') if well == 'SYN-A' else body}
    report, target = td_run(journey_run, hooks=hooks)
    td_expect(report, td_both('SYN-A', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'time-depth', 'SYN-A', leg)
        assert disagreeing(r) == ['pairs_sha256', 'time'] and q(r, 'time')['over_budget'] == 1 and q(r, 'depth')['over_budget'] == 0
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t2_the_last_pair_dropped_disagrees_on_its_count_and_leaves_its_position_unmatched(journey_run):
    hooks = {'td_landed': lambda well, body: body.replace(b'400.0,0.31\n', b'') if well == 'SYN-A' else body}
    report, target = td_run(journey_run, hooks=hooks)
    td_expect(report, td_both('SYN-A', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, 'time-depth', 'SYN-A', leg)
        assert disagreeing(r) == ['depth', 'pairs', 'pairs_sha256', 'time'] and (q(r, 'pairs')['expected'], q(r, 'pairs')['observed']) == (4, 3)
        assert all(q(r, c)['unmatched'] == 1 and q(r, c)['compared'] == 3 for c in ('depth', 'time'))
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t3_two_pairs_swapped_in_the_held_original_disagree_where_they_sit(journey_run):
    """A comparison by sorted value would pass this; the pairs are keyed by ordinal and digested in file order."""
    def swap(well, held):
        if well == 'SYN-A': held.write_bytes(held.read_bytes().replace(b'100.0,0.1\n200.0,0.18\n', b'200.0,0.18\n100.0,0.1\n'))
    report, target = td_run(journey_run, hooks={'td_held': swap})
    td_expect(report, {('time-depth', 'SYN-A', 'opendtect-to-project'): 'disagree'})
    r = the(report, 'time-depth', 'SYN-A', 'opendtect-to-project')
    assert disagreeing(r) == ['depth', 'pairs_sha256', 'time'] and q(r, 'pairs')['state'] == 'agree'
    assert sorted(x['at'] for x in r['examples'] if x['quantity'] == 'depth' and x['expected'] != x['observed']) == ['1', '2']
    assert ev.evaluate(report) == [] and gone(journey_run, target)


TD_C = b'depth,time\n100.0,0.1\n200.0,0.18\n150.0,0.25\n'  # its third depth does not increase


def test_s5_t4_a_refused_middle_table_fails_alone_with_the_converter_s_sentence_and_no_upload(journey_run):
    uploads = []
    definition = {'SYN-A': TD_DEF['SYN-A'], 'SYN-C': td_entry('checkshots/C.csv', 1, 'comma', 'depth', 'time'), 'SYN-B': TD_DEF['SYN-B']}
    report, target = td_run(journey_run, definition, {**TD_MEMBERS, 'checkshots/C.csv': TD_C}, hooks={'td_uploading': uploads.append})
    td_expect(report, {**td_both('SYN-C', 'failed'), ('time-depth', 'SYN-C', 'project-to-resinsight'): 'unsupported'}, models=('SYN-A', 'SYN-C', 'SYN-B'), wells=2)
    assert uploads == ['SYN-A', 'SYN-B']
    leg1 = the(report, 'time-depth', 'SYN-C', 'opendtect-to-project')
    assert leg1['evidence'] == {'error': TD_WRONG % ('SYN-C', 'Depth', 'depth'), 'class': 'other', 'source_row': 3}
    assert {f['step']: f['owner'] for f in td_findings(report)} == {'time-depth SYN-C opendtect-to-project': 'E137', 'time-depth SYN-C project-to-sdk': 'E137',
                                                                    'time-depth project-to-resinsight': 'E129'}
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t5_a_defined_well_not_in_the_survey_is_an_inventory_problem(journey_run):
    report, target = td_run(journey_run, {'SYN-Z': TD_DEF['SYN-A']})
    assert report['time_depth'] == {'definition': True, 'models': 1, 'survey_wells': 5, 'outside': 1}
    assert the(report, 'time-depth', '*', '*')['evidence'] == {'route': 'none', 'wells': 5}
    assert ev.evaluate(report) == ['time-depth: 1 well(s) of the time-depth definition are not wells of the survey.'] and gone(journey_run, target)


def test_s5_t6_one_depth_changed_after_the_offline_read_disagrees_on_the_sdk_leg_alone(journey_run):
    def changed(unit, first):
        if unit == ('time-depth', 'SYN-B'): first['pairs'][1][0] += 0.5
        return first
    report, target = td_run(journey_run, hooks={'sdk_result': changed})
    td_expect(report, {('time-depth', 'SYN-B', 'project-to-sdk'): 'disagree'})
    r = the(report, 'time-depth', 'SYN-B', 'project-to-sdk')
    assert disagreeing(r) == ['depth', 'pairs_sha256'] and q(r, 'depth')['over_budget'] == 1
    assert {f['step']: f['owner'] for f in td_findings(report)}['time-depth SYN-B project-to-sdk'] == 'E51'
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t7_a_declaration_sent_otherwise_disagrees_on_that_declaration_alone(journey_run):
    """The expectation is frozen from the definition before the hook changes what is sent."""
    report, target = td_run(journey_run, hooks={'td_declared': lambda well, d: {**d, 'time_unit': 's'} if well == 'SYN-B' else d})
    td_expect(report, {('time-depth', 'SYN-B', 'opendtect-to-project'): 'disagree'})
    r = the(report, 'time-depth', 'SYN-B', 'opendtect-to-project')
    assert disagreeing(r) == ['time_unit'] and (q(r, 'time_unit')['expected'], q(r, 'time_unit')['observed']) == ('ms', 's')
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t9_an_original_written_otherwise_disagrees_on_its_digest_alone(journey_run):
    """The bundle refuses an original.csv changed inside it (its digest is the revision's), so the change is made to
    what the offline reader printed: `100.0` written `100.00`, every number kept."""
    other = hashlib.sha256(TD_A.replace(b'100.0,', b'100.00,')).hexdigest()
    def changed(unit, first):
        if unit == ('time-depth', 'SYN-A'): first['sha256'] = other
        return first
    report, target = td_run(journey_run, hooks={'sdk_result': changed})
    td_expect(report, {('time-depth', 'SYN-A', 'project-to-sdk'): 'disagree'})
    assert disagreeing(the(report, 'time-depth', 'SYN-A', 'project-to-sdk')) == ['original_sha256']
    assert ev.evaluate(report) == [] and gone(journey_run, target)


def test_s5_t10_an_empty_definition_counts_every_well_and_t14_reports_carry_their_own_mode(journey_run):
    """T10; T14 within one process: the reports of a run with a definition, one without and one with again each
    validate by their own `time_depth` (the evaluator and compose keep no state between them; one journey per test, as
    the gateway lane's control schema is seeded once per test)."""
    report, target = td_run(journey_run, {})
    td_expect(report, {}, models=(), wells=5)
    assert report['time_depth'] == {'definition': True, 'models': 0, 'survey_wells': 5, 'outside': 0}
    assert the(report, 'time-depth', '*', '*')['evidence'] == {'route': 'none', 'wells': 5} and td_findings(report) == []
    assert ev.evaluate(report) == [] and gone(journey_run, target)
    without = json.loads(json.dumps(report))
    without['time_depth']['definition'] = False
    the(without, 'time-depth', '*', '*')['state'], the(without, 'time-depth', '*', '*')['evidence'] = 'not-yet', {'waits_on': 'E137 s3'}
    assert [ev.evaluate(r) for r in (report, without, report)] == [[], [], []]
    assert ev.evaluate(json.loads(json.dumps({**without, 'time_depth': report['time_depth']})))  # each report by its own counts
    kinds = lambda undefined: [(r['kind'], r['state']) for r in journey.compose([], [], [], {}, {}, {}, {}, None, None, None, undefined) if r['kind'] == 'time-depth']  # noqa: E731
    assert [kinds(5), kinds(None), kinds(0), kinds(5)] == [[('time-depth', 'unsupported')], [('time-depth', 'not-yet')], [], [('time-depth', 'unsupported')]]


def test_s5_t11_every_well_defined_leaves_no_kind_level_row_and_one_with_wells_0_is_a_problem(journey_run):
    tables = {w: b'depth,time\n%d.0,0.1\n%d.0,0.2\n' % (10 + n, 20 + n) for n, w in enumerate(WELLS)}
    members = {'checkshots/%d.csv' % n: raw for n, raw in enumerate(tables.values())}
    definition = {w: td_entry('checkshots/%d.csv' % n, 1, 'comma', 'depth', 'time') for n, w in enumerate(WELLS)}
    report, target = td_run(journey_run, definition, members)
    td_expect(report, {}, models=tuple(WELLS), wells=0)
    assert ev.evaluate(report) == [] and gone(journey_run, target)
    extra = json.loads(json.dumps(report))
    extra['rows'].append(journey.row('time-depth', '*', '*', None, state='unsupported', evidence={'route': 'none', 'wells': 1}))
    assert ev.evaluate(extra) == ['time-depth * *: the survey wells with no defined table stand as one unsupported row, its route none and its wells 0, '
                                  'and no row when there are none.']


def test_s5_t12_both_tables_refused_fail_four_rows_owned_by_e137_and_keep_the_route_finding(journey_run):
    members = {'checkshots/A.csv': TD_A.replace(b'300.0,0.25', b'300.0,0.15'), 'checkshots/B.txt': TD_B.replace(b'12.0\t120.0', b'12.0\t80.0')}
    report, target = td_run(journey_run, members=members)
    td_expect(report, {**td_both('SYN-A', 'failed'), **td_both('SYN-B', 'failed')})
    assert the(report, 'time-depth', 'SYN-A', 'opendtect-to-project')['evidence']['error'] == TD_WRONG % ('SYN-A', 'Time', 'time')
    assert the(report, 'time-depth', 'SYN-B', 'opendtect-to-project')['evidence']['error'] == TD_WRONG % ('SYN-B', 'Depth', 'depth')
    assert sorted(f['owner'] for f in td_findings(report)) == ['E129', 'E137', 'E137', 'E137', 'E137']
    assert ev.evaluate(report) == [] and gone(journey_run, target)
