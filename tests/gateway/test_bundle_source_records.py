"""E122 s5b C4: through the in-process gateway, an export carries each exact version's source record as the provenance
route serves it, and nothing else of the route's answer; an independent checker (`bundle_source_check`, no `ophiolite`
import) compares every carried record with the route. Expected records are literals written here, never read from the
code under test; the route is the comparison, not the source of the expectation."""
import copy
import hashlib
import json

import anyio
import httpx
import pytest

from test_exchange import two_keys, uploads, points, key, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_in_process_publish import client as persona
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from test_exchange_source import QGIS, send
from bundle_source_check import check
from ophiolite import Credential
from ophiolite.aio import AsyncClient
from project_gateway import source_provenance as sp
from project_gateway.tests.test_contracts_registry import ROOT
from project_gateway.tests.test_source_gone_agent import C, FOLDER, send as folder_send
from project_gateway.tests.test_upload_runs import RUN04

SCHEMA = json.loads((ROOT / 'scientific/v1/source-provenance.json').read_text())
RUN06 = FOLDER[2][1]


def sha(raw): return hashlib.sha256(raw).hexdigest()


def stored_context(web, asset, revision):
    """The version's own stored metadata digest, read from the rows (the record's `context`), never from the route."""
    db = web.a.journal.db
    storage = db.execute('SELECT storage_id FROM source_provenance WHERE asset_id=? AND revision=?', (asset, revision)).fetchone()[0]
    return sp.context_digest(json.loads(db.execute('SELECT metadata FROM retained_assets WHERE id=?', (storage,)).fetchone()[0]))


def qgis_record(web, asset, raw):
    return {'schema': 'ophiolite.source-provenance/1',
            'identity': {'source_system': 'application:qgis-plugin', 'source_instance': '/projects/groningen.qgz', 'id_scheme': 'source-native',
                         'source_object_id': {'container': 'layer-7', 'id': '42'}},
            'content': {'content_sha256': sha(raw), 'source_version': None},
            'context': {'comparison': 'comparison/1', 'context_sha256': stored_context(web, asset, sha(raw))}}


def path_record(web, asset, path, raw):
    """A folder sent as `Petrel export` (test_source_gone_agent.NAME): the source is named, the file by its path."""
    return {'schema': 'ophiolite.source-provenance/1',
            'identity': {'source_system': 'upload', 'source_instance': 'Petrel export', 'id_scheme': 'source-path', 'source_object_id': {'path': path, 'part': None}},
            'content': {'content_sha256': sha(raw), 'source_version': None},
            'context': {'comparison': 'comparison/1', 'context_sha256': stored_context(web, asset, sha(raw))}}


def route_of(web, token):
    def route(asset, revision):
        answer = web.c.get('/api/v1/projects/p/scientific-assets/%s/revisions/%s/provenance' % (asset, revision), headers={'Authorization': 'Bearer ' + token})
        if answer.status_code != 200: raise LookupError(answer.status_code)
        return answer.json()
    return route


