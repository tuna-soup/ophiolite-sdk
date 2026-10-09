"""E94 C5, gateway lane: the SDK against the real routes of an in-process gateway.

/3 is declared on the curve and the typed descriptor paths over HTTP; a client that declares nothing reads the /2 view
and the SDK every release before E94 pins (afaf4e3) opens its bundle; a bundle exported by a member who cannot read
one parent names that parent nowhere; the story, what-changed and dependents answers equal the route answers."""
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web, Caller  # noqa: F401
    from project_gateway.tests.test_organizations import service  # noqa: F401
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401
    from project_gateway.tests.test_calculations import source, publish
    from project_gateway.tests.test_manifest_v3_reader import upgrade
    from project_gateway.tests.e94_story_world import released
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
import ophiolite.client
from ophiolite import Client, Credential
from ophiolite.bundle import open_bundle
from ophiolite.typed import PointSet

V3, V2 = 'ophiolite.revision-manifest/3', 'ophiolite.revision-manifest/2'
OLDER = 'afaf4e3'  # the SDK the lock pins before E94 (E93)
ROOT = Path(__file__).resolve().parents[2]
LAS = '~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.M 100 : start\nSTOP.M 102 : stop\nSTEP.M 1 : step\nNULL. -999.25 : missing\nWELL. SDK : fixture\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma\n~ASCII\n100 0\n101 -999.25\n102 30\n'
UNKNOWN = dict(crs='unknown', xy_unit='unknown', z_unit='unknown', z_meaning='unknown', positive='unknown', vertical_datum='unknown')
METHOD = {'name': 'scipy.spatial.Delaunay', 'library': 'scipy', 'version': '1.14.1'}


def client(web, persona, scopes='read,write'):
    return Client('https://workspace.example', 'p', Credential.bearer('oph_api_' + persona + ':' + scopes), web.c)


def every_file(folder):
    return b''.join(p.read_bytes() for p in sorted(Path(folder).rglob('*')) if p.is_file())


