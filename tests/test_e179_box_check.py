"""E179 s1 C3a: the box runs a check that answers an outcome. A request in the check form (`step: "check"` and the
`result` slot, procedure-box 1.1.0) calls the entry with its inputs and settings, and only what `answered(...)` holds
lands in the output folder, as `answer.json` (`ophiolite.check-answer/1`). A process request is unchanged.

Mutations (break -> FAIL, restore -> PASS; recorded in the lane's logs/c3a-mutations.txt):
a. `_child_answer` also writes outputs.json -> the one-file case;
b. the box takes `step` without `result` -> the together case;
c. `child_request` adds `answer` to every request -> the process child request case;
d. `answered` accepts a passed answer with a failing row -> the consistency case."""
import json
import subprocess
import sys

import pytest

from ophiolite import box as the_box, procedures
from test_procedure_box import request as process_request
from test_procedures_run import depth_shift

BOX = 'import sys; from ophiolite.box import main; sys.exit(main(*sys.argv[1:]))'
MANIFEST = {
    'schema': 'ophiolite.procedure/1', 'name': 'residual-limit', 'label': "Residuals within the team's limit", 'version': 1, 'step': 'check',
    'inputs': [{'slot': 'residuals', 'label': 'Residual result', 'class': 'result', 'kinds': ['well-residual/1'], 'cardinality': 'one'},
               {'slot': 'tops', 'label': 'Tops of the wells', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'many'}],
    'outputs': [{'role': 'answer', 'label': 'Answer', 'class': 'answer'}],
    'settings': [{'key': 'limit', 'label': 'Largest residual allowed', 'type': 'number', 'unit': 'm', 'default': 5, 'minimum': 0}],
    'entry': 'procedure:check'}
CODE = '''import json

from ophiolite import procedure
from ophiolite.procedures import answered


@procedure
def check(inputs, settings):
    rows = json.loads(open(inputs['residuals'][0].path).read())['rows']
    said = MODE
    return said(rows, settings['limit'])
'''
MODES = {
    'answer': "lambda rows, limit: answered('failed' if any(abs(r) > limit for _, r in rows) else 'passed', "
              "[{'key': k, 'measure': 'residual', 'value': r, 'unit': 'm', 'limit': limit, 'pass': abs(r) <= limit} for k, r in rows])",
    'raises': "lambda rows, limit: 1 / 0",
    'wrong': "lambda rows, limit: {'state': 'passed'}",
}
RESIDUALS = {'rows': [['W-1 Top A', 1.5], ['W-2 Top Brent', 6.1], ['W-3 Top C', -2.0]]}  # three rows, one beyond 5 m: counted by hand


def bundle(tmp_path, mode):
    folder = tmp_path / 'bundle'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps(MANIFEST))
    (folder / 'procedure.py').write_text(CODE.replace('MODE', MODES[mode]))
    return folder


def check_request(**changes):
    return {'entry': 'procedure:check', 'settings': {'limit': 5}, 'step': 'check', 'result': 'residuals',
            'inputs': {'residuals': [{'path': '/box/inputs/residuals-0.json', 'kind': 'well-residual/1', 'declared': {}, 'asset_id': 'r-1', 'revision': 'v-1'}],
                       'tops': [{'path': '/box/inputs/tops-0.csv', 'kind': 'well-tops-csv/1', 'declared': {}, 'asset_id': 't-1', 'revision': 'v-1'}]},
            **changes}


def run_box(tmp_path, folder, request):
    root, output = tmp_path / 'box', tmp_path / 'output'
    for member in folder.iterdir():
        target = root / 'bundle' / member.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(member.read_bytes())
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs' / 'residuals-0.json').write_text(json.dumps(RESIDUALS))
    (root / 'inputs' / 'tops-0.csv').write_text('name,md\nTop A,100\n')
    (root / 'request.json').write_text(json.dumps(request))
    output.mkdir()
    done = subprocess.run([sys.executable, '-B', '-c', BOX, str(root / 'request.json'), str(output), str(root)], capture_output=True, text=True)
    return done, output


