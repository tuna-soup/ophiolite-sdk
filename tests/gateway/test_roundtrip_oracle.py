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
from test_roundtrip_journey import (CLEAN, FAULT_OBJECTS, FAULTS, GRIDS, LINE_OBJECTS, OBJECTS, OPHIOLITE, WELLS, Project, Target, both,  # noqa: F401
                                    check_clean, clean_states, digest, disagreeing, exporter_env, journey, oracle, q, replacing, states, survey, the,
                                    top, x_of, y_of, zipped)
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
# HORIZONS2D, written out here); their kinds then have no whole-kind row. E138 s2: the fake's four lines (LINES2D)
# are judged, each with its own rows; E138 s3: so are its fault stick set and 3D fault (STICKSETS, FAULTS3D)
WAITING_ROWS = {('horizon-2d', 'Syn2DH', '*')}
CLI_CLEAN = {**{k: s for k, s in CLEAN.items() if k[1:] != ('*', '*') or k[0] == 'time-depth'}, **{k: s for k, s in clean_states(LINE_OBJECTS).items() if k[0] == 'line-2d'},
             **{k: 'not-yet' for k in WAITING_ROWS}}
S0_OBJECTS = [o for o in OBJECTS if o[0] != 'fault-sticks']


def check_cli_clean(report, target, run):
    """s0's hand-counted record on the s0 objects, the lines and the fault sets, and the waiting identity with its
    slice, outside `selected`."""
    check_clean(report, target, run, clean=CLI_CLEAN, objects=OBJECTS + LINE_OBJECTS + [k[:2] for k in WAITING_ROWS], selected=OBJECTS + LINE_OBJECTS)
    assert {r['evidence']['waits_on'] for r in report['rows'] if (r['kind'], r['object'], r['leg']) in WAITING_ROWS} == {'E137 s6'}


def leftovers(oracle_):
    return sorted(p.name for p in (oracle_.work.path / ro.FOLDER).iterdir() if p.suffix == '.jsonl')


# --- the oracle against the literals (R1-9, R2-4) -------------------------------------------------------------------

def test_the_cli_oracle_lists_the_s0_objects_in_s0_order(bound):
    o = bound()
    assert o['enumerated'] == S0_OBJECTS + LINE_OBJECTS + FAULT_OBJECTS  # E138 s3: the fault sets after the lines, 3D faults first
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


# E138 s3 C2 (D3): odbind's first read rewrites `.wll` files (MNSH: 1,700 by `list`); the fake's `settle` variant
# rewrites SYN-A's one legacy log file on the first `Well.log_names`, which the oracle's `list` (bind) makes
LEGACY_LOG = 'Syn_Survey/WellInfo/SYN-A^9.wll'
LEGACY, SETTLED = b'dTect V6.6\n', b'dTect V7.0\n'  # fake_odbind/__init__.py LEGACY, SETTLED, written out (E125: no odbind import here)


def settle_archive(path):
    import io
    import zipfile
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zipped())) as src, zipfile.ZipFile(out, 'w') as z:
        for info in src.infolist(): z.writestr(info, src.read(info))
        for name, raw in [('Syn_Survey/WellInfo/', b''), (LEGACY_LOG, LEGACY + b'no header: never listed as a log\n')]:
            info = zipfile.ZipInfo(name, (2026, 10, 31, 0, 0, 0))
            if name.endswith('/'): info.external_attr = 0o40755 << 16
            z.writestr(info, raw)
    path.write_bytes(out.getvalue())
    return path


@pytest.mark.parametrize('after_settle', [False, True])
def test_c2_the_first_read_s_rewrite_is_settled_and_a_change_after_it_still_stops_the_run(bound, survey, service, tmp_path, after_settle):
    """C2: with the `settle` variant the oracle's first read rewrites one log file: the run is judged as the clean
    CLI run and `survey_settled_by_first_read` is 1. A file rewritten after the settle step (a test hook) still
    stops the run with SURVEY_CHANGED."""
    archive, volume = settle_archive(tmp_path / 'settle.zip'), tmp_path / 'volume'
    volume.mkdir()
    seen = {}
    def settled(root):
        seen['settled'] = (root / LEGACY_LOG).read_bytes()[:11]
        if after_settle: (root / 'Syn_Survey' / '.defs').write_bytes(b'Depth in feet: Yes\n')
    target = Target(service, survey)
    report = journey.run(archive, volume, target, oracle=bound('settle'), python=sys.executable, exporter_env=exporter_env('settle'),
                         forbidden=[tmp_path / 'forbidden'], host='synthetic', hooks={'settled': settled})
    assert seen['settled'] == SETTLED  # rewritten by the first read, before the settled digest
    assert report['run']['survey_settled_by_first_read'] == 1 and report['run']['archive_unchanged'] is True
    if after_settle:
        assert report['run']['stopped'] == {'sentence': journey.SURVEY_CHANGED, 'differing': 1} and report['run']['survey_unchanged'] is False
        assert report['rows'] == [] and journey.ev.evaluate(report) == []
    else:
        assert report['run']['survey_unchanged'] is True and 'stopped' not in report['run']
        assert states(report) == CLI_CLEAN and journey.ev.evaluate(report) == []
    import os
    assert os.listdir(volume) == []


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
# E137 s6b C3: it reads a 2D horizon line by line too, so `Syn2DH` is read; a 2D horizon the survey does not hold is refused
@pytest.mark.parametrize('kind, name, cls', [('fault-3d', 'Nope', 'other'), ('horizon-2d', 'Nope', 'other'), ('seismic-3d', 'Nope', 'other')])
def test_a_refused_object_is_unread_with_its_d10_class(bound, kind, name, cls):
    o = bound()
    with pytest.raises(ro.Unread) as refused:
        list(o.documents(kind, name))
    assert (refused.value.code, refused.value.cls) == (2, cls) and refused.value.cls in ro.CLASSES
    assert leftovers(o) == []