def older_reader(tmp_path, bundle):
    """Open a bundle with the SDK the lock pinned before E94, in a separate interpreter."""
    target = tmp_path / 'older'
    if not target.exists():
        try: archive = subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar', OLDER, 'ophiolite'], capture_output=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError): pytest.skip('The older SDK commit is not in this checkout')
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(target, filter='data')
    probe = ('import sys,json\nfrom ophiolite.bundle import open_bundle\n'
             'try:open_bundle(sys.argv[1]);print(json.dumps(["opened"]))\n'
             'except Exception as e:print(json.dumps([type(e).__name__,str(e)]))\n')
    out = subprocess.run([sys.executable, '-I', '-c', 'import sys;sys.path.insert(0,sys.argv[2]);exec(sys.argv[3])', str(bundle), str(target), probe],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture
def made(web, monkeypatch, tmp_path):
    """A shale-volume curve the server ran itself (a real /3 writer), from an uploaded HON-GT-01 gamma ray."""
    released(monkeypatch, tmp_path)
    bob = Caller(web, 'session', 'bob'); parent = source(web)
    first = publish(bob, parent, 'c5-story-1', name='Shale volume HON-GT-01')
    return bob, parent, first


def test_the_curve_path_declares_3_and_a_client_that_does_not_reads_the_2_view(web, made, monkeypatch, tmp_path):
    _, _, first = made
    sdk = client(web, 'bob')
    declared = sdk.read(first['asset_id'], first['revision'], ['VSH'])._wire_descriptors[0]
    assert declared['manifest']['schema'] == V3 and declared['manifest']['derivation_record']['kind'] == 'executed'
    assert sdk.describe(first['asset_id'], first['revision'], 'VSH').manifest.schema_ == V3
    sdk.export([(first['asset_id'], first['revision'], ['VSH'])], tmp_path / 'new')
    assert json.loads(next((tmp_path / 'new').rglob('descriptor-*.json')).read_text())['manifest']['schema'] == V3
    assert open_bundle(tmp_path / 'new').assets[0].curves['VSH'].view.values
    monkeypatch.setattr(ophiolite.client, 'PROFILES', '')  # a client that declares nothing
    view = sdk.read(first['asset_id'], first['revision'], ['VSH'])._wire_descriptors[0]
    assert view['manifest']['schema'] == V2 and 'derivation_record' not in view['manifest'] and view['manifest']['digest'] == declared['manifest']['digest_v2']
    assert view['derivation'] == {'method': declared['manifest']['method']}
    sdk.export([(first['asset_id'], first['revision'], ['VSH'])], tmp_path / 'view')
    assert older_reader(tmp_path, tmp_path / 'view') == ['opened']  # the older verifier, end to end


@pytest.fixture
def hidden(web):
    """A typed result with two parents, one of which bob cannot read, stored as /3 (record: slots and commitments)."""
    alice, bob = client(web, 'alice'), client(web, 'bob')
    seen = alice.upload_data(LAS.encode(), profile='las2/1', name='Seen', attribution='Synthetic', audience=['bob'], rights_confirmed=True, command_id='c5-seen')
    unseen = alice.upload_data(LAS.replace('100 0', '100 5').encode(), profile='las2/1', name='Hidden', attribution='Synthetic', audience=['bob'], rights_confirmed=True, command_id='c5-hidden')
    alice.share(seen, read=['bob'], expected_generation=alice.grants(seen).generation)
    receipt = alice.publish_derived(PointSet.write([(0, 0, 3), (10, 5, None)], **UNKNOWN), name='C5 points', from_=[seen, unseen], method=METHOD, command_id='c5-derive')
    info = Caller(web, 'session', 'alice').ok('publications', 'info', {'asset_id': receipt.asset_id})
    Caller(web, 'session', 'alice').ok('publications', 'share', {'asset_id': receipt.asset_id, 'audience': ['bob'], 'reuse_audience': [], 'expected_generation': info['grants_generation']})
    _, document = upgrade(web.a, {'project_id': 'p', 'asset_id': receipt.asset_id, 'revision': receipt.revision}, METHOD)
    return alice, bob, seen, unseen, receipt, document


def test_the_typed_path_declares_3_and_a_hidden_parent_is_in_no_bundle_file(hidden, monkeypatch, tmp_path):
    alice, bob, seen, unseen, receipt, document = hidden
    typed = bob.read_data(receipt.asset_id, receipt.revision)
    bob.export([(receipt.asset_id, receipt.revision, None)], tmp_path / 'bob')
    descriptor = json.loads(next((tmp_path / 'bob').rglob('descriptor.json')).read_text())
    assert descriptor['manifest']['schema'] == V3 and descriptor['manifest']['derivation_record'] == document['derivation_record']
    assert descriptor['parent_visibility'] == 'restricted' and [p['key'] for p in descriptor['parents']] == [seen.asset_id]
    files = every_file(tmp_path / 'bob')
    for ident in (unseen.asset_id, unseen.revision): assert ident.encode() not in files  # descriptor, derivation record and every file
    for ident in (seen.asset_id, seen.revision): assert ident.encode() in files
    assert open_bundle(tmp_path / 'bob').assets[0].entry['asset_id'] == receipt.asset_id and typed is not None
    monkeypatch.setattr(ophiolite.client, 'PROFILES', '')
    bob.export([(receipt.asset_id, receipt.revision, None)], tmp_path / 'view')
    view = json.loads(next((tmp_path / 'view').rglob('descriptor.json')).read_text())
    assert view['manifest']['schema'] == V2 and view['manifest']['digest'] == document['digest_v2'] and view['derivation']['method']['name'] == METHOD['name']
    assert older_reader(tmp_path, tmp_path / 'view') == ['opened']


def test_the_story_what_changed_and_dependents_equal_the_route_answers(web, made):
    bob, parent, first = made
    second = publish(bob, parent, 'c5-story-2', picks={'how': 'typed', 'clean': 35, 'shale': 150}, name='Shale volume HON-GT-01')
    sdk = client(web, 'bob')
    route = lambda op, body: bob.ok('results', op, body)
    one = lambda r: {'asset_id': r['asset_id'], 'revision': r['revision']}
    assert sdk.story(first['asset_id'], first['revision']) == route('story', one(first))
    assert sdk.story(second['asset_id'], second['revision'], limit=1) == route('story', {**one(second), 'limit': 1})
    changed = sdk.what_changed((first['asset_id'], first['revision']), (second['asset_id'], second['revision']))
    assert changed == route('what-changed', {'a': one(first), 'b': one(second)})
    assert any(s['label'] == 'Clean value' and (s['a'], s['b']) == ('30', '35') for s in changed['settings'])
    below = sdk.dependents(parent['asset_id'], parent['revision'])
    assert below == route('dependents', one(parent)) and below['schema'] == 'ophiolite.dependents/1'
    preview = client(web, 'bob', 'read,write,compute').remake(first['asset_id'], first['revision'])  # remake-run is a compute route
    assert preview == route('remake-run', {**one(first), 'step': 'preview'}) and preview['inputs'][0]['slot'] == 'gamma'
