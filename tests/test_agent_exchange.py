"""E155 s0 C1: an assistant checks and gets with its own key, and its send asks for a tool run. A real `AgentClient`
over an `httpx.MockTransport` gateway that records every request (the spy); expected outcomes, facts and files are
literals. Each test names the mutation that fails it."""
import base64
import hashlib
import json

import httpx
import pytest

from ophiolite import exchange
from ophiolite.agent_exchange import AGENT_REFUSALS, AgentExchange, AgentTransport
from ophiolite.agents import AgentClient
from ophiolite.auth import Credential
from ophiolite.exchange import Exchange, folder_lock

URL = 'https://gateway.example'
RASTER, SOURCE = b'II*\x00 a stored map', 'Top Chalk depth map, exported from the stored grid\n'
MANIFEST = {'files': {'map.tif': hashlib.sha256(RASTER).hexdigest(), 'source.txt': hashlib.sha256(SOURCE.encode()).hexdigest()}}
TOPS = {'asset_id': 'a-tops', 'kind': 'derived', 'authority': 'project', 'revision': 'r' * 64, 'name': 'Chalk tops'}
MAP = {'asset_id': 'a-map', 'kind': 'external-scalar-map', 'authority': 'project', 'revision': '3', 'name': 'Top Chalk depth'}
RUN_NEEDED = 'No tool ran this: an assistant publishes a result only as a step of a tool run it reported.'


class Refreshing(Credential):
    """An assistant sign-in whose access token is refreshed on every request."""
    def __init__(self, first=0):
        super().__init__('token-0')
        self.issued = first

    def headers(self, url=None, project=None, *, cancel=None):
        self.issued += 1
        return {'Authorization': 'Bearer token-%d' % self.issued}


class Gateway:
    """The routes an assistant's check and get read; `seen` is every request as (path, authorization)."""
    def __init__(self, agent_id='agent-7'):
        self.agent_id, self.inventory, self.seen = agent_id, [dict(TOPS), dict(MAP)], []

    def __call__(self, request):
        path = request.url.path
        self.seen.append((path, request.headers.get('authorization')))
        body = json.loads(request.content or b'{}') if 'json' in request.headers.get('content-type', 'json') else {}
        operation = path.split('/projects/p/', 1)[1]
        if operation == 'capabilities/describe':
            return httpx.Response(200, json={'principal': {'kind': 'agent', 'agent': {'id': self.agent_id, 'name': 'Helper'}}, 'operations': []})
        if operation == 'catalog/inventory':
            return httpx.Response(200, json={'assets': self.inventory, 'next_cursor': None})
        if operation == 'maps/export':
            assert body['reference'] == {'project_id': 'p', 'asset_id': 'a-map', 'revision': '3'}
            return httpx.Response(200, json={'reference': body['reference'], 'asset': 'a-map', 'revision': '3', 'representation': 'source',
                                             'raster': base64.b64encode(RASTER).decode(), 'source_text': SOURCE, 'manifest': MANIFEST})
        if operation == 'activity/report':
            return httpx.Response(200, json={'recorded': True})
        return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'No such route here.', 'request_id': 'r-1'})


def agent(gateway, credential='oph_agent_test'):
    return AgentClient(URL, 'p', credential, http=httpx.Client(transport=httpx.MockTransport(gateway)))


def paths(gateway):
    return [p.split('/projects/p/', 1)[1] for p, _ in gateway.seen]


def test_check_and_get_read_with_the_agents_own_key(tmp_path):
    gateway = Gateway()
    ex = agent(gateway).exchange(tmp_path / 'work')
    assert isinstance(ex, AgentExchange) and isinstance(ex.transport, AgentTransport)
    first = ex.check()
    assert (first.outcome, first.sentence, first.facts) == ('nothing-new', 'You hold nothing yet. This first check noted the 2 items you can see; the next check lists what is new.',
                                                            {'newer': [], 'new': [], 'lost': [], 'holding': False, 'baseline': True, 'visible': 2})
    got = ex.get('a-map', output=tmp_path / 'work/map')
    assert (got.outcome, got.facts) == ('got', {'name': 'Top Chalk depth', 'folder': str(tmp_path / 'work/map'), 'map': True, 'number': 3})
    assert got.sentence == ('Got Top Chalk depth, version 3. You now hold it; saved in %s. It is a GeoTIFF generated from the stored map, not the file that was imported.'
                            % (tmp_path / 'work/map'))
    assert sorted(p.name for p in (tmp_path / 'work/map').iterdir()) == ['manifest.json', 'map.tif', 'source.txt']
    assert (tmp_path / 'work/map/map.tif').read_bytes() == RASTER and (tmp_path / 'work/map/source.txt').read_text() == SOURCE
    gateway.inventory.append({'asset_id': 'a-gr', 'kind': 'derived', 'authority': 'project', 'revision': 'g' * 64, 'name': 'Gamma ray'})
    second = ex.check()
    assert (second.outcome, second.sentence) == ('updates', '1 new since your last check: Gamma ray.')
    assert {a for _, a in gateway.seen} == {'Bearer oph_agent_test'}
    assert paths(gateway) == ['catalog/inventory', 'catalog/inventory', 'maps/export', 'catalog/inventory']


def test_get_sends_no_delivery_report_and_reports_nothing(tmp_path):
    """Mutation: `report = ClientTransport.report` restored on AgentTransport -> the spy sees one activity/report."""
    gateway = Gateway()
    ex = agent(gateway).exchange(tmp_path / 'work')
    got = ex.get('a-map', output=tmp_path / 'work/map')
    assert got.technical == {'asset_id': 'a-map', 'revision': '3', 'reported': None}
    assert 'activity/report' not in paths(gateway)
    assert json.loads((tmp_path / 'work/held.json').read_text())['items']['a-map']['revision'] == '3'


