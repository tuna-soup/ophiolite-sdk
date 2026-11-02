"""E138 s0 C2 (strategy rev 3 C2; decision D86; acceptance 3's local part; R1-17, R2-12): the work folder refuses
before any write where a round trip may not write, unpacks only members that stay inside it, kills every process
group it started, and says it is removed only once it is gone."""
import importlib.util
import os
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('roundtrip_workfolder', ROOT / 'conformance/roundtrip/workfolder.py')
wf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wf
spec.loader.exec_module(wf)


@pytest.fixture
def volume(tmp_path):
    """A volume of the test's own, and forbidden roots of its own beside it (tmp_path itself is under TMPDIR)."""
    v = tmp_path / 'volume'
    v.mkdir()
    return v, [tmp_path / 'forbidden']


def archive(path, members, links=()):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in members.items(): z.writestr(name, data)
        for name, to in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, to)
    return path


def listing(p):
    return sorted(str(x.relative_to(p)) for x in p.rglob('*')) if p.exists() else None


@pytest.mark.parametrize('where', ['/tmp', '~/ophiolite-staging', 'deposits', 'licensed', 'repository', 'gettempdir'])
def test_create_refuses_before_any_write_where_a_round_trip_may_not_write(where):
    path = {'/tmp': Path('/tmp'), '~/ophiolite-staging': Path.home() / 'ophiolite-staging', 'deposits': wf.VOLUME / 'osd-deposits/terranubis',
            'licensed': wf.VOLUME / 'licensed-data', 'repository': ROOT / 'conformance', 'gettempdir': Path(wf.tempfile.gettempdir())}[where]
    before = sorted(os.listdir(path)) if path.is_dir() and os.access(path, os.R_OK) else None
    with pytest.raises(wf.Refused):
        wf.WorkFolder.create(path)
    assert (sorted(os.listdir(path)) if path.is_dir() and os.access(path, os.R_OK) else None) == before


def test_a_volume_reached_through_a_link_into_a_forbidden_root_is_refused(volume, tmp_path):
    v, forbidden = volume
    forbidden[0].mkdir()
    (tmp_path / 'link').symlink_to(forbidden[0])
    (forbidden[0] / 'sub').mkdir()
    for through in (tmp_path / 'link', tmp_path / 'link/sub'):  # the volume a link, and a link as its ancestor
        with pytest.raises(wf.Refused, match='does not write under'):
            wf.WorkFolder.create(through, forbidden)
    assert listing(forbidden[0]) == ['sub']


def test_the_work_folder_is_private_to_this_user(volume):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)
    mode = os.lstat(folder.path)
    assert (stat.S_IMODE(mode.st_mode), mode.st_uid, folder.path.parent) == (0o700, os.getuid(), v)
    assert folder.close() is True and listing(v) == []


@pytest.mark.parametrize('members, links, says', [
    ({'../escape.txt': 'x'}, (), 'would leave'),
    ({'/abs.txt': 'x'}, (), 'would leave'),
    ({'ok.txt': 'x'}, [('link', '/etc/passwd')], 'symbolic link'),
    ({'a\\..\\..\\b': 'x'}, (), 'would leave')])
def test_a_member_that_leaves_the_folder_or_is_a_link_is_refused_before_one_byte(volume, tmp_path, members, links, says):
    v, forbidden = volume
    with wf.WorkFolder.create(v, forbidden) as folder:
        with pytest.raises(wf.Refused, match=says):
            folder.extract(archive(tmp_path / 'a.zip', members, links))
        assert listing(folder.path) == []
    assert listing(tmp_path / 'volume') == [] and not (tmp_path / 'escape.txt').exists()


def test_a_destination_that_is_a_link_or_is_reached_through_one_is_refused(volume, tmp_path):
    v, forbidden = volume
    outside = tmp_path / 'outside'
    outside.mkdir()
    with wf.WorkFolder.create(v, forbidden) as folder:
        (folder.path / 'survey').symlink_to(outside)
        (folder.path / 'up').symlink_to(outside)
        z = archive(tmp_path / 'a.zip', {'f.txt': 'x'})
        with pytest.raises(wf.Refused, match='symbolic link'):
            folder.extract(z, 'survey')
        with pytest.raises(wf.Refused, match='symbolic link'):
            folder.extract(z, 'up/survey')
    assert listing(outside) == []


