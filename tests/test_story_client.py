"""E94 C5: the story, what changed, dependents and making it again, from Python and the command line.

The story lines are frozen in tests/fixtures/story/story-lines.txt (the Workspace words the same JSON in the Journey's
sentences, app/tests/story.mjs). The route answers here are written by hand in the shapes of the Platform's operation models;
tests/gateway/test_story.py proves the same calls against the real routes."""
import copy
import json
from pathlib import Path

import pytest

from ophiolite import cli, story
from ophiolite.entities import EntityClient
from ophiolite.errors import Refused
from ophiolite.publish import operation_path

FIX = Path(__file__).parent / 'fixtures/story'
PAGE = json.loads((FIX / 'story-page.json').read_text())
LINES = (FIX / 'story-lines.txt').read_text().splitlines()
R = 'a' * 64


class Recorded(EntityClient):
    """The hand-written methods over a fake `_post`: every call is recorded, every answer is the one given."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _post(self, area, op, body, retry=False):
        self.calls.append((area, op, copy.deepcopy(body), retry))
        answer = self.answers[op]
        return answer(body) if callable(answer) else copy.deepcopy(answer)


def run(argv, client, capsys):
    args = cli.parser().parse_args(argv)
    payload = cli._journey(args, client)
    return payload, capsys.readouterr().out


# --- the story as lines ------------------------------------------------------------------------------------------------

def test_the_story_lines_are_the_frozen_ones():
    assert story.lines(PAGE) == LINES


def test_the_servers_through_sentence_reads_once():
    """The server sends E93's sentence ("Through the Python library 0.1.0"); an older answer the bare name."""
    for through in ('Through the Python library 0.1.0', 'the Python library 0.1.0'):
        page = copy.deepcopy(PAGE)
        next(n for n in page['nodes'] if n['id'] == page['root'])['made']['through'] = through
        assert '  Through the Python library 0.1.0.' in story.lines(page)
    assert not any('Through Through' in line for line in story.lines(page))


def test_the_story_keeps_the_order_of_the_inputs_given():
    """Mutation: walking the inputs sorted (or reversed) changes the lines."""
    page = copy.deepcopy(PAGE)
    two = [n for n in page['nodes'] if len(n.get('inputs') or []) > 1]
    assert two, 'the fixture needs a node with two inputs'
    two[0]['inputs'].reverse()
    assert story.lines(page) != story.lines(PAGE) and sorted(story.lines(page)) == sorted(LINES)


def test_a_restricted_story_says_so_and_an_open_one_does_not():
    assert LINES[-1] == 'Some earlier steps are not shown because you cannot open them.'
    page = {**copy.deepcopy(PAGE), 'restricted': False}
    assert story.lines(page) == LINES[:-1]
    dependents = {**copy.deepcopy(PAGE), 'schema': 'ophiolite.dependents/1'}
    assert story.lines(dependents)[-1] == 'Some results made from this are not shown because you cannot open them.'


def test_a_node_reached_twice_is_shown_once():
    page = copy.deepcopy(PAGE)
    root = next(n for n in page['nodes'] if n['id'] == page['root'])
    root['inputs'].append({'id': root['inputs'][0]['id'], 'slot': 'again'})
    out = story.lines(page)
    title = story._title(next(n for n in page['nodes'] if n['id'] == root['inputs'][0]['id']))
    assert sum(1 for line in out if line.strip() == title) == 1 and any(line.strip() == title + ' (shown above)' for line in out)


def test_a_long_story_names_where_to_continue_and_the_next_page():
    page = {**copy.deepcopy(PAGE), 'restricted': False, 'next_cursor': 'c1',
            'continue_from': [{'asset_id': 'a-x', 'revision': R, 'version': 3, 'name': 'Porosity HON-GT-01'}]}
    assert story.lines(page)[-3:] == [story.LONG, '  Porosity HON-GT-01, version 3', 'More on the next page.']


