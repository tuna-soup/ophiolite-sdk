"""E178 s2c (§6 i), gateway lane: `ophiolite results chains` and `ophiolite results chain-runs` as an external client: a
separate process (`python -m ophiolite.cli`, the installed package) over HTTP to the in-process gateway, with access
keys made the way a person makes them. The world is the chain-run tests' (alice administers p; bob is a member; the
chain "After new tops": Well residuals, Design review, Regrid decision, Tight residuals; the trigger a new version of
the tops "t1"). Every verb runs; `--json` prints the served answer as it is; the default lines are labels and state
words and name no step key, state or reason code, digest or id. A refusal is the server's: nothing is judged here.

Mutations: `--json` printing words or a rebuilt answer; a step key, a state code or an id in the words; a client-side
refusal of bob's declaration (the server's sentence replaced or the exit code changed)."""
import copy
import json
import os
import re
import subprocess
import sys

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import key
from ophiolite.testing import fixture_server

KEYS = ('design', 'go-on', 'residuals-tight')
CODES = ('waiting-for-earlier', 'not-checked', 'did-not-apply', 'not_compared', 'step-waits', 'step-closed', 'not-this-kind',
         'other-tool-version', 'not-from-checked-version', 'person-only', 'not-found', 'label-taken', 'waiting.', 'stopped.')
REMEDY = ' Read the reason the answer names (reason) and its sentence; nothing was stored. Change what it names and send again with a new command id.'
STEPS = '4 steps: Well residuals, Design review, Regrid decision, Tight residuals.'


@pytest.fixture
def cli(keyed, tmp_path):
    """cli(made key, verb, *words) -> (exit code, stdout, stderr) of one `ophiolite results <verb> …` process."""
    web = keyed

    def handler(method, path, raw, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content

    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))

        def call(made, *words):
            env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': made['key']}
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'results', *words, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=120, env=env,
                                  cwd=tmp_path)  # outside the source tree: the installed package answers
            return done.returncode, done.stdout.strip(), done.stderr.strip()
        call.web, call.dir = web, tmp_path
        yield call


@pytest.fixture
def w(cli):
    from project_gateway.tests.chain_run_world import Runs
    world = Runs(cli.web)
    world.keys = key(cli.web, 'alice'), key(cli.web, 'bob')
    return world


def words(result, *ids):
    """The default lines of a successful call: no step key, state or reason code, 32-hex digest or run id, none of `ids`."""
    code, out, err = result
    assert (code, err) == (0, ''), result
    assert not re.search(r'[0-9a-f]{32}', out), out
    for word in KEYS + CODES + tuple(ids):
        assert word not in out, (word, out)
    return out.splitlines()


def answer(result):
    code, out, err = result
    assert (code, err) == (0, ''), result
    return json.loads(out)


def exact(v):
    return '@%s:%s' % (v['asset_id'], v['revision'])


def declared(w, name, **kw):
    path = w.cli_dir / name
    path.write_text(json.dumps(w.chain(selection=None, **kw)))
    return str(path)


