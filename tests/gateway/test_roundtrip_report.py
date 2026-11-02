"""E138 s0 C1 (strategy rev 3 §1, §2, D2-D4, D8; acceptance 1; R2-1, R2-4, R2-5, R2-7 to R2-9): the comparator on
arrays, the evaluator on the summary, and E129's ResInsight result as tool-level rows.

The report, comparator and evaluator are Integration qualification tooling (`conformance/roundtrip/`, D91), read here
from the monorepo above the SDK tree. `example()` is a report built by the comparator from arrays written by hand
from the synthetic survey's literals (D5): `Syn` 3.0*i - 0.75*c + 0.0625*k*k + 0.5 at (12,22); `Top` 1000.0 + 7.0*i -
1.5*c with (12,24) undefined; x = 500000.375 + 25*(c - 20), y = 0.125 + 25*(i - 10) as OpendTect holds them, and in
hundredths, half-even, as the exported files hold them. Each acceptance-1 mutation changes that one valid report
once; each keeps the schema and is refused by the evaluator in sentences naming its row."""
import copy
import hashlib
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / 'conformance/roundtrip'


def module(name):
    spec = importlib.util.spec_from_file_location('roundtrip_' + name, HERE / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


ev, cmp, ri = module('evaluate'), module('compare'), module('resinsight_evidence')
TABLE = ev.load()
D = lambda text: hashlib.sha256(text.encode()).hexdigest()
INLINES, CROSSLINES, Z = (10, 12, 14, 16), (20, 22, 24, 26), range(5)
GATEWAY = {'name': 'ophiolite-gateway', 'version': 'in-process', 'host': 'synthetic'}
SDK = {'name': 'ophiolite-sdk', 'version': 'checkout', 'host': 'synthetic'}
# E129's own frozen result (ophiolite-sdk/tests/gateway/test_starter_resinsight.py:24-75): 2 wells, 7 stations,
# 14 log values drawn, no difference, within x 0.0313 m, y 0.00000401 m, z 0.0000303 m.
E129 = {'format': 'ophiolite.resinsight-starter-result/1', 'cube': False, 'resinsight': '2026.9.0', 'rips': '2026.9.0.2',
        'wells': [{'name': 'SYN-A', 'positions': 'wells/SYN-A-positions.csv', 'stations': 4, 'first': [0.0, 500010.125, 10.375, -20.0],
                   'last': [180.0, 500015.0, 12.25, 158.75], 'samples': 181, 'logs': [{'las': 'wells/SYN-A.las', 'curves': ['DEPT', 'DT', 'GR'], 'rows': 7}]},
                  {'name': 'SYN-B', 'positions': 'wells/SYN-B-positions.csv', 'stations': 3, 'first': [0.0, 500075.0, 50.0, -10.0],
                   'last': [100.0, 500076.5, 51.25, 89.75], 'samples': 101, 'logs': []}],
        'stations': 7, 'samples': 14, 'tolerance_m': {'x': 0.0313, 'y': 0.00000401, 'z': 0.0000303}, 'without_logs': ['SYN-B'],
        'reopened': True, 'differences': 0}
WELLS, LOGS = ['SYN-A', 'SYN-B'], ['SYN-A/GR', 'SYN-A/DT']
# R2-9: E129 results it would write for a fault, each counted as `read_back` and `compare` count (both openings).
NEGATIVES = {
    'a well missing in ResInsight': dict(E129, wells=[E129['wells'][0], dict(E129['wells'][1], samples=0)], differences=2),
    'a supplied well the result does not list': dict(E129, wells=E129['wells'][:1], stations=4),
    'geometry-only diagnostics': dict(E129, differences=2),
    'log-only diagnostics': dict(E129, differences=2),
    'the openings before and after differ': dict(E129, differences=2),
}


def syn(i, c, k):
    return 3.0 * i - 0.75 * c + 0.0625 * k * k + (0.5 if (i, c) == (12, 22) else 0.0)


def top(i, c):
    return None if (i, c) == (12, 24) else 1000.0 + 7.0 * i - 1.5 * c


def held(i, c):
    """x and y as OpendTect holds them."""
    return 500000.375 + 25.0 * (c - 20), 0.125 + 25.0 * (i - 10)


def written(v):
    """V in hundredths, half-even on its binary value, as the exporter's files hold it (an independent literal rule, D5)."""
    return float((Decimal(v) * 100).quantize(Decimal(1), rounding='ROUND_HALF_EVEN') / 100)


def row(kind, obj, leg, tool, pairs, synthetic=True, **extra):
    """A compared row: PAIRS maps each quantity of the table's entry to (expected, observed)."""
    quantities, examples = [], []
    for name, (e, o) in pairs.items():
        q, x = cmp.quantity(TABLE, kind, leg, name, e, o, synthetic=synthetic)
        quantities.append(q); examples += x
    body = {'kind': kind, 'object': obj, 'leg': leg, 'tool': tool, 'state': None, 'evidence': {}, 'quantities': quantities,
            'examples': examples[:64], 'limits': cmp.entry_of(TABLE, kind, leg)['limits'], 'sampled': None, 'not_recorded': [], **extra}
    body['state'] = ev.row_state(body)
    return body


def waiting(kind, obj, leg, on):
    return {'kind': kind, 'object': obj, 'leg': leg, 'tool': None, 'state': 'not-yet', 'evidence': {'waits_on': on}, 'quantities': [],
            'examples': [], 'limits': [], 'sampled': None, 'not_recorded': []}


def whole(kind, state, on=None):
    return {**waiting(kind, '*', '*', on), 'state': state, 'evidence': {'waits_on': on} if on else {'route': 'none'}}


def absent(kind):
    return {**waiting(kind, '*', '*', None), 'state': 'absent', 'evidence': {'enumeration': ev.LISTED_BY[kind]}}


# the read CLI's listing calls (journey.py ENUMERATION), written out here
ENUMERATION = ['Seismic3D.names', 'Horizon3D.names', 'Well.names', 'Well.log_names', 'Seismic2D.names', 'Seismic2D.line_names', 'Horizon2D.names',
               'Fault3D.names', 'FaultStickSet.names']


def grid(value, reader=lambda v: v):
    return {'%d,%d' % (i, c): (None if value(i, c) is None else reader(value(i, c))) for i in INLINES for c in CROSSLINES}


def example():
    traces = ['%d,%d' % (i, c) for i in INLINES for c in CROSSLINES]
    samples = [syn(i, c, k) for i in INLINES for c in CROSSLINES for k in Z]
    axes, digest, nulls = 'inline 10-16/2; crossline 20-26/2; z 100-116/4 ms', cmp.samples_sha256(samples), cmp.mask_sha256([True] * 16)
    x = {t: held(*map(int, t.split(',')))[0] for t in traces}
    y = {t: held(*map(int, t.split(',')))[1] for t in traces}
    cube = {'traces': (16, 16), 'samples per trace': (5, 5), 'axes': (axes, axes), 'unit': ('ms', 'ms'), 'samples_sha256': (digest, digest),
            'null mask': ('none', 'none')}
    defined = cmp.mask_sha256([top(i, c) is not None for i in INLINES for c in CROSSLINES])
    gx, gy = grid(lambda i, c: held(i, c)[0]), grid(lambda i, c: held(i, c)[1])
    surface = {'nodes': (16, 16), 'defined nodes': (15, 15), 'null mask': (defined, defined), 'z': (grid(top), grid(top)),
               'x': (gx, {k: written(v) for k, v in gx.items()}), 'y': (gy, {k: written(v) for k, v in gy.items()})}
    stations = {'0': (0.0, 500010.125, 10.375, -20.0), '1': (60.0, 500010.125, 10.375, 40.0), '2': (120.0, 500012.5, 11.0, 99.5), '3': (180.0, 500015.0, 12.25, 158.75)}
    path = {'stations': (4, 4), **{name: ({k: v[n] for k, v in stations.items()},) * 2 for n, name in enumerate(('md', 'x', 'y', 'tvdss'))}}
    gr = {'%.2f' % (100.0 + 0.15 * k): v for k, v in enumerate([None, 41.5, 47.25, 39.0, 52.75, 44.0, None])}
    depth = {k: float(k) for k in gr}
    grmask = cmp.mask_sha256([v is not None for v in gr.values()])
    log = {'samples': (7, 7), 'unit': ('API', 'API'), 'null mask': (grmask, grmask), 'values': (gr, gr)}
    rows = [
        row('seismic-3d', 'Syn', 'opendtect-to-project', GATEWAY, {**cube, 'x': (x, {k: written(v) for k, v in x.items()}), 'y': (y, {k: written(v) for k, v in y.items()})}),
        row('seismic-3d', 'Syn', 'project-to-sdk', SDK, cube),
        row('horizon-3d', 'Top', 'opendtect-to-project', GATEWAY, surface),
        row('horizon-3d', 'Top', 'project-to-sdk', SDK, {'original_sha256': (D('Top.csv'), D('Top.csv')), **surface}),
        waiting('horizon-3d', 'Top', 'project-to-qgis', 'tool qgis'),
        {**waiting('horizon-3d', 'Top', 'project-to-resinsight', None), 'state': 'unsupported', 'evidence': {'route': 'none'}},  # E139 s2 (S2-7)
        row('well-path', 'SYN-A', 'opendtect-to-project', GATEWAY, path),
        row('well-path', 'SYN-A', 'project-to-sdk', SDK, {'original_sha256': (D('SYN-A-positions.csv'), D('SYN-A-positions.csv')), **path}),
        *ri.rows(E129, 'synthetic', ['SYN-A'], ['SYN-A/GR']),
        row('well-head', 'SYN-A', 'opendtect-to-project', GATEWAY, {'x': ({'SYN-A': 500010.125},) * 2, 'y': ({'SYN-A': 10.375},) * 2}),
        waiting('well-head', 'SYN-A', 'project-to-qgis', 'tool qgis'),
        row('well-log', 'SYN-A/GR', 'opendtect-to-project', GATEWAY, {**log, 'depth': (depth, depth)}),
        row('well-log', 'SYN-A/GR', 'project-to-sdk', SDK, {'original_sha256': (D('SYN-A.las'), D('SYN-A.las')), **log}),
        absent('horizon-2d'), absent('fault-sticks'), absent('line-2d'),  # E138 s1 D4: the enumeration lists none of them
        whole('time-depth', 'not-yet', 'E137 s3'),
    ]
    listed = [{'kind': k, 'object': o} for k, o in (('seismic-3d', 'Syn'), ('horizon-3d', 'Top'), ('well-path', 'SYN-A'), ('well-head', 'SYN-A'),
                                                     ('well-log', 'SYN-A/GR'))]
    return {'format': ev.FORMAT, 'journey': 'synthetic-example', 'dataset': {'id': 'synthetic-survey', 'archive_sha256': D('archive'), 'synthetic': True},
            'ophiolite_commit': '0' * 40, 'tolerances': {'version': TABLE['version'], 'sha256': ev.table_sha256(TABLE)},
            'run': {'started_at': '2026-10-31T00:00:00Z', 'finished_at': '2026-10-31T00:01:00Z', 'host': 'synthetic', 'work_folder_removed': True,
                    'storage_removed': True},
            'inventory': {'enumerated': listed, 'selected': copy.deepcopy(listed),
                          'enumeration': list(ENUMERATION)},
            'rows': rows, 'findings': []}


def the(report, kind, obj, leg):
    return next(r for r in report['rows'] if (r['kind'], r['object'], r['leg']) == (kind, obj, leg))


def quantity(r, name):
    return next(q for q in r['quantities'] if q['name'] == name)


def judged(report):
    assert ev.schema_problems(report) == [], 'the mutation must keep the shape, so that only the evaluator can refuse it'
    return ev.evaluate(report)


def test_the_example_built_by_the_comparator_is_judged_clean():
    report = example()
    assert judged(report) == []
    assert [r['state'] for r in report['rows'][:4]] == ['within', 'equal', 'within', 'within']
    x = quantity(the(report, 'horizon-3d', 'Top', 'opendtect-to-project'), 'x')
    assert (x['positions'], x['compared'], x['over_budget'], x['largest']) == (16, 16, 0, {'value': 0.0, 'at': '10,20', 'budget': 0.005})
    depth = quantity(the(report, 'well-log', 'SYN-A/GR', 'opendtect-to-project'), 'depth')
    assert depth['budget'] == '4*ulp32(given)+4*ulp32(first)' and depth['largest']['budget'] == 4 * cmp.ulp32(100.0) + 4 * cmp.ulp32(100.0)


def count_changed(r):
    quantity(the(r, 'horizon-3d', 'Top', 'opendtect-to-project'), 'nodes')['observed'] = 15


def digest_changed(r):
    quantity(the(r, 'seismic-3d', 'Syn', 'project-to-sdk'), 'samples_sha256')['observed'] = D('other samples')


def tolerance_raised(r):
    quantity(the(r, 'horizon-3d', 'Top', 'opendtect-to-project'), 'x')['budget'] = 0.05


def equal_over_budget(r):
    row = the(r, 'well-path', 'SYN-A', 'project-to-sdk')
    q = quantity(row, 'x')
    q['over_budget'], q['largest'] = 1, {'value': 0.25, 'at': '3', 'budget': 0.0}
    for q in row['quantities']: q['mode'] = 'exact' if q['mode'] == 'tolerance' else q['mode']
    row['state'], row['examples'] = 'equal', []


def absent_without_enumeration(r):
    r['rows'] = [x for x in r['rows'] if x['kind'] != 'well-log']
    r['inventory']['enumerated'] = [i for i in r['inventory']['enumerated'] if i['kind'] != 'well-log']
    r['inventory']['selected'] = [i for i in r['inventory']['selected'] if i['kind'] != 'well-log']
    r['rows'].append({**whole('well-log', 'absent'), 'evidence': {}})


def failed_as_disagree(r):
    row = the(r, 'seismic-3d', 'Syn', 'project-to-sdk')
    row['quantities'], row['state'], row['evidence'] = [], 'disagree', {'error': 'This revision could not be read.'}


def unsupported_row_dropped(r):
    r['rows'] = [x for x in r['rows'] if (x['kind'], x['leg']) != ('horizon-3d', 'project-to-resinsight')]


def unsupported_row_waiting(r):
    row = the(r, 'horizon-3d', 'Top', 'project-to-resinsight')
    row['state'], row['evidence'] = 'not-yet', {'waits_on': 'tool resinsight'}


def resinsight_row_for_a_cube(r):
    r['rows'].append({**waiting('seismic-3d', 'Syn', 'project-to-resinsight', None), 'state': 'unsupported', 'evidence': {'route': 'none'}})


MUTATIONS = {
    'ResInsight horizon row dropped (E139 s2)': (unsupported_row_dropped, [
        'horizon-3d Top project-to-resinsight: missing (a leg with no route is stated as unsupported).']),
    'ResInsight horizon row stated as waiting (E139 s2)': (unsupported_row_waiting, [
        'horizon-3d Top project-to-resinsight: no route exists for this leg; the row is unsupported, its route none, with no quantities.']),
    'an unsupported row on a kind without one (E139 s2)': (resinsight_row_for_a_cube, ['seismic-3d Syn project-to-resinsight: not a leg this kind has.']),
    'one count changed': (count_changed, ['horizon-3d Top opendtect-to-project: nodes: stated agree; expected 16 and observed 15 make it disagree.']),
    'one digest changed': (digest_changed, ['seismic-3d Syn project-to-sdk: samples_sha256: stated agree; expected %r and observed %r make it disagree.'
                                            % (cmp.samples_sha256([syn(i, c, k) for i in INLINES for c in CROSSLINES for k in Z]), D('other samples'))]),
    'a tolerance edited above the table': (tolerance_raised, ["horizon-3d Top opendtect-to-project: x: budget 0.05 and quantum 0.01 are not the table's 0.005 and 0.01."]),
    'equal stated on a difference over the budget': (equal_over_budget, [
        'well-path SYN-A project-to-sdk: md is compared as exact; the table says tolerance.',
        "well-path SYN-A project-to-sdk: md: stated agree; expected None and observed None make it disagree.",
        'well-path SYN-A project-to-sdk: x is compared as exact; the table says tolerance.',
        "well-path SYN-A project-to-sdk: x: stated agree; expected None and observed None make it disagree.",
        'well-path SYN-A project-to-sdk: y is compared as exact; the table says tolerance.',
        "well-path SYN-A project-to-sdk: y: stated agree; expected None and observed None make it disagree.",
        'well-path SYN-A project-to-sdk: tvdss is compared as exact; the table says tolerance.',
        "well-path SYN-A project-to-sdk: tvdss: stated agree; expected None and observed None make it disagree."]),
    'absent without an enumeration': (absent_without_enumeration, [
        'well-log * *: a whole-kind row of an enumerated kind is absent, from an enumeration that lists none.']),
    'failed reported as disagree': (failed_as_disagree, ['seismic-3d Syn project-to-sdk: stated disagree; the evidence makes it failed (This revision could not be read.).']),
}


@pytest.mark.parametrize('name', sorted(MUTATIONS))
def test_each_acceptance_1_mutation_keeps_the_schema_and_the_evaluator_refuses_it(name):
    change, expected = MUTATIONS[name]
    report = example()
    change(report)
    assert judged(report) == expected


def failing_deleted(r):
    """R2-7: a quantity that would fail is left out of the report altogether."""
    row = the(r, 'horizon-3d', 'Top', 'opendtect-to-project')
    row['quantities'] = [q for q in row['quantities'] if q['name'] != 'x']
    row['examples'] = [x for x in row['examples'] if x['quantity'] != 'x']


def nothing_compared(r):
    q = quantity(the(r, 'horizon-3d', 'Top', 'opendtect-to-project'), 'z')
    q['positions'], q['compared'] = 0, 0


def both_shortened(r):
    """R2-7: both arrays lose the same node, so no position is unmatched and nothing is over the budget."""
    gx = grid(lambda i, c: held(i, c)[0])
    del gx['16,26']
    q, _ = cmp.quantity(TABLE, 'horizon-3d', 'opendtect-to-project', 'x', gx, {k: written(v) for k, v in gx.items()}, synthetic=True)
    row = the(r, 'horizon-3d', 'Top', 'opendtect-to-project')
    row['quantities'] = [q if old['name'] == 'x' else old for old in row['quantities']]


def not_finite(r):
    quantity(the(r, 'horizon-3d', 'Top', 'opendtect-to-project'), 'z')['largest']['value'] = float('nan')


def inconsistent(r):
    q = quantity(the(r, 'seismic-3d', 'Syn', 'opendtect-to-project'), 'y')
    q['over_budget'], q['state'] = 17, 'disagree'


COMPLETENESS = {
    'a largest error that is not finite': (not_finite, ['horizon-3d Top opendtect-to-project: z: the largest error nan is not a finite number.']),
    'more over the budget than positions': (inconsistent, [
        'seismic-3d Syn opendtect-to-project: y: 17 over the budget is outside 0 held on one side and 16 positions.',
        'seismic-3d Syn opendtect-to-project: y: 17 values over the budget, yet the largest error 0.0 is within 0.005.',
        'seismic-3d Syn opendtect-to-project: stated within; its quantities make it disagree.']),
    'a failing quantity deleted': (failing_deleted, ['horizon-3d Top opendtect-to-project: x is missing.',
                                                     'horizon-3d Top opendtect-to-project: stated within; its quantities make it disagree.']),
    'compared set to 0': (nothing_compared, ['horizon-3d Top opendtect-to-project: z: nothing was compared.',
                                             'horizon-3d Top opendtect-to-project: z: 0 positions compared; nodes says 16.']),
    'both arrays shortened together': (both_shortened, ['horizon-3d Top opendtect-to-project: x: 15 positions compared; nodes says 16.']),
}


@pytest.mark.parametrize('name', sorted(COMPLETENESS))
def test_each_incomplete_comparison_keeps_the_schema_and_the_evaluator_refuses_it(name):
    change, expected = COMPLETENESS[name]
    report = example()
    change(report)
    assert judged(report) == expected


def test_a_difference_over_the_budget_counted_honestly_makes_the_row_disagree_not_equal():
    report = example()
    row = the(report, 'well-path', 'SYN-A', 'project-to-sdk')
    q = quantity(row, 'x')
    q['over_budget'], q['largest'], q['state'], row['state'] = 1, {'value': 0.25, 'at': '3', 'budget': 0.0}, 'disagree', 'equal'
    assert judged(report) == ['well-path SYN-A project-to-sdk: stated equal; its quantities make it disagree.']


def test_a_corrupt_value_outside_the_kept_examples_is_seen_by_the_aggregates():
    """R1-7: the comparator sees every value; a live run keeps no example, and one value of 200 still decides."""
    expected = {str(n): 1000.0 + n for n in range(200)}
    observed = dict(expected, **{'137': 1000.5 + 137})
    q, examples = cmp.quantity(TABLE, 'horizon-3d', 'opendtect-to-project', 'z', expected, observed, synthetic=False)
    assert (q['state'], q['compared'], q['over_budget'], q['largest'], examples) == ('disagree', 200, 1, {'value': 0.5, 'at': '137', 'budget': 0.0}, [])
    samples = [float(n) for n in range(80)]
    changed = samples[:61] + [samples[61] + 1.0] + samples[62:]
    assert cmp.samples_sha256(samples) != cmp.samples_sha256(changed)


@pytest.mark.parametrize('held_value, file_value, state', [
    (500000.375, 500000.38, 'agree'), (50.125, 50.12, 'agree'), (-49.875, -49.88, 'agree'), (-0.125, -0.12, 'agree'),
    (500000.375, 500000.39, 'disagree'), (500000.375, 500000.37, 'disagree'), (-49.875, -49.87, 'disagree'),
    (0.015, 0.01, 'agree'), (0.015, 0.02, 'disagree'), (0.025, 0.03, 'agree'), (0.025, 0.02, 'disagree')])
def test_coordinates_are_compared_in_whole_hundredths_ties_half_even(held_value, file_value, state):
    """R1-12 / D4 / R2-4: the source side quantised as the exporter rounds, Decimal(v) half-even on the binary value,
    so the unchanged fixture agrees at its ties, 0.015 and 0.025 land where float64 holds them, and one hundredth off
    is over the 0.005 m budget."""
    q, _ = cmp.quantity(TABLE, 'horizon-3d', 'opendtect-to-project', 'x', {'n': held_value}, {'n': file_value}, synthetic=True)
    assert q['state'] == state


def test_the_quantiser_follows_the_exporters_binary_semantics_not_the_shortest_text():
    """R2-4 / R2-8: the counterexamples to Decimal(repr(v)) beside the exactly representable ties."""
    assert [cmp.quantised(v, 0.01) for v in (500000.375, -0.875, 50.125, -49.875, 0.015, 0.025)] == [50000038, -88, 5012, -4988, 1, 3]


def test_a_per_position_budget_decides_at_each_position_and_the_largest_error_carries_its_own():
    """R2-5: the log-depth rule gives a larger budget deeper down; one position over its own budget counts even when
    a larger error elsewhere is within that position's larger budget."""
    first, deep = 100.0, 10000.0
    expected = {'0': first, '1': deep}
    observed = {'0': first + 9 * cmp.ulp32(first), '1': deep + 100 * cmp.ulp32(first)}
    q, _ = cmp.quantity(TABLE, 'well-log', 'opendtect-to-project', 'depth', expected, observed, synthetic=True)
    assert (q['over_budget'], q['state'], q['largest']['at'], q['largest']['budget']) == (1, 'disagree', '1', 4 * cmp.ulp32(deep) + 4 * cmp.ulp32(first))
    assert q['largest']['value'] == pytest.approx(100 * cmp.ulp32(first))


def test_a_moved_null_with_the_same_count_changes_the_mask():
    assert cmp.mask_sha256([False, True, True, True, True, True, False]) != cmp.mask_sha256([False, True, True, True, True, False, True])


def test_a_live_report_carries_no_values_the_schema_and_the_evaluator_both_refuse(monkeypatch):
    report = example()
    report['dataset']['synthetic'] = False
    assert ev.schema_problems(report) != []
    monkeypatch.setattr(ev, 'schema_problems', lambda r: [])
    problems = ev.evaluate(report)
    assert 'horizon-3d Top opendtect-to-project: a live report carries no values.' in problems


def test_a_mandatory_leg_stays_mandatory_when_its_route_is_deleted_from_the_table():
    table = copy.deepcopy(TABLE)
    table['entries'] = [e for e in table['entries'] if (e['kind'], e['leg']) != ('well-path', 'project-to-sdk')]
    report = example()
    report['rows'] = [r for r in report['rows'] if (r['kind'], r['leg']) != ('well-path', 'project-to-sdk')]
    report['tolerances']['sha256'] = ev.table_sha256(table)
    assert ev.evaluate(report, table) == ['well-path SYN-A project-to-sdk: missing (a mandatory leg).']


def test_the_report_names_the_table_it_was_made_under_and_both_removals():
    report = example()
    report['tolerances']['sha256'], report['run']['storage_removed'] = D('an edited table'), False
    assert judged(report) == ['The report was judged against another tolerance table (version 2, sha256 %s).' % D('an edited table'),
                              'The run did not verify its storage removed, so the report is not clean.']


def test_an_object_outside_the_enumeration_a_duplicate_and_a_missing_kind_row_are_refused():
    report = example()
    report['rows'].append(copy.deepcopy(the(report, 'horizon-3d', 'Top', 'project-to-sdk')))
    report['rows'] = [r for r in report['rows'] if r['kind'] != 'fault-sticks']
    the(report, 'well-head', 'SYN-A', 'project-to-qgis')['object'] = 'SYN-B'
    assert judged(report) == ["well-head SYN-B project-to-qgis: the object is not in the survey's enumeration.",
                              'horizon-3d Top project-to-sdk: the row appears twice.',
                              'well-head SYN-A project-to-qgis: missing (a mandatory leg).',
                              'fault-sticks * *: missing (the survey lists none, and no row says absent).']


def test_the_e129_adapter_keeps_tool_level_evidence_only_and_invents_nothing():
    """R2-1: one diagnostic count, the reopening and the tolerance maxima, the same on every row; per object only
    whether it was listed; no per-coordinate count over a budget."""
    rows = ri.rows(E129, 'synthetic', WELLS, LOGS)
    assert [(r['kind'], r['object'], r['state']) for r in rows] == [('well-path', 'SYN-A', 'within'), ('well-path', 'SYN-B', 'within'),
                                                                     ('well-log', 'SYN-A/GR', 'within'), ('well-log', 'SYN-A/DT', 'within')]
    level = {'diagnostics': 0, 'reopened': True, 'tolerance_m': {'x': 0.0313, 'y': 0.00000401, 'z': 0.0000303}, 'scope': ri.SCOPE}
    assert all(r['evidence'] == {'tool_level': level} for r in rows)
    assert [[(q['name'], q['mode'], q['expected'], q['observed']) for q in r['quantities']] for r in rows] == [
        [('listed', 'count', 1, 1), ('diagnostics', 'count', 0, 0), ('reopened', 'exact', 'yes', 'yes')]] * 4
    assert not any('over_budget' in q or 'largest' in q for r in rows for q in r['quantities'])
    assert rows[2]['sampled'] == 'at most 50 positions across all supplied logs, drawn once'
    assert rows[0]['not_recorded'] == ['largest error', 'over budget per position', 'observed arrays']
    # C3 live run: a log is listed by its LAS mnemonic, in capitals, whatever its OpendTect name
    spaced = dict(E129, wells=[dict(E129['wells'][0], logs=[{'las': 'wells/SYN-A.las', 'curves': ['DEPT', 'Gamma_ray'], 'rows': 7}])])
    assert [r['state'] for r in ri.rows(spaced, 'synthetic', [], ['SYN-A/Gamma ray', 'SYN-A/DT'])] == ['within', 'disagree']


def refused(adapter, result):
    """A negative is seen when every row disagrees on a counted diagnostic, or the unlisted well's row does."""
    rows = adapter(result, 'synthetic', WELLS, LOGS)
    if result['differences']: assert [r['state'] for r in rows] == ['disagree'] * 4
    else: assert [(r['object'], r['state']) for r in rows if r['state'] != 'within'] == [('SYN-B', 'disagree')]


def zero(result, host, wells, logs):
    """A copying adapter: E129's shape with nothing found."""
    return ri.rows(dict(result, differences=0, wells=E129['wells']), host, wells, logs)


@pytest.mark.parametrize('name', sorted(NEGATIVES))
def test_each_frozen_e129_negative_disagrees_and_a_copying_adapter_misses_it(name):
    """R2-9: missing well, geometry-only, log-only, and before/after diagnostics; the copying adapter fails each."""
    result = NEGATIVES[name]
    refused(ri.rows, result)
    with pytest.raises(AssertionError):
        refused(zero, result)
    counted = ri.rows(result, 'synthetic', WELLS, LOGS)
    assert {r['evidence']['tool_level']['diagnostics'] for r in counted} == {result['differences']}


# --- E138 s1 §5 mutations on the record (strategy rev 5 D3, D4, D10; R1-1, R1-4, R1-14, R2-2, R2-9e, R2-9f) ----------

def horizon_waiting(r, total, defined, kind='horizon-3d', obj='Top'):
    """Every row of one object stated as waiting on E139 s2 with node counts."""
    for x in r['rows']:
        if (x['kind'], x['object']) == (kind, obj) and x['state'] != 'unsupported':
            x.update(state='not-yet', evidence={'waits_on': 'E139 s2', 'nodes': {'total': total, 'defined': defined}}, quantities=[], examples=[], tool=None)
    r['inventory']['selected'] = [i for i in r['inventory']['selected'] if (i['kind'], i['object']) != (kind, obj)]


def test_mutation_3_only_a_horizon_above_the_admission_waits_on_e139_s2():
    report = example()
    horizon_waiting(report, 100_001, 90_000)
    assert judged(report) == []
    report = example()
    horizon_waiting(report, 100_000, 90_000)
    assert judged(report) == ['horizon-3d Top %s: only a horizon of more than 100000 nodes in total waits on E139 s2, with its node counts.' % leg
                              for leg in ('opendtect-to-project', 'project-to-sdk', 'project-to-qgis')]
    report = example()
    horizon_waiting(report, 100_001, 90_000, 'well-path', 'SYN-A')
    assert [p for p in judged(report) if 'E139 s2' in p] == [
        'well-path SYN-A %s: only a horizon of more than 100000 nodes in total waits on E139 s2, with its node counts.' % leg
        for leg in ('opendtect-to-project', 'project-to-sdk', 'project-to-resinsight')]


def test_mutation_2_selected_must_be_the_enumeration_less_the_waiting_objects():
    report = example()
    report['inventory']['selected'] = [i for i in report['inventory']['selected'] if i['kind'] != 'well-log']
    assert judged(report) == ['The selected objects are not the enumerated ones less those whose every row waits (4 selected, 5 expected).']
    report = example()
    report['inventory']['enumerated'].append({'kind': 'horizon-3d', 'object': 'Base'})
    assert judged(report) == ['horizon-3d Base opendtect-to-project: missing (a mandatory leg).', 'horizon-3d Base project-to-sdk: missing (a mandatory leg).',
                              'horizon-3d Base project-to-qgis: missing (a mandatory leg).',
                              'horizon-3d Base project-to-resinsight: missing (a leg with no route is stated as unsupported).',
                              'The selected objects are not the enumerated ones less those whose every row waits (5 selected, 6 expected).']


def not_listed(r, kind='line-2d', cls='read error'):
    r['inventory']['not_listed'] = [{'kind': kind, 'class': cls}]
    r['rows'] = [x for x in r['rows'] if x['kind'] != kind]


def test_mutation_11_a_kind_that_could_not_be_listed_is_failed_never_absent():
    report = example()
    not_listed(report)
    report['rows'].append({**absent('line-2d'), 'state': 'failed', 'evidence': {'class': 'read error'}})
    assert judged(report) == []
    report = example()
    not_listed(report)
    report['rows'].append(absent('line-2d'))
    assert judged(report) == ['line-2d * *: a kind the survey could not list is failed with its class alone, never absent.']
    report = example()
    not_listed(report)
    assert judged(report) == ['line-2d * *: missing (the kind could not be listed, and no row says failed).']
    report = example()
    the(report, 'line-2d', '*', '*')['evidence'] = {'enumeration': 'Survey.line_names'}
    assert judged(report) == ['line-2d * *: a whole-kind row of an enumerated kind is absent, from an enumeration that lists none.']


def identities(r):
    """A listing with two 2D horizons and one Fault3D: three per-identity rows, no whole-kind row for those kinds (E138
    s2: lines are judged, so the 2D horizons wait here)."""
    r['rows'] = [x for x in r['rows'] if x['kind'] not in ('horizon-2d', 'fault-sticks')]
    for kind, obj in (('horizon-2d', 'L1'), ('horizon-2d', 'L2'), ('fault-sticks', 'F1')):
        r['inventory']['enumerated'].append({'kind': kind, 'object': obj})
        r['rows'].append(waiting(kind, obj, '*', ev.WAITING[kind]))


def test_mutation_12_each_listed_identity_of_a_waiting_kind_has_its_row():
    report = example()
    identities(report)
    assert judged(report) == [] and [r['evidence']['waits_on'] for r in report['rows'] if r['leg'] == '*' and r['object'] != '*'] == ['E137 s6', 'E137 s6', 'E137 s2']
    report = example()
    identities(report)
    report['rows'] = [r for r in report['rows'] if r['object'] != 'L2']
    assert judged(report) == ['horizon-2d L2 *: missing (each identity of a kind that waits has its row).',  # an object with no row is not one that waits
                              'The selected objects are not the enumerated ones less those whose every row waits (5 selected, 6 expected).']
    report = example()
    identities(report)
    report['rows'] = [r for r in report['rows'] if r['kind'] != 'horizon-2d'] + [whole('horizon-2d', 'not-yet', 'E137 s6')]
    assert judged(report) == ['horizon-2d * *: a whole-kind row of an enumerated kind is absent, from an enumeration that lists none.',
                              'horizon-2d L1 *: missing (each identity of a kind that waits has its row).',
                              'horizon-2d L2 *: missing (each identity of a kind that waits has its row).',
                              'The selected objects are not the enumerated ones less those whose every row waits (5 selected, 7 expected).']
    report = example()
    report['inventory']['enumerated'].append({'kind': 'fault-sticks', 'object': 'F1'})
    report['rows'].append(waiting('fault-sticks', 'F1', '*', 'E137 s2'))
    assert judged(report) == ['fault-sticks * *: a whole-kind row of an enumerated kind is absent, from an enumeration that lists none.']


def stopped(r):
    r['run'].update(stopped={'sentence': 'The deposit or its unpacked survey changed during the run; no row is judged.', 'differing': 1},
                    survey_unchanged=False, archive_unchanged=True)
    r['rows'], r['inventory']['selected'] = [], []


def test_mutation_15_a_stopped_run_has_no_judged_row_and_no_coverage_check():
    report = example()
    stopped(report)
    assert judged(report) == [] and ev.verdict(report, []) == 'stopped'
    report['rows'].append(example()['rows'][0])
    assert judged(report) == ['The run stopped (The deposit or its unpacked survey changed during the run; no row is judged.), yet 1 row(s) are judged.']
    report = example()
    report['run']['survey_unchanged'] = False
    assert judged(report) == ['The run states its survey unchanged false, yet it did not stop.']
    report = example()
    report['rows'] = []
    assert 'The report holds no row, and the run did not stop.' in judged(report)


def test_mutation_16_the_memory_record_needs_its_tree_sample():
    report = example()
    report['run']['memory'] = {'maxrss_kib': {'journey': 81_000, 'largest child': 64_000}, 'tree_max_kib': {'online': 150_000, 'offline': 90_000}, 'within_target': True}
    assert judged(report) == [] and ev.verdict(report, []) == 'clean'
    del report['run']['memory']['tree_max_kib']
    assert judged(report) == ['The run claims the 2 GB target without a sample of its process tree.']
    report['run']['memory'].update(tree_max_kib={'online': ev.TARGET_KIB + 1}, within_target=False)
    assert judged(report) == ['The run\'s process tree reached %d KiB, above the 2 GB target.' % (ev.TARGET_KIB + 1)]
    report['run']['memory'].update(tree_max_kib={'online': ev.TARGET_KIB}, within_target=False)
    assert judged(report) == ['The run says it missed the 2 GB target its sample meets.']


def test_a_live_report_numbers_its_objects_keeps_classes_and_records_its_checks():
    report = example()
    report['dataset']['synthetic'] = False
    for r in report['rows']: r['examples'] = []
    the(report, 'seismic-3d', 'Syn', 'project-to-sdk').update(state='failed', quantities=[], evidence={'error': 'The cube “Syn” could not be read.', 'class': 'read error'})
    problems = judged(report)
    assert 'seismic-3d Syn project-to-sdk: a live report keeps the class of a failure, never its words (D10).' in problems
    assert {'seismic-3d: a live report numbers its objects (D10).', 'A live run verifies its survey unchanged.', 'A live run records its memory.',
            'A live run records its cleanup.', 'A live run records its limits.'} <= set(problems)


def test_a_stopped_live_report_owes_no_memory_cleanup_or_limits():
    """C3 live run: a live run that stopped before its second digest writes the stopped report, which records none."""
    run = {'stopped': {'sentence': 'The run stopped before its second digest (Unread).', 'differing': 0}, 'work_folder_removed': True, 'storage_removed': True}
    assert ev.run_problems(run, True) == []
    assert 'A live run records its memory.' in ev.run_problems({'work_folder_removed': True, 'storage_removed': True}, True)