def test_identifiers_stay_out_of_the_lines():
    text = '\n'.join(LINES)
    for node in PAGE['nodes']:
        assert all(v not in text for v in (node.get('revision'), node.get('asset_id')) if v)
        if node.get('technical'): assert all(str(v) not in text for v in node['technical'].values() if v and len(str(v)) > 12)


# --- the client calls --------------------------------------------------------------------------------------------------

def test_every_new_read_is_one_allowed_route():
    for op in ('story', 'what-changed', 'dependents', 'remake-run', 'remake-save'):
        assert operation_path('p', 'results', op).endswith('/results/' + op)
    with pytest.raises(Refused): operation_path('p', 'results', 'remake-everything')


def test_the_reads_send_exact_versions_and_retry():
    c = Recorded({'story': PAGE, 'what-changed': {}, 'dependents': PAGE})
    c.story('a-shale', R, cursor='c1', limit=5)
    c.what_changed(('a-old', 'b' * 64), ('a-shale', R))
    c.dependents('a-shale', R)
    assert c.calls == [('results', 'story', {'asset_id': 'a-shale', 'revision': R, 'cursor': 'c1', 'limit': 5}, True),
                       ('results', 'what-changed', {'a': {'asset_id': 'a-old', 'revision': 'b' * 64}, 'b': {'asset_id': 'a-shale', 'revision': R}}, True),
                       ('results', 'dependents', {'asset_id': 'a-shale', 'revision': R}, True)]


def test_remake_refuses_a_step_it_cannot_take_before_any_call():
    c = Recorded({})
    for kwargs in ({'step': 'save'}, {'step': 'run'}, {'step': 'status'}, {'step': 'discard'}):
        with pytest.raises(Refused): c.remake('a', R, **kwargs)
    for outputs in ([], [{'role': 'v', 'target': 'replace', 'command_id': 'x'}], [{'role': 'v', 'target': 'new-result'}]):
        with pytest.raises(Refused): c.remake_save('e1', outputs)
    assert c.calls == []
    c.answers = {'remake-run': {}}
    c.remake('a', R, step='discard', execution_id='e1')
    assert c.calls[-1][3] is False  # discarding is not retried


# --- the command line --------------------------------------------------------------------------------------------------

def test_the_story_verb_prints_the_lines_and_json_prints_the_page(capsys):
    c = Recorded({'story': PAGE})
    _, out = run(['story', 'a-shale', R], c, capsys)
    assert out.splitlines() == LINES
    payload, out = run(['story', 'a-shale', R, '--json'], c, capsys)
    assert json.loads(out) == PAGE == payload


CHANGED = {'schema': 'ophiolite.what-changed/1', 'sentence': None, 'inputs_same': False,
           'inputs': [{'restricted': False, 'slot': 'gamma', 'a': {'asset_id': 'a-gr', 'revision': 'b' * 64, 'version': 1},
                       'b': {'asset_id': 'a-gr', 'revision': 'c' * 64, 'version': 2},
                       'change': {'sentence': 'Nothing differs in how these were made.', 'inputs_same': True, 'inputs': [], 'settings': [],
                                  'calculation': {'same': True, 'a': 'x', 'b': 'x'}, 'release': {'same': True, 'a': 'y', 'b': 'y'}}},
                      {'restricted': True}],
           'settings': [{'label': 'Clean value', 'unit': 'gAPI', 'a': '30', 'b': '35'}],
           'calculation': {'same': True, 'a': 'Linear (simple), version 1', 'b': 'Linear (simple), version 1'},
           'release': {'same': False, 'a': 'Ophiolite 2026.10.59', 'b': 'Ophiolite 2026.10.60'},
           'a': {'asset_id': 'a-shale', 'revision': 'd' * 64}, 'b': {'asset_id': 'a-shale', 'revision': R}}


