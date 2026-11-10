"""E141 s3 C1 (acceptance 7), the client half: the D-K key events and the delegate's five minutes through `iter_window`,
sync and async, and `read_window` on a service account's key reading all three pieces of the long-read volume.

The deployment, the long-read volume, its literals (AGGREGATE, 3 pieces of 8 traces) and the stored-read trap are the
Platform's (`project_gateway.tests.test_volume_window_long_reads`): the real-credential gateway, keys made through its
routes and a real `oph_api_` delegate issued by `Automation.issue`. The SDK's piece bound is lowered with the server's
(the s1 recording's patch point, `volume_windows.BYTES_MAX`). Synthetic fixtures only (D75). After each event the SDK
raises the existing category for the server's 403 (`PermissionRefused`), the window is not complete, its digest is
None, and nothing stored is read for the refused piece."""
import asyncio
import os

import httpx
import pytest

try:
    from project_gateway.tests.real_credentials import ORIGIN, project as credentials  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests.test_service_accounts import p  # noqa: F401 (fixture)
    from project_gateway.tests import test_volume_window_long_reads as platform
    from project_gateway.tests.test_volume_window_long_reads import long as server  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential
from ophiolite import volume_windows as vw
from ophiolite.errors import PermissionRefused, Unavailable


@pytest.fixture
def long(server, monkeypatch):
    monkeypatch.setattr(vw, 'BYTES_MAX', platform.PIECE)
    return server


def expired_delegate(long, made):
    long.p.sql("UPDATE ab_api_credentials SET expires_at=now()-interval '1 second' WHERE id=%s", made['id'])


def ended_session(long, made):
    long.p.sql('''UPDATE ab_browser_sessions SET expires_at=now()-interval '1 second'
        WHERE id=(SELECT parent_session FROM ab_api_credentials WHERE id=%s)''', made['id'])


EVENTS = [(kind, event) for kind, event, _ in platform.EVENTS] + [('delegate', expired_delegate), ('delegate', ended_session)]
MODES = ['sync', 'async']


def credential_for(long, kind):
    made = {'personal': platform.personal, 'service': platform.service_key, 'delegate': platform.delegate}[kind](long)
    return made, made.get('key') or made['token']


def asked(long):
    """The window paths the in-process client asks (sync), after the volume's `/volume-windows`."""
    log = []
    long.p.c.event_hooks['request'].append(lambda request: '/volume-windows' in request.url.path and log.append(request.url.path.rsplit('/volume-windows', 1)[1]))
    return log


# --- read_window on a service key: all three pieces ----------------------------------------------------------------

@pytest.mark.parametrize('mode', MODES)
def test_read_window_on_a_service_key_reads_all_three_pieces(long, mode):
    """Mutation (Platform): `access_keys.authorize` refuses rows with an `account_id` (PermissionRefused, nothing read)."""
    key = platform.service_key(long)['key']
    if mode == 'sync':
        log = asked(long)
        got = Client(ORIGIN, 'p', Credential.bearer(key), long.p.c).read_window(long.info['asset_id'], long.info['revision'])
        assert log == ['', '/pieces/0', '/pieces/1', '/pieces/2']
    else:
        async def run():
            from ophiolite.aio import AsyncClient
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=long.p.app), base_url=ORIGIN) as http:
                async with AsyncClient(ORIGIN, 'p', Credential.bearer(key), http) as job:
                    return await job.read_window(long.info['asset_id'], long.info['revision'])
        got = asyncio.run(run())
    assert got.document['pieces'] == {'count': 3, 'traces_per_piece': 8, 'bytes_max': 512}
    assert got.window_digest == platform.AGGREGATE
    assert got.shape == [6, 4, 16]
    assert got.values[0][0][:3] == [100000.0, 100001.0, 100002.0] and got.values[5][3][15] == 603015.0  # i*100000 + (j-1)*1000 + k


# --- each event stops the next piece --------------------------------------------------------------------------------

