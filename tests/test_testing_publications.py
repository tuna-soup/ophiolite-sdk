"""E52 C4: the synthetic server answers a derived publication's versions, read-back and history as the server does.

`tests/fixtures/e52-shale-volume-server.json` holds the Platform's own answers (recorded in process at Platform
fbcb593) for the same SDK-written files: the fixture's descriptor, curve and history must equal them, apart from
identifiers, times and the parts the fixture does not serve (the revision manifest and the display words). A fixture
that invents history, loses a version's parameters or drifts from the server's shape fails here."""
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from ophiolite import Client, Credential, petrophysics as pp
from ophiolite.errors import IntegrityConflict, OphioliteError
from ophiolite.testing import synthetic_server
from ophiolite.writers import write_curves

SERVER = json.loads((Path(__file__).parent / 'fixtures/e52-shale-volume-server.json').read_text())
NOT_SERVED = {'manifest', 'display'}  # the fixture serves no revision manifest and no display words


def files():
    return [base64.b64decode(f) for f in SERVER['files']]


@pytest.fixture
def published():
    """alice publishes the two recorded files as versions 1 and 2 of one result on the synthetic server."""
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        asset = next(iter(alice.assets()))
        parent = (asset['asset_id'], asset['revision'])
        one, two = files()
        receipts = [SERVER['receipts'][0]['method'], SERVER['receipts'][1]['method']]
        def publish(raw, method, command, **over):
            from ophiolite.writers import WrittenOriginal
            method = {k: v for k, v in method.items() if k != 'script_sha256'}
            return alice.publish_derived(WrittenOriginal(raw, 'las2/1', {}, 'derived.las'), name='Synthetic shale volume', from_=[parent], method=method, command_id=command, **over)
        r1 = publish(one, receipts[0], 'v1')
        r2 = publish(two, receipts[1], 'v2', new_version_of=r1.asset_id, expected_parent=r1.revision)
        yield server, alice, parent, publish, r1, r2


def same(fixture, server, ids):
    """Equal after naming identifiers and times by role; what the fixture does not serve is left out."""
    def norm(value):
        if isinstance(value, dict):
            return {k: norm(v) for k, v in value.items() if k not in ('evaluated_at', 'published_at', 'request_id', 'run_id')}
        if isinstance(value, list): return [norm(v) for v in value]
        return ids.get(value, value) if isinstance(value, str) else value
    return norm(fixture), norm({k: v for k, v in server.items() if k not in NOT_SERVED})


def roles(r1, parent):
    s1 = SERVER['receipts'][0]
    return {r1.asset_id: 'RESULT', s1['asset_id']: 'RESULT', parent[0]: 'PARENT', SERVER['parent']['asset_id']: 'PARENT',
            'ophiolite:derived': 'PARENT-AUTHORITY', 'ophiolite:uploaded': 'PARENT-AUTHORITY', 'alice': 'alice'}


def test_versions_keep_the_asset_and_each_its_own_parameters(published):
    server, alice, parent, publish, r1, r2 = published
    assert (r1.asset_id == r2.asset_id, r1.revision_number, r2.revision_number) == (True, 1, 2)
    assert [r.revision for r in (r1, r2)] == [r['revision'] for r in SERVER['receipts']]  # the same files, the same digests as the server
    for receipt, recorded in zip((r1, r2), SERVER['receipts']):
        back = alice.read(receipt.asset_id, receipt.revision, ['VSH'])
        assert back.descriptors[0].model_dump(by_alias=True)['derivation']['method']['parameters'] == recorded['method']['parameters']
    assert [(row.number, row.revision) for row in alice.history(r2).revisions] == [(1, r1.revision), (2, r2.revision)]