def pend(work, owner):
    """A pending send left in the folder by an earlier process of this assistant."""
    work.mkdir(parents=True, exist_ok=True)
    record = {'schema': exchange.SCHEMA, 'url': URL, 'project': 'p', 'holder_id': 'h' * 32, 'items': {}, 'seen': None,
              'pending': {'command_id': 'c' * 32, 'request': {'name': 'Shifted tops'}, 'resolved': {'parents': [], 'expected_parent': None},
                          'owner': owner, 'started': 1.0}}
    (work / 'held.json').write_text(json.dumps(record))


def owner_check(gateway, credential, work):
    """The owner check a send meets first, through the core over the rebuilt transport (no send reaches the project:
    the saved request differs, so an owner that matches gets "unfinished" and another gets "another access key")."""
    with pytest.raises(exchange.ExchangeRefused) as caught:
        Exchange(AgentTransport(agent(gateway, credential)), work).send(b'x', name='Other', profile='well-tops-csv/1', how='by hand', based_on=['a-tops'])
    return caught.value


def test_a_refreshed_assistant_sign_in_keeps_its_identity_and_another_agent_is_refused(tmp_path):
    """Mutation: identity taken from the key fingerprint (ClientTransport.identity) -> the rebuilt transport, on a
    refreshed token, meets outcome-unknown with other_key."""
    gateway = Gateway()
    first = AgentTransport(agent(gateway, Refreshing()))
    owner = first.identity()
    pend(tmp_path / 'work', owner)  # persisted by the first process; the next one signs in with a refreshed token
    same = owner_check(gateway, Refreshing(first=5), tmp_path / 'work')
    assert same.outcome == 'not-valid' and same.facts == {'reasons': 'an earlier send from this folder is unfinished: run it again unchanged, or set it aside'}
    assert owner == {'kind': 'agent', 'agent_id': 'agent-7'} and first.identity() == owner
    assert paths(gateway).count('capabilities/describe') == 2  # asked once per object: the first transport and the rebuilt one
    other = owner_check(Gateway(agent_id='agent-8'), Refreshing(first=9), tmp_path / 'work')
    assert (other.outcome, other.facts) == ('outcome-unknown', {'name': 'Shifted tops', 'other_key': True})
    assert other.sentence == ('An earlier send of Shifted tops was started with another access key and may or may not have arrived. '
                              'Run it again with that key to find out, or set it aside.')
    assert not any(p.endswith(('publications/derive', 'agents/propose')) for p, _ in gateway.seen)


def test_send_asks_for_a_tool_run_with_nothing_locked_saved_or_sent(tmp_path):
    """Mutation: AgentExchange.send delegating to Exchange.send -> the spy sees a publications/derive."""
    gateway = Gateway()
    pend(tmp_path / 'work', None)
    record = json.loads((tmp_path / 'work/held.json').read_text())
    record.update(pending=None, items={'a-tops': {'asset_id': 'a-tops', 'name': 'Chalk tops', 'kind': 'derived', 'revision': TOPS['revision'], 'number': 1,
                                                  'output': None}})
    (tmp_path / 'work/held.json').write_text(json.dumps(record))  # the folder holds what the send builds on: only the refusal stops it
    ex = agent(gateway).exchange(tmp_path / 'work')
    before, seen = (tmp_path / 'work/held.json').read_bytes(), len(gateway.seen)
    with pytest.raises(AGENT_REFUSALS['run-needed']) as caught:
        ex.send(b'name,md\nTop Chalk,1003\n', name='Shifted tops', profile='well-tops-csv/1', how='shifted by hand', based_on=['a-tops'])
    assert (caught.value.outcome, str(caught.value), caught.value.facts) == ('run-needed', RUN_NEEDED, {})
    assert isinstance(caught.value, exchange.Refused) and caught.value.code == 'run-needed'
    assert (tmp_path / 'work/held.json').read_bytes() == before and len(gateway.seen) == seen
    with folder_lock(tmp_path / 'work/held.lock', 0): pass  # no lock is left


def test_the_vendored_core_is_unchanged():
    assert exchange.OUTCOMES == ('nothing-new', 'updates', 'access-changed', 'got', 'already-latest', 'not-visible', 'cannot-read-here', 'damaged',
                                 'map-unavailable', 'sent-new', 'sent-version', 'newer-version-exists', 'nothing-changed', 'earlier-version',
                                 'access-refused', 'not-valid', 'not-held', 'too-large', 'outcome-unknown', 'abandoned', 'folder-busy', 'rate-limited',
                                 'sign-in-needed', 'could-not-reach', 'stays', 'name-unclear', 'name-not-found', 'made-for')  # E192 s2: made-for
    assert set(exchange.SENTENCES) == set(exchange.OUTCOMES) and set(exchange.REFUSALS) == {
        'not-visible', 'cannot-read-here', 'damaged', 'map-unavailable', 'newer-version-exists', 'nothing-changed', 'earlier-version', 'access-refused',
        'not-valid', 'not-held', 'too-large', 'outcome-unknown', 'folder-busy', 'rate-limited', 'sign-in-needed', 'could-not-reach',
        'name-unclear', 'name-not-found'}
    # the carried copy's bytes are tools/check-vendored-exchange.py's and sync's (this module runs in the export, beside no plug-in)
