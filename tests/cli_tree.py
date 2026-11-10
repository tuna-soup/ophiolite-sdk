"""E163 s1: the complete command tree of `ophiolite.cli.parser()`, as data (design 1 of the strategy).

  python tests/cli_tree.py --write tests/fixtures/cli-0.3-baseline.json   run once, at the parent of the regrouping

For every spelling (the 62 top-level ones and every nested verb): its aliases and, per argument, dest, option strings,
default, type, choices, required, nargs, action class and mutually exclusive group. For every leaf: one sample argv
built from those properties and the namespace it parsed to, and, for a leaf that takes `--configuration`, what that
argv sent to and answered from the SDK's fixture server (`served`), so the regrouped tree can be compared with
literals recorded before it existed. `procedures`, which shares its verbs' names with `tools`, is walked like any spelling.
"""
import argparse
import base64
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

GROUP = {argparse._SubParsersAction}
SKIP = (argparse._HelpAction, argparse._VersionAction)


def subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def kind(value):
    return None if value is None else getattr(value, '__name__', type(value).__name__)


def required(action):
    """A positional with nargs='*' takes zero values either way; Python 3.12.3 marks it required and later 3.12
    releases (the hosted runners') do not, so it is recorded as not required."""
    return action.required and not (not action.option_strings and action.nargs == '*')


def arguments(parser):
    groups = {id(a): i for i, g in enumerate(parser._mutually_exclusive_groups) for a in g._group_actions}
    out = []
    for a in parser._actions:
        if isinstance(a, SKIP) or isinstance(a, argparse._SubParsersAction): continue
        out.append({'dest': a.dest, 'options': list(a.option_strings), 'default': repr(a.default), 'type': kind(a.type),
                    'choices': None if a.choices is None else [str(c) for c in a.choices], 'required': required(a),
                    'nargs': None if a.nargs is None else str(a.nargs), 'action': type(a).__name__, 'exclusive': groups.get(id(a))})
    return out


def walk(parser, path=()):
    """(spelling, parser, aliases) for every spelling under PARSER, depth first, each parser object once per path."""
    sub = subparsers(parser)
    if sub is None: return
    names = {}
    for name, child in sub.choices.items(): names.setdefault(id(child), []).append(name)
    for name, child in sub.choices.items():
        if names[id(child)][0] != name: continue
        yield ' '.join(path + (name,)), child, names[id(child)][1:]
        yield from walk(child, path + (name,))


def value(action):
    if action.choices is not None: return str(next(iter(action.choices)))
    if action.type in (int, float): return '1'
    return 'x'


def sample(parser):
    """The shortest argv this leaf parser accepts: every required argument, one value each (one option per required
    exclusive group)."""
    argv, taken = [], set()
    for g in parser._mutually_exclusive_groups:
        if g.required:
            a = g._group_actions[0]; taken.add(id(a))
            argv += [a.option_strings[0]] + ([] if a.nargs == 0 else [value(a)])
    for a in parser._actions:
        if isinstance(a, SKIP) or id(a) in taken or not a.required: continue
        if a.option_strings: argv += [a.option_strings[0]] + ([] if a.nargs == 0 else [value(a)])
    for a in parser._actions:
        if not a.option_strings and not isinstance(a, argparse._SubParsersAction) and a.nargs not in ('?', '*'):
            argv += [value(a)] * (a.nargs if isinstance(a.nargs, int) else 1)
    return argv


def parsed(top, argv):
    try:
        return {k: json.loads(json.dumps(v, default=str)) for k, v in sorted(vars(top.parse_args(argv)).items())}
    except SystemExit as stopped:
        return {'exit': stopped.code}


ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b(?:[a-z]+-)?[0-9a-f]{32}\b')
# `doctor` names the interpreter and the local contracts release, which move with the host and with main
VERSION = re.compile(r'^(Python|Local contracts): \S+$', re.M)


def served(argv):
    """Run `cli.main(ARGV + --configuration)` in a fresh folder against a fresh `fixture_server` (E-12): every request
    (method, path, body), the outcome (exit code, or the class of what it raised) and stdout, with the folder, the
    server address and generated command ids replaced by placeholders."""
    from ophiolite import Credential, cli
    from ophiolite.testing import fixture_server
    keep = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith('OPHIOLITE_')}
    home, cwd, credential = os.environ.get('HOME'), os.getcwd(), Credential.__dict__['from_file']
    Credential.from_file = staticmethod(lambda path: Credential.bearer('oph_api_alice'))
    try:
        with tempfile.TemporaryDirectory() as folder, fixture_server() as server:
            configuration = Path(folder) / 'configuration.json'
            configuration.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
            os.chdir(folder); os.environ['HOME'] = folder
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, 'stdin', io.StringIO()):
                try: outcome = cli.main(list(argv) + ['--configuration', str(configuration)]); outcome = outcome if isinstance(outcome, int) else 0
                except SystemExit as stopped: outcome = stopped.code
                except Exception as raised: outcome = type(raised).__name__
            said = lambda text: ID.sub('<id>', text.replace(server.url, '<server>').replace(folder, '<folder>'))
            return {'outcome': outcome, 'stdout': VERSION.sub(r'\1: <version>', said(out.getvalue())),
                    'requests': [[r['method'], said(r['path']), said(base64.b64decode(r['body_base64']).decode('utf-8', 'replace'))]
                                 for r in server.requests]}
    finally:
        os.chdir(cwd); Credential.from_file = credential; os.environ.update(keep)
        if home is not None: os.environ['HOME'] = home


