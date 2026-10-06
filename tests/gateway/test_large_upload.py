"""E54 C5: the SDK sends a file above the request limit in parts (resuming with the same command), passes the
deployment's sentences on, and reads an original back by ranges into a file that appears only when every byte matched."""
import base64
import hashlib
import json
import struct
import tracemalloc

import httpx
import numpy as np
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, session, ORIGIN  # noqa: F401
from test_exchange import key, client as key_client, points, refused
from asset_connectors.segy import write
from ophiolite import Client, Credential
from ophiolite.errors import CapacityExceeded, IntegrityConflict, Refused, Unavailable, VerificationFailed

MIB = 1024 * 1024
DECLARED = {'crs': 'EPSG:23031', 'z_domain': 'time'}
SAVE = dict(name='Large volume', attribution='Synthetic', audience=['bob'], rights_confirmed=True)


def volume(inlines, crosslines, samples):
    """A big-endian IEEE volume, inline i crossline j sample k = i*100000 + (j-1)*1000 + k."""
    length = 240 + 4 * samples
    out = [bytes(write(None, [[[0.0] * samples]], inlines=[1], crosslines=[1], code=5)[:3600])]
    for i in range(1, inlines + 1):
        block = np.zeros((crosslines, length), np.uint8)
        block[:, 70:72] = np.frombuffer(struct.pack('>h', 1), np.uint8)
        block[:, 188:192] = np.frombuffer(struct.pack('>i', i), np.uint8)
        block[:, 192:196] = np.arange(1, crosslines + 1, dtype='>i4').view(np.uint8).reshape(crosslines, 4)
        block[:, 240:] = (i * 100000 + np.arange(crosslines)[:, None] * 1000 + np.arange(samples)[None, :]).astype('>f4').view(np.uint8)
        out.append(block.tobytes())
    return b''.join(out)


FORTY = volume(98, 100, 1000)  # 39.6 MiB: four parts of 8 MiB and a last of 7.6 MiB


@pytest.fixture
def large(web, monkeypatch, tmp_path):
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * MIB))
    path = tmp_path / 'volume.sgy'; path.write_bytes(FORTY)
    log = []
    def record(request):
        if request.url.path.endswith('/las-uploads/part'):
            log.append(('part', json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))['index']))
        else: log.append(request.url.path.rsplit('/', 2)[-2] + '/' + request.url.path.rsplit('/', 1)[-1])
    web.c.event_hooks['request'].append(record)
    return web, path, log


def test_a_forty_mebibyte_volume_resumes_after_a_lost_connection_and_reads_back_exactly(large, tmp_path):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    def cut(request):
        if request.url.path.endswith('/las-uploads/part') and json.loads(base64.b64decode(request.headers['x-ophiolite-upload']))['index'] == 3:
            raise httpx.ConnectError('the connection dropped')
    web.c.event_hooks['request'].append(cut)
    with pytest.raises(Unavailable): alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='forty', **SAVE)
    assert [e for e in log if e[0] == 'part'] == [('part', 0), ('part', 1), ('part', 2)] + [('part', 3)] * 3
    web.c.event_hooks['request'].remove(cut); log.clear()
    result = alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='forty', **SAVE)
    assert [e for e in log if e[0] == 'part'] == [('part', 3), ('part', 4)]
    assert log[0] == 'las-uploads/begin' and log[-1] == 'las-uploads/publish' and 'las-uploads/finish' in log
    assert result.revision == hashlib.sha256(FORTY).hexdigest()
    (tmp_path / 'saved').mkdir()
    saved = alice.download_original(result.asset_id, result.revision, tmp_path / 'saved' / 'copy.sgy')
    assert saved.read_bytes() == FORTY and [p.name for p in (tmp_path / 'saved').iterdir()] == ['copy.sgy']
    assert alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='forty', **SAVE).asset_id == result.asset_id  # the same command again
    inline = alice.read_slice(result.asset_id, result.revision, 'inline', 5)
    assert list(inline.values[0][:3]) == [500000.0, 500001.0, 500002.0]


