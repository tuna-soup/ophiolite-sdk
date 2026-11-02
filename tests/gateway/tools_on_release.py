"""E131 s1 acceptance 7 (D6, R2-3, R2-5): a tool written on this head runs on the published pre-lane release, and a
version the release registered runs through this head's `tool_*` methods, both against the released Platform.

It needs two things this lane provides locally and hosted runners do not: OPHIOLITE_RELEASE_PYTHON, a Python whose venv
was made fresh with `pip install ophiolite==2026.10.128`, and OPHIOLITE_SANDBOX, the `dev up --json` file of a sandbox
running the released image (localhost/ophiolite-server:2026.10.128-amd64), as `tools/lane-sandbox.py` gives a command.
Without either it skips, saying which. Its name is not test_*.py on purpose: an SDK lane fails on any skip
(tools/run-sdk-checks.py), so no lane collects it; it runs by path inside the sandbox:

  tools/lane-sandbox.py --scratch DIR --image localhost/ophiolite-server:2026.10.128-amd64 \
    "release:PORT:OPHIOLITE_RELEASE_PYTHON=<venv>/bin/python <lane venv>/bin/python -m pytest -q ophiolite-sdk/tests/gateway/tools_on_release.py"

The release runs isolated (`-I`, a scrubbed environment) so the head's checkout can never stand in for it. Expected
values are literals."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import ophiolite
from ophiolite import Client, Credential, cli, procedures

RELEASE = os.environ.get('OPHIOLITE_RELEASE_PYTHON')
SANDBOX = os.environ.get('OPHIOLITE_SANDBOX')
pytestmark = pytest.mark.skipif(not (RELEASE and SANDBOX), reason='acceptance 7 needs OPHIOLITE_RELEASE_PYTHON (a fresh venv '
                                'with ophiolite==2026.10.128) and OPHIOLITE_SANDBOX (a sandbox of the released Platform image)')
RELEASED = '2026.10.128'
FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'
SAMPLE = b'name,md,tvd,source\nNU,1203.5,1198.2,picks 2024\nNM,1421,,\nNL,1650.25,1601,picks 2024\n'
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'
LAS = '~Version\nVERS. 2.0 : LAS version\n~Well\n'
# Runs in the release's interpreter: each call is (access key, method, args, kwargs) on a fresh release Client.
CALLS = r'''
import json, sys
import ophiolite
from ophiolite import Client, Credential
order = json.load(sys.stdin)
results = [getattr(Client(order['url'], order['project'], Credential.bearer(key)), method)(*args, **kwargs)
           for key, method, args, kwargs in order['calls']]
print(json.dumps({'file': ophiolite.__file__, 'version': ophiolite.__version__, 'results': results}, default=str))
'''


@pytest.fixture
def sandbox():
    return json.loads(Path(SANDBOX).read_text())


def release(tmp_path, sandbox, calls):
    """The calls made by the published release, isolated from this checkout; returns its answer."""
    (tmp_path / 'release-home').mkdir(exist_ok=True)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'release-home'), 'LANG': 'C.UTF-8'}
    order = {'url': sandbox['url'], 'project': sandbox['project'], 'calls': calls}
    done = subprocess.run([RELEASE, '-I', '-c', CALLS], input=json.dumps(order), capture_output=True, text=True, env=env,
                          cwd=tmp_path, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    answer = json.loads(done.stdout)
    where = Path(answer['file']).resolve()
    assert answer['version'] == RELEASED and 'site-packages' in where.parts
    assert where.is_relative_to(Path(RELEASE).parent.parent.resolve())
    assert not where.is_relative_to(Path(ophiolite.__file__).resolve().parents[2])
    return answer['results']


def keys(sandbox):
    return sandbox['people']['alice']['access_key'], sandbox['people']['bob']['access_key'], sandbox['administrator']['write_key']


def test_a_tool_written_on_this_head_runs_on_the_release(tmp_path, sandbox):
    alice, bob, administrator = keys(sandbox)
    folder = tmp_path / 'shift'
    made = cli.main(['tools', 'new', str(folder), '--step', 'process', '--kind', 'well-tops'])  # the validate verdict of the new folder
    assert (folder / 'data/tops.csv').read_bytes() == SAMPLE
    head_digest = procedures.validate(folder)['digest']
    assert made['valid'] is True and made['digest'] == head_digest
    registered, = release(tmp_path, sandbox, [[alice, 'procedure_register', [str(folder)], {}]])
    assert registered['digest'] == head_digest
    release(tmp_path, sandbox, [[administrator, 'procedure_enable', [head_digest], {}]])
    ran, = release(tmp_path, sandbox, [[bob, 'procedure_run', ['shift', str(tmp_path / 'out')], {
        'inputs': {'data': [str(folder / 'data/tops.csv')]}, 'kinds': {'data': 'well-tops-csv/1'},
        'declared': {'data': str(folder / 'data/declared.json')}, 'yes': True, 'cache': str(tmp_path / 'cache-release')}]])
    made = ran['run']['outputs']['data']
    assert ran['run']['procedure']['digest'] == head_digest
    assert (made['file'], (tmp_path / 'out' / made['file']).read_bytes()) == ('data.csv', SAMPLE)


def test_versions_the_release_registered_run_through_the_tool_methods(tmp_path, sandbox):
    alice, bob, administrator = keys(sandbox)
    shift, las = tmp_path / 'depth-shift', tmp_path / 'team-las'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', shift, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(FIXTURES / 'bundles/team-las', las, ignore=shutil.ignore_patterns('__pycache__'))
    registered = release(tmp_path, sandbox, [[alice, 'procedure_register', [str(shift)], {}],
                                             [alice, 'procedure_register', [str(las)], {}]])
    release(tmp_path, sandbox, [[administrator, 'procedure_enable', [one['digest']], {}] for one in registered])
    head = Client(sandbox['url'], sandbox['project'], Credential.bearer(bob))
    listed = {(row['name'], row['digest']) for row in head.tool_list()}
    assert {('depth-shift', registered[0]['digest']), ('team-las', registered[1]['digest'])} <= listed
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in/tops.csv').write_text(TOPS)
    (tmp_path / 'in/tops.declared.json').write_text('{"depth_unit": "m", "depth_basis": "md"}')
    (tmp_path / 'in/a.las').write_text(LAS)
    head.tool_run('depth-shift', tmp_path / 'out-shift', {'tops': [tmp_path / 'in/tops.csv']}, kinds={'tops': 'well-tops-csv/1'},
                  declared={'tops': tmp_path / 'in/tops.declared.json'}, settings=['shift=2.5'], yes=True, cache=tmp_path / 'cache-head')
    head.tool_run('team-las', tmp_path / 'out-las', {'file': [tmp_path / 'in/a.las']}, yes=True, cache=tmp_path / 'cache-head')
    assert (tmp_path / 'out-shift/shifted.csv').read_bytes() == SHIFTED
    assert (tmp_path / 'out-las/log.las').read_text() == LAS
