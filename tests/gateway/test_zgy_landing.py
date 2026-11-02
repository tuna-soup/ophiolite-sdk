"""E123 SZ C4 (acceptance 4): a ZGY cube read on a person's computer with the packaged procedure "Read a ZGY cube on
your computer" lands, through the real upload and conversion routes of an in-process gateway, as one seismic volume.
tina registers the packaged procedure, alice enables it, bob uploads a folder holding the cube (it waits as "Can be
read on your computer") and reads it here: asked first (no CRS, no vertical domain, no horizontal unit: nothing is
declared to the server), then with the three settings it lands with the description written below by hand. The server
reads only the SEG-Y the procedure wrote; it never reads ZGY (`planned.json` keeps `zgy/1` deferred as a server reader).

Every literal is written by hand from the OpenZGY test cube (5 x 5 x 50 float, inlines 1-5, crosslines 20-24, 4 ms,
corners (0, 0) to (100, 100)) and the C3 decoding literals; none is computed from the code under test."""
import hashlib
import importlib.util
import os
import shutil
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, intake, zgy
from ophiolite.bundle import recorded_reading
from ophiolite.procedures import NotRun

CUBE = Path(__file__).resolve().parents[1] / 'fixtures' / 'zgy' / 'small-32bit.zgy'
CUBE_SHA256 = 'fdde06a818d1ae5c077f8d361cdb175cc4279be93ec1b39f892d265fc47d471e'
SETTINGS = ['crs=EPSG:23031', 'z_domain=time', 'horizontal_unit=m']


def openzgy():
    """pyzgy is in the dev install on Linux x86_64 only (segyio has no aarch64 wheel); elsewhere these cases do not apply."""
    return importlib.util.find_spec('openzgy') and __import__('openzgy.api', fromlist=['api'])


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


@pytest.fixture
def reading(world, tmp_path):
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    version = clients['tina'].procedure_register(zgy.PROCEDURE)
    clients['alice'].procedure_enable(version['digest'])

    def upload(name, make):
        folder = tmp_path / ('upload-' + name); folder.mkdir()
        make(folder / (name + '.zgy'))
        report = clients['bob'].upload_runs.upload(folder, attribution='OpenZGY test data (Equinor ASA), Apache-2.0', audience=[], rights_confirmed=True)
        return report, folder / (name + '.zgy')

    def read(report, path, settings=None, **options):
        return intake.read(clients['bob'], report.run_id, path, version=version['digest'], folder=tmp_path / ('state-' + path.stem),
                           cache=tmp_path / 'cache', settings=settings, yes=True, **options)
    return {**clients, 'digest': version['digest'], 'upload': upload, 'read': read}


def written(api, path, *, zunitdim, zunitname, zunitfactor, zstart, zinc, hunitdim=None, hunitname='', hunitfactor=1.0):
    import numpy
    with api.ZgyWriter(str(path), size=(2, 3, 4), datatype=api.SampleDataType.float, zunitdim=zunitdim, zunitname=zunitname,
                       zunitfactor=zunitfactor, zstart=zstart, zinc=zinc, hunitdim=hunitdim or api.UnitDimension.length,
                       hunitname=hunitname or 'm', hunitfactor=hunitfactor, annotstart=(10, 20), annotinc=(1, 1),
                       corners=((1000, 2000), (1025, 2000), (1000, 2050), (1025, 2050))) as writer:
        writer.write((0, 0, 0), numpy.arange(24, dtype=numpy.float32).reshape((2, 3, 4)))


def landed(reading, report, path, settings):
    result = reading['read'](report, path, settings, keep_original=True)
    assert result['conversion']['state'] == 'complete', result['conversion']
    [row] = result['report'].items
    [output] = row['outputs']
    assert (row['state'], output['role']) == ('converted', 'volume'), row
    return output, reading['bob'].read_data(output['asset_id'], output['revision'])


