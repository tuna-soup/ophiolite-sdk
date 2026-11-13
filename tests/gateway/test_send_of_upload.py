"""E70d C1 (was adhoc-e121-words2 B7): `send --of` naming one's own upload adds its next version by upload
(`las-uploads/upload` with `append_to`, E53), through the real gateway and ClientTransport. The project records who sent
it, with which key, how, and the version it builds on; the server decides whether bytes and declarations are new. A
Gateway that still meets an upload on the derive route (an older SDK) keeps B7's words for its author and today's for
anyone else (the kind of an item is not told to someone who did not upload it)."""
import hashlib
import json

import httpx
import pytest

from test_exchange import two_keys, both_routes, points, refused, key, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401
from ophiolite.errors import PermissionRefused

UPLOAD = 'An upload does not take a published version; publish this as a new result based on the upload'
TODAY = 'Only the author can add a version to this result, of the same type'
QGIS = {'system': 'application:qgis-plugin', 'instance': '/projects/groningen.qgz', 'container': 'layer-7', 'id': '42'}


def send(ex, parent, v, **over):
    return ex.send(v.bytes, **{'name': 'Picked points', 'profile': v.profile, 'declare': v.declared, 'how': 'picked again',
                               'based_on': [parent], 'of': parent, 'rights_confirmed': True, **over})


def history(web, made, parent):
    return client(web, made)._post('applications', 'result-history', {'asset_id': parent})['revisions']


def via(web, parent, revision):
    from project_gateway.scientific_api import ScientificAPI
    return ScientificAPI(web.a).call('describe', {'project_id': 'p', 'asset_id': parent, 'revision': revision}, 'alice')['display']['version']['via']


def test_send_of_ones_own_upload_adds_version_two_by_upload(two_keys):
    """S1, S2. Mutations: the supersedes edge not written (kernel.py `add`) -> red; the audience sent as the parent's -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = both_routes(web)
    v = points(3)
    exact = lambda revision: {'asset_id': parent, 'revision': revision, 'authority': 'ophiolite:uploaded'}
    audience = a.transport.client.grants(exact(a.held()[parent]['revision'])).recipients
    done = send(a, parent, v, source=QGIS)
    assert (done.outcome, done.sentence) == ('sent-version', 'Sent Picked points as version 2. Version 1 is kept.')
    assert [route for route, _ in seen] == ['upload'] and seen[0][1]['append_to'] == parent
    one, two = history(web, ka, parent)
    assert (two['number'], two['by'], two['parent_revision']) == (2, 'alice', one['revision'])
    db = web.a.journal.db
    edge = db.execute("SELECT object,evidence FROM relationships WHERE subject_asset=? AND subject_revision=? AND predicate='supersedes'",
                      (parent, two['revision'])).fetchone()
    assert json.loads(edge[0])['revision'] == one['revision'] and json.loads(edge[1]) == {'command_id': done.technical['command_id']}
    assert via(web, parent, two['revision'])['label'] == ka['label']
    assert a.transport.client.provenance(parent, two['revision']).words.startswith('From qgis-plugin, workspace `/projects/groningen.qgz`')
    assert sorted(a.transport.client.grants(exact(two['revision'])).recipients) == sorted(audience) == ['alice', 'bob']
    entry = a.held()[parent]
    assert (entry['kind'], entry['number'], entry['revision']) == ('uploaded', 2, two['revision'])


def test_a_second_folder_on_version_one_is_told_of_version_two(two_keys):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    send(a, parent, points(3))
    stale = refused('newer-version-exists', lambda: send(b, parent, points(4)))
    assert stale.sentence.startswith('Version 2 was added by ') and stale.sentence.endswith(
        'Your change was not sent. Either get version 2 and look at it, or send yours as a new item.')
    assert len(history(web, ka, parent)) == 2


def test_the_server_decides_sameness_on_bytes_and_declarations(keyed, tmp_path):
    """Codex 4a/4b. Mutations: `same_content` by digest -> A/D2 is refused before sending; the D4 adapter removed -> the
    repeat of A/D2 names version 1."""
    web = keyed
    made = key(web, 'alice')
    alice = client(web, made)
    raw, d1, d2 = b'x,y,z\n0,0,1\n10,5,2\n', {'crs': 'EPSG:28992', 'z_unit': 'm', 'z_meaning': 'depth'}, {'crs': 'EPSG:28992', 'z_unit': 'ft', 'z_meaning': 'depth'}
    up = alice.upload_data(raw, profile='points-csv/1', declared=d1, name='Picked points', attribution='Synthetic', audience=[],
                           rights_confirmed=True, command_id='e70d-decl')
    a, b = alice.exchange(tmp_path / 'a'), client(web, made).exchange(tmp_path / 'b')
    for ex, out in ((a, 'pa'), (b, 'pb')): ex.check(); ex.get(up.asset_id, output=tmp_path / out)
    go = lambda ex, declared: ex.send(raw, name='Picked points', profile='points-csv/1', declare=declared, how='redeclared', based_on=[up.asset_id],
                                      of=up.asset_id, rights_confirmed=True)
    assert go(a, d2).sentence == 'Sent Picked points as version 2. Version 1 is kept.'
    assert refused('nothing-changed', lambda: go(a, d2)).sentence == 'This is the same as version 2; nothing was sent.'
    back = refused('earlier-version', lambda: go(a, d1))
    assert back.sentence.startswith('This content was version 1 on ')
    stale = refused('newer-version-exists', lambda: go(b, {**d1, 'z_meaning': 'time'}))
    assert stale.sentence.startswith('Version 2 was added by ')
    assert len(history(web, made, up.asset_id)) == 2


def test_someone_else_is_refused_and_nothing_is_added(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    bob = client(web, key(web, 'bob')).exchange(tmp_path / 'bob'); bob.check(); bob.get(parent, output=tmp_path / 'pbob')
    seen = both_routes(web)
    refused('access-refused', lambda: send(bob, parent, points(3)))
    assert [route for route, _ in seen] == ['upload'] and len(history(web, ka, parent)) == 1


def test_a_lost_answer_is_recovered_with_one_version(two_keys, tmp_path):
    """Codex 4d. Mutation: a fresh command id on the retry -> a third version, or a recurrence refusal -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    drop = {'on': True}
    def lose(response):
        if drop['on'] and response.request.url.path.endswith('/las-uploads/upload'): raise httpx.ReadError('connection lost after commit')
    web.c.event_hooks['response'].append(lose)
    v = points(6)
    unknown = refused('outcome-unknown', lambda: send(a, parent, v))
    drop['on'] = False
    done = send(client(web, ka).exchange(tmp_path / 'a'), parent, v)
    assert done.outcome == 'sent-version' and done.technical['command_id'] == unknown.technical['command_id']
    assert [r['number'] for r in history(web, ka, parent)] == [1, 2]


