"""E144 s1 C4: `ophiolite.rules.run(path, kind, declared=)` on this computer equals each case's hand-written oracle
(the contract snapshot's rules/v1/fixtures/run, checked against its plants in the Platform, never against this path),
and so equals what the Gateway stores at landing. The installed wheel runs it with no asset_connectors."""
import json
import os
import subprocess
from importlib.resources import files

import pytest

from ophiolite import rules
from ophiolite.data_rules import engine
from ophiolite.readers import ReadRefused

from test_init_wheel import ROOT, clean_env, installed_outside

WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
RUN = files('ophiolite').joinpath('contracts/rules/v1/fixtures/run')
CASES = json.loads(RUN.joinpath('cases.json').read_bytes())


def oracle(case):
    """The current snapshot's oracle (E144 s2: 1.3.0; a tops file's top-on-path/1 is offline here)."""
    return engine.canonical(engine.parse(RUN.joinpath('1.3.0', '%s.expected.json' % case['name']).read_bytes()))


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_each_case_run_offline_equals_its_oracle(case):
    """Mutations: a None sample not mapped to NaN (las-other-null), the index taken from column 2 (every LAS case), the
    declarations dropped (survey-m, survey-ft, tops) -> red."""
    assert engine.canonical(rules.run(str(RUN.joinpath(case['file'])), case['kind'], declared=case['declared'])) == oracle(case)


def test_a_kind_no_rule_reads_answers_no_results_without_reading(tmp_path):
    block = rules.run(str(tmp_path / 'absent.obj'), 'mesh-text/1')  # E144 s2: an ESRI grid is read by in-area-of-use/1
    assert block == {'schema': 'ophiolite.rule-results/1', 'kind': 'mesh-text/1', 'registry_version': '1.3.0', 'results': []}


def test_a_file_the_reader_refuses_raises_its_refusal(tmp_path):
    (tmp_path / 'survey.csv').write_text('md,inclination,azimuth\n0,0,0\n10,1,1\n5,1,1\n')
    with pytest.raises(ReadRefused) as refused:
        rules.run(str(tmp_path / 'survey.csv'), 'deviation-csv/1', declared={'depth_unit': 'm'})
    assert refused.value.code == 'not-increasing'


PROBE = '''\
import sys
sys.modules['asset_connectors'] = None  # any import of Connectors now fails, installed or not
from ophiolite import rules
from ophiolite.data_rules import engine
print(rules.__file__)
print(engine.canonical(rules.run('log.las', 'las2/1')).decode())
'''


def test_the_installed_wheel_runs_the_rules_with_no_connectors(tmp_path):
    """Mutations: the SDK copy imports asset_connectors -> the probe fails, red; the child given PYTHONPATH=<checkout>
    -> the path assertion is red."""
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    assert installed_outside(WHEEL, tmp_path)
    case = next(c for c in CASES if c['name'] == 'las-gr')
    (tmp_path / 'log.las').write_bytes(RUN.joinpath(case['file']).read_bytes())
    done = subprocess.run([WHEEL, '-c', PROBE], cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    where, block = done.stdout.splitlines()
    assert not where.startswith(str(ROOT / 'ophiolite') + os.sep), where
    assert block.encode() == oracle(case)


# --- E144 s2: the spatial rules offline, under the current snapshot 1.3.0 (C4 ran them under a pending overlay) -----

SPATIAL_CASES = json.loads(RUN.joinpath('spatial-cases.json').read_bytes())
SDK_READS = ('points-csv/1', 'esri-ascii-grid/1')


@pytest.mark.parametrize('case', [c for c in SPATIAL_CASES if c['kind'] in SDK_READS],
                         ids=[c['name'] for c in SPATIAL_CASES if c['kind'] in SDK_READS])
def test_each_spatial_case_the_sdk_reads_run_offline_equals_its_oracle(case):
    """Mutations: the grid's present cells taken south row first (grid-rd), the declared crs dropped (points-rd) -> red."""
    block = rules.run(str(RUN.joinpath(case['file'])), case['kind'], declared=case['declared'])
    expected = engine.parse(RUN.joinpath('1.3.0', '%s.expected.json' % case['name']).read_bytes())
    assert engine.canonical(block) == engine.canonical(expected)


@pytest.mark.parametrize('case', [c for c in SPATIAL_CASES if c['kind'] not in SDK_READS],
                         ids=[c['name'] for c in SPATIAL_CASES if c['kind'] not in SDK_READS])
def test_a_spatial_kind_the_sdk_does_not_read_is_the_readers_refusal(case):
    """R1-2: read before adapting, so a kind with rules but no SDK reader is `not-a-process-kind`, never a KeyError."""
    with pytest.raises(ReadRefused) as refused:
        rules.run(str(RUN.joinpath(case['file'])), case['kind'], declared=case['declared'])
    assert (refused.value.code, refused.value.field) == ('not-a-process-kind', 'kind')
