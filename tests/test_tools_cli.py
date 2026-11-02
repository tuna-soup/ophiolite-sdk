"""E131 s1 C3: `ophiolite tools` is the group; `ophiolite procedures` runs the same commands. At a terminal the old
spelling first prints exactly one notice line on stderr, before the arguments are read (so `--help` and usage errors
have it too); piped, as scripts and the conformance kit run it, its output is byte-identical to before (R2-8). Help says
tools; the frozen help oracles are compared through HELP_WORDS (D4.3), re-wrapping only the lines argparse wraps.
Expected values are literals."""
import argparse
import contextlib
import io
import json
import os
import pty
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ophiolite
from ophiolite import Client, cli, procedures, tools

NOTICE = ('`ophiolite procedures` now runs as `ophiolite tools`; the old spelling is removed in a later release, announced '
          'one release ahead in the CHANGELOG.\n')
FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'
# D4.3: the help words, in this order, applied to a frozen help text (never to offline answers or JSON).
HELP_WORDS = [
    (re.compile(r'ophiolite procedures'), 'ophiolite tools'),
    (re.compile(r'Procedures'), 'Tools'),
    (re.compile(r'\bprocedures\b'), 'tools'),
    (re.compile(r'\bprocedure-made\b'), 'tool-made'),
    (re.compile(r'\bprocedure\b(?!\.json|\.py)'), 'tool'),
    (re.compile(r' \(E105b\): '), ': '),
]


def words(text):
    for pattern, replacement in HELP_WORDS:
        text = pattern.sub(replacement, text)
    return text


def unwrap(text):
    """Help with each wrapped entry joined to one line: a line indented more than four spaces continues the entry above
    it. Line order, blank lines and the indentation of option names and headings are kept as they are."""
    lines = []
    for line in text.split('\n'):
        if lines and lines[-1].strip() and len(line) - len(line.lstrip(' ')) > 4 and line.strip():
            lines[-1] = lines[-1].rstrip() + ' ' + line.strip()
        else:
            lines.append(line)
    return [line[:len(line) - len(line.lstrip(' '))] + ' '.join(line.split()) for line in lines]


def reworded(text):
    """A frozen help text as this head prints it: each entry joined to one line, then HELP_WORDS applied."""
    return [words(line) for line in unwrap(text)]


def call(*argv):
    """(exit code, stdout, stderr) of `ophiolite …` through `cli.main`."""
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli.main([str(a) for a in argv])
        except SystemExit as stop: code = stop.code or 0
    return code, out.getvalue(), err.getvalue()


def at_terminal(*argv):
    """(exit code, stdout, stderr) of `python -m ophiolite …` in its own process with stderr on a pseudo-terminal and
    stdout piped (R2-8: a person typing the command)."""
    leader, follower = pty.openpty()
    env = {**os.environ, 'COLUMNS': '100', 'PYTHONPATH': str(Path(ophiolite.__file__).resolve().parents[1])}
    try:
        done = subprocess.run([sys.executable, '-m', 'ophiolite', *map(str, argv)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=follower, env=env, timeout=120)
    finally:
        os.close(follower)
    chunks = []
    while True:
        try: chunk = os.read(leader, 65536)
        except OSError: break  # the terminal is closed once everything was read
        if not chunk: break
        chunks.append(chunk)
    os.close(leader)
    return done.returncode, done.stdout.decode(), b''.join(chunks).decode().replace('\r\n', '\n')


@pytest.fixture
def columns(monkeypatch):
    monkeypatch.setenv('COLUMNS', '100'); monkeypatch.setattr(sys, 'argv', ['ophiolite'])


def test_new_under_both_spellings_writes_the_same_start(tmp_path):
    a, b = tmp_path / 'a/demo', tmp_path / 'b/demo'
    made_a, made_b = call('tools', 'new', a, '--step', 'process'), call('procedures', 'new', b, '--step', 'process')
    assert made_a == (0, 'Created demo with procedure.json and procedure.py. Edit them, then run: ophiolite tools validate %s\n' % a, '')
    assert made_b == (0, 'Created demo with procedure.json and procedure.py. Edit them, then run: ophiolite procedures validate %s\n' % b, '')
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir()) == ['procedure.json', 'procedure.py']
    for name in ('procedure.json', 'procedure.py'):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    assert procedures.validate(a)['digest'] == procedures.validate(b)['digest']


def cases(tmp_path):
    bundle = tmp_path / 'depth-shift'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', bundle, ignore=shutil.ignore_patterns('__pycache__'))
    return ((['validate', bundle], 0), (['validate', bundle, '--json'], 0), (['--help'], 0), (['new'], 2),
            (['new', tmp_path / 'x', '--step', 'nowhere'], 2))


def test_at_a_terminal_the_notice_is_one_line_first_on_stderr_and_only_for_the_old_spelling(tmp_path):
    for argv, code in cases(tmp_path):
        new, old = at_terminal('tools', *argv), at_terminal('procedures', *argv)
        assert new[0] == old[0] == code, argv
        assert NOTICE not in new[2] and old[2] == NOTICE + new[2], argv
        assert old[1] == new[1], argv
        if code == 2: assert new[2].startswith('usage: ') and ' tools new: error: ' in new[2], new[2]  # `-m` names the program __main__.py
        if '--json' in argv: assert json.loads(old[1])['valid'] is True


def test_piped_the_old_spelling_answers_byte_for_byte_as_the_new(tmp_path, columns):
    for argv, code in cases(tmp_path):
        new, old = call('tools', *argv), call('procedures', *argv)
        assert new == old and new[0] == code and NOTICE.strip() not in old[1] + old[2], argv
    assert call('procedures', '--help')[1].startswith('usage: ophiolite tools [-h] [--json]\n')
    assert call('tools', 'new')[2].startswith('usage: ophiolite tools new ')


def test_the_old_spelling_is_left_out_of_the_command_list(columns):
    top = call('--help')[1]
    assert '{list,fetch,' in top and ',tools,' in top and 'procedures' not in top
    assert '    tools Write, check and run your own tools on this computer (offline; nothing is published)' in unwrap(top)


def test_tools_help_says_tools(columns):
    sub = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction))
    verbs = list(sub.choices['tools']._subparsers._group_actions[0].choices)
    assert verbs == ['new', 'validate', 'run', 'register', 'list', 'show', 'enable', 'withdraw', 'trust', 'publish', 'again']
    for argv in [['tools', '--help']] + [['tools', verb, '--help'] for verb in verbs]:
        code, text, err = call(*argv)
        assert (code, err) == (0, '') and text.startswith('usage: ophiolite tools'), argv
        assert re.findall(r'\bprocedures?\b(?!\.json|\.py)', text) == [], argv
        assert call('procedures', *argv[1:])[1] == text, argv


def test_help_words_change_only_the_named_words():
    assert words('Run a procedure-made result; procedure.json and procedure.py; ophiolite procedures list; Procedures '
                 'catalogue instead of a folder (E105b): the') == (
        'Run a tool-made result; procedure.json and procedure.py; ophiolite tools list; Tools catalogue instead of a '
        'folder: the')
    assert unwrap('  --kind KIND   What it\n                reads\n\noptions:') == ['  --kind KIND What it reads', '', 'options:']


def test_client_has_every_twin():
    for verb in tools.VERBS:
        assert getattr(Client, 'tool_' + verb) is getattr(tools.ToolClient, 'tool_' + verb), verb
        assert hasattr(Client, 'procedure_' + verb), verb
    assert issubclass(Client, tools.ToolClient) and not issubclass(procedures._AgentCatalogue, tools.ToolClient)
