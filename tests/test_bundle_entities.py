"""E20 (bundle 2.4): entities and relationships travel with the exact revisions they concern; the
reader checks every edge against the registry and the bundle's contents, and navigates offline.
Released 2.x readers ignore the added keys."""
import copy
import importlib.util
import json
import pytest
from ophiolite import bundle
from ophiolite.errors import VerificationFailed
from test_bundle import Read, typed_items, rewrite

WELL = {'entity_id': 'well-1', 'kind': 'well', 'name': 'W', 'identity': {'authority': 'nlog', 'key': 'W-1', 'provisional': False}}
BORE = {'entity_id': 'wellbore-1', 'kind': 'wellbore', 'name': 'W-1 main', 'identity': {'authority': None, 'key': None, 'provisional': True}}


def graph(items):
    edges = [{'predicate': 'of-entity', 'subject': {'kind': 'revision', 'asset_id': c['asset_id'], 'revision': c['revision']}, 'object': {'kind': 'wellbore', 'entity_id': 'wellbore-1'},
              'evidence': {'source': {'asset_id': c['asset_id'], 'revision': c['revision']}}} for c, _ in items[:2]]
    edges.append({'predicate': 'part-of', 'subject': {'kind': 'wellbore', 'entity_id': 'wellbore-1'}, 'object': {'kind': 'well', 'entity_id': 'well-1'}, 'evidence': None})
    return {'entities': [WELL, BORE], 'relationships': edges}


def test_entities_travel_and_navigate_offline(tmp_path):
    items = typed_items(); g = graph(items)
    opened = bundle.write_bundle(tmp_path / 'b', items, graph=g)
    assert opened.manifest['bundle_version'] == '2.4.0' and [e.entity_id for e in opened.entities] == ['well-1', 'wellbore-1']
    bore = opened.entity('wellbore-1')
    assert {(a.asset_id, a.revision) for a in opened.assets_of(bore)} == {(c['asset_id'], c['revision']) for c, _ in items[:2]}  # stated independently above
    assert [a.type for a in opened.assets_of(bore, profile='well-tops-csv/1')] == ['well-tops'] and bore.well_id() == 'well-1'
    assert [e.entity_id for e in opened.wellbores('well-1')] == ['wellbore-1']
    plain = bundle.write_bundle(tmp_path / 'plain', [items[0]])  # no entities: exactly as before (1.0 for curves)
    assert plain.manifest['bundle_version'] == '1.0.0' and 'entities' not in plain.manifest and plain.entities == []


@pytest.mark.parametrize('tamper', ['unexported revision', 'predicate swap', 'missing well', 'unregistered', 'system predicate', 'duplicate entity', 'curve bundle'])
def test_every_inconsistent_edge_is_refused(tmp_path, tamper):
    items = typed_items(); opened = bundle.write_bundle(tmp_path / 'b', items, graph=graph(items))
    def edit(m):
        edges, ents = m['relationships'], m['entities']
        if tamper == 'unexported revision': edges[0]['subject']['revision'] = '0' * 64  # a real asset, another revision
        if tamper == 'predicate swap': edges[-1]['predicate'] = 'of-entity'  # entity subject for a revision predicate
        if tamper == 'missing well': m['entities'] = [e for e in ents if e['kind'] != 'well']
        if tamper == 'unregistered': edges[0]['predicate'] = 'near'
        if tamper == 'system predicate': edges[0]['predicate'] = 'derived-from'
        if tamper == 'duplicate entity': ents.append(copy.deepcopy(ents[0]))
        if tamper == 'curve bundle': m['schema'] = bundle.SCHEMA; m['bundle_version'] = '1.0.0'
    rewrite(opened.path, edit)
    with pytest.raises(VerificationFailed): bundle.open_bundle(opened.path)


@pytest.mark.parametrize('frozen', ['bundle_2_1', 'bundle_2_2'])
def test_released_readers_read_a_populated_2_4_bundle(tmp_path, frozen):
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_' + frozen, Path(__file__).parent / ('frozen/%s.py' % frozen))
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    items = typed_items(); opened = bundle.write_bundle(tmp_path / 'b', items, graph=graph(items))
    old = reader.open_bundle(opened.path)
    assert [a.revision for a in old.assets] == [a.revision for a in opened.assets]
