"""E163 s1: the command line in groups (D112, R-F4).

`regroup(parser)` takes the flat tree `cli.parser()` builds and adds the groups of `GROUPS` on top of it. A group verb is
the old command's own parser object, so `ophiolite data wells` and `ophiolite wells` cannot differ in arguments or in
what they run; every old parser that names no `command` default is given its own spelling, which is what `cli.main`
dispatches on. The old spellings stay in the parser as hidden aliases for one release; `notice` says the new spelling
once, at a terminal only (E131 R2-8: a script sees nothing new). Help and usage errors name the grouped spelling.
"""
import argparse

# (group, its one line, its verbs: the old top-level spellings, in the order its help lists them). `tools` and
# `starter` are old commands too: their own verbs stay, the extra ones listed here join them. `demo` (E162 slice 1) is a
# group of its own: `ophiolite demo` and `ophiolite demo stop`.
GROUPS = (
    ('account', 'Sign in, check this computer, and who can see what',
     ('login', 'logout', 'status', 'doctor', 'projects', 'orgs', 'teams', 'access-history', 'ai-use', 'share', 'audience', 'rights')),
    ('data', 'Read what you may see: curves, wells, lists and exact revisions',
     ('curves', 'wells', 'list', 'fetch', 'read-data', 'entities', 'changes', 'check', 'get', 'find', 'kinds', 'surveys', 'survey',
      'holders')),  # find: E145 s3; kinds: E168 s1; surveys: E142 s1; holders: E171 s1
    ('exchange', 'Bring files in and take bundles out',
     ('import', 'upload', 'export', 'bundle', 'send', 'made-for', 'deliver', 'intake', 'source', 'sources', 'repositories', 'well-imports',
      'sample', 'new-data', 'templates', 'template', 'targets', 'layouts', 'table-kinds', 'org-connections')),  # table-kinds: E203 s1
    ('results', 'Make, publish and follow results',
     ('prepare', 'run', 'publish', 'correct', 'publish-derived', 'remake', 'recover', 'withdraw', 'verdicts', 'outcomes', 'chains',
      'chain-runs', 'figures', 'story', 'what-changed', 'dependents', 'affected', 'trajectories', 'try')),  # try: E150 s1b; affected: E177 s1; chains, chain-runs: E178 s2c; figures: E191 s1
    ('tools', 'Write, check and run your own tools', ('init', 'skills', 'checks', 'rules', 'residuals', 'recipes')),
    ('starter', 'Starter packs of one catalogue record', ()),
    ('demo', 'A demo project on this computer, with three commands to try', ()),
)
# three commands that run as printed (D-4); E162 slice 1 puts `ophiolite demo` first (with --bundle until the bundle is
# published) in place of `data list`, so the top help stays one screen of 15 lines
START = (('demo', '--bundle PATH', 'A demo project on this computer, with three commands to try'),
         ('account', 'login', 'Approve this project in your browser'),
         ('data', 'wells list', 'The wells you may read, located'))
NAMES = tuple(g for g, _, _ in GROUPS)
ALIASES = {old: group for group, _, verbs in GROUPS for old in verbs}
ALIASES['procedures'] = 'tools'  # E131's spelling of the tools group; cli.main says its own notice
_SAID = []


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _rename(parser, prog):
    """PROG for PARSER and, recursively, every verb under it: argparse fixes a child's prog when it is created."""
    parser.prog = prog
    sub = _subparsers(parser)
    if sub is None: return
    sub._prog_prefix = prog
    for name, child in sub.choices.items():
        _rename(child, '%s %s' % (prog, name))


def _help(parser):
    lines = ['usage: %s [-h] [--version] <group> ...' % parser.prog, '', 'Start here:']
    width = max(len('%s %s %s' % (parser.prog, g, v)) for g, v, _ in START) + 2
    lines += ['  %-*s%s' % (width, '%s %s %s' % (parser.prog, g, v), line) for g, v, line in START]
    lines.append('Groups:')
    lines += ['  %-10s%s' % (g, line) for g, line, _ in GROUPS]
    lines.append("Run '%s <group> --help' for its commands; '%s --version' for the release." % (parser.prog, parser.prog))
    return '\n'.join(lines) + '\n'


def regroup(parser):
    top = _subparsers(parser)
    flat = dict(top.choices)
    helps = {c.dest: c.help for c in top._choices_actions}
    for name, child in flat.items():
        if child.get_default('command') is None: child.set_defaults(command=name)
    shown = []
    for group, line, verbs in GROUPS:
        if group in flat:
            own = flat[group]; sub = _subparsers(own)
        else:
            own = argparse._SubParsersAction.add_parser(top, group, help=line, description=line)
            sub = own.add_subparsers(dest='group_verb', required=True, metavar='<command>')
        # `procedures` is E131's spelling of the whole tools group, so it takes the group's new verbs too (same help)
        for into in [sub] + ([_subparsers(flat['procedures'])] if group == 'tools' else []):
            for verb in verbs:
                into._name_parser_map[verb] = flat[verb]
                into._choices_actions.append(into._ChoicesPseudoAction(verb, (), helps.get(verb)))
        _rename(own, '%s %s' % (parser.prog, group))
        shown.append(sub._ChoicesPseudoAction(group, (), line))
    top._choices_actions[:] = shown
    top.metavar = '<group>'
    parser.format_help = lambda: _help(parser)
    parser.format_usage = lambda: 'usage: %s [-h] [--version] <group> ...\n' % parser.prog
    error = parser.error

    def refused(message):  # the choice list of an unknown first word names the groups, never the hidden aliases
        if message.startswith('argument <group>: invalid choice:'):
            message = '%s (choose from %s)' % (message.split(' (choose from', 1)[0], ', '.join(NAMES))
        error(message)
    parser.error = refused
    return parser


def notice(words, stream):
    """At a terminal, once per process: the new spelling of an old one (never for `procedures`, whose E131 notice
    cli.main prints, nor for a group)."""
    first = next((w for w in words if not w.startswith('-')), None)
    if first in ALIASES and first not in NAMES and first != 'procedures' and not _SAID and stream.isatty():
        _SAID.append(first)
        print('ophiolite %s is now ophiolite %s %s; the old spelling stops working in the next release.'
              % (first, ALIASES[first], first), file=stream)
