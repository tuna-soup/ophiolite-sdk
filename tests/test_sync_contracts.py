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


# H44 item 2a: the snapshot keeps tests/fixtures/PROVENANCE.json true. The public tree is copied as
# test_public_inputs.py copies it; the fake git serves the real committed contract files (a coherent snapshot), with one
# mutation per case outside the registry's reference closure.
CHANGED, REMOVED, ADDED = 'assets/v1/README.md', 'bundles/v1/README.md', 'docs/h44-new-note.md'


@pytest.fixture
def public(tmp_path, monkeypatch):
    from test_public_inputs import public_copy
    public_copy(tmp_path)
    contracts = ROOT/'ophiolite/contracts'
    recorded = json.loads((contracts/'SOURCE.json').read_text())
    files = {p.relative_to(contracts).as_posix(): p.read_bytes() for p in contracts.rglob('*') if p.is_file() and p.name != 'SOURCE.json'}
    def git(root, *args):
        if args[0] == 'status': return b''
        if args[0] == 'rev-parse': return ((recorded['platform_commit'] if args[1] == 'HEAD' else recorded['contracts_tree'])+'\n').encode()
        objects = {hashlib.sha1(name.encode()).hexdigest(): name for name in sorted(files)}
        if args[0] == 'ls-tree': return b'\0'.join(b'100644 blob '+d.encode()+b'\tcontracts/'+n.encode() for d, n in objects.items())+b'\0'
        if args[0] == 'cat-file': return files[objects[args[2]]]
        raise AssertionError(args)
    monkeypatch.setattr(sync, 'git', git)
    monkeypatch.setattr(sync, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['sync', '--source', '/synthetic-git-response'])
    state = {'files': files, 'root': tmp_path, 'record': tmp_path/'tests/fixtures/PROVENANCE.json'}
    def run(change=None):
        if change: change(files)
        sync.snapshot(Path('/synthetic-git-response'))  # precondition: the mutated snapshot is still a valid one
        return sync.main()
    state['run'] = run
    return state


def audit(root):
    spec = importlib.util.spec_from_file_location('public_inputs', ROOT/'tools/check_public_inputs.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.verify(root)


def rows(state):
    return {row['path']: row for row in json.loads(state['record'].read_text())['inputs']}


def test_changed_bytes_rewrite_the_row(public):
    assert public['run'](lambda f: f.__setitem__(CHANGED, f[CHANGED]+b'\nOne more line.\n')) == 0
    assert rows(public)['ophiolite/contracts/'+CHANGED]['sha256'] == hashlib.sha256(public['files'][CHANGED]).hexdigest()
    assert audit(public['root']) == 308  # red before: Provenance hash mismatch


def test_a_new_platform_commit_moves_every_source_commit(public, monkeypatch):
    real = sync.git
    monkeypatch.setattr(sync, 'git', lambda root, *a: b'f'*40+b'\n' if a[:2] == ('rev-parse', 'HEAD') else real(root, *a))
    assert public['run']() == 0
    assert {r['source_commit'] for p, r in rows(public).items() if p.startswith('ophiolite/contracts/')} == {'f'*40}
    assert audit(public['root']) == 308  # red before: Source evidence mismatch


def test_a_file_removed_upstream_is_pruned_and_its_row_dropped(public):
    assert public['run'](lambda f: f.pop(REMOVED)) == 0  # red before: Untracked snapshot paths
    assert not (public['root']/'ophiolite/contracts'/REMOVED).exists()
    assert 'ophiolite/contracts/'+REMOVED not in rows(public)
    assert audit(public['root']) == 307


def added(public):
    code = public['run'](lambda f: f.__setitem__(ADDED, b'# A new note\n'))
    return code, rows(public)['ophiolite/contracts/'+ADDED]


def test_a_new_file_is_pending_review(public):
    assert added(public)[1]['disposition'] == 'pending-review'


def test_a_new_file_has_no_evidence(public):
    assert added(public)[1]['evidence'] == ''


def test_a_new_file_exits_3(public):
    assert added(public)[0] == 3


def test_a_pending_row_keeps_the_gate_closed(public):
    added(public)
    with pytest.raises(ValueError, match='Redistribution evidence missing for ophiolite/contracts/'+ADDED): audit(public['root'])


def test_an_unchanged_snapshot_leaves_provenance_byte_identical(public):
    before = public['record'].read_bytes()
    assert public['run']() == 0
    assert public['record'].read_bytes() == before


def test_untouched_rows_keep_their_fields_and_order(public):
    before = json.loads(public['record'].read_text())['inputs']
    public['run'](lambda f: (f.__setitem__(CHANGED, b'changed\n'), f.pop(REMOVED)))
    after = json.loads(public['record'].read_text())['inputs']
    assert [r['path'] for r in after] == [r['path'] for r in before if r['path'] != 'ophiolite/contracts/'+REMOVED]
    for old, new in zip([r for r in before if r['path'] != 'ophiolite/contracts/'+REMOVED], after):
        assert {k: new[k] for k in ('evidence', 'license', 'origin', 'disposition')} == {k: old[k] for k in ('evidence', 'license', 'origin', 'disposition')}
        if old['path'] != 'ophiolite/contracts/'+CHANGED: assert new == old


def test_an_unknown_local_file_refuses_and_nothing_is_pruned_or_written(public):
    destination = public['root']/'ophiolite/contracts'
    (destination/'local-notes.md').write_text('someone\'s file')
    before = {p: p.read_bytes() for p in public['root'].rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='Untracked snapshot paths'):
        public['run'](lambda f: (f.pop(REMOVED), f.__setitem__(CHANGED, b'changed\n')))
    assert {p: p.read_bytes() for p in public['root'].rglob('*') if p.is_file()} == before


def test_the_real_tool_exits_3_as_a_process(tmp_path):
    """Round 3 (C4): the exit status of the tool run as a program, against a real Platform-shaped git repository."""
    import shutil, subprocess
    from test_public_inputs import public_copy
    sdk, platform = tmp_path/'sdk', tmp_path/'platform'
    sdk.mkdir(); public_copy(sdk)
    (sdk/'tools').mkdir(); shutil.copyfile(ROOT/'tools/sync_contracts.py', sdk/'tools/sync_contracts.py')
    shutil.copytree(ROOT/'ophiolite/contracts', platform/'contracts', ignore=shutil.ignore_patterns('SOURCE.json'))
    (platform/'contracts'/ADDED).write_text('# A new note\n')
    for args in (('init', '-q'), ('add', '-A'), ('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'c')):
        subprocess.run(['git', '-C', str(platform), *args], check=True, capture_output=True)
    done = subprocess.run([sys.executable, str(sdk/'tools/sync_contracts.py'), '--source', str(platform)], capture_output=True, text=True)
    assert done.returncode == 3, done.stdout + done.stderr  # mutation: the entry point drops main()'s return value
    assert 'Pending review (write disposition and evidence by hand): ophiolite/contracts/'+ADDED in done.stdout
    assert 'Provenance: 309 inputs' in done.stdout