def test_s5_c1f_a_read_stopped_at_its_cap_is_too_large_and_leaves_no_file(bound):
    """E138 s5 D1: the CLI's JSON Lines for one object are capped one byte past CAP; the stop is `too large` with
    its numbers, the partial file is removed, and without a cap the same read is whole."""
    o = bound()
    o.cap = 100
    with pytest.raises(ro.Unread) as stopped:
        list(o.documents('seismic-3d', 'Syn'))
    assert (stopped.value.cls, stopped.value.limit, stopped.value.observed) == ('too large', 100, 101) and stopped.value.cls in ro.CLASSES
    assert leftovers(o) == []
    o.cap = None
    assert len(list(o.documents('seismic-3d', 'Syn'))) == 5  # the header and four inlines


def test_s5_c1f_the_journey_s_oracle_cap_fails_both_legs_of_the_cube_with_its_numbers(bound, run_with):
    """E138 s5 D1: the allowance at Syn's oracle read (the fourth measurement: export, landing, download, oracle)
    holds 1,000 bytes; Syn fails both judged legs `too large` (volume, oracle), and every other row is as clean."""
    calls = []
    def free():
        calls.append(1)
        return journey.RESERVE + (1000 if len(calls) == 4 else 10 ** 9)
    report, target = run_with(bound(), hooks={'free_bytes': free})
    assert states(report) == {**CLI_CLEAN, **both('seismic-3d', 'Syn', 'failed')}
    for leg in OPHIOLITE:
        assert the(report, 'seismic-3d', 'Syn', leg)['evidence']['too_large'] == {'bound': 'volume', 'phase': 'oracle', 'limit': 1000, 'observed': 1001}
    assert [f['owner'] for f in report['findings'] if f['step'].startswith('seismic-3d Syn ')] == ['E140']
    assert journey.ev.evaluate(report) == []


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
    report['rows'][0]['evidence'].update({'nodes': {'total': 100001, 'defined': 90000, 'admission': 100000}, 'class': 'no route', 'waits_on': 'E138 s2'})
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

def synthetic_qgis_of(change=None, log_change=None):
    """A QGIS, per collection (E138 s3 D4), that follows every `next` of the collection it is asked for at that
    collection's page size (O2: wells 2, lines and point-sets 100): its inside-script output (qgis_read_inside.py's
    shapes: a well's id, x and y; a line's properties and LineString points; a point's properties, x and y) and the
    proxy log it leaves. CHANGE(collection, features), when given, returns what QGIS saw; LOG_CHANGE(collection, log)
    the log it left (H3)."""
    def read(work, origin, port, landing, key, crs, *, name, timeout, run_engine=None, collection='wells'):
        import urllib.parse
        import urllib.request
        qg = journey._module('qgis_leg')  # the journey's own module: a page size patched there is the double's too (H3)
        def get(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key}), timeout=60) as answer: return json.loads(answer.read())
        documents, size = [], qg.page_size(collection)
        pages = qg.pages(get, '%s/collections/%s/items' % (landing, collection), limit=size, crs=crs, keep=documents.append)
        path = urllib.parse.urlsplit(landing).path + '/collections/%s/items' % collection
        log = [{'method': 'GET', 'path': path, 'status': 200, 'ids': ids, 'query': 'limit=%d' % size + ('&cursor=' + c if c else '')} for c, ids in pages]
        served = [f for d in documents for f in d['features']]
        if collection == qg.COLLECTION:
            features = [{'id': f['id'], 'x': f['geometry'] and f['geometry']['coordinates'][0], 'y': f['geometry'] and f['geometry']['coordinates'][1]} for f in served]
        elif collection == qg.POINTS:
            features = [{'properties': dict(f['properties']), 'x': f['geometry'] and f['geometry']['coordinates'][0], 'y': f['geometry'] and f['geometry']['coordinates'][1]} for f in served]
        else:
            features = [{'properties': dict(f['properties']), 'points': f['geometry'] and [list(p) for p in f['geometry']['coordinates']]} for f in served]
        if change: features = change(collection, features)
        if log_change: log = log_change(collection, log)
        return {'collection': collection, 'valid': True, 'features': features, 'page_count': len(pages), 'qgis_version': '4.2.2-synthetic'}, log
    return read


synthetic_qgis = synthetic_qgis_of()


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
              **{(k, o, 'project-to-qgis'): 'within' for k, o in OBJECTS if k in ('well-head', 'fault-sticks', 'horizon-3d')}}
    assert states(report) == {**CLEAN, **tooled} and journey.ev.evaluate(report) == []
    assert len(built) == 1 and len(target.projects) == 1 and closes == [False] and target.projects[0].stopped
    assert len(judged) == 11 and all(not left for _, left in judged)  # 2 cubes, a horizon, 5 paths, a LAS, 2 fault sets: each gone once judged
    assert list(report['run']['memory']['tree_max_kib']) == ['online', 'tools', 'close', 'offline']
    assert report['run']['cleanup'] == {'no_processes': True, 'no_containers': True, 'no_stray_files': True}
    assert report['run']['limits'] == {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21}
    assert report['run']['work_folder_removed'] and report['run']['storage_removed'] and os.listdir(volume) == []


# --- E138 s3 C1a §5: fault stick sets on every leg, QGIS's `lines` through the per-collection double ----------------
# Each test runs one journey through the loopback gateway with the QGIS double (ResInsight not given: its rows wait);
# the fault rows' expected values are the hand literals of test_roundtrip_journey.py (SynF, SynF3D).

FAULT_LEGS = ('opendtect-to-project', 'project-to-sdk', 'project-to-qgis')
NOT_STATED = 'Not stated: no coordinate system is declared for this layer.'  # the gateway's placement, written out
QGIS_CLEAN = {**CLEAN, **{('well-head', w, 'project-to-qgis'): 'within' for w in WELLS}, **{(k, o, 'project-to-qgis'): 'within' for k, o in FAULT_OBJECTS},
              ('horizon-3d', 'Top', 'project-to-qgis'): 'within'}
