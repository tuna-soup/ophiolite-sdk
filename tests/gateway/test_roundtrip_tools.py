"""E138 s1 C2 (strategy D6, D10, D11; R1-10, R2-9b; mutation 9): the QGIS leg's judge, its paging proof and its
container, against synthetic inside-script outputs, a synthetic proxy log and a stub engine.

The judge is checked against hand-written heads and features, never against production output; the paging check
against hand-written proxy logs (a fabricated `page_count` with one logged request fails). `read` runs end to end
with a stub engine that plays the container: it reads the mounted in.json, pages the wells collection through the
recording proxy's Unix socket (tools/interop/proxy.py, unchanged) from a small paged upstream, and writes out.json, so
the log the check reads is the real proxy's. The live QGIS is proven by the live run."""
import importlib.util
import json
import os
import stat
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module(name):
    spec = importlib.util.spec_from_file_location('roundtrip_' + name, ROOT / 'conformance/roundtrip' / (name + '.py'))
    if 'roundtrip_' + name in sys.modules: return sys.modules['roundtrip_' + name]
    loaded = importlib.util.module_from_spec(spec)
    sys.modules['roundtrip_' + name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


qg, ev, wf, rl = _module('qgis_leg'), _module('evaluate'), _module('workfolder'), _module('resinsight_leg')
TABLE = ev.load()
TOOL = {'name': 'qgis', 'version': 'test', 'host': 'synthetic'}
HEADS = {'W-1': (500010.125, 6100010.375), 'W-2': (500020.5, 6100020.25), 'W-3': (500030.0, 6100030.75)}
CREATED = {'W-1': 'ent-1', 'W-2': 'ent-2', 'W-3': 'ent-3'}
ITEMS = '/api/v1/projects/p/features/collections/wells/items'


def features(heads=HEADS, created=CREATED):
    return [{'id': created[n], 'x': x, 'y': y} for n, (x, y) in heads.items()]


def seen(feats=None, collection='wells', valid=True):
    return {'collection': collection, 'valid': valid, 'features': features() if feats is None else feats, 'page_count': 2, 'qgis_version': '4.2.2'}


def by_object(rows): return {r['object']: r for r in rows}


def good_log():
    return [{'method': 'GET', 'path': ITEMS, 'query': 'limit=2', 'status': 200, 'ids': ['ent-1', 'ent-2']},
            {'method': 'GET', 'path': ITEMS, 'query': 'limit=2&cursor=c2', 'status': 200, 'ids': ['ent-3']}]


PAGES = [('', ['ent-1', 'ent-2']), ('c2', ['ent-3'])]


def test_clean_heads_agree_on_every_quantity():
    rows = qg.judge(TABLE, seen(), HEADS, CREATED, tool=TOOL, synthetic=True)
    assert [r['object'] for r in rows] == list(HEADS)
    for r in rows:
        assert (r['kind'], r['leg'], r['state']) == ('well-head', 'project-to-qgis', 'within'), r
        assert {q['name']: q['state'] for q in r['quantities']} == {'wells': 'agree', 'identities': 'agree', 'x': 'agree', 'y': 'agree'}


@pytest.mark.parametrize('case', ['other-well', 'dropped', 'swapped', 'moved-1mm'])
def test_one_wrong_feature_turns_that_head_only(case):
    feats = features()
    if case == 'other-well': feats[1]['x'] = HEADS['W-3'][0]
    if case == 'dropped': del feats[1]
    if case == 'swapped': feats[1]['x'], feats[1]['y'] = feats[1]['y'], feats[1]['x']
    if case == 'moved-1mm': feats[1]['y'] += 0.0011  # over the 0.001 m budget
    rows = by_object(qg.judge(TABLE, seen(feats), HEADS, CREATED, tool=TOOL, synthetic=True))
    assert rows['W-2']['state'] == 'disagree' and {rows['W-1']['state'], rows['W-3']['state']} == {'within'}
    turned = {q['name'] for q in rows['W-2']['quantities'] if q['state'] == 'disagree'}
    assert turned == {'other-well': {'x'}, 'dropped': {'wells', 'identities', 'x', 'y'}, 'swapped': {'x', 'y'}, 'moved-1mm': {'y'}}[case]


def test_within_the_budget_agrees():
    feats = features(); feats[0]['x'] += 0.0009
    assert by_object(qg.judge(TABLE, seen(feats), HEADS, CREATED, tool=TOOL, synthetic=True))['W-1']['state'] == 'within'


def test_a_duplicated_identity_fails_that_head_with_its_class():
    feats = features() + [dict(features()[2])]
    rows = by_object(qg.judge(TABLE, seen(feats), HEADS, CREATED, tool=TOOL, synthetic=True))
    assert rows['W-3']['state'] == 'failed' and rows['W-3']['evidence'] == {'error': qg.TWICE, 'class': 'duplicate trace position'}
    assert rows['W-1']['state'] == rows['W-2']['state'] == 'within'


@pytest.mark.parametrize('bad, cls', [({'collection': 'boreholes'}, 'other'), ({'valid': False, 'features': []}, 'tool diagnostics'),
                                      ({'stopped': qg.NOT_STARTED % 125}, 'tool did not start')])
def test_the_wrong_collection_an_invalid_layer_or_no_start_fails_every_head(bad, cls):
    rows = qg.judge(TABLE, {**seen(), **bad}, HEADS, CREATED, tool=TOOL, synthetic=True)
    assert {(r['state'], r['evidence']['class']) for r in rows} == {('failed', cls)} and len(rows) == 3


def test_failure_sentences_carry_no_name_or_identity():
    feats = features() + [dict(features()[2])]
    rows = qg.judge(TABLE, seen(feats), HEADS, CREATED, tool=TOOL, synthetic=False)
    text = json.dumps([r['evidence'] for r in rows])
    assert not any(s in text for s in [*HEADS, *CREATED.values()])
    assert all(r['examples'] == [] for r in rows)  # a live run keeps no example


def test_the_paging_proof_holds_for_two_followed_pages():
    assert qg.paging(good_log(), PAGES, CREATED.values()) == []


@pytest.mark.parametrize('case', ['one-request', 'cursor-not-followed', 'short-union', 'other-identity', 'page-size'])
def test_the_paging_proof_fails(case):
    log = good_log()
    if case == 'one-request': log = [{**log[0], 'ids': ['ent-1', 'ent-2', 'ent-3'], 'query': 'limit=2'}]
    if case == 'cursor-not-followed': log[1]['query'] = 'limit=2&cursor=elsewhere'
    if case == 'short-union': log[1]['ids'] = []
    if case == 'other-identity': log[1]['ids'] = ['ent-3', 'ent-9']
    if case == 'page-size': log = [{**e, 'query': e['query'].replace('limit=2', 'limit=10')} for e in log]
    problems = qg.paging(log, PAGES, CREATED.values())
    expected = {'one-request': qg.FEW_REQUESTS % 1, 'cursor-not-followed': qg.NOT_FOLLOWED % (1, 1), 'short-union': qg.UNION % (2, 3, 0),
                'other-identity': qg.UNION % (3, 3, 1), 'page-size': qg.PAGE_SIZES % ('10', 2)}[case]
    assert expected in problems


def test_a_fabricated_page_count_with_one_logged_request_fails_every_head():
    log = [{'method': 'GET', 'path': ITEMS, 'query': 'limit=2', 'status': 200, 'ids': ['ent-1', 'ent-2', 'ent-3']}]
    rows, problems = qg.rows(TABLE, {**seen(), 'page_count': 2}, log, PAGES, HEADS, CREATED, tool=TOOL, synthetic=True)
    assert problems and {(r['state'], r['evidence']['error']) for r in rows} == {('failed', qg.NOT_PAGED)}
    rows, problems = qg.rows(TABLE, seen(), good_log(), PAGES, HEADS, CREATED, tool=TOOL, synthetic=True)
    assert problems == [] and {r['state'] for r in rows} == {'within'}


def test_qgis_s_first_probe_of_ten_neither_proves_nor_spoils_the_paging():
    """QGIS 4.2.2 asks for one page of 10 without a cursor before it pages (the real image, 1 Nov 2026)."""
    probe = {'method': 'GET', 'path': ITEMS, 'query': 'limit=10&crs=x', 'status': 200, 'ids': ['ent-1', 'ent-2', 'ent-3']}
    assert qg.paging([probe] + good_log(), PAGES, CREATED.values()) == []
    assert qg.paging([probe, good_log()[0]], PAGES, CREATED.values()) == [qg.FEW_REQUESTS % 1, qg.NOT_FOLLOWED % (1, 1), qg.UNION % (2, 3, 0)]


def test_requests_to_other_paths_or_refused_pages_do_not_count():
    log = good_log() + [{'method': 'GET', 'path': ITEMS.replace('wells', 'points'), 'query': 'limit=2&cursor=c9', 'status': 200, 'ids': ['ent-9']}]
    assert qg.paging(log, PAGES, CREATED.values()) == []
    log = [good_log()[0], {**good_log()[1], 'status': 401}]
    assert qg.FEW_REQUESTS % 1 in qg.paging(log, PAGES, CREATED.values())


def test_the_gateway_pages_follow_next_and_refuse_a_loop():
    docs = {'/items?limit=2': {'features': [{'id': 'a'}, {'id': 'b'}], 'links': [{'rel': 'next', 'href': 'http://o/items?limit=2&cursor=k1'}]},
            'http://o/items?limit=2&cursor=k1': {'features': [{'id': 'c'}], 'links': [{'rel': 'self', 'href': 'x'}]}}
    assert qg.pages(docs.__getitem__, '/items') == [('', ['a', 'b']), ('k1', ['c'])]
    docs['http://o/items?limit=2&cursor=k1']['links'] = [{'rel': 'next', 'href': 'http://o/items?limit=2&cursor=k1'}]
    with pytest.raises(ValueError, match='repeat'):
        qg.pages(docs.__getitem__, '/items')


# --- the container, with a stub engine -------------------------------------------------------------------------------

STUB = r'''#!%(python)s
"""A stub engine: `run` plays the QGIS container, `ps`, `stop` and `rm` answer from a state file."""
import http.client, json, os, socket, sys, time
from urllib.parse import urlsplit
state, argv = %(state)r, sys.argv[1:]
with open(state + '.calls', 'a') as calls: calls.write(json.dumps(argv) + '\n')
if argv[0] == 'run': open(state + '.env', 'w').write(json.dumps({k: os.environ.get(k) for k in ('HOME', 'XDG_DATA_HOME', 'OPHIOLITE_E138_RUN')}))
mode = open(state + '.mode').read().strip() if os.path.exists(state + '.mode') else 'clean'
if argv[0] == 'ps':
    print(open(state).read() if os.path.exists(state) else '', end=''); sys.exit(0 if mode != 'ps-fails' else 1)
if argv[0] in ('stop', 'rm'):
    if os.path.exists(state): os.unlink(state)
    sys.exit(0)
name = argv[argv.index('--name') + 1]
mounts = dict(reversed(v.split(':')[:2]) for v in (argv[i + 1] for i, a in enumerate(argv) if a == '-v'))
open(state, 'w').write(name + '\n')
if mode == 'hang': time.sleep(600)
if mode == 'no-start': os.unlink(state); sys.exit(125)
spec = json.load(open(mounts['/work'] + '/in.json'))
class Unix(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.connect(mounts['/run/e46'] + '/proxy.sock')
url, feats = spec['landing'] + '/collections/' + spec['collection'] + '/items?limit=%%d' %% spec['page_size'], []
while url:
    c = Unix('127.0.0.1'); part = urlsplit(url); c.request('GET', part.path + '?' + part.query, headers={'Host': part.netloc})
    doc = json.loads(c.getresponse().read()); c.close()
    feats += [{'id': f['properties']['entity_id'], 'x': f['geometry']['coordinates'][0], 'y': f['geometry']['coordinates'][1]} for f in doc['features']]
    url = next((l['href'] for l in doc['links'] if l['rel'] == 'next'), None)
    if mode == 'one-page': url = None
json.dump({'collection': spec['collection'], 'valid': True, 'features': feats, 'page_count': 2, 'qgis_version': '4.2.2-stub'},
          open(mounts['/work'] + '/out.json', 'w'))
os.unlink(state)
'''


class Upstream:
    """A paged wells collection (page size from `limit`; the cursor is the next index), answering only with the key."""
    def __init__(self, heads=HEADS, created=CREATED, key='k-read'):
        entities = [(created[n], x, y) for n, (x, y) in heads.items()]
        seen_keys = self.keys = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                seen_keys.append(self.headers.get('Authorization'))
                part = urlsplit(self.path); query = parse_qs(part.query)
                if self.headers.get('Authorization') != 'Bearer ' + key or part.path != ITEMS: return self.answer(401, {'code': 'refused'})
                start, limit = int(query.get('cursor', ['0'])[0]), int(query.get('limit', ['10'])[0])
                page = entities[start:start + limit]
                links = [{'rel': 'next', 'href': 'http://%s%s?limit=%d&cursor=%d' % (self.headers['Host'], ITEMS, limit, start + limit)}] if start + limit < len(entities) else []
                self.answer(200, {'type': 'FeatureCollection', 'links': links,
                                  'features': [{'type': 'Feature', 'id': e, 'geometry': {'type': 'Point', 'coordinates': [x, y]}, 'properties': {'entity_id': e}} for e, x, y in page]})

            def answer(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/geo+json' if status == 200 else 'application/json')
                self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

            def log_message(self, *args): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]

    def close(self): self.server.shutdown(); self.server.server_close()


@pytest.fixture
def stub(tmp_path):
    state = tmp_path / 'engine-state'
    path = tmp_path / 'engine'
    path.write_text(STUB % {'python': sys.executable, 'state': str(state)}); path.chmod(stat.S_IRWXU)
    upstream = Upstream()
    volume = Path(tempfile.mkdtemp(prefix='v'))  # pytest's own folder is too deep for a Unix socket path
    work = wf.WorkFolder.create(volume, forbidden=[tmp_path / 'forbidden'])
    yield SimpleNamespace(engine=str(path), state=state, upstream=upstream, work=work,
                          calls=lambda: [json.loads(line) for line in Path(str(state) + '.calls').read_text().splitlines()],
                          mode=lambda m: Path(str(state) + '.mode').write_text(m))
    upstream.close(); work.close(); volume.rmdir()


def stub_read(stub, timeout=60):
    return qg.read(stub.work, stub.upstream.url, 8123, 'http://127.0.0.1:8123/api/v1/projects/p/features', 'k-read', 'EPSG:23031',
                   name='e138-qgis-test', timeout=timeout, run_engine=stub.engine)


def test_the_stub_read_is_judged_clean_and_its_proxy_log_proves_the_paging(stub):
    got, log = stub_read(stub)
    def get(url):  # the gateway's own pages, asked directly (not through QGIS or the proxy)
        request = urllib.request.Request(url.replace('http://127.0.0.1:8123', stub.upstream.url), headers={'Authorization': 'Bearer k-read'})
        with urllib.request.urlopen(request) as answer: return json.loads(answer.read())
    pages = qg.pages(get, stub.upstream.url + ITEMS)
    assert [c for c, _ in pages] == ['', '2']
    rows, problems = qg.rows(TABLE, got, log, pages, HEADS, CREATED, tool=qg.tool_of(got, 'synthetic', None), synthetic=True)
    assert problems == [] and {r['state'] for r in rows} == {'within'}
    assert [e['injected'] for e in log] == [True, True] and set(stub.upstream.keys) == {'Bearer k-read'}
    run = stub.calls()[0]
    assert run[:5] == ['run', '--rm', '--name', 'e138-qgis-test', '--network=none'] and 'k-read' not in json.dumps(run)
    assert all(v.split(':')[0].startswith(str(stub.work.path)) for v in (run[i + 1] for i, a in enumerate(run) if a == '-v')
               if v.split(':')[1] in ('/work', '/run/e46'))
    assert qg.absent('e138-qgis-test', stub.engine)
    engine_env = json.loads(Path(str(stub.state) + '.env').read_text())  # the engine's own store stays the user's
    assert engine_env == {'HOME': os.environ.get('HOME'), 'XDG_DATA_HOME': os.environ.get('XDG_DATA_HOME'), 'OPHIOLITE_E138_RUN': stub.work.marker}
    for place in (engine_env['HOME'], engine_env['XDG_DATA_HOME']):  # the host rule (D11): never a store under the work folder
        assert place is None or not Path(place).resolve().is_relative_to(stub.work.path.resolve())
    assert '-e' in run and 'HOME=/work/home' in run  # the container side keeps its /work HOME


def test_a_read_that_stops_after_one_page_fails_the_paging_whatever_it_prints(stub):
    stub.mode('one-page')
    got, log = stub_read(stub)
    assert got['page_count'] == 2 and len(log) == 1
    rows, problems = qg.rows(TABLE, got, log, [('', ['ent-1', 'ent-2']), ('2', ['ent-3'])], HEADS, CREATED, tool=TOOL, synthetic=True)
    assert qg.FEW_REQUESTS % 1 in problems and {r['state'] for r in rows} == {'failed'}


def test_a_container_that_does_not_start_fails_with_its_class(stub):
    stub.mode('no-start')
    got, _ = stub_read(stub)
    assert got['stopped'] == qg.NOT_STARTED % 125
    rows, _ = qg.rows(TABLE, got, [], [], HEADS, CREATED, tool=TOOL, synthetic=True)
    assert {(r['state'], r['evidence']['class']) for r in rows} == {('failed', 'tool did not start')}


def test_a_container_that_hangs_is_stopped_by_name_and_verified_absent(stub):
    stub.mode('hang')
    got, _ = stub_read(stub, timeout=3)
    assert got['stopped'] == qg.TIMED_OUT % 3
    assert ['stop', '-t', '5', 'e138-qgis-test'] in stub.calls() and qg.absent('e138-qgis-test', stub.engine)


def test_absent_is_true_only_when_the_engine_answers_without_the_name(stub, tmp_path):
    stub.state.write_text('e138-qgis-test\n')
    assert not qg.absent('e138-qgis-test', stub.engine)
    stub.state.write_text('')
    assert qg.absent('e138-qgis-test', stub.engine)
    stub.mode('ps-fails')
    assert not qg.absent('e138-qgis-test', stub.engine)
    assert not qg.absent('e138-qgis-test', str(tmp_path / 'no-engine'))
    ps = [c for c in stub.calls() if c[0] == 'ps'][0]
    assert ps == ['ps', '-a', '--filter', 'name=^e138-qgis-test$', '--format', '{{.Names}}']


def test_a_work_folder_too_deep_for_the_socket_is_refused_before_the_proxy_starts(tmp_path):
    deep = tmp_path / ('d' * 120)
    deep.mkdir()
    with pytest.raises(ValueError, match='too long'):
        qg.read(wf.WorkFolder(deep), 'http://127.0.0.1:1', 1, 'x', 'k', 'EPSG:23031', name='n', serve=lambda *a, **k: pytest.fail('no proxy'))
    assert os.listdir(deep) != [] and not (deep / 'qgis-proxy.jsonl').exists()


# --- the ResInsight leg, against the fake rips (R1-11; mutation 10) --------------------------------------------------

FAKE_RIPS, CONNECTORS = ROOT / 'ophiolite-connectors/tests/fake_rips', ROOT / 'ophiolite-connectors/src'
SYN_A = 'md,x,y,tvdss\n0.0,500010.125,10.375,-20.0\n60.0,500010.125,10.375,40.0\n120.0,500012.5,11.0,99.5\n180.0,500015.0,12.25,158.75\n'
SYN_B = 'md,x,y,tvdss\n0.0,500075.0,50.0,-10.0\n50.0,500075.0,50.0,40.0\n100.0,500076.5,51.25,89.75\n'
LAS_A = ('~Version\n VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\n WRAP.   NO : ONE LINE PER DEPTH STEP\n~Well\n STRT.M 100.0 : first depth\n'
         ' STOP.M 100.9 : last depth\n STEP.M 0.15 : depth step\n NULL. -999.25 : null value\n WELL. SYN-A : well\n~Curve\n DEPT.M : measured depth\n'
         ' DT.us/ft : DT\n GR.API : GR\n~ASCII\n100.0 -999.25 -999.25\n100.15 120.25 60.5\n100.3 121.5 61.0\n100.45 122.0 62.0\n100.6 123.75 63.5\n'
         '100.75 124.5 64.0\n100.9 125.0 -999.25\n')  # E129's E6 pack (test_resinsight_starter.py:23-29)
SUPPLIED = [('well-path', 'SYN-A'), ('well-path', 'SYN-B'), ('well-log', 'SYN-A/GR'), ('well-log', 'SYN-A/DT')]


@pytest.fixture
def ri(tmp_path):
    """A work folder holding the downloads, the Connectors interpreter over the fake rips, and the stand-in ResInsight."""
    state = tmp_path / 'servers'
    python = tmp_path / 'connectors-python'
    python.write_text('#!/bin/sh\nPYTHONPATH=%s:%s FAKE_RIPS_STATE=%s DISPLAY=:99 exec %s "$@"\n' % (FAKE_RIPS, CONNECTORS, state, sys.executable))
    exe = tmp_path / 'ResInsight'
    exe.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE_RIPS / 'fake_resinsight.py'))
    for script in (python, exe): script.chmod(0o755)
    (tmp_path / 'volume').mkdir()
    work = wf.WorkFolder.create(tmp_path / 'volume', forbidden=[tmp_path / 'forbidden'])
    down = work.path / 'downloads'; down.mkdir()
    for name, text in (('a.csv', SYN_A), ('b.csv', SYN_B), ('a.las', LAS_A)): (down / name).write_text(text)
    downloads = [('well-path', 'SYN-A', down / 'a.csv'), ('well-path', 'SYN-B', down / 'b.csv'), ('well-log', 'SYN-A/GR', down / 'a.las'),
                 ('well-log', 'SYN-A/DT', down / 'a.las')]
    yield SimpleNamespace(work=work, python=str(python), exe=str(exe), downloads=downloads, state=state, tmp=tmp_path)
    work.close()


