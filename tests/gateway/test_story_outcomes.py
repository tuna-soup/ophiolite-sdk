"""E120 s7, gateway lane: `ophiolite story` as an external client (a separate `python -m ophiolite.cli` process over HTTP
to the in-process gateway, an access key made the way a person makes it) prints the root version's outcome lines in the
Workspace result page's words, after the root's own lines: accepted, rejected, not checked and delivered, one test each,
on E120's residual World and its send procedure (`test_outcome_gate.Gate`). The story is one read of `results/story`
and one of `outcomes/states`; nothing is written. Mutations: drop the states read; print the server's rejected head;
drop the claims; put the lines after the inputs."""
import json
import os
import subprocess
import sys

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import key
from ophiolite.testing import fixture_server


@pytest.fixture
def run(keyed, tmp_path):
    """run(key, *argv) -> (exit code, stdout lines, stderr) of one `ophiolite story …` process; run.sent: the paths it called."""
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
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'story', *argv, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=60, env=env,
                                  cwd=tmp_path)  # outside the source tree: the installed package answers
            return done.returncode, done.stdout.rstrip('\n').splitlines(), done.stderr.strip()
        call.web, call.sent = web, sent
        yield call


@pytest.fixture
def g(run, monkeypatch):
    from project_gateway import outcomes
    from project_gateway.tests.test_outcome_gate import PINNED, Gate
    monkeypatch.setattr(outcomes, 'delivery_uuid', lambda: PINNED)
    return Gate(run.web)


def told(run, receipt):
    """The story's lines for alice, after checking it read the story and the states once each and nothing else."""
    del run.sent[:]
    code, out, err = run(key(run.web, 'alice'), receipt['asset_id'], receipt['revision'])
    assert (code, err) == (0, ''), (code, out, err)
    assert [p.rsplit('/', 2)[-2:] for p in run.sent] == [['results', 'story'], ['outcomes', 'states']], run.sent
    return out


def under_root(out, lines):
    """The lines follow the root's own lines (two spaces in), before its first input."""
    at = out.index('  ' + lines[0])
    assert out[at:at + len(lines)] == ['  ' + line for line in lines], out
    assert all(line.startswith('  ') and not line.startswith('    ') for line in out[1:at]), out
    return at


def test_an_accepted_version_reads_its_acceptance_under_its_lines(run, g):
    from project_gateway.tests.test_outcome_gate import accepted
    from project_gateway.tests.test_outcome_states import declare, today
    declare(g)
    out = told(run, accepted(g))
    under_root(out, ['Accepted on %s under Tops within 5 m version 1' % today()])


def test_a_rejected_version_reads_as_the_workspace_words_it(run, g):
    from project_gateway.tests.test_outcome_gate import rejected
    from project_gateway.tests.test_outcome_states import declare
    declare(g)
    out = told(run, rejected(g))
    line = next(line for line in out if 'Fails the outcome' in line).strip()
    assert line.startswith('Fails the outcome "Tops within 5 m", declared at version 1 (a change to its rule makes a new version): '), out
    assert not any('Rejected under' in line for line in out), out
    under_root(out, [line])


def test_a_version_published_before_its_outcome_reads_not_checked_with_the_outcomes_name(run, g):
    from project_gateway.tests.test_outcome_gate import accepted
    from project_gateway.tests.test_outcome_states import declare
    receipt = accepted(g)
    declare(g)
    out = told(run, receipt)
    under_root(out, ['Tops within 5 m: Not checked: published before this outcome; run and publish again'])


def test_a_delivered_version_reads_its_delivery_under_its_acceptance(run, g):
    from project_gateway.tests.test_outcome_gate import accepted, answer
    from project_gateway.tests.test_outcome_states import declare, today
    from project_gateway.tests.test_outcome_story import report
    found = declare(g)
    receipt = accepted(g)
    assert answer(g.deliver_as(found['outcome_id'], receipt))['state'] == 'claimed'
    under_root(told(run, receipt), ['Accepted on %s under Tops within 5 m version 1' % today(),
                                    'Delivered as Tops within 5 m version 1: allowed to be delivered; no delivery reported yet.'])
    report(g, receipt, 'confirmed', 'report-0001-confirmed')
    under_root(told(run, receipt), ['Accepted on %s under Tops within 5 m version 1' % today(),
                                    'Delivered as Tops within 5 m version 1: delivered to Team database, confirmed %s.' % today()])
