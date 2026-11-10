"""E168 s1 C2 against the in-process gateway (charter acceptance 1, the SDK half): a well log (its matrix row has a
kind) and a point set (its row has none, with the matrix's reason) read through describe, read().to_frame(),
read_data (sync and async), Entity.assets() and associations() say what the gateway served. The served pair is
swapped for one the packaged matrix does not hold, so a value the SDK filled in from its own copy fails."""
import json
import types

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from project_gateway.tests.test_applications import LAS
from ophiolite import osdu

WELL_LOG = 'osdu:wks:work-product-component--WellLog:1.5.0'
HORIZON = 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'
FILE_ROWS = json.loads(osdu.MATRIX.read_text(encoding='utf-8'))['rows']
REASON = next(r['none'] for r in FILE_ROWS if r['profile'] == 'points-csv/1')
DECLARED = {'crs': 'EPSG:28992', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'}
POINTS = b'x,y,z\n500000,0,1000\n500025,0,1001\n500050,25,1002\n'


@pytest.fixture
def landed(web):
    """alice's las2/1 log and points-csv/1 set, both associated with one wellbore."""
    from project_gateway.las_uploads import LASUploads, Upload
    alice = client(web, 'alice', 'delegate')
    log = alice.upload_las(LAS.encode(), name='Well log', attribution='Synthetic', audience=[], rights_confirmed=True)
    points = LASUploads(web.a).ingest(Upload(command_id='k-1', name='Points', profile='points-csv/1', declared=DECLARED, project_id='p',
                                             filename='points.csv', attribution='Synthetic', audience=[], rights_confirmed=True), POINTS, 'alice')
    bore = alice.create_entity('wellbore', 'K-1', authority='nlog', key='K-100-1', audience=[], command_id='k-b')
    alice.of_entity(log.asset_id, log.revision, bore, statement='Header names K-1', command_id='k-a1')
    alice.of_entity(points['asset_id'], points['revision'], bore, statement='Survey of K-1', command_id='k-a2')
    return alice, (log.asset_id, log.revision), (points['asset_id'], points['revision']), bore


@pytest.fixture
def swapped(monkeypatch):
    """The gateway serves HORIZON for las2/1 (a valid kind its matrix row does not hold); every other profile as before."""
    from project_gateway import contracts_registry
    contracts_registry.osdu_pair('las2/1')  # load the real lookup first
    real = contracts_registry._OSDU_KIND
    fake = types.SimpleNamespace(pair=lambda p: {'osdu_kind': HORIZON, 'osdu_kind_reason': None} if p == 'las2/1' else real.pair(p))
    monkeypatch.setattr(contracts_registry, '_OSDU_KIND', fake)


def pair_of(found):
    get = found.get if isinstance(found, dict) else lambda k: getattr(found, k)
    return get('osdu_kind'), get('osdu_kind_reason')


def reads(alice, log, points, bore):
    """(name, (osdu_kind, osdu_kind_reason)) for every SDK surface."""
    frame, meta = alice.read(*log, ['GR']).to_frame()
    typed = alice.read_data(*points)
    items = {i['asset_id']: i for i in bore.assets()}
    bulk = {i['asset_id']: i for i in alice.associations()}
    return {'describe': pair_of(alice.describe(*log, 'GR')), 'frame': pair_of(meta),
            'frame attrs': pair_of(meta.attach(frame).attrs['ophiolite']),
            'entity log': pair_of(items[log[0]]), 'associations log': pair_of(bulk[log[0]]),
            'read_data points': pair_of(typed), 'typed attrs': pair_of(typed.attach(typed.to_frame()).attrs['ophiolite']),
            'entity points': pair_of(items[points[0]]), 'associations points': pair_of(bulk[points[0]])}


def expected(log_kind):
    return {name: ((log_kind, None) if name.endswith('log') or name.startswith(('describe', 'frame')) else (None, REASON))
            for name in ('describe', 'frame', 'frame attrs', 'entity log', 'associations log', 'read_data points', 'typed attrs',
                         'entity points', 'associations points')}


def test_every_sdk_read_says_the_kind_and_the_no_kind_reason_the_gateway_served(web, landed):
    pytest.importorskip('pandas')
    assert reads(*landed) == expected(WELL_LOG)


def test_the_sdk_shows_the_served_kind_verbatim_when_it_differs_from_its_own_matrix(web, landed, swapped):
    pytest.importorskip('pandas')
    assert osdu.profiles_for(WELL_LOG)[0] == 'las2/1'  # the packaged matrix still says WellLog
    assert reads(*landed) == expected(HORIZON)


@pytest.mark.anyio
async def test_the_async_client_reads_the_same_pair(web, landed):
    import httpx
    from ophiolite import Credential
    from ophiolite.aio import AsyncClient
    _, _, points, _ = landed
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example') as http:
        async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            typed = await alice.read_data(*points)
    assert pair_of(typed) == (None, REASON)
