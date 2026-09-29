"""E30b B7: a derived publication in a portable bundle. Whole-bundle redaction (an exporter who cannot read a
parent gets a bare commitment and the parent's id appears in no file), a tampered method caught by the
manifest digest even when the outer checksum is recomputed, and the frozen pre-E30 reader's one outcome."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import io
from pathlib import Path
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.bundle import open_bundle
from ophiolite.errors import VerificationFailed
from ophiolite.typed import PointSet
from tests.gateway.test_in_process_publish import LAS_TEXT,UNKNOWN,client

FROZEN='72c4bde361e58fd71b806d0c3284c994cb98bdfa'  # the SDK every release before E30 pins (E28)
ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def published(web):
    alice,bob=client(web,'alice','delegate'),client(web,'bob','delegate')
    seen=alice.upload_data(LAS_TEXT.encode(),profile='las2/1',name='Seen',attribution='Synthetic',audience=['bob'],rights_confirmed=True,command_id='b7-seen')
    hidden=alice.upload_data(LAS_TEXT.replace('100 0','100 5').encode(),profile='las2/1',name='Hidden',attribution='Synthetic',audience=['bob'],rights_confirmed=True,command_id='b7-hidden')
    alice.share(seen,read=['bob'],expected_generation=alice.grants(seen).generation)
    points=PointSet.write([(0,0,3),(10,5,None)],**UNKNOWN)
    receipt=alice.publish_derived(points,name='B7 points',from_=[seen,hidden],method={'name':'scipy.spatial.Delaunay','library':'scipy','version':'1.14.1'},command_id='b7-derive')
    from project_gateway.tests.test_one_api_matrix import Caller
    info=Caller(web,'session','alice').ok('publications','info',{'asset_id':receipt.asset_id})
    Caller(web,'session','alice').ok('publications','share',{'asset_id':receipt.asset_id,'audience':['bob'],'reuse_audience':[],'expected_generation':info['grants_generation']})
    return alice,bob,seen,hidden,receipt


def every_file(folder):
    return b''.join(p.read_bytes() for p in sorted(Path(folder).rglob('*')) if p.is_file())


def test_an_exporter_who_cannot_read_a_parent_gets_a_bare_commitment_and_the_id_nowhere(published,tmp_path):
    alice,bob,seen,hidden,receipt=published
    bob.export([(receipt.asset_id,receipt.revision,None)],tmp_path/'bob')
    descriptor=json.loads(next((tmp_path/'bob').rglob('descriptor.json')).read_text())
    assert descriptor['parent_visibility']=='restricted' and [p['key'] for p in descriptor['parents']]==[seen.asset_id]
    assert sorted(len(e) for e in descriptor['manifest']['lineage'])==[1,4]  # one bare {commitment}, one disclosed entry
    assert hidden.asset_id.encode() not in every_file(tmp_path/'bob')  # every serialized field of every file
    assert open_bundle(tmp_path/'bob').assets[0].entry['asset_id']==receipt.asset_id
    alice.export([(receipt.asset_id,receipt.revision,None)],tmp_path/'alice')
    full=json.loads(next((tmp_path/'alice').rglob('descriptor.json')).read_text())
    assert {p['key'] for p in full['parents']}=={seen.asset_id,hidden.asset_id} and full['derivation']['method']['name']=='scipy.spatial.Delaunay'


def test_a_changed_method_is_caught_by_the_manifest_digest_not_the_outer_checksum(published,tmp_path):
    alice,_,_,_,receipt=published
    alice.export([(receipt.asset_id,receipt.revision,None)],tmp_path/'b')
    path=next((tmp_path/'b').rglob('descriptor.json'));document=json.loads(path.read_text())
    document['manifest']['method']['version']='9.9.9';document['derivation']['method']['version']='9.9.9'
    raw=(json.dumps(document,indent=2)+'\n').encode();path.write_bytes(raw)
    manifest=json.loads((tmp_path/'b'/'manifest.json').read_text())
    for item in (f for e in manifest['assets'] for f in e['files']):
        if item['path']==path.relative_to(tmp_path/'b').as_posix():item.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    (tmp_path/'b'/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with pytest.raises(VerificationFailed) as refused:open_bundle(tmp_path/'b')
    assert 'checksum' not in str(refused.value) and 'digest' in str(refused.value)


def test_an_upload_without_a_derivation_reads_normally(published,tmp_path):
    alice,_,seen,_,_=published
    opened=alice.export([(seen.asset_id,seen.revision,['GR'])],tmp_path/'u')
    descriptor=json.loads(next((tmp_path/'u').rglob('descriptor*.json')).read_text()) if list((tmp_path/'u').rglob('descriptor*.json')) else None
    assert descriptor is None or 'derivation' not in descriptor
    assert open_bundle(tmp_path/'u').assets[0].curves['GR'].view.values==[0,None,30]


def test_the_frozen_pre_e30_reader_refuses_a_2_manifest_with_one_outcome(published,tmp_path):
    alice,_,seen,_,receipt=published
    try:archive=subprocess.run(['git','-C',str(ROOT),'archive','--format=tar',FROZEN,'ophiolite'],capture_output=True,check=True).stdout
    except (subprocess.CalledProcessError,FileNotFoundError):pytest.skip('The pre-E30 SDK commit is not in this checkout')
    tarfile.open(fileobj=io.BytesIO(archive)).extractall(tmp_path/'frozen',filter='data')
    alice.export([(receipt.asset_id,receipt.revision,None)],tmp_path/'bundle')
    alice.export([(seen.asset_id,seen.revision,['GR'])],tmp_path/'upload')
    probe=('import sys,json\nfrom ophiolite.bundle import open_bundle\n'
           'try:open_bundle(sys.argv[1]);print(json.dumps(["opened"]))\n'
           'except Exception as e:print(json.dumps([type(e).__name__,str(e)]))\n')
    def frozen(bundle):
        out=subprocess.run([sys.executable,'-I','-c','import sys;sys.path.insert(0,sys.argv[2]);'+'exec(sys.argv[3])',str(bundle),str(tmp_path/'frozen'),probe],capture_output=True,text=True,check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])
    assert frozen(tmp_path/'upload')==['opened']  # the frozen reader works here: what follows is its answer to /2, not the environment
    # R6-2: the frozen public model (manifest schema literal /1) refuses the shape before any digest check
    assert frozen(tmp_path/'bundle')==['VerificationFailed','Scientific data does not satisfy the declared contract. No files were saved.']
