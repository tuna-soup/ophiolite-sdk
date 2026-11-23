"""E184 s0a C2: the exchange core checks a transfer receipt, returns it on the outcome and says whether the project kept
it (strategy E184-s0-transfer-receipt, rev 2 closed, D-3, D-5, D-6, D-7; tests T4, T5, T5b, T6, T6b, T7). The receipts
and the code document are the contract snapshot's (`ophiolite/contracts`); the project is tests/helpers/exchange_fake.py
with a recording `publish` and `report`. Each test names the mutation it catches."""
import base64
import copy
import importlib.util
import json
from importlib.resources import files
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite import publish as planning
from ophiolite.errors import Refused, ValidationFailed
from ophiolite.exchange import ClientTransport, Exchange, NotValid, Outcome

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha
CONTRACTS = files('ophiolite').joinpath('contracts')
VALID = CONTRACTS.joinpath('exchange/v1/fixtures/valid')
CASES = json.loads(CONTRACTS.joinpath('exchange/v1/fixtures/invalid/transfer-receipt-cases.json').read_text())
CODES = json.loads(CONTRACTS.joinpath('connectors/v1/transfer-codes.json').read_text())
UNLISTED = 'This transfer would report a change its route does not declare, so nothing was done.'
SHAPE = 'This transfer\'s receipt is not well formed, so nothing was done.'
NOT_KEPT = ' This project did not keep the lists; they are on your screen only.'
UNCONFIRMED = ' It is not known whether the project kept the lists.'
V1, V2 = b'porosity v1', b'porosity v2'


def valid(name):
    return json.loads(VALID.joinpath(name).read_text())


def changed(case):
    instance = valid(case['document'])
    for path, value in case.get('set', []):
        target = instance
        for key in path[:-1]: target = target[key]
        target[path[-1]] = copy.deepcopy(value)
    for path, value in case.get('append', []):
        target = instance
        for key in path: target = target[key]
        target.append(copy.deepcopy(value))
    return instance


# --- T4: the core's verdicts --------------------------------------------------------------------------------------

def test_the_sentences_are_the_strategy_literals():
    assert (exchange.UNLISTED, exchange.SHAPE, exchange.NOT_KEPT, exchange.UNCONFIRMED) == (UNLISTED, SHAPE, NOT_KEPT, UNCONFIRMED)


@pytest.mark.parametrize('name', ['transfer-receipt-horizon-send-planned.json', 'transfer-receipt-horizon-send-committed.json',
                                  'transfer-receipt-horizon-get-committed.json', 'transfer-receipt-qgis-read-planned.json'])
def test_the_route_fixtures_pass(name):
    assert exchange.receipt_problem(valid(name), CODES) is None


def test_the_largest_receipt_has_the_shape_and_no_route():
    """The contract takes it (2,048 bytes); its codes are no route's, so the core refuses it as unlisted."""
    doc = valid('transfer-receipt-max.json')
    assert exchange._receipt_shape(doc) is None and len(exchange.receipt_bytes(doc)) == 2048
    assert exchange.receipt_problem(doc, CODES) == (UNLISTED, {'code': 'kept-1', 'list': 'kept'})


@pytest.mark.parametrize('case', CASES['schema'] + CASES['model'], ids=lambda c: c['name'])
def test_the_core_refuses_every_contract_case_as_shape(case):
    """Mutation: drop a rule from `_receipt_shape` (maxItems, a length, planned/made, the byte ceiling) -> its case passes."""
    sentence, technical = exchange.receipt_problem(changed(case), CODES)
    assert (sentence, technical['reason']) == (SHAPE, 'contract')


@pytest.mark.parametrize('case', CASES['codes'], ids=lambda c: c['name'])
def test_the_core_refuses_every_code_case_with_its_literal(case):
    """Mutation: accept a `changed` code listed only under `kept` -> wrong-list returns None."""
    assert exchange.receipt_problem(changed(case), CODES) == ({'UNLISTED': UNLISTED, 'SHAPE': SHAPE}[case['refusal']], case['technical'])


