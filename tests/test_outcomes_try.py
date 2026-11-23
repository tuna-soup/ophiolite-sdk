"""E176 s1 C5, offline: what `Client.try_result` sends for a run folder, that it reports nothing and leaves the folder
as it was, and the words `ophiolite outcomes try` prints. Literals by hand; the HTTP answers are the Platform's
test_outcome_trial.py and the child-process journey test_outcomes_e2e.py."""
import base64
import hashlib
import json
from pathlib import Path

import pytest

from ophiolite import outcomes, procedures

DIGEST = 'd' * 64
VERSION = {'digest': DIGEST, 'name': 'well-residuals', 'version': 3, 'label': 'Well residuals',
           'manifest': {'step': 'process', 'inputs': [{'slot': s} for s in ('selection', 'tops', 'surface', 'trajectories')], 'outputs': [{'kind': 'well-residual/1'}]}}
SETTINGS = {'formation': 'DCC', 'display_unit': 'm'}
RAW = b'{"schema":"ophiolite.well-residual/1","rows":[]}'


def version(n):
    return {'asset_id': 'a%d' % n, 'revision': ('%x' % n) * 64}


def folder(tmp_path):
    """A run folder as `procedures run` leaves it: run.json and the one output."""
    (tmp_path / 'residuals.json').write_bytes(RAW)
    inputs = {'tops': [{**version(2), 'kind': 'well-tops-csv/1', 'declared': {}}], 'selection': [{**version(1), 'kind': 'well-set/1', 'declared': None}],
              'surface': [{**version(3), 'kind': 'esri-ascii-grid/1', 'declared': None}], 'trajectories': [{**version(4), 'kind': 'deviation-csv/1', 'declared': {}}]}
    record = {'schema': procedures.LOCAL_RUN, 'procedure': {'digest': DIGEST}, 'settings': SETTINGS, 'inputs': inputs,
              'outputs': {'residuals': {'file': 'residuals.json', 'sha256': hashlib.sha256(RAW).hexdigest(), 'profile': 'well-residual/1', 'declared': {}}}}
    (tmp_path / 'run.json').write_text(json.dumps(record))
    return tmp_path


ACCEPTED = {'outcome': {'id': 'o1', 'version': 1, 'rule': 'well-residual-within/1', 'settings_sha256': 'e' * 64}, 'label': 'Tops within 5 m',
            'would': 'accepted', 'reason': None, 'sentence': None, 'data_rules': None,
            'rows': {'computed': 3, 'passing': 3, 'failing_count': 0, 'failing': [], 'not_computed': []}}


class Fake(outcomes.OutcomeClient):
    project = 'p'

    def __init__(self, answer=None):
        self.sent, self.answer = [], answer or {'outcomes': [ACCEPTED]}

    def procedure_get(self, digest):
        assert digest == DIGEST
        return VERSION

    def outcome_named(self, label):
        return {'outcome_id': {'Tops within 5 m': 'o1'}[label], 'label': label}

    def _post(self, area, operation, body, retry=False):
        if (area, operation) != ('outcomes', 'try'): raise AssertionError('a trial sent %s/%s' % (area, operation))  # nothing is reported
        self.sent.append((body, retry))
        return self.answer


