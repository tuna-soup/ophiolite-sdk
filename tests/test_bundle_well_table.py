"""E162 s2a C1 (bundle 2.17): a bundle carries at most one wells table, the accepted rows a wells import kept
(sql-wells/1), exactly as kept beside the kept copy's source manifest. The check verifies the bytes against the
revision, the table with sources.verified_table, and every association of the table against its rows; import_plan
refuses it by name; released readers refuse the newer type; a bundle without one is unchanged. Everything is synthetic."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.errors import Refused, VerificationFailed
from test_bundle import rewrite, typed_read

SCHEMA = [{'name': 'id', 'type': 'TEXT'}, {'name': 'name', 'type': 'TEXT'}, {'name': 'x', 'type': 'REAL'}, {'name': 'y', 'type': 'REAL'}]
ROWS = [{'id': 'S-1', 'name': 'Synthetic 1', 'x': 4.1, 'y': 52.1}, {'id': 'S-2', 'name': 'Synthetic 2', 'x': 4.2, 'y': 52.2}]
MAPPING = {'entity': 'well', 'fields': {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y'}, 'crs': 'EPSG:4326', 'schema_digest': '0' * 64}
ASSET = 'a' * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def snapshot(rows=ROWS):
    wells = [{'well_id': r['id'], 'name': r['name'], 'operator': None, 'x': r['x'], 'y': r['y'], 'depth': None} for r in rows]
    return canonical({'schema': 'ophiolite.sql-wells/1', 'source_schema': SCHEMA, 'source_rows': rows, 'wells': wells, 'mapping': MAPPING})


def source(raw):
    revision = hashlib.sha256(raw).hexdigest()
    return {'schema': 'ophiolite.source-snapshot/1', 'reference': {'authority': 'synthetic', 'key': 'w', 'revision': revision, 'profile': 'sql-wells/1'},
            'metadata': {'kind': 'well', 'name': 'Synthetic wells'}, 'sha256': revision, 'bytes': len(raw), 'media_type': 'application/json',
            'contract': {}, 'losses': ['Synthetic loss'], 'scientific_validation': 'source-declared; review required'}


def table(raw=None):
    raw = raw or snapshot()
    return bundle.WellTable(raw, source(raw), 'Wells imported from Synthetic wells')


def well(n):
    return {'entity_id': 'well-%d' % n, 'kind': 'well', 'name': 'Synthetic %d' % n, 'identity': {'authority': 'synthetic', 'key': 'S-%d' % n, 'provisional': False}}


def items_and_graph(*more):
    read = table()
    items = [({'asset_id': ASSET, 'revision': read.revision, 'curves': None}, read), *more]
    edges = [{'predicate': 'of-entity', 'subject': {'kind': 'revision', 'asset_id': ASSET, 'revision': read.revision, 'row': 'S-%d' % n},
              'object': {'kind': 'well', 'entity_id': 'well-%d' % n}, 'evidence': None} for n in (1, 2)]
    return items, {'entities': [well(1), well(2)], 'relationships': edges}


def written(tmp_path, *more):
    items, graph = items_and_graph(*more)
    return bundle.write_bundle(tmp_path / 'b', items, graph=graph)


def test_a_wells_table_round_trips_at_2_17_with_its_rows_and_wells(tmp_path):
    opened = written(tmp_path)
    assert (opened.manifest['schema'], opened.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.17.0')
    [asset] = opened.assets
    assert (asset.type, asset.entry['profile'], asset.entry['origin'], asset.name) == ('well-table', 'sql-wells/1', 'retained-capture', 'Wells imported from Synthetic wells')
    assert sorted(f['path'] for f in asset.entry['files']) == ['assets/0/descriptor.json', 'assets/0/original.json']
    assert asset.original == snapshot() and asset.revision == hashlib.sha256(snapshot()).hexdigest()
    assert asset.data.source_rows == ROWS and [w['well_id'] for w in asset.data.wells] == ['S-1', 'S-2'] and asset.data.mapping == MAPPING
    assert asset.data.descriptor == source(snapshot()) and asset.entry['losses'] == ['Synthetic loss']
    assert [r[2] for r in opened.entity('well-2').rows()] == ['S-2']


def test_beside_other_types_the_minor_is_the_tables_and_a_bundle_without_one_is_unchanged(tmp_path):
    tops = typed_read('tops')
    opened = written(tmp_path, ({'asset_id': tops._wire_descriptor['asset_id'], 'revision': tops._wire_descriptor['revision'], 'curves': None}, tops))
    assert opened.manifest['bundle_version'] == '2.17.0' and [a.type for a in opened.assets] == ['well-table', 'well-tops']
    plain = bundle.write_bundle(tmp_path / 'plain', [({'asset_id': tops._wire_descriptor['asset_id'], 'revision': tops._wire_descriptor['revision'], 'curves': None}, tops)])
    assert plain.manifest['bundle_version'] == '2.0.0'  # S5: no table, the version and the bytes as before


def rewrite_file(root, relative, mutate):
    """Change one file and restate its digest and size, so only the check under test can refuse it."""
    path = root / relative; raw = mutate(path.read_bytes()); path.write_bytes(raw)
    def fix(m):
        for asset in m['assets']:
            for f in asset['files']:
                if f['path'] == relative: f.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    rewrite(root, fix)


def other_descriptor(raw):
    d = json.loads(raw); d['reference']['revision'] = '0' * 64
    return json.dumps(d).encode()


def first(m):
    return m['relationships'][0]


TAMPERS = {
    'an older minor': (lambda m: m.update(bundle_version='2.16.0'), 'needs bundle version 2.17'),
    'a row the table does not hold': (lambda m: first(m)['subject'].update(row='S-9'), bundle.WELL_TABLE_ROWS),
    'a row named twice': (lambda m: m['relationships'][1]['subject'].update(row=first(m)['subject']['row']), bundle.WELL_TABLE_ROWS),
    'the whole table associated': (lambda m: first(m)['subject'].pop('row'), bundle.WELL_TABLE_ROWS),
    'a well no row locates': (lambda m: m['entities'].append(well(3)), bundle.WELL_TABLE_WELLS),
    'a kept reading beside it': (lambda m: m['assets'][0].update(read_by={}), bundle.WELL_TABLE_SHAPE),
    'another profile': (lambda m: m['assets'][0].update(profile='table/1'), bundle.WELL_TABLE_SHAPE),
    'another origin': (lambda m: m['assets'][0].update(origin='source-reference'), 'disagrees with a wells table'),
}


@pytest.mark.parametrize('tamper', list(TAMPERS))
def test_every_inconsistent_wells_table_is_refused(tmp_path, tamper):
    opened = written(tmp_path)
    mutate, sentence = TAMPERS[tamper]
    rewrite(opened.path, mutate)
    with pytest.raises(VerificationFailed, match=re.escape(sentence)): bundle.open_bundle(opened.path)


def test_a_source_manifest_of_another_revision_is_refused(tmp_path):
    opened = written(tmp_path)
    rewrite_file(opened.path, 'assets/0/descriptor.json', other_descriptor)
    with pytest.raises(VerificationFailed, match=re.escape(bundle.WELL_TABLE_RECORD)): bundle.open_bundle(opened.path)


def test_kept_rows_that_are_not_the_named_revision_are_refused(tmp_path):
    opened = written(tmp_path)
    rewrite_file(opened.path, 'assets/0/original.json', lambda raw: raw.replace(b'Synthetic 1', b'Synthetic 9'))
    with pytest.raises(VerificationFailed, match='not the exact revision it names'): bundle.open_bundle(opened.path)


def test_rows_inconsistent_with_their_mapping_are_refused_before_anything_is_written(tmp_path):
    rows = snapshot().replace(b'"well_id":"S-2"', b'"well_id":"S-7"')
    with pytest.raises(VerificationFailed, match='inconsistent with their mapping'): table(rows)
    assert not (tmp_path / 'b').exists()


def test_two_wells_tables_are_refused_by_the_writer(tmp_path):
    items, graph = items_and_graph()
    other = table(snapshot(ROWS[:1]))
    items.append(({'asset_id': 'b' * 64, 'revision': other.revision, 'curves': None}, other))
    with pytest.raises(VerificationFailed, match=re.escape(bundle.WELL_TABLE_ONE)): bundle.write_bundle(tmp_path / 'b', items, graph=graph)
    assert not (tmp_path / 'b').exists()


def test_a_table_above_the_file_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', len(snapshot()) - 1)
    items, graph = items_and_graph()
    with pytest.raises(Refused, match='exceeds the supported size'): bundle.write_bundle(tmp_path / 'b', items, graph=graph)


def test_import_plan_refuses_the_table_by_name_and_plans_the_rest(tmp_path):
    tops = typed_read('tops')
    opened = written(tmp_path, ({'asset_id': tops._wire_descriptor['asset_id'], 'revision': tops._wire_descriptor['revision'], 'curves': None}, tops))
    table_step, tops_step = bundle.import_plan(opened, {})
    assert (table_step['state'], table_step['reason']) == ('refused', 'A wells table is restored with its wells (`ophiolite.restore`), not uploaded')
    assert tops_step['state'] in ('ready', 'refused') and tops_step['type'] == 'well-tops'


def test_a_released_reader_refuses_the_newer_type(tmp_path):
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_2_10_wt', Path(__file__).parent / 'frozen/bundle_2_10.py')
    frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    with pytest.raises(VerificationFailed, match='unknown type'): frozen.open_bundle(written(tmp_path).path)
