"""E162 s2a C1 (R9), in-process gateway lane: a wells table goes through the production wells import (E42a); the
accepted rows it kept are exported with Client.export into a bundle 2.17 beside the wells they locate, reopened offline
and compared with what the read routes serve. A kept copy that cannot be read now refuses the export, and nothing is
written; any other exact read refuses exactly as before."""
import hashlib

import pytest
from test_well_sources import imported, decide  # noqa: F401 (fixtures)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from ophiolite import bundle
from ophiolite.errors import OphioliteError


def kept(imported):
    """(asset, revision) of the kept rows, as the imported wells name them."""
    source = next(w.location['source'] for w in imported.alice.wells() if w.location)
    return source['asset_id'], source['revision']


def test_the_kept_rows_travel_with_the_wells_they_locate(imported, tmp_path):
    asset, revision = kept(imported)
    opened = imported.alice.export([(asset, revision, None)], tmp_path / 'b')
    assert opened.manifest['bundle_version'] == '2.17.0'
    [table] = opened.assets
    assert (table.type, table.asset_id, table.revision, table.entry['profile']) == ('well-table', asset, revision, 'sql-wells/1')
    assert hashlib.sha256(table.original).hexdigest() == revision
    assert [r['id'] for r in table.data.source_rows] == ['W-1', 'W-2'] and table.data.source_rows[0]['operator'] == 'Shell'  # the skipped row is not kept
    assert table.data.descriptor['reference']['revision'] == revision and table.data.descriptor['schema'] == 'ophiolite.source-snapshot/1'
    served = {w.entity_id: w for w in imported.alice.wells() if w.location}
    assert sorted(e.entity_id for e in opened.entities) == sorted(served)
    for entity in opened.entities:
        well = served[entity.entity_id]
        assert (entity.name, entity.identity) == (well.name, well.document['identity'])
        assert [(a, r, row) for a, r, row in entity.rows()] == [(asset, revision, well.location['source']['row'])]
    again = bundle.open_bundle(opened.path)  # offline, as a reader would
    assert [w['well_id'] for w in again.assets[0].data.wells] == ['W-1', 'W-2']
    [step] = bundle.import_plan(again, {})
    assert (step['state'], step['reason']) == ('refused', bundle.WELL_TABLE_RESTORED)


def test_a_wells_file_import_exports_its_kept_rows_too(web, tmp_path):
    """The landing's path (E87): a wells CSV through the table import keeps its rows the same way."""
    from test_well_sources import client
    alice = client(web, 'alice')
    path = tmp_path / 'wells.csv'
    path.write_bytes(b'id,name,x,y\r\nS-1,Synthetic 1,600000.5,6080000.25\r\nS-2,Synthetic 2,601000,6081000\r\n')
    done = alice.imports.from_table(path, 'wells', {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y'}, authority='synthetic',
                                    declarations={'crs': 'EPSG:23031', 'depth_unit': 'm', 'depth_kind': 'MD', 'depth_reference': 'unknown'})
    assert done['run']['state'] == 'complete', done['run']
    wells = [w for w in alice.wells() if w.location]
    source = wells[0].location['source']
    opened = alice.export([(source['asset_id'], source['revision'], None)], tmp_path / 'b')
    [table] = opened.assets
    assert (opened.manifest['bundle_version'], table.type) == ('2.17.0', 'well-table')
    assert [r['id'] for r in table.data.source_rows] == ['S-1', 'S-2'] and table.data.source_rows[0]['x'] == 600000.5
    assert sorted((e.name, e.rows()[0][2]) for e in opened.entities) == [('Synthetic 1', 'S-1'), ('Synthetic 2', 'S-2')]


def test_an_audience_member_exports_the_same_rows(imported, tmp_path):
    asset, revision = kept(imported)
    opened = imported.bob.export([(asset, revision, None)], tmp_path / 'b')
    assert opened.assets[0].original == imported.alice.export([(asset, revision, None)], tmp_path / 'a').assets[0].original


def test_a_withdrawn_copy_refuses_the_export_and_nothing_is_written(imported, tmp_path):
    asset, revision = kept(imported)
    decide(imported.web, 'withdraw', {'id': imported.release['id'], 'manifest_digest': imported.release['manifest_digest'], 'reason': 'E162 s2a test'})
    with pytest.raises(OphioliteError):
        imported.alice.export([(asset, revision, None)], tmp_path / 'b')
    assert not (tmp_path / 'b').exists()


def test_another_revision_of_the_kept_copy_refuses_as_its_exact_read_does(imported, tmp_path):
    asset, _ = kept(imported)
    with pytest.raises(OphioliteError) as before:
        imported.alice.read_data(asset, '0' * 64)
    with pytest.raises(type(before.value)) as now:
        imported.alice.export([(asset, '0' * 64, None)], tmp_path / 'b')
    assert (now.value.status, str(now.value)) == (before.value.status, str(before.value)) and not (tmp_path / 'b').exists()


def test_an_unknown_asset_refuses_exactly_as_before(imported, tmp_path):
    with pytest.raises(OphioliteError) as before:
        imported.alice.read_data('f' * 64, '0' * 64)
    with pytest.raises(type(before.value)) as now:
        imported.alice.export([('f' * 64, '0' * 64, None)], tmp_path / 'b')
    assert (type(now.value), now.value.status, str(now.value)) == (type(before.value), before.value.status, str(before.value))
