"""E120 s3 (C5 tests 1, 1a to 1f; D7, 2-5, 5-20, 5-23), gateway lane: `ophiolite deliver NAME --as OUTCOME` as an
external client of the in-process gateway, signed in with access keys, no mocks at client.py or publish.py. alice
administers project p, declares "Tops within 5 m" (delivered by tops-to-team-database to Team database), registers
and enables that send procedure (it copies the residual version into a local folder and counts its runs) and publishes
residual results through E119b's run path. Interruptions are the deliver module's own seams (`_deliver_once`,
`_launched`), never the transport."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
try:
    from project_gateway.tests.test_outcome_states import declare, publish, residuals
    from project_gateway.tests.test_outcome_republish import Again
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import client, key
from ophiolite import procedures
from ophiolite.exchange import ClientTransport
from ophiolite.testing import fixture_server

NAME, OUTCOME, DESTINATION = 'tops-to-team-database', 'Tops within 5 m', 'Team database'
WRITER = '''import os
from pathlib import Path

import ophiolite
from ophiolite import procedure


@procedure
def send(inputs, settings, delivery):
    counter = Path(os.environ['E120_COUNTER'])  # counted at entry
    counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
    target = Path(delivery.system.config['folder']) / delivery.id
    target.mkdir(parents=True)
    (target / 'residuals.json').write_bytes(Path(inputs['residuals'][0].path).read_bytes())
    return ophiolite.delivered(items=1)
'''
MANIFEST = {'schema': 'ophiolite.procedure/1', 'name': NAME, 'label': 'Residuals to the team database', 'version': 1, 'step': 'send',
            'inputs': [{'slot': 'residuals', 'label': 'Residuals to deliver', 'class': 'version', 'kinds': ['well-residual/1'], 'cardinality': 'one'},
                       {'slot': 'db', 'label': DESTINATION, 'class': 'system', 'config_keys': ['folder']}],
            'outputs': [{'role': 'delivery', 'label': 'Delivered residuals', 'class': 'delivery'}], 'settings': [], 'entry': 'procedure:send'}
CLAIMED = 'Delivered as Tops within 5 m: Accepted under version 1; the delivery may start.'


class ParentStopped(BaseException):
    """The parent process stops at a seam."""


@pytest.fixture
def j(keyed, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setenv('E120_COUNTER', str(tmp_path / 'runs'))
    monkeypatch.chdir(tmp_path)
    # keyed maps an access key to its person for the gateway's platform calls; the record's Activity (activity/deliver)
    # took its platform at start, so it reads through the same mapping (fixture wiring, as a deployment's one platform)
    keyed.app.state.activity.platform = lambda method, body, token: keyed.a.sources.platform(method, body, token)
    w = Again(keyed)  # E119b's residual world, with E120 s2's run made again
    alice_key, bob_key = key(keyed, 'alice'), key(keyed, 'bob')
    alice = client(keyed, alice_key)
    folder = tmp_path / 'send'
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps(MANIFEST, indent=2))
    (folder / 'procedure.py').write_text(WRITER)
    assert procedures.validate(folder)['valid'], procedures.validate(folder)
    alice.procedure_enable(alice.procedure_register(folder)['digest'])
    found = declare(w)
    _, accepted = publish(w, residuals(w, 0.5, -1.0, 5.0))
    team = tmp_path / 'team'
    team.mkdir()
    config = tmp_path / 'db.json'
    config.write_text(json.dumps({'folder': str(team)}))
    item = next(i['name'] for i in ClientTransport(alice).inventory() if i['asset_id'] == accepted['asset_id'])
    w.j = {'alice': alice, 'bob': client(keyed, bob_key), 'keys': {'alice': alice_key, 'bob': bob_key}, 'outcome': found, 'receipt': accepted,
           'item': item, 'config': config, 'team': team, 'work': tmp_path / '.ophiolite-held', 'runs': tmp_path / 'runs', 'tmp': tmp_path}
    return w


def named(w, change, command, name):
    """E119b's publish with the result under its own name, so `--item NAME@1` names exactly one version."""
    raw = w.payload(change)
    r = w.report(raw, command)
    assert r.status_code == 200, r.text
    run = r.json()
    published = w.alice.post('publications', 'derive', {}, raw=raw, header={**w.header(run, raw), 'name': name})
    assert published.status_code == 200, published.text
    return published.json()


def deliver(w, who='alice', as_=OUTCOME, item=None):
    return w.j[who].deliver(NAME, systems={'db': str(w.j['config'])}, items=['residuals=%s@1' % (item or w.j['item'])], work=w.j['work'], wait=0, yes=True, as_=as_)


def runs(w):
    return int(w.j['runs'].read_text()) if w.j['runs'].exists() else 0


def attempts(w):
    return sorted((w.j['work'] / 'deliveries').glob('*/attempt.json'))


def intents(w):
    return sorted((w.j['work'] / 'deliveries' / 'intents').glob('*.json'))


def claims(w):
    with w.a.journal.lock:
        return w.a.journal.db.execute('SELECT outcome_id,state,reason,delivery_id,command_id FROM outcome_claims ORDER BY at').fetchall()


