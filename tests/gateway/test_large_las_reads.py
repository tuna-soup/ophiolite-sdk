"""E100d1 A4 against the in-process gateway: a JSON-form LAS above 32 MiB is read by ranges (its digest verified), and a
curve stored as columns pages a level-0 window of 4,000 samples in two pages. Sync and async."""
import hashlib
import httpx
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import Credential
from project_gateway.tests.test_large_las import las

MIB = 1024 * 1024
UPLOAD = dict(attribution='Synthetic', audience=[], rights_confirmed=True)
CURVES = ['C%02d' % k for k in range(1, 64)]


def wide(rows):
    """64 declared curves (depth and 63 values), three decimals: C k at row i = ((i + k) mod 1000) / 1000."""
    head = ('~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.M 0 : start\nSTOP.M %s : stop\nSTEP.M 0.5 : step\n'
            'NULL. -999.25 : missing\nWELL. WIDE-1 : fixture\n~Curve\nDEPT.M : depth\n' % (0.5 * (rows - 1))
            + ''.join('%s.V : value %d\n' % (c, k) for k, c in enumerate(CURVES, 1)) + '~ASCII\n')
    values = ['%.3f' % (j * 0.001) for j in range(1000)]
    lines = ['%.1f ' % (0.5 * i) + ' '.join(values[(i + k) % 1000] for k in range(1, 64)) for i in range(rows)]
    return (head + '\n'.join(lines) + '\n').encode()


WIDE = wide(90_000)


@pytest.fixture
def requests(web, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * MIB))
    log = []
    web.c.event_hooks['request'].append(lambda request: log.append((request.url.path, request.url.query.decode(), request.headers.get('range'))))
    return log


def test_a_json_form_las_above_32_mib_is_read_by_ranges(web, requests):
    """Mutation: Client._artifact without ranges (the gateway answers 413 above 32 MiB: CapacityExceeded)."""
    assert 32 * MIB < len(WIDE) < 64 * MIB
    alice = client(web, 'alice', 'delegate')
    sent = alice.upload_las(WIDE, name='Wide', **UPLOAD)
    requests.clear()
    got = alice.read(sent.asset_id, sent.revision, ['C07'])
    assert got.artifact == WIDE and hashlib.sha256(got.artifact).hexdigest() == sent.revision
    ranges = [r for _, _, r in requests if r]
    assert ranges == ['bytes=%d-%d' % (i * 8 * MIB, (i + 1) * 8 * MIB - 1) for i in range(len(WIDE) // (8 * MIB) + 1)]
    assert len(got.curves[0].values) == 90_000 and got.curves[0].values[:3] == [0.007, 0.008, 0.009]


def windows(log):
    return [query for path, query, _ in log if path.endswith('/windows')]


def test_a_level_0_window_of_4000_samples_takes_two_pages(web, requests):
    """Mutation: the cursor not carried (Window.path) gives a repeated page, refused, or a short result."""
    alice = client(web, 'alice', 'delegate')
    sent = alice.upload_las(las(150_000), name='Columns', **UPLOAD)
    requests.clear()
    got = alice.curve_window(sent.asset_id, sent.revision, 'GR', 0, 1999.5, level=0)
    assert got.pages == 2 and got.sample_index == list(range(4000))
    first, second = windows(requests)
    assert 'cursor=' not in first and 'cursor=' in second


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.mark.anyio
async def test_the_async_client_reads_the_same_two_ways(web, requests):
    """Mutation: AsyncClient._artifact without ranges (CapacityExceeded)."""
    from ophiolite.aio import AsyncClient
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example') as http:
        async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            sent = await alice.upload_las(WIDE, name='Wide', **UPLOAD)
            got = await alice.read(sent.asset_id, sent.revision, ['C07'])
            assert got.artifact == WIDE and got.curves[0].values[:3] == [0.007, 0.008, 0.009]
            columns = await alice.upload_las(las(150_000), name='Columns', **UPLOAD)
            window = await alice.curve_window(columns.asset_id, columns.revision, 'GR', 0, 1999.5, level=0)
    assert window.pages == 2 and window.sample_index == list(range(4000))
