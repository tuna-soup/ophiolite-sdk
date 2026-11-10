"""E163 s1 C2: the command line in groups, the old spellings as hidden aliases, `ophiolite --version`.

The grouped tree is compared with `fixtures/cli-0.3-baseline.json`, recorded from the parser before the groups existed
(tests/cli_tree.py), never with the alias: an alias and a group verb that both reached the wrong command would agree.
"""
import contextlib
import io
import json
import os
import pty
import re
import subprocess
import sys
from pathlib import Path

import pytest

import ophiolite
from ophiolite import cli, cli_groups
from ophiolite.testing import fixture_server
from cli_tree import arguments, served, walk

FIXTURES = Path(__file__).parent / 'fixtures'
SDK = str(Path(ophiolite.__file__).resolve().parents[1])  # a subprocess runs this checkout's package, not an installed one
BASELINE = json.loads((FIXTURES / 'cli-0.3-baseline.json').read_text())
HELP = json.loads((FIXTURES / 'cli-0.3-help.json').read_text())
GROUP_DESTS = {'group_verb', 'procedure_action', 'spelling'}  # what a group adds to the namespace of its verb
EPIC = re.compile(r'\bE\d+[a-z]?\d*\b')


@pytest.fixture(autouse=True)
def columns(monkeypatch):
    monkeypatch.setenv('COLUMNS', str(HELP['columns'])); monkeypatch.setattr(sys, 'argv', ['ophiolite'])


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: code = cli.main([str(a) for a in argv])
        except SystemExit as stopped: code = stopped.code
    return code, out.getvalue(), err.getvalue()


def parsed(argv):
    with contextlib.redirect_stderr(io.StringIO()):
        try: return {k: json.loads(json.dumps(v, default=str)) for k, v in sorted(vars(cli.parser().parse_args(argv)).items())}
        except SystemExit as stopped: return {'exit': stopped.code}


def grouped(spelling):
    first, *rest = spelling.split()
    group = cli_groups.ALIASES.get(first, first)
    return ([group] if group != first and first != 'procedures' else []) + [first] + rest


def test_the_top_help_is_one_screen_of_groups():
    for width in (80, 100):
        os.environ['COLUMNS'] = str(width)
        code, text, err = call('--help')
        assert (code, err) == (0, '') and len(text.splitlines()) <= 15
        assert text == HELP['top']
        listed = [line.split()[0] for line in text.split('Groups:\n', 1)[1].splitlines() if line.startswith('  ')]
        assert listed == list(cli_groups.NAMES) == list(HELP['groups'])
        assert '{' not in text  # no brace list of spellings, hidden or not


def test_an_unknown_word_names_the_groups_only():
    code, out, err = call('bogus')
    assert code == 2 and out == ''
    assert err.splitlines()[-1] == "ophiolite: error: argument <group>: invalid choice: 'bogus' (choose from %s)" % ', '.join(cli_groups.NAMES)


def test_each_group_lists_exactly_its_verbs_with_their_lines():
    for group, row in HELP['groups'].items():
        code, text, err = call(group, '--help')
        assert (code, err) == (0, ''), group
        # the characters in order, not the columns: Python 3.12.3 and later 3.12 releases indent and wrap a group's
        # verb list differently (a later one breaks "use-again" after its hyphen)
        assert ''.join(text.split()) == ''.join(row['help'].split()), group
        sub = cli_groups._subparsers(cli_groups._subparsers(cli.parser()).choices[group])
        assert {c.dest: c.help for c in sub._choices_actions} == row['verbs'], group


def test_every_baseline_spelling_keeps_its_arguments_under_both_spellings():
    now = {spelling: parser for spelling, parser, _ in walk(cli.parser())}
    for spelling, row in BASELINE['spellings'].items():
        assert arguments(now[spelling]) == row['arguments'], spelling
        assert now[' '.join(grouped(spelling))] is now[spelling], spelling


def test_every_leaf_parses_to_the_namespace_recorded_before_the_groups():
    leaves = {s: r for s, r in BASELINE['spellings'].items() if 'argv' in r}
    assert len(leaves) == 103
    for spelling, row in leaves.items():
        assert parsed(spelling.split() + row['argv']) == row['namespace'], spelling
        group = parsed(grouped(spelling) + row['argv'])
        assert {k: v for k, v in group.items() if k not in GROUP_DESTS or k in row['namespace']} == row['namespace'], spelling


def test_every_leaf_that_reaches_a_server_sends_and_answers_what_it_did_before_the_groups():
    """Each configured leaf, in either spelling, against a fresh fixture server: the requests (method, path, body),
    outcome and stdout recorded at the parent. The fixture serves the pilot operations only, so most sample argvs
    end in a refusal; those are compared the same way and counted apart."""
    rows = {s: r['served'] for s, r in BASELINE['spellings'].items() if 'served' in r}
    asked = {s: r for s, r in rows.items() if r['requests']}
    assert (len(rows), len(asked), sum(r['outcome'] == 0 for r in asked.values())) == (87, 58, 0)
    from cli_tree import regrouped  # E163 s1b: what a leaf prints names the grouped spelling; the record stays as recorded
    for spelling, row in rows.items():
        argv = BASELINE['spellings'][spelling]['argv']
        row = {**row, 'stdout': regrouped(row['stdout'])}
        assert served(spelling.split() + argv) == row, spelling
        assert served(grouped(spelling) + argv) == row, spelling


