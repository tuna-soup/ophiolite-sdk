"""E162 s2a C3 (D2), in-process gateway lane: ophiolite.restore over a bundle 2.17 exported by the production client
(a wells table, a log, tops and a survey bound to it, a grid). Wells first through the table import, then the logs and
grids, then the tops and surveys bound to the restored log, then the of-entity edges; a repeat returns the same
destinations and asserts nothing twice; a bundle outside the bounded shape is refused before anything is written."""
import hashlib

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from project_gateway.tests.test_applications import LAS
from ophiolite.errors import ImportIncomplete, Refused, RestoreIncomplete, Unavailable, ValidationFailed
from ophiolite.restore import restore, table_csv

WELLS = b'id,name,x,y\r\nS-1,Synthetic 1,600000.5,6080000.25\r\nS-2,Synthetic 2,601000,6081000\r\n'
DECLARED = {'crs': 'EPSG:23031', 'depth_unit': 'm', 'depth_kind': 'MD', 'depth_reference': 'unknown'}
TOPS = b'name,md\nTop A,100.5\nTop B,102\n'
SURVEY = b'md,inclination,azimuth\n100,0,0\n200,10,0\n'
GRID = b'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -1\n0 -1\n2 3\n'
ATTRIBUTION = 'Restored from a synthetic bundle'


def landed(web, tmp_path, bound=True, table=True):
    """alice's project as land.py leaves it, exported: (alice, bundle, the well S-1)."""
    alice = client(web, 'alice', 'delegate')
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / 'wells.csv'; path.write_bytes(WELLS)
    assert alice.imports.from_table(path, 'wells', {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y'}, authority='synthetic', declarations=DECLARED)['run']['state'] == 'complete'
    wells = {w.document['identity']['key']: w for w in alice.wells()}
    log = alice.upload_las(LAS.encode(), name='Log', attribution='Synthetic', audience=[], rights_confirmed=True)
    link = {'asset_id': log.asset_id, 'revision': log.revision} if bound else None
    tops = alice.upload_data(TOPS, profile='well-tops-csv/1', name='Tops', attribution='Synthetic', audience=[], rights_confirmed=True,
                             declared={'depth_unit': 'm', 'depth_basis': 'same-as-log'}, well_log=link)
    survey = alice.upload_data(SURVEY, profile='deviation-csv/1', name='Survey', filename='survey.csv', attribution='Synthetic', audience=[],
                               rights_confirmed=True, declared={'depth_unit': 'm', 'azimuth_reference': 'grid-north'}, well_log=link)
    grid = alice.upload_data(GRID, profile='esri-ascii-grid/1', name='Grid', attribution='Synthetic', audience=[], rights_confirmed=True,
                             declared={'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'})
    for a in (log, tops, survey): alice.of_entity(a.asset_id, a.revision, wells['S-1'].entity_id)  # (c): a person's of-entity on these revisions
    source = wells['S-1'].location['source']
    selections = [(log.asset_id, log.revision, ['GR']), (tops.asset_id, tops.revision, None), (survey.asset_id, survey.revision, None),
                  (grid.asset_id, grid.revision, None)] + ([(source['asset_id'], source['revision'], None)] if table else [])
    return alice, alice.export(selections, tmp_path / 'bundle'), wells['S-1']


def catalogue(alice):
    return sorted((i['asset_id'], i['revision']) for i in alice.assets())


def test_a_bundle_is_restored_wells_first_and_a_repeat_changes_nothing(web, tmp_path):
    alice, bundle, well = landed(web, tmp_path)
    digest = hashlib.sha256((bundle.path / 'manifest.json').read_bytes()).hexdigest()
    rows = restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True, expected_manifest_sha256=digest)
    assert [(r['type'], r['state']) for r in rows] == [('well-log', 'restored'), ('well-tops', 'restored'), ('trajectory', 'restored'),
                                                        ('regular-grid-surface', 'restored'), ('well-table', 'restored')]
    log, tops, survey, grid, table = [r['destination'] for r in rows]
    assert log['asset_id'] != bundle.assets[0].asset_id and log['revision'] == bundle.assets[0].revision  # a new upload of the same bytes
    now = {w.entity_id: w for w in alice.wells()}
    assert sorted(now) == sorted(e.entity_id for e in bundle.entities)  # the wells were here already: found by identity, none added
    assert table == {k: now[well.entity_id].location['source'][k] for k in ('asset_id', 'revision')} != {k: well.location['source'][k] for k in ('asset_id', 'revision')}
    for bound in (tops, survey):  # (b): bound to the restored log at its exact revision
        assert alice.read_data(bound['asset_id'], bound['revision']).relationships == {'well_log': log}
    held = {(i['asset_id'], i['revision']) for i in alice.data(well.entity_id)}
    assert {(d['asset_id'], d['revision']) for d in (log, tops, survey)} <= held
    restored = {(d['asset_id'], d['revision']) for d in (log, tops, survey)}  # E162 s2d: the sentence a well page shows, no digest
    assert {i['association']['evidence'].get('statement') for i in alice.data(well.entity_id) if (i['asset_id'], i['revision']) in restored} == {'Restored from the portable bundle.'}
    before, edges = catalogue(alice), len(alice.data(well.entity_id))
    again = restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True, expected_manifest_sha256=digest)
    assert [r['destination'] for r in again] == [r['destination'] for r in rows]
    assert catalogue(alice) == before and len(alice.data(well.entity_id)) == edges


