"""E120 s0 t12, gateway lane: the SDK's `ophiolite outcomes` as an external client: a separate process (`python -m
ophiolite.cli`, the installed package) over HTTP to the in-process gateway, with access keys made the way a person
makes them. alice administers project p; bob is a member. The default lines are words; the ids are under --json. A
refusal prints the server's sentence and the remedy; a permission refusal exits 3 (access), any other 1."""
import json
import os
import subprocess
import sys

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import client, key
from ophiolite.testing import fixture_server


@pytest.fixture
def run(keyed, tmp_path):
    """run(key, *verb) -> (exit code, stdout, stderr) of one `ophiolite outcomes …` process."""
    web = keyed

    def handler(method, path, raw, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content

    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))

        def call(made, *verb):
            env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': made['key']}
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'outcomes', *verb, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=60, env=env,
                                  cwd=tmp_path)  # outside the source tree: the installed package answers
            return done.returncode, done.stdout.strip(), done.stderr.strip()
        call.web = web
        yield call


FIVE = ['--label', 'Tops within 5 m', '--tolerance', '5', '--procedure', 'tops-to-team-database', '--destination', 'Team database']
REMEDY = ' Read the reason the answer names (reason) and its sentence; nothing was stored. Change what it names and send again with a new command id.'
SAID = 'residual results, every computed residual within %s; rows not computed are %s; delivered to Team database.'


def test_an_administrator_declares_revises_and_withdraws_an_outcome_from_the_command_line(run):
    alice, bob = key(run.web, 'alice'), key(run.web, 'bob')
    assert run(alice, 'list') == (0, 'This project has no outcomes yet.', '')
    assert run(alice, 'declare', *FIVE) == (0, 'Declared "Tops within 5 m" (enabled, version 1): ' + SAID % ('5 m', 'allowed'), '')
    code, out, err = run(bob, 'declare', *FIVE[:1], 'Tops within 2 m', *FIVE[2:])
    assert (code, out, err) == (3, '', 'Only a project administrator can declare or change outcomes.' + REMEDY), (code, out, err)
    assert run(alice, 'revise', 'Tops within 5 m', '--label', 'Tops within 1 m', '--tolerance', '1', '--not-computed', 'refused') == (
        0, 'Revised "Tops within 1 m" (enabled, version 2): ' + SAID % ('1 m', 'refused'), '')
    assert run(bob, 'list') == (0, '"Tops within 1 m" (enabled, version 2): ' + SAID % ('1 m', 'refused'), '')
    assert run(alice, 'disable', 'Tops within 1 m') == (0, '"Tops within 1 m" is disabled; it is kept and can be enabled again.', '')
    assert run(alice, 'enable', 'Tops within 1 m') == (0, '"Tops within 1 m" is enabled.', '')
    code, out, err = run(bob, 'get', 'Tops within 1 m')
    assert code == 0 and out.splitlines() == ['"Tops within 1 m" (enabled, version 2): ' + SAID % ('1 m', 'refused'),
                                              'Version 1, declared by alice.', 'Version 2, declared by alice.',
                                              '1. Declared by alice (version 1).', '2. Enabled by alice (version 1).', '3. Revised by alice (version 2).',
                                              '4. Disabled by alice (version 2).', '5. Enabled by alice (version 2).'], out
    code, out, err = run(alice, 'get', 'Tops within 1 m', '--json')
    assert code == 0 and json.loads(out)['declaration']['rule']['settings'] == {'tolerance': {'value': 1.0, 'unit': 'm'}, 'not_computed': 'refused'}
    assert run(alice, 'withdraw', 'Tops within 1 m') == (0, '"Tops within 1 m" is withdrawn; its name is free again.', '')
    assert run(alice, 'list') == (0, '"Tops within 1 m" (withdrawn, version 2): ' + SAID % ('1 m', 'refused'), '')
    code, out, err = run(alice, 'declare', *FIVE[:1], 'tops_within_5m', *FIVE[2:])
    assert (code, out, err) == (1, '', 'The name of an outcome must read as words, for example "Tops within 5 m".' + REMEDY), (code, out, err)


def test_a_result_reads_its_outcome_states_by_its_item_and_version_from_the_command_line(run):
    """E120 s1 (C5 t3, the external-client line): alice declares, publishes a residual result through E119b's run path
    and reads its state by `ITEM@N`; bob, who cannot read the result, is refused with the reason's sentence."""
    from project_gateway.procedures import day
    from project_gateway.tests.test_residual_runs import World
    import time
    w = World(run.web)
    alice, bob = key(run.web, 'alice'), key(run.web, 'bob')
    assert run(alice, 'declare', *FIVE)[0] == 0
    _, published = w.publish(w.payload(), 'run-1')
    assert published.status_code == 200, published.text
    from ophiolite.exchange import ClientTransport
    name = next(i['name'] for i in ClientTransport(client(run.web, alice)).inventory() if i['asset_id'] == published.json()['asset_id'])
    assert run(alice, 'states', name + '@1') == (0, 'Tops within 5 m: Accepted on %s under Tops within 5 m version 1' % day(time.time()), '')
    code, out, err = run(alice, 'states', name + '@2')
    assert (code, out, err) == (1, '', '"%s" has no version 2.' % name), (code, out, err)
    code, out, err = run(bob, 'states', name)
    assert (code, out) == (1, '') and err.startswith('This project has no item named "%s".' % name), (code, out, err)
