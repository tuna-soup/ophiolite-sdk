"""E183 s2b C1: the SDK sends a LAS upload's curve declaration to the in-process gateway, in one request, in parts and
from a work folder that recovers; the version keeps the caller's declaration and nothing is read from the file's
header (strategy E183-s2-curve-declaration, rev 2 closed: T1.2, T1.3, T1.4's gateway wording, T1.5, T1.6).

Every file is SYNTHETIC and written here; its header names a well, a datum and a depth unit that no declaration uses."""
import base64
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import publish
from ophiolite.errors import IntegrityConflict, Refused, ValidationFailed

LAS = '''~Version
VERS. 2.0 : LAS
WRAP. NO : rows
~Well
STRT.M 100 : start
STOP.M 222 : stop
STEP.M 1 : step
NULL. -999.25 : missing
WELL. HEADER-WELL-9 : well named in the file
PDAT. HEADER-DATUM : datum named in the file
DEPU. FT : depth unit named in the file
~Curve
DEPT.M : depth
GR.gAPI : gamma
~ASCII
100 0
101 -999.25
102 30
''' + ''.join('%d %d\n' % (103 + n, n % 50) for n in range(120))  # 1,5xx bytes: above a 1 KiB request
DECLARED = {'well': 'SYNTHETIC-W1', 'depth_kind': 'MD', 'depth_datum': 'unknown'}
SEND = dict(name='Synthetic log', attribution='Synthetic test', audience=[], rights_confirmed=True)
ONE_REQUEST = 'Upload details are invalid or too long; confirm rights, name and attribution'


def stored(web, asset_id):
    """The newest version's metadata and its representation rows."""
    from project_gateway import kernel
    a = web.a
    with a.journal.lock:
        row = a.journal.db.execute('SELECT id,metadata FROM retained_assets WHERE id=? OR json_extract(metadata,?)=? ORDER BY created_at DESC',
                                   (asset_id, '$.revision_of', asset_id)).fetchone()
        return json.loads(row[1]), sorted(kernel.rows_locked(a.journal.db, row[0]))


def sent(web):
    paths = []
    web.c.event_hooks['request'].append(lambda request: paths.append(request.url.path.rsplit('/', 1)[-1]))
    return paths


def test_t12_one_request_keeps_the_declaration_and_a_retry_is_one_command(web):
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='declared', **SEND)
    metadata, rows = stored(web, info.asset_id)
    assert metadata['curve_declaration'] == DECLARED and rows == ['curve:GR', 'well-log-curve:GR']
    assert alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='declared', **SEND).asset_id == info.asset_id
    with pytest.raises(IntegrityConflict): alice.upload_las(LAS.encode(), command_id='declared', **SEND)  # another fingerprint
    with pytest.raises(IntegrityConflict): alice.upload_las(LAS.encode(), curve_declaration={**DECLARED, 'depth_kind': 'TVD'}, command_id='declared', **SEND)


def test_t13_in_parts_begin_carries_it_and_a_retry_continues(web, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_MAX_UPLOAD_BYTES', '1024'); monkeypatch.setenv('OPHIOLITE_MAX_FILE_BYTES', str(64 * 1024 * 1024))
    monkeypatch.setattr(publish, 'SINGLE', 0)
    alice = client(web, 'alice', 'delegate')
    paths = sent(web)
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='parts', **SEND)
    assert 'begin' in paths and 'publish' in paths and 'part' in paths
    metadata, rows = stored(web, info.asset_id)
    assert metadata['curve_declaration'] == DECLARED and rows == ['curve:GR', 'well-log-curve:GR']
    assert alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='parts', **SEND).asset_id == info.asset_id


@pytest.mark.parametrize('declaration', [{**DECLARED, 'well': ''}, {**DECLARED, 'depth_datum': ' padded'}, {**DECLARED, 'depth_kind': 'KB'},
                                         {'well': 'SYNTHETIC-W1'}, {**DECLARED, 'extra': 'x'}])