def configured(parser):
    return any('--configuration' in a.option_strings for a in parser._actions)


def baseline(top, commit):
    spellings = {}
    for spelling, parser, aliases in walk(top):
        row = {'aliases': aliases, 'arguments': arguments(parser)}
        if subparsers(parser) is None:
            row['argv'] = sample(parser)
            row['namespace'] = parsed(top, spelling.split() + row['argv'])
            if configured(parser): row['served'] = served(spelling.split() + row['argv'])
        spellings[spelling] = row
    return {'schema': 'ophiolite.cli-baseline/1', 'frozen_at': commit, 'spellings': spellings}


def old_lines(top):
    """{old top-level spelling: its one line}, read from the group that lists it as a verb (design 6: the top list of
    spellings is retired; a group's verb line is its successor)."""
    from ophiolite import cli_groups
    lines = {}
    for group, _, verbs in cli_groups.GROUPS:
        listed = {c.dest: c.help for c in subparsers(subparsers(top).choices[group])._choices_actions}
        lines.update((verb, listed[verb]) for verb in verbs)
    return lines


def spelled(top, spelling):
    """The parser of SPELLING, its help and usage named by SPELLING (an old spelling's text before the groups: the
    usage prefix is the one difference E163 s1 allows)."""
    from ophiolite import cli_groups
    parser = top
    for word in spelling.split(): parser = subparsers(parser).choices[word]
    cli_groups._rename(parser, '%s %s' % (top.prog, spelling))
    return parser


WORDS = (  # E163 s1b E-2: the helps that said procedure and say tool, literally (the strategy's word table)
    ('The read procedure version to run', 'The read tool version to run'), ('A setting of the read procedure;', 'A setting of the read tool;'),
    ("The procedure's name in the project's catalogue", "The tool's name in the project's catalogue"),
    ("(default: the procedure's name for it)", "(default: the tool's name for it)"),
    ("The send procedure's name in the project's catalogue", "The send tool's name in the project's catalogue"),
    ('This version of the procedure (your', 'This version of the tool (your'), ('Trust the procedure version without', 'Trust the tool version without'),
    ('A setting of the procedure; once per setting', 'A setting of the tool; once per setting'),
    ('The send procedure that delivers it', 'The send tool that delivers it'), ('The residual procedure, by its name', 'The residual tool, by its name'),
    ('The procedure version (default:', 'The tool version (default:'), ('Run procedure versions you have not trusted', 'Run tool versions you have not trusted'))


def regrouped(text):
    """TEXT recorded before E163 s1b as the SDK says it now: every `ophiolite <old>` it names becomes
    `ophiolite <group> <old>` (`procedures` becomes `tools`), and the WORDS table applies. A usage line's prefix stays
    old: `spelled` renders it so. Anything else the SDK rewords still differs. Rendered help rewraps when its words
    change, so a help is compared `flat` on both sides: `regrouped(flat(recorded)) == flat(rendered)`."""
    from ophiolite import cli_groups
    old = re.compile(r'(?<![./\w-])(?<!usage: )ophiolite (%s)\b(?![-\w])' % '|'.join(map(re.escape, sorted(cli_groups.ALIASES, key=len, reverse=True))))
    def grouped(m):
        if m.group(1) == 'import' and m.string[max(0, m.start() - 5):m.start()] == 'from ': return m.group(0)
        return 'ophiolite tools' if m.group(1) == 'procedures' else 'ophiolite %s %s' % (cli_groups.ALIASES[m.group(1)], m.group(1))
    text = old.sub(grouped, text)
    for before, after in WORDS: text = text.replace(before, after)
    return text


def flat(text):
    """TEXT on one line, its whitespace collapsed."""
    return ' '.join(text.split())


def groups(top, columns):
    """The grouped help as `cli-0.3-help.json` freezes it: the top help, and per group its rendered help and verb lines."""
    from ophiolite import cli_groups
    record = {'columns': columns, 'top': top.format_help(), 'groups': {}}
    for group in cli_groups.NAMES:
        own = subparsers(top).choices[group]
        record['groups'][group] = {'help': own.format_help(), 'verbs': {c.dest: c.help for c in subparsers(own)._choices_actions}}
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    given = parser.add_mutually_exclusive_group(required=True)
    given.add_argument('--write', type=Path, help='the baseline, from the tree before the groups')
    given.add_argument('--write-help', type=Path, help='cli-0.3-help.json, from the grouped tree, at 100 columns')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ['COLUMNS'] = '100'; sys.argv[0] = 'ophiolite'
    from ophiolite import cli
    if args.write_help:
        args.write_help.write_text(json.dumps(groups(cli.parser(), 100), indent=1) + '\n')
        print('cli_tree: wrote %s' % args.write_help)
        return
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    with contextlib.redirect_stderr(io.StringIO()):  # a sample argv argparse refuses records its exit code, not its usage text
        record = baseline(cli.parser(), commit)
    args.write.write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')
    leaves = [r for r in record['spellings'].values() if 'argv' in r]
    asked = [r['served'] for r in leaves if r.get('served', {}).get('requests')]
    print('cli_tree: %d spellings, %d leaves, %d samples refused, %d sent requests (%d answered 0)' % (
        len(record['spellings']), len(leaves), sum('exit' in r['namespace'] for r in leaves), len(asked),
        sum(s['outcome'] == 0 for s in asked)))


if __name__ == '__main__':
    main()
