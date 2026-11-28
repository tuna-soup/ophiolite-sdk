"""E211 s1 C7 (ruling 26 Nov, named scope): the bundle v2 manifest schema (2.20.0, additive) admits what this SDK's
writer writes. The released 2.17 bundle validates, every earlier released v2 bundle still validates, and a fresh
export with a wells table, row-scoped associations whose evidence is served with a null source or statement, and a
bundle that records why no wells travel validate too. Each addition is needed: the schema with that one addition taken
out refuses the bundle that uses it (the 2.17 bundle for the well-table type). Everything is synthetic.

Mutations, each named by the test that kills it: well-table removed from the type enum (the released bundles; the
fresh export); the subject's row removed, null taken from the evidence source or statement, or entities_omitted
removed (the fresh export and the additions)."""
import copy
import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
from ophiolite import bundle
from test_bundle import typed_read
from test_bundle_well_table import items_and_graph

RELEASED_DIR = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles'
SCHEMA = json.loads(files('ophiolite.contracts').joinpath('bundles/v2/manifest-schema.json').read_text())
ADDITIONS = ('well-table', 'row', 'null source', 'null statement', 'entities_omitted')


def without(addition, schema=SCHEMA):
    """The schema with one 2.20 addition taken out, as 2.19 had it."""
    schema = copy.deepcopy(schema)
    relation = schema['properties']['relationships']['items']['properties']
    evidence = relation['evidence']['anyOf'][1]['properties']
    if addition == 'well-table': schema['$defs']['BundleAssetV2']['properties']['type']['enum'].remove('well-table')
    elif addition == 'row': del relation['subject']['properties']['row']
    elif addition == 'null source': evidence['source']['type'] = 'object'
    elif addition == 'null statement': evidence['statement']['type'] = 'string'
    elif addition == 'entities_omitted': del schema['properties']['observations']['properties']['entities_omitted']
    return schema


def errors(manifest, schema=SCHEMA):
    return list(jsonschema.Draft202012Validator(schema).iter_errors(manifest))


def released(version):
    return json.loads((RELEASED_DIR / version / 'manifest.json').read_text())


V2 = sorted((p.name for p in RELEASED_DIR.iterdir() if p.name.startswith('2.') and (p / 'manifest.json').is_file()), key=lambda v: int(v.split('.')[1]))


def test_the_schema_is_two_twenty():
    assert SCHEMA['x-ophiolite'] == {'id': 'ophiolite.portable-bundle/2', 'version': '2.20.0', 'lifecycle': 'preview'}


@pytest.mark.parametrize('version', V2)
def test_every_released_v2_bundle_validates(version):
    assert errors(released(version)) == []


def test_the_released_two_seventeen_bundle_needs_the_well_table_type():
    assert '2.17' in V2 and [a['type'] for a in released('2.17')['assets']] == ['well-table']
    assert errors(released('2.17'), without('well-table'))
    for addition in ADDITIONS[1:]: assert errors(released('2.17'), without(addition)) == []  # it uses no other addition


def fresh(tmp_path):
    """A fresh export: a wells table with two row-scoped associations, one whose evidence names a source and no
    statement and one whose evidence has neither, as the gateway serves them; and a tops bundle without wells."""
    items, graph = items_and_graph()
    first, second = graph['relationships']
    first['evidence'] = {'source': {'asset_id': first['subject']['asset_id'], 'revision': first['subject']['revision']}, 'statement': None}
    second['evidence'] = {'source': None, 'statement': None}
    table = bundle.write_bundle(tmp_path / 'table', items, graph=graph)
    tops = typed_read('tops')
    plain = bundle.write_bundle(tmp_path / 'plain', [({'asset_id': tops._wire_descriptor['asset_id'], 'revision': tops._wire_descriptor['revision'], 'curves': None}, tops)],
                                entities_omitted='not requested')
    return [json.loads((tmp_path / name / 'manifest.json').read_text()) for name in ('table', 'plain')], (table, plain)


def test_a_fresh_export_validates_and_needs_each_addition(tmp_path):
    (table, plain), opened = fresh(tmp_path)
    assert (table['bundle_version'], plain['schema']) == ('2.17.0', bundle.SCHEMA_2)  # the writer still names the lowest minor
    assert plain['observations'] == {'entities_omitted': 'not requested'}
    assert errors(table) == [] and errors(plain) == []
    for addition in ADDITIONS:
        assert errors(plain if addition == 'entities_omitted' else table, without(addition)), addition
    assert [len(o.assets) for o in opened] == [1, 1]  # the writer's own check read both back


def test_the_additions_only_widen():
    """Nothing became required and every earlier v2 bundle passes the schema with all five taken out as well."""
    relation = SCHEMA['properties']['relationships']['items']
    assert relation['required'] == ['predicate', 'subject', 'object', 'evidence'] and relation['properties']['subject']['required'] == ['kind']
    assert 'required' not in SCHEMA['properties']['observations']
    old = SCHEMA
    for addition in ADDITIONS: old = without(addition, old)
    for version in V2:
        if version != '2.17': assert errors(released(version), old) == [], version