NO_ROUTE = {'step': 'fault-sticks project-to-resinsight', 'numbers': '2 sets: rips has no fault-stick import', 'owner': 'E129', 'sent': None, 'class': 'no route'}
SYNF = ('fault-sticks', 'SynF')


@pytest.fixture
def qgis_run(survey, service, tmp_path):
    """qgis_run(variant=None, change=None, the_oracle=None, hooks=None) -> report: one synthetic journey through the
    loopback gateway with QGIS's double (CHANGE as synthetic_qgis_of's)."""
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    def run(variant=None, change=None, the_oracle=None, hooks=None, admission=None, log_change=None, qgis=True):
        if admission is not None: survey.setenv('OPHIOLITE_MAX_HORIZON_NODES', str(admission))  # the gateway lane's deployment M (limits.py)
        target = lt.LiveTarget(loopback_build(service, survey, []), version='test', host='synthetic', lifespan='off')
        tools = journey.SecondTools(host='synthetic', key='oph_api_alice:read,write', qgis=qgis, read_qgis=synthetic_qgis_of(change, log_change), timeout=600)
        return journey.run(archive, volume, target, oracle=the_oracle or oracle(), python=sys.executable, exporter_env=exporter_env(variant),
                           forbidden=[tmp_path / 'forbidden'], host='synthetic', tools=tools, hooks=hooks or {})
    run.volume = volume
    return run


def fault_expect(report, changed):
    """The rows a mutation reaches are CHANGED, every other as in the clean QGIS run; the record stays consistent."""
    assert states(report) == {**QGIS_CLEAN, **changed}
    assert journey.ev.evaluate(report) == []
    return report


def every(name, state): return {('fault-sticks', name, leg): state for leg in FAULT_LEGS}


def stick_lines(change):
    """A landed hook on SynF's file: CHANGE([(index, line)]) -> lines, the banner kept."""
    def landed(entry, raw):
        if entry != 'faults/SynF.dat': return raw
        head, *rest = raw.decode('ascii').splitlines(keepends=True)
        return (head + ''.join(line for _, line in change([(int(line.split()[3]), line) for line in rest]))).encode('ascii')
    return landed


def relabel(mapping): return stick_lines(lambda lines: [(i, line.rsplit(' ', 1)[0] + ' %d\n' % mapping.get(i, i)) for i, line in lines])


def test_the_clean_qgis_run_judges_both_fault_sets_on_every_leg_and_writes_one_no_route_finding(qgis_run):
    """§5 clean: 2 × 2 judged legs equal, 2 QGIS rows within, 2 ResInsight rows unsupported; one E129 finding. F9
    and F15 on the evaluator: the QGIS row dropped, stated unsupported, or its coordinates not recorded where the
    source states a CRS, is refused."""
    import copy
    report = fault_expect(qgis_run(), {})
    assert report['findings'] == [NO_ROUTE]
    for name, sticks in FAULTS.items():
        r = the(report, 'fault-sticks', name, 'project-to-qgis')
        n = sum(len(p) for _, p in sticks)
        assert [(x['name'], x['expected'], x['observed']) for x in r['quantities'] if x['mode'] == 'count'] == [
            ('features', len(sticks), len(sticks)), ('placed', len(sticks), len(sticks)), ('points', n, n)]
        assert all(q(r, c)['over_budget'] == 0 and q(r, c)['compared'] == n for c in 'xy') and r['not_recorded'] == [] and r['evidence'] == {}
        assert the(report, 'fault-sticks', name, 'project-to-resinsight')['evidence'] == {'route': 'none'}
    x = {e['at']: e['observed'] for e in the(report, *SYNF, 'project-to-qgis')['examples'] if e['quantity'] == 'x'}
    assert (x['0,0'], x['1,0'], x['2,2']) == (500010.0, 500035.0, 500062.0)
    # F9: the QGIS fault row dropped, or stated unsupported
    dropped = copy.deepcopy(report)
    dropped['rows'] = [r for r in dropped['rows'] if (r['kind'], r['object'], r['leg']) != (*SYNF, 'project-to-qgis')]
    assert 'fault-sticks SynF project-to-qgis: missing (a mandatory leg).' in journey.ev.evaluate(dropped)
    stated = copy.deepcopy(report)
    r = the(stated, *SYNF, 'project-to-qgis')
    r.update(state='unsupported', evidence={'route': 'none'}, quantities=[], examples=[])
    assert journey.ev.evaluate(stated) == ['fault-sticks SynF project-to-qgis: a mandatory leg cannot be unsupported.']
    # C1b: the horizon's QGIS row, 16 nodes on point-sets, x and y against hundredths, z of the 15 defined
    r = the(report, 'horizon-3d', 'Top', 'project-to-qgis')
    assert [(x['name'], x['expected'], x['observed']) for x in r['quantities'] if x['mode'] == 'count'] == [('features', 16, 16), ('placed', 16, 16)]
    assert all(q(r, c)['over_budget'] == 0 for c in 'xyz') and r['not_recorded'] == [] and r['evidence'] == {}
    # F15: coordinates not recorded on a source that states a CRS (the fault row, a well head's and the horizon's)
    for key in ((*SYNF, 'project-to-qgis'), ('well-head', 'SYN-A', 'project-to-qgis'), ('horizon-3d', 'Top', 'project-to-qgis')):
        unplaced = copy.deepcopy(report)
        r = the(unplaced, *key)
        r['quantities'] = [{'name': x['name'], 'mode': 'tolerance', 'expected': None, 'observed': None, 'state': 'unsupported'} if x['name'] in ('x', 'y') else x
                           for x in r['quantities']]
        r['not_recorded'], r['examples'] = ['x', 'y'], []
        r['state'] = journey.ev.row_state(r)
        assert journey.ev.evaluate(unplaced) == ['%s %s %s: %s is not recorded, yet its source states a CRS.' % (*key, c) for c in 'xy']


