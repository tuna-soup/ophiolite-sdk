"""E192 s2: the SDK's `made_for` through the real gateway (s1 records it). An upload and a derived publication each
record the exact design version they were made for as a made-for row, stated by the sender, never a parent; a version
the sender cannot read is answered as an unknown version (404), and nothing is written.

Mutations: `made_for` dropped from `upload_metadata` or `derive_request` (publish.py) -> that route records no row."""
import json

import pytest

from test_exchange import key, client, points  # noqa: F401
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401
from ophiolite.errors import OphioliteError
from ophiolite.writers import WrittenOriginal


def made_for(web, asset, revision):
    with web.a.journal.lock:
        rows = web.a.journal.db.execute("SELECT object,actor FROM relationships WHERE subject_asset=? AND subject_revision=? AND predicate='made-for' "
                                        'ORDER BY object', (asset, revision)).fetchall()
    return [(json.loads(o), a) for o, a in rows]


def parents(web, asset, revision):
    with web.a.journal.lock:
        return web.a.journal.db.execute("SELECT count(*) FROM relationships WHERE subject_asset=? AND subject_revision=? AND predicate='derived-from' "
                                        'AND object LIKE ?', (asset, revision, '%synthetic-design%')).fetchone()[0]


@pytest.fixture
def design(keyed):
    web = keyed
    alice = client(web, key(web, 'alice'))
    d = points(5)
    made = alice.upload_data(d.bytes, profile=d.profile, declared=d.declared, name='synthetic-design', attribution='Synthetic', audience=[],
                             rights_confirmed=True, command_id='e192s2-design')
    return web, alice, made


def test_an_upload_and_a_derive_record_the_design_version_they_were_made_for(design):
    web, alice, d = design
    v = points(7)
    up = alice.upload_data(v.bytes, profile=v.profile, declared=v.declared, name='Synthetic estimate', attribution='Synthetic', audience=[],
                           rights_confirmed=True, command_id='e192s2-up', made_for=[(d.asset_id, d.revision)])
    rows = made_for(web, up.asset_id, up.revision)
    assert [(r['key'], r['revision'], actor) for r, actor in rows] == [(d.asset_id, d.revision, 'alice')]
    w = points(8)
    out = alice.publish_derived(WrittenOriginal(w.bytes, w.profile, dict(w.declared), 'derived.csv'), name='Synthetic derived estimate',
                                from_=[(up.asset_id, up.revision)], method={'name': 'synthetic'}, command_id='e192s2-derive',
                                made_for=[{'asset_id': d.asset_id, 'revision': d.revision}])
    rows = made_for(web, out.asset_id, out.revision)
    assert [(r['key'], r['revision'], actor) for r, actor in rows] == [(d.asset_id, d.revision, 'alice')]
    assert parents(web, out.asset_id, out.revision) == 0  # stated, never a parent


def test_an_exchange_send_records_the_version_its_first_answer_named(design, tmp_path):
    """The script's journey: `made_for(name=)` answers version 1 of the design and writes nothing; the design gets a
    version 2; the send with the answered version records version 1. Mutation: ClientTransport.publish not passing
    `made_for` (exchange.py) -> no row."""
    web, alice, d = design
    p = points(6)
    held = alice.upload_data(p.bytes, profile=p.profile, declared=p.declared, name='Synthetic picks', attribution='Synthetic', audience=[],
                             rights_confirmed=True, command_id='e192s2-held')
    ex = alice.exchange(tmp_path / 'w')
    ex.get(held.asset_id, output=tmp_path / 'picks')
    answer = ex.made_for(name='synthetic-design')
    assert answer.outcome == 'made-for' and answer.technical == {'asset_id': d.asset_id, 'revision': d.revision} and answer.facts['number'] == 1
    v2 = points(10)
    alice.upload_data(v2.bytes, profile=v2.profile, declared=v2.declared, name='synthetic-design', attribution='Synthetic', audience=[],
                      rights_confirmed=True, command_id='e192s2-design-2', append_to=d.asset_id, expected_parent=d.revision)
    s = points(11)
    done = ex.send(s.bytes, name='Synthetic estimate', profile=s.profile, declare=s.declared, how='by hand', based_on=[held.asset_id],
                   made_for=[answer.technical])
    assert done.outcome == 'sent-new', done.sentence
    rows = made_for(web, done.technical['asset_id'], done.technical['revision'])
    assert [(r['key'], r['revision']) for r, _ in rows] == [(d.asset_id, d.revision)]


def test_a_version_the_sender_cannot_read_is_an_unknown_version_and_nothing_is_written(design):
    web, alice, d = design
    bob = client(web, key(web, 'bob'))
    v = points(9)
    with web.a.journal.lock: before = web.a.journal.db.execute('SELECT count(*) FROM relationships').fetchone()[0]
    with pytest.raises(OphioliteError) as refused:
        bob.upload_data(v.bytes, profile=v.profile, declared=v.declared, name='Synthetic estimate', attribution='Synthetic', audience=[],
                        rights_confirmed=True, command_id='e192s2-bob', made_for=[(d.asset_id, d.revision)])
    assert refused.value.status == 404 and refused.value.code == 'not-found', (refused.value.status, refused.value.code, str(refused.value))
    with web.a.journal.lock: after = web.a.journal.db.execute('SELECT count(*) FROM relationships').fetchone()[0]
    assert after == before
