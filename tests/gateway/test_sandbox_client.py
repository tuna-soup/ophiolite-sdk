"""E113 s1 C7, gateway lane: sandbox runs from the SDK and the command line against the real routes of an in-process
gateway (test_sandbox_runs' `started`: a deployment with a sandbox image whose engine is the test's FakeBox, no worker
threads, so the test runs the job). alice administers p and turns runs on and off; bob starts a run, follows it through
`runners/job` until it publishes, and alice verifies the version against it. Acceptance 7 on that published result: it
exports into a portable bundle and reopens with `procedure.witness` byte-equal, and the released SDK 2026.11.4 reads the
bundle's record with the witness an extra key it has no field for (so its reader shows nothing for it: not recorded).

Mutations (break -> FAIL, restore -> PASS; recorded in the lane's logs/c7-mut-*.txt):
a. `procedure_sandbox_job` returns the first answer without following -> the wait case stays queued;
b. `procedure_verify` sends `witnessed` as `{check_id}` -> the CLI verify case is refused."""
import contextlib
import copy
import hashlib
import io
import json
import os
import types
from pathlib import Path

import pytest
try:
    from project_gateway.tests import sandbox_world as sw
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests.test_sandbox_runs import started  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)

from ophiolite import Client, Credential, bundle, cli