def ri_run(ri, **kw):
    return rl.run(ri.work, ri.python, ri.downloads, executable=kw.pop('executable', ri.exe), host='synthetic', timeout=kw.pop('timeout', 120), **kw)


def started(ri):
    path = ri.state / 'starts.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_fake_rips_leg_is_within_on_every_supplied_object_and_leaves_nothing(ri):
    seen = {}
    def look(pack, project): seen['files'] = sorted(str(p.relative_to(pack)) for p in pack.rglob('*') if p.is_file())
    rows, facts = ri_run(ri, mutate=look)
    assert [(r['kind'], r['object'], r['leg'], r['state']) for r in rows] == [(k, o, 'project-to-resinsight', 'within') for k, o in SUPPLIED]
    assert rows[0]['tool']['name'] == 'resinsight' and rows[0]['evidence']['tool_level']['diagnostics'] == 0
    assert seen['files'] == ['files/targets/resinsight/import.py', 'files/wells/w1-1.las', 'files/wells/w1-positions.csv', 'files/wells/w2-positions.csv']
    assert facts == {'removed': True} and not (ri.work.path / 'ri-pack').exists() and not (ri.work.path / 'ri-project').exists()
    assert len(started(ri)) == 2 and all(not os.path.exists('/proc/%d' % s['pid']) for s in started(ri))  # the launcher's and the comparison's
    assert ri.work.survivors() == []


