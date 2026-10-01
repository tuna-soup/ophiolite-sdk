"""E20: a colleague navigates wells, wellbores and their exact revisions in Python; anything the
registry does not allow, or a person outside the audience, is refused."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.errors import PermissionRefused, Unavailable, ValidationFailed, OphioliteError
from project_gateway.tests.test_applications import LAS


def test_a_colleague_navigates_from_the_well_to_exact_revisions_and_lineage(web):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = alice.upload_las(LAS.encode(), name='Well log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    well = alice.create_entity('well', 'W', authority='nlog', key='W-100', audience=['bob'], command_id='e-w')
    bore = alice.create_entity('wellbore', 'W-1', provisional=True, audience=['bob'], part_of=well, statement='Completion report', command_id='e-b')
    assert alice.create_entity('wellbore', 'W-1', provisional=True, audience=['bob'], part_of=well, statement='Completion report', command_id='e-b').entity_id == bore.entity_id  # replayed
    done = alice.of_entity(log.asset_id, log.revision, bore, statement='Header names the wellbore', command_id='e-a')
    assert done['predicate'] == 'of-entity'
    seen = {e.name: e for e in bob.entities()}
    assert set(seen) == {'W', 'W-1'} and [w.name for w in seen['W'].wellbores()] == ['W-1'] and seen['W-1'].well().name == 'W'
    [item] = seen['W-1'].assets()
    assert (item['asset_id'], item['revision']) == (log.asset_id, log.revision) and item['association']['evidence']['source'] == {'asset_id': log.asset_id, 'revision': log.revision}
    assert seen['W-1'].assets(profile='well-tops-csv/1') == [] and bob.parts(seen['W'])[0].entity_id == bore.entity_id
    assert bob.lineage(log.asset_id, log.revision)['parents'] == []
    later = alice.identify(bore, authority='nlog', key='W-100-1')
    assert later.identity == {'authority': 'nlog', 'key': 'W-100-1', 'provisional': False} and len(bob.data(bore)) == 1
    with pytest.raises(OphioliteError): alice._associate('near', {'kind': 'wellbore', 'entity_id': bore.entity_id}, well, {}, None)
    with pytest.raises((PermissionRefused, Unavailable)): list(client(web, 'viewer', 'delegate').entity(well.entity_id).assets())


def test_associations_name_the_entity_of_every_asset_you_may_read_in_one_read(web):
    """H3: the bulk read equals the per-entity reads, each item with its entity, and keeps its filters."""
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = alice.upload_las(LAS.encode(), name='Well log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    seen_by_bob = alice.create_entity('wellbore', 'B', authority='nlog', key='W-300-1', audience=['bob'], command_id='h3-b')  # a log names a wellbore
    hidden = alice.create_entity('wellbore', 'H', authority='nlog', key='W-301-1', audience=[], command_id='h3-h')
    alice.of_entity(log.asset_id, log.revision, seen_by_bob, statement='Header names B', command_id='h3-a1')
    other = alice.upload_las(LAS.encode(), name='Other log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': other.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    alice.of_entity(other.asset_id, other.revision, hidden, statement='Header names H', command_id='h3-a2')  # one wellbore per log
    mine = list(alice.associations())
    assert {(i['entity']['entity_id'], i['asset_id']) for i in mine} == {(seen_by_bob.entity_id, log.asset_id), (hidden.entity_id, other.asset_id)}
    theirs = list(bob.associations(assets=[log.asset_id, other.asset_id], kind='wellbore'))
    assert [(i['entity']['entity_id'], i['entity']['name']) for i in theirs] == [(seen_by_bob.entity_id, 'B')]  # the hidden well never appears
    per_well = [dict(i, entity={'entity_id': e.entity_id, 'kind': e.kind, 'name': e.name}) for e in bob.entities() for i in e.assets()]
    key = lambda i: i['association']['assertion_id']
    assert sorted(bob.associations(), key=key) == sorted(per_well, key=key)
    assert list(bob.associations(assets=['no-such-asset'])) == []


def test_an_export_carries_the_entities_and_navigates_offline(web, tmp_path):
    from ophiolite.bundle import open_bundle
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = alice.upload_las(LAS.encode(), name='Well log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    well = alice.create_entity('well', 'W', authority='nlog', key='W-200', audience=['bob'])
    bore = alice.create_entity('wellbore', 'W-2', authority='nlog', key='W-200-1', part_of=well, statement='Report', audience=[])
    alice.of_entity(log.asset_id, log.revision, bore)
    mine = alice.export([(log.asset_id, log.revision, ['GR'])], tmp_path / 'alice')
    assert mine.manifest['bundle_version'] == '2.4.0' and {e.entity_id for e in mine.entities} == {well.entity_id, bore.entity_id}
    offline = open_bundle(tmp_path / 'alice')
    assert [(a.asset_id, a.revision) for a in offline.assets_of(bore.entity_id)] == [(log.asset_id, log.revision)] and offline.entity(bore.entity_id).well_id() == well.entity_id
    theirs = bob.export([(log.asset_id, log.revision, ['GR'])], tmp_path / 'bob')  # Bob may not read the wellbore: nothing about it travels
    assert theirs.manifest['bundle_version'] == '1.0.0' and theirs.entities == []