def test_chains_declare_list_get_due_dismiss_revise_and_withdraw_in_words_and_as_served(cli, w):
    from project_gateway.tests.test_chains_declare import SENTENCES
    alice, bob = w.keys
    w.cli_dir = cli.dir
    ids = (w.o10, w.o6, w.s['asset_id'])
    assert cli(alice, 'chains', 'list') == (0, 'This project has no chains yet.', '')
    assert cli(bob, 'chains', 'declare', declared(w, 'chain.json')) == (3, '', SENTENCES['permission'] + REMEDY)  # the server's, as served
    assert words(cli(alice, 'chains', 'declare', declared(w, 'chain.json')), *ids) == [
        'Declared "After new tops" (enabled, version 1), starts after a new version; ' + STEPS]
    chain = w.alice.ok('chains', 'list', {})['chains'][0]
    ids += (chain['id'],)
    assert answer(cli(alice, 'chains', 'list', '--json')) == w.alice.ok('chains', 'list', {})
    assert words(cli(alice, 'chains', 'disable', 'after new tops'), *ids) == ['"After new tops" is disabled; it is kept and its runs go on.']
    assert answer(cli(alice, 'chains', 'enable', 'After new tops', '--json')) == {**w.alice.ok('chains', 'get', {'chain_id': chain['id']})['current'], 'due_stops': 0}
    assert words(cli(bob, 'chains', 'get', 'After new tops'), *ids) == [
        '"After new tops" (enabled, version 1), starts after a new version; ' + STEPS, 'Version 1, declared by alice.',
        '1. Declared by alice (version 1).', '2. Enabled by alice (version 1).', '3. Disabled by alice (version 1).', '4. Enabled by alice (version 1).']
    assert answer(cli(bob, 'chains', 'get', 'After new tops', '--json')) == w.alice.ok('chains', 'get', {'chain_id': chain['id']})
    first = w.trigger()
    assert words(cli(alice, 'chains', 'due'), *ids) == ['"After new tops" version 1 is due for version 2 of "t1".']
    due = answer(cli(alice, 'chains', 'due', 'After new tops', '--json'))
    assert due == {**w.alice.ok('chains', 'due', {'chain_id': chain['id']}), 'as_of': due['as_of']}
    assert words(cli(alice, 'chains', 'dismiss', 'After new tops', exact(first), '--reason', 'Superseded by the next pick'), *ids) == [
        'Set aside version 2 of "t1" for "After new tops"; no run starts for it.']
    assert cli(alice, 'chains', 'due') == (0, 'Nothing is due.', '')
    assert words(cli(alice, 'chains', 'declare', declared(w, 'second.json', label='Second look')), *ids) == [
        'Declared "Second look" (enabled, version 1), starts after a new version; ' + STEPS]
    assert words(cli(alice, 'chains', 'revise', 'Second look', declared(w, 'revised.json', label='Second look', value=6.0)), *ids) == [
        'Revised "Second look" (disabled, version 2), starts after a new version; ' + STEPS]
    assert words(cli(alice, 'chains', 'withdraw', 'Second look'), *ids) == ['"Second look" is withdrawn; its name is free again and its runs are kept.']
    assert cli(alice, 'chains', 'get', 'Second look') == (1, '', 'This project has no chain named "Second look".')


