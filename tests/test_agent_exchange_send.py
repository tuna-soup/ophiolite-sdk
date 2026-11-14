"""E155 s0 C2: an assistant sends a tool run's outputs as one approved report, bound to what its folder holds. A real
`AgentClient` over an `httpx.MockTransport` gateway that keeps plans, runs and result histories the way the gateway
does (the same request is the same plan; a step's command id answers its receipt again); expected requests, sentences
and records are literals. One test per step of strategy §3.2 and row of §3.3; each names the mutation that fails it."""
import base64
import hashlib
import json

import httpx
import pytest

from ophiolite import exchange
from ophiolite.agent_exchange import AGENT_REFUSALS, AgentExchange
from ophiolite.agents import TOOL_RUN_SENTENCES, AgentClient, DryRun
from ophiolite.auth import Credential
from ophiolite.client import Client
from ophiolite.exchange import ClientTransport, Exchange, Outcome
from ophiolite.procedures import LOCAL_RUN, NotRun, output_command

URL = 'https://gateway.example'
TOPS = 't' * 64  # the input version the run read
OLD, PREV, HEAD = 'o' * 64, 'p' * 64, 'h' * 64  # versions 1 and 2 of the earlier result, and a version 3 someone adds
RAW = {'shifted': b'name,md\nTop Chalk,1005.5\n', 'moved': b'name,md\nTop Chalk,1010\n'}
LABELS = {'shifted': 'Shifted tops', 'moved': 'Moved tops'}
PROCEDURE = {'digest': 'd' * 64, 'name': 'depth-shift', 'version': 1, 'label': 'Shift tops by a fixed depth'}
NEWER = 'Version 3 was added. Your change was not sent. Either get version 3 and look at it, or send yours as a new item.'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))