def test_try_result_sends_the_report_it_would_make_and_the_header_without_a_run(tmp_path):
    """Mutations: send the header with `run` -> its key is in the header -> red; report the run first -> the fake
    refuses procedure-runs/report -> red; parents in run.json's key order -> the derived_from list differs -> red."""
    work = folder(tmp_path)
    before = {p.name: p.read_bytes() for p in work.iterdir()}
    fake = Fake()
    assert fake.try_result(work, outcomes=['Tops within 5 m']) == {'residuals': {'outcomes': [ACCEPTED]}}
    [(body, retry)] = fake.sent
    header = json.loads(base64.b64decode(body['header']))
    report = body['run']['report']
    assert retry is True and body['outcome_ids'] == ['o1'] and body['run']['role'] == 'residuals'
    assert base64.b64decode(body['content_base64']) == RAW
    assert 'run' not in header and header['command_id'].startswith('try-') and report['command_id'].startswith('try-')
    assert {k: v for k, v in header.items() if k != 'command_id'} == {
        'project_id': 'p', 'profile': 'well-residual/1', 'name': 'Well residuals',
        'derived_from': [version(1), version(2), version(3), version(4)],  # the manifest's slot order, selection first
        'method': {'name': 'Well residuals', 'declared': True, 'library': 'well-residuals', 'version': '3', 'parameters': SETTINGS, 'script_sha256': DIGEST},
        'output_sha256': hashlib.sha256(RAW).hexdigest(), 'output_bytes': len(RAW)}
    assert {k: v for k, v in report.items() if k != 'command_id'} == {
        'procedure': {'digest': DIGEST}, 'settings': SETTINGS,
        'inputs': {'tops': [version(2)], 'selection': [version(1)], 'surface': [version(3)], 'trajectories': [version(4)]},
        'outputs': [{'role': 'residuals', 'sha256': hashlib.sha256(RAW).hexdigest(), 'bytes': len(RAW), 'declared': {}}]}
    assert {p.name: p.read_bytes() for p in work.iterdir()} == before  # no publish.json: a later procedure_publish starts afresh


def test_a_changed_output_is_not_tried(tmp_path):
    """Mutation: skip the SHA-256 check in `local_run` -> the fake answers -> red."""
    work = folder(tmp_path)
    (work / 'residuals.json').write_bytes(RAW + b' ')
    fake = Fake()
    with pytest.raises(procedures.NotRun) as caught:
        fake.try_result(work)
    assert (caught.value.code, fake.sent) == ('output-changed', [])


def rejected(reason=None, failing=(), not_computed=(), would='rejected', unit='m', limit=5):
    row = lambda value, passed: {'key': {'wellbore': 'wb-0123456789abcdef', 'occurrence': 1}, 'measure': 'residual', 'value': value, 'unit': unit,  # noqa: E731
                                 'limit': limit, 'pass': passed, 'reason': None if value is not None else 'no-trajectory'}
    rows = {'computed': len(failing), 'passing': 0,  # E176 s2a: the counts agree, as the gateway's do (R4 reads them)
'failing_count': len(failing) + sum(1 for p in not_computed if not p),
            'failing': [row(v, False) for v in failing] + [row(None, False) for p in not_computed if not p], 'not_computed': [row(None, p) for p in not_computed]}
    return {**ACCEPTED, 'would': would, 'reason': reason, 'rows': rows}


def test_the_lines_say_each_outcome_in_words_without_identifiers_or_codes():
    """One literal per branch (r1 #15). Mutation: print the first failing row's key -> its wellbore id is in a line ->
    red; print the reason code -> 'rows_missing' is in a line -> red."""
    answer = {'outcomes': [
        ACCEPTED,
        rejected(failing=[5.0001, -6.5]),
        rejected(failing=[7.0], not_computed=[False, False]),
        {**rejected(failing=[1.0], unit='ft', limit=2.5), 'label': 'Tops within 2.5 ft'},
        rejected('rows_missing'),
        rejected('data_rule'),
        rejected('inputs'),
        rejected('unit_mismatch', would='not_compared'),
        {**ACCEPTED, 'would': 'not_evaluated', 'reason': 'declarer_cannot_read', 'rows': None,
         'sentence': 'Would not be evaluated: the person who declared this outcome cannot read set-s.'},
        {**ACCEPTED, 'would': 'not_tried', 'reason': 'tool_rule', 'rows': None, 'sentence': "Not tried: this outcome's rule is a tool, which runs only after publication."}]}
    lines = outcomes.trial_lines(answer)
    assert lines.split('\n') == [
        'Tops within 5 m: would be accepted',
        'Tops within 5 m: would be rejected: 2 rows over 5 m',
        'Tops within 5 m: would be rejected: 1 row over 5 m, 2 required rows not computed',
        'Tops within 2.5 ft: would be rejected: 1 row over 2.5 ft',
        'Tops within 5 m: would be rejected: rows missing: the result leaves out rows its selection requires',
        'Tops within 5 m: would be rejected: an input failed a data rule the outcome names',
        'Tops within 5 m: would be rejected: made without an input kind it reads',
        'Tops within 5 m: would not be compared: units disagree',
        'Tops within 5 m: would not be evaluated: the person who declared this outcome cannot read set-s.',
        "Tops within 5 m: not tried: this outcome's rule is a tool, which runs only after publication."]
    assert 'wb-0123456789abcdef' not in lines and not any(code in lines for code in ('rows_missing', 'data_rule', 'unit_mismatch', 'tool_rule'))
    assert outcomes.trial_lines({'outcomes': [], 'sentence': 'No outcome is declared for this kind.'}) == 'No outcome is declared for this kind.'