def test_what_changed_compares_the_named_versions_in_words(capsys):
    c = Recorded({'what-changed': CHANGED})
    payload, out = run(['what-changed', 'a-shale', R, 'd' * 64], c, capsys)
    assert c.calls[0][2] == {'a': {'asset_id': 'a-shale', 'revision': 'd' * 64}, 'b': {'asset_id': 'a-shale', 'revision': R}}
    assert out.splitlines() == ['Settings: Clean value 35 gAPI, was 30 gAPI.', 'Input gamma: version 2, was version 1.',
                                '  Nothing differs in how these were made.', 'An input you cannot open differs.',
                                'Calculation: the same.', 'Ophiolite release: Ophiolite 2026.10.60, was Ophiolite 2026.10.59.']
    run(['what-changed', 'a-shale', R, 'd' * 64, '--since-asset', 'a-first'], c, capsys)
    assert c.calls[1][2]['a'] == {'asset_id': 'a-first', 'revision': 'd' * 64}
    _, out = run(['what-changed', 'a-shale', R, 'd' * 64, '--json'], c, capsys)
    assert json.loads(out) == CHANGED


def test_dependents_prints_its_tree(capsys):
    page = {**copy.deepcopy(PAGE), 'schema': 'ophiolite.dependents/1'}
    for node in page['nodes']: node['dependents'] = node.pop('inputs', None) or []
    c = Recorded({'dependents': page})
    _, out = run(['dependents', 'a-shale', R], c, capsys)
    assert out.splitlines() == story.lines(page) and out.splitlines()[-1].startswith('Some results made from this')
    assert out.splitlines()[0] == LINES[0]


PREVIEW = {'schema': 'ophiolite.remake-preview/1', 'asset_id': 'a-shale', 'revision': R,
           'inputs': [{'slot': 'gamma', 'label': 'Gamma ray', 'asset_id': 'a-gr', 'revision': 'c' * 64, 'version': 2,
                       'name': 'HON-GT-01 gamma ray', 'recorded_version': 1, 'newer': True}],
           'method': {'display': 'Shale volume', 'version_label': 'version 1', 'release': 'Ophiolite 2026.10.60'},
           'made_with': 'Ophiolite 2026.10.60', 'settings': [], 'changes': None}


def status(outcome):
    return {'schema': 'ophiolite.remake/1', 'execution_id': 'e1', 'state': 'completed', 'asset_id': 'a-shale', 'revision': R,
            'outcomes': [{'role': 'vshale', 'label': 'Shale volume', 'outcome': outcome}], 'release': 'Ophiolite 2026.10.60',
            'made': {'at': None, 'by': 'sanne', 'agent': None}, 'expires_at': '2026-10-10T12:00:00Z', 'failure': None,
            'held': [{'role': 'vshale', 'label': 'Shale volume', 'output': {},
                      'summary': {'reason': '12 of 400 samples changed; the largest change is 0.04 v/v.', 'changed': 12, 'of': 400, 'largest': 0.04, 'unit': 'v/v'},
                      'audience': {'everyone': False, 'recipients': ['bram'], 'notified': ['bram'], 'digest': 'f' * 64}}] if outcome == 'different' else None}


def remaking(outcome='different'):
    def run_step(body):
        return {'preview': PREVIEW, 'run': {**status(outcome), 'state': 'running', 'held': None}, 'status': status(outcome)}[body['step']]
    def save(body):
        return {'schema': 'ophiolite.remake-saves/1', 'execution_id': body['execution_id'],
                'saves': [{'role': o['role'], 'target': o['target'], 'command_id': o['command_id'], 'asset_id': 'a-new', 'revision': 'e' * 64,
                           'revision_number': 3 if o['target'] == 'new-version' else 1, 'notified': ['bram'] if o['target'] == 'new-version' else []}
                          for o in body['outputs']]}
    return Recorded({'remake-run': run_step, 'remake-save': save})