class Gateway:
    """The routes `send_run` uses, keeping state as the gateway does. `answer` is the state a new plan gets; `conflict`
    roles have their stale parent refused (409); `refuse` {role or 'report': reason} answers tool-run-refused; `lose`
    names an operation (or 'derive:<role>') whose next answer is lost after it took effect."""
    def __init__(self, agent_id='agent-7'):
        self.agent_id, self.answer, self.seen = agent_id, 'approved', []
        self.plans, self.runs, self.receipts = {}, {}, {}
        self.history = {'a-prev': [(1, OLD), (2, PREV)], 'a-tops': [(1, TOPS)]}
        self.refuse, self.lose = {}, set()
        self.entities = {}  # E155 s2: entity id -> kind, as entities/get answers it

    def __call__(self, request):
        op = request.url.path.split('/projects/p/', 1)[1]
        if request.headers.get('content-type') == 'application/octet-stream':
            body, raw = json.loads(base64.b64decode(request.headers['x-ophiolite-upload'])), request.content
        else: body, raw = json.loads(request.content or b'{}'), None
        self.seen.append({'op': op, 'body': body, 'raw': raw, 'plan': request.headers.get('x-ophiolite-plan')})
        answer = self.route(op, body, raw)
        key = 'derive:' + body['run']['role'] if op == 'publications/derive' else op
        if key in self.lose: self.lose.discard(key); raise httpx.ReadError('lost', request=request)
        return answer

    def refused(self, reason):
        sentence = TOOL_RUN_SENTENCES[reason].format(delegator='Bob Example')
        return httpx.Response(403, json={'code': 'tool-run-refused', 'message': sentence, 'reason': reason, 'request_id': 'r-1'})

    def route(self, op, body, raw):
        if op == 'capabilities/describe':
            return httpx.Response(200, json={'principal': {'kind': 'agent', 'agent': {'id': self.agent_id}}, 'operations': []})
        if op == 'procedures/get':
            return httpx.Response(200, json={'manifest': {'step': 'process', 'inputs': [{'slot': 'tops', 'kind': 'well-tops-csv/1'}],
                                                          'outputs': [{'role': r, 'label': LABELS[r], 'kind': 'well-tops-csv/1'} for r in RAW]}})
        if op == 'entities/get':
            if body['entity_id'] not in self.entities: return httpx.Response(404, json={'code': 'not-found', 'message': 'Entity unavailable', 'request_id': 'r-4'})
            return httpx.Response(200, json={'entity_id': body['entity_id'], 'kind': self.entities[body['entity_id']], 'name': 'Delft 1'})
        if op == 'agents/propose':
            if 'report' in self.refuse: return self.refused(self.refuse['report'])
            plan = sha(canonical(body['request']).encode())
            self.plans.setdefault(plan, {'state': self.answer, 'request': body['request']})  # an existing hash keeps its state
            return httpx.Response(200, json={'hash': plan, 'state': self.plans[plan]['state']})
        if op == 'agents/status':
            return httpx.Response(200, json={'state': self.plans[body['hash']]['state']})
        if op == 'procedure-runs/report' and body.get('dry_run'):
            return httpx.Response(200, json={'schema': 'ophiolite.agent-dry-run/1', 'dry_run': True, 'operation': 'procedure-runs/report', 'project_id': 'p',
                                             'would': {'outcome': 'proceeds', 'effects': [{'action': 'create', 'kind': 'procedure-run', 'count': 1}]},
                                             'digest': '9' * 64})
        if op == 'procedure-runs/report':
            plan = self.plans[self.seen[-1]['plan']]
            assert plan['state'] == 'approved' and canonical(body) == canonical(plan['request'])  # exactly the approved request
            run = self.runs.setdefault(body['command_id'], 'run-' + body['command_id'][-6:])
            outputs = [{**o, 'outcome': 'published' if (run, o['role']) in self.receipts else None, 'receipt': self.receipts.get((run, o['role']))}
                       for o in body['outputs']]
            return httpx.Response(200, json={'run_id': run, 'state': 'partial', 'procedure': PROCEDURE, 'settings': body['settings'], 'outputs': outputs})
        if op == 'publications/derive':
            role, run = body['run']['role'], body['run']['id']
            assert body['command_id'] == output_command(run, role)
            if (run, role) in self.receipts: return httpx.Response(200, json=self.receipts[(run, role)])
            if role in self.refuse: return self.refused(self.refuse[role])
            target = body.get('new_version_of')
            versions = self.history.get(target, []) if target else []
            if target and (body['expected_parent'] != versions[-1][1] or body['output_sha256'] in [r for _, r in versions]):
                return httpx.Response(409, json={'code': 'revision-conflict', 'message': 'The parent is not the head.', 'request_id': 'r-2'})
            asset, number = target or 'a-new-' + role, len(versions) + 1
            self.history.setdefault(asset, []).append((number, body['output_sha256']))
            self.receipts[(run, role)] = {'asset_id': asset, 'revision': body['output_sha256'], 'revision_number': number}
            return httpx.Response(200, json=self.receipts[(run, role)])
        if op == 'applications/result-history':
            return httpx.Response(200, json={'revisions': [{'number': n, 'revision': r, 'by': None, 'published_at': None}
                                                           for n, r in self.history.get(body['asset_id'], [])], 'display': {'member_names': {}}})
        return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'No such route here.', 'request_id': 'r-3'})

    def ops(self): return [s['op'] for s in self.seen]
    def proposed(self): return [s['body'] for s in self.seen if s['op'] == 'agents/propose']
    def derived(self, role=None): return [s for s in self.seen if s['op'] == 'publications/derive' and role in (None, s['body']['run']['role'])]


def agent(gateway): return AgentClient(URL, 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(gateway)))


def run_folder(tmp_path, roles=('shifted',), profile='well-tops-csv/1', raw=None):
    run = tmp_path / 'run'
    run.mkdir()
    outputs = {}
    for role in roles:
        data = (raw or {}).get(role, RAW[role])
        (run / ('%s.csv' % role)).write_bytes(data)
        outputs[role] = {'file': '%s.csv' % role, 'sha256': sha(data), 'profile': profile, 'declared': {'depth_unit': 'm'}}
    (run / 'run.json').write_text(json.dumps({'schema': LOCAL_RUN, 'procedure': {'name': 'depth-shift', 'version': 1, 'digest': 'd' * 64, 'rules_version': '1.3.0'},
                                              'settings': {'shift': 2.5}, 'inputs': {'tops': [{'asset_id': 'a-tops', 'revision': TOPS, 'kind': 'well-tops-csv/1'}]},
                                              'systems': {}, 'outputs': outputs, 'runner': 'this computer'}))
    return run


def held_entry(asset, name, revision, number, kind='derived'):
    return {'asset_id': asset, 'name': name, 'kind': kind, 'revision': revision, 'number': number, 'output': None}


