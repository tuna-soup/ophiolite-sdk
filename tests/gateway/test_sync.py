"""E28 C10: Sync (resync, catch-up, checkpoint, follow) against the in-process gateway."""
import json
import uuid
import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401
from ophiolite import Client, Credential
from ophiolite.sync import Checkpoint, ResyncRequired, Sync

URL = 'https://workspace.example'


def client(web, persona='alice'):
    return Client(URL, 'p', Credential.bearer('oph_api_%s:read,write' % persona), web.c)


def well(c, name=None):
    return c.create_entity('well', name or 'Well ' + uuid.uuid4().hex[:6], authority='nlog', key=uuid.uuid4().hex[:10], audience=['bob'])


def published(web, alice, reuse=('bob',)):
    """Alice publishes a result and shares it with bob (read, and reuse unless told otherwise)."""
    binding = alice.configure(release_id=web.r['id'], curve='GR', name='Sync ' + uuid.uuid4().hex[:6], runners=['alice'], command_id='c-' + uuid.uuid4().hex[:8],
                              publication_profile='curve-edits/1')
    run = alice.start(binding, application_version='sync/1', parameters={}, command_id='s-' + uuid.uuid4().hex[:8])
    run.input()
    receipt = alice.publish(run, changes=[{'index': 0, 'value': 2}])
    alice.share(receipt, read=['bob'], reuse=list(reuse), expected_generation=alice.grants(receipt).generation)
    return receipt


def test_a_new_identity_during_catch_up_is_cached_and_survives_a_restart(web, tmp_path):
    alice = client(web)
    sync = Sync(alice, checkpoint=tmp_path / 'checkpoint.json')
    sync.run()
    assert sync.cache.complete
    created = well(alice)
    assert sync.run() >= 1 and sync.cache.get('entity', created.entity_id)['name'] == created.name  # never cached before
    saved = json.loads((tmp_path / 'checkpoint.json').read_text())
    assert saved['cursor'] == sync.head()['cursor'] and saved['epoch'] == sync.head()['epoch']
    restarted = Sync(client(web), checkpoint=tmp_path / 'checkpoint.json')  # a new process: a checkpoint, no cache
    restarted.run()
    assert restarted.cache.complete and restarted.cache.get('entity', created.entity_id) is not None


def test_a_write_behind_the_enumeration_cursor_still_converges(web):
    alice = client(web)
    for _ in range(3): well(alice)
    sync = Sync(alice)
    late = {}
    real = sync._inventory
    def inventory():
        late['well'] = well(alice)  # written after the head was captured, while enumerating
        return real()
    sync._inventory = inventory
    sync.run()
    assert sync.cache.get('entity', late['well'].entity_id) is not None  # replayed from the captured head


def test_a_failed_read_leaves_the_checkpoint_where_it_was(web, tmp_path):
    alice = client(web)
    sync = Sync(alice, checkpoint=tmp_path / 'c.json'); sync.run()
    before = dict(sync.checkpoint.values)
    well(alice)
    real = sync._entity
    def broken(entity_id): raise RuntimeError('the network dropped mid-batch')
    sync._entity = broken
    with pytest.raises(RuntimeError): sync.run()
    assert sync.checkpoint.values == before and json.loads((tmp_path / 'c.json').read_text()) == before
    sync._entity = real
    sync.run()
    assert sync.checkpoint.values['cursor'] > before['cursor']


def test_a_stale_access_lost_after_restoration_refreshes_and_reuse_follows_revocation(web):
    alice, bob = client(web), client(web, 'bob')
    receipt = published(web, alice)
    key = receipt.output_reference.key
    sync = Sync(bob); sync.run()
    assert sync.cache.get('asset', key)['can_reuse'] is True
    alice.share(receipt, read=['bob'], reuse=[], expected_generation=alice.grants(receipt).generation)  # reuse only withdrawn
    sync.run()
    assert sync.cache.get('asset', key)['can_reuse'] is False  # R7-1: what bob may do with it changed
    alice.share(receipt, read=[], reuse=[], expected_generation=alice.grants(receipt).generation)
    alice.share(receipt, read=['bob'], reuse=[], expected_generation=alice.grants(receipt).generation)  # restored before bob catches up
    sync.run()
    assert sync.cache.get('asset', key) is not None  # the access-lost was re-read, not trusted
    alice.share(receipt, read=[], reuse=[], expected_generation=alice.grants(receipt).generation)
    sync.run()
    assert sync.cache.get('asset', key) is None  # now really lost: evicted


def test_an_expired_cursor_falls_back_to_a_resync_and_changes_raises_it(web):
    alice = client(web)
    sync = Sync(alice); sync.run()
    well(alice)
    head = sync.head()
    web.a.journal.db.execute('INSERT INTO project_event_retention VALUES(?,?) ON CONFLICT(project) DO UPDATE SET floor=excluded.floor', ('p', head['cursor']))
    with pytest.raises(ResyncRequired): next(sync.changes(head['epoch'], 0))
    sync.run()  # behind the floor: resynchronised, not failed
    assert sync.checkpoint.values['cursor'] == head['cursor']


def test_follow_streams_the_events_after_a_cursor(web):
    import project_gateway.changes as feed
    feed.POLL_SECONDS = 0.05
    alice = client(web)
    head = Sync(alice).head()
    created = well(alice)
    events = list(Sync(alice).follow(epoch=head['epoch'], after=head['cursor'], seconds=0.3, reconnect=False))
    assert ('entity-created', created.entity_id) in [(e['kind'], e['subject_id']) for e in events]
    assert all(set(e) == {'project', 'cursor', 'epoch', 'kind', 'subject_kind', 'subject_id', 'generation', 'revision', 'actor_kind', 'actor', 'at'} for e in events)