def test_the_cube_waits_is_asked_then_lands_as_one_seismic_volume(reading):
    if not openzgy(): return
    report, path = reading['upload']('small-32bit', lambda p: shutil.copyfile(CUBE, p))
    [row] = report.items
    assert row['state'] == 'needs-procedure' and [v['digest'] for v in row['procedures']] == [reading['digest']]
    with pytest.raises(NotRun) as asked: reading['read'](report, path)
    assert asked.value.code == 'asked' and 'Choose the coordinate system' in str(asked.value) and 'horizontal_unit=m' in str(asked.value)
    [still] = reading['bob'].upload_runs.status(report.run_id).items  # nothing was declared: no conversion row
    assert still['state'] == 'needs-procedure' and not still.get('outputs')
    output, volume = landed(reading, report, path, SETTINGS)
    c = volume.context
    assert (c['type'], c['inline'], c['crossline']) == ('seismic-volume', {'first': 1, 'last': 5, 'step': 1, 'count': 5},
                                                        {'first': 20, 'last': 24, 'step': 1, 'count': 5})
    assert (c['samples'], c['sample_interval'], c['sample_unit'], c['first_sample'], c['z_domain'], c['crs']) == (50, 4.0, 'ms', 0, 'time', 'EPSG:23031')
    assert (c['first_cdp'], c['last_cdp'], c['format_code']) == ({'x': 0, 'y': 0}, {'x': 100, 'y': 100}, 5)
    assert None not in c.values()
    first, last, middle = (reading['bob'].read_slice(output['asset_id'], output['revision'], 'inline', n, volume=volume) for n in (1, 5, 3))
    assert [round(float(v), 7) for v in first.values[0][:3]] == [1.1999998, 1.2000093, 1.2000198]
    assert round(float(last.values[4][49]), 5) == 5.24049 and round(float(middle.values[3][17]), 7) == 3.2301693
    assert round(float(middle.values[2][17]), 7) == 3.22017  # crossline 22 keeps its own trace (the twin small-32bit.sgy)
    read_by = recorded_reading(volume._wire_descriptor)
    assert read_by['original']['sha256'] == CUBE_SHA256 == hashlib.sha256(CUBE.read_bytes()).hexdigest()
    assert read_by['settings'] == {'crs': 'EPSG:23031', 'z_domain': 'time', 'horizontal_unit': 'm'}


def test_a_cube_in_feet_is_stopped_with_its_unit_and_nothing_is_declared(reading):
    api = openzgy()
    if not api: return
    report, path = reading['upload']('feet', lambda p: written(api, p, zunitdim=api.UnitDimension.time, zunitname='ms', zunitfactor=0.001,
                                                                 zstart=0.0, zinc=4.0, hunitname='ft', hunitfactor=0.3048))
    with pytest.raises(NotRun) as stop: reading['read'](report, path, SETTINGS)
    assert stop.value.code == 'procedure-stopped' and 'feet' in str(stop.value)
    [still] = reading['bob'].upload_runs.status(report.run_id).items
    assert still['state'] == 'needs-procedure' and not still.get('outputs')


def test_a_depth_cube_and_a_time_cube_starting_at_100_ms_land_as_stated(reading):
    api = openzgy()
    if not api: return
    report, path = reading['upload']('depth', lambda p: written(api, p, zunitdim=api.UnitDimension.length, zunitname='m', zunitfactor=1.0,
                                                                  zstart=0.0, zinc=5.0))
    _, depth = landed(reading, report, path, ['crs=EPSG:23031', 'z_domain=depth'])
    c = depth.context
    assert (c['samples'], c['sample_interval'], c['sample_unit'], c['first_sample'], c['z_domain']) == (4, 5.0, 'm', 0, 'depth')
    assert (c['first_cdp'], c['last_cdp'], c['inline']['first'], c['crossline']['last']) == ({'x': 1000, 'y': 2000}, {'x': 1025, 'y': 2050}, 10, 22)
    report, path = reading['upload']('late', lambda p: written(api, p, zunitdim=api.UnitDimension.time, zunitname='ms', zunitfactor=0.001,
                                                                 zstart=100.0, zinc=2.0))
    _, late = landed(reading, report, path, ['crs=EPSG:23031', 'z_domain=time'])
    assert (late.context['first_sample'], late.context['sample_interval'], late.context['sample_unit']) == (100, 2.0, 'ms')


def test_zgy_stays_a_deferred_server_reader_that_names_the_procedure():
    from asset_connectors import planned_readers
    row = planned_readers.entry('zgy/1')
    assert row['status'] == 'deferred' and 'Read a ZGY cube on your computer' in row['evidence']['reason']