def test_each_version_keeps_the_key_it_was_sent_with(two_keys, tmp_path, service):
    """Codex 4f. Mutation: the via copied from the head, or read from the key row now -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v2 = points(3)
    two = send(a, parent, v2)
    b.get(parent, output=tmp_path / 'pb')
    three = send(b, parent, points(4))
    with service.connect() as db: db.execute('UPDATE ab_access_keys SET label=%s WHERE id=%s', ('Renamed later', ka['id']))
    record = json.loads((tmp_path / 'a/held.json').read_text())  # version 2's send, replayed under its saved command
    request = {'name': 'Picked points', 'profile': v2.profile, 'how': 'picked again', 'based_on': [parent], 'of': parent, 'declare': dict(v2.declared),
               'extra': {}, 'sha256': hashlib.sha256(v2.bytes).hexdigest(), 'bytes': len(v2.bytes), 'rights_confirmed': True}
    record['pending'] = {'command_id': two.technical['command_id'], 'request': request, 'owner': a.transport.identity(), 'started': 0,
                         'resolved': {'parents': [], 'expected_parent': history(web, ka, parent)[0]['revision'], 'route': 'upload'}}
    (tmp_path / 'a/held.json').write_text(json.dumps(record))
    replayed = send(client(web, ka).exchange(tmp_path / 'a'), parent, v2)
    assert replayed.technical['revision'] == two.technical['revision']
    assert [via(web, parent, r)['label'] for r in (two.technical['revision'], three.technical['revision'])] == [ka['label'], kb['label']]
    assert len(history(web, ka, parent)) == 3


def test_a_profile_that_takes_no_version_by_upload_is_not_valid(two_keys):
    """The gateway checks the profile before the item (las_uploads `VERSIONED`), so a grid sent as the points' next
    version is the case. Mutation: the 422 relayed as "the request was not accepted" -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    caught = refused('not-valid', lambda: send(a, parent, points(3), profile='zmap-plus-grid/1',
                                                    declare={'crs': 'EPSG:28992', 'z_unit': 'm', 'z_meaning': 'depth'}))
    assert caught.sentence == 'The project refused this: this type of file does not take a new version by upload. Nothing was sent.'
    assert len(history(web, ka, parent)) == 1 and a._load()['pending'] is None


def publish(ex, parent, revision, command_id):
    """The publication itself, past the SDK's choice of route (an older SDK, or a client of its own)."""
    v = points(4)
    request = {'name': 'Picked points', 'profile': v.profile, 'how': 'edited', 'declare': v.declared, 'of': parent}
    with pytest.raises(PermissionRefused) as caught:
        ex.transport.publish(v.bytes, request, {'parents': [{'asset_id': parent, 'revision': revision}], 'expected_parent': revision}, command_id)
    return caught.value.server_message


def test_the_gateway_tells_the_uploads_author_and_nobody_else(two_keys, tmp_path):
    """Mutation: the author's words removed -> today's words -> red; the author test removed -> Bob reads them -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    revision = a._load()['items'][parent]['revision']
    assert publish(a, parent, revision, 'b7-alice') == UPLOAD
    bob = client(web, key(web, 'bob')).exchange(tmp_path / 'bob'); bob.check(); bob.get(parent, output=tmp_path / 'pbob')
    assert publish(bob, parent, revision, 'b7-bob') == TODAY
