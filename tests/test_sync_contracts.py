"""Defensive maintainer-input parsing, separately from the real pinned-tree check."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sync_contracts',ROOT/'tools/sync_contracts.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)

@pytest.fixture
def source(monkeypatch):
    state={'dirty':False,'mode':b'100644','files':{
        'registry.json':json.dumps({'version':'1.0.0','schemas':[],'profiles':[],'documents':[]}).encode(),
        'registry-schema.json':b'{"type":"object"}','profile-schema.json':b'{"type":"object"}'}}
    def git(root,*args):
        if args[0]=='status':return b'dirty' if state['dirty'] else b''
        if args[0]=='rev-parse':return (('a'*40 if args[1]=='HEAD' else 'd'*40 if args[1]=='c'*40+':contracts' else 'b'*40)+'\n').encode()
        names=sorted(state['files']);objects={hashlib.sha1(name.encode()).hexdigest():name for name in names}
        if args[0]=='ls-tree':return b'\0'.join(state['mode']+b' blob '+digest.encode()+b'\tcontracts/'+name.encode() for digest,name in objects.items())+b'\0'
        if args[0]=='cat-file':return state['files'][objects[args[2]]]
        raise AssertionError(args)
    monkeypatch.setattr(sync,'git',git)
    return state

@pytest.mark.parametrize('case,message',[
 ('dirty','must be clean'),('missing','Incomplete registry'),('mode','regular'),('path','Unsafe contract'),
 ('external','External/absolute'),('missingref','Missing or unsafe'),('unsafe-ref','Missing or unsafe'),('fragment','Unsupported reference fragment')])
def test_source_guard_refusals(source,case,message):
    if case=='dirty':source['dirty']=True
    if case=='missing':del source['files']['profile-schema.json']
    if case=='mode':source['mode']=b'120000'
    if case=='path':source['files']['../outside']=b'{}'
    refs={'external':'https://foreign.invalid/schema','missingref':'missing.json','unsafe-ref':'../registry.json','fragment':'#anchor'}
    if case in refs:source['files']['registry-schema.json']=json.dumps({'$ref':refs[case]}).encode()
    with pytest.raises(ValueError,match=message):sync.snapshot(Path('/synthetic-git-response'))

@pytest.mark.parametrize('case',['tree','bytes','extra'])
def test_sync_checkpoint_guards(source,tmp_path,monkeypatch,case):
    files=sync.snapshot(Path('/synthetic-git-response'));destination=tmp_path/'ophiolite/contracts';destination.mkdir(parents=True)
    for name,raw in files.items():(destination/name).write_bytes(raw)
    if case=='tree':
        path=destination/'SOURCE.json';value=json.loads(path.read_text());value['platform_commit']='c'*40;path.write_text(json.dumps(value,indent=2)+'\n')
    if case=='bytes':(destination/'profile-schema.json').write_text('changed')
    if case=='extra':(destination/'unreviewed.txt').write_text('unknown input')
    monkeypatch.setattr(sync,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['sync','--source','/synthetic-git-response']+([] if case=='extra' else ['--check']))
    with pytest.raises(ValueError):sync.main()


def test_local_ref_resolution_and_complete_snapshot(source):
    source['files']['registry-schema.json']=b'{"$defs":{"Item":{"type":"string"}},"$ref":"#/$defs/Item"}'
    files=sync.snapshot(Path('/synthetic-git-response'))
    assert set(files)==set(source['files'])|{'SOURCE.json'}
    assert all(files[name]==raw for name,raw in source['files'].items())
