"""E132 s0 C3b, gateway lane (slice 1 answers): `ophiolite verdicts record|list` as an external client (a separate
`python -m ophiolite.cli` process over HTTP to the in-process gateway, an access key made the way a person makes it),
on a residual result published through E119b's run path and named by its item and version. Since slice 1 the server
records: `record` prints the server's line and exits 0, `list` prints the same line; an item the person cannot read
keeps `result_version`'s own refusal and sends no verdict request."""
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

REASON = 'tops differ from the published log'
LINE = re.compile(r'^Rejected by .+, \d{1,2} [A-Z][a-z]+ \d{4}: ' + REASON + '$')  # the server's words (D7); the day is the gateway's clock


@pytest.fixture
def run(keyed, tmp_path):
    """run(key, *verb) -> (exit code, stdout, stderr) of one `ophiolite verdicts …` process; run.sent: the paths it called."""
    web, sent = keyed, []

    def handler(method, path, raw, headers):
        sent.append(path)
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content

    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))

        def call(made, *verb):
            env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': made['key']}
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'verdicts', *verb, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=60, env=env,
                                  cwd=tmp_path)  # outside the source tree: the installed package answers
            return done.returncode, done.stdout.strip(), done.stderr.strip()
        call.web, call.sent = web, sent
        yield call


def test_both_commands_print_the_servers_line_on_a_resolved_result_and_an_unreadable_item_sends_nothing(run):
    from project_gateway.tests.test_residual_runs import World
    w = World(run.web)
    alice, bob = key(run.web, 'alice'), key(run.web, 'bob')
    _, published = w.publish(w.payload(), 'run-1')
    assert published.status_code == 200, published.text
    from ophiolite.exchange import ClientTransport
    name = next(i['name'] for i in ClientTransport(client(run.web, alice)).inventory() if i['asset_id'] == published.json()['asset_id'])
    code, recorded, err = run(alice, 'record', name + '@1', 'rejected', '--reason', REASON)
    assert (code, err) == (0, '') and LINE.match(recorded), (code, recorded, err)
    code, listed, err = run(alice, 'list', name + '@1')
    assert (code, listed, err) == (0, recorded, '')
    assert sum(p.endswith('/verdicts/record') for p in run.sent) == 1 and sum(p.endswith('/verdicts/list') for p in run.sent) == 1
    del run.sent[:]
    code, out, err = run(bob, 'record', name, 'accepted')
    assert (code, out) == (1, '') and err.startswith('This project has no item named "%s".' % name), (code, out, err)
    assert not any('/verdicts/' in p for p in run.sent)