@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('kind,event', EVENTS, ids=['%s-%s' % (k, e.__name__) for k, e in EVENTS])
def test_each_event_stops_iter_window_at_the_next_piece(long, kind, event, mode):
    """Mutations (Platform, the route-level file's): each D-K predicate and the delegate's two expiries; any of them
    lets piece 1 through and `next` returns it instead of raising."""
    made, credential = credential_for(long, kind)
    asset, revision = long.info['asset_id'], long.info['revision']
    if mode == 'sync':
        reader = Client(ORIGIN, 'p', Credential.bearer(credential), long.p.c).iter_window(asset, revision)
        first = next(reader)
        assert (first.index, first.count, first.traces, len(first.values)) == (0, 3, (0, 7), 8)
        event(long, made)
        long.seen.clear()
        with pytest.raises(PermissionRefused) as refused:
            next(reader)
        state = (refused.value.status, reader.complete, reader.window_digest)
    else:
        async def run():
            from ophiolite.aio import AsyncClient
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=long.p.app), base_url=ORIGIN) as http:
                async with AsyncClient(ORIGIN, 'p', Credential.bearer(credential), http) as job:
                    reader = await job.iter_window(asset, revision)
                    async with reader:
                        first = await reader.__anext__()
                        assert (first.index, first.count, first.traces, len(first.values)) == (0, 3, (0, 7), 8)
                        event(long, made)
                        long.seen.clear()
                        with pytest.raises(PermissionRefused) as refused:
                            await reader.__anext__()
                        return refused.value.status, reader.complete, reader.window_digest
        state = asyncio.run(run())
    assert state == (403, False, None)
    assert long.seen == []


# --- refused before the first byte (D-B), through the SDK ----------------------------------------------------------

BEFORE = [(platform.other_projects_key_on_p, PermissionRefused, 403), (platform.ps_asset_through_q, Unavailable, 404),
          (platform.outside_the_audience, Unavailable, 404)]


@pytest.mark.parametrize('case,error,status', BEFORE, ids=[c.__name__ for c, _, _ in BEFORE])
def test_read_window_asks_no_piece_when_the_document_is_refused(long, case, error, status):
    key, where = case(long)
    log = asked(long)
    long.seen.clear()
    with pytest.raises(error) as refused:
        Client(ORIGIN, where, Credential.bearer(key), long.p.c).read_window(long.info['asset_id'], long.info['revision'])
    assert refused.value.status == status
    assert log == [] and long.seen == []  # E140 s3: the description is read first, so the refusal comes before any window request


# --- E140 s3 C2: an 8-bit cube's windows through client and aio (acceptance 7, the client half) ---------------------
# The Platform's native world (test_native_windows): the s0 fixture cube and a second shape, published through the
# parts route (the gate open since C4); the windows, bounds and literal codes are that module's.

import hashlib  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from project_gateway.tests import test_native_windows as native  # noqa: E402
from project_gateway.tests.test_native_windows import native_world  # noqa: F401,E402 (fixture)
from project_gateway.payload_store import PayloadUnavailable  # noqa: E402
from project_gateway.scientific_api import ScientificAPI  # noqa: E402
from ophiolite.errors import Incompatible, VerificationFailed  # noqa: E402


def arguments(query):
    """read_window's keywords for a window query: one position as an int, a range as 'first:last'."""
    return {name: int(value) if value.lstrip('-').isdigit() else value for name, value in query}