def interrupted(w, monkeypatch, **kw):
    """The gate committed its claim; the parent stops before the pending record is written."""
    def stop(*a, **k): raise ParentStopped()
    with monkeypatch.context() as m:  # only the seam is undone; the fixture's environment stays
        m.setattr(procedures.ProcedureClient, '_deliver_once', stop)
        with pytest.raises(ParentStopped): deliver(w, **kw)
    assert attempts(w) == [] and len(intents(w)) == 1 and runs(w) == 0
    return claims(w)


# --- 1: refused, through the command line ---------------------------------------------------------------------------------

def test_1_a_refused_deliver_as_exits_nonzero_with_the_sentence_and_leaves_no_pending_record_and_no_run(j):
    """Mutation: write the pending record before the gate -> an attempt.json is left -> red."""
    w = j
    rejected = named(w, residuals(w, 0.5, 5.0001, 2.0), 'run-2', 'Residuals DCC rejected')  # its own name: the --item match is unchanged (D-4(4))
    item = next(i['name'] for i in ClientTransport(w.j['alice']).inventory() if i['asset_id'] == rejected['asset_id'])

    def handler(method, path, raw, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = w.web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content
    with fixture_server(handler) as server:
        configuration = w.j['tmp'] / 'configuration.json'
        configuration.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))
        env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': w.j['keys']['alice']['key']}
        done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'deliver', NAME, '--as', OUTCOME, '--system', 'db=%s' % w.j['config'],
                               '--item', 'residuals=%s@1' % item, '--yes', '--work', str(w.j['work']), '--configuration', str(configuration),
                               '--credentials', str(w.j['tmp'] / 'not-saved.json')], capture_output=True, text=True, timeout=120, env=env, cwd=w.j['tmp'])
    assert (done.returncode, done.stdout.strip()) == (1, ''), done
    assert done.stderr.strip() == 'Rejected under Tops within 5 m version 1: B1 top 2: 5.0001 m'
    assert (attempts(w), intents(w), runs(w), list(w.j['team'].iterdir())) == ([], [], 0, [])
    assert [c[1:3] for c in claims(w)] == [('refused', 'rejected')]


# --- 1a: claimed ------------------------------------------------------------------------------------------------------------

def test_1a_a_claimed_deliver_as_saves_the_gates_delivery_id_and_runs_once(j):
    """Mutation: generate a local uuid -> the attempt's id is not the claim's -> red."""
    w = j
    answer = deliver(w)
    [(outcome_id, state, reason, delivery_id, _)] = claims(w)
    assert (outcome_id, state, reason) == (w.j['outcome']['outcome_id'], 'claimed', None)
    assert (answer['delivery_id'], answer['state'], answer['reported']) == (delivery_id, 'confirmed', True), [json.loads(a.read_text()).get('report_error') for a in attempts(w)]
    [path] = attempts(w)
    attempt = json.loads(path.read_text())
    assert (attempt['delivery_id'], attempt['outcome']['label'], attempt['outcome']['version']) == (delivery_id, OUTCOME, 1)
    assert (runs(w), intents(w), [p.name for p in w.j['team'].iterdir()]) == (1, [], [delivery_id])


def test_1a_deliver_as_takes_one_version(j):
    w = j
    with pytest.raises(procedures.NotRun) as refused:
        w.j['alice'].deliver(NAME, systems={'db': str(w.j['config'])}, items=['residuals=%s@1' % w.j['item'], 'residuals=%s@1' % w.j['item']],
                             work=w.j['work'], wait=0, yes=True, as_=OUTCOME)
    assert (refused.value.code, str(refused.value)) == ('too-many-inputs', 'Not run: Residuals to deliver takes one file.') and (claims(w), attempts(w)) == ([], [])


# --- 1b to 1f: interruptions and resumption ---------------------------------------------------------------------------------

def test_1b_an_interruption_after_the_gate_resumes_with_the_same_command_and_claim_and_launches_once(j, monkeypatch):
    """Mutation: a fresh command on resume -> two claims -> red."""
    w = j
    [first] = interrupted(w, monkeypatch)
    answer = deliver(w)
    assert claims(w) == [first]
    assert (answer['delivery_id'], answer['state'], runs(w), intents(w)) == (first[3], 'confirmed', 1, [])
    [path] = attempts(w)
    assert json.loads(path.read_text())['delivery_id'] == first[3]


def test_1c_resuming_after_the_outcome_was_disabled_launches_nothing_and_says_why(j, monkeypatch):
    w = j
    interrupted(w, monkeypatch)
    w.alice.ok('outcomes', 'disable', {'command_id': 'off', 'outcome_id': w.j['outcome']['outcome_id']})
    with pytest.raises(procedures.NotRun) as refused: deliver(w)
    assert (refused.value.code, str(refused.value)) == ('as-refused', 'Not checked: This outcome is disabled')
    assert (attempts(w), intents(w), runs(w), len(claims(w))) == ([], [], 0, 1)


