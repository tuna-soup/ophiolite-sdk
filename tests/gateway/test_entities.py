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