FROZEN = Path(__file__).resolve().parents[1] / 'frozen' / 'sdk_release_2026_11_4'  # test_bundle_verification's extracts and digests
DIGESTS = {'generated.py.txt': 'eb8fb61dc614696c14c1bc99b36036741768bbc07e178e60cc8909ee6686da96',
           'invariants.py.txt': 'b1a2b6b7d6beb32c2406b4f32e6912fd1df141aeddc4c5410537d9adeeca7469'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def released():
    """(generated, invariants) of the released SDK 2026.11.4, loaded as test_bundle_verification loads them (that module
    imports the unit suite's conftest, which a gateway test cannot)."""
    import ophiolite.models  # noqa: F401 (the package its relative import names)
    loaded = []
    for name, file in (('ophiolite.models._release_2026_11_4_generated', 'generated.py.txt'), ('ophiolite.models._release_2026_11_4_invariants', 'invariants.py.txt')):
        raw = (FROZEN / file).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == DIGESTS[file], file + ' is not the frozen extract'
        module = types.ModuleType(name)
        module.__package__, module.__file__ = 'ophiolite.models', str(FROZEN / file)
        exec(compile(raw, module.__file__, 'exec'), module.__dict__)  # compiled here: nothing is written beside the extracts
        loaded.append(module)
    return loaded


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def command(client, *argv):
    """(exit code, stdout, stderr) of one `ophiolite tools …` catalogue verb with this client."""
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli._catalogue(cli.parser().parse_args(['tools', *map(str, argv)]), client)
        except SystemExit as stop: code = stop.code if isinstance(stop.code, int) else 1
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_the_sdk_turns_runs_on_and_off_starts_one_and_follows_it_until_it_publishes(started):
    world, pool, box, d, a = started
    alice, bob = sdk(world, 'alice'), sdk(world, 'bob')
    assert alice.procedure_sandbox_enable(d, False)['sandbox'] is False
    assert bob.procedure_get(d)['sandbox'] is False
    assert alice.procedure_sandbox_enable(d)['sandbox'] is True
    slept = []
    def runs_it(seconds):  # the deployment's worker, in the test: the job runs while the SDK waits
        slept.append(seconds)
        if len(slept) == 1: sw.execute(pool, job_id[0])
    job_id = []
    original = bob._post
    def seen(area, operation, body, **kw):
        answer = original(area, operation, body, **kw)
        if operation == 'sandbox-run': job_id.append(answer['id'])
        return answer
    bob._post = seen
    job = bob.procedure_sandbox_run(d, {'tops': [(a['asset_id'], a['revision'])]}, settings={'shift': 5}, limits={'memory_mb': 128}, wait=60,
                                    interval=0.5, sleep=runs_it)
    assert (job['state'], job['kind'], job['limits']['memory_mb'], slept) == ('published', 'procedure', 128, [0.5]), job
    [output] = job['result']['outputs']
    assert sw.payload(world, output['asset_id'], output['revision']) == sw.SHIFTED_RAW
    assert bob.procedure_sandbox_job(job['id']) == job  # the same job, read again


def test_without_a_wait_the_answer_is_the_queued_job(started):
    world, pool, box, d, a = started
    job = sdk(world, 'bob').procedure_sandbox_run(d, {'tops': [a]}, settings={'shift': 5}, command_id='sr-sdk')
    assert (job['state'], job['command_id'], job['script_sha256']) == ('queued', 'sr-sdk', d)
    assert sdk(world, 'bob').procedure_sandbox_run(d, {'tops': [a]}, settings={'shift': 5}, command_id='sr-sdk')['id'] == job['id']  # resent: the same job


def test_the_command_line_switches_starts_reads_the_job_and_verifies_against_the_run(started, tmp_path):
    world, pool, box, d, a = started
    alice, bob = sdk(world, 'alice'), sdk(world, 'bob')
    label = alice.procedure_get(d)['label']
    assert command(alice, 'sandbox', 'off', 'depth-shift', '--version', 1) == (0, 'Sandbox runs of %s, version 1, are off in this project.' % label, '')
    assert command(bob, 'sandbox', 'status', 'depth-shift') == (0, 'Sandbox runs of %s, version 1, are off in this project.' % label, '')
    assert command(alice, 'sandbox', 'on', 'depth-shift', '--version', 1) == (0, 'Sandbox runs of %s, version 1, are on in this project.' % label, '')
    code, text, _ = command(bob, 'sandbox', 'run', 'depth-shift', '--item', 'tops=@%s:%s' % (a['asset_id'], a['revision']), '--setting', 'shift=5', '--json')
    job = json.loads(text)
    assert (code, job['state'], job['limits']) == (0, 'queued', sw.LIMITS)
    assert command(bob, 'sandbox', 'status', '--job', job['id']) == (0, 'Sandbox run %s is waiting for a runner.' % job['run_id'], '')
    assert sw.execute(pool, job['id'])['state'] == 'published'
    assert command(bob, 'sandbox', 'status', '--job', job['id']) == (0, 'Sandbox run %s published its outputs.' % job['run_id'], '')
    code, text, _ = command(alice, 'verify', 'depth-shift', '--run', job['run_id'])
    assert code == 0 and text.startswith('Verified by Alice against a run Ophiolite made on '), text
    assert command(bob, 'sandbox', 'run', 'depth-shift', '--item', 'tops=%s' % a['asset_id'])[:2] == (1, '')  # not an exact version: refused here


def test_a_run_that_ends_unpublished_exits_1_with_its_words(started):
    world, pool, box, d, a = started
    bob = sdk(world, 'bob')
    job = bob.procedure_sandbox_run(d, {'tops': [a]}, settings={'shift': 5})
    assert world.ok('bob', 'runners', 'cancel', {'id': job['id']})['state'] == 'cancelled'
    assert command(bob, 'sandbox', 'status', '--job', job['id']) == (1, 'Sandbox run %s was cancelled.' % job['run_id'], '')


def test_a_sandbox_published_result_exports_reopens_and_the_released_reader_keeps_the_witness_unread(started, tmp_path):
    """Acceptance 7 (M8) on the actual published result."""
    world, pool, box, d, a = started
    bob = sdk(world, 'bob')
    job = bob.procedure_sandbox_run(d, {'tops': [a]}, settings={'shift': 5})
    done = sw.execute(pool, job['id'])
    [output] = done['result']['outputs']
    stored = sw.stored_record(world, output['asset_id'], output['revision'])
    assert stored['procedure']['witness']['kind'] == 'sandbox' and stored['procedure']['witness']['job'] == job['id']
    opened = bob.export([(output['asset_id'], output['revision'], None)], tmp_path / 'bundle')
    reopened = bundle.open_bundle(opened.path)
    [asset] = reopened.assets
    path = next(f['path'] for f in asset.entry['files'] if f['role'] == 'descriptor')
    descriptor = json.loads((reopened.path / path).read_bytes())
    record = descriptor['manifest']['derivation_record']
    assert canonical(record['procedure']['witness']) == canonical(stored['procedure']['witness'])

    generated, invariants = released()
    assert 'witness' not in generated.DerivationProcedure.model_fields  # the released reader has no field for it: not recorded
    dumped = generated.DerivationRecordV2.model_validate(copy.deepcopy(record)).model_dump(by_alias=True)
    assert canonical(dumped['procedure']['witness']) == canonical(record['procedure']['witness'])  # kept, unread
    value = {**descriptor, 'manifest': {**descriptor['manifest'], 'derivation_record': dumped}}
    artifact = next(r for r in descriptor['representations'] if r['kind'] != 'normalized')
    normalized = next((r for r in descriptor['representations'] if r['kind'] == 'normalized'), None)
    assert invariants.manifest(value, artifact, normalized) is None