def test_remake_without_save_saves_nothing_and_says_how_to(capsys):
    c = remaking()
    payload, out = run(['remake', 'a-shale', R, '--newer', '--command-id', 'k1'], c, capsys)
    ops = [(op, body.get('step')) for _, op, body, _ in c.calls]
    assert ops == [('remake-run', 'preview'), ('remake-run', 'run'), ('remake-run', 'status')]
    assert c.calls[0][2]['inputs'] == 'newer'
    assert c.calls[1][2]['inputs'] == [{'slot': 'gamma', 'asset_id': 'a-gr', 'revision': 'c' * 64}] and c.calls[1][2]['command_id'] == 'k1'
    assert out.splitlines() == ['Shale volume: different', '  Shale volume: 12 of 400 samples changed; the largest change is 0.04 v/v.',
                                'Nothing was saved. It is kept for you until 2026-10-10T12:00:00Z; to save it run again with --save --target new-result (or new-version) and --command-id k1.']
    assert payload['saves'] == []


def test_remake_with_nothing_different_saves_nothing_even_with_save(capsys):
    c = remaking('equal')
    _, out = run(['remake', 'a-shale', R, '--command-id', 'k1', '--save', '--target', 'new-result'], c, capsys)
    assert 'remake-save' not in [op for _, op, _, _ in c.calls] and out.splitlines()[-1] == 'Nothing differs, so nothing was saved.'


@pytest.mark.parametrize('argv', [['--save'], ['--save', '--command-id', 'k1'], ['--save', '--target', 'new-result'], ['--target', 'new-result'],
                                  ['--command-id', 'k' * 49]])
def test_remake_save_needs_its_command_id_and_target_before_any_call(argv, capsys):
    c = remaking()
    with pytest.raises(Refused): run(['remake', 'a-shale', R, *argv], c, capsys)
    assert c.calls == []


def test_remake_save_as_a_new_version_sends_the_audience_it_showed(capsys):
    c = remaking()
    payload, out = run(['remake', 'a-shale', R, '--command-id', 'k1', '--save', '--target', 'new-version'], c, capsys)
    assert c.calls[-1][1:3] == ('remake-save', {'execution_id': 'e1', 'outputs': [
        {'role': 'vshale', 'target': 'new-version', 'command_id': 'k1-0', 'audience_digest': 'f' * 64}]})
    assert out.splitlines()[-1] == 'Saved vshale as a new version (version 3); told: bram.'
    c = remaking()
    run(['remake', 'a-shale', R, '--command-id', 'k1', '--save', '--target', 'new-result'], c, capsys)
    assert c.calls[-1][2]['outputs'] == [{'role': 'vshale', 'target': 'new-result', 'command_id': 'k1-0'}]


# --- the same exchanges TypeScript asserts (packages/typescript/tests/story.test.ts) ---------------------------------

def test_python_sends_the_shared_exchanges_and_returns_their_answers():
    exchanges = json.loads((FIX / 'exchanges.json').read_text())['exchanges']
    answers = iter(e['response'] for e in exchanges)
    c = Recorded({op: (lambda body: next(answers)) for op in ('story', 'what-changed', 'dependents', 'remake-run', 'remake-save')})
    got = [c.story('a-shale', R, limit=5), c.what_changed(('a-shale', 'd' * 64), ('a-shale', R)), c.dependents('a-shale', R),
           c.remake('a-shale', R, inputs='newer'),
           c.remake('a-shale', R, step='run', inputs=[{'slot': 'gamma', 'asset_id': 'a-gr', 'revision': 'c' * 64}], command_id='k1'),
           c.remake('a-shale', R, step='status', execution_id='e1'),
           c.remake_save('e1', [{'role': 'vshale', 'target': 'new-version', 'command_id': 'k1-0', 'audience_digest': 'f' * 64}])]
    for (area, op, body, _), e, answer in zip(c.calls, exchanges, got):
        assert operation_path('p', area, op) == e['path'] and {'project_id': 'p', **body} == e['request'] and answer == e['response']
    assert len(c.calls) == len(exchanges)