def test_1d_an_interruption_after_the_launch_is_recovered_by_e109_without_asking_the_gate_again(j, monkeypatch):
    w = j
    def stop(process, folder):
        process.wait()
        raise ParentStopped()
    with monkeypatch.context() as m:
        m.setattr(procedures, '_launched', stop)
        with pytest.raises(ParentStopped): deliver(w)
    [first] = claims(w)
    asked = []
    gate = procedures.ProcedureClient._deliver_as_gate
    monkeypatch.setattr(procedures.ProcedureClient, '_deliver_as_gate', lambda self, *a: asked.append(a) or gate(self, *a))
    answer = deliver(w)
    assert (asked, claims(w), runs(w), answer['delivery_id']) == ([], [first], 1, first[3])


def test_1e_resuming_after_the_acceptance_changed_launches_nothing_and_a_new_deliver_as_is_a_new_claim(j, monkeypatch):
    """3-4: version 2 is declared after the claim. The new claim is judged afresh (the result now reads published
    before this outcome; its republication form follows)."""
    w = j
    [first] = interrupted(w, monkeypatch)
    from project_gateway.tests.test_outcome_states import FIVE
    w.alice.ok('outcomes', 'revise', {'command_id': 'v2', 'outcome_id': w.j['outcome']['outcome_id'],
                                      'declaration': {**FIVE, 'rule': {**FIVE['rule'], 'settings': {**FIVE['rule']['settings'], 'tolerance': {'value': 6, 'unit': 'm'}}}}})
    with pytest.raises(procedures.NotRun) as refused: deliver(w)
    assert str(refused.value) == "This outcome's acceptance changed; deliver as Tops within 5 m again"
    assert (attempts(w), intents(w), runs(w), claims(w)) == ([], [], 0, [first])
    with pytest.raises(procedures.NotRun) as again: deliver(w)
    assert str(again.value) == 'Not checked: published before this outcome; run and publish again'
    assert [c[1:3] for c in claims(w)] == [('claimed', None), ('refused', 'before')] and claims(w)[1][4] != first[4]
    assert runs(w) == 0


def test_1e_after_the_result_is_published_again_for_version_2_the_resume_still_launches_nothing_and_a_new_deliver_as_claims_version_2(j, monkeypatch):
    """3-4, the republication form (slice 2's duty from s3): version 2 is declared after the claim and the result is
    published again for it ("Publish for", C3), so it reads Accepted under version 2. The saved intent's claim is
    version 1's: the resume refuses and launches nothing; a new deliver-as is a new claim and launches once. Mutation:
    judge the replay by "it passes now" alone -> the old claim launches -> red."""
    w = j
    [first] = interrupted(w, monkeypatch)
    from project_gateway.tests.test_outcome_states import FIVE
    w.revise(w.j['outcome'], {**FIVE, 'rule': {**FIVE['rule'], 'settings': {**FIVE['rule']['settings'], 'tolerance': {'value': 6, 'unit': 'm'}}}})
    _, r = w.again(w.j['receipt'], raw=w.payload(residuals(w, 0.5, -1.0, 5.0)), for_outcome=w.j['outcome']['outcome_id'])
    assert (r.status_code, r.json().get('republished')) == (200, True), r.text
    with pytest.raises(procedures.NotRun) as refused: deliver(w)
    assert str(refused.value) == "This outcome's acceptance changed; deliver as Tops within 5 m again"
    assert (attempts(w), intents(w), runs(w), claims(w)) == ([], [], 0, [first])
    answer = deliver(w)
    [_, second] = claims(w)
    assert (second[1:3], second[4] != first[4], answer['delivery_id'], answer['state']) == (('claimed', None), True, second[3], 'confirmed')
    assert (runs(w), [p.name for p in w.j['team'].iterdir()]) == (1, [second[3]])


def test_1f_a_saved_intent_is_not_used_for_another_outcome_or_person_and_nothing_launches_under_the_old_claim(j, monkeypatch):
    """5-23. Mutation: match a saved intent by procedure only -> the old claim launches -> red."""
    w = j
    [first] = interrupted(w, monkeypatch)
    from project_gateway.tests.test_outcome_states import FIVE
    declare(w, {**FIVE, 'label': 'Tops within 1 m', 'rule': {**FIVE['rule'], 'settings': {**FIVE['rule']['settings'], 'tolerance': {'value': 1, 'unit': 'm'}}}}, 'd-2')
    with pytest.raises(procedures.NotRun) as other: deliver(w, as_='Tops within 1 m')
    assert str(other.value) == 'Not checked: published before this outcome; run and publish again'  # declared after the publication
    with pytest.raises(procedures.NotRun) as person: deliver(w, who='bob')
    # bob cannot see the result here, so his request stops at the item before any gate (the gate's own person check is C4 t6)
    assert str(person.value) == 'Not sent: there is no item named Residuals DCC in this project that you can see.'
    assert ([c[1:3] for c in claims(w)], claims(w)[0]) == ([('claimed', None), ('refused', 'before')], first)
    assert (attempts(w), runs(w), len(intents(w))) == ([], 0, 1)  # the old intent waits for its own request