def test_a_check_request_leaves_exactly_the_answer_the_entry_returned(tmp_path):
    done, output = run_box(tmp_path, bundle(tmp_path, 'answer'), check_request())
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in output.iterdir()) == ['answer.json']
    assert json.loads((output / 'answer.json').read_text()) == {
        'schema': 'ophiolite.check-answer/1', 'state': 'failed',
        'rows': [{'key': 'W-1 Top A', 'measure': 'residual', 'value': 1.5, 'unit': 'm', 'limit': 5, 'pass': True},
                 {'key': 'W-2 Top Brent', 'measure': 'residual', 'value': 6.1, 'unit': 'm', 'limit': 5, 'pass': False},
                 {'key': 'W-3 Top C', 'measure': 'residual', 'value': -2.0, 'unit': 'm', 'limit': 5, 'pass': True}]}


@pytest.mark.parametrize('mode', ['raises', 'wrong'])
def test_an_entry_that_raises_or_returns_something_else_writes_nothing_and_exits_3(tmp_path, mode):
    done, output = run_box(tmp_path, bundle(tmp_path, mode), check_request())
    assert done.returncode == 3
    assert list(output.iterdir()) == []
    assert done.stderr.startswith({'raises': 'The check stopped: ZeroDivisionError', 'wrong': 'The check did not return answered(...): it returned dict'}[mode])


@pytest.mark.parametrize('changes', [{'step': None}, {'result': None}, {'step': 'process'}, {'result': 'surface'}])
def test_step_and_result_come_together_and_name_a_check_of_an_input_slot(tmp_path, changes):
    asked = {k: v for k, v in check_request(**changes).items() if v is not None}
    with pytest.raises(the_box.Refused) as refused: the_box.child_request(asked, tmp_path / 'output', tmp_path / 'box')
    assert str(refused.value) in ('A check request names step check and the input slot of its result, together.',)


def test_a_process_request_makes_the_child_request_it_made_before(tmp_path):
    """The literal child request of E113's box for the shift tool's request: no `answer` key, nothing else changed."""
    folder = depth_shift(tmp_path / 'bundle')
    child = the_box.child_request(process_request(folder), '/output', '/box')
    assert set(child) == {'snapshot', 'exchange', 'entry', 'settings', 'inputs'}
    assert (child['snapshot'], child['exchange']) == ('/box/bundle', '/output')
    assert child['inputs'] == {'tops': [{'local': 'version', 'path': '/box/inputs/tops-0.csv', 'kind': 'well-tops-csv/1',
                                         'declared': {'depth_unit': 'm', 'depth_basis': 'md'}, 'asset_id': 'a-1', 'revision': 'r-1', 'wellbore': None}]}


ROW = {'key': 'W-1', 'measure': 'residual', 'value': 1.0, 'unit': 'm', 'limit': 5, 'pass': True}


@pytest.mark.parametrize('state, rows, reason', [
    ('passed', [ROW, {**ROW, 'pass': False}], None), ('passed', [], None), ('failed', [ROW], None), ('not_compared', [], None),
    ('passed', [ROW], 'why'), ('maybe', [ROW], None), ('passed', [{**ROW, 'value': float('nan')}], None),
    ('passed', [{**ROW, 'value': True}], None), ('passed', [{**ROW, 'key': ''}], None), ('passed', [{**ROW, 'unit': 'u' * 17}], None),
    ('passed', [{**ROW, 'extra': 1}], None), ('passed', [ROW] * 1001, None), ('not_compared', [], 'line\nbreak')])
def test_answered_refuses_what_the_platform_would_read_as_malformed(state, rows, reason):
    with pytest.raises(ValueError): procedures.answered(state, rows, reason)


def test_answered_takes_the_edges_the_platform_reads():
    assert procedures.answered('passed', [ROW] * 1000).document['rows'] == [ROW] * 1000
    assert procedures.answered('not_compared', [], 'r' * 200).document == {'schema': 'ophiolite.check-answer/1', 'state': 'not_compared', 'rows': [], 'reason': 'r' * 200}
    assert procedures.answered('failed', [{**ROW, 'value': None, 'unit': None, 'limit': None, 'pass': False}]).document['state'] == 'failed'
