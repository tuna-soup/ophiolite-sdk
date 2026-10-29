"""E126a against the real gateway in process: WELL comes only from a well linked to the exact revision you may read,
and lasio-built files reach the project exactly (upload_las and publish_derived), missing samples staying missing."""
import math

import lasio
import pytest
import numpy as np
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.lasio import curves_from_lasio, lasio_bytes, to_lasio
from project_gateway.tests.test_applications import LAS


def plain(values):
    return [None if math.isnan(v) else float(v) for v in values]


def shared_log(alice, name):
    log = alice.upload_las(LAS.encode(), name=name, attribution='Synthetic', audience=['bob'], rights_confirmed=True)
    alice._post('las-uploads', 'share', {'asset_id': log.asset_id, 'audience': ['bob'], 'expected_generation': 1})
    return log


def well_of(reader, log, **options):
    return to_lasio(reader.read(log.asset_id, log.revision, ['GR']), **options).well['WELL'].value


def test_well_is_the_linked_well_you_may_read(web):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = shared_log(alice, 'Well log')
    assert well_of(bob, log) == '' and well_of(bob, log, well='A') == 'A'  # no association yet; never the header's SYNTHETIC
    well = alice.create_entity('well', 'W', authority='nlog', key='W-126', audience=['bob'], command_id='e126a-w')
    bore = alice.create_entity('wellbore', 'W-1', provisional=True, audience=['bob'], part_of=well, statement='Report', command_id='e126a-b')
    alice.of_entity(log.asset_id, log.revision, bore, statement='Header names the wellbore', command_id='e126a-a')
    assert well_of(bob, log) == 'W' and well_of(bob, log, well='A') == 'W' and well_of(alice, log) == 'W'


def test_a_well_hidden_from_you_is_not_named(web):
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    log = shared_log(alice, 'Well log')
    hidden = alice.create_entity('well', 'Hidden', authority='nlog', key='W-127', audience=[], command_id='e126a-hw')
    bore = alice.create_entity('wellbore', 'H-1', provisional=True, audience=['bob'], part_of=hidden, statement='Report', command_id='e126a-hb')
    alice.of_entity(log.asset_id, log.revision, bore, statement='Header names the wellbore', command_id='e126a-ha')
    assert bob.entity(bore.entity_id).well() is None  # the gateway leaves an unreadable parent out of part_of
    assert well_of(bob, log) == '' and well_of(alice, log) == 'Hidden'


def test_a_direct_well_link_names_the_well(web):
    alice = client(web, 'alice', 'delegate')
    log = shared_log(alice, 'Well log')
    well = alice.create_entity('well', 'Direct', authority='nlog', key='W-128', audience=[], command_id='e126a-dw')
    alice.of_entity(log.asset_id, log.revision, well, statement='Header names the well', command_id='e126a-da')
    assert well_of(alice, log) == 'Direct'


def test_a_link_on_an_earlier_revision_does_not_name_a_later_one(web):
    alice = client(web, 'alice', 'delegate')
    source = shared_log(alice, 'Source log')
    las = to_lasio(alice.read(source.asset_id, source.revision, ['GR']))
    first = alice.publish_derived(curves_from_lasio(las), name='Result', from_=[(source.asset_id, source.revision)], method={'name': 'copy'}, command_id='e126a-v1')
    las['GR'] = las['GR'] + 1
    second = alice.publish_derived(curves_from_lasio(las), name='Result', from_=[(source.asset_id, source.revision)], method={'name': 'copy'},
                                   command_id='e126a-v2', new_version_of=first.asset_id, expected_parent=first.revision)
    well = alice.create_entity('well', 'First only', authority='nlog', key='W-129', audience=[], command_id='e126a-fw')
    alice.of_entity(first.asset_id, first.revision, well, statement='Version 1 only', command_id='e126a-fa')
    assert well_of(alice, first) == 'First only' and well_of(alice, second) == ''


def test_lasio_built_files_reach_the_project_exactly(web):
    alice = client(web, 'alice', 'delegate')
    las = lasio.LASFile()
    las.append_curve('DEPT', np.array([100.0, 101.0, 102.0]), unit='M')
    las.append_curve('GR', np.array([0.1 + 0.2, np.nan, 1e-7]), unit='gAPI')
    las.append_curve('RHOB', np.array([2.5, 2.6, np.nan]), unit='g/cm3')
    las.well['NULL'].value = -999.25
    uploaded = alice.upload_las(lasio_bytes(las), name='Built in a notebook', attribution='Synthetic', audience=[], rights_confirmed=True)
    frame, meta = alice.read(uploaded.asset_id, uploaded.revision, ['GR', 'RHOB']).to_frame()
    assert list(frame.index) == [100.0, 101.0, 102.0] and plain(frame['GR']) == [0.30000000000000004, None, 1e-07] and plain(frame['RHOB']) == [2.5, 2.6, None]
    assert (meta.curves['GR'].unit, meta.curves['RHOB'].unit, meta.axis.unit) == ('gAPI', 'g/cm3', 'M')
    result = alice.publish_derived(curves_from_lasio(las), name='Derived in a notebook', from_=[(uploaded.asset_id, uploaded.revision)],
                                   method={'name': 'copy'}, command_id='e126a-rt')
    frame, meta = alice.read(result.asset_id, result.revision, ['GR', 'RHOB']).to_frame()
    assert list(frame.index) == [100.0, 101.0, 102.0] and plain(frame['GR']) == [0.30000000000000004, None, 1e-07] and plain(frame['RHOB']) == [2.5, 2.6, None]
    assert (meta.curves['GR'].unit, meta.curves['RHOB'].unit) == ('gAPI', 'g/cm3')


def test_find_log_reads_the_real_catalogue(web):
    from ophiolite.errors import Refused
    from ophiolite.writers import write_curves
    alice, bob = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate')
    short = shared_log(alice, 'L')  # three rows, shared with bob for reading only
    longer = alice.upload_las(write_curves([1, 2, 3, 4, 5], {'GR': ('gAPI', [1, 2, None, 4, 5])}, depth_unit='M').bytes, name='Longer',
                              attribution='Synthetic', audience=[], rights_confirmed=True)
    assert alice.find_log(curves=['GR'])['asset_id'] == longer.asset_id and alice.find_log(curves=['gr'], name='L')['asset_id'] == short.asset_id
    with pytest.raises(Refused, match=r"No log you may use-as-input matches curves \['GR'\]\."): bob.find_log(curves=['GR'])
    assert bob.find_log(curves=['GR'], operation='read')['asset_id'] == short.asset_id  # 'L' before the fixture's 'curve' at three rows each
    result = alice.publish_derived(write_curves([1, 2], {'GR': ('gAPI', [1, 2])}, depth_unit='M'), name='Declared', from_=[(short.asset_id, short.revision)],
                                   method={'name': 'm', 'parameters': {'outputs': {'GR': {'quantity': 'Gamma Ray'}}}}, command_id='e126a-q')
    assert alice.find_log(quantity='Gamma Ray')['asset_id'] == result.asset_id  # the two-row result: the uploads declare no quantity