def test_a_bool_is_not_a_count_and_no_code_document_refuses():
    receipt = valid('transfer-receipt-horizon-send-planned.json')
    receipt['changed'][1]['count'] = True
    assert exchange.receipt_problem(receipt, CODES) == (SHAPE, {'reason': 'contract', 'error': 'changed'})
    assert exchange.receipt_problem(valid('transfer-receipt-horizon-send-planned.json'), None) == (SHAPE, {'reason': 'codes-version', 'version': '1.0.0'})


# --- E184 s1 T4b: the core's verdicts against code document 1.1.0 are the gateway's (test_transfer_receipt_contract) --

CODES_11 = json.loads(CONTRACTS.joinpath('connectors/v1/transfer-codes/1.1.0.json').read_text())


def as_11(case):
    """A code case with its receipt at 1.1.0; the codes-version case (it names 1.1.0, now kept) names 1.2.0."""
    instance, technical = changed(case), case['technical']
    version = '1.2.0' if technical.get('reason') == 'codes-version' else '1.1.0'
    instance['codes'] = {'id': 'ophiolite.transfer-codes/1', 'version': version}
    return instance, (dict(technical, version='1.2.0') if version == '1.2.0' else technical)


@pytest.mark.parametrize('case', CASES['codes'], ids=lambda c: c['name'])
def test_e184s1_the_core_refuses_every_code_case_of_1_1_0_with_its_literal(case):
    instance, technical = as_11(case)
    assert exchange.receipt_problem(instance, CODES_11) == ({'UNLISTED': UNLISTED, 'SHAPE': SHAPE}[case['refusal']], technical)


def test_e184s1_the_log_fixture_passes_1_1_0_only():
    """The hand log receipt (1.1.0) passes its own document; against 1.0.0 it is codes-version, and at 1.0.0 its route
    is none of 1.0.0's. Mutation: receipt_problem not comparing the version -> the 1.0.0 verdict is `route`."""
    log = valid('transfer-receipt-log-get-committed.json')
    assert exchange.receipt_problem(log, CODES_11) is None
    assert exchange.receipt_problem(log, CODES) == (SHAPE, {'reason': 'codes-version', 'version': '1.1.0'})
    at_10 = dict(log, codes={'id': 'ophiolite.transfer-codes/1', 'version': '1.0.0'})
    assert exchange.receipt_problem(at_10, CODES)[1]['reason'] == 'route'
    for name in ('transfer-receipt-horizon-send-planned.json', 'transfer-receipt-horizon-get-committed.json'):
        assert exchange.receipt_problem(dict(valid(name), codes={'id': 'ophiolite.transfer-codes/1', 'version': '1.1.0'}), CODES_11) is None


# --- T5 and T5b: the outcome and the lines ------------------------------------------------------------------------

def test_an_outcome_without_a_receipt_is_the_answer_it_was():
    """Mutation: always emit 'receipt': None -> the bytes differ from the literal written before C2."""
    said = Outcome('sent-new', 'Sent Porosity as a new item; it is private until you share it.', {'name': 'Porosity'}, {'asset_id': 'a'})
    assert json.dumps(said.to_dict()) == ('{"outcome": "sent-new", "sentence": "Sent Porosity as a new item; it is private until you share it.", '
                                          '"facts": {"name": "Porosity"}, "technical": {"asset_id": "a"}}')
    receipt = valid('transfer-receipt-horizon-send-planned.json')
    assert Outcome('sent-new', 's', receipt=receipt).to_dict()['receipt'] == receipt


def test_the_lines_say_nothing_for_an_empty_list_and_no_code():
    """Mutation: print 0 or the code -> the literal differs."""
    receipt = valid('transfer-receipt-horizon-get-committed.json')
    assert exchange.receipt_lines(receipt) == [
        'Kept:', "  Nodes on the survey's grid, written as a new horizon beside yours: 16", '  The coordinate system, EPSG:32631',
        'Changed:', '  Points without a height, which become nodes without a value: 1',
        "  Values that move by up to half of OpendTect's Z step for their inline: 7",
        'Not carried:', '  nothing']
    planned = valid('transfer-receipt-horizon-send-planned.json')
    text = '\n'.join(exchange.receipt_lines(planned))
    assert 'Z as OpendTect stores it, in milliseconds of two-way time, positive down, below SRD' in text  # no count: no number
    assert not any(row['code'] in text for name in ('kept', 'changed', 'not_carried') for row in planned[name])
    assert 'points-csv/1' not in text and 'Syn_Survey' not in text