def three(two_keys):
    """T1's versions: a QGIS send naming its object, a folder upload's LAS (source-path) and a send without a block."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    sent = send(a, points(7), parent, source=QGIS)
    qgis = (sent.technical['asset_id'], sent.technical['revision'])
    run = folder_send(web, FOLDER[1:2], 'f-1')  # alice's own upload run: TUM-03-S2/…04R_1.las
    las = (run['items'][0]['asset_id'], run['items'][0]['revision'])
    plain = (item, sha(v1.bytes))
    return web, ka, a.transport.client, qgis, las, plain


def test_t1_an_export_carries_exactly_the_records_the_route_serves(two_keys, tmp_path):
    web, ka, alice, qgis, las, plain = three(two_keys)
    opened = alice.export([(*qgis, None), (*las, ['GRS']), (*plain, None)], tmp_path / 'exported')
    assert opened.manifest['bundle_version'] == '2.10.0'
    entries = opened.manifest['assets']
    expected = [qgis_record(web, qgis[0], points(7).bytes), path_record(web, las[0], FOLDER[1][0], RUN04)]
    assert [e['source_record'] for e in entries[:2]] == [{'schema': 'ophiolite.source-provenance/1', 'asset_id': k[0], 'revision': k[1], 'record': r}
                                                         for k, r in zip((qgis, las), expected)]
    assert 'source_record' not in entries[2] and opened.assets[2].source_record is None
    route = route_of(web, ka['key'])
    assert [route(*k)['record'] for k in (qgis, las, plain)] == expected + [None]
    assert opened.summary()['source_records'] == 2 and 'source_records_omitted' not in opened.summary()
    assert check(opened.path, [qgis, las, plain], route, SCHEMA) == []


def test_t1b_each_exact_version_carries_its_own_record(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    first = send(a, points(7), parent, source=QGIS)
    second = send(b, points(8), parent, source=QGIS)
    asset = first.technical['asset_id']
    assert (second.technical['asset_id'], second.facts['number']) == (asset, 2)
    older, newer = sha(points(7).bytes), sha(points(8).bytes)
    alice = a.transport.client
    alone = alice.export([(asset, older, None)], tmp_path / 'older')
    assert alone.assets[0].source_record == qgis_record(web, asset, points(7).bytes)
    both = alice.export([(asset, newer, None), (asset, older, None)], tmp_path / 'both')
    assert [a.source_record['content']['content_sha256'] for a in both.assets] == [newer, older]
    assert [a.source_record for a in both.assets] == [qgis_record(web, asset, points(8).bytes), qgis_record(web, asset, points(7).bytes)]


def _broken(root, mutate):
    manifest = json.loads((root / 'manifest.json').read_text()); mutate(manifest)
    (root / 'manifest.json').write_text(json.dumps(manifest))


def test_t2_the_independent_checker_finds_each_kind_of_difference(two_keys, tmp_path):
    web, ka, alice, qgis, las, plain = three(two_keys)
    route = route_of(web, ka['key'])
    keys = [qgis, las, plain]
    opened = alice.export([(*qgis, None), (*las, ['GRS']), (*plain, None)], tmp_path / 'exported')
    assert check(opened.path, keys, route, SCHEMA) == []
    def case(name, mutate=None, expected=keys, answer=route):
        root = tmp_path / name; root.mkdir()
        (root / 'manifest.json').write_text((opened.path / 'manifest.json').read_text())
        if mutate: _broken(root, mutate)
        return check(root, expected, answer, SCHEMA)
    def digit(m):
        held = m['assets'][0]['source_record']['record']['content']; d = held['content_sha256']
        held['content_sha256'] = ('1' if d[0] != '1' else '2') + d[1:]  # another hex digit: the schema still holds
    assert case('digit', digit) == [('differs-from-route', qgis)]
    assert case('missing', lambda m: m['assets'][1].pop('source_record')) == [('record-missing', las)]
    assert case('unexpected', lambda m: m['assets'][2].update(source_record={'schema': 'ophiolite.source-provenance/1', 'asset_id': plain[0], 'revision': plain[1],
                                                                             'record': copy.deepcopy(m['assets'][0]['source_record']['record'])})) == [('record-unexpected', plain)]
    assert case('removed', lambda m: m['assets'].pop(2)) == [('inventory', plain)]
    assert case('duplicated', lambda m: m['assets'].append(copy.deepcopy(m['assets'][0]))) == [('inventory', qgis)]
    other = ('another-asset', 'f' * 64)
    assert case('distinct', lambda m: m['assets'].append(dict(copy.deepcopy(m['assets'][2]), asset_id=other[0], revision=other[1]))) == [('inventory', other)]
    assert case('wrapper', lambda m: m['assets'][0]['source_record'].update(words='From QGIS.')) == [('schema', qgis)]
    assert case('record schema', lambda m: m['assets'][1]['source_record']['record']['identity'].update(id_scheme='source-url')) == [('schema', las)]
    assert case('identity', lambda m: m['assets'][0]['source_record'].update(revision=las[1])) == [('identity', qgis)]
    def refusing(asset, revision):
        if (asset, revision) == las: raise LookupError(404)
        return route(asset, revision)
    assert case('refused', answer=refusing) == [('route-refuses', las)]


def test_t8_a_readable_version_without_a_record_carries_none(two_keys, tmp_path):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    alice = a.transport.client
    assert route_of(web, ka['key'])(item, sha(v1.bytes))['record'] is None
    opened = alice.export([(item, sha(v1.bytes), None)], tmp_path / 'exported')
    assert opened.assets[0].source_record is None and 'source_record' not in opened.manifest['assets'][0]
    assert opened.manifest['bundle_version'] == '2.2.0'  # a point set, nothing more: the version it had before records


def test_t12_only_the_record_travels_never_the_observation_gone_or_words(web, tmp_path):
    one = folder_send(web, FOLDER, 'p-1')
    folder_send(web, FOLDER[:2], 'p-3')  # C is not in this complete send: its item is marked gone
    item = next(i for i in one['items'] if i['ordinal'] == 2)
    answer = route_of(web, 'oph_api_alice:read')(item['asset_id'], item['revision'])
    assert answer['observation'] is not None and answer['gone'] is not None and answer['record'] is not None
    opened = persona(web, 'alice', 'delegate').export([(item['asset_id'], item['revision'], ['GR'])], tmp_path / 'exported')
    held = opened.manifest['assets'][0]['source_record']
    assert set(held) == {'schema', 'asset_id', 'revision', 'record'} and held['record'] == path_record(web, item['asset_id'], C, RUN06)
    text = (opened.path / 'manifest.json').read_text()
    assert answer['words'] not in text and answer['gone']['sentence'] not in text and json.dumps(answer['observation'])[1:-1] not in text
    assert 'declared_by' not in text and 'marked_at' not in text


def volume(web):
    from asset_connectors import segy
    alice = persona(web, 'alice', 'delegate')
    cube = [[[float(i * 10 + j + k) for k in range(3)] for j in range(2)] for i in range(2)]
    raw = segy.write(None, cube, inlines=[1, 2], crosslines=[5, 6])
    made = alice.upload_data(raw, profile='segy/1', name='Cube', attribution='Synthetic', audience=[], rights_confirmed=True, declared={'z_domain': 'time'})
    return alice, made


def test_t9_slice_exports_carry_the_volume_versions_record_sync_and_async(web, tmp_path):
    alice, made = volume(web)
    served = route_of(web, 'oph_api_alice:read')(made.asset_id, made.revision)['record']
    assert served is not None and served['content']['content_sha256'] == made.revision
    sync = alice.export_slices(made.asset_id, made.revision, [('inline', 1)], tmp_path / 'sync')
    assert sync.assets[0].source_record == served and sync.manifest['bundle_version'] == '2.10.0'
    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example') as http:
            async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as client:
                return await client.export_slices(made.asset_id, made.revision, [('crossline', 5)], tmp_path / 'async')
    opened = anyio.run(main)
    assert opened.assets[0].source_record == served and opened.manifest['bundle_version'] == '2.10.0'
    route = route_of(web, 'oph_api_alice:read')
    assert check(sync.path, [(made.asset_id, made.revision)], route, SCHEMA) == check(opened.path, [(made.asset_id, made.revision)], route, SCHEMA) == []
