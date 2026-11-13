"""E164 s1 C2: every fenced block of the SDK README runs, in order, against `ophiolite demo` of the candidate wheel; a
block that cannot run carries `<!-- not-run: <reason> -->` and its reason is listed. The page runs in its own fresh
folder with its own demo (the site's start-here page is E164 slice 2's). Each test names the mutation it catches.

Every documented command runs as a subprocess of OPHIOLITE_TEST_WHEEL_PYTHON (this interpreter when it is unset, which
the output says), with that interpreter's folder first on PATH, so `ophiolite` and `python` are the wheel's. Hosted CI
serves a synthetic demo-compatible bundle whose wells, depths and values are the constants below, independent of the
README; the README's three-commands block is the F3-block bundle's own lines, so hosted CI runs the lines the demo
prints for the synthetic bundle and checks the block's shape. With OPHIOLITE_F3_BLOCK set (the lane host), the F3 test
runs every block verbatim and requires the three-commands block to be what the demo prints, byte for byte."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import zipfile
from test_demo_bundle_server import Log, demo_bundle, typed

SDK = Path(__file__).resolve().parents[1]
README = SDK / 'README.md'  # the site's start-here page is run by E164 slice 2; this module reads nothing above the SDK
INSTALL = 'the test installs the candidate wheel in its place'
PRINTED = ("these are the F3 bundle's lines (its asset and revision); hosted CI runs the lines the demo prints, and the "
           "lane-host run runs this block verbatim")
PERMITTED = [INSTALL, PRINTED]  # the exact not-run inventory of each page, in page order
LANGUAGES = ('sh', 'python')
EPIC = re.compile(r'\bE[0-9]{1,3}[a-z]?\b')
MARKER = re.compile(r'^<!-- not-run: (.*) -->$')
INDENT = '     '  # the demo prints each command indented five spaces

# The synthetic bundle (fixed constants of this test): the first log is first in the catalogue and first by well name,
# so the demo's fetch line and the README's Python block both read it.
FIRST = ('qs-log-1', 'QS-1', [(1500.0, 55.5), (1500.5, None), (1501.0, 0.0), (1501.5, 72.25)])
SECOND = ('qs-log-2', 'QS-2', [(900.0, 12.0), (900.5, 13.5), (901.0, 14.0)])


class Block:
    def __init__(self, language, lines, line, reason):
        self.language, self.lines, self.line, self.reason = language, lines, line, reason

    def __repr__(self):
        return 'Block(%s at line %d%s)' % (self.language, self.line, ', not-run' if self.reason is not None else '')


def blocks(text):
    """The fenced blocks of TEXT, each with the reason of the not-run marker on the line before it. A fence whose
    language is not sh or python, an unclosed fence, an empty reason or a marker not directly above a fence fails."""
    lines, found, i = text.split('\n'), [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            language = line[3:].strip()
            assert language in LANGUAGES, 'line %d: a fence in %r, not sh or python' % (i + 1, language or 'no language')
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith('```')), None)
            assert end is not None and lines[end] == '```', 'line %d: an unclosed fence' % (i + 1)
            marked = MARKER.match(lines[i - 1]) if i else None
            reason = marked.group(1) if marked else None
            assert reason is None or reason.strip(), 'line %d: a not-run marker without a reason' % i
            found.append(Block(language, lines[i + 1:end], i + 1, reason)); i = end + 1; continue
        if 'not-run' in line and not (MARKER.match(line) and i + 1 < len(lines) and lines[i + 1].startswith('```')):
            raise AssertionError('line %d: a not-run marker that is not directly above a fence' % (i + 1))
        i += 1
    fences = [n for n, line in enumerate(lines) if line.lstrip().startswith('```')]  # counted apart from the walk above
    assert len(fences) == 2 * len(found), 'fences %s do not pair into %d blocks' % (fences, len(found))
    return found


def checked(text):
    """The blocks of a page whose not-run inventory is exactly PERMITTED, with no epic number anywhere."""
    found = blocks(text)
    assert [b.reason for b in found if b.reason is not None] == PERMITTED
    assert EPIC.findall(text) == []
    return found


def demo_line(found):
    """The block and line that start the demo, and the bundle path it names."""
    for block in found:
        for line in block.lines:
            argv = shlex.split(line)
            if block.reason is None and argv[:2] == ['ophiolite', 'demo'] and argv[2:3] != ['stop']:
                assert argv[2:3] == ['--bundle'] and len(argv) == 4, line
                return block, line, argv[3]
    raise AssertionError('no block starts ophiolite demo')


def shape(argv):
    """ARGV with what names one bundle's objects masked: the asset, the revision, the well in the output folder, and the
    interpreter (the demo prints its own path; the README says python)."""
    out = list(argv)
    for n, word in enumerate(out):
        if n and out[n - 1] in ('--asset', '--revision'): out[n] = '<%s>' % out[n - 1][2:]
        if n and out[n - 1] == '--output': out[n] = re.sub(r'[^/]*-GR$', '<well>-GR', word)
    if out and (out[0] == 'python' or Path(out[0]).name.startswith('python')): out[0] = '<python>'
    return out


def wheel_python():
    given = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if given: return given, 'the candidate wheel (OPHIOLITE_TEST_WHEEL_PYTHON)'
    return sys.executable, 'this interpreter, OPHIOLITE_TEST_WHEEL_PYTHON being unset'


def environment(python, home):
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}
    if os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON'): env.pop('PYTHONPATH', None)  # the wheel's package, not the tree's
    env.update(HOME=str(home), PATH=str(Path(python).parent) + os.pathsep + env.get('PATH', ''))
    return env


def run(argv, folder, python, check=True):
    done = subprocess.run(argv, cwd=folder, env=environment(python, folder), capture_output=True, text=True, timeout=300)
    if check: assert done.returncode == 0, '%s exited %d: %s' % (shlex.join(argv), done.returncode, done.stderr[-2000:])
    return done


def printed(stdout):
    """(text, argv) of each command the demo printed."""
    return [(line[len(INDENT):], shlex.split(line)) for line in stdout.splitlines() if line.startswith(INDENT)]


def as_written(commands):
    """The demo's printed lines as a page writes them: byte for byte, the third line's interpreter read as python."""
    return [text for text, _ in commands[:2]] + [shlex.join(['python', *argv[1:]]) for _, argv in commands[2:]]


def run_page(page, folder, python, place, verbatim=False):
    """Run every block of PAGE in FOLDER, in order; PLACE(path) puts the bundle where the demo block names it. The
    three-commands block runs as the demo printed it for this bundle, or VERBATIM (the F3 bundle's own lines).
    Returns (demo's printed commands, (block, results of the three commands), Python blocks' output, not-run reasons)."""
    found = checked(page.read_text(encoding='utf-8'))
    _, start, bundle = demo_line(found)
    place(folder / bundle)
    commands, three, said, skipped = None, None, [], []
    try:
        for block in found:
            if block.reason == INSTALL: skipped.append(block.reason); continue
            if block.reason == PRINTED:
                assert commands is not None, 'the three commands come after the demo starts'
                if verbatim:
                    assert block.lines == as_written(commands), 'the three-commands block differs from what the demo prints'
                    argvs = [shlex.split(line) for line in block.lines]
                else:
                    assert [shape(shlex.split(line)) for line in block.lines] == [shape(argv) for _, argv in commands]
                    argvs = [argv for _, argv in commands]
                three = (block, [run(argv, folder, python, check=False) for argv in argvs])
                if not verbatim: skipped.append(block.reason)
                continue
            if block.language == 'python':
                said.append(run([python, '-c', '\n'.join(block.lines)], folder, python).stdout); continue
            for line in block.lines:
                done = run(shlex.split(line), folder, python)
                if line == start: commands = printed(done.stdout)
    finally:
        run(['ophiolite', 'demo', 'stop'], folder, python, check=False)
    print('%s: not run: %s' % (page.name, ' | '.join(skipped)))
    return commands, three, said, skipped


def synthetic(path):
    reads = [Log(FIRST[0], FIRST[1], FIRST[2]), Log(SECOND[0], SECOND[1], SECOND[2]), typed('tops'), typed('trajectory'), typed('grid')]
    build = path.parent / 'build'; build.mkdir()
    os.replace(demo_bundle(build, reads), path)


def test_every_block_runs_against_the_demo_of_the_candidate_wheel(tmp_path):
    """Mutations: rename a command in a block → it exits non-zero; a constant print in the Python block → its line
    differs from the constants'; the fetch line swapped for a listing line → the block's shape differs from the
    printed one, and no curve file is saved."""
    python, which = wheel_python()
    print('commands run with %s: %s' % (which, python))
    folder = tmp_path / 'README'; folder.mkdir()
    commands, three, said, skipped = run_page(README, folder, python, synthetic)
    assert skipped == PERMITTED
    assert [r.returncode for r in three[1]] == [0, 0, 0], [r.stderr[-1000:] for r in three[1]]
    wells, fetch, derive = three[1]
    assert wells.stdout.splitlines()[:2] == ["Well('%s', unlocated)" % FIRST[1], "Well('%s', unlocated)" % SECOND[1]]
    saved = json.loads((folder / 'ophiolite-demo' / ('%s-GR' % FIRST[1]) / 'curve.json').read_text())
    assert (saved['axis'], saved['values']) == ([d for d, _ in FIRST[2]], [v for _, v in FIRST[2]])
    receipt = json.loads(derive.stdout)['receipt']
    assert [p['key'] for p in receipt['derived_from']] == [FIRST[0]] and receipt['asset_id'] and receipt['revision']  # one publication
    rows = FIRST[2]
    expected = '%d wells, the first %s; GR of the first log: %d samples, %s to %s' % (2, FIRST[1], len(rows), rows[0][0], rows[-1][0])
    assert [s.strip() for s in said] == [expected]
    assert not (folder / 'ophiolite-demo' / 'state.json').exists()  # the stop block ran


def test_the_f3_bundle_runs_every_block_verbatim(tmp_path):
    """The lane-host run (a READY requirement): every block verbatim, the three-commands block included, which must be
    the demo's printed lines byte for byte (its interpreter read as python). Without OPHIOLITE_F3_BLOCK it returns with a
    report line; it never skips, because the unit lane fails on skips. A set variable with a wrong digest fails."""
    bundle = os.environ.get('OPHIOLITE_F3_BLOCK')
    if not bundle:
        print('F3 run not requested: OPHIOLITE_F3_BLOCK is unset (the lane host sets it)')
        return
    from ophiolite import demo
    assert hashlib.sha256(Path(bundle).read_bytes()).hexdigest() == demo.BUNDLE_SHA256, 'OPHIOLITE_F3_BLOCK is not the F3-block bundle'
    record = os.environ.get('OPHIOLITE_F3_ORACLE')  # tools/demo-project/oracle.json of the monorepo, set with OPHIOLITE_F3_BLOCK
    assert record and Path(record).is_file(), 'set OPHIOLITE_F3_ORACLE to the F3-block bundle\'s oracle.json with OPHIOLITE_F3_BLOCK'
    python, which = wheel_python()
    print('F3 run with %s: %s' % (which, python))
    oracle = json.loads(Path(record).read_text())
    with zipfile.ZipFile(bundle) as archive:  # the first log's GR as stored in the bundle, read without the SDK: the first
        # LAS entry that carries GR, in catalogue (bundle) order, as the README's Python block picks it
        gr = [[f['path'] for f in a['files'] if f['path'].endswith('/curve-GR.json')]
              for a in json.loads(archive.read('manifest.json'))['assets'] if a.get('profile') == 'las2/1']
        [member] = next(paths for paths in gr if paths)
        curve = json.loads(archive.read(member))
    wells = sorted(oracle['wells'])

    def place(path):
        os.link(Path(bundle).resolve(), path)  # a second name, no bytes copied (open_bundle refuses a symbolic link); run
        # with --basetemp on the bundle's file system, in a 0700 folder outside every repository and the temporary folder

    folder = tmp_path / 'README'; folder.mkdir()
    commands, (block, results), said, skipped = run_page(README, folder, python, place, verbatim=True)
    assert skipped == [INSTALL]  # the three-commands block ran verbatim
    assert [r.returncode for r in results] == [0, 0, 0], [r.stderr[-1000:] for r in results]
    assert len([line for line in results[0].stdout.splitlines() if line.startswith('Well(')]) == len(wells)
    assert json.loads(results[2].stdout)['receipt']['asset_id']  # one publication
    expected = '%d wells, the first %s; GR of the first log: %d samples, %s to %s' % (
        len(wells), wells[0], len(curve['values']), float(curve['axis'][0]), float(curve['axis'][-1]))
    assert [s.strip() for s in said] == [expected]
    print('F3 run: every README block ran verbatim; the three commands equal the printed lines')


def test_the_readme_is_a_short_quick_start():
    """Mutations: a sixty-first line, or an epic number → this fails."""
    text = README.read_text(encoding='utf-8')
    assert len(text.splitlines()) <= 60
    checked(text)
    assert text.rstrip('\n').splitlines()[-1].endswith('(https://github.com/tuna-soup/ophiolite-sdk/blob/main/CONTRACTS.md).')
    assert all(t.startswith('https://') for t in re.findall(r'\]\(([^)]+)\)', text))  # PyPI renders it: absolute links only


def test_the_three_commands_have_the_shape_the_demo_prints():
    """Mutations: the fetch line swapped for a listing line, a command renamed, or a line dropped → the shapes differ
    from what the SDK's own demo would print."""
    from ophiolite import demo
    [block] = [b for b in checked(README.read_text(encoding='utf-8')) if b.reason == PRINTED]
    facts = {'well': 'any', 'asset': 'a', 'revision': 'r'}
    assert [shape(shlex.split(line)) for line in block.lines] == [shape(argv) for argv in demo.lines(Path(demo.FOLDER), facts)]


def test_the_page_rules_catch_each_mutation():
    """Each mutation of the README fails the inventory: an epic number, a block's language changed to text, a not-run
    marker added to the demo block, a marker without a reason, an unclosed fence."""
    import pytest
    text = README.read_text(encoding='utf-8')
    _, start, _ = demo_line(blocks(text))
    mutations = {
        'epic number': text.replace('## Install', '## Install (E164)', 1),
        'language': text.replace('```python', '```text', 1),
        'marker on the demo block': text.replace('```sh\n' + start, '<!-- not-run: no bundle here -->\n```sh\n' + start, 1),
        'empty reason': text.replace('<!-- not-run: ' + INSTALL, '<!-- not-run:  ', 1),
        'unclosed fence': text.rstrip('\n').rsplit('```', 1)[0],
        'fetch swapped': text,
    }
    fetch = next(line for line in text.splitlines() if line.startswith('ophiolite data fetch '))
    listing = next(line for line in text.splitlines() if line.startswith('ophiolite data wells list '))
    mutations['fetch swapped'] = text.replace(fetch, listing, 1)
    for name, mutated in mutations.items():
        assert mutated != text, name
        with pytest.raises(AssertionError):
            found = checked(mutated)
            if name == 'fetch swapped':
                from ophiolite import demo
                [block] = [b for b in found if b.reason == PRINTED]
                facts = {'well': 'any', 'asset': 'a', 'revision': 'r'}
                assert [shape(shlex.split(l)) for l in block.lines] == [shape(a) for a in demo.lines(Path(demo.FOLDER), facts)]
