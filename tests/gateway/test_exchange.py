"""E70a C3: check, get and send through ClientTransport against the in-process gateway, with access keys made the
real way (a browser session creates them; the access-key service is not patched: test_access_key_chain.keyed).
Alice holds two write keys (A and B); Bob, a member, has his own."""
import base64
import hashlib
import json

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, session, ORIGIN  # noqa: F401
from ophiolite import Client, Credential
from ophiolite import exchange
from ophiolite.typed import PointSet

UNKNOWN = dict(crs='unknown', xy_unit='unknown', z_unit='unknown', z_meaning='unknown', positive='unknown', vertical_datum='unknown')
LAS_TEXT = ('~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.M 100 : start\nSTOP.M 102 : stop\nSTEP.M 1 : step\nNULL. -999.25 : missing\n'
            'WELL. SDK : fixture\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma\n~ASCII\n100 0\n101 -999.25\n102 30\n')


def key(web, person, scope='write'):
    token, headers = session(web, person)
    made = web.c.post('/api/v1/access-keys/create', json={'project_id': 'p', 'label': 'Exchange ' + person + ' ' + scope, 'scope': scope, 'days': 30}, headers=headers)
    assert made.status_code == 200, made.text
    web.app.state.sessions.remove(token); web.c.cookies.clear()
    return made.json()


def remove(web, person, ident):
    token, headers = session(web, person)
    assert web.c.post('/api/v1/access-keys/remove', json={'id': ident}, headers=headers).status_code == 200
    web.app.state.sessions.remove(token); web.c.cookies.clear()


def client(web, made, project='p'):
    return Client(ORIGIN, project, Credential.bearer(made['key']), web.c)


def points(z):
    return PointSet.write([(0, 0, z), (10, 5, None)], **UNKNOWN)


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    return caught.value


@pytest.fixture
def two_keys(keyed, tmp_path):
    """Alice's keys A and B; a typed parent both hold; A sends "Porosity points" (version 1) and B gets it."""
    web = keyed
    ka, kb = key(web, 'alice'), key(web, 'alice')
    alice = client(web, ka)
    base = points(1)
    parent = alice.upload_data(base.bytes, profile=base.profile, declared=base.declared, name='Picked points', attribution='Synthetic',
                               audience=['bob'], rights_confirmed=True, command_id='e70a-parent')
    alice.share(parent, read=['bob'], reuse=['bob'], expected_generation=alice.grants(parent).generation)
    a, b = alice.exchange(tmp_path / 'a'), client(web, kb).exchange(tmp_path / 'b')
    for ex, out in ((a, 'pa'), (b, 'pb')): ex.check(); ex.get(parent.asset_id, output=tmp_path / out)
    v1 = points(2)
    sent = a.send(v1.bytes, name='Porosity points', profile=v1.profile, declare=v1.declared, how='kriging', based_on=[parent.asset_id])
    assert (sent.outcome, sent.sentence) == ('sent-new', 'Sent Porosity points as a new item; it is private until you share it.')
    item = sent.technical['asset_id']
    assert b.get(item, output=tmp_path / 'xb').outcome == 'got'
    return web, ka, kb, a, b, parent.asset_id, item, v1


def uploads(web):
    seen = []
    def hook(request):
        if request.url.path.endswith('/publications/derive'): seen.append(json.loads(base64.b64decode(request.headers['X-Ophiolite-Upload'])))
    web.c.event_hooks['request'].append(hook)
    return seen


