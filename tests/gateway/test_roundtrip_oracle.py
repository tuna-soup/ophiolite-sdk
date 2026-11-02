"""E138 s1 C1 (strategy rev 3 §2, D1, D2, D4, D10, D11; R1-2, R1-9, R2-3, R2-4; mutations 1, 4, 6 and 11's oracle part):
the expected side from E137's read CLI, and the part-by-part comparison.

The read CLI runs as a child process under the fake odbind of `ophiolite-opendtect/tests/fake_odbind` (on its
PYTHONPATH with the connector, as the exporter runs in test_roundtrip_journey.py); nothing here imports either (the
E125 boundary). The CLI's oracle is checked against s0's hand-written literals and the digest constants computed from
the frozen synthetic grids (test_roundtrip_journey.py `oracle`, `digest`, `mask`), never against production code, and
the synthetic journey run with it meets s0's hand-counted clean record, the literal run's rows (R1-9, R2-4). The streaming
comparator is checked against the whole comparison and against hand-counted aggregates of a frozen grid (mutation 4).
A gateway module, as test_roundtrip_journey.py: it reads the journey and the fake from the monorepo."""
import importlib.util
import json
import math
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (the gateway lane's fixtures)
from test_roundtrip_journey import (CLEAN, GRIDS, LINE_OBJECTS, OBJECTS, OPHIOLITE, Project, Target, check_clean, clean_states, digest,  # noqa: F401
                                    disagreeing, exporter_env, journey, oracle, q, states, survey, the, top, x_of, y_of, zipped)
from project_gateway.tests import test_one_api_matrix

ROOT = Path(__file__).resolve().parents[3]


def _module(name):
    spec = importlib.util.spec_from_file_location('roundtrip_' + name + '_oracle_test', ROOT / 'conformance/roundtrip' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


ro, wf, cmp, lt = _module('read_oracle'), journey.wf, journey.cmp, _module('live_target')
TABLE = journey.ev.load()


@pytest.fixture
def bound(survey, tmp_path):
    """bound(variant=None, cls=ReadOracle) -> the CLI's oracle listed on the synthetic survey, in a work folder of its
    own on a volume of its own (the journey wires the oracle into its run in C1's journey part)."""
    volume = tmp_path / 'oracle-volume'
    volume.mkdir()
    (tmp_path / 'syn.zip').write_bytes(zipped())
    folders = []
    def bind(variant=None, cls=ro.ReadOracle):
        work = wf.WorkFolder.create(volume, [tmp_path / 'forbidden'])
        folders.append(work)
        root = work.extract(tmp_path / 'syn.zip', 'survey')
        return cls(sys.executable, exporter_env(variant), timeout=120).bind(work, root, 'Syn_Survey')
    bind.volume = volume
    yield bind
    for work in folders: assert work.close()


@pytest.fixture
def run_with(survey, service, tmp_path):
    """run_with(the_oracle) -> (report, target): one synthetic journey against THE_ORACLE, on a volume of its own (one
    per test: the gateway lane's `web` seeds the test's control database once)."""
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    def run(the_oracle, **kw):
        target = Target(service, survey)
        return journey.run(archive, volume, target, oracle=the_oracle, python=sys.executable, exporter_env=exporter_env(),
                           forbidden=[tmp_path / 'forbidden'], host='synthetic', **kw), target
    run.volume = volume
    return run


# E138 s1 D4 (R2-2): the fake's listed identities of the kinds that wait, one row each (fake_odbind/__init__.py
# STICKSETS, FAULTS3D, HORIZONS2D, written out here); their kinds then have no whole-kind row. E138 s2: the fake's
# four lines (LINES2D) are judged, each with its own rows
WAITING_ROWS = {('fault-sticks', 'SynF', '*'), ('fault-sticks', 'SynF3D', '*'), ('horizon-2d', 'Syn2DH', '*')}
CLI_CLEAN = {**{k: s for k, s in CLEAN.items() if k[1:] != ('*', '*') or k[0] == 'time-depth'}, **{k: s for k, s in clean_states(LINE_OBJECTS).items() if k[0] == 'line-2d'},
             **{k: 'not-yet' for k in WAITING_ROWS}}


def check_cli_clean(report, target, run):
    """s0's hand-counted record on the s0 objects and the lines, and the waiting identities with their slices, outside
    `selected`."""
    check_clean(report, target, run, clean=CLI_CLEAN, objects=OBJECTS + LINE_OBJECTS + [k[:2] for k in WAITING_ROWS], selected=OBJECTS + LINE_OBJECTS)
    assert {r['evidence']['waits_on'] for r in report['rows'] if (r['kind'], r['object'], r['leg']) in WAITING_ROWS} == {'E137 s2', 'E137 s6'}


def leftovers(oracle_):
    return sorted(p.name for p in (oracle_.work.path / ro.FOLDER).iterdir() if p.suffix == '.jsonl')


# --- the oracle against the literals (R1-9, R2-4) -------------------------------------------------------------------

def test_the_cli_oracle_lists_the_s0_objects_in_s0_order(bound):
    o = bound()
    assert o['enumerated'] == list(OBJECTS) + LINE_OBJECTS
    assert o['enumeration'][:2] == ['Seismic3D.names', 'Horizon3D.names'] and 'Seismic2D.line_names' in o['enumeration']
    assert o['not_listed'] == [] and o['survey']['crs'] == 'EPSG:32631'


def test_every_listed_identity_is_kept_with_the_kind_it_is_reported_as(bound):
    """D4: lines, the 2D horizon and the 3D fault are identities of their own (the fault as fault-sticks, R1-3)."""
    ids = {(i['kind'], i['object']): i['reported'] for i in bound()['identities']}
    assert ids[('well', 'SYN-A')] == ['well-path', 'well-head'] and ids[('well-log', 'SYN-A/GR')] == ['well-log']
    assert ids[('fault-3d', 'SynF3D')] == ['fault-sticks'] and ids[('fault-sticks', 'SynF')] == ['fault-sticks']
    assert ids[('horizon-2d', 'Syn2DH')] == ['horizon-2d']
    lines = [o for k, o in ids if k == 'line-2d']
    assert lines and all('/' in o for o in lines)


def test_the_cli_oracle_equals_the_literal_oracle_object_for_object(bound):
    o, literal = bound(), oracle(lines=True)['objects']
    got = o['objects']
    assert sorted(got) == sorted(literal)
    for key in literal:
        source = got[key]
        if key[0] == 'seismic-3d':
            want = literal[key]
            assert (source['count'], source['axes'], source['unit'], source['components']) == (want['count'], want['axes'], want['unit'], ['Component 1'])
            assert source['traces'] == want['traces'], key
        else:
            assert source == literal[key], key
    assert leftovers(o) == []  # each object's lines deleted once read


def test_the_cli_oracle_meets_the_digest_constants_of_the_frozen_grids(bound):
    """R2-4: the samples digest of each cube, from the CLI's lines through `Digests`, equals the constant computed
    from the literal formula (test_roundtrip_journey.digest), and the clean cubes' null mask is 'none'."""
    o = bound()
    for cube in GRIDS:
        _, lines = o.inlines('seismic-3d', cube)
        d = cmp.Digests()
        for _, part in lines:
            for k in sorted(part): d.add(part[k][2])
        assert (d.samples_sha256(), d.null_mask()) == (digest(cube), 'none'), cube


def test_inlines_hand_over_one_inline_at_a_time_and_count_a_horizon_s_nodes(bound):
    o = bound()
    header, lines = o.inlines('horizon-3d', 'Top')
    assert header['kind'] == 'horizon-3d' and header['undefined'].startswith('null where odbind gives NaN')
    first = next(lines)
    assert first == (10, {(10, c): (x_of(c), y_of(10), top(10, c)) for c in (20, 22, 24, 26)})
    assert [i for i, _ in lines] == [12, 14, 16]
    assert o.nodes('Top') == (16, 15)  # one node, (12, 24), undefined
    assert leftovers(o) == []


def test_an_undefined_sample_is_nan_in_the_cube_source(bound):
    """Variant `nan`: Syn's (12, 22) sample 1 is NaN; the CLI prints null and the source holds NaN, so s0's null
    mask sees it."""
    traces = bound('nan')['objects'][('seismic-3d', 'Syn')]['traces']
    assert math.isnan(traces[(12, 22)][2][1]) and not any(math.isnan(v) for k, t in traces.items() if k != (12, 22) for v in t[2])


# --- the journey with the CLI's oracle (R1-9) -----------------------------------------------------------------------

def test_the_journey_with_the_cli_oracle_meets_s0_s_hand_counted_record(bound, run_with):
    """R1-9: the journey reads its oracle only through `enumerated` and `objects` (journey.py `legs`, `source`), and
    both equal the literals above object for object, so its rows are the literal run's; this run is held to the same
    hand-counted record as s0's clean run (test_roundtrip_journey.check_clean), one journey per test since the
    gateway lane seeds its control database once."""
    report, target = run_with(bound())
    check_cli_clean(report, target, run_with)


class Patched(ro.ReadOracle):
    """Mutation 1: the CLI's lines with one sample of Syn's inline 14 changed (a patched JSONL line)."""
    def documents(self, kind, name, *more):
        for doc in super().documents(kind, name, *more):
            if kind == 'seismic-3d' and name == 'Syn' and doc.get('inline') == 14:
                doc['samples'][0][1][2] += 0.5
            yield doc


def test_mutation_1_a_changed_cli_sample_disagrees_on_the_digest_alone(bound, run_with):
    """The file is unchanged (its digest is the literal constant) and only Syn's rows turn: the oracle is the source
    of the difference; s0's clean test holds the literal run clean."""
    report, _ = run_with(bound(cls=Patched))
    turned = {k for k, s in states(report).items() if s != CLI_CLEAN[k]}
    assert turned == {('seismic-3d', 'Syn', leg) for leg in OPHIOLITE}
    for leg in OPHIOLITE:
        r = the(report, 'seismic-3d', 'Syn', leg)
        assert disagreeing(r) == ['samples_sha256'] and q(r, 'samples_sha256')['observed'] == digest('Syn') != q(r, 'samples_sha256')['expected']


# --- refusals (D10, mutation 6) -------------------------------------------------------------------------------------

def test_mutation_6_an_output_outside_the_work_folder_is_refused_with_its_class(bound, monkeypatch):
    o = bound()
    real = o._child
    monkeypatch.setattr(o, '_child', lambda args, stdout: real([*args[:3], '--out', '../x.jsonl', *args[5:]], stdout))
    with pytest.raises(ro.Unread) as refused:
        list(o.documents('seismic-3d', 'Syn'))
    assert (refused.value.code, refused.value.cls) == (2, 'outside path')
    assert not (o.work.path.parent / 'x.jsonl').exists()


# E137 s2 C1: the read CLI now reads a 3D fault's sticks, so `SynF3D` is read; a 3D fault the survey does not hold is still refused
@pytest.mark.parametrize('kind, name, cls', [('fault-3d', 'Nope', 'other'), ('horizon-2d', 'Syn2DH', 'no route'), ('seismic-3d', 'Nope', 'other')])
def test_a_refused_object_is_unread_with_its_d10_class(bound, kind, name, cls):
    o = bound()
    with pytest.raises(ro.Unread) as refused:
        list(o.documents(kind, name))
    assert (refused.value.code, refused.value.cls) == (2, cls) and refused.value.cls in ro.CLASSES
    assert leftovers(o) == []


def test_the_classes_of_the_cli_s_sentences():
    assert ro.classify('OpendTect could not read the seismic cube “X”.') == 'read error'
    assert ro.classify('OpendTect could not list the 2D lines.') == 'read error'
    assert ro.classify('The output ../x is not a relative path inside the working directory.') == 'outside path'
    assert ro.classify('The 3D fault “F” is enumerated but not read yet: E137 slice 2 reads it.') == 'no route'
    assert ro.classify('Something else.') == 'other' and ro.classify(None) == 'other'


def test_the_cli_runs_with_home_and_tmp_inside_the_work_folder(bound):
    """D11: the child's HOME, TMPDIR and XDG folders are the work folder's own."""
    o = bound()
    env = o.work.child_env({'PATH': '/usr/bin'})
    assert env['PATH'] == '/usr/bin'
    for name in ('HOME', 'TMPDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        place = Path(env[name])
        assert o.work.path in place.parents and place.is_dir() and oct(place.stat().st_mode & 0o777) == '0o700', name


def test_a_failed_listing_is_unread_and_names_no_document(bound, monkeypatch):
    class Broken(ro.ReadOracle):
        def _child(self, args, stdout):
            stdout.write(b'{"format": "something else"}\n'); return 0
    with pytest.raises(ro.Unread) as refused:
        bound(cls=Broken)
    assert refused.value.cls == 'other'


# --- the part-by-part comparison (D2, R2-3, mutation 4) ---------------------------------------------------------------

def spec(name='x', budget=0.01, quantum=None, rule=None):
    s = {'name': name, 'mode': 'tolerance', 'budget': budget, 'quantum': quantum}
    if rule: s['budget_rule'] = rule
    return s


def grid(inlines=(1, 2, 3), crosslines=(1, 2, 3)):
    return {'%d,%d' % (i, c): float(10 * i + c) for i in inlines for c in crosslines}


def parts(values):
    """VALUES split by inline, in table order."""
    out = {}
    for label, v in values.items(): out.setdefault(int(label.split(',')[0]), {})[label] = v
    return [out[i] for i in sorted(out)]


def summed(s, expected, observed, synthetic=True):
    acc = cmp.Tolerance(s, synthetic=synthetic)
    e, o = parts(expected), {int(next(iter(p)).split(',')[0]): p for p in parts(observed)}
    inlines = sorted({int(k.split(',')[0]) for k in expected} | {int(k.split(',')[0]) for k in observed})
    for i in inlines:
        acc.add(next((p for p in e if int(next(iter(p)).split(',')[0]) == i), {}), o.get(i, {}))
    return acc.result()


CASES = {
    'clean': lambda g: dict(g),
    'missing trace': lambda g: {k: v for k, v in g.items() if k != '2,2'},
    'wrong crossline': lambda g: {('2,4' if k == '2,2' else k): v for k, v in g.items()},
    'unequal inline sets': lambda g: {**{k: v for k, v in g.items() if not k.startswith('3,')}, '4,1': 41.0},
    'truncated last inline': lambda g: {k: v for k, v in g.items() if k not in ('3,2', '3,3')},
    'worst in a later inline': lambda g: {**g, '1,2': g['1,2'] + 0.02, '3,1': g['3,1'] + 0.05},
    'a tie keeps the first position': lambda g: {**g, '1,3': g['1,3'] + 0.04, '3,3': g['3,3'] + 0.04},
    'nulls': lambda g: {**g, '2,1': None, '2,3': None},
}


@pytest.mark.parametrize('case', sorted(CASES))
def test_the_summed_comparison_answers_as_the_whole_comparison(case):
    g = grid()
    observed = CASES[case](g)
    for s in (spec(), spec(quantum=0.01, budget=0.02), spec(rule='4*ulp32(given)+4*ulp32(first)', budget=None)):
        assert summed(s, g, observed) == cmp.tolerance(s, g, observed, synthetic=True), (case, s)
        assert summed(s, g, observed, synthetic=False) == cmp.tolerance(s, g, observed, synthetic=False)


def test_the_summed_aggregates_against_hand_counted_values():
    """Mutation 4, against counts written by hand from the 3x3 grid (values 10 i + c)."""
    g = grid()
    q_, _ = summed(spec(), g, CASES['missing trace'](g))
    assert (q_['positions'], q_['compared'], q_['unmatched'], q_['over_budget'], q_['state']) == (9, 8, 1, 1, 'disagree')
    q_, _ = summed(spec(), g, CASES['wrong crossline'](g))
    assert (q_['positions'], q_['compared'], q_['unmatched'], q_['over_budget']) == (10, 8, 2, 2)
    q_, _ = summed(spec(), g, CASES['unequal inline sets'](g))
    assert (q_['positions'], q_['compared'], q_['unmatched'], q_['over_budget']) == (10, 6, 4, 4)
    q_, _ = summed(spec(), g, CASES['truncated last inline'](g))
    assert (q_['positions'], q_['compared'], q_['unmatched']) == (9, 7, 2)
    q_, x = summed(spec(), g, CASES['worst in a later inline'](g))
    assert q_['largest'] == {'value': float(Decimal('31.05') - Decimal('31')), 'at': '3,1', 'budget': 0.01} and q_['over_budget'] == 2
    assert [e['at'] for e in x[:2]] == ['3,1', '1,2']
    q_, x = summed(spec(), g, CASES['a tie keeps the first position'](g))
    assert q_['largest']['at'] == '1,3' and [e['at'] for e in x[:2]] == ['1,3', '3,3']


def test_a_permutation_of_intact_traces_passes_by_design():
    """R2-3: the comparison is keyed by position, so inlines or crosslines reordered in the file agree."""
    g = grid()
    reordered = dict(reversed(list(g.items())))
    q_, _ = summed(spec(), g, reordered)
    assert (q_['state'], q_['over_budget'], q_['compared']) == ('agree', 0, 9)


def test_examples_keep_the_64_largest_across_parts():
    g = grid(range(1, 21), range(1, 11))  # 200 positions over 20 parts
    observed = {k: v + 0.001 * n for n, (k, v) in enumerate(g.items())}
    q_, x = summed(spec(budget=1.0), g, observed)
    whole = cmp.tolerance(spec(budget=1.0), g, observed, synthetic=True)
    assert (q_, x) == whole and len(x) == cmp.EXAMPLES and x[0]['at'] == '20,10'


def test_digests_part_by_part_equal_the_whole_digests():
    values = [[1.5, 2.25, math.nan], [3.0, 4.0, 5.0]]
    d = cmp.Digests()
    for trace in values: d.add(trace)
    flat = [v for t in values for v in t]
    assert d.samples_sha256() == cmp.samples_sha256(flat) and d.null_mask() == cmp.mask_sha256([math.isfinite(v) for v in flat])
    clean = cmp.Digests(); clean.add([1.0, 2.0])
    assert clean.null_mask() == 'none' and clean.count == 2


def test_a_duplicated_trace_position_is_a_structure_refusal():
    assert cmp.keyed([((1, 1), 'a'), ((1, 2), 'b')]) == {(1, 1): 'a', (1, 2): 'b'}
    with pytest.raises(cmp.Duplicate) as twice:
        cmp.keyed([((1, 1), 'a'), ((1, 1), 'b')])
    assert twice.value.cls == 'duplicate trace position' and twice.value.cls in ro.CLASSES
    assert not any(ch.isdigit() for ch in str(twice.value))  # D10: the sentence names no position


# --- the report's new fields (R1-7; the evaluator's rules over them follow in C1's journey part) ----------------------

def live_fields(report):
    report = json.loads(json.dumps(report))
    report['run'].update({'stopped': {'sentence': 'A survey file changed during the run.', 'differing': 1}, 'survey_unchanged': False,
                          'archive_unchanged': True, 'limits': {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 31, 'OPHIOLITE_MAX_UPLOAD_TOTAL_BYTES': 2 ** 33,
                                                                     'OPHIOLITE_MAX_RETAINED_BYTES': 2 ** 33},
                          'memory': {'maxrss_kib': {'journey': 1, 'read-cli': 2}, 'tree_max_kib': {'online': 3, 'offline': 4}},
                          'cleanup': {'no_processes': True, 'no_containers': True, 'no_stray_files': True}})
    report['inventory']['not_listed'] = [{'kind': 'line-2d', 'class': 'read error'}]
    report['rows'][0]['evidence'].update({'nodes': {'total': 100001, 'defined': 90000}, 'class': 'no route', 'waits_on': 'E138 s2'})
    report['findings'] = [{'step': 'export', 'numbers': '1 of 15', 'owner': 'E129', 'sent': '2026-11-01', 'class': 'undefined samples'}]
    return report


def test_the_schema_takes_the_live_fields_and_their_classes():
    from test_roundtrip_report import example
    base = example()
    assert journey.ev.schema_problems(base) == [] and journey.ev.schema_problems(live_fields(base)) == []
    for path, bad in ((('run', 'stopped'), {'sentence': 'x'}), (('inventory', 'not_listed'), [{'kind': 'line-2d', 'class': 'odbind said so'}]),
                      (('run', 'cleanup'), {'no_processes': True}), (('run', 'limits'), {'OPHIOLITE_ANYTHING': 1}),
                      (('run', 'memory'), {'tree_max_kib': {}})):
        report = live_fields(base)
        report[path[0]][path[1]] = bad
        assert journey.ev.schema_problems(report), path
    report = live_fields(base)
    report['rows'][0]['evidence']['class'] = 'Traceback (most recent call last)'
    assert journey.ev.schema_problems(report)


# --- C2: the live target, an in-process gateway on a loopback port (rev 5 D5) ----------------------------------------

def loopback_build(service, monkeypatch, built):
    """s0's Project built for ORIGIN (the gateway lane's `web` takes its origin from test_one_api_matrix.ORIGIN), with
    its application and the delegate credential its synthetic client uses."""
    from ophiolite import Credential
    def build(work, origin):
        monkeypatch.setattr(test_one_api_matrix, 'ORIGIN', origin)
        project = Project(work, service, monkeypatch)
        project.app, project.credential = project.web.app, Credential.bearer('oph_api_alice:read,write')
        built.append(project)
        return project
    return build


def test_the_synthetic_journey_runs_clean_through_the_loopback_gateway(survey, service, tmp_path):
    """D5 (rev 5): every upload and read crosses 127.0.0.1; the limits are set while the gateway runs and restored
    after; the gateway's thread and socket are gone once the run ends; the rows name the in-process tool."""
    import os
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    built, seen = [], {}
    target = lt.LiveTarget(loopback_build(service, survey, built), {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21, 'OPHIOLITE_MAX_UPLOAD_TOTAL_BYTES': 2 ** 24},
                           version='test', host='synthetic', lifespan='off')  # `web`'s TestClient holds the lifespan
    def after(client, receipts):
        (live,) = target.projects
        seen['url'], seen['limit'] = client.url, os.environ.get('OPHIOLITE_MAX_FILE_BYTES')
        seen['stores'] = {(kind, str(root)) for kind, root in live.payload_stores()}
        seen['work'] = built[0].work
    before = os.environ.get('OPHIOLITE_MAX_FILE_BYTES')
    report = journey.run(archive, volume, target, oracle=oracle(), python=sys.executable, exporter_env=exporter_env(),
                         forbidden=[tmp_path / 'forbidden'], host='synthetic', hooks={'after_landing': after})
    assert states(report) == CLEAN and journey.ev.evaluate(report) == []
    assert seen['url'].startswith('http://127.0.0.1:') and seen['limit'] == str(2 ** 21)
    assert seen['stores'] == {('local', str(seen['work'] / 'payloads'))}
    (live,) = target.projects
    assert live.stopped and live.limits == {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21, 'OPHIOLITE_MAX_UPLOAD_TOTAL_BYTES': 2 ** 24}
    assert os.environ.get('OPHIOLITE_MAX_FILE_BYTES') == before
    assert {r['tool']['name'] for r in report['rows'] if r['leg'] == 'opendtect-to-project' and r['tool']} == {lt.TOOL}
    assert report['run']['work_folder_removed'] and report['run']['storage_removed'] and os.listdir(volume) == []


def test_located_heads_page_through_the_loopback_features_collection(survey, service, tmp_path):
    """D6 (R1-6, R2-9b) on the gateway: the five synthetic heads located by one well-location/1 each are the wells
    collection, exactly (the journey's uploads add no well entity), at page size 2 in the survey CRS, and the
    gateway's own pages follow `next` to the end; the coordinates are the heads given, per created entity id."""
    import urllib.request
    from test_roundtrip_journey import TRACKS
    qg, located = _module('qgis_leg'), _module('located')
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    heads = {w: track[0][1:3] for w, track in TRACKS.items()}
    seen = {}
    target = lt.LiveTarget(loopback_build(service, survey, []), version='test', host='synthetic', lifespan='off')
    def after(client, receipts):
        (live,) = target.projects
        created = located.locate(client, heads, 'EPSG:23031')
        def get(url):
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer oph_api_alice:read,write'})
            with urllib.request.urlopen(request, timeout=30) as answer: return json.loads(answer.read())
        documents = []
        items = '%s/api/v1/projects/p/features/collections/wells/items' % live.origin
        seen.update(created=created, pages=qg.pages(get, items, crs='EPSG:23031', keep=documents.append), documents=documents)
    report = journey.run(archive, volume, target, oracle=oracle(), python=sys.executable, exporter_env=exporter_env(),
                         forbidden=[tmp_path / 'forbidden'], host='synthetic', hooks={'after_landing': after})
    assert states(report) == CLEAN
    created, pages = seen['created'], seen['pages']
    assert len(set(created.values())) == 5 and [len(ids) for _, ids in pages] == [2, 2, 1] and pages[0][0] == ''
    assert {i for _, ids in pages for i in ids} == set(created.values())
    got = {f['id']: tuple(f['geometry']['coordinates']) for d in seen['documents'] for f in d['features']}
    assert {w: got[created[w]] for w in heads} == {w: tuple(xy) for w, xy in heads.items()}
    log = [{'method': 'GET', 'path': '/api/v1/projects/p/features/collections/wells/items', 'status': 200, 'ids': ids,
            'query': 'limit=2' + ('&cursor=' + c if c else '')} for c, ids in pages]  # what a QGIS that follows every next would leave
    assert qg.paging(log, pages, created.values()) == []


@pytest.mark.parametrize('limits', [{'OPHIOLITE_MAX_UPLOAD_BYTES': 2 ** 20}, {'OPHIOLITE_MAX_FILE_BYTES': 10}, {'OPHIOLITE_MAX_FILE_BYTES': '2048'},
                                    {'OPHIOLITE_MAX_RETAINED_BYTES': 2 ** 41}])
def test_a_limit_the_target_does_not_set_or_out_of_bounds_is_refused_before_anything_starts(limits):
    with pytest.raises(ValueError):
        lt.LiveTarget(lambda work, origin: pytest.fail('nothing is built'), limits)


def test_a_build_that_fails_closes_the_socket_and_restores_the_limits(tmp_path):
    import os
    before = os.environ.get('OPHIOLITE_MAX_RETAINED_BYTES')
    def broken(work, origin): raise RuntimeError('no project')
    with pytest.raises(RuntimeError):
        lt.LiveTarget(broken, {'OPHIOLITE_MAX_RETAINED_BYTES': 2 ** 30}).open(tmp_path)
    assert os.environ.get('OPHIOLITE_MAX_RETAINED_BYTES') == before


# --- mutation 14: the four phases on one project (rev 5 D2, D6, D11; R2-5, R2-9d) -------------------------------------

def synthetic_qgis(work, origin, port, landing, key, crs, *, name, timeout, run_engine=None):
    """A QGIS that follows every `next` of the wells collection: its inside-script output and the proxy log it leaves."""
    import urllib.request
    qg = _module('qgis_leg')
    def get(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key}), timeout=30) as answer: return json.loads(answer.read())
    documents = []
    pages = qg.pages(get, '%s/collections/%s/items' % (landing, qg.COLLECTION), crs=crs, keep=documents.append)
    path = urllib.parse.urlsplit(landing).path + '/collections/wells/items'
    log = [{'method': 'GET', 'path': path, 'status': 200, 'ids': ids, 'query': 'limit=2' + ('&cursor=' + c if c else '')} for c, ids in pages]
    features = [{'id': f['id'], 'x': f['geometry']['coordinates'][0], 'y': f['geometry']['coordinates'][1]} for d in documents for f in d['features']]
    return {'collection': qg.COLLECTION, 'valid': True, 'features': features, 'page_count': len(pages), 'qgis_version': '4.2.2-synthetic'}, log


def test_mutation_14_the_four_phases_run_on_one_project_closed_once_and_every_artifact_goes(survey, service, tmp_path):
    import os
    import urllib.parse  # noqa: F401 (synthetic_qgis)
    from test_roundtrip_tools import FAKE_RIPS, CONNECTORS
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    python, exe, state = tmp_path / 'connectors-python', tmp_path / 'ResInsight', tmp_path / 'servers'
    python.write_text('#!/bin/sh\nPYTHONPATH=%s:%s FAKE_RIPS_STATE=%s DISPLAY=:99 exec %s "$@"\n' % (FAKE_RIPS, CONNECTORS, state, sys.executable))
    exe.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE_RIPS / 'fake_resinsight.py'))
    for script in (python, exe): script.chmod(0o755)
    built, closes, judged = [], [], []

    class Counted(lt.LiveTarget):
        def open(self, work):
            project = super().open(work)
            close = project.close
            project.close = lambda: (closes.append(project.closed), close())
            return project
    target = Counted(loopback_build(service, survey, built), {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21}, version='test', host='synthetic', lifespan='off')
    tools = journey.SecondTools(host='synthetic', key='oph_api_alice:read,write', resinsight_python=str(python), resinsight=str(exe), qgis=True,
                                read_qgis=synthetic_qgis, timeout=120, stray_roots=[tmp_path / 'strays'])
    def artifact_judged(unit, path): judged.append((unit, os.path.lexists(path)))
    report = journey.run(archive, volume, target, oracle=oracle(), python=sys.executable, exporter_env=exporter_env(), forbidden=[tmp_path / 'forbidden'],
                         host='synthetic', tools=tools, hooks={'artifact_judged': artifact_judged})
    tooled = {**{(k, o, 'project-to-resinsight'): 'within' for k, o in OBJECTS if k in ('well-path', 'well-log')},
              **{('well-head', o, 'project-to-qgis'): 'within' for k, o in OBJECTS if k == 'well-head'}}
    assert states(report) == {**CLEAN, **tooled} and journey.ev.evaluate(report) == []
    assert len(built) == 1 and len(target.projects) == 1 and closes == [False] and target.projects[0].stopped
    assert len(judged) == 9 and all(not left for _, left in judged)  # 2 cubes, a horizon, 5 paths, a LAS: each artifact gone once judged
    assert list(report['run']['memory']['tree_max_kib']) == ['online', 'tools', 'close', 'offline']
    assert report['run']['cleanup'] == {'no_processes': True, 'no_containers': True, 'no_stray_files': True}
    assert report['run']['limits'] == {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21}
    assert report['run']['work_folder_removed'] and report['run']['storage_removed'] and os.listdir(volume) == []