def test_t14_the_local_refusal_says_what_the_gateway_says(web, declaration):
    """The local sentence is the gateway's own for the refused fields (begin's answer); its one-request route refuses
    the same declaration with its general upload-details sentence."""
    alice = client(web, 'alice', 'delegate')
    with pytest.raises(ValidationFailed) as local: alice.upload_las(LAS.encode(), curve_declaration=declaration, command_id='bad', **SEND)
    begin = {'command_id': 'bad', 'filename': 'input.las', 'profile': 'las2/1', 'declared': {}, 'bytes': 10, 'sha256': '0' * 64}
    with pytest.raises(Refused) as served: alice._post('las-uploads', 'begin', {**begin, 'curve_declaration': declaration})
    assert served.value.server_message == local.value.violations[0]  # the deployment's sentence, carried on the error
    value, _ = publish.upload_metadata('p', 'bad', filename='input.las', **SEND)
    raw = {'Content-Type': 'application/octet-stream',
           'X-Ophiolite-Upload': base64.b64encode(json.dumps({**value, 'curve_declaration': declaration}).encode()).decode()}
    with pytest.raises(Refused) as served: alice._post_bytes('las-uploads', 'upload', LAS.encode(), extra_headers=raw)
    assert served.value.status == 400 and served.value.server_message == ONE_REQUEST


def test_t14_only_a_las_file_takes_it_here_and_there(web):
    alice = client(web, 'alice', 'delegate')
    tops = b'well,top,md\nW,A,100\n'
    with pytest.raises(ValidationFailed) as local:
        alice.upload_data(tops, profile='well-tops-csv/1', filename='tops.csv', curve_declaration=DECLARED, command_id='tops', **SEND)
    value, _ = publish.upload_metadata('p', 'tops', filename='tops.csv', profile='well-tops-csv/1', **SEND)
    raw = {'Content-Type': 'application/octet-stream',
           'X-Ophiolite-Upload': base64.b64encode(json.dumps({**value, 'curve_declaration': DECLARED}).encode()).decode()}
    with pytest.raises(Refused) as served: alice._post_bytes('las-uploads', 'upload', tops, extra_headers=raw)
    assert served.value.server_message == local.value.violations[0] == 'Only a LAS file takes a curve declaration.'


def test_t15_a_work_folder_keeps_the_declaration_through_a_recovery(web, tmp_path, monkeypatch):
    from ophiolite import Client as C
    alice = client(web, 'alice', 'delegate')
    real = C._post_bytes

    def lost(self, *a, **k):
        real(self, *a, **k); raise ConnectionError('the response was lost')
    monkeypatch.setattr(C, '_post_bytes', lost)
    with pytest.raises(ConnectionError): alice.work_folder(tmp_path / 'work').upload_las(LAS.encode(), curve_declaration=DECLARED, **SEND)
    monkeypatch.setattr(C, '_post_bytes', real)
    state = json.loads((tmp_path / 'work' / 'run.json').read_text())
    assert state['upload_declaration'] == DECLARED
    recovered = alice.recover(tmp_path / 'work')
    metadata, rows = stored(web, recovered.asset_id)
    assert metadata['curve_declaration'] == DECLARED and rows == ['curve:GR', 'well-log-curve:GR']
    with web.a.journal.lock:
        assert web.a.journal.db.execute("SELECT COUNT(*) FROM retained_assets WHERE kind='uploaded'").fetchone()[0] == 1
    with pytest.raises(Refused):  # another declaration in the same folder is other work
        alice.work_folder(tmp_path / 'work').upload_las(LAS.encode(), curve_declaration={**DECLARED, 'well': 'OTHER'}, **SEND)


def test_t16_nothing_is_read_from_the_header(web):
    """C1. (a) no declaration: none sent, none stored, no well log row; (b) `well` only: refused here, nothing sent;
    (c) a complete one: the stored declaration is the caller's, not the header's. Mutation: an omitted or missing field
    filled from the file's header: red in (a) and (b)."""
    alice = client(web, 'alice', 'delegate')
    paths = sent(web)
    plain = alice.upload_las(LAS.encode(), command_id='plain', **SEND)
    metadata, rows = stored(web, plain.asset_id)
    assert 'curve_declaration' not in metadata and rows == ['curve:GR']
    before = len(paths)
    with pytest.raises(ValidationFailed): alice.upload_las(LAS.encode(), curve_declaration={'well': 'SYNTHETIC-W1'}, command_id='partial', **SEND)
    assert len(paths) == before
    declared = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='complete', **SEND)
    assert stored(web, declared.asset_id)[0]['curve_declaration'] == DECLARED