def test_a_published_result_runs_the_same_under_either_spelling(tmp_path, monkeypatch):
    """The served successes (E-12): prepare, publish and recover against one fixture server, old and grouped."""
    monkeypatch.setattr(ophiolite.Credential, 'from_file', lambda path: ophiolite.Credential.bearer('oph_api_alice'))
    seen = []
    for words in (('prepare', 'publish', 'recover'), (('results', 'prepare'), ('results', 'publish'), ('results', 'recover'))):
        words = [w if isinstance(w, tuple) else (w,) for w in words]
        with fixture_server() as server:
            folder = tmp_path / str(len(seen)); folder.mkdir(); work = folder / 'work'
            configuration = folder / 'configuration.json'
            configuration.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
            (folder / 'source.py').write_text('raise AssertionError("prepare executed code")\n'); (folder / 'parameters.json').write_text('{}')
            common = ['--configuration', str(configuration), '--work', str(work)]
            said = [call(*words[0], *common, '--asset', 'synthetic', '--revision', 'revision', '--curve', 'GR', '--name', 'CLI',
                         '--script', str(folder / 'source.py'), '--parameters', str(folder / 'parameters.json'))]
            (work / 'curves.json').write_text(json.dumps([{'mnemonic': 'NEW', 'unit': 'gAPI', 'description': 'Original synthetic',
                                                           'values': [0, None, 10, 20, 30]}], indent=2)); (work / 'curves.json').chmod(0o600)
            said += [call(*words[1], *common), call(*words[2], *common)]
            seen.append(([(type(s[0]).__name__, re.sub(r'\b[0-9a-f]{64}\b', '<id>', s[1])) for s in said], [r['path'].rsplit('/', 1)[-1] for r in server.requests], dict(server.handler.mutations),
                         (work / 'result.las').read_bytes()))
    assert seen[0] == seen[1]
    assert seen[0][0] == [('Run', 'Exact input ready. No calculation or publication performed. Run: <id>\n'),
                          ('Receipt', 'Committed derived asset: <id>\nRevision: <id>\n'
                                      'Publication does not change sharing. Manage recipients explicitly in Workspace.\n'),
                          ('NoneType', '')]
    assert seen[0][1:3] == (['configure', 'start', 'original', 'read', 'publish', 'download'], {'configure': 1, 'start': 1, 'publish': 1})


def test_help_and_usage_errors_name_the_grouped_spelling_under_either():
    for argv in (['wells', '--help'], ['data', 'wells', '--help']):
        assert call(*argv)[1].startswith('usage: ophiolite data wells [-h]'), argv
    for argv in (['checks', 'publishers', 'add'], ['tools', 'checks', 'publishers', 'add']):
        code, out, err = call(*argv)
        assert code == 2 and 'ophiolite tools checks publishers add: error: ' in err, argv


def at_terminal(*argv):
    """Run the CLI with stderr on a pseudo-terminal: (exit code, stdout, stderr)."""
    leader, follower = pty.openpty()
    done = subprocess.run([sys.executable, '-m', 'ophiolite', *argv], stdout=subprocess.PIPE, stderr=follower, text=True, timeout=120,
                          env=dict(os.environ, COLUMNS='100', PYTHONPATH=SDK))
    os.close(follower)
    said = b''
    with contextlib.suppress(OSError):
        while chunk := os.read(leader, 65536): said += chunk
    os.close(leader)
    return done.returncode, done.stdout, said.decode().replace('\r\n', '\n')


def test_at_a_terminal_an_old_spelling_says_its_new_one_once_first_on_stderr():
    old, new = at_terminal('targets'), at_terminal('exchange', 'targets')
    line = 'ophiolite targets is now ophiolite exchange targets; the old spelling stops working in the next release.\n'
    assert old[0] == new[0] == 0 and old[1] == new[1] and old[2] == line + new[2]
    assert at_terminal('skills', 'path')[2].count('stops working') == 1


def test_piped_an_old_spelling_answers_byte_for_byte_as_the_grouped_one():
    for old, new in ((['targets'], ['exchange', 'targets']), (['targets', '--json'], ['exchange', 'targets', '--json']),
                     (['skills', 'path'], ['tools', 'skills', 'path']), (['wells'], ['data', 'wells'])):
        assert call(*old) == call(*new), old


def test_version_prints_the_release_without_configuration(tmp_path):
    done = subprocess.run([sys.executable, '-m', 'ophiolite', '--version'], capture_output=True, text=True, cwd=tmp_path,
                          env=dict(os.environ, HOME=str(tmp_path), PYTHONPATH=SDK), timeout=120)
    assert (done.returncode, done.stdout, done.stderr) == (0, ophiolite.__version__ + '\n', '')


def test_the_lines_say_tool_and_name_no_epic():
    texts = [HELP['top']] + [row['help'] for row in HELP['groups'].values()]
    texts += [line for row in HELP['groups'].values() for line in row['verbs'].values()]
    assert [t for t in texts if re.search(r'\bprocedures?\b', t) or EPIC.search(t)] == []