def test_an_extraction_that_fails_after_a_member_was_written_removes_what_it_wrote(volume, tmp_path, monkeypatch):
    v, forbidden = volume
    real, calls = zipfile.ZipFile._extract_member, []

    def failing(self, member, *a, **kw):
        calls.append(member)
        if len(calls) == 2: raise OSError('disk full')
        return real(self, member, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, '_extract_member', failing)
    with wf.WorkFolder.create(v, forbidden) as folder:
        with pytest.raises(OSError, match='disk full'):
            folder.extract(archive(tmp_path / 'a.zip', {'one.txt': '1', 'two.txt': '2'}))
        assert len(calls) == 2 and listing(folder.path) == []


GROUP = ("import os, signal, subprocess, sys, time\n"
         "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
         "subprocess.Popen([sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'])\n"
         "open('started', 'w').close()\n"
         "time.sleep(120)\n")


def running(pgid):
    """The group's processes that are not zombies (a container's first process may never reap an orphan)."""
    out = []
    for stat_file in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat_file.read_text().rsplit(')', 1)[1].split()
        except OSError:
            continue
        if int(fields[2]) == pgid and fields[0] != 'Z': out.append(stat_file.parent.name)
    return out


def gone(pgid, within=10.0):
    """killpg(pgid, 0) finds no process of the group, or only zombies are left of it."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        if not running(pgid): return True
        time.sleep(0.1)
    return False


def started(folder, within=10.0):
    deadline = time.monotonic() + within
    while not (folder.path / 'started').exists() and time.monotonic() < deadline: time.sleep(0.05)


def test_a_timeout_kills_the_whole_group_including_a_descendant_that_ignores_sigterm(volume):
    v, forbidden = volume
    with wf.WorkFolder.create(v, forbidden) as folder:
        with pytest.raises(subprocess.TimeoutExpired):
            folder.run([sys.executable, '-c', GROUP], timeout=3)
        assert gone(folder.children[0].pid)


def test_an_interrupt_kills_the_whole_group(volume):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)

    def interrupt(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        signal.alarm(3)
        with pytest.raises(KeyboardInterrupt):
            folder.run([sys.executable, '-c', GROUP])
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert gone(folder.children[0].pid)
    assert folder.close() is True


def test_close_kills_a_group_whose_leader_has_already_exited(volume):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)
    leader = ("import subprocess, sys\n"
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
              "open('started', 'w').close()\n")
    assert folder.run([sys.executable, '-c', leader], timeout=30) == 0
    pgid = folder.children[0].pid
    assert not gone(pgid, within=0.5)  # the descendant outlived its leader
    assert folder.close() is True and gone(pgid)


def test_a_normal_run_and_extraction_then_removal(volume, tmp_path):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)
    target = folder.extract(archive(tmp_path / 'a.zip', {'S/a.txt': 'a', 'S/b/c.txt': 'c'}))
    assert listing(target) == ['S', 'S/a.txt', 'S/b', 'S/b/c.txt']
    assert folder.run([sys.executable, '-c', "open('ran', 'w').write('yes')"], timeout=30) == 0
    assert (folder.path / 'ran').read_text() == 'yes'
    assert folder.close() is True and listing(v) == []


def test_cleanup_removes_a_link_inside_the_folder_without_following_it(volume, tmp_path):
    v, forbidden = volume
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('kept')
    folder = wf.WorkFolder.create(v, forbidden)
    (folder.path / 'link').symlink_to(outside)
    (folder.path / 'inner').mkdir()
    (folder.path / 'inner/file-link').symlink_to(outside / 'keep.txt')
    assert folder.close() is True and listing(v) == []
    assert (outside / 'keep.txt').read_text() == 'kept'


def test_cleanup_refuses_a_folder_replaced_by_a_link(volume, tmp_path):
    v, forbidden = volume
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('kept')
    folder = wf.WorkFolder.create(v, forbidden)
    os.rmdir(folder.path)
    folder.path.symlink_to(outside)
    assert folder.close() is False
    assert (outside / 'keep.txt').read_text() == 'kept'


def test_a_removal_that_fails_answers_false(volume, monkeypatch):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)
    (folder.path / 'f.txt').write_text('x')
    monkeypatch.setattr(wf.shutil, 'rmtree', lambda *a, **kw: None)
    assert folder.close() is False
    monkeypatch.undo()
    assert folder.close() is True


# --- E138 s1 D3 (R1-13, mutation 5's digest part) and D11 -------------------------------------------------------------

def test_the_archive_facts_are_read_in_blocks_and_see_bytes_and_mtime(tmp_path, monkeypatch):
    import hashlib
    path = tmp_path / 'deposit.zip'
    path.write_bytes(b'abc' * 2_000_000)  # 6 MB: two blocks
    reads = []
    real = open
    def counted(p, mode='r', *a, **k):
        f = real(p, mode, *a, **k)
        if mode == 'rb':
            read = f.read
            f.read = lambda n=-1: (reads.append(n), read(n))[1]
        return f
    monkeypatch.setattr('builtins.open', counted)
    facts = wf.archive_facts(path)
    monkeypatch.undo()
    assert facts['sha256'] == hashlib.sha256(b'abc' * 2_000_000).hexdigest() and facts['size'] == 6_000_000
    assert reads and set(reads) == {wf.BLOCK}  # never a whole-file read
    os.utime(path, ns=(facts['mtime_ns'], facts['mtime_ns'] + 1))
    assert wf.differing(facts, wf.archive_facts(path)) == 1  # the same bytes with another mtime
    path.write_bytes(b'abd' * 2_000_000)
    os.utime(path, ns=(facts['mtime_ns'], facts['mtime_ns']))
    assert wf.differing(facts, wf.archive_facts(path)) == 1  # other bytes, the old mtime restored


def test_the_survey_digests_count_a_changed_an_added_and_a_deleted_file(tmp_path):
    survey = tmp_path / 'Syn_Survey'
    (survey / 'Seismics').mkdir(parents=True)
    (survey / '.survey').write_text('Name: Syn_Survey\n')
    (survey / 'Seismics' / 'Syn.cbvs').write_bytes(b'\0' * 10)
    before = wf.tree_digests(survey)
    assert sorted(before) == ['.survey', 'Seismics/Syn.cbvs'] and wf.differing(before, wf.tree_digests(survey)) == 0
    (survey / 'Seismics' / 'Syn.cbvs').write_bytes(b'\1' * 10)
    assert wf.differing(before, wf.tree_digests(survey)) == 1
    (survey / 'Seismics' / 'Syn.par').write_text('x')
    (survey / '.survey').unlink()
    assert wf.differing(before, wf.tree_digests(survey)) == 3
    (survey / 'link').symlink_to(tmp_path)
    assert wf.tree_digests(survey)['link'] == 'link: %s' % tmp_path  # recorded, never followed


def test_a_child_s_home_tmp_and_xdg_folders_are_the_work_folder_s(volume):
    v, forbidden = volume
    folder = wf.WorkFolder.create(v, forbidden)
    env = folder.child_env({'PATH': '/usr/bin', 'HOME': '/home/someone'})
    out = folder.path / 'env.txt'
    code = folder.run([sys.executable, '-c', 'import os, tempfile; print(os.environ["HOME"], tempfile.gettempdir(), os.environ["XDG_CACHE_HOME"])'],
                      timeout=30, env=env, stdout=open(out, 'w'))
    assert code == 0
    home, tmp, cache = out.read_text().split()
    assert all(folder.path in Path(p).parents for p in (home, tmp, cache)) and env['PATH'] == '/usr/bin'
    (folder.path / 'home' / '.cache').rmdir()
    (folder.path / 'home' / '.cache').symlink_to(v)
    with pytest.raises(wf.Refused):
        folder.child_env({})
    assert folder.close() is True


def test_strays_count_only_the_run_s_names_that_appeared_or_changed(tmp_path):
    """D11: a listing before and after; another session's new file in the same root never counts."""
    roots = [tmp_path / 'tmp', tmp_path / 'home', tmp_path / 'no-such-root']
    for r in roots[:2]: r.mkdir()
    (roots[0] / 'e138-old').write_text('x'); (roots[0] / '.X99-lock').write_text('1')
    before = wf.listing(roots)
    assert set(before) == {(str(roots[0]), 'e138-old'), (str(roots[0]), '.X99-lock')}
    (roots[0] / 'someone-else').write_text('x')  # another session's
    (roots[1] / 'xvfb-run.abc').mkdir()  # appeared
    os.utime(roots[0] / '.X99-lock', ns=(1, 1))  # changed
    assert wf.strays(before, wf.listing(roots)) == 2
    (roots[1] / 'xvfb-run.abc').rmdir(); (roots[0] / '.X99-lock').unlink()
    assert wf.strays(before, wf.listing(roots)) == 0  # gone is clean; e138-old was there before