def test_read_back_and_history_equal_the_servers_answers(published):
    server, alice, parent, publish, r1, r2 = published
    ids = roles(r1, parent)
    for receipt in (r1, r2):
        recorded = SERVER['reads'][receipt.revision]
        url = f'{server.url}/api/v1/projects/p/scientific-assets/{receipt.asset_id}/revisions/{receipt.revision}'
        headers = {'Authorization': 'Bearer oph_api_alice'}
        descriptor = httpx.get(url + '?curve=VSH', headers=headers).json()
        curve = httpx.get(url + '/representations/curve:VSH?curve=VSH', headers=headers).content
        artifact = httpx.get(url + '/representations/artifact?curve=VSH', headers=headers).content
        theirs_curve = base64.b64decode(recorded['curve_base64'])
        ids.update({hashlib.sha256(curve).hexdigest(): 'CURVE-DIGEST', hashlib.sha256(theirs_curve).hexdigest(): 'CURVE-DIGEST'})
        mine, theirs = same(descriptor, recorded['descriptor'], ids)
        assert mine == theirs
        assert curve.replace(receipt.asset_id.encode(), b'RESULT') == theirs_curve.replace(SERVER['receipts'][0]['asset_id'].encode(), b'RESULT')  # the same compact, sorted bytes
        assert hashlib.sha256(artifact).hexdigest() == receipt.revision
    status, history = server.handler('POST', '/api/v1/projects/p/applications/result-history',
                                     json.dumps({'project_id': 'p', 'asset_id': r1.asset_id}).encode(), {'Authorization': 'Bearer oph_api_alice'})
    mine, theirs = same(history, SERVER['history'], ids)
    assert status == 200 and mine == {**theirs, 'display': mine['display']} and mine['display'] == {'member_names': {'alice': 'Alice'}}


def test_append_rules_refuse_as_the_server_does(published):
    server, alice, parent, publish, r1, r2 = published
    one, two = files()
    third = one.replace(b'SYNTHETIC-M1', b'SYNTHETIC-M2')
    with pytest.raises(IntegrityConflict) as stale:
        publish(third, SERVER['receipts'][0]['method'], 'v3', new_version_of=r1.asset_id, expected_parent=r1.revision)
    assert (stale.value.status, stale.value.code, stale.value.server_message) == (SERVER['stale'][0], SERVER['stale'][1]['code'], SERVER['stale'][1]['error'])
    with pytest.raises(IntegrityConflict) as duplicate:
        publish(one, SERVER['receipts'][0]['method'], 'v4', new_version_of=r1.asset_id, expected_parent=r2.revision)
    assert (duplicate.value.status, duplicate.value.code, duplicate.value.server_message) == (SERVER['duplicate'][0], SERVER['duplicate'][1]['code'], SERVER['duplicate'][1]['error'])
    with Client(server.url, 'p', Credential.bearer('oph_api_bob')) as bob:
        from ophiolite.writers import WrittenOriginal
        with pytest.raises(OphioliteError) as other:
            bob.publish_derived(WrittenOriginal(third, 'las2/1', {}, 'derived.las'), name='Mine', from_=[parent], method={'name': 'mine'},
                                command_id='b1', new_version_of=r1.asset_id, expected_parent=r2.revision)
    assert (other.value.status, other.value.code, other.value.server_message) == (SERVER['not_author'][0], SERVER['not_author'][1]['code'], SERVER['not_author'][1]['error'])
    assert [(row.number, row.revision) for row in alice.history(r1).revisions] == [(1, r1.revision), (2, r2.revision)]  # nothing appended
    assert publish(one, SERVER['receipts'][0]['method'], 'v1').revision == r1.revision  # a replay returns the recorded receipt


def test_the_fixture_serves_what_a_fresh_calculation_publishes():
    """The gallery's path: compute with ophiolite.petrophysics, write with notes, publish, read back the values."""
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        asset = next(iter(alice.assets())); view = alice.read(asset['asset_id'], asset['revision'], ['GR']).curves[0]
        picks = pp.typed_picks(5, 35)
        values = pp.shale_volume(view.values, method='clavier', clean=5, shale=35)
        written = write_curves(view.axis, {'VSH': ('V/V', values)}, depth_unit='M', notes=[pp.calculation_record('clavier', picks, 'gAPI')])
        receipt = alice.publish_derived(written, name='VSH', from_=[(asset['asset_id'], asset['revision'])],
                                        method=pp.shale_volume_method(method='clavier', picks=picks), command_id='fresh')
        back = alice.read(receipt.asset_id, receipt.revision, ['VSH'])
        assert back.curves[0].values == values and back.descriptors[0].model_dump(by_alias=True)['scientific']['quantity'] == 'Shale Volume Fraction'
