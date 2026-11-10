"""E141 s4: conformance/roundtrip/window_readback.py against the synthetic survey (the fake odbind of
test_roundtrip_journey.py: Syn 4 x 4 x 5 on inlines 10-16 step 2, crosslines 20-26 step 2, z 100-116 step 4; Syn2
2 x 2 x 5 on 12-14 step 2, 22-24 step 2, z 102-110 step 2), the read CLI's oracle and the loopback project. The piece
bound is lowered on both sides to 40 bytes (two traces of five samples), so windows cross pieces at this size; the
command line runs in this process (the lowered SDK bound is this process's), through the helper's `cli` argument.

Expected values are counted by hand, never computed by the helper. Mutations it catches (each applied to the
helper, red, restored):
  1. off-by-one crop: `plan` starts the crop at ordinal 0 (the hand-counted plan differs);
  2. swapped inline/crossline: `keys` walks crossline-major (every Syn row disagrees on samples);
  3. a z offset: `Grid.z` adds one interval (every row disagrees on z);
  4. a dropped piece: `by_http` asks one piece less (every http row disagrees);
  5. the comparator always equal: `same32` returns True (the tampered runs answer equal).
"""
import contextlib
import importlib.util
import io
import os
import stat
import sys
from pathlib import Path

import pytest

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (the gateway lane's fixtures)
from test_roundtrip_journey import exporter_env, survey, zipped  # noqa: F401
from test_roundtrip_oracle import loopback_build
from project_gateway import volume_windows as vw
from ophiolite import volume_windows as svw

ROOT = Path(__file__).resolve().parents[3]
PIECE = 40  # two traces of five samples


def _module(name):
    key = 'roundtrip_' + name
    if key in sys.modules: return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / 'conformance/roundtrip' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[key] = loaded
    spec.loader.exec_module(loaded)
    return loaded


wr, ro, lt = _module('window_readback'), _module('read_oracle'), _module('live_target')

# the windows by label, counted by hand from the grids and the 40-byte bound
PLAN = {
    'Syn': {'full-inline': ('14:14', '20:26', '0:4'), 'crop': ('12:14', '22:24', '1:3'),
            'corner-1': ('10:10', '20:20', '2:4'), 'corner-2': ('10:10', '26:26', '2:4'), 'corner-3': ('16:16', '20:20', '2:4'),
            'corner-4': ('16:16', '26:26', '2:4'), 'piece-crossing': ('12:12', '20:26', '0:4')},
    'Syn2': {'full-inline': ('14:14', '22:24', '0:4'), 'crop': ('14:14', '24:24', '1:3'),
             'corner-1': ('12:12', '22:22', '2:4'), 'corner-2': ('12:12', '24:24', '2:4'), 'corner-3': ('14:14', '22:22', '2:4'),
             'corner-4': ('14:14', '24:24', '2:4'), 'piece-crossing': ('12:14', '22:24', '0:4')}}
SAMPLES = {'full-inline': 20, 'crop': 12, 'piece-crossing': 20, **{'corner-%d' % n: 3 for n in range(1, 5)}}  # Syn
SAMPLES2 = {'full-inline': 10, 'crop': 3, 'piece-crossing': 20, **{'corner-%d' % n: 3 for n in range(1, 5)}}  # Syn2
PIECES = {'full-inline': 2, 'crop': 2, 'piece-crossing': 2, **{'corner-%d' % n: 1 for n in range(1, 5)}}  # Syn, 40-byte pieces
ROWS_PER_CUBE = 7 * 2 + 2  # sdk and http for every window, cli for crop and piece-crossing


def in_process_cli(monkeypatch):
    """The command line's own main in this process: FOLDER its working folder, ENV its whole environment."""
    from ophiolite import cli

    def run(argv, folder, env):
        out = io.StringIO()
        with monkeypatch.context() as m:
            m.chdir(folder)
            for name in [k for k in os.environ if k not in env]: m.delenv(name)
            for name, value in env.items(): m.setenv(name, value)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try: code = cli.entrypoint(argv)
                except SystemExit as stop: code = stop.code
        return code or 0, out.getvalue()
    return run


@pytest.fixture
def readback(survey, service, tmp_path):
    """readback(hooks=None) -> the report of one synthetic run on a volume of its own."""
    layout = vw.layout
    survey.setattr(vw, 'RESULT_BYTES', PIECE)
    survey.setattr(vw, 'layout', lambda resolved, *_: layout(resolved, PIECE))
    survey.setattr(svw, 'BYTES_MAX', PIECE)
    archive, volume = tmp_path / 'syn-survey.zip', tmp_path / 'volume'
    archive.write_bytes(zipped()); volume.mkdir()

    def go(hooks=None):
        target = lt.LiveTarget(loopback_build(service, survey, []), {'OPHIOLITE_MAX_FILE_BYTES': 2 ** 21, 'OPHIOLITE_MAX_UPLOAD_TOTAL_BYTES': 2 ** 24},
                               version='test', host='synthetic', lifespan='off')
        report = wr.run(archive, volume, target, oracle=ro.ReadOracle(sys.executable, exporter_env(), timeout=120), exporter_env=exporter_env(),
                        forbidden=[tmp_path / 'forbidden'], cli=in_process_cli(survey), hooks=hooks, host='synthetic')
        assert os.listdir(volume) == []
        return report
    return go


def rows_of(report, cube=None, verdict=None):
    return [r for r in report['rows'] if (cube is None or r['cube'] == cube) and (verdict is None or r['verdict'] == verdict)]


def test_every_window_of_both_cubes_reads_back_equal_by_every_path(readback):
    report = readback()
    assert report['format'] == 'ophiolite.window-readback/1'
    assert [(c['object'], c['state']) for c in report['cubes']] == [('Syn', 'judged'), ('Syn2', 'judged')]
    assert report['summary'] == {'rows': 2 * ROWS_PER_CUBE, 'equal': 2 * ROWS_PER_CUBE, 'disagree': 0}
    for cube in ('Syn', 'Syn2'):
        planned = {(r['window'], r['query']['inline'], r['query']['crossline'], r['query']['sample']) for r in rows_of(report, cube)}
        assert planned == {(w, *q) for w, q in PLAN[cube].items()}
        counts = SAMPLES if cube == 'Syn' else SAMPLES2
        assert {(r['window'], r['path']): r['samples_compared'] for r in rows_of(report, cube)} == \
            {**{(w, p): counts[w] for w in counts for p in ('sdk', 'http')}, ('crop', 'cli'): counts['crop'], ('piece-crossing', 'cli'): counts['piece-crossing']}
    assert {r['window']: r['pieces'] for r in rows_of(report, 'Syn') if r['path'] == 'http'} == PIECES
    (syn,) = [c for c in report['cubes'] if c['object'] == 'Syn']
    assert syn['grid'] == {'inlines': 4, 'crosslines': 4, 'samples': 5} and syn['bytes_max'] == PIECE and syn['not_planned'] == []
    run = report['run']
    assert run['work_folder_removed'] and run['storage_removed'] and run['survey_unchanged'] and run['archive_unchanged'] and run['no_processes']


def test_a_crop_asked_one_inline_off_disagrees_on_its_labels(readback):
    def off(cube, window, query):
        return {**query, 'inline': '14:16'} if (cube, window) == ('Syn', 'crop') else query
    report = readback({'query': off})
    bad = rows_of(report, verdict='disagree')
    assert {(r['cube'], r['window'], r['path']) for r in bad} == {('Syn', 'crop', p) for p in ('sdk', 'http', 'cli')}
    assert {r['path']: r['first_difference'] for r in bad} == {'sdk': {'key': 'inline', 'quantity': 'labels'}, 'http': {'key': 'inline', 'quantity': 'labels'},
                                                               'cli': {'key': '12,22', 'quantity': 'labels'}}
    assert {r['max_abs_difference'] for r in bad} == {2.0}  # inline 14 against 12: i + c/4 + k/16 moves by 2


def test_a_dropped_piece_disagrees_by_its_read(readback):
    report = readback({'pieces': lambda n: range(n - 1) if n > 1 else range(n)})
    bad = rows_of(report, verdict='disagree')
    assert {(r['cube'], r['window']) for r in bad} == {('Syn', w) for w in ('full-inline', 'crop', 'piece-crossing')} | {('Syn2', 'piece-crossing')}
    assert {r['path'] for r in bad} == {'http'}
    assert {r['first_difference']['quantity'] for r in bad} == {'read'} and {r['stopped'] for r in bad} == {'Disagree: the window is not complete'}
    assert {r['traces'] for r in bad if (r['cube'], r['window']) == ('Syn', 'crop')} == {3}  # 40 // (3 samples x 4) = 3 traces in piece 0; piece 1 (the fourth trace) dropped


def test_a_z_axis_one_interval_late_disagrees_on_every_row(readback, monkeypatch):
    real = wr.Judge.axes
    monkeypatch.setattr(wr.Judge, 'axes', lambda self, i, c, z0, zstep, *a, **k: real(self, i, c, z0 + zstep, zstep, *a, **k))
    report = readback()
    assert report['summary']['equal'] == 0
    assert {r['first_difference']['quantity'] for r in report['rows']} == {'z'}


def test_traces_read_crossline_major_disagree_on_their_samples(readback, monkeypatch):
    keys = wr.keys
    monkeypatch.setattr(wr, 'keys', lambda grid, window: [(k[0], k[1]) for k in sorted(keys(grid, window), key=lambda k: (k[1], k[0]))])
    report = readback()
    bad = {(r['cube'], r['window'], r['path']): (r['first_difference'], r['max_abs_difference']) for r in rows_of(report, 'Syn', 'disagree')}
    assert bad[('Syn', 'crop', 'sdk')] == ({'key': '14,22', 'quantity': 'samples', 'sample': 1}, 1.5)  # (12,24) read where (14,22) is kept


def test_a_cube_with_no_crop_or_crossing_window_is_read_by_the_command_line_on_its_full_inline(readback, monkeypatch):
    plan = wr.plan
    monkeypatch.setattr(wr, 'plan', lambda grid, bound: {w: q for w, q in plan(grid, bound).items() if w not in ('crop', 'piece-crossing')})
    report = readback()
    assert report['summary'] == {'rows': 2 * (5 * 2 + 1), 'equal': 2 * (5 * 2 + 1), 'disagree': 0}
    assert {(r['cube'], r['window']) for r in report['rows'] if r['path'] == 'cli'} == {('Syn', 'full-inline'), ('Syn2', 'full-inline')}
    assert {c['object']: c['not_planned'] for c in report['cubes']} == {'Syn': ['crop', 'piece-crossing'], 'Syn2': ['crop', 'piece-crossing']}


def test_the_report_is_written_0600_and_never_inside_a_repository(tmp_path, monkeypatch):
    with pytest.raises(wr.wf.Refused):
        wr.write({'format': wr.FORMAT}, ROOT / 'report.json')
    monkeypatch.setattr(wr.wf, 'forbidden_roots', lambda extra=(): [])
    out = wr.write({'format': wr.FORMAT}, tmp_path / 'report.json')
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