def test_chain_runs_start_list_get_attach_acknowledge_choose_and_continue_in_words_and_as_served(cli, w):
    alice, bob = w.keys
    w.cli_dir = cli.dir
    assert cli(alice, 'chains', 'declare', declared(w, 'chain.json'))[0] == 0
    chain = w.alice.ok('chains', 'list', {})['chains'][0]
    old = w.result()  # made from the version of t1 before the trigger: refused, not-from-checked-version
    trigger = w.trigger()
    started = '"After new tops" version 1 over version 2 of "t1": %s. Started by alice.'
    assert words(cli(alice, 'chain-runs', 'start', 'After new tops', exact(trigger))) == [
        started % 'open', 'Well residuals: Open', 'Design review: Waits for an earlier step', 'Regrid decision: Waits for an earlier step',
        'Tight residuals: Waits for an earlier step']
    run = w.alice.ok('chain-runs', 'list', {})['runs'][0]
    ids = (w.o10, w.o6, chain['id'], run['id'])
    assert answer(cli(alice, 'chain-runs', 'get', 'After new tops', '--json')) == w.alice.ok('chain-runs', 'get', {'run_id': run['id']})
    assert words(cli(bob, 'chain-runs', 'list'), *ids) == [started % 'open']
    assert answer(cli(bob, 'chain-runs', 'list', 'After new tops', '--json')) == w.bob.ok('chain-runs', 'list', {'chain_id': chain['id']})
    lines = words(cli(alice, 'chain-runs', 'attach', 'After new tops', 'Well residuals', exact(old)), *ids)
    assert lines[:3] == [started % 'open', 'Well residuals: Open', '  A result from alice was refused: This result was not made from the version this run checks.']
    lines = words(cli(alice, 'chain-runs', 'attach', run['id'], 'well residuals', exact(w.result(5.01, 2.0, 2.0))), *ids)
    assert lines[0] == started % 'waiting for a person' and lines[3:6] == ['  A result was attached by alice; its check: accepted.', 'Design review: Open',
                                                                          'Regrid decision: Waits for an earlier step']
    acknowledged = answer(cli(alice, 'chain-runs', 'acknowledge', 'After new tops', 'Design review', '--label', 'Design review held',
                              '--reference', 'Minutes 14 Nov', '--json'))
    assert acknowledged == w.alice.ok('chain-runs', 'get', {'run_id': run['id']})
    assert cli(alice, 'chain-runs', 'choose', 'After new tops', 'Regrid decision', 'Later') == (
        1, '', '"Later" is not an answer to this question; its answers are "Regrid now", "Hold".')  # a name not found, as `outcomes` says it
    assert words(cli(alice, 'chain-runs', 'choose', 'After new tops', 'Regrid decision', 'hold'), *ids)[4:8] == [
        'Design review: Said to be done outside', '  alice said "Design review held" was done outside, kept at Minutes 14 Nov.',
        'Regrid decision: Answered', '  alice answered "Hold".']
    assert words(cli(alice, 'chain-runs', 'attach', 'After new tops', 'Tight residuals', exact(w.result(8.0, 2.0, 2.0))), *ids)[0] == \
        started % 'stopped at a rejected step'
    assert words(cli(alice, 'chain-runs', 'continue', 'After new tops', 'Tight residuals', '--reason', 'Known bad well'), *ids) == [
        started % 'done', 'Well residuals: Accepted', '  A result from alice was refused: This result was not made from the version this run checks.',
        '  A result was attached by alice; its check: accepted.', 'Design review: Said to be done outside',
        '  alice said "Design review held" was done outside, kept at Minutes 14 Nov.', 'Regrid decision: Answered', '  alice answered "Hold".',
        'Tight residuals: Continued by a person despite the check', '  A result was attached by alice; its check: rejected.',
        '  alice continued despite the check: Known bad well']
    assert answer(cli(alice, 'chain-runs', 'get', run['id'], '--json')) == w.alice.ok('chain-runs', 'get', {'run_id': run['id']})
    code, out, err = cli(bob, 'chain-runs', 'get', run['id'], '--json')  # Q6: bob cannot read alice's results, so the run is not his to read
    assert (code, json.loads(out)['error']['code'], err) == (4, 'chain-refused', '') and 'There is no such chain or run in this project.' in out
    assert cli(bob, 'chain-runs', 'list') == (0, 'No run you can read.', '')


def test_chain_runs_decide_on_a_step_that_cannot_be_decided(cli, w, monkeypatch):
    """A record without measures (as test_chain_runs_steps `unchecked`): the design step cannot be decided; alice
    decides it does not apply and the words say the vocabulary's state and her reason."""
    from project_gateway import chains_service
    alice, _ = w.keys
    w.cli_dir = cli.dir
    assert cli(alice, 'chains', 'declare', declared(w, 'chain.json'))[0] == 0
    trigger = w.trigger()
    assert cli(alice, 'chain-runs', 'start', 'After new tops', exact(trigger))[0] == 0
    w.alice.ok('outcomes', 'disable', {'command_id': w.command(), 'outcome_id': w.o10})
    monkeypatch.setattr(chains_service.Chains, 'prepare', lambda self, *a: None)
    lines = words(cli(alice, 'chain-runs', 'attach', 'After new tops', 'Well residuals', exact(w.result())))
    assert lines[1:3] == ['Well residuals: Not checked yet', '  A result was attached by alice.']
    lines = words(cli(alice, 'chain-runs', 'continue', 'After new tops', 'Well residuals', '--reason', 'Checked by hand'))
    assert lines[4] == 'Design review: Cannot be decided: the check did not record the largest residual, either sign; a person decides'
    lines = words(cli(alice, 'chain-runs', 'decide', 'After new tops', 'Design review', '--does-not-apply', '--reason', 'No residual block'))
    assert lines[4:7] == ['Design review: Skipped by a person', '  alice skipped it: No residual block', 'Regrid decision: Open']
    run = w.alice.ok('chain-runs', 'list', {})['runs'][0]
    assert answer(cli(alice, 'chain-runs', 'get', 'After new tops', '--json')) == w.alice.ok('chain-runs', 'get', {'run_id': run['id']})
