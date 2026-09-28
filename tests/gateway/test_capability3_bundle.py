"""E22b: a Python sign-in of capability 3 carries wells and wellbores in its export and imports a
result larger than the old 8 MiB client limit; an export that cannot carry wells says so in the
bundle, which a reader still sees after reopening and after packing."""
import hashlib
import warnings
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite import Client
from ophiolite.auth import Credential
from ophiolite.bundle import open_bundle, pack
from ophiolite.errors import Unavailable
from project_gateway.application_access import ApplicationAccess
from project_gateway.tests.test_one_api_matrix import claims_for
from project_gateway.tests.test_configured_limits import big_las


def capability3(web, service, persona):
    api = ApplicationAccess(service)
    row = api.request({'project_id': 'p', 'scopes': ['read', 'write'], 'label': 'Python', 'capability': 3}, persona, claims_for(persona))
    api.browser('approve', {'id': row['id'], 'confirmation_code': row['confirmation_code']}, persona)
    return Client('https://workspace.example', 'p', Credential.bearer('provider-' + persona, grant=row['id']), web.c)


@pytest.fixture
def shared_log(web, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', str(32 * 1024 * 1024))
    alice = client(web, 'alice', 'delegate')
    raw = big_las(int(12.5 * 1024 * 1024)); assert len(raw) > 8 * 1024 * 1024
    log = alice.upload_las(raw, name='Large log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    well = alice.create_entity('well', 'W', authority='nlog', key='W-C3', audience=['bob'])
    bore = alice.create_entity('wellbore', 'W-C3-1', authority='nlog', key='W-C3-1', part_of=well, statement='Report', audience=['bob'])
    alice.of_entity(log.asset_id, log.revision, bore)
    return raw, log, well, bore


def test_capability_3_exports_wells_and_imports_a_large_result(web, service, shared_log, tmp_path):
    raw, log, well, bore = shared_log
    bob = capability3(web, service, 'bob')
    with warnings.catch_warnings():
        warnings.simplefilter('error')  # nothing left out, nothing to warn about
        bundle = bob.export([(log.asset_id, log.revision, ['C00'])], tmp_path / 'bundle')
    assert {e.entity_id for e in bundle.entities} == {well.entity_id, bore.entity_id}
    assert 'entities_omitted' not in bundle.summary()
    [done] = bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert done['state'] == 'imported' and done['destination']['revision'] == hashlib.sha256(raw).hexdigest() == log.revision
    assert bob.entities() and bob.lineage(log.asset_id, log.revision)['revision'] == log.revision


def test_an_export_that_cannot_carry_wells_says_so_in_the_bundle(web, shared_log, tmp_path):
    raw, log, _, _ = shared_log
    old = client(web, 'bob', 'grant')  # a capability-1 approval: no wells, and the bundle records why
    with pytest.warns(UserWarning, match='left out'):
        bundle = old.export([(log.asset_id, log.revision, ['C00'])], tmp_path / 'old')
    reason = 'this sign-in may not read wells and wellbores'
    assert bundle.entities == [] and bundle.summary()['entities_omitted'] == reason
    assert open_bundle(tmp_path / 'old').summary()['entities_omitted'] == reason
    pack(tmp_path / 'old', tmp_path / 'old.zip')
    assert open_bundle(tmp_path / 'old.zip').summary()['entities_omitted'] == reason


def test_omission_reasons_and_their_absence(web, service, shared_log, tmp_path):
    raw, log, _, _ = shared_log
    bob = capability3(web, service, 'bob')
    unasked = bob.export([(log.asset_id, log.revision, ['C00'])], tmp_path / 'unasked', entities=False)
    assert unasked.summary()['entities_omitted'] == 'not requested'
    legacy_server = capability3(web, service, 'bob')
    def missing(*a, **k): raise Unavailable('Not found', status=404)
    legacy_server.entities = missing  # a server from before wells and wellbores answers 404
    with pytest.warns(UserWarning):
        legacy = legacy_server.export([(log.asset_id, log.revision, ['C00'])], tmp_path / 'legacy')
    assert legacy.summary()['entities_omitted'] == 'this server has no wells and wellbores'
    alice = client(web, 'alice', 'delegate')
    lone = alice.upload_las(big_las(4096), name='Unassociated', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': lone.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    empty = bob.export([(lone.asset_id, lone.revision, ['C00'])], tmp_path / 'empty')  # readable, simply none associated
    assert empty.entities == [] and 'entities_omitted' not in empty.summary()


def test_the_deployment_limit_is_the_servers_to_state(web, service, monkeypatch):
    from ophiolite.errors import CapacityExceeded, ValidationFailed
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', str(9 * 1024 * 1024))
    bob = capability3(web, service, 'bob')
    with pytest.raises(CapacityExceeded, match='upload limit of 9 MiB'):
        bob.upload_las(big_las(int(12.5 * 1024 * 1024)), name='Too large here', attribution='Synthetic', audience=[], rights_confirmed=True)
    with pytest.raises(ValidationFailed, match='32 MiB'):
        bob.upload_las(b'x' * (32 * 1024 * 1024 + 1), name='Never', attribution='Synthetic', audience=[], rights_confirmed=True)