def work(tmp_path, *extra):
    """A folder holding the run's input (Chalk tops at the version the run read) and the earlier result at version 2."""
    folder = tmp_path / 'work'
    folder.mkdir()
    items = {e['asset_id']: e for e in (held_entry('a-tops', 'Chalk tops', TOPS, 1), held_entry('a-prev', 'Shifted tops', PREV, 2), *extra)}
    (folder / 'held.json').write_text(json.dumps({'schema': exchange.SCHEMA, 'url': URL, 'project': 'p', 'holder_id': 'h' * 32, 'items': items,
                                                  'seen': sorted(items), 'pending': None}))
    return folder


def record(folder): return json.loads((folder / 'held.json').read_text())


def refused(code, call):
    with pytest.raises(AGENT_REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code and str(caught.value) == caught.value.sentence
    return caught.value


def report_request(command, publish, roles=('shifted',), raw=None):
    data = {r: (raw or {}).get(r, RAW[r]) for r in roles}
    return {'project_id': 'p', 'command_id': command, 'procedure': {'digest': 'd' * 64}, 'settings': {'shift': 2.5},
            'inputs': {'tops': [{'asset_id': 'a-tops', 'revision': TOPS}]},
            'outputs': [{'role': r, 'sha256': sha(data[r]), 'bytes': len(data[r]), 'declared': {'depth_unit': 'm'}} for r in roles], 'publish': publish}


def command(run): return json.loads((run / 'agent-run.json').read_text())['command_id']


# -- (e)-(g): only the report, then each output under it ---------------------------------------------------------------

def test_a_new_result_is_sent_as_the_report_and_its_one_derive(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    done = agent(gateway).exchange(folder).send_run(run, name='Shifted tops')
    assert isinstance(done, Outcome) and done.outcome == 'sent-run'
    assert done.sentence == 'Sent Shifted tops as a new item; it is private until you share it.'
    c = command(run)
    assert gateway.ops() == ['capabilities/describe', 'agents/propose', 'agents/status', 'procedure-runs/report', 'procedures/get', 'publications/derive']
    [proposed] = gateway.proposed()
    assert proposed['operation'] == 'procedure-runs/report' and proposed['request'] == report_request(c, {'shifted': {'name': 'Shifted tops'}})
    [derive] = gateway.derived()
    assert derive['plan'] == sha(canonical(proposed['request']).encode())  # sent under the report's plan
    assert {k: derive['body'][k] for k in ('name', 'derived_from', 'run')} == {'name': 'Shifted tops', 'derived_from': [{'asset_id': 'a-tops', 'revision': TOPS}],
                                                                            'run': {'id': 'run-' + c[-6:], 'role': 'shifted'}}
    assert 'new_version_of' not in derive['body'] and derive['raw'] == RAW['shifted']
    assert done.technical == {'plan': derive['plan'], 'run_id': 'run-' + c[-6:],
                              'outputs': [{'role': 'shifted', 'asset_id': 'a-new-shifted', 'revision': sha(RAW['shifted']), 'number': 1}]}
    held = record(folder)
    assert held['pending'] is None
    assert {k: v for k, v in held['items']['a-new-shifted'].items() if k != 'got_at'} == {
        'asset_id': 'a-new-shifted', 'name': 'Shifted tops', 'kind': 'derived', 'revision': sha(RAW['shifted']), 'number': 1, 'sent': True, 'output': None, 'note': None}


def test_a_new_version_is_based_on_the_held_version(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    done = agent(gateway).exchange(folder).send_run(run, name='Shifted tops', of='a-prev', expected=PREV)
    assert (done.outcome, done.sentence) == ('sent-run', 'Sent Shifted tops as version 3. Version 2 is kept.')
    [proposed] = gateway.proposed()
    assert proposed['request']['publish'] == {'shifted': {'name': 'Shifted tops', 'new_version_of': 'a-prev', 'expected_parent': PREV}}
    [derive] = gateway.derived()
    assert (derive['body']['new_version_of'], derive['body']['expected_parent']) == ('a-prev', PREV)
    assert record(folder)['items']['a-prev']['revision'] == sha(RAW['shifted']) and record(folder)['items']['a-prev']['number'] == 3


# -- (c): bound to what the folder holds; refusals before anything is sent ---------------------------------------------

@pytest.mark.parametrize('tops', [None, held_entry('a-tops', 'Chalk tops', 'x' * 64, 2)])
def test_an_input_not_held_at_the_version_the_run_read_is_refused_with_nothing_sent(tmp_path, tops):
    """Mutation: the held-input check removed -> the spy sees the proposal."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    held = record(folder)
    if tops is None: del held['items']['a-tops']
    else: held['items']['a-tops'] = tops
    (folder / 'held.json').write_text(json.dumps(held))
    error = refused('not-held', lambda: agent(gateway).exchange(folder).send_run(run, name='Shifted tops'))
    assert error.sentence == 'You can only build on items you hold. Get %s first.' % ('that item' if tops is None else 'Chalk tops')
    assert gateway.seen == [] and record(folder)['pending'] is None and not (run / 'agent-run.json').exists()


def test_a_moved_expectation_and_unchanged_bytes_are_refused_before_anything_is_sent(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    ex = agent(gateway).exchange(folder)
    error = refused('newer-version-exists', lambda: ex.send_run(run, name='Shifted tops', of='a-prev', expected=OLD))
    assert error.sentence == 'A newer version was added first. Your change was not sent. Either get the latest version and look at it, or send yours as a new item.'
    (tmp_path / 'same').mkdir()
    same = run_folder(tmp_path / 'same', raw={'shifted': b'v2'})
    held = record(folder); held['items']['a-prev']['revision'] = sha(b'v2'); (folder / 'held.json').write_text(json.dumps(held))
    error = refused('nothing-changed', lambda: ex.send_run(same, name='Shifted tops', of='a-prev', expected=sha(b'v2')))
    assert error.sentence == 'This is the same as version 2; nothing was sent.'
    assert gateway.seen == [] and record(folder)['pending'] is None


@pytest.mark.parametrize('raw, head, code, sentence', [
    (RAW['shifted'], HEAD, 'newer-version-exists', NEWER),
    (b'name,md\nTop Chalk,1001\n', None, 'earlier-version', 'This content was version 1.'),
    (b'name,md\nTop Chalk,1009\n', 'same', 'nothing-changed', 'This is the same as version 3; nothing was sent.')])
def test_a_stale_parent_after_the_approval_answers_what_history_says(tmp_path, raw, head, code, sentence):
    """After a 409 at the step: someone added version 3 (whose content may be this output's), or the output is an
    earlier version's content. Mutation: the step's 409 mapped to not-valid -> red."""
    gateway, run, folder = Gateway(), run_folder(tmp_path, raw={'shifted': raw}), work(tmp_path)
    if head is None: gateway.history['a-prev'] = [(1, sha(raw)), (2, PREV)]
    gateway.answer = 'pending'
    ex = agent(gateway).exchange(folder)
    assert ex.send_run(run, name='Shifted tops', of='a-prev', expected=PREV, wait=False).outcome == 'proposed'
    if head is not None: gateway.history['a-prev'].append((3, HEAD if head == HEAD else sha(raw)))  # the owner publishes after the proposal
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'approved'
    error = refused(code, lambda: ex.send_run(run, name='Shifted tops', of='a-prev', expected=PREV))
    assert error.sentence == sentence
    kept = record(folder)['pending']
    assert kept['refused'] == {'role': 'shifted', 'outcome': code} and kept['receipts'] == {}
    assert gateway.history['a-prev'][-1][1] != sha(raw) or head == 'same'


# -- (a): uploads are not sent ------------------------------------------------------------------------------------------

def test_an_output_that_is_not_a_result_and_an_uploaded_item_ask_for_an_upload(tmp_path):
    gateway, folder = Gateway(), work(tmp_path, held_entry('a-file', 'Well report', 'u' * 64, 1, kind='uploaded'))
    error = refused('upload-needed', lambda: agent(gateway).exchange(folder).send_run(run_folder(tmp_path, profile='segy-rev1/1'), name='Shifted tops'))
    assert error.sentence == 'shifted.csv is a file to upload, not a result; an assistant does not send uploads. Nothing was sent.'
    (tmp_path / 'b').mkdir()
    other = run_folder(tmp_path / 'b')
    error = refused('upload-needed', lambda: agent(gateway).exchange(folder).send_run(other, name='Shifted tops', of='a-file', expected='u' * 64))
    assert error.sentence == 'Well report is a file to upload, not a result; an assistant does not send uploads. Nothing was sent.'
    assert gateway.seen == []


# The comparison of DERIVE_PROFILES with the gateway's is tests/gateway/test_agent_exchange_profiles.py (it reads the Platform).


# -- several outputs: names, a partial send, its repeat -----------------------------------------------------------------

def test_several_outputs_are_named_by_the_manifest_labels_never_by_role(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path, roles=('shifted', 'moved')), work(tmp_path)
    done = agent(gateway).exchange(folder).send_run(run, name='Chalk tops')
    [proposed] = gateway.proposed()
    assert proposed['request']['publish'] == {'shifted': {'name': 'Chalk tops: Shifted tops'}, 'moved': {'name': 'Chalk tops: Moved tops'}}
    assert done.sentence == ('Sent Chalk tops: Shifted tops as a new item; it is private until you share it. '
                             'Sent Chalk tops: Moved tops as a new item; it is private until you share it.')
    assert not any(' shifted' in s or ' moved' in s for s in (done.sentence, *proposed['request']['publish']['shifted'].values()))
    (tmp_path / 'n').mkdir()
    named = agent(Gateway()).exchange(work(tmp_path / 'n'))
    assert named.send_run(run_folder(tmp_path / 'n', roles=('shifted', 'moved')), name={'shifted': 'Up', 'moved': 'Down'}).sentence.startswith('Sent Up as a new item')


def test_a_partial_send_keeps_what_landed_and_a_repeat_retries_only_the_rest(tmp_path):
    """Two outputs: the first publishes, the second meets a moved parent, then (repeated) an unverified tool. Mutation:
    receipts saved only after the loop -> the first output's receipt is missing from held.json after the refusal."""
    gateway, run, folder = Gateway(), run_folder(tmp_path, roles=('shifted', 'moved')), work(tmp_path)
    gateway.answer = 'pending'
    ex = agent(gateway).exchange(folder)
    ex.send_run(run, name='Chalk tops', of={'moved': 'a-prev'}, expected={'moved': PREV}, wait=False)
    gateway.history['a-prev'].append((3, HEAD))
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'approved'
    error = refused('sent-part', lambda: ex.send_run(run, name='Chalk tops', of={'moved': 'a-prev'}, expected={'moved': PREV}))
    assert error.sentence == 'Sent Chalk tops: Shifted tops as a new item; it is private until you share it. Chalk tops: Moved tops was not sent: ' + NEWER
    assert isinstance(error, exchange.IntegrityConflict)
    kept = record(folder)
    assert kept['pending']['receipts'] == {'shifted': {'asset_id': 'a-new-shifted', 'revision': sha(RAW['shifted']), 'number': 1}}
    assert kept['pending']['refused'] == {'role': 'moved', 'outcome': 'newer-version-exists'}
    assert kept['items']['a-new-shifted']['revision'] == sha(RAW['shifted']) and kept['items']['a-prev']['revision'] == PREV
    assert gateway.history['a-prev'] == [(1, OLD), (2, PREV), (3, HEAD)]
    first = [s['body'] for s in gateway.derived('moved')]
    gateway.refuse['moved'] = 'not-verified'
    error = refused('sent-part', lambda: ex.send_run(run, name='Chalk tops', of={'moved': 'a-prev'}, expected={'moved': PREV}))
    assert error.sentence.endswith('Chalk tops: Moved tops was not sent: The tool version this run names is not verified.')
    assert len(gateway.proposed()) == 1 and len(gateway.derived('shifted')) == 1  # the same plan; the first output never sent twice
    assert [s['body'] for s in gateway.derived('moved')] == first * 2  # the same step, unchanged
    assert record(folder)['pending']['refused'] == {'role': 'moved', 'outcome': 'tool-run-refused'}


# -- lost answers, a rebuilt process, timeout and expiry ------------------------------------------------------------------

def test_a_lost_proposal_answer_is_the_same_plan_on_repeat(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.lose.add('agents/propose')
    ex = agent(gateway).exchange(folder)
    error = refused('outcome-unknown', lambda: ex.send_run(run, name='Shifted tops'))
    assert error.technical['command_id'] == command(run) and record(folder)['pending']['plan'] is None
    assert ex.send_run(run, name='Shifted tops').outcome == 'sent-run'
    first, second = gateway.proposed()
    assert first == second and len(gateway.plans) == 1


def test_a_lost_answer_after_the_first_output_publishes_nothing_twice(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path, roles=('shifted', 'moved')), work(tmp_path)
    gateway.lose.add('derive:shifted')
    ex = agent(gateway).exchange(folder)
    refused('outcome-unknown', lambda: ex.send_run(run, name='Chalk tops'))
    assert record(folder)['pending']['receipts'] == {}
    done = ex.send_run(run, name='Chalk tops')
    assert done.outcome == 'sent-run' and len(gateway.derived('shifted')) == 1 and len(gateway.derived('moved')) == 1
    assert [o['number'] for o in done.technical['outputs']] == [1, 1] and len(gateway.history['a-new-shifted']) == 1


def test_a_rebuilt_process_continues_from_the_folder_and_another_agent_is_refused(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer = 'pending'
    proposed = agent(gateway).exchange(folder).send_run(run, name='Shifted tops', wait=False)
    assert (proposed.outcome, proposed.sentence) == ('proposed', 'Waiting for approval to send Shifted tops. Nothing is published until it is approved; '
                                                                 'run the same send again to continue.')
    assert proposed.facts == {'name': 'Shifted tops'} and proposed.technical == {'plan': next(iter(gateway.plans)), 'command_id': command(run)}
    other = Gateway(agent_id='agent-8'); other.plans, other.history = gateway.plans, gateway.history
    error = refused('outcome-unknown', lambda: agent(other).exchange(folder).send_run(run, name='Shifted tops'))
    assert error.facts == {'name': 'Shifted tops', 'other_key': True}
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'approved'
    done = AgentExchange(agent(gateway).exchange(folder).transport, folder).send_run(run, name='Shifted tops')  # a new process: new client, new exchange
    assert done.outcome == 'sent-run' and len(gateway.proposed()) == 1


def test_a_timeout_keeps_the_command_and_a_definitive_end_starts_afresh(tmp_path):
    """Mutation: the command id kept after expiry (no fresh attempt) -> the next send proposes the old hash."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer = 'pending'
    ex = agent(gateway).exchange(folder)
    ticks = iter(range(100))
    assert ex.send_run(run, name='Shifted tops', timeout=1, interval=0, clock=lambda: next(ticks), sleep=lambda _: None).outcome == 'proposed'
    c1 = command(run)
    assert ex.send_run(run, name='Shifted tops', wait=False).technical['command_id'] == c1 and len(gateway.plans) == 1
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'expired'
    error = refused('expired', lambda: ex.send_run(run, name='Shifted tops'))
    assert error.sentence == 'The approval to send Shifted tops expired. Nothing was published; send it again to ask again.'
    assert record(folder)['pending'] is None and record(folder)['closed_runs'] == [c1]
    again = ex.send_run(run, name='Shifted tops', wait=False)
    c2 = command(run)
    assert c2 != c1 and again.technical['command_id'] == c2 and len(gateway.plans) == 2
    gateway.plans[again.technical['plan']]['state'] = 'declined'
    error = refused('declined', lambda: ex.send_run(run, name='Shifted tops'))
    assert error.sentence == 'The send of Shifted tops was declined. Nothing was published.'
    gateway.answer = 'approved'
    assert ex.send_run(run, name='Shifted tops').outcome == 'sent-run' and command(run) not in (c1, c2) and len(gateway.plans) == 3
    [derive] = gateway.derived()  # one derive, under the third plan
    assert derive['plan'] == [p for p in gateway.plans][-1]


# -- what may change after the first send ------------------------------------------------------------------------------

def test_changed_arguments_changed_bytes_and_advanced_inputs(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer = 'pending'
    ex = agent(gateway).exchange(folder)
    ex.send_run(run, name='Shifted tops', of='a-prev', expected=PREV, wait=False)
    error = refused('not-valid', lambda: ex.send_run(run, name='Other tops', of='a-prev', expected=PREV))
    assert error.facts == {'reasons': 'an earlier send from this folder is unfinished: run it again unchanged, or set it aside'}
    (run / 'shifted.csv').write_bytes(b'name,md\nTop Chalk,1\n')
    with pytest.raises(NotRun) as caught: ex.send_run(run, name='Shifted tops', of='a-prev', expected=PREV)
    assert caught.value.code == 'output-changed' and str(caught.value) == 'Not published: shifted.csv changed after the run; run it again.'
    assert record(folder)['pending']['request']['name'] == 'Shifted tops'
    (run / 'shifted.csv').write_bytes(RAW['shifted'])
    held = record(folder)  # a get advanced the folder after the proposal: the send continues from what it froze
    held['items']['a-prev'].update(revision=HEAD, number=3); held['items']['a-tops'].update(revision='n' * 64, number=2)
    (folder / 'held.json').write_text(json.dumps(held))
    gateway.history['a-prev'] = [(1, OLD), (2, PREV)]
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'approved'
    done = ex.send_run(run, name='Shifted tops', of='a-prev', expected=PREV)
    assert done.outcome == 'sent-run' and len(gateway.proposed()) == 1
    [derive] = gateway.derived()
    assert derive['body']['expected_parent'] == PREV and derive['body']['derived_from'] == [{'asset_id': 'a-tops', 'revision': TOPS}]


def test_a_persons_send_over_a_run_pending_meets_the_owner_check_and_abandon_clears_it(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer = 'pending'
    agent(gateway).exchange(folder).send_run(run, name='Shifted tops', wait=False)
    person = Client(URL, 'p', credential=Credential('person-token'), http=httpx.Client(transport=httpx.MockTransport(gateway)))
    seen = len(gateway.seen)
    with pytest.raises(exchange.OutcomeUnknown) as caught:
        Exchange(ClientTransport(person), folder).send(RAW['shifted'], name='Shifted tops', profile='well-tops-csv/1', how='by hand', based_on=['a-tops'])
    assert caught.value.facts == {'name': 'Shifted tops', 'other_key': True} and len(gateway.seen) == seen
    gone = Exchange(ClientTransport(person), folder).abandon_pending()
    assert (gone.outcome, gone.technical) == ('abandoned', {'command_id': command(run)}) and record(folder)['pending'] is None


# -- E166's words, the dry run --------------------------------------------------------------------------------------------

@pytest.mark.parametrize('reason', list(TOOL_RUN_SENTENCES))
def test_a_tool_run_refusal_passes_the_gateways_sentence_through(tmp_path, reason):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.refuse['report'] = reason
    error = refused('tool-run-refused', lambda: agent(gateway).exchange(folder).send_run(run, name='Shifted tops'))
    assert error.sentence == TOOL_RUN_SENTENCES[reason].format(delegator='Bob Example') and error.technical['reason'] == reason
    assert record(folder)['pending'] is None  # cleared at the report


def test_a_dry_run_answers_the_reports_dry_run_and_saves_nothing(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    seen = agent(gateway).exchange(folder).send_run(run, name='Shifted tops', dry_run=True)
    assert isinstance(seen, DryRun) and seen.would.outcome == 'proceeds'
    assert record(folder)['pending'] is None and 'agents/propose' not in gateway.ops()
    [asked] = [s['body'] for s in gateway.seen if s['op'] == 'procedure-runs/report']
    assert asked == {**report_request(command(run), {'shifted': {'name': 'Shifted tops'}}), 'dry_run': True}


# -- E155 s2 C2: of_entity, read once and frozen ----------------------------------------------------------------------------

WELLBORE = {'kind': 'wellbore', 'entity_id': 'wb-1'}


def test_of_entity_is_read_once_and_sent_with_the_report_and_its_derive(tmp_path):
    """The kind is the one entities/get answers. Mutation: no entities/get (a kind assumed) → the literal call list and
    the well's kind differ."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.entities = {'wb-1': 'well'}
    done = agent(gateway).exchange(folder).send_run(run, name='Shifted tops', of_entity='wb-1')
    assert done.outcome == 'sent-run'
    assert gateway.ops() == ['capabilities/describe', 'entities/get', 'agents/propose', 'agents/status', 'procedure-runs/report', 'procedures/get', 'publications/derive']
    [proposed] = gateway.proposed()
    assert proposed['request'] == report_request(command(run), {'shifted': {'name': 'Shifted tops', 'of_entity': {'kind': 'well', 'entity_id': 'wb-1'}}})
    assert gateway.derived()[0]['body']['of_entity'] == {'kind': 'well', 'entity_id': 'wb-1'}


def test_a_resumed_send_reads_no_entity_again_and_sends_what_it_froze(tmp_path):
    """M6: the entity answers another kind after the proposal. Mutation: read again on resume → a second entities/get
    and the derive names a well."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer, gateway.entities = 'pending', {'wb-1': 'wellbore'}
    ex = agent(gateway).exchange(folder)
    assert ex.send_run(run, name='Shifted tops', of_entity='wb-1', wait=False).outcome == 'proposed'
    assert record(folder)['pending']['resolved']['of_entity'] == {'shifted': WELLBORE}
    gateway.entities['wb-1'] = 'well'
    [plan] = gateway.plans; gateway.plans[plan]['state'] = 'approved'
    assert ex.send_run(run, name='Shifted tops', of_entity='wb-1').outcome == 'sent-run'
    assert gateway.ops().count('entities/get') == 1 and len(gateway.proposed()) == 1
    assert gateway.proposed()[0]['request']['publish']['shifted']['of_entity'] == WELLBORE == gateway.derived()[0]['body']['of_entity']


def test_a_mapping_by_output_an_omitted_role_and_one_entity_for_two_roles(tmp_path):
    """Mutation: entities read per role, not per id → two entities/get for one well."""
    gateway, run, folder = Gateway(), run_folder(tmp_path, roles=('shifted', 'moved')), work(tmp_path)
    gateway.entities = {'wb-1': 'wellbore'}
    agent(gateway).exchange(folder).send_run(run, name='Chalk tops', of_entity={'shifted': 'wb-1', 'moved': 'wb-1'})
    assert gateway.ops().count('entities/get') == 1
    assert {r: e['of_entity'] for r, e in gateway.proposed()[0]['request']['publish'].items()} == {'shifted': WELLBORE, 'moved': WELLBORE}
    (tmp_path / 'o').mkdir()
    gateway, run, folder = Gateway(), run_folder(tmp_path / 'o', roles=('shifted', 'moved')), work(tmp_path / 'o')
    gateway.entities = {'wb-1': 'wellbore'}
    agent(gateway).exchange(folder).send_run(run, name='Chalk tops', of_entity={'shifted': 'wb-1'})
    publish = gateway.proposed()[0]['request']['publish']
    assert publish['shifted']['of_entity'] == WELLBORE and 'of_entity' not in publish['moved']
    assert {d['body']['run']['role']: d['body'].get('of_entity') for d in gateway.derived()} == {'shifted': WELLBORE, 'moved': None}
    (tmp_path / 'p').mkdir()
    ex = agent(Gateway()).exchange(work(tmp_path / 'p'))
    error = refused('not-valid', lambda: ex.send_run(run, name='Chalk tops', of_entity='wb-1'))  # several outputs: an id per output
    assert error.facts == {'reasons': 'give the well or wellbore by output when the run made several'}


def test_another_entity_on_a_pending_send_is_unfinished(tmp_path):
    """Mutation: of_entity left out of `asked` → the pending send continues with the first entity."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.answer, gateway.entities = 'pending', {'wb-1': 'wellbore', 'wb-2': 'wellbore'}
    ex = agent(gateway).exchange(folder)
    ex.send_run(run, name='Shifted tops', of_entity='wb-1', wait=False)
    for other in ('wb-2', None):
        error = refused('not-valid', lambda: ex.send_run(run, name='Shifted tops', of_entity=other, wait=False))
        assert error.facts == {'reasons': 'an earlier send from this folder is unfinished: run it again unchanged, or set it aside'}


def test_a_missing_entity_is_refused_before_anything_is_proposed(tmp_path):
    """Mutation: the entity read after the proposal → the spy sees agents/propose."""
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    error = refused('not-valid', lambda: agent(gateway).exchange(folder).send_run(run, name='Shifted tops', of_entity='wb-gone'))
    assert error.facts == {'reasons': 'name a well or wellbore you can read in this project'} and error.technical['entity_id'] == 'wb-gone'
    assert 'agents/propose' not in gateway.ops() and record(folder)['pending'] is None


def test_a_dry_run_carries_the_entity(tmp_path):
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    gateway.entities = {'wb-1': 'wellbore'}
    agent(gateway).exchange(folder).send_run(run, name='Shifted tops', of_entity='wb-1', dry_run=True)
    [asked] = [s['body'] for s in gateway.seen if s['op'] == 'procedure-runs/report']
    assert asked == {**report_request(command(run), {'shifted': {'name': 'Shifted tops', 'of_entity': WELLBORE}}), 'dry_run': True}