def test_an_interrupted_or_tampered_download_leaves_no_file(large, tmp_path, monkeypatch):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    result = alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='forty', **SAVE)
    target = tmp_path / 'out' ; target.mkdir()
    calls = []
    def dropped(request):
        if request.url.path.endswith('/representations/artifact'):
            calls.append(1)
            if len(calls) == 2: raise httpx.ConnectError('the connection dropped')
    web.c.event_hooks['request'].append(dropped)
    with pytest.raises(Unavailable): alice.download_original(result.asset_id, result.revision, target / 'copy.sgy')
    assert list(target.iterdir()) == []
    web.c.event_hooks['request'].remove(dropped)
    get = alice._get
    def tampered(path, limit, **options):
        raw = get(path, limit, **options)
        return (b'\0' if raw[:1] != b'\0' else b'\1') + raw[1:] if options.get('ranged', '').startswith('bytes=%d-' % (8 * MIB)) else raw
    monkeypatch.setattr(alice, '_get', tampered)
    with pytest.raises(IntegrityConflict, match='^The downloaded original does not match the file the deployment holds; nothing was saved\\.$'):
        alice.download_original(result.asset_id, result.revision, target / 'copy.sgy')
    assert list(target.iterdir()) == []


def test_a_damaged_part_is_sent_once_more_and_a_second_damage_is_the_deployments_sentence(large, monkeypatch):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    from ophiolite import publish
    header, damaged = publish.part_header, []
    def damaging(project, upload_id, index, raw):  # the digest of other bytes: the part arrives damaged
        if index == 1 and len(damaged) < times: damaged.append(index); raw = b'x' + raw[1:]
        return header(project, upload_id, index, raw)
    monkeypatch.setattr(publish, 'part_header', damaging)
    times = 1
    result = alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='once', **SAVE)
    assert [e for e in log if e[0] == 'part'] == [('part', 0), ('part', 1), ('part', 1), ('part', 2), ('part', 3), ('part', 4)]
    assert result.revision == hashlib.sha256(FORTY).hexdigest()
    times, damaged[:] = 2, []; log.clear()
    with pytest.raises(Refused) as caught: alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='twice', **SAVE)
    assert (caught.value.message, caught.value.code) == ('Part 2 arrived damaged twice. Check your connection and continue.', 'part-corrupt')
    assert [e for e in log if e[0] == 'part'] == [('part', 0), ('part', 1), ('part', 1)]


@pytest.mark.parametrize('change', ['first', 'digest'])
def test_a_range_answer_for_other_bytes_saves_nothing(large, tmp_path, monkeypatch, change):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    result = alice.upload_data(path, profile='segy/1', declared=DECLARED, command_id='forty', **SAVE)
    target = tmp_path / 'out'; target.mkdir()
    get = alice._get
    def other(path, limit, **options):
        raw = get(path, limit, **options)
        if options['ranged'].startswith('bytes=%d-' % (16 * MIB)):
            answer = options['answer']
            if change == 'first': answer['content-range'] = answer['content-range'].replace('bytes %d-' % (16 * MIB), 'bytes %d-' % (8 * MIB))
            else: answer['x-content-sha256'] = '0' * 64
        return raw
    monkeypatch.setattr(alice, '_get', other)
    with pytest.raises(VerificationFailed, match='^The deployment answered another part of the file\\.$'):
        alice.download_original(result.asset_id, result.revision, target / 'copy.sgy')
    assert list(target.iterdir()) == []


def test_the_deployments_sentences_reach_the_caller(large, tmp_path, monkeypatch):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    big = tmp_path / 'big.sgy'
    with big.open('wb') as out: out.truncate(65 * MIB)
    with pytest.raises(CapacityExceeded) as caught: alice.upload_data(big, profile='segy/1', declared=DECLARED, **SAVE)
    assert caught.value.message == 'This file is 65 MiB. This deployment accepts files up to 64 MiB. Ask your administrator to raise the limit, or crop the volume.'
    assert caught.value.code == 'file-too-large'
    cut = tmp_path / 'cut.sgy'; cut.write_bytes(FORTY[:9 * MIB])  # the last trace stops short
    from project_gateway.las_uploads import LASUploads, LASValidationError
    with pytest.raises(LASValidationError) as reader:
        LASUploads(web.a).validate(FORTY[:9 * MIB], {'authority': 'ophiolite:uploaded', 'key': 'k', 'revision': '0' * 64, 'profile': 'segy/1'}, DECLARED, cap=9 * MIB)
    with pytest.raises(Refused) as caught: alice.upload_data(cut, profile='segy/1', declared=DECLARED, **SAVE)
    assert (caught.value.message, caught.value.code) == (str(reader.value), 'not-a-volume')


def test_a_small_file_is_still_one_request(large):
    web, path, log = large
    alice = client(web, 'alice', 'delegate')
    log.clear()
    grid = b'ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -1\n0 -1\n2 3\n' + b' ' * MIB
    alice.upload_data(grid, profile='esri-ascii-grid/1', declared={'crs': 'EPSG:28992'}, **SAVE)
    assert log == ['las-uploads/upload']


