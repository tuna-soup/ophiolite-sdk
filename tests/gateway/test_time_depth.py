"""E57: the Python route against an in-process gateway. PRW-06's checkshots (the NLOG workbook's 1,906 pairs, the
Platform fixture) are uploaded with their declarations, read back whole and as a DataFrame, linked to their wellbore,
exported with the link and planned for import with every declaration, the numeric one as its decimal text; a table
written in Python is published as a result of the same wellbore. Expected values are literals read from the workbook."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.bundle import import_plan, open_bundle
from ophiolite.errors import ValidationFailed
from ophiolite.typed import TimeDepth
from ophiolite.writers import write_time_depth
from project_gateway.tests.test_well_file_uploads import DECLARED, PRW06

UPLOAD = dict(attribution='NLOG.NL', audience=[], rights_confirmed=True)


def test_upload_read_link_export_and_publish(web, tmp_path):
    alice = client(web, 'alice', 'delegate')
    declared = {**DECLARED, 'seismic_reference_elevation': '12.5'}
    upload = alice.upload_data(PRW06, profile='time-depth-csv/1', name='PRW-06 checkshots', filename='prw06_checkshot.csv', declared=declared, **UPLOAD)
    table = alice.read_data(upload.asset_id, upload.revision)
    assert isinstance(table, TimeDepth) and len(table) == 1906 and table.original == PRW06
    assert table.pairs[1000] == (1029.5, 1000, 3463.13) and table.pairs[-1] == (2550.57, 1904.66, 3771.32)
    assert (table.context['seismic_reference_elevation'], table.context['datum']) == (12.5, 'unknown')
    try: import pandas  # noqa: F401 (the gateway lane may run without the pandas extra; the unit lane frames the fixture)
    except ImportError: pandas = None
    if pandas is not None:
        frame = table.to_frame()
        assert frame.shape == (1906, 3) and str(frame['velocity'].dtype) == 'Float64' and frame.iloc[1000].tolist() == [1029.5, 1000.0, 3463.13]

    well = alice.create_entity('well', 'PRW', authority='nlog', key='PRW-06', command_id='e57-w')
    bore = alice.create_entity('wellbore', 'PRW-06', provisional=True, part_of=well, statement='NLOG borehole PRW-06', command_id='e57-b')
    alice.of_entity(upload.asset_id, upload.revision, bore, statement='The NLOG workbook names PRW-06', command_id='e57-a')
    exported = alice.export([(upload.asset_id, upload.revision, None)], tmp_path / 'b')
    assert exported.manifest['bundle_version'] == '2.6.0'
    offline = open_bundle(tmp_path / 'b')
    assert [(a.asset_id, a.revision) for a in offline.assets_of(bore.entity_id)] == [(upload.asset_id, upload.revision)]  # the link travels
    [step] = import_plan(offline, {})
    assert (step['state'], step['profile']) == ('ready', 'time-depth-csv/1') and step['declared'] == declared  # 12.5 as its decimal text
    again = alice.upload_data(offline.assets[0].original, profile=step['profile'], name='PRW-06 checkshots (imported)', declared=step['declared'], **UPLOAD)
    assert alice.read_data(again.asset_id, again.revision).context['seismic_reference_elevation'] == 12.5

    every_100_ms = [(d, t) for d, t, _ in table.pairs if t % 100 == 0]
    written = write_time_depth(every_100_ms, **DECLARED)
    result = alice.publish_derived(written, name='PRW-06 every 100 ms', from_=[(upload.asset_id, upload.revision)], command_id='e57-derived',
                                   method={'name': 'Every 100 ms of two-way time', 'declared': False}, of_entity={'kind': 'wellbore', 'entity_id': bore.entity_id})
    read = alice.read_data(result.asset_id, result.revision)
    assert read.original == written.bytes and read.pairs == [(d, t, None) for d, t in every_100_ms] and len(read) == 20
    assert [x['entity']['entity_id'] for x in alice.associations(assets=[result.asset_id], kind='wellbore')] == [bore.entity_id]
    with pytest.raises(ValidationFailed, match='Declare the depth type'):
        write_time_depth(every_100_ms, **{**DECLARED, 'depth_type': None})