def test_the_identity_is_the_key_itself_because_no_route_names_its_person(two_keys):
    """Stop rule 8: no route tells an access key whose it is, so a pending send is bound to the key (two keys of the
    same person are two identities); recovery under a rotated key is refused and recorded as an owner decision."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    one, two = a.transport.identity(), b.transport.identity()
    assert one == {'kind': 'delegate', 'fingerprint': hashlib.sha256(ka['key'].encode()).hexdigest()} and one != two


def test_a_newer_version_from_the_other_key_is_checked_and_a_stale_send_is_refused_naming_it(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2 = points(3)
    version = a.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='kriging again', based_on=[parent], of=item)
    assert (version.outcome, version.sentence) == ('sent-version', 'Sent Porosity points as version 2. Version 1 is kept.')
    checked = b.check()
    assert checked.outcome == 'updates' and checked.sentence.startswith('1 newer: Porosity points, version 2 by ') and checked.sentence.endswith('just now.')
    wire = uploads(web)
    v3 = points(4)
    stale = refused('newer-version-exists', lambda: b.send(v3.bytes, name='Porosity points', profile=v3.profile, declare=v3.declared, how='mine', based_on=[parent], of=item))
    assert stale.sentence.startswith('Version 2 was added by ') and stale.sentence.endswith(
        'Your change was not sent. Either get version 2 and look at it, or send yours as a new item.')
    assert [w['expected_parent'] for w in wire] == [hashlib.sha256(v1.bytes).hexdigest()]  # the held version, not the head
    assert stale.technical['code'] == 'revision-conflict' and stale.technical['status'] == 409
    same = refused('nothing-changed', lambda: b.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='mine', based_on=[parent], of=item))
    assert same.sentence == 'This is the same as version 2; nothing was sent.'
    got = b.get(item, output=tmp_path / 'xb')
    assert got.outcome == 'got' and got.sentence.startswith('Got Porosity points, version 2 by ')
    data = json.loads((tmp_path / 'xb/data.json').read_text())
    assert (data['context']['x_range'], data['context']['y_range'], data['context']['count']) == ([0.0, 10.0], [0.0, 5.0], 2)
    assert (tmp_path / 'xb/original').read_bytes() == b'x,y,z\n0,0,3\n10,5,\n'  # version 2: the first z is 3, the last is missing


def test_a_typed_get_writes_the_original_data_and_descriptor_with_literal_values(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    files = sorted(p.name for p in (tmp_path / 'xb').iterdir())
    assert files == ['data.json', 'descriptor.json', 'original']
    assert (tmp_path / 'xb/original').read_bytes() == v1.bytes
    data = json.loads((tmp_path / 'xb/data.json').read_text())
    assert (data['context']['type'], data['context']['x_range'], data['context']['missing_z_count']) == ('point-set', [0.0, 10.0], 1)
    assert v1.bytes == b'x,y,z\n0,0,2\n10,5,\n'  # first z 2, last missing
    again = b.get(item, output=tmp_path / 'xb')
    assert (again.outcome, again.sentence) == ('already-latest', 'You already hold the latest version of Porosity points, saved in %s.' % (tmp_path / 'xb'))


@pytest.mark.parametrize('who', ['removed', 'read-only', 'colleague'])
def test_credentials_and_refusals(two_keys, tmp_path, who):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2 = points(5)
    attempt = lambda ex, of=item: ex.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='x', based_on=[parent], of=of)
    if who == 'removed':
        remove(web, 'alice', kb['id'])
        for call in (b.check, lambda: b.get(item), lambda: attempt(b)):
            caught = refused('sign-in-needed', call)
            assert caught.sentence == 'Your access key is not accepted any more. Ask for a new one.'
        return
    if who == 'read-only':
        reader = client(web, key(web, 'alice', 'read')).exchange(tmp_path / 'r'); reader.get(parent); reader.get(item)
        caught = refused('access-refused', lambda: attempt(reader))
    else:
        alice = client(web, ka)
        info = alice._post('publications', 'info', {'asset_id': item})
        alice._post('publications', 'share', {'asset_id': item, 'audience': ['bob'], 'reuse_audience': ['bob'], 'expected_generation': info['grants_generation']})
        bob = client(web, key(web, 'bob')).exchange(tmp_path / 'bob'); bob.get(parent); bob.get(item)
        caught = refused('access-refused', lambda: attempt(bob))
        mine = bob.send(v2.bytes, name='Porosity points (Bob)', profile=v2.profile, declare=v2.declared, how='x', based_on=[parent, item])
        assert mine.outcome == 'sent-new'
    assert caught.sentence == ('The project did not allow this with this access key, so nothing was sent. '
                               "Check that the key is for this project and can write, or ask the item's author.")
    assert 'new item' not in caught.sentence


def test_a_lost_answer_is_recovered_once_even_after_the_parent_moved(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    import httpx
    drop = {'on': True}
    def lose(response):
        if drop['on'] and response.request.url.path.endswith('/publications/derive'): raise httpx.ReadError('connection lost after commit')
    web.c.event_hooks['response'].append(lose)
    v2 = points(6)
    send = lambda ex: ex.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='kriging again', based_on=[parent], of=item)
    unknown = refused('outcome-unknown', lambda: send(a))
    assert unknown.sentence == 'An earlier send of Porosity points may or may not have arrived. Run the same send again to find out; it will not publish twice.'
    drop['on'] = False
    a_again = client(web, ka).exchange(tmp_path / 'a')                     # a new process on the same folder
    done = send(a_again)
    assert done.outcome == 'sent-version' and done.technical['command_id'] == unknown.technical['command_id']
    history = client(web, ka)._post('applications', 'result-history', {'asset_id': item})
    assert [r['number'] for r in history['revisions']] == [1, 2]                # exactly one new version


def test_a_command_reused_for_different_content_is_not_valid(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2 = points(7)
    first = a.send(v2.bytes, name='Other', profile=v2.profile, declare=v2.declared, how='x', based_on=[parent])
    record = json.loads((tmp_path / 'a/held.json').read_text())
    v3 = points(8)
    request = {'name': 'Third', 'profile': v3.profile, 'how': 'x', 'based_on': [parent], 'of': None, 'declare': dict(v3.declared), 'extra': {},
               'sha256': hashlib.sha256(v3.bytes).hexdigest(), 'bytes': len(v3.bytes)}
    record['pending'] = {'command_id': first.technical['command_id'], 'request': request, 'resolved': {'parents': [{'asset_id': parent, 'revision': record['items'][parent]['revision']}],
                         'expected_parent': None}, 'owner': a.transport.identity(), 'started': 0}
    (tmp_path / 'a/held.json').write_text(json.dumps(record))
    caught = refused('not-valid', lambda: a.send(v3.bytes, name='Third', profile=v3.profile, declare=v3.declared, how='x', based_on=[parent]))
    assert caught.sentence == 'The project refused this: the request was not accepted. Nothing was sent.' and caught.technical['status'] == 409


def test_history_failing_after_a_stale_refusal_gives_the_number_free_sentence(two_keys, monkeypatch):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2, v3 = points(9), points(10)
    a.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='x', based_on=[parent], of=item)
    monkeypatch.setattr(b.transport, 'history', lambda item: (_ for _ in ()).throw(RuntimeError('history down')))
    stale = refused('newer-version-exists', lambda: b.send(v3.bytes, name='Porosity points', profile=v3.profile, declare=v3.declared, how='x', based_on=[parent], of=item))
    assert stale.sentence.startswith('A newer version was added first.')


def test_an_expired_change_log_changes_nothing_in_check(two_keys):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2 = points(11)
    a.send(v2.bytes, name='Porosity points', profile=v2.profile, declare=v2.declared, how='x', based_on=[parent], of=item)
    before = b.check().sentence
    db = web.a.journal.db
    with web.a.journal.lock, db: db.execute("DELETE FROM project_events WHERE project='p'")  # nothing the held record relies on
    assert 'newer' in before and b.check().sentence == before


def test_shared_away_and_shared_again(keyed, tmp_path):
    web = keyed
    alice, bob_key = client(web, key(web, 'alice')), key(web, 'bob')
    base = points(1)
    parent = alice.upload_data(base.bytes, profile=base.profile, declared=base.declared, name='Picked points', attribution='Synthetic',
                               audience=['bob'], rights_confirmed=True, command_id='e70a-shared')
    alice.share(parent, read=['bob'], reuse=['bob'], expected_generation=alice.grants(parent).generation)
    bob = client(web, bob_key).exchange(tmp_path / 'bob'); bob.check(); bob.get(parent.asset_id, output=tmp_path / 'p')
    alice.share(parent, read=[], reuse=[], expected_generation=alice.grants(parent).generation)
    lost = bob.check()
    assert (lost.outcome, lost.sentence) == ('access-changed', 'You can no longer see 1 item you hold: Picked points. They may have been removed or no longer shared with you.')
    assert refused('not-visible', lambda: bob.get(parent.asset_id)).sentence.startswith('You can no longer see Picked points.')
    alice.share(parent, read=['bob'], reuse=['bob'], expected_generation=alice.grants(parent).generation)
    back = bob.check()
    assert back.outcome == 'updates' and 'Picked points' in back.sentence and parent.asset_id in bob.held()


def test_a_well_log_needs_its_curves_and_reads_with_them(keyed, tmp_path):
    web = keyed
    alice = client(web, key(web, 'alice'))
    log = alice.upload_las(LAS_TEXT.encode(), name='Gamma log', attribution='Synthetic', audience=[], rights_confirmed=True)
    ex = alice.exchange(tmp_path / 'w')
    cannot = refused('cannot-read-here', lambda: ex.get(log.asset_id, output=tmp_path / 'o'))
    assert cannot.sentence == 'This kind of item cannot be received by this script yet: name the curves to receive a well log.'
    got = ex.get(log.asset_id, output=tmp_path / 'o', curves=['GR'])
    assert got.outcome == 'got' and (tmp_path / 'o/artifact.las').read_bytes() == LAS_TEXT.encode()
    assert got.sentence == 'Got Gamma log, version 1. You now hold it; saved in %s.' % (tmp_path / 'o')  # a single upload has no `history`: it is version 1


def test_a_newer_version_of_an_upload_is_detected_and_not_received(keyed, tmp_path):
    """Stop rule 9 (E53 merged): a real successor made by the upload-append writer."""
    from project_gateway.tests.test_section_types import WAVELET
    from project_gateway.tests.test_section_publication import WAVELET_2
    web = keyed
    alice = client(web, key(web, 'alice'))
    first = alice.upload_data(WAVELET, profile='wavelet-text/1', name='Wavelet', attribution='Synthetic', audience=[], rights_confirmed=True, command_id='e70a-w1')
    ex = alice.exchange(tmp_path / 'w')
    assert ex.get(first.asset_id, output=tmp_path / 'o').outcome == 'got'
    alice.upload_data(WAVELET_2, profile='wavelet-text/1', name='Wavelet', attribution='Synthetic', audience=[], rights_confirmed=True, command_id='e70a-w2',
                      append_to=first.asset_id, expected_parent=first.revision)
    assert ex.check().sentence.startswith('1 newer: Wavelet')
    cannot = refused('cannot-read-here', lambda: ex.get(first.asset_id, output=tmp_path / 'o'))
    assert cannot.sentence == 'This kind of item cannot be received by this script yet: a newer version of an uploaded file cannot be received yet.'
    assert (tmp_path / 'o/original').read_bytes() == WAVELET and ex.held()[first.asset_id]['revision'] == first.revision


def test_a_seismic_volume_is_described_not_received(keyed, tmp_path):
    from asset_connectors import segy
    web = keyed
    alice = client(web, key(web, 'alice'))
    cube = [[[float(i + j + k) for k in range(4)] for j in range(2)] for i in range(2)]
    volume = alice.upload_data(segy.write(None, cube, inlines=[1, 2], crosslines=[5, 6]), profile='segy/1', name='Cube', attribution='Synthetic',
                               audience=[], rights_confirmed=True, declared={'z_domain': 'time'})
    ex = alice.exchange(tmp_path / 'w')
    cannot = refused('cannot-read-here', lambda: ex.get(volume.asset_id, output=tmp_path / 'o'))
    assert cannot.sentence == 'This kind of item cannot be received by this script yet: a seismic volume is described here, not received; read its slices in Python.'
    assert ex.held() == {} and not (tmp_path / 'o').exists()