def test_refusals_come_before_any_write(web, tmp_path):
    alice, bundle, _ = landed(web, tmp_path)
    before = catalogue(alice)
    with pytest.raises(ValidationFailed):
        restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=False)
    with pytest.raises(Refused, match='This bundle is not the expected one: its manifest has SHA-256 [0-9a-f]{64}, not 0{64}. Nothing was written.'):
        restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True, expected_manifest_sha256='0' * 64)
    assert catalogue(alice) == before


def test_a_bundle_without_its_wells_table_or_with_an_unbound_survey_is_refused(web, tmp_path):
    alice, bundle, _ = landed(web, tmp_path / 'a', table=False)
    with pytest.raises(Refused, match='This bundle holds no wells table'):
        restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True)
    alice, bundle, _ = landed(web, tmp_path / 'b', bound=False)
    before = catalogue(alice)
    with pytest.raises(Refused, match='well-tops [0-9a-f]+ is bound to no well log'):
        restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True)
    assert catalogue(alice) == before


def test_an_interrupted_restoration_reports_every_item_and_a_repeat_finishes(web, tmp_path, monkeypatch):
    alice, bundle, _ = landed(web, tmp_path)
    original = type(alice).upload_data
    def lost(self, *args, **kwargs):
        if kwargs.get('profile') == 'deviation-csv/1': raise Unavailable('The answer was lost')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(type(alice), 'upload_data', lost)
    with pytest.raises(RestoreIncomplete) as stopped:
        restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True)
    assert isinstance(stopped.value, ImportIncomplete)
    assert [(r['type'], r['state']) for r in stopped.value.details['assets']] == [('well-log', 'restored'), ('well-tops', 'restored'), ('trajectory', 'failed'),
                                                                                  ('regular-grid-surface', 'restored'), ('well-table', 'restored')]
    monkeypatch.setattr(type(alice), 'upload_data', original)
    done = restore(alice, bundle.path, audience=[], attribution=ATTRIBUTION, rights_confirmed=True)
    assert [r['state'] for r in done] == ['restored'] * 5 and done[0]['destination'] == stopped.value.details['assets'][0]['destination']


def test_the_kept_rows_are_written_again_in_column_order(web, tmp_path):
    _, bundle, _ = landed(web, tmp_path)
    table = next(a for a in bundle.assets if a.type == 'well-table').data
    assert table_csv(table) == b'id,name,x,y\r\nS-1,Synthetic 1,600000.5,6080000.25\r\nS-2,Synthetic 2,601000.0,6081000.0\r\n'