FIXTURES = Path(outcomes.__file__).parent / 'contracts' / 'outcomes' / 'v1' / 'fixtures'
CASES = json.loads((FIXTURES / 'trial-lines.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_the_lines_are_the_contracts_hand_counted_literals(case):
    """E176 s2a (R4): the SDK and the gateway (test_trial_attached.py) give the same words for the same answer. Mutation:
    count required rows from the capped `not_computed` list -> 'twenty-five-required-not-computed' says 20 -> red."""
    answer = json.loads((FIXTURES / 'trial' / 'valid' / (case['base'] + '.json')).read_text())
    if 'rows' in case: answer['outcomes'][0]['rows'] = case['rows']
    assert outcomes.trial_lines(answer).split('\n') == case['lines']


class LostAnswer(Exception):
    pass


class Agent:
    """An assistant's client: answers procedures/get and outcomes/try; the proposal's answer is lost after it was sent."""
    project = 'p'

    def __init__(self):
        self.tried, self.proposed = [], []

    def read(self, path, body):
        assert (path, body) == ('procedures/get', {'digest': DIGEST})
        return VERSION

    def _post(self, area, operation, body, retry=False):
        if (area, operation) != ('outcomes', 'try'): raise AssertionError('a trial sent %s/%s' % (area, operation))
        self.tried.append(body)
        return {'outcomes': [ACCEPTED], 'at': 1.0, 'seal': 'sealed'}

    def propose(self, operation, request, summary='', *, evidence=None):
        self.proposed.append((operation, request, evidence))
        raise LostAnswer()


def test_an_assistant_tries_exactly_the_report_it_proposes_and_sends_the_trial_in_the_evidence(tmp_path):
    """E176 s2a: `try_outcomes` sends `request()` without `publish` as the run's report; `report(trial=)` puts that
    answer in the evidence of the same request. Mutations: try the report with `publish` -> red; drop the trial from
    the evidence -> red; a new command id per call -> the reports differ -> red."""
    work, agent = folder(tmp_path), Agent()
    run = procedures.AgentRun(agent, work, name='Well residuals')
    answers = run.try_outcomes()
    [body] = agent.tried
    assert answers == {'residuals': {'outcomes': [ACCEPTED], 'at': 1.0, 'seal': 'sealed'}} and body['run']['role'] == 'residuals' and 'outcome_ids' not in body
    header = json.loads(base64.b64decode(body['header']))
    assert 'run' not in header and header['name'] == 'Well residuals' and base64.b64decode(body['content_base64']) == RAW
    sent = {'instruction': 'Publish the residuals', 'model': {'provider': 'p', 'id': 'm'}, 'conversation': {'kind': 'chat', 'reference': 'c'}, 'client': 'x/1'}
    with pytest.raises(LostAnswer): run.report('Publish the residuals', evidence=sent, trial=answers['residuals'])
    [(operation, request, evidence)] = agent.proposed
    assert operation == 'procedure-runs/report' and request['publish'] == {'residuals': {'name': 'Well residuals'}}
    assert body['run']['report'] == {k: v for k, v in request.items() if k != 'publish'}
    assert evidence == {**sent, 'trial': answers['residuals']} and 'trial' not in sent
    run.try_outcomes(role='residuals', outcome_ids=['o1'])
    assert agent.tried[1]['outcome_ids'] == ['o1'] and agent.tried[1]['run'] == body['run']


def test_a_trial_without_evidence_is_refused_before_anything_is_sent(tmp_path):
    agent = Agent()
    with pytest.raises(ValueError) as caught:
        procedures.AgentRun(agent, folder(tmp_path), name='Well residuals').report('Publish', trial={'outcomes': []})
    assert (str(caught.value), agent.proposed) == ('A trial goes in the evidence: pass evidence with trial.', [])