def test_send_above_the_served_limit_is_too_large(keyed, tmp_path):
    web = keyed
    alice = key_client(web, key(web, 'alice'))
    base = points(1)
    parent = alice.upload_data(base.bytes, profile=base.profile, declared=base.declared, name='Picked points', attribution='Synthetic',
                               audience=['bob'], rights_confirmed=True, command_id='e54-parent')
    ex = alice.exchange(tmp_path / 'a'); ex.check(); ex.get(parent.asset_id, output=tmp_path / 'pa')
    large = refused('too-large', lambda: ex.send(b'x' * (9 * MIB), name='Large points', profile=base.profile, declare=base.declared, how='kriging', based_on=[parent.asset_id]))
    assert large.sentence == 'The file is larger than this project accepts. Nothing was sent.'


class Fake:
    """A gateway that answers the parts protocol and keeps nothing: what the client holds is all that is measured."""
    def __init__(self, size, part=8 * MIB):
        self.size, self.part, self.received = size, part, []

    def __call__(self, request):
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'describe': return httpx.Response(200, json={'limits': {'upload_bytes': self.part, 'file_bytes': 64 * MIB}})
        parts = -(-self.size // self.part)
        view = {'upload_id': 'a' * 64, 'state': 'open', 'parts': parts, 'part_bytes': self.part, 'received': []}
        if name == 'begin': self.sha = json.loads(request.content)['sha256']; return httpx.Response(200, json=view)
        if name == 'part': self.received.append(len(request.content)); return httpx.Response(200, json=view)
        if name == 'finish': return httpx.Response(202, json={**view, 'state': 'checked'})
        return httpx.Response(200, json={'asset_id': 'x', 'revision': self.sha, 'name': 'Large volume', 'can_share': True, 'acquisition': {},
                                         'permitted_audience': [], 'recipients': ['alice'], 'reuse_recipients': []})


def test_sending_in_parts_holds_one_part_at_a_time(tmp_path):
    path = tmp_path / 'volume.sgy'; path.write_bytes(FORTY)
    fake = Fake(len(FORTY))
    sdk = Client('https://workspace.example', 'p', None, httpx.Client(transport=httpx.MockTransport(fake), base_url='https://workspace.example'))
    tracemalloc.start()
    try:
        sdk.upload_data(path, profile='segy/1', declared=DECLARED, **SAVE)
        peak = tracemalloc.get_traced_memory()[1]
    finally: tracemalloc.stop()
    assert fake.received == [8 * MIB] * 4 + [len(FORTY) - 32 * MIB]
    assert peak < 24 * MIB, peak


def test_a_parts_upload_saved_under_another_revision_is_refused(tmp_path):
    class Other(Fake):
        def __call__(self, request):
            response = super().__call__(request)
            if request.url.path.endswith('/publish'): self.sha = '0' * 64; response = super().__call__(request)
            return response
    path = tmp_path / 'volume.sgy'; path.write_bytes(FORTY)
    sdk = Client('https://workspace.example', 'p', None, httpx.Client(transport=httpx.MockTransport(Other(len(FORTY))), base_url='https://workspace.example'))
    with pytest.raises(VerificationFailed, match='^The uploaded original has a different checksum revision\\.$'):
        sdk.upload_data(path, profile='segy/1', declared=DECLARED, **SAVE)


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.mark.anyio
async def test_the_async_client_sends_in_parts_and_reads_by_ranges(web, monkeypatch, tmp_path):
    from ophiolite.aio import AsyncClient
    monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * MIB))
    raw = volume(30, 30, 1000)  # 11.5 MiB: two parts
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='https://workspace.example') as http:
        async with AsyncClient('https://workspace.example', 'p', Credential.bearer('oph_api_alice:read,write'), http) as alice:
            result = await alice.upload_data(raw, profile='segy/1', declared=DECLARED, command_id='async', **SAVE)
            assert result.revision == hashlib.sha256(raw).hexdigest()
            saved = await alice.download_original(result.asset_id, result.revision, tmp_path / 'copy.sgy')
    assert saved.read_bytes() == raw


def test_the_large_files_notebook_sends_in_parts_and_reads_back_in_a_project(large, tmp_path, monkeypatch):
    import runpy
    from pathlib import Path
    from ophiolite import gallery
    web, path, log = large
    import tempfile
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path)); log.clear()
    gallery.use(client(web, 'alice', 'delegate'))
    try: runpy.run_path(str(Path(__file__).parents[2] / 'notebooks' / 'large-files' / 'notebook.py'))
    finally: gallery.use(None)
    assert [e for e in log if e[0] == 'part'] == [('part', 0), ('part', 1), ('part', 2)] and 'las-uploads/publish' in log
