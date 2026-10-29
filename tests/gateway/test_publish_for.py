"""E120 s2 (C5 tests 2 and 2a; D10, 1-8, 3-6), gateway lane: `ophiolite procedures again … --for OUTCOME` as an external
client of the in-process gateway, signed in with an access key, no mocks at client.py or publish.py. alice administers
project p, declares "Tops within 5 m", publishes a residual result through E119b's run path (Accepted under version 1)
and revises the outcome to 6 m, so the result reads published before this outcome. Running it again for the outcome
publishes the same bytes again, which version 2 evaluates. This computer's part is a seam: each input is taken as its
stored type and the run writes the earlier result's bytes (the fixture procedure is not a residual calculator)."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.test_outcome_republish import Again
    from project_gateway.tests.test_outcome_states import declare, today
    from project_gateway.tests.test_residual_runs import MANIFEST, SETTINGS
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import client, key
from ophiolite import cli, procedures

SIX = 'Tops within 6 m'
AGAIN = 'Published again for Tops within 6 m: Residuals DCC, version 1, the same result.'
RECEIPT_KEYS = ['asset_id', 'command_id', 'derived_from', 'method', 'outcome', 'profile', 'republished', 'revision', 'revision_number']


@pytest.fixture
def p(keyed, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.chdir(tmp_path)
    w = Again(keyed)
    found = declare(w)
    w.original = w.accepted()
    w.revise(found)
    w.found, w.client, w.tmp = found, client(keyed, key(keyed, 'alice')), tmp_path

    def download(self, asset, revision, stem, profile=None, declared=None, wellbore=None):
        return procedures.ProjectInput(str(stem), profile, dict(declared or {}), asset, revision, wellbore)

    def ran(local, destination, inputs, settings=None, expected_digest=None):
        folder = Path(destination)
        folder.mkdir(parents=True)
        (folder / 'residuals.json').write_bytes(w.raw)
        record = {'schema': procedures.LOCAL_RUN, 'procedure': {'digest': expected_digest}, 'settings': dict(SETTINGS), 'systems': {},
                  'inputs': {i['slot']: [{'asset_id': v.asset_id, 'revision': v.revision, 'kind': v.kind, 'declared': v.declared} for v in inputs[i['slot']]]
                             for i in MANIFEST['inputs']},  # in the manifest's order, as run() records them
                  'outputs': {'residuals': {'file': 'residuals.json', 'sha256': hashlib.sha256(w.raw).hexdigest(), 'profile': 'well-residual/1', 'declared': {}}},
                  'runner': 'this computer'}
        (folder / 'run.json').write_text(json.dumps(record))
        return {'sentence': 'Ran the residuals on this computer.'}
    monkeypatch.setattr(procedures.ProcedureClient, '_download_version', download)
    monkeypatch.setattr(procedures, 'run', ran)
    return w


def command(client, *argv):
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli._catalogue(cli.parser().parse_args(['procedures', *map(str, argv)]), client)
        except SystemExit as stop: code = stop.code or 0
    return code, out.getvalue().strip(), err.getvalue().strip()


def line(w):
    [o] = w.client.outcome_states(w.original['asset_id'], w.original['revision'])['outcomes']
    return o['version'], o['line']


def test_2_procedures_again_for_publishes_again_and_version_2_reads_it(p):
    """Mutation: derive_request leaves `for_outcome` out -> an ordinary "Same result" -> red."""
    w = p
    assert line(w) == (2, 'Not checked: published before this outcome; run and publish again')
    code, out, err = command(w.client, 'again', w.original['asset_id'], '--revision', w.original['revision'], '--output', w.tmp / 'again', '--for', SIX, '--yes')
    assert (code, err, out.splitlines()) == (0, '', ['Ran the residuals on this computer.', AGAIN])
    assert [row[1] for row in w.outputs()] == ['published', 'republished'] and w.derived() == 1
    assert json.loads((w.tmp / 'again/publish.json').read_text())['for_outcome'] == {'outcome_id': w.found['outcome_id'], 'label': SIX}
    assert line(w) == (2, 'Accepted on %s under Tops within 6 m version 2' % today())


def test_2_an_interrupted_publish_for_resumes_from_its_saved_state_and_still_publishes_for_the_outcome(p, monkeypatch):
    """1-8. Mutation: keep `for_outcome` in memory only (not in publish.json) -> the resume answers "Same result" -> red."""
    w = p
    with monkeypatch.context() as m:
        def stop(state): raise KeyboardInterrupt
        m.setattr(procedures, 'before_report', stop)
        with pytest.raises(KeyboardInterrupt): w.client.procedure_again(w.original['asset_id'], w.original['revision'], w.tmp / 'again', yes=True, for_=SIX)
    assert w.outputs() == [(w.run['run_id'], 'published', w.original['asset_id'], w.original['revision'])]
    answer = w.client.procedure_publish(w.tmp / 'again')  # the folder alone: the outcome comes from publish.json
    [output] = answer['outputs']
    assert (output['outcome'], output['sentence']) == ('republished', AGAIN)
    assert [row[1] for row in w.outputs()] == ['published', 'republished']


def test_2a_the_receipt_on_publish_and_on_resume_has_the_public_key_set(p):
    """3-6. Mutation: serve the stored receipt unscrubbed (outputs_locked) -> the resumed receipt carries _request -> red."""
    w = p
    published = w.client.procedure_again(w.original['asset_id'], w.original['revision'], w.tmp / 'again', yes=True, for_=SIX)
    [first] = published['outputs']
    resumed = w.client.procedure_publish(w.tmp / 'again')  # the answer was lost: the run's answered output comes back
    [again] = resumed['outputs']
    assert (sorted(first['receipt']), sorted(again['receipt'])) == (RECEIPT_KEYS, RECEIPT_KEYS)
    assert again['receipt'] == first['receipt'] and first['receipt']['republished'] is True
    assert (again['outcome'], [row[1] for row in w.outputs()]) == ('republished', ['published', 'republished'])


def test_2_an_unknown_outcome_name_refuses_before_anything_runs(p):
    w = p
    from ophiolite.errors import Refused
    with pytest.raises(Refused) as refused: w.client.procedure_again(w.original['asset_id'], w.original['revision'], w.tmp / 'again', yes=True, for_='Tops within 9 m')
    assert (str(refused.value), (w.tmp / 'again').exists(), len(w.outputs())) == ('This project has no outcome named "Tops within 9 m".', False, 1)