# --- T6: a send carries the receipt only to a project that keeps it -----------------------------------------------

class Keeping(Fake):
    """The fake project; `kept` is the codes versions its capabilities list (None: an older project, no method)."""
    def __init__(self, kept=None):
        super().__init__()
        self.receipts, self.reports, self.refuse = [], [], []
        if kept is not None: self.keeps_receipts = lambda version: version in kept

    def publish(self, data, request, resolved, command_id, attribution=None, receipt=None):
        self.receipts.append(receipt)
        return Fake.publish(self, data, request, resolved, command_id, attribution)

    def report(self, reference, holder_id, event_id, **held):
        self.reports.append(held)
        if self.refuse: raise self.refuse.pop(0)


def send(tmp_path, project, receipt):
    project.add('poro', V1, name='Porosity')
    ex = Exchange(project, tmp_path / 'work', codes=CODES)
    ex.get('poro')
    return ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro', receipt=receipt)


@pytest.mark.parametrize('kept', [None, ['9.9.9']])
def test_a_project_that_does_not_keep_this_version_gets_no_receipt_and_the_outcome_says_so(tmp_path, kept):
    """Mutation: send the receipt whenever present -> the project records it."""
    project, receipt = Keeping(kept), valid('transfer-receipt-horizon-send-planned.json')
    done = send(tmp_path, project, receipt)
    assert project.receipts == [None]
    assert done.sentence == 'Sent Porosity as version 2. Version 1 is kept.' + NOT_KEPT
    assert done.receipt == receipt


def test_a_project_that_keeps_it_gets_the_receipt_byte_for_byte(tmp_path):
    project, receipt = Keeping(['1.0.0']), valid('transfer-receipt-horizon-send-planned.json')
    done = send(tmp_path, project, receipt)
    assert [exchange.receipt_bytes(r) for r in project.receipts] == [exchange.receipt_bytes(receipt)]
    assert (done.sentence, done.to_dict()['receipt']) == ('Sent Porosity as version 2. Version 1 is kept.', receipt)


def test_a_send_without_a_receipt_sends_none_and_says_nothing_more(tmp_path):
    project = Keeping(['1.0.0'])
    done = send(tmp_path, project, None)
    assert project.receipts == [None] and done.sentence == 'Sent Porosity as version 2. Version 1 is kept.' and 'receipt' not in done.to_dict()


