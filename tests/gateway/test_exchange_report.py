"""E70b C3: a confirmed `get` tells the project which version this holder received (`exchange-consumer/1`), once.

The in-process gateway of test_exchange_map (maps configured, so Activity and the map catalog are there), access
keys made the real way by a browser session. Counted at the wire: every POST to `/activity/report`."""
import json

import httpx
import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from test_exchange_map import mapped, key  # noqa: F401
from ophiolite import exchange
from ophiolite.typed import PointSet

UNKNOWN = dict(crs='unknown', xy_unit='unknown', z_unit='unknown', z_meaning='unknown', positive='unknown', vertical_datum='unknown')


def owner_view(gateway, person='alice'):
    """The project's delivery observations as `person` sees them in the Workspace (a browser session)."""
    token, csrf = gateway.app.state.sessions.create(person, None, person)
    gateway.c.cookies.set('ab_session', token)
    page = gateway.c.post('/api/v1/projects/p/activity/list', json={'project_id': 'p'}, headers={'X-CSRF-Token': csrf, 'Origin': ORIGIN})
    gateway.app.state.sessions.remove(token); gateway.c.cookies.clear()
    assert page.status_code == 200, page.text
    return [e for e in page.json()['events'] if e['kind'] == 'consumer.applied']


@pytest.fixture
def world(mapped, tmp_path):
    """Alice's read key and a points item she uploaded; every report request recorded as it is sent."""
    gateway, asset = mapped
    alice = key(gateway, 'alice', 'write')
    data = PointSet.write([(0, 0, 1), (10, 5, None)], **UNKNOWN)
    item = alice.upload_data(data.bytes, profile=data.profile, declared=data.declared, name='Picked points', attribution='Synthetic',
                             audience=['bob'], rights_confirmed=True, command_id='e70b-points')
    reader = key(gateway, 'alice', 'read')
    sent = []
    gateway.c.event_hooks['request'].append(lambda r: sent.append(json.loads(r.read())) if r.url.path.endswith('/activity/report') else None)
    return gateway, asset, item, reader, sent


def test_a_confirmed_get_is_reported_once_under_the_key_s_name(world, tmp_path):
    gateway, _, item, reader, sent = world
    ex = reader.exchange(tmp_path / 'work')
    got = ex.get(item.asset_id, output=tmp_path / 'out')
    assert got.outcome == 'got' and got.technical['reported'] is True
    holder = json.loads((tmp_path / 'work/held.json').read_text())['holder_id']
    assert [(s['binding_id'], s['profile'], s['mode'], s['reference']) for s in sent] == [(holder, 'exchange-consumer/1', 'get', {'project_id': 'p', 'asset_id': item.asset_id, 'revision': item.revision})]
    assert 'project_id' not in sent[0]  # the reference names the project
    events = owner_view(gateway)
    assert len(events) == 1 and events[0]['via']['label'] == 'Map read' and events[0]['coverage_profile'] == 'exchange-consumer/1'
    # The same version again (no output, so it is fetched and confirmed again), and from a fresh process: one event.
    assert ex.get(item.asset_id).technical['reported'] is True
    fresh = reader.exchange(tmp_path / 'work')
    assert fresh.get(item.asset_id).technical['reported'] is True
    assert len({s['event_id'] for s in sent}) == 1 and len(sent) == 3
    assert len(owner_view(gateway)) == 1


def test_a_failed_report_leaves_the_confirmation_and_the_record_as_they_are(world, tmp_path, monkeypatch):
    gateway, _, item, reader, sent = world
    real = gateway.c.stream
    def failing(kind):
        def stream(method, url, **kw):
            if str(url).endswith('/activity/report'):
                if kind == 'timeout': raise httpx.ReadTimeout('timed out')
                if kind == 'lost':  # the project stored it; the answer never arrived
                    with real(method, url, **kw) as response: response.read()
                    raise httpx.RemoteProtocolError('connection closed')
                return _closed(503, method, url)
            return real(method, url, **kw)
        return stream
    for n, kind in enumerate(('timeout', 'lost', 'unavailable')):
        monkeypatch.setattr(gateway.c, 'stream', failing(kind))
        ex = reader.exchange(tmp_path / ('w%d' % n))
        receipt = ex.fetch(item.asset_id, output=tmp_path / ('o%d' % n))
        got = receipt.confirm()
        assert (got.outcome, receipt.confirmed, receipt.reported, got.technical['reported']) == ('got', True, False, False), kind
        record = json.loads((tmp_path / ('w%d' % n) / 'held.json').read_text())
        entry = record['items'][item.asset_id]
        assert entry['revision'] == item.revision and not any('report' in k for k in entry), kind  # the record says nothing of reporting
    monkeypatch.setattr(gateway.c, 'stream', real)
    assert len(owner_view(gateway)) == 1  # only the lost answer reached the project
    retried = reader.exchange(tmp_path / 'w1').get(item.asset_id)  # the lost one, retried: the same event id
    assert retried.technical['reported'] is True and len(owner_view(gateway)) == 1


def _closed(status, method, url):
    """A response context manager the client's `stream` call can enter, carrying `status`."""
    import contextlib
    @contextlib.contextmanager
    def cm():
        yield httpx.Response(status, json={'error': 'Activity unavailable', 'code': 'UNAVAILABLE', 'message': 'Activity unavailable'}, request=httpx.Request(method, url))
    return cm()


def test_nothing_is_reported_unless_a_version_is_confirmed(world, tmp_path, monkeypatch):
    gateway, _, item, reader, sent = world
    ex = reader.exchange(tmp_path / 'work')
    with ex.fetch(item.asset_id) as receipt: pass  # fetched, never confirmed
    assert receipt.reported is None and sent == []
    with pytest.raises(exchange.REFUSALS['not-visible']): ex.get('no-such-item')  # the fetch fails
    monkeypatch.setattr(exchange.Exchange, '_save', lambda self, record: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): ex.get(item.asset_id)  # the record could not be written
    monkeypatch.undo()
    blocker = tmp_path / 'blocked'; blocker.write_text('a file where the folder would go')
    with pytest.raises(Exception): ex.get(item.asset_id, output=blocker / 'inside')  # the files could not be written
    assert sent == []
    receipt = ex.fetch(item.asset_id); receipt.confirm()
    with pytest.raises(exchange.REFUSALS['not-valid']): receipt.confirm()  # a repeated confirmation is refused, and reports nothing
    assert len(sent) == 1


def test_a_map_get_is_reported(world, tmp_path):
    gateway, asset, _, reader, sent = world
    got = reader.exchange(tmp_path / 'work').get(asset, output=tmp_path / 'map')
    assert got.outcome == 'got' and got.technical['reported'] is True
    assert [e['data']['reference']['asset_id'] for e in owner_view(gateway)] == [asset]


def test_a_transport_without_report_is_unchanged(world, tmp_path):
    gateway, _, item, reader, sent = world
    class Plain:  # a host's own transport (QGIS) that does not report
        def __init__(self, inner): self.inner, self.url, self.project = inner, inner.url, inner.project
        def __getattr__(self, name):
            if name == 'report': raise AttributeError(name)
            return getattr(self.inner, name)
    ex = exchange.Exchange(Plain(reader.exchange(tmp_path / 'x').transport), tmp_path / 'work')
    got = ex.get(item.asset_id)
    assert got.outcome == 'got' and got.technical['reported'] is None and sent == []
