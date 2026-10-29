"""E122 s6 C2, in-process gateway lane: `upload_data(..., application_source=...)` through the real routes, in one
request and in parts; the version's provenance is the gateway's application sentence. The posted operations are
recorded, so the parts case cannot pass by going as one request."""
import base64
import hashlib
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)

LAS = '~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.M 100 : start\nSTOP.M 102 : stop\nSTEP.M 1 : step\nNULL. -999.25 : missing\nWELL. SDK : fixture\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma\n~ASCII\n100 0\n101 -999.25\n102 30\n'
RAW = LAS.encode()
F3 = {'system': 'application:opendtect', 'instance': 'F3_Demo', 'container': 'F3_Demo', 'id': '100050.2'}
SAVE = dict(name='Well', attribution='Synthetic', audience=['bob'], rights_confirmed=True, filename='well.las', profile='las2/1')


@pytest.fixture
def logged(web):
    log = []
    def record(request):
        op = request.url.path.rsplit('/', 1)[-1]
        if request.url.path.split('/')[-2] == 'las-uploads':
            body = request.headers.get('x-ophiolite-upload') if op in ('upload', 'part') else request.content
            log.append((op, json.loads(base64.b64decode(body)) if op in ('upload', 'part') else json.loads(body)))
    web.c.event_hooks['request'].append(record)
    return web, log


def words(alice, got):
    return alice.provenance(got.asset_id, got.revision).words


def test_one_request_carries_the_block_and_the_version_says_where_it_came_from(logged):
    web, log = logged
    alice = client(web, 'alice', 'delegate')
    got = alice.upload_data(RAW, application_source=F3, command_id='one', **SAVE)
    assert [op for op, _ in log] == ['upload'] and log[0][1]['source'] == F3
    digest = hashlib.sha256(RAW).hexdigest()
    assert words(alice, got) == 'From opendtect, workspace `F3_Demo`, object `100050.2` in `F3_Demo` (checksum %s…).' % digest[:12]


def test_a_file_in_parts_carries_the_block_on_its_publish(logged, monkeypatch):
    web, log = logged
    from ophiolite import publish
    monkeypatch.setattr(publish, 'SINGLE', 16)
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', '65536')
    alice = client(web, 'alice', 'delegate')
    monkeypatch.setattr(type(alice), 'served_limits', lambda self: {'upload_bytes': 16, 'file_bytes': 64 * 1024 * 1024})
    got = alice.upload_data(RAW, application_source=F3, command_id='parts', **SAVE)
    ops = [op for op, _ in log]
    assert ops[0] == 'begin' and 'part' in ops and 'finish' in ops and ops[-1] == 'publish' and 'upload' not in ops
    assert 'source' not in log[0][1] and log[-1][1]['source'] == F3
    digest = hashlib.sha256(RAW).hexdigest()
    assert words(alice, got) == 'From opendtect, workspace `F3_Demo`, object `100050.2` in `F3_Demo` (checksum %s…).' % digest[:12]


def test_an_upload_without_the_block_sends_no_source_and_says_it_was_a_file(logged):
    web, log = logged
    alice = client(web, 'alice', 'delegate')
    got = alice.upload_data(RAW, command_id='plain', **SAVE)
    assert 'source' not in log[0][1]
    assert words(alice, got).startswith('From file `well.las` (checksum ')