def test_a_retry_of_an_unfinished_send_carries_the_saved_receipt(tmp_path):
    """B-D2: recovery never recomputes. Mutation: the retry sends the receipt it was given now."""
    project, first = Keeping(['1.0.0']), valid('transfer-receipt-horizon-send-planned.json')
    project.add('poro', V1, name='Porosity')
    ex = Exchange(project, tmp_path / 'work', codes=CODES)
    ex.get('poro')
    arguments = dict(name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro')
    project.fail = {'publish': ConnectionError('the network went away')}
    with pytest.raises(exchange.OutcomeUnknown): ex.send(V2, receipt=first, **arguments)
    assert json.loads(ex.path.read_text())['pending']['receipt'] == first
    later = copy.deepcopy(first)
    later['kept'][0].update(count=17, sentence="Nodes of the horizon's grid, at the survey's positions: 17")
    assert exchange.receipt_problem(later, CODES) is None
    project.fail = {}
    done = ex.send(V2, receipt=later, **arguments)
    assert project.receipts == [first, first] and done.receipt == first
    assert json.loads(ex.path.read_text())['pending'] is None


def test_a_receipt_the_core_refuses_stops_the_send_before_any_request(tmp_path):
    """T7: receipt-over is refused with SHAPE before anything is sent. Mutation: check after publish."""
    project = Keeping(['1.0.0'])
    over = changed(next(c for c in CASES['model'] if c['name'] == 'over'))
    with pytest.raises(NotValid) as refused: send(tmp_path, project, over)
    assert (str(refused.value), refused.value.technical['reason']) == (SHAPE, 'contract')
    assert project.receipts == [] and not any(call[0] == 'publish' for call in project.calls)
    unlisted = changed(next(c for c in CASES['codes'] if c['name'] == 'unlisted'))
    with pytest.raises(NotValid) as refused: Exchange(project, tmp_path / 'work', codes=CODES).send(
            V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro', receipt=unlisted)
    assert (str(refused.value), refused.value.technical) == (UNLISTED, {'code': 'z-step', 'list': 'changed'})


# --- T6b: a get's report says whether the project kept the receipt ------------------------------------------------

def got(tmp_path, project, receipt):
    project.add('poro', V1, name='Porosity')
    ex = Exchange(project, tmp_path / 'work', codes=CODES)
    return ex.fetch('poro').confirm(receipt=receipt)


GET = 'transfer-receipt-horizon-get-committed.json'


def test_a_get_reported_to_a_keeping_project_carries_the_receipt(tmp_path):
    project, receipt = Keeping(['1.0.0']), valid(GET)
    done = got(tmp_path, project, receipt)
    assert [r.get('receipt') for r in project.reports] == [receipt]
    assert not done.sentence.endswith((NOT_KEPT, UNCONFIRMED)) and done.receipt == receipt and done.technical['reported'] is True


def test_a_report_refused_as_invalid_then_accepted_without_the_field_says_not_kept(tmp_path):
    """R9. Mutation: report success after the fallback -> no NOT_KEPT."""
    project = Keeping(['1.0.0']); project.refuse = [Refused('Request body is not valid', status=400)]
    done = got(tmp_path, project, valid(GET))
    assert ['receipt' in r for r in project.reports] == [True, False]
    assert done.sentence.endswith(NOT_KEPT) and done.technical['reported'] is True


def test_a_report_that_times_out_says_unconfirmed(tmp_path):
    project = Keeping(['1.0.0']); project.refuse = [TimeoutError('timed out')]
    done = got(tmp_path, project, valid(GET))
    assert done.sentence.endswith(UNCONFIRMED) and done.technical['reported'] is False


def test_a_project_without_the_member_gets_a_report_without_the_receipt(tmp_path):
    project = Keeping(None)
    done = got(tmp_path, project, valid(GET))
    assert ['receipt' in r for r in project.reports] == [False] and done.sentence.endswith(NOT_KEPT)


def test_a_refused_get_receipt_leaves_the_record_unchanged(tmp_path):
    project = Keeping(['1.0.0']); project.add('poro', V1, name='Porosity')
    ex = Exchange(project, tmp_path / 'work', codes=CODES)
    pending = ex.fetch('poro')
    with pytest.raises(NotValid): pending.confirm(receipt=changed(next(c for c in CASES['codes'] if c['name'] == 'twice')))
    assert 'poro' not in ex.held() and project.reports == []
    pending.release()


# --- the SDK transport and the request bytes ----------------------------------------------------------------------

class Described:
    """A client whose capabilities answer is `answer`; records upload and derive calls."""
    url, project = 'https://example.invalid', 'p'

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def _described(self): return self.answer

    from ophiolite.client import Client
    transfer_codes_kept = Client.transfer_codes_kept


@pytest.mark.parametrize('answer, kept', [({}, False), ({'transfer_receipts': {'codes': ['9.9.9']}}, False),
                                          ({'transfer_receipts': {'codes': ['1.0.0']}}, True), ({'transfer_receipts': ['1.0.0']}, False)])
def test_the_transport_reads_the_capabilities_member(answer, kept):
    assert ClientTransport(Described(answer)).keeps_receipts('1.0.0') is kept


def _header(extra):
    return extra['X-Ophiolite-Upload']


def test_the_largest_receipt_fits_the_upload_and_derive_headers():
    """T7/D-7: receipt-max beside long upload and derive metadata stays within the 8,192-byte header. Mutation: the
    receipt cap raised to 4,096 -> the header check refuses."""
    receipt = valid('transfer-receipt-max.json')
    body, extra = planning.upload_metadata('p' * 160, 'c' * 64, filename='f' * 160, name='n' * 160, attribution='a' * 500, audience=[],
                                           rights_confirmed=True, well_notes='w' * 1000, profile='points-csv/1', append_to='i' * 160, expected_parent='e' * 64,
                                           holder='h' * 80, application='application:' + 'w' * 128, receipt=receipt)
    assert body['receipt'] == receipt and len(_header(extra)) <= 8192
    assert json.loads(base64.b64decode(_header(extra)))['receipt'] == receipt
    with pytest.raises(ValidationFailed) as refused:
        planning.upload_metadata('p', 'c', filename='f', name='n', attribution='a', audience=[], rights_confirmed=True,
                                 receipt=changed(next(c for c in CASES['model'] if c['name'] == 'over')))
    assert SHAPE in str(refused.value)
    from ophiolite.writers import WrittenOriginal
    written = WrittenOriginal(b'x,y,z\n1,2,3\n', 'points-csv/1', {'crs': 'EPSG:32631'}, 'derived')
    body, extra = planning.derive_request('p' * 200, written, name='n' * 160, from_=[('i' * 64, 'r' * 64)], method={'name': 'm' * 80, 'declared': False},
                                          command_id='c' * 64, new_version_of='i' * 64, expected_parent='e' * 64, holder='h' * 80,
                                          application='application:' + 'w' * 128, receipt=receipt)
    assert body['receipt'] == receipt and len(_header(extra)) <= 8192


def test_without_a_receipt_the_upload_request_is_unchanged():
    """Mutation: emit receipt: null -> the request gains a key."""
    body, _ = planning.upload_metadata('p', 'c', filename='f', name='n', attribution='a', audience=[], rights_confirmed=True)
    assert 'receipt' not in body


# -- C5: Client.receipts reads exchange/receipts whole, page by page -------------------------------------------------

class ReceiptsGateway:
    """exchange/receipts over the contract's answer fixture: the send and no get, then its get behind cursor `c1`
    (`c1` again when `repeat`; another item when `other`; 403 when not `member`)."""
    def __init__(self, repeat=False, other=False, member=True):
        self.bodies, self.repeat, self.other, self.member = [], repeat, other, member

    def __call__(self, request):
        import httpx
        assert request.url.path == '/api/v1/projects/p-rec/exchange/receipts'
        body = json.loads(request.content); self.bodies.append(body)
        if not self.member: return httpx.Response(403, json={'error': 'Project access denied', 'code': 'PERMISSION_DENIED', 'message': 'Project access denied'})
        served, first = valid('transfer-receipts-answer.json'), body.get('cursor') is None
        page = dict(served, got=[] if first else served['got'], next='c1' if first or self.repeat else None)
        if self.other: page['item'] = 'another-item'
        return httpx.Response(200, json=page)


def receipts_client(gateway):
    import httpx
    from ophiolite import Client
    return Client('https://gateway.example', 'p-rec', None, httpx.Client(transport=httpx.MockTransport(gateway)))


def test_the_receipts_are_read_whole_over_their_pages():
    """Mutation: stop after the first page, or drop the cursor -> the get is missing or the read repeats."""
    served, gateway = valid('transfer-receipts-answer.json'), ReceiptsGateway()
    assert receipts_client(gateway).receipts(served['item'], served['revision']) == served
    assert gateway.bodies == [{'project_id': 'p-rec', 'item': served['item'], 'revision': served['revision']},
                              {'project_id': 'p-rec', 'item': served['item'], 'revision': served['revision'], 'cursor': 'c1'}]


@pytest.mark.parametrize('how,said', [({'repeat': True}, 'Invalid or repeated receipts cursor.'),
                                      ({'other': True}, 'The receipts page names another item or version.')], ids=['repeat', 'other'])
def test_a_repeated_cursor_or_another_item_s_page_is_refused(how, said):
    """Mutation: no seen-cursor set, or no item check -> a loop, or another item's receipts taken as this one's."""
    from ophiolite.errors import VerificationFailed
    served = valid('transfer-receipts-answer.json')
    with pytest.raises(VerificationFailed) as caught: receipts_client(ReceiptsGateway(**how)).receipts(served['item'], served['revision'])
    assert said in str(caught.value)


def test_a_person_outside_the_project_is_refused_as_by_the_gateway():
    from ophiolite.errors import PermissionRefused
    with pytest.raises(PermissionRefused): receipts_client(ReceiptsGateway(member=False)).receipts('i', 'r')
