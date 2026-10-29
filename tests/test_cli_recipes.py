"""E112 s2 (C2): `ophiolite recipes run` and `recipes show`. The run goes through `cli._recipes` with the fake project of
test_recipe_runs (no server); `show` goes through the whole command line with a client that raises if it is made."""
import json

import pytest

from ophiolite import cli
from test_recipe_runs import IDENTITY, SET, GRID, world  # noqa: F401 (fixture)


def args(w, *more, json_=False, set_aside=None, yes=False):
    given = ['--input', 'selection=' + SET, '--input', 'surface=' + GRID, '--input', 'team_db=' + str(w.db), *more]
    parsed = cli.parser().parse_args(['recipes', 'run', str(w.recipe), '--work', str(w.work), *given] + (['--json'] if json_ else []) +
                                     (['--set-aside', set_aside] if set_aside else []) + (['--yes'] if yes else []))
    return parsed


def exit_of(call):
    with pytest.raises(SystemExit) as stopped:
        call()
    return stopped.value.code


def test_a_finished_recipe_exits_0_with_its_sentence(world, capsys):
    said = cli._recipes(args(world), world)
    assert said['state'] == 'finished' and capsys.readouterr().out == 'Finished: all 4 steps of "Residual report again".\n'


def test_a_failed_step_exits_1_and_an_unknown_delivery_exits_4(world, capsys):
    # mutation: `unknown` mapped to EXIT['refused'] -> 1 instead of 4 -> red
    world.residual_plan = ['untrusted']
    assert exit_of(lambda: cli._recipes(args(world), world)) == 1
    assert capsys.readouterr().out.startswith('Stopped at step 1 of 4 (run): Not run: you have not trusted version 2')
    world.plan['deliver'] = ['unknown']
    assert exit_of(lambda: cli._recipes(args(world, yes=True), world)) == 4
    assert capsys.readouterr().out.rstrip().endswith('or set it aside with --set-aside send.')
    cli._recipes(args(world, set_aside='send'), world)  # set aside: exit 0


def test_a_refusal_before_any_step_exits_1_with_the_sentence_on_stderr_and_json_on_stdout(world, capsys):
    cli._recipes(args(world), world)
    world.identity = {'kind': 'grant', 'user_id': 'u2'}
    assert exit_of(lambda: cli._recipes(args(world), world)) == 1
    assert capsys.readouterr().err.startswith('Not run: ')
    assert exit_of(lambda: cli._recipes(args(world, json_=True), world)) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'recipe-principal'


def test_an_input_not_given_as_name_value_is_refused(world):
    with pytest.raises(ValueError, match='--input NAME=VALUE'):
        cli._recipes(args(world, '--input', 'selection'), world)


def test_json_prints_the_summary_with_the_journal_steps(world, capsys):
    cli._recipes(args(world, json_=True), world)
    printed = json.loads(capsys.readouterr().out)
    assert printed['state'] == 'finished' and [s['id'] for s in printed['steps']] == ['run', 'publish', 'states', 'send']


def test_a_missing_work_folder_is_a_usage_error(world):
    assert exit_of(lambda: cli.entrypoint(['recipes', 'run', str(world.recipe)])) == 2


def test_show_reads_the_journal_without_a_server_in_words_and_json(world, monkeypatch, capsys):
    # mutation: `recipes show` dispatched after the configuration and client -> a missing configuration refuses -> red
    world.plan['deliver'] = ['unknown']
    with pytest.raises(SystemExit):
        cli._recipes(args(world), world)
    capsys.readouterr()

    def no_client(*a, **k): raise AssertionError('show made a client')
    monkeypatch.setattr(cli, 'Client', no_client, raising=False)
    monkeypatch.chdir(world.tmp)  # no configuration.json here
    cli.main(['recipes', 'show', str(world.work)])
    lines = capsys.readouterr().out.splitlines()
    assert lines[:4] == ['Residual report again: 4 steps', '1. run (residuals): Finished', '2. publish (publish): Finished', '3. states (states): Finished']
    assert lines[4].startswith('4. send (deliver): Needs attention: Outcome unknown for Team database')
    for technical in ('steps/', 'a-res', 'sha256', 'set_aside', 'started', world.delivered[0]):  # 6-V1
        assert technical not in '\n'.join(lines)
    cli.main(['recipes', 'show', str(world.work), '--json'])
    journal = json.loads(capsys.readouterr().out)
    assert journal['schema'] == 'ophiolite.recipe-journal/1' and journal['principal']['identity'] == IDENTITY
