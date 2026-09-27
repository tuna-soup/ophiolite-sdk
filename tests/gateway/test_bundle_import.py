"""E18: importing a portable bundle into a deployment through the ordinary upload route. Each
original becomes the importer's own private upload with the declared context and the bundle named
as provenance (not authority); relationships need an explicit mapping; slices have no original;
repeating an import returns the same assets."""
import hashlib
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.errors import PermissionRefused, Unavailable, ValidationFailed
from project_gateway.tests.test_applications import LAS

TOPS = b'name,md\nTop A,100.5\nTop B,102\n'
GRID = b'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -1\n0 -1\n2 3\n'


def test_a_bundle_imports_as_private_uploads_with_context_and_provenance(web, tmp_path):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = alice.upload_las(LAS.encode(), name='Exported log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    tops = alice.upload_data(TOPS, profile='well-tops-csv/1', name='Exported tops', attribution='Synthetic', audience=['bob'], rights_confirmed=True,
                             declared={'depth_unit': 'm', 'depth_basis': 'same-as-log'}, well_log={'asset_id': log.asset_id, 'revision': log.revision})
    grid = alice.upload_data(GRID, profile='esri-ascii-grid/1', name='Exported grid', attribution='Synthetic', audience=['bob'], rights_confirmed=True,
                             declared={'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'})
    for asset in (tops, grid): alice._post('las-uploads', 'share', {'asset_id': asset.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    bundle = bob.export([(log.asset_id, log.revision, ['GR']), (tops.asset_id, tops.revision, None), (grid.asset_id, grid.revision, None)], tmp_path / 'bundle')
    digest = hashlib.sha256((bundle.path / 'manifest.json').read_bytes()).hexdigest()
    with pytest.raises(ValidationFailed): bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=False)
    first = bob.import_bundle(bundle.path, audience=['viewer'], attribution='Imported from Alice\'s bundle', rights_confirmed=True)
    assert [(r['type'], r['state']) for r in first] == [('well-log', 'imported'), ('well-tops', 'refused'), ('regular-grid-surface', 'imported')]
    assert 'name the imported well log' in first[1]['reason']
    imported_log = first[0]['destination']
    assert imported_log['asset_id'] != log.asset_id and imported_log['revision'] == log.revision == hashlib.sha256(LAS.encode()).hexdigest()
    # With the mapping, the tops import and belong to the imported log at its exact revision.
    second = bob.import_bundle(bundle.path, audience=['viewer'], attribution='Imported from Alice\'s bundle', rights_confirmed=True,
                               well_logs={log.asset_id: (imported_log['asset_id'], imported_log['revision'])})
    assert [r['state'] for r in second] == ['imported', 'imported', 'imported']
    assert second[0]['destination'] == imported_log and second[2]['destination'] == first[2]['destination']  # repeating returns the same assets
    read = bob.read_data(second[1]['destination']['asset_id'], second[1]['destination']['revision'])
    assert [(t['name'], t['md']) for t in read.tops] == [('Top A', 100.5), ('Top B', 102.0)]
    assert read.context['depth_unit'] == 'm' and read.context['depth_basis'] == 'same-as-log'
    assert read.relationships == {'well_log': {'asset_id': imported_log['asset_id'], 'revision': imported_log['revision']}}
    grid_read = bob.read_data(second[2]['destination']['asset_id'], second[2]['destination']['revision'])
    assert grid_read.values == [0.0, None, 2.0, 3.0] and (grid_read.context['crs'], grid_read.context['z_meaning'], grid_read.context['positive']) == ('EPSG:28992', 'depth', 'down')
    acquisition = bob.read(imported_log['asset_id'], imported_log['revision'], ['GR'])._wire_descriptors[0]['acquisition']
    assert acquisition['identity'] == 'bob' and acquisition['origin'] == {'kind': 'portable-bundle', 'manifest_sha256': digest, 'asset_id': log.asset_id,
                                                                          'revision': log.revision, 'exporter': acquisition['origin']['exporter']}
    assert acquisition['origin']['exporter'].startswith('ophiolite-sdk')
    # Private to the importer: the audience is only the ceiling; Alice (not in it) and the viewer (not shared yet) cannot read.
    with pytest.raises((Unavailable, PermissionRefused)): client(web, 'viewer', 'delegate').read(imported_log['asset_id'], imported_log['revision'], ['GR'])
    with pytest.raises((Unavailable, PermissionRefused)): alice.read(imported_log['asset_id'], imported_log['revision'], ['GR'])
    # Re-exporting the imported asset carries its origin.
    again = bob.export([(imported_log['asset_id'], imported_log['revision'], ['GR'])], tmp_path / 'again')
    assert again.assets[0].curves['GR'].wire_descriptor['acquisition']['origin']['manifest_sha256'] == digest


def test_slices_have_no_original_to_import(web, tmp_path):
    from asset_connectors import segy
    alice = client(web, 'alice', 'delegate')
    cube = [[[float(i * 10 + j + k) for k in range(3)] for j in range(2)] for i in range(2)]
    raw = segy.write(None, cube, inlines=[1, 2], crosslines=[5, 6])
    volume = alice.upload_data(raw, profile='segy/1', name='Cube', attribution='Synthetic', audience=[], rights_confirmed=True, declared={'z_domain': 'time'})
    bundle = alice.export_slices(volume.asset_id, volume.revision, [('inline', 1)], tmp_path / 'slices')
    [result] = alice.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert result['state'] == 'refused' and 'no original' in result['reason']


def test_an_interrupted_import_reports_each_asset_and_a_repeat_finishes_without_duplicates(web, tmp_path, monkeypatch):
    from ophiolite.errors import ImportIncomplete
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    ups = [alice.upload_data(GRID, profile='esri-ascii-grid/1', name='Grid %d' % i, attribution='Synthetic', audience=['bob'], rights_confirmed=True,
                             declared={'crs': 'EPSG:28992'}, command_id='grid-%d' % i) for i in (1, 2)]
    log = alice.upload_las(LAS.encode(), name='Log', attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    for asset in (*ups, log): alice._post('las-uploads', 'share', {'asset_id': asset.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    bundle = bob.export([(ups[0].asset_id, ups[0].revision, None), (log.asset_id, log.revision, ['GR']), (ups[1].asset_id, ups[1].revision, None)], tmp_path / 'b')
    original = type(bob).upload_data; calls = []
    def flaky(self, *args, **kwargs):
        calls.append(kwargs['command_id'])
        if len(calls) == 2: raise Unavailable('The answer was lost')  # the upload may or may not have happened
        return original(self, *args, **kwargs)
    monkeypatch.setattr(type(bob), 'upload_data', flaky)
    with pytest.raises(ImportIncomplete) as stopped: bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert [a['state'] for a in stopped.value.details['assets']] == ['imported', 'failed', 'not attempted']
    monkeypatch.setattr(type(bob), 'upload_data', original)
    done = bob.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert [a['state'] for a in done] == ['imported'] * 3 and done[0]['destination'] == stopped.value.details['assets'][0]['destination']
    assert len({a['destination']['asset_id'] for a in done}) == 3