def native_reader(world, info, query, mode, description=None):
    """(document, [(index, count, codes bytes)]) of every piece, through Client (sync) or AsyncClient."""
    key = world.p.key('alice', scope='read')
    asset, revision = info['asset_id'], info['revision']
    if mode == 'sync':
        reader = Client(ORIGIN, 'p', Credential.bearer(key), world.p.c).iter_window(asset, revision, description=description, **arguments(query))
        return reader.document, [(piece.index, piece.count, piece.raw) for piece in reader], reader

    async def run():
        from ophiolite.aio import AsyncClient
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.p.app), base_url=ORIGIN) as http:
            async with AsyncClient(ORIGIN, 'p', Credential.bearer(key), http) as job:
                reader = await job.iter_window(asset, revision, description=description, **arguments(query))
                async with reader:
                    return reader.document, [(piece.index, piece.count, piece.raw) async for piece in reader], reader
    return asyncio.run(run())


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('shape,bytes_max', native.BOUNDS, ids=['%s-%s' % b for b in native.BOUNDS])
def test_each_window_of_an_8_bit_cube_reads_its_literal_codes_through_the_sdk(native_world, monkeypatch, shape, bytes_max, mode):
    """Acceptance 7 (client half): every class of window, through `iter_window`, sync and async: the SDK asks
    `windows=2`, checks `/2`, and each piece's bytes are the literal codes (the last piece of the whole cube short).
    Mutations (Platform): width 4 kept in `plan`; the slot placement reversed; the piece count at width 4."""
    info = native_world.land(shape)
    if bytes_max:
        native.bounded(monkeypatch, bytes_max)
        monkeypatch.setattr(vw, 'BYTES_MAX', bytes_max)
    for name, query, inlines, crosslines, samples in native.windows_of(shape):
        traces = native.literal(shape, inlines, crosslines, samples)
        document, pieces, reader = native_reader(native_world, info, query, mode)
        per = document['pieces']['traces_per_piece']
        assert (document['schema'], document['samples']['width']) == ('ophiolite.volume-window/2', 1), name
        assert [(i, n) for i, n, _ in pieces] == [(i, len(pieces)) for i in range(-(-len(traces) // per))], name
        assert [raw for _, _, raw in pieces] == [b''.join(traces[i * per:(i + 1) * per]) for i in range(len(pieces))], name
        assert reader.complete and reader.window_digest == hashlib.sha256(b''.join(traces)).hexdigest(), name
        if name == 'whole' and bytes_max: assert len(pieces[-1][2]) < per * (samples[1] - samples[0] + 1)


def test_a_stored_description_with_another_undefined_code_is_refused_at_the_sdk_check(native_world):
    """Integrity: the document is the server's own, the description otherwise consistent but saying every code is a
    value (undefined_code None): the SDK refuses the window by name before asking any piece."""
    info = native_world.land('fixture')
    document, _, reader = native_reader(native_world, info, [], 'sync')
    described = reader.window.description
    mutated = vw.WindowDescription(described.asset, described.revision, described.geometry, dict(described.context, undefined_code=None))
    native_world.seen.clear()
    with pytest.raises(VerificationFailed, match="the code for no value is not the asset's"):
        native_reader(native_world, info, [], 'sync', description=mutated)
    assert native_world.seen == []


def test_a_piece_asked_again_after_a_503_is_the_same_bytes(native_world, monkeypatch):
    """Integrity: the store answers 503 once for piece 1; the SDK asks it again and gets the same bytes (the window
    digest is the literal codes')."""
    info = native_world.land('fixture')
    native.bounded(monkeypatch, 4 * 11)
    monkeypatch.setattr(vw, 'BYTES_MAX', 4 * 11)
    piece, failed = ScientificAPI.volume_piece, []

    def once(self, item, ident, observation, resolved, pieces, index):
        if index == 1 and not failed:
            failed.append(index)
            raise PayloadUnavailable('The payload store is unavailable')
        return piece(self, item, ident, observation, resolved, pieces, index)
    monkeypatch.setattr(ScientificAPI, 'volume_piece', once)
    log = asked(SimpleNamespace(p=native_world.p))
    _, pieces, reader = native_reader(native_world, info, [], 'sync')
    traces = native.literal('fixture', (0, 4), (0, 6), (0, 10))
    assert failed == [1] and log.count('/pieces/1') == 2
    assert b''.join(raw for _, _, raw in pieces) == b''.join(traces) and reader.window_digest == hashlib.sha256(b''.join(traces)).hexdigest()


def test_an_old_client_sees_the_sentence_without_the_parameter(native_world):
    """R21: a request without `windows=2` (as an SDK before s3 sends it) raises Incompatible whose rendered text is
    the sentence and remedy a person reads, with no `windows=2` and no contract id in it."""
    info = native_world.land('fixture')
    client = Client(ORIGIN, 'p', Credential.bearer(native_world.p.key('alice', scope='read')), native_world.p.c)
    with pytest.raises(Incompatible) as refused:
        client._window_json(vw.window_path(client.prefix, info['asset_id'], info['revision']))
    rendered = str(refused.value)
    assert refused.value.status == 422 and native.REFUSED_SENTENCE in rendered
    assert 'windows=2' not in rendered and 'volume-window/2' not in rendered