def test_f1_one_z_1e_9_s_off_disagrees_on_the_digest_and_keyed_z_on_both_legs(qgis_run):
    z = 0.108 + 1e-9
    report = qgis_run(hooks={'landed': replacing('faults/SynF.dat', b'500011.0 21.0 0.108 0\n', b'500011.0 21.0 %s 0\n' % repr(z).encode())})
    fault_expect(report, both(*SYNF, 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, *SYNF, leg)
        assert disagreeing(r) == ['sticks_sha256', 'z'] and q(r, 'z')['over_budget'] == 1 and q(r, 'z')['largest']['at'] == '0,1'
        assert [e['observed'] for e in r['examples'] if (e['quantity'], e['at']) == ('z', '0,1')] == [z]


def test_f2_the_last_point_of_a_stick_dropped_disagrees_on_its_counts_and_leaves_its_position_unmatched(qgis_run):
    report = qgis_run(hooks={'landed': replacing('faults/SynF.dat', b'500012.0 22.0 0.112 0\n', b'')})
    fault_expect(report, every('SynF', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, *SYNF, leg)
        assert disagreeing(r) == ['points', 'points per stick', 'sticks_sha256', 'x', 'y', 'z'] and (q(r, 'points')['expected'], q(r, 'points')['observed']) == (9, 8)
        assert all((q(r, c)['unmatched'], q(r, c)['compared'], q(r, c)['positions']) == (1, 8, 9) for c in 'xyz')
    r = the(report, *SYNF, 'project-to-qgis')
    assert disagreeing(r) == ['points', 'points per stick', 'x', 'y'] and all((q(r, c)['unmatched'], q(r, c)['compared']) == (1, 8) for c in 'xy')


def test_f3_two_stick_labels_swapped_in_place_disagree_on_order_digest_and_keyed_x(qgis_run):
    """O1, R2-4: index 0 now holds the x 500035 points; y is not claimed (every SynF stick has y 20, 21, 22)."""
    report = qgis_run(hooks={'landed': relabel({0: 1, 1: 0})})
    fault_expect(report, every('SynF', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, *SYNF, leg)
        assert disagreeing(r) == ['stick order', 'sticks_sha256', 'x'] and q(r, 'points per stick')['state'] == 'agree'
        assert q(r, 'x')['over_budget'] == 6 and q(r, 'x')['largest']['value'] == 25.0
    assert disagreeing(the(report, *SYNF, 'project-to-qgis')) == ['x']


def test_f3b_two_sticks_moved_with_their_labels_disagree_on_file_order_alone(qgis_run):
    report = qgis_run(hooks={'landed': stick_lines(lambda lines: [l for l in lines if l[0] == 1] + [l for l in lines if l[0] != 1])})
    fault_expect(report, both(*SYNF, 'disagree'))
    for leg in OPHIOLITE: assert disagreeing(the(report, *SYNF, leg)) == ['stick order', 'sticks_sha256']


def test_f4_the_sdk_leg_judges_the_polyline_set_not_the_original(qgis_run):
    """A changed PolylineSet with the original untouched: leg 1 equal, the SDK leg disagrees (a leg reading the
    file would stay green)."""
    def sdk_result(unit, first):
        if unit == SYNF: first['sticks'][1][1][0][0] += 1.0
        return first
    report = qgis_run(hooks={'sdk_result': sdk_result})
    fault_expect(report, {(*SYNF, 'project-to-sdk'): 'disagree'})
    r = the(report, *SYNF, 'project-to-sdk')
    assert disagreeing(r) == ['sticks_sha256', 'x'] and q(r, 'x')['largest']['at'] == '1,0' and q(r, 'original_sha256')['state'] == 'agree'


def test_f5_one_qgis_x_two_millimetres_off_disagrees_on_x_alone(qgis_run):
    def change(collection, features):
        if collection == 'lines':
            f = next(f for f in features if f['properties']['name'] == 'fault-sticks SynF' and f['properties']['stick'] == 0)
            f['points'][0][0] += 0.002
        return features
    report = fault_expect(qgis_run(change=change), {(*SYNF, 'project-to-qgis'): 'disagree'})
    r = the(report, *SYNF, 'project-to-qgis')
    assert disagreeing(r) == ['x'] and q(r, 'x')['over_budget'] == 1 and q(r, 'x')['largest']['at'] == '0,0'


REFUSED = ['SynF1', 'SynFz', 'SynF ']  # fake_odbind `faults`: a stick of one point, a depth fault, a trailing space


def test_f6_the_exporter_s_fault_refusals_fail_both_judged_legs_owned_by_e137(qgis_run):
    the_oracle = oracle()
    the_oracle['enumerated'] += [('fault-sticks', n) for n in REFUSED]
    report = qgis_run(variant='faults', the_oracle=the_oracle)
    refused = {}
    for n in REFUSED: refused.update({**every(n, 'failed'), ('fault-sticks', n, 'project-to-resinsight'): 'unsupported'})
    fault_expect(report, refused)
    for n in REFUSED:
        assert {leg: the(report, 'fault-sticks', n, leg)['evidence']['class'] for leg in FAULT_LEGS} == dict.fromkeys(FAULT_LEGS, 'other')
    owners = {f['step']: f['owner'] for f in report['findings']}
    assert owners == {**{'fault-sticks %s %s' % (n, leg): o for n in REFUSED for leg, o in zip(FAULT_LEGS, ('E137', 'E137', 'E46'))},
                      'fault-sticks project-to-resinsight': 'E129'}
    assert [f['numbers'] for f in report['findings'] if f['step'] == NO_ROUTE['step']] == ['5 sets: rips has no fault-stick import']


# F7, frozen at lane open: on a survey stating no CRS the exporter refuses every well before the location reader is
# reached ("The survey states no coordinate system, so the well's position cannot be sent."), so every well row fails,
# class `other`, the well-head QGIS rows included (not landed); the cubes, the horizon and the fault sets are judged
NOCRS = {k: 'failed' for k in QGIS_CLEAN if k[0] in ('well-path', 'well-head', 'well-log')}
NO_WELL = "The survey states no coordinate system, so the well's position cannot be sent."


def unplaced(report, name):
    r = the(report, 'fault-sticks', name, 'project-to-qgis')
    return [(x['name'], x['state']) for x in r['quantities']], r['not_recorded'], r['evidence']


def test_f7_a_survey_that_states_no_crs_judges_features_and_identities_and_records_no_coordinates(qgis_run):
    """D5: every layer is declared `unknown`. The fault rows judge features, placed (none) and identities; points,
    points per stick, x and y are not recorded and every placement is the gateway's Not-stated sentence. R2-8c: the
    well-head QGIS rows are `failed`, class `other` (the exporter's refusal; the next test freezes the location
    reader's own decision). C1b: the horizon's QGIS row (point-sets) is `within`: features, placed (none), identities
    and z judged, x and y not recorded, the same Not-stated placement."""
    report = fault_expect(qgis_run(variant='nocrs'), {**NOCRS, **{(k, o, 'project-to-qgis'): 'equal' for k, o in FAULT_OBJECTS}})
    r = the(report, 'horizon-3d', 'Top', 'project-to-qgis')
    assert [(x['name'], x['state']) for x in r['quantities']] == [('features', 'agree'), ('placed', 'agree'), ('identities', 'agree'), ('z', 'agree'),
                                                                  ('x', 'unsupported'), ('y', 'unsupported')]
    assert (r['not_recorded'], r['evidence']) == (['x', 'y'], {'crs': 'unknown', 'placement': NOT_STATED})
    assert (q(r, 'features')['observed'], q(r, 'placed')['observed'], q(r, 'z')['compared']) == (16, 0, 16)  # the undefined node compared as absent on both sides
    for name, sticks in FAULTS.items():
        assert unplaced(report, name) == ([('features', 'agree'), ('placed', 'agree'), ('identities', 'agree'), ('points', 'unsupported'),
                                           ('points per stick', 'unsupported'), ('x', 'unsupported'), ('y', 'unsupported')],
                                          ['points', 'points per stick', 'x', 'y'], {'crs': 'unknown', 'placement': NOT_STATED})
        assert (q(the(report, 'fault-sticks', name, 'project-to-qgis'), 'features')['observed'], q(the(report, 'fault-sticks', name, 'project-to-qgis'), 'placed')['observed']) == (len(sticks), 0)
    for w in WELLS:
        r = the(report, 'well-head', w, 'project-to-qgis')
        assert (r['state'], r['evidence']['class'], NO_WELL in r['evidence']['error']) == ('failed', 'other', True)
    assert NO_ROUTE in report['findings'] and not any(f['step'].endswith('paging') for f in report['findings'])


def test_f7_the_location_reader_accepts_an_unknown_crs_and_refuses_none_stated(survey, service, tmp_path):
    """R2-8c, read from typed_reader `_well_location` and frozen: a `well-location/1` in `unknown` is accepted, so the
    head is listed by the wells collection without geometry and its QGIS row (D5) is `equal` on wells and
    identities, x and y not recorded, no class; a location stating no CRS (`''`) is refused, class `other`."""
    import urllib.request
    from test_roundtrip_journey import TRACKS
    qg, located = _module('qgis_leg'), _module('located')
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()
    heads, seen = {w: track[0][1:3] for w, track in TRACKS.items()}, {}
    target = lt.LiveTarget(loopback_build(service, survey, []), version='test', host='synthetic', lifespan='off')
    def after(client, receipts):
        (live,) = target.projects
        created = located.locate(client, heads, 'unknown')
        def get(url):
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer oph_api_alice:read,write'})
            with urllib.request.urlopen(request, timeout=30) as answer: return json.loads(answer.read())
        documents = []
        pages = qg.pages(get, '%s/api/v1/projects/p/features/collections/wells/items' % live.origin, keep=documents.append)
        try: located.locate(client, {'Refused': (1.0, 2.0)}, '', prefix='e138-refused')
        except Exception as error: seen['refused'] = error
        seen.update(created=created, pages=pages, features=[f for d in documents for f in d['features']])
    report = journey.run(archive, volume, target, oracle=oracle(), python=sys.executable, exporter_env=exporter_env(),
                         forbidden=[tmp_path / 'forbidden'], host='synthetic', hooks={'after_landing': after})
    assert states(report) == CLEAN
    assert {f['id']: f['geometry'] for f in seen['features']} == dict.fromkeys(seen['created'].values())
    inside = {'collection': 'wells', 'valid': True, 'features': [{'id': f['id'], 'x': None, 'y': None} for f in seen['features']]}
    log = [{'method': 'GET', 'path': '/api/v1/projects/p/features/collections/wells/items', 'status': 200, 'ids': ids,
            'query': 'limit=2' + ('&cursor=' + c if c else '')} for c, ids in seen['pages']]
    rows, problems = qg.rows(TABLE, inside, log, seen['pages'], heads, seen['created'], tool=None, synthetic=True, crs='unknown')
    assert problems == [] and {r['state'] for r in rows} == {'equal'} and all(r['not_recorded'] == ['x', 'y'] and r['evidence'] == {'crs': 'unknown'} for r in rows)
    assert type(seen['refused']).__name__ == 'Refused' and journey.class_of(seen['refused']) == 'other'  # the SDK's refusal; the reader's sentence stays server-side


def test_f8_a_placed_feature_on_a_source_without_a_crs_disagrees(qgis_run):
    def change(collection, features):
        if collection == 'lines': next(f for f in features if f['properties']['name'] == 'fault-sticks SynF')['points'] = [[1.0, 2.0], [3.0, 4.0]]
        return features
    report = fault_expect(qgis_run(variant='nocrs', change=change), {**NOCRS, ('fault-sticks', 'SynF3D', 'project-to-qgis'): 'equal', (*SYNF, 'project-to-qgis'): 'disagree'})
    r = the(report, *SYNF, 'project-to-qgis')
    assert disagreeing(r) == ['placed', 'points', 'points per stick', 'x', 'y'] and (q(r, 'placed')['expected'], q(r, 'placed')['observed']) == (0, 1)


def test_f13_a_refused_well_location_fails_the_heads_and_the_fault_reads_go_on(qgis_run):
    """R2-8c: the location reader's refusal (a location stating no CRS, `''`) fails the well-head QGIS rows with its
    class and one E46 finding; the fault sets are still read by QGIS, every other row is as in the clean run, and the
    run does not stop. On the default variant: on `nocrs` the exporter refuses the wells first (F7), so no location
    is ever asked for."""
    located = _module('located')
    report = qgis_run(hooks={'locate': lambda client, heads, crs: located.locate(client, heads, '')})
    fault_expect(report, {('well-head', w, 'project-to-qgis'): 'failed' for w in WELLS})
    assert {the(report, 'well-head', w, 'project-to-qgis')['evidence']['class'] for w in WELLS} == {'other'}
    assert {'step': 'well-head project-to-qgis', 'numbers': '5 wells: %s' % journey.NOT_LOCATED, 'owner': 'E46', 'sent': None, 'class': 'other'} in report['findings']
    assert [f['owner'] for f in report['findings'] if f['step'].startswith('well-head ')] == ['E46'] * 6 and NO_ROUTE in report['findings']


@pytest.mark.parametrize('mutation', ['another source, the same stick', 'another revision'])
def test_f14_a_feature_of_another_source_or_revision_disagrees_on_identities(qgis_run, mutation):
    def change(collection, features):
        if collection != 'lines': return features
        mine = next(n for n, f in enumerate(features) if f['properties']['name'] == 'fault-sticks SynF' and f['properties']['stick'] == 1)
        if mutation == 'another revision': features[mine]['properties']['source_revision'] += '-other'
        else: features[mine] = json.loads(json.dumps(next(f for f in features if f['properties']['name'] == 'fault-sticks SynF3D' and f['properties']['stick'] == 1)))
        return features
    report = qgis_run(change=change)
    if mutation == 'another revision':
        fault_expect(report, {(*SYNF, 'project-to-qgis'): 'disagree'})
        assert disagreeing(the(report, *SYNF, 'project-to-qgis')) == ['identities']
    else:
        fault_expect(report, {(k, o, 'project-to-qgis'): 'disagree' for k, o in FAULT_OBJECTS})
        assert disagreeing(the(report, *SYNF, 'project-to-qgis')) == ['features', 'identities', 'placed', 'points', 'points per stick', 'x', 'y']
        assert disagreeing(the(report, 'fault-sticks', 'SynF3D', 'project-to-qgis')) == ['features', 'identities', 'placed']  # its stick 1 twice, the first compared


def test_f12_a_stick_relabelled_into_an_index_gap_disagrees_on_the_encoded_index(qgis_run):
    """F3, R2-6: SynF's stick 2 relabelled 5; the digest encodes the index, so it is red; stick 5 is unmatched."""
    report = qgis_run(hooks={'landed': relabel({2: 5})})
    fault_expect(report, every('SynF', 'disagree'))
    for leg in OPHIOLITE:
        r = the(report, *SYNF, leg)
        assert disagreeing(r) == ['points per stick', 'stick order', 'sticks_sha256', 'x', 'y', 'z']
        assert all((q(r, c)['unmatched'], q(r, c)['over_budget']) == (6, 6) for c in 'xyz')
    assert disagreeing(the(report, *SYNF, 'project-to-qgis')) == ['identities', 'points per stick', 'x', 'y']


# --- E138 s3 C1b §5: the horizon at the served admission M (H1), QGIS's `point-sets` (H2-H7) ---------------------------
# TopBig (fake_odbind `big`, R2-8d): 11 inlines x 9,091 crosslines = 100,001 nodes, every one defined; its literal
# source is written here by formula, never read from the fake.

TOP = ('horizon-3d', 'Top')
BIG = ('horizon-3d', 'TopBig')
HORIZON_LEGS = ('opendtect-to-project', 'project-to-sdk', 'project-to-qgis')
# Frozen 1 Nov 2026: the project's own sentence ("This horizon has 100001 nodes; this deployment accepts at most
# 100000. Nothing was added.", typed_reader.py) stays server-side, as the location reader's does (F7); the SDK raises
# its generic refusal, class `other`, and the node counts come from the journey's own count against the served M.
SDK_REFUSED = ("The application request was refused. Check the input and supported profile. Correct the request: compare its fields "
               "with the operation's schema in /api/v1/openapi.json and send it again.")


def big_source():
    return {(i, c): (700000.125 + 12.5 * (i - 1000) + 2.5 * (c - 2000), 6000000.375 + 3.75 * (i - 1000) + 25.0 * (c - 2000), 1500.0 + 2.0 * (i - 1000) + 0.25 * (c - 2000))
            for i in range(1000, 1011) for c in range(2000, 11091)}


def big_oracle():
    the_oracle = oracle()
    at = the_oracle['enumerated'].index(TOP) + 1
    the_oracle['enumerated'][at:at] = [BIG]
    the_oracle['objects'][BIG] = big_source()
    return the_oracle


def big_clean(state='within'):
    return {**QGIS_CLEAN, **{(*BIG, leg): state for leg in HORIZON_LEGS}, (*BIG, 'project-to-resinsight'): 'unsupported'}


def test_h1a_a_horizon_above_the_served_admission_fails_every_leg_with_its_node_counts_owned_by_e139(qgis_run):
    """H1a, D3: M = 100,000 served; TopBig's upload is refused by number (the SDK's refusal, class `other`), so
    leg 1, the SDK leg and the QGIS leg fail with {total, defined, admission} and one E139 finding carries the
    numbers; Top and everything else is as in the clean QGIS run."""
    report = qgis_run(variant='big', the_oracle=big_oracle(), admission=100_000)
    fault_expect(report, big_clean('failed'))
    for leg in HORIZON_LEGS:
        r = the(report, *BIG, leg)
        assert r['evidence']['nodes'] == {'total': 100_001, 'defined': 100_001, 'admission': 100_000} and r['evidence']['class'] == 'other'
        assert r['evidence']['error'] == SDK_REFUSED and r['quantities'] == []
    big = [f for f in report['findings'] if f['step'].startswith('horizon-3d TopBig')]
    assert big == [{'step': 'horizon-3d TopBig opendtect-to-project', 'owner': 'E139', 'sent': None, 'class': 'other',
                    'numbers': '100001 nodes in total, 100001 defined; the project admits 100000 (horizon_nodes)'}]
    assert not any(f['step'].startswith('horizon-3d Top ') for f in report['findings'])


@pytest.mark.parametrize('admission', [200_000, 100_001])
def test_h1bc_a_horizon_at_or_under_the_served_admission_lands_and_is_judged_on_leg_1_and_the_sdk(qgis_run, admission):
    """H1b (M = 200,000) and H1c (M = 100,001, the boundary): TopBig is admitted, lands as columns and is judged on
    leg 1 and the SDK leg; no horizon finding. QGIS is not given, so every QGIS row waits on its tool."""
    # QGIS's read-back of TopBig is the routed E139 finding: a point-set page costs the project, not the page
    # (project_gateway/features.py:312-322 loads every point-set payload per items request); no test pages it here.
    report = qgis_run(variant='big', the_oracle=big_oracle(), admission=admission, qgis=False)
    assert states(report) == {**CLEAN, **both(*BIG, 'within'), (*BIG, 'project-to-qgis'): 'not-yet', (*BIG, 'project-to-resinsight'): 'unsupported'}
    assert journey.ev.evaluate(report) == []
    for leg in OPHIOLITE:
        r = the(report, *BIG, leg)
        assert 'nodes' not in r['evidence'] and all(q(r, c)['compared'] == 100_001 and q(r, c)['over_budget'] == 0 for c in 'xyz')
    assert the(report, *BIG, 'project-to-qgis')['evidence'] == {'waits_on': 'tool qgis'}
    assert not any(f['step'].startswith('horizon-3d') for f in report['findings'])


def points_of(name):
    """The point-sets features of the horizon NAME, in the order served."""
    return lambda features: [f for f in features if f['properties'].get('name') == 'horizon-3d ' + name]


@pytest.mark.parametrize('mutation', ['another source, the same feature_index', 'another revision', 'a feature_index twice'])
def test_h2_a_point_of_another_source_or_revision_or_a_repeated_index_disagrees_on_identities(qgis_run, mutation):
    """H2 (F14's shape): Top's feature 3 stated as of another source (its source_asset_id changed), or of another
    revision, or Top's feature 5 served once more."""
    def change(collection, features):
        if collection != 'point-sets': return features
        mine = [n for n, f in enumerate(features) if f['properties']['feature_index'] == 3]
        (n,) = mine
        if mutation == 'another revision': features[n]['properties']['source_revision'] += '-other'
        elif mutation == 'another source, the same feature_index': features[n]['properties']['source_asset_id'] += '-other'
        else: features.append(json.loads(json.dumps(next(f for f in features if f['properties']['feature_index'] == 5))))
        return features
    report = qgis_run(change=change)
    r = the(report, *TOP, 'project-to-qgis')
    assert r['state'] == 'disagree' and journey.ev.evaluate(report) == []
    assert states(report) == {**QGIS_CLEAN, (*TOP, 'project-to-qgis'): 'disagree'}
    expected = {'another revision': ['identities'], 'another source, the same feature_index': ['features', 'identities', 'placed', 'x', 'y', 'z'],
                'a feature_index twice': ['features', 'identities', 'placed']}[mutation]
    assert disagreeing(r) == expected
    if mutation != 'another revision': assert q(r, 'features')['observed'] == {'another source, the same feature_index': 15, 'a feature_index twice': 17}[mutation]


def test_h3_a_cursor_qgis_did_not_follow_fails_the_point_sets_rows_with_one_e46_paging_finding(qgis_run, survey):
    """H3, O2: a multi-page point-sets collection without TopBig (CI cost): the point-sets page size is set to 5 for
    the journey and its QGIS double alike, so Top's 16 points come in 4 pages (3 cursors); the second page's request
    is dropped from the proxy log. Top's QGIS row fails, class `tool diagnostics`, with E46's paging findings; the
    other legs and collections are untouched."""
    qg = journey._module('qgis_leg')
    survey.setitem(qg.PAGE_SIZE_OF, qg.POINTS, 5)
    def log_change(collection, log):
        if collection != qg.POINTS: return log
        assert [e['query'].split('&')[0] for e in log] == ['limit=5'] * 4
        return log[:1] + log[2:]
    report = qgis_run(log_change=log_change)
    fault_expect(report, {(*TOP, 'project-to-qgis'): 'failed'})
    r = the(report, *TOP, 'project-to-qgis')
    assert (r['evidence']['class'], r['evidence']['error']) == ('tool diagnostics', 'The proxy log does not prove that QGIS paged the point-sets collection.')
    paging = [f for f in report['findings'] if f['step'] == 'horizon-3d project-to-qgis paging']
    # one E46 finding per problem: 4 pages hold 3 cursors; the dropped page held 5 of the 16 points
    assert [(f['owner'], f['numbers']) for f in paging] == [('E46', qg.NOT_FOLLOWED % (1, 3)), ('E46', qg.UNION % (11, 16, 0))]


@pytest.mark.parametrize('mutation', ['z + 0.5', 'a null moved'])
def test_h5_a_changed_or_moved_z_disagrees_on_z_alone(qgis_run, mutation):
    """H5: Top's z at node (10,20) raised 0.5, or its one undefined z moved to another node (the undefined node
    then served a z, the other none)."""
    def change(collection, features):
        if collection != 'point-sets': return features
        top_ = points_of('Top')(features)
        if mutation == 'z + 0.5': top_[0]['properties']['z'] += 0.5
        else:
            (hole,) = [f for f in top_ if f['properties'].get('z') is None]
            other = next(f for f in top_ if f is not hole)
            hole['properties']['z'], other['properties']['z'] = other['properties']['z'], None
        return features
    report = fault_expect(qgis_run(change=change), {(*TOP, 'project-to-qgis'): 'disagree'})
    r = the(report, *TOP, 'project-to-qgis')
    assert disagreeing(r) == ['z']
    if mutation == 'z + 0.5': assert (q(r, 'z')['over_budget'], q(r, 'z')['largest']['at'], q(r, 'z')['largest']['value']) == (1, '10,20', 0.5)


def test_h7_two_millimetres_on_an_observed_x_disagree_on_x_alone_by_one(qgis_run):
    """H7, R2-5: the observation is untouched (no quantum in the comparator): +0.002 m on one served x (a value on a
    hundredth; +0.002 does not reach the next) is over the 0.001 m budget at that node only."""
    def change(collection, features):
        if collection == 'point-sets': points_of('Top')(features)[0]['x'] += 0.002
        return features
    report = fault_expect(qgis_run(change=change), {(*TOP, 'project-to-qgis'): 'disagree'})
    r = the(report, *TOP, 'project-to-qgis')
    assert disagreeing(r) == ['x'] and q(r, 'x')['over_budget'] == 1 and q(r, 'x')['largest']['at'] == '10,20'


def test_h6_one_run_reads_all_three_collections_and_a_timed_out_lines_read_fails_only_its_rows(survey, service, tmp_path):
    """H6, M5: the real `qgis_leg.read` per collection, through the proxy, with the stub engine of
    test_roundtrip_tools.py; the `lines` read hangs past the timeout. Its container is stopped by name and the fault
    rows fail, class `tool did not start`; the wells and the horizon are judged; after each read that collection's
    folders and logs are gone; no container is left."""
    import os
    import stat
    import tempfile
    from test_roundtrip_tools import STUB
    qg = _module('qgis_leg')
    state, engine = tmp_path / 'engine-state', tmp_path / 'engine'
    engine.write_text(STUB % {'python': sys.executable, 'state': str(state)}); engine.chmod(stat.S_IRWXU)
    Path(str(state) + '.mode').write_text('hang:lines')
    archive, volume = tmp_path / 'syn-survey.zip', Path(tempfile.mkdtemp(prefix='v'))  # a short volume: the proxy socket path holds 100 bytes
    archive.write_bytes(zipped())
    left = {}

    class Watched(journey.SecondTools):
        def qgis_read(self, work, project, collection, crs):
            out = super().qgis_read(work, project, collection, crs)
            suffix = '' if collection == qg.COLLECTION else '-' + collection
            left[collection] = sorted(n for n in ('qgis' + suffix, 'qs' + suffix, 'qgis-proxy%s.jsonl' % suffix, 'qgis-console%s.log' % suffix) if (work.path / n).exists())
            return out
    try:
        target = lt.LiveTarget(loopback_build(service, survey, []), version='test', host='synthetic', lifespan='off')
        tools = Watched(host='synthetic', key='oph_api_alice:read,write', qgis=True, run_engine=str(engine), timeout=20)
        report = journey.run(archive, volume, target, oracle=oracle(), python=sys.executable, exporter_env=exporter_env(),
                             forbidden=[tmp_path / 'forbidden'], host='synthetic', tools=tools)
    finally:
        leftover = os.listdir(volume); volume.rmdir()
    fault_expect(report, {(k, o, 'project-to-qgis'): 'failed' for k, o in FAULT_OBJECTS})
    for k, o in FAULT_OBJECTS:
        r = the(report, k, o, 'project-to-qgis')
        assert (r['evidence']['class'], r['evidence']['error']) == ('tool did not start', qg.TIMED_OUT % 20)
    assert left == {'wells': [], 'lines': [], 'point-sets': []} and leftover == []
    calls = [json.loads(line) for line in Path(str(state) + '.calls').read_text().splitlines()]
    names = [c[c.index('--name') + 1] for c in calls if c[0] == 'run']
    assert len(names) == 3 and len(set(names)) == 3 and [n for n in names if '-lines-' in n] == [n for n in tools.containers if '-lines-' in n]
    lines_name = next(n for n in names if '-lines-' in n)
    assert ['stop', '-t', '5', lines_name] in calls and not any(c[0] == 'stop' and c[-1] != lines_name for c in calls)
    assert report['run']['cleanup']['no_containers'] is True
    assert [f['owner'] for f in report['findings'] if f['step'].startswith('fault-sticks') and 'qgis' in f['step']] == ['E46'] * len(FAULT_OBJECTS)


def test_z0_the_control_line_head_is_start_stop_step_with_five_samples(bound, tmp_path):
    """R2-2, R2-8b: the head's z is [100, 116, 4] and each trace has five samples; the line source takes it as is."""
    o = bound()
    header, chunks = o.line_chunks('Syn2D/L1')
    assert header['z'] == [100.0, 116.0, 4.0] and [len(s) for doc in chunks for s in doc['samples'][0]] == [5] * 5
    line = journey.line_source(o, 'Syn2D/L1', tmp_path / 'spool.f32')
    try: assert (line.axes, line.count) == ('100.0/4.0/5', 5)
    finally: line.source.close()
