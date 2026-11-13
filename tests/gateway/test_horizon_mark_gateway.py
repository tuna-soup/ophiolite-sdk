"""E173 s0b C3: the SDK marks an uploaded point set as a horizon in one request and in parts, against the in-process
gateway; the inventory lists it as one, a repeated command answers the same item, and the same command without the mark
is another request."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import publish
from ophiolite.errors import IntegrityConflict
from ophiolite.sync import Sync

ROWS = b'x,y,z,phi\n' + b''.join(b'%d,%d,%d.5,0.1\n' % (i, i * 2, 1000 + i) for i in range(160))  # 2,6xx bytes: above a 1 KiB request
SEND = dict(profile='points-csv/1', name='Top Chalk', attribution='Synthetic', audience=[], rights_confirmed=True)


def marks(c):
    return {i['asset_id']: i['represents'] for i in Sync(c).inventory() if i['authority'] == 'retained'}


def test_one_request_marks_a_horizon_and_a_repeat_answers_the_same_item(web):
    alice = client(web, 'alice', 'delegate')
    horizon = alice.upload_data(ROWS, represents='horizon', command_id='marked', **SEND)
    plain = alice.upload_data(ROWS, command_id='plain', **SEND)
    assert marks(alice) == {horizon.asset_id: 'horizon', plain.asset_id: None}
    assert alice.upload_data(ROWS, represents='horizon', command_id='marked', **SEND).asset_id == horizon.asset_id
    with pytest.raises(IntegrityConflict): alice.upload_data(ROWS, command_id='marked', **SEND)  # the mark dropped: another request


def test_in_parts_the_mark_goes_with_begin(web, monkeypatch):
    """Mutation: `_upload_parts` not passing the mark (listed None)."""
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', '1024'); monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * 1024 * 1024))
    monkeypatch.setattr(publish, 'SINGLE', 0)
    alice = client(web, 'alice', 'delegate')
    paths = []
    web.c.event_hooks['request'].append(lambda request: paths.append(request.url.path.rsplit('/', 1)[-1]))
    horizon = alice.upload_data(ROWS, represents='horizon', command_id='parts', **SEND)
    assert 'begin' in paths and 'publish' in paths and paths.count('part') >= 3
    assert marks(alice) == {horizon.asset_id: 'horizon'}
    assert alice.upload_data(ROWS, represents='horizon', command_id='parts', **SEND).asset_id == horizon.asset_id
    with pytest.raises(IntegrityConflict): alice.upload_data(ROWS, command_id='parts', **SEND)
