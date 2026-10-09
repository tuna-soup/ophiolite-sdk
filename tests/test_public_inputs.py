import importlib.util
import json
import shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_inputs',ROOT/'tools/check_public_inputs.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

def test_current_inputs():assert audit.verify()==190  # E94: derivation, parameters and parameter-labels contracts and three story fixtures; E55: the reader registry; E53: three section schemas, six profiles, nine fixtures, the section capability and the 2.5 manifest fixture

@pytest.mark.parametrize('case',['missing','duplicate','hash','rights','evidence','source','canary','notice','third-party-licence','third-party-notice','third-party-register'])
def test_unqualified_input_refusal(tmp_path,case):
    for name in ('LICENSE','NOTICE','THIRD_PARTY.md'):shutil.copyfile(ROOT/name,tmp_path/name)
    shutil.copytree(ROOT/'ophiolite/contracts',tmp_path/'ophiolite/contracts')
    shutil.copytree(ROOT/'tests/recordings',tmp_path/'tests/recordings')
    shutil.copytree(ROOT/'tests/fixtures',tmp_path/'tests/fixtures')
    for source in (ROOT/'ophiolite/templates').glob('*/data/*'):
        if source.is_file():
            target=tmp_path/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    path=tmp_path/'tests/fixtures/PROVENANCE.json';path.parent.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'tests/fixtures/PROVENANCE.json').read_text())
    if case=='missing':manifest['inputs'].pop()
    if case=='duplicate':manifest['inputs'].append(manifest['inputs'][0])
    if case=='hash':manifest['inputs'][0]['sha256']='0'*64
    if case=='rights':manifest['inputs'][0]['disposition']='unverified'
    if case=='evidence':manifest['inputs'][0]['evidence']=''
    if case=='source':manifest['inputs'][0]['source_commit']='0'*40
    if case=='canary':
        # Correct hashes isolate the credential scanner from integrity checks.
        import hashlib
        row=manifest['inputs'][0];data=b'E4_SECRET_' + b'CANARY_DO_NOT_PUBLISH'
        (tmp_path/row['path']).write_bytes(data);row['sha256']=hashlib.sha256(data).hexdigest()
        src=tmp_path/'ophiolite/contracts/SOURCE.json';value=json.loads(src.read_text())
        value['files'][row['path'].removeprefix('ophiolite/contracts/')]=row['sha256'];src.write_text(json.dumps(value))
    if case=='notice':(tmp_path/'NOTICE').unlink()
    excerpt=next(row for row in manifest['inputs'] if row['disposition']=='third-party-attribution')  # E52
    if case=='third-party-licence':excerpt['license']='Apache-2.0'
    if case=='third-party-register':excerpt['evidence']='Reviewed.'
    if case=='third-party-notice':(tmp_path/'THIRD_PARTY.md').write_text((ROOT/'THIRD_PARTY.md').read_text().replace(excerpt['attribution'],''))
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):audit.verify(tmp_path)


def public_copy(tmp_path):
    for name in ('LICENSE','NOTICE','THIRD_PARTY.md'):shutil.copyfile(ROOT/name,tmp_path/name)
    shutil.copytree(ROOT/'ophiolite/contracts',tmp_path/'ophiolite/contracts')
    shutil.copytree(ROOT/'tests/recordings',tmp_path/'tests/recordings')
    shutil.copytree(ROOT/'tests/fixtures',tmp_path/'tests/fixtures')
    for source in (ROOT/'ophiolite/templates').glob('*/data/*'):
        if source.is_file():
            target=tmp_path/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    target=tmp_path/'tests/fixtures/PROVENANCE.json';target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'tests/fixtures/PROVENANCE.json',target)
    return target

@pytest.mark.parametrize('case',['schema','body','path'])
def test_provenance_independent_guards(tmp_path,case):
    target=public_copy(tmp_path);manifest=json.loads(target.read_text())
    if case=='schema':manifest['schema']='unknown/1'
    if case=='body':(tmp_path/manifest['inputs'][0]['path']).write_bytes(b'changed but credential-free')
    if case=='path':
        row=manifest['inputs'][0];old=row['path'];row['path']='ophiolite/contracts/../outside'
        shutil.copyfile(tmp_path/old,tmp_path/'ophiolite/outside')
        source=tmp_path/'ophiolite/contracts/SOURCE.json';value=json.loads(source.read_text())
        value['files']['../outside']=value['files'].pop(old.removeprefix('ophiolite/contracts/'))
        source.write_text(json.dumps(value))
    target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match={'schema':'provenance schema','body':'hash mismatch','path':'Unsafe provenance'}[case]):audit.verify(tmp_path)

@pytest.mark.parametrize('case',['omit','bytecode','unexpected','tamper','missing'])
def test_archive_guards(tmp_path,case):
    import zipfile
    root=tmp_path/'root';(root/'ophiolite/contracts').mkdir(parents=True,exist_ok=True)
    (root/'ophiolite/contracts/a.json').write_text('{}')
    (root/'ophiolite/client.py').write_text('# implementation\n')
    members={'ophiolite/contracts/a.json':b'{}','ophiolite/client.py':b'# implementation\n'}
    if case=='omit':del members['ophiolite/contracts/a.json']
    if case=='bytecode':
        path=root/'ophiolite/__pycache__/probe.pyc';path.parent.mkdir();path.write_bytes(b'cache')
        members['ophiolite/__pycache__/probe.pyc']=b'cache'
    if case=='unexpected':members['outside.txt']=b'extra'
    if case=='tamper':members['ophiolite/client.py']=b'changed'
    if case=='missing':members['ophiolite/absent.py']=b'extra'
    archive=tmp_path/'test.whl'
    with zipfile.ZipFile(archive,'w') as package:
        for name,raw in members.items():package.writestr(name,raw)
    with pytest.raises(ValueError):audit.archive(archive,root)


def test_template_source_archive_matches_audited_source(tmp_path):
    import io,tarfile
    root=tmp_path/'root';(root/'ophiolite/contracts').mkdir(parents=True)
    (root/'ophiolite/contracts/a.json').write_text('{}')
    (root/'templates/example').mkdir(parents=True);(root/'templates/example/app.py').write_text('print("reviewed")\n')
    archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive,'w:gz') as output:
        for name,raw in {'ophiolite/contracts/a.json':b'{}','templates/example/app.py':b'print("changed")\n'}.items():
            member=tarfile.TarInfo('source/'+name);member.size=len(raw);output.addfile(member,io.BytesIO(raw))
    with pytest.raises(ValueError,match='Archive differs from audited source: templates/'):
        audit.archive(archive,root)
