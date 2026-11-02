"""E132 s2 C3, gateway lane: `ophiolite withdraw ITEM@N --reason TEXT` as an external client (a separate
`python -m ophiolite.cli` process over HTTP to the in-process gateway, an access key made the way a person makes it), on
a residual result published through E119b's run path. The command prints the server's confirmation only; the
rejection it records shows in `ophiolite verdicts list`; a blank reason exits 1 with the server's sentence and writes
nothing."""
import json
import os
import re
import subprocess
import sys

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import client, key
from ophiolite.testing import fixture_server

REASON = 'wrong well'
LINE = re.compile(r'^Rejected by .+, \d{1,2} [A-Z][a-z]+ \d{4}: ' + REASON + '$')  # the server's verdict line


@pytest.fixture
def run(keyed, tmp_path):
    """run(key, *argv) -> (exit code, stdout, stderr) of one `ophiolite …` process; run.sent: the paths it called."""
    web, sent = keyed, []

    def handler(method, path, raw, headers):
        sent.append(path)
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content

    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))

        def call(made, *argv):
            env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': made['key']}
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', *argv, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=60, env=env,
                                  cwd=tmp_path)  # outside the source tree: the installed package answers
            return done.returncode, done.stdout.strip(), done.stderr.strip()
        call.web, call.sent = web, sent
        yield call


def published(run):
    from project_gateway.tests.test_residual_runs import World
    w = World(run.web)
    alice = key(run.web, 'alice')
    _, made = w.publish(w.payload(), 'run-1')
    assert made.status_code == 200, made.text
    from ophiolite.exchange import ClientTransport
    name = next(i['name'] for i in ClientTransport(client(run.web, alice)).inventory() if i['asset_id'] == made.json()['asset_id'])
    return alice, name, made.json()


def test_withdraw_prints_the_confirmation_and_the_rejection_shows_in_the_verdicts(run):
    alice, name, made = published(run)
    code, out, err = run(alice, 'withdraw', name + '@1', '--reason', REASON)
    assert (code, out, err) == (0, '%s is now Withdrawn: %s' % (name, REASON), ''), (code, out, err)
    assert made['revision'] not in out
    assert [p.rsplit('/', 2)[-2:] for p in run.sent if '/stages/' in p] == [['stages', 'get'], ['stages', 'transition']]
    code, listed, err = run(alice, 'verdicts', 'list', name + '@1')
    assert (code, err) == (0, '') and LINE.match(listed), (code, listed, err)


def test_a_blank_reason_exits_1_with_the_servers_sentence_and_writes_nothing(run):
    alice, name, _ = published(run)
    code, out, err = run(alice, 'withdraw', name + '@1', '--reason', '   ')
    assert code == 1 and 'reason of up to 500 characters is required' in err, (code, out, err)
    code, listed, err = run(alice, 'verdicts', 'list', name + '@1')
    assert (code, listed) == (0, 'No verdicts on this version yet.'), (code, listed, err)
    assert sum(p.endswith('/stages/transition') for p in run.sent) == 1
