"""E192 s2b C4: a cost table kept as a file names the exact design version it was made for, through the real gateway.
The design's version is answered, a newer version is published before the import starts, and the kept table states
exactly the answered version (class stated, never a parent); the design's dependents list the table as stated; a retry
records it once. A version the sender cannot read is not found and nothing is kept; without made_for nothing is stated.

Mutations: the made-for row written as derived-from (table_landings `land`) -> parents non-empty and red; `made_for`
dropped from `_kept_upload` -> no stated parent."""
import json

import pytest

from test_exchange import key, client, points  # noqa: F401
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401
from ophiolite import exchange
from ophiolite.errors import OphioliteError

# synthetic, frozen by hand: six rows, one empty cost
COSTS = (b'section,item,cost,currency\r\n'
         b'wells,rig day,41000,EUR\r\n'
         b'wells,casing,12500,EUR\r\n'
         b'facilities,pump,8800,EUR\r\n'
         b'facilities,manifold,,EUR\r\n'
         b'survey,acquisition,23000,EUR\r\n'
         b'survey,processing,6400,EUR\r\n')


def rows(web, predicate, asset, revision):
    with web.a.journal.lock:
        found = web.a.journal.db.execute('SELECT object,actor FROM relationships WHERE subject_asset=? AND subject_revision=? AND predicate=? ORDER BY object',
                                         (asset, revision, predicate)).fetchall()
    return [(json.loads(o)['key'], json.loads(o)['revision'], a) for o, a in found]


@pytest.fixture
def design(keyed, tmp_path):
    web = keyed
    alice = client(web, key(web, 'alice'))
    d = points(5)
    made = alice.upload_data(d.bytes, profile=d.profile, declared=d.declared, name='synthetic-design', attribution='Synthetic', audience=[],
                             rights_confirmed=True, command_id='e192s2b-design')
    path = tmp_path / 'costs.csv'; path.write_bytes(COSTS)
    return web, alice, made, path


def kept(done):
    assert (done['run']['state'], done['preview']['target']) == ('complete', 'table'), done['run']
    unit = done['run']['units'][0]
    return unit['asset_id'], unit['revision']


def test_a_kept_table_states_the_answered_design_version(design, tmp_path):
    web, alice, d, path = design
    answer = alice.exchange(tmp_path / 'w').made_for(name='synthetic-design')
    assert answer.technical == {'asset_id': d.asset_id, 'revision': d.revision} and answer.facts['number'] == 1
    v2 = points(10)
    newer = alice.upload_data(v2.bytes, profile=v2.profile, declared=v2.declared, name='synthetic-design', attribution='Synthetic', audience=[],
                              rights_confirmed=True, command_id='e192s2b-design-2', append_to=d.asset_id, expected_parent=d.revision)
    assert newer.revision != d.revision
    done = alice.imports.from_table(path, 'table', made_for=[answer.technical], command_id='e192s2b-costs')
    table = kept(done)
    assert rows(web, 'made-for', *table) == [(d.asset_id, d.revision, 'alice')]
    assert rows(web, 'derived-from', *table) == []
    lineage = alice.lineage(*table)
    assert lineage['parents'] == [] and [(p['key'], p['revision']) for p in lineage['stated_parents']] == [(d.asset_id, d.revision)]
    assert lineage['stated_parent_visibility'] == 'complete'
    dependents = alice.dependents(d.asset_id, d.revision)
    found = [n for n in dependents['nodes'] if (n['asset_id'], n['revision']) == table]
    assert len(found) == 1 and found[0].get('stated') is True
    again = alice.imports.start(done['read'], 'table', {'fields': {}, 'declarations': {}}, preview_digest=done['preview']['preview_digest'],
                                command_id='e192s2b-costs', made_for=[answer.technical])  # the start retried after a lost answer
    assert again['id'] == done['run']['id'] and again['state'] == 'complete'
    assert rows(web, 'made-for', *table) == [(d.asset_id, d.revision, 'alice')]  # once


def test_a_version_the_sender_cannot_read_is_not_found_and_nothing_is_kept(design, tmp_path):
    web, alice, d, path = design
    bob = client(web, key(web, 'bob'))
    with web.a.journal.lock: before = web.a.journal.db.execute('SELECT count(*) FROM relationships').fetchone()[0]
    with pytest.raises(OphioliteError) as refused:
        bob.imports.from_table(path, 'table', made_for=[(d.asset_id, d.revision)])
    assert (refused.value.status, refused.value.code) == (404, 'not-found'), (refused.value.status, refused.value.code, str(refused.value))
    with web.a.journal.lock: after = web.a.journal.db.execute('SELECT count(*) FROM relationships').fetchone()[0]
    assert after == before
    t = points(6)
    alice.upload_data(t.bytes, profile=t.profile, declared=t.declared, name='synthetic-twin', attribution='Synthetic', audience=[],
                      rights_confirmed=True, command_id='e192s2b-twin-1')
    alice.upload_data(t.bytes, profile=t.profile, declared=t.declared, name='synthetic-twin', attribution='Synthetic', audience=[],
                      rights_confirmed=True, command_id='e192s2b-twin-2')
    with pytest.raises(exchange.REFUSALS['name-unclear']):
        alice.exchange(tmp_path / 'w').made_for(name='synthetic-twin')


def test_without_made_for_nothing_is_stated(design):
    web, alice, d, path = design
    table = kept(alice.imports.from_table(path, 'table'))
    assert rows(web, 'made-for', *table) == []
    assert 'stated_parents' not in alice.lineage(*table)