@pytest.mark.parametrize('case', ['missing-download', 'exits-at-once', 'leftover-project'])
def test_each_tool_failure_fails_every_row_with_its_class_and_removes_the_folders(ri, case):
    def mutate(pack, project):
        if case == 'missing-download': (pack / 'files/wells/w2-positions.csv').unlink()
        if case == 'leftover-project': project.mkdir(); (project / 'left.txt').write_text('an earlier run')
    executable = ri.exe
    if case == 'exits-at-once':
        executable = ri.tmp / 'ResInsight-exits'
        Path(executable).write_text('#!/bin/sh\nexit 3\n'); Path(executable).chmod(0o755)
    rows, facts = ri_run(ri, mutate=mutate, executable=str(executable))
    cls = {'missing-download': 'other', 'exits-at-once': 'tool did not start', 'leftover-project': 'tool did not start'}[case]
    assert {(r['state'], r['evidence']['class']) for r in rows} == {('failed', cls)} and len(rows) == 4
    assert facts == {'removed': True} and not (ri.work.path / 'ri-project').exists()
    text = json.dumps([r['evidence'] for r in rows])
    assert 'SYN' not in text and 'left.txt' not in text  # E129's words stay in the work folder's logs
    if case != 'missing-download': assert (ri.work.path / 'ri-launch.log').read_text().strip()
    assert ri.work.survivors() == []


def test_without_resinsight_the_rows_wait_on_the_tool(ri):
    rows, facts = ri_run(ri, executable=str(ri.tmp / 'no-such-resinsight'))
    assert {(r['state'], json.dumps(r['evidence'])) for r in rows} == {('not-yet', '{"waits_on": "tool resinsight"}')} and len(rows) == 4
    assert facts == {'removed': True} and started(ri) == []


def test_a_child_that_leaves_its_group_is_found_by_its_mark_and_stopped(ri):
    """D11: ResInsight under E129's launcher starts a session of its own; the run's mark still finds it."""
    code = ('import os, subprocess, sys, time\n'
            'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True, '
            'stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n')
    assert ri.work.run([sys.executable, '-c', code], timeout=30, env=ri.work.child_env()) == 0
    left = ri.work.survivors()
    assert len(left) == 1 and os.getsid(left[0]) == left[0]
    assert ri.work.stop_survivors() is True and ri.work.survivors() == []
    other = wf.WorkFolder.create(ri.tmp / 'volume', forbidden=[ri.tmp / 'forbidden'])
    assert other.marker != ri.work.marker and other.survivors() == []
    other.close()
