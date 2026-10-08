"""E86 C8: the table targets from the packaged contracts, `ophiolite targets` and the shared renderer (R12).

The expected sentences are literals: the strategy's worked example, the fifteen E43 sentences that Platform's
test_mapping_words.py holds (written from the Workspace's words before they moved), and every case of the render cases
shared with Connectors and the Workspace (copied into tests/fixtures, compared with a Connectors checkout when one is
beside this repository)."""
import json
import os
from importlib.resources import files
from pathlib import Path

import pytest

from ophiolite import targets
from ophiolite.cli import entrypoint
from ophiolite.models.generated import TableTarget

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/render-cases.json').read_text())['cases']
PACKAGED = files('ophiolite').joinpath('contracts')


def test_the_registry_lists_six_targets_and_each_is_the_generated_model():
    listed = targets.targets()
    assert [t.target for t in listed] == ['wells', 'well-tops', 'deviation-survey', 'point-set', 'time-depth', 'table']
    assert all(isinstance(t, TableTarget) for t in listed)
    wells = targets.target('wells')
    assert wells.field_names == ['id', 'name', 'x', 'y', 'depth', 'operator']
    assert [v.label for v in wells.declaration('depth_unit').values] == ['Metres', 'International feet']
    assert targets.target('well-tops').reader_names == {'name': 'name', 'md': 'md', 'tvd': 'tvd', 'source': 'source'}
    with pytest.raises(KeyError): wells.declaration('nope')
    with pytest.raises(KeyError): targets.target('nope')


def test_targets_json_prints_the_document(capsys):
    entrypoint(['targets', 'well-tops', '--json'])
    assert json.loads(capsys.readouterr().out) == json.loads(PACKAGED.joinpath('targets/v1/well-tops.json').read_text())


def test_targets_without_a_name_lists_them_in_words(capsys):
    entrypoint(['targets'])
    assert capsys.readouterr().out.splitlines() == ['wells - Wells', 'well-tops - Well tops', 'deviation-survey - Deviation survey', 'point-set - Points',
                                                    'time-depth - Time-depth pairs (waits for E57)', 'table - Table (waits for E58b)']


def test_an_unknown_target_exits_2(capsys):
    with pytest.raises(SystemExit) as stopped: entrypoint(['targets', 'cores'])
    assert stopped.value.code == 2 and "No table type is named 'cores'" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stopped: entrypoint(['targets', 'cores', '--json'])
    assert stopped.value.code == 2 and json.loads(capsys.readouterr().out)['error']['code'] == 'unknown-target'


def test_the_worked_example_gives_its_two_sentences():
    report = {'rows_checked': 5}
    assert targets.render('well-tops', report, {'field': 'md', 'code': 'not-numeric', 'severity': 'invalid', 'rows': 1,
                                               'examples': [{'row_key': 'row 2', 'value': '17x9.0', 'truncated': False}]}, {}) == \
        '1 of 5 rows have a measured depth that is not a number, for example 17x9.0.'
    assert targets.render(targets.target('well-tops'), report, {'field': 'well', 'code': 'reference-missing', 'severity': 'invalid', 'rows': 1,
                                                               'examples': [{'row_key': 'row 4', 'value': None, 'truncated': False}]}, {}) == '1 of 5 rows have no well.'


TWO = [{'row_key': 'W-3', 'value': 'abc', 'truncated': False}, {'row_key': 'W-9', 'value': '7.5x', 'truncated': True},
       {'row_key': 'W-12', 'value': 'zz', 'truncated': False}]
RD = {'crs': 'EPSG:28992'}
E43 = [  # Platform test_mapping_words.py CASES (rows 1,200 of 1,661), the ones without a long tail
    ('id-repeated', 'id', TWO, RD, '1,200 of 1,661 rows share their well identifier with another row; each well needs its own.'),
    ('not-numeric', 'depth', TWO, RD, '1,200 of 1,661 rows have a depth that is not a number, for example abc and 7.5x….'),
    ('latitude-out-of-range', 'y', TWO[:1], {'crs': 'EPSG:4326'},
     '1,200 of 1,661 rows have a Y outside -90 to 90, for example abc; the selected system is WGS 84 (longitude, latitude).'),
    ('longitude-out-of-range', 'x', TWO, RD,
     '1,200 of 1,661 rows have an X outside -180 to 180, for example abc and 7.5x…; the selected system is Amersfoort / RD New (metres).'),
    ('field-not-mapped', 'operator', [], RD, 'Choose the column that holds the operating organization.'),
    ('mapping-invalid', None, [], RD, 'Part of this mapping cannot be used as it is; review its settings.'),
]


@pytest.mark.parametrize('code,field,examples,declarations,sentence', E43)
def test_the_e43_sentences(code, field, examples, declarations, sentence):
    group = {'field': field, 'code': code, 'severity': 'invalid', 'rows': 1200, 'examples': examples}
    assert targets.render('wells', {'rows_checked': 1661}, group, declarations) == sentence


def test_an_unknown_code_reads_as_mapping_invalid():
    assert targets.render('wells', {'rows_checked': 1}, {'field': None, 'code': 'never-heard-of', 'rows': 1, 'examples': []}, {}) == \
        'Part of this mapping cannot be used as it is; review its settings.'


@pytest.mark.parametrize('case', CASES, ids=[c['group']['code'] + ':' + c['target'] for c in CASES])
def test_every_shared_render_case(case):
    assert targets.render(case['target'], case['report'], case['group'], case['declarations']) == case['sentence']


def test_the_render_cases_are_connectors_own():
    beside = Path(os.environ.get('OPHIOLITE_CONNECTORS_ROOT') or ROOT.parent / 'ophiolite-connectors') / 'src/asset_connectors/targets/render-cases.json'
    if not beside.is_file(): pytest.skip('no Connectors checkout beside the SDK')
    assert beside.read_bytes() == (ROOT / 'tests/fixtures/render-cases.json').read_bytes()


def test_the_catalogue_travels_with_the_epsg_notice():
    """Ruling A7 (4): the packaged catalogue keeps its notice file and the IOGP line."""
    notice = PACKAGED.joinpath('vocabulary/v1/coordinate-systems.NOTICE').read_text()
    assert 'EPSG Dataset © IOGP' in notice and 'https://epsg.org/terms-of-use.html' in notice
