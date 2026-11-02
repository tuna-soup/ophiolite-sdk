"""E139 s2 (S2-6, S2-10) against the in-process gateway: a point set above 100,000 nodes is served as its stored columns
(`ophiolite.point-columns/1`); `read_data` reads them by ranges above the whole-answer bound (lowered here to 1 MiB so
3.2 MB of columns take four parts) and checks them as the Platform codec does, then the point-set rules, the source
identity, the context and the interpretation. Every refusal below changes one thing and recomputes the descriptor's
length and digest, so only the targeted check can refuse."""
import copy
import hashlib
import json
import struct

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import _ranges, validate
from ophiolite.errors import PermissionRefused, Unavailable, VerificationFailed
from ophiolite.typed import PointSet

MIB = 1024 * 1024
N = 100_005
DECLARED = {'crs': 'EPSG:28992', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'}
NAN = struct.pack('<Q', 0x7FF8000000000000)


def z(i): return None if i % 1000 == 999 else 1000 + i / 4


def points_csv():
    """x 500000 + 25 (i mod 400), y 25 (i div 400), z 1000 + i/4 (none at every 1000th), amp i mod 7."""
    rows = ['x,y,z,amp'] + ['%d,%d,%s,%d' % (500000 + 25 * (i % 400), 25 * (i // 400), '' if z(i) is None else repr(z(i)), i % 7) for i in range(N)]
    return ('\n'.join(rows) + '\n').encode()


@pytest.fixture
def served(web, monkeypatch):
    """The horizon landed for alice (the deployment admits 1,000,000 nodes); [asset, revision]; every request logged."""
    from project_gateway.las_uploads import LASUploads, Upload
    monkeypatch.setenv('OPHIOLITE_MAX_HORIZON_NODES', '1000000')
    landed = LASUploads(web.a).ingest(Upload(command_id='h-1', name='Big', profile='points-csv/1', declared=DECLARED, project_id='p', filename='big.csv',
                                             attribution='Synthetic', audience=[], rights_confirmed=True), points_csv(), 'alice')
    log = []
    web.c.event_hooks['request'].append(lambda request: log.append((request.url.path, request.headers.get('range'))))
    return landed['asset_id'], landed['revision'], log


@pytest.fixture
def small_bound(monkeypatch):
    monkeypatch.setattr(_ranges, 'WHOLE_BYTES', MIB); monkeypatch.setattr(_ranges, 'PART_BYTES', MIB)


def test_a_point_set_above_100000_nodes_is_read_from_its_columns_by_ranges(web, served, small_bound):
    """Mutation: read_data reading the data representation whole (the 1 MiB bound is not taken: no Range sent, the
    asked ranges below are missing) or the columns branch removed from typed_pair (refused as not JSON)."""
    asset, revision, log = served
    p = client(web, 'alice', 'delegate').read_data(asset, revision)
    data = next(r for r in p.descriptor.model_dump(by_alias=True)['representations'] if r['kind'] == 'normalized')
    assert (data['profile'], data['bytes']) == ('ophiolite.point-columns/1', len(p._wire_data_bytes))
    assert isinstance(p, PointSet) and p.data['schema'] == 'ophiolite.point-columns/1' and p.version == 1 and p.context['count'] == N
    assert p.points[0] == [500000.0, 0.0, 1000.0] and p.points[999] == [504975.0, 50.0, None] and p.points[-1] == [500100.0, 6250.0, 1000 + (N - 1) / 4]
    assert p.attributes == [{'name': 'amp', 'source_name': 'amp', 'kind': 'number'}] and p.data['attributes'][0]['values'][:8] == [0, 1, 2, 3, 4, 5, 6, 0]
    assert p.context['missing_z_count'] == 100 and p.context['z_range'] == [1000.0, 1000 + (N - 1) / 4]
    asked = [r for path, r in log if r and path.endswith('/representations/data')]
    assert 3 * MIB < data['bytes'] < 4 * MIB and asked == ['bytes=%d-%d' % (k * MIB, (k + 1) * MIB - 1) for k in range(4)]
    frame = p.to_frame()
    assert list(frame.columns) == ['x', 'y', 'z', 'amp'] and len(frame) == N and frame['z'].isna().sum() == 100


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.mark.anyio
async def test_the_async_client_reads_the_same_columns_by_ranges(web, served, small_bound):
    """Mutation: AsyncClient.read_data reading the data whole (no Range sent)."""
    import httpx
    from ophiolite import Credential
    from ophiolite.aio import AsyncClient
    asset, revision, _ = served
    log = []
    async def seen(request): log.append((request.url.path, request.headers.get('range')))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example', event_hooks={'request': [seen]}) as http:
        async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            p = await alice.read_data(asset, revision)
    assert p.data['schema'] == 'ophiolite.point-columns/1' and p.points[999] == [504975.0, 50.0, None] and len(p.points) == N
    assert [r for path, r in log if r and path.endswith('/representations/data')] == ['bytes=%d-%d' % (k * MIB, (k + 1) * MIB - 1) for k in range(4)]


@pytest.fixture
def wire(web, served):
    """The descriptor and the columns as served (whole, under the default bound)."""
    asset, revision, _ = served
    p = client(web, 'alice', 'delegate').read_data(asset, revision)
    return p._wire_descriptor, p._wire_data_bytes


def split(raw):
    size, = struct.unpack('<I', raw[8:12])
    return json.loads(raw[12:12 + size]), raw[12 + size:]


def joined(header, body, *, text=None):
    text = text or json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    return b'OPHPTS1\n' + struct.pack('<I', len(text)) + text + body


def sealed(descriptor, raw):
    """DESCRIPTOR with its normalized representation's length and digest recomputed for RAW, in the representation and in
    the revision manifest, whose digest is recomputed as `invariants.manifest` does (an upload's manifest is /1 or /2)."""
    d = copy.deepcopy(descriptor)
    rep = next(r for r in d['representations'] if r['kind'] == 'normalized')
    rep.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    m = d['manifest']
    assert m['schema'] in ('ophiolite.revision-manifest/1', 'ophiolite.revision-manifest/2')
    next(r for r in m['representations'] if r['id'] == rep['id']).update(bytes=rep['bytes'], sha256=rep['sha256'])
    body = {'schema': m['schema'], 'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': {'sha256': m['artifact']['sha256'], 'bytes': m['artifact']['bytes']},
            'representations': sorted(({'id': r['id'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in m['representations']), key=lambda r: r['id']),
            'lineage': sorted(e['commitment'] for e in m['lineage']), **({'method': m['method']} if 'method' in m else {})}
    m['digest'] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return d


def at(column, i): return (column * N + i) * 8  # the byte offset of value I of column number COLUMN in the body


def put(body, offset, value): return body[:offset] + value + body[offset + 8:]


def header_with(change):
    def mutate(header, body):
        h = copy.deepcopy(header); change(h); return joined(h, body)
    return mutate


DAMAGED = 'The point set’s columns are damaged.'
MUTATIONS = {
    'magic': (lambda h, b: b'OPHPTS2\n' + joined(h, b)[8:], DAMAGED),
    'header not canonical': (lambda h, b: joined(h, b, text=json.dumps(h, sort_keys=True).encode()), DAMAGED),
    'columns out of order': (header_with(lambda h: h.update(columns=['x', 'z', 'y', 'amp'])), DAMAGED),
    'one byte more': (lambda h, b: joined(h, b + b'\0'), DAMAGED),
    'count': (header_with(lambda h: h.update(count=N - 1)), DAMAGED),
    'another NaN for a missing z': (lambda h, b: joined(h, put(b, at(2, 999), struct.pack('<Q', 0x7FF8000000000001))), DAMAGED),
    'an infinite attribute': (lambda h, b: joined(h, put(b, at(3, 5), struct.pack('<d', float('inf')))), DAMAGED),
    'x missing': (lambda h, b: joined(h, put(b, at(0, 7), NAN)), DAMAGED),
    'x extent': (header_with(lambda h: h['context'].update(x_range=[500000.0, 509950.0])), 'Coordinates and their context disagree'),
    'missing z count': (header_with(lambda h: h['context'].update(missing_z_count=99)), 'Points and their context disagree'),
    'header contract': (header_with(lambda h: h['context'].update(z_meaning='sideways')), 'Scientific data does not satisfy the declared contract.'),
    'source digest': (header_with(lambda h: h.update(source_sha256='0' * 64)), 'Typed data and artifact source identities disagree'),
    'interpretation': (header_with(lambda h: h['interpretation'].update(null_policy='empty cells and NaN')),
                       'Descriptor scientific context or interpretation disagrees with the data'),
    'context': (header_with(lambda h: h['context'].update(vertical_datum='MSL')), 'Descriptor scientific context or interpretation disagrees with the data'),
}


def test_the_served_columns_pass_unchanged(wire):
    """The control for every refusal below: the served pair, resealed, is accepted."""
    descriptor, raw = wire
    header, body = split(raw)
    assert joined(header, body) == raw
    asset, value = validate.typed_pair(sealed(descriptor, raw), raw)
    assert value['schema'] == 'ophiolite.point-columns/1' and len(value['points']) == N


@pytest.mark.parametrize('case', sorted(MUTATIONS))
def test_a_changed_column_or_header_is_refused_by_its_own_check(wire, case):
    descriptor, raw = wire
    change, sentence = MUTATIONS[case]
    header, body = split(raw)
    changed = change(header, body)
    assert changed != raw
    with pytest.raises(VerificationFailed) as caught: validate.typed_pair(sealed(descriptor, changed), changed)
    assert caught.value.message == sentence


# --- S2-10: what the deployment answers to each range ------------------------------------------------------------------

@pytest.fixture
def answers(web, monkeypatch):
    """Rewrites the gateway's answer to the Kth ranged request for the data representation: CHANGE(request, response)."""
    transport = web.c._transport
    real = transport.handle_request
    plan = {}

    def handle(request):
        ranged = request.url.path.endswith('/representations/data') and request.headers.get('range')
        if ranged: plan['seen'] = plan.get('seen', 0) + 1
        change = plan.get(plan.get('seen')) if ranged else None
        if change is None: return real(request)
        return change(request, real)
    monkeypatch.setattr(transport, 'handle_request', handle)
    return plan


def rewritten(response, *, content=None, **headers):
    response.read()
    merged = {**dict(response.headers), **headers}
    merged.pop('content-length', None)
    return type(response)(response.status_code, headers=merged, content=response.content if content is None else content)


def resent(request, real, **headers):
    """REQUEST as sent, with HEADERS changed (a None value drops that header)."""
    kept = {k: v for k, v in request.headers.items() if k.lower() not in {h.lower() for h in headers}}
    return real(type(request)(request.method, request.url, headers={**kept, **{k: v for k, v in headers.items() if v is not None}}))


def read(web, served):
    asset, revision, log = served
    log.clear()
    return client(web, 'alice', 'delegate').read_data(asset, revision), [r for p, r in log if r and p.endswith('/representations/data')]


def test_a_short_part_is_continued_from_where_it_ended(web, served, small_bound, answers):
    """The second part answers half its bytes (its Content-Range saying so); the read goes on from there."""
    def short(request, real):
        response = real(request); response.read()
        first, last = (int(v) for v in response.headers['content-range'].split(' ')[1].split('/')[0].split('-'))
        total = response.headers['content-range'].split('/')[1]
        half = (last - first + 1) // 2
        return rewritten(response, content=response.content[:half], **{'content-range': 'bytes %d-%d/%s' % (first, first + half - 1, total)})
    answers[2] = short
    p, asked = read(web, served)
    assert len(p.points) == N and asked[:3] == ['bytes=0-1048575', 'bytes=1048576-2097151', 'bytes=1572864-2621439'] and len(asked) == 4


@pytest.mark.parametrize('case', ['overlapping', 'another total', 'another digest'])
def test_another_part_is_refused(web, served, small_bound, answers, case):
    """Mutation: Parts.accept without its start, total or digest check (the read goes on and fails later or not at all)."""
    def other(request, real):
        response = real(request); response.read()
        first_last, total = response.headers['content-range'].split(' ')[1].split('/')
        first, last = (int(v) for v in first_last.split('-'))
        if case == 'overlapping': return rewritten(response, **{'content-range': 'bytes %d-%d/%s' % (first - 8, last - 8, total)})
        if case == 'another total': return rewritten(response, **{'content-range': 'bytes %d-%d/%d' % (first, last, int(total) + 8)})
        return rewritten(response, **{'x-content-sha256': '0' * 64})
    answers[2] = other
    with pytest.raises(VerificationFailed) as caught: read(web, served)
    assert caught.value.message == _ranges.OTHER_PART


def test_a_range_the_deployment_ignores_is_refused(web, served, small_bound, answers):
    """The Range header is dropped on the way: the gateway answers the whole data with 200, which is not a part."""
    answers[1] = lambda request, real: resent(request, real, range=None)
    with pytest.raises(Unavailable) as caught: read(web, served)
    assert caught.value.status == 200


def test_a_changed_byte_in_a_part_fails_the_final_digest(web, served, small_bound, answers):
    """Every part's headers are right; one byte of the third is not. Mutation: typed_pair without its length/digest check."""
    def flipped(request, real):
        response = real(request); response.read()
        return rewritten(response, content=response.content[:-1] + bytes([response.content[-1] ^ 1]))
    answers[3] = flipped
    with pytest.raises(VerificationFailed) as caught: read(web, served)
    assert caught.value.message == 'Normalized representation unavailable or integrity mismatch'


def test_access_lost_between_parts_stops_the_read(web, served, small_bound, answers):
    """After the first part the reader is someone the item is not visible to (Eve, outside the project): the gateway's own
    answer to the second part is a refusal, and nothing is returned."""
    answers[2] = lambda request, real: resent(request, real, authorization='Bearer oph_api_eve:read,write')
    with pytest.raises(PermissionRefused) as caught: read(web, served)
    assert caught.value.status == 403
