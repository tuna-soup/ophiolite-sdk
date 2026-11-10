"""E168 s1 C1: ophiolite.kinds(), ophiolite.profiles_for(kind) and `ophiolite data kinds` read the export matrix and
never compute a kind (charter acceptance 2)."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys

import pytest

import ophiolite
from ophiolite import cli, osdu

WELL_LOG = 'osdu:wks:work-product-component--WellLog:1.5.0'
FILE_ROWS = json.loads(osdu.MATRIX.read_text(encoding='utf-8'))['rows']  # the oracle is the file, not a typed count
WELL_LOGS = ['las2/1', 'wavelet-text/1', 'time-depth-csv/1', 'ophiolite.table-target/time-depth/1']
REASON = next(r['none'] for r in FILE_ROWS if r['profile'] == 'points-csv/1')


def lookup_module(monkeypatch):
    """s0's synced lookup (its folder is not a package), loaded without writing bytecode into the contract snapshot
    (sync_contracts.py refuses a path the snapshot does not hold)."""
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    spec = importlib.util.spec_from_file_location('e168_osdu_kind', osdu.MATRIX.parent / 'osdu_kind.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def renamed(tmp_path, monkeypatch):
    """The packaged matrix with las2/1 renamed las2/9: a well-formed table, so only the rename can fail a test."""
    document = json.loads(osdu.MATRIX.read_text(encoding='utf-8'))
    [row] = [r for r in document['rows'] if r['profile'] == 'las2/1']
    row['profile'] = 'las2/9'
    (tmp_path / 'export-matrix.json').write_text(json.dumps(document), encoding='utf-8')
    monkeypatch.setattr(osdu, 'MATRIX', tmp_path / 'export-matrix.json')


def offline(monkeypatch):
    """Configuration, credentials and the transport refuse to be reached."""
    def reached(*_args, **_kwargs): raise AssertionError('kinds reached configuration or the network')
    monkeypatch.setattr(cli, '_load', reached); monkeypatch.setattr(cli, 'configuration', reached)
    import httpx
    monkeypatch.setattr(httpx.Client, 'send', reached)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


def test_the_sdk_reads_the_table_s0s_lookup_reads(monkeypatch):
    cache = osdu.MATRIX.parent / '__pycache__'  # an installed wheel has one already (pip compiles); the load adds nothing
    before = sorted(cache.iterdir()) if cache.exists() else None
    assert osdu.MATRIX == lookup_module(monkeypatch).MATRIX and osdu.MATRIX.is_file()
    assert (sorted(cache.iterdir()) if cache.exists() else None) == before


def test_kinds_are_the_matrix_rows_in_order_and_a_caller_cannot_change_the_next_answer():
    rows = ophiolite.kinds()
    assert rows == FILE_ROWS and len(rows) == len(FILE_ROWS)
    rows[0]['kind'] = 'changed'; rows[0]['declarations'].append('changed'); rows[1]['losses'].append('changed'); rows.pop()
    assert ophiolite.kinds() == FILE_ROWS


def test_profiles_for_the_well_log_kind_is_exactly_the_matrix_set():
    assert ophiolite.profiles_for(WELL_LOG) == WELL_LOGS == [r['profile'] for r in FILE_ROWS if r.get('kind') == WELL_LOG]


def test_every_kind_in_the_matrix_answers_its_rows_and_each_profile_once():
    named = {r['kind'] for r in FILE_ROWS if r.get('kind')}
    assert sorted(p for k in named for p in ophiolite.profiles_for(k)) == sorted(r['profile'] for r in FILE_ROWS if r.get('kind'))


@pytest.mark.parametrize('kind', ['osdu:wks:work-product-component--WellLog:9.9.9', 'osdu:wks:work-product-component--WellLog:1.5',
                                  'osdu:wks:work-product-component--WellLog', 'OSDU:WKS:WORK-PRODUCT-COMPONENT--WELLLOG:1.5.0',
                                  ' ' + WELL_LOG, WELL_LOG + ' ', ''])
def test_an_unknown_kind_is_an_empty_list_never_a_near_match(kind):
    assert ophiolite.profiles_for(kind) == []


def test_a_kind_that_is_not_a_string_is_refused():
    with pytest.raises(TypeError):
        ophiolite.profiles_for(None)


def test_a_renamed_matrix_row_changes_both_answers(renamed, monkeypatch):
    offline(monkeypatch)
    assert ophiolite.profiles_for(WELL_LOG) == ['las2/9'] + WELL_LOGS[1:]
    _, text = run('data', 'kinds')
    assert 'las2/1 ' not in text and text.splitlines()[0].split() == ['las2/9', WELL_LOG]


def test_data_kinds_prints_one_line_per_matrix_row_offline(monkeypatch):
    offline(monkeypatch)
    code, text = run('data', 'kinds')
    lines = text.splitlines()
    assert len(lines) == len(FILE_ROWS)
    assert [line.split()[0] for line in lines] == [r['profile'] for r in FILE_ROWS]
    assert lines[0].split() == ['las2/1', WELL_LOG]
    [points] = [line for line in lines if line.split()[0] == 'points-csv/1']
    assert points.split(None, 1)[1] == 'none: ' + REASON


def test_data_kinds_json_is_the_file_rows_in_order(monkeypatch):
    offline(monkeypatch)
    code, text = run('data', 'kinds', '--json')
    assert json.loads(text) == {'kinds': FILE_ROWS}


def test_the_flat_spelling_answers_the_same_and_says_its_grouped_one_at_a_terminal():
    from test_cli_groups import at_terminal
    assert run('kinds') == run('data', 'kinds') and run('kinds', '--json') == run('data', 'kinds', '--json')
    old, new = at_terminal('kinds'), at_terminal('data', 'kinds')
    line = 'ophiolite kinds is now ophiolite data kinds; the old spelling stops working in the next release.\n'
    assert old[0] == new[0] == 0 and old[1] == new[1] and old[2] == line + new[2]


def test_the_installed_wheel_carries_the_table_and_the_command(tmp_path):
    from test_init_wheel import WHEEL, clean_env, installed_outside
    import os
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    assert installed_outside(WHEEL, tmp_path)
    script = 'import json, ophiolite; print(json.dumps([ophiolite.kinds(), ophiolite.profiles_for(%r)]))' % WELL_LOG
    done = subprocess.run([WHEEL, '-c', script], cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [FILE_ROWS, WELL_LOGS]
    done = subprocess.run([WHEEL, '-m', 'ophiolite', 'data', 'kinds', '--json'], cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and json.loads(done.stdout) == {'kinds': FILE_ROWS}, done.stderr
