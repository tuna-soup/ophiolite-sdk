"""E163 s1b: every word the SDK ships names a command by its grouped spelling (design 1 of the strategy).

A message, help line or docstring that says `ophiolite login` sends a reader to the spelling slice 2 removes, and at a
terminal it prints the old spelling's notice. The scan reads every string literal of the package (docstrings and the
parts of f-strings included); the alias table in `cli_groups.py` and the `procedures` notice in `cli.py` name the old
spellings on purpose.
"""
import ast
import re
from pathlib import Path

from ophiolite import cli_groups

PACKAGE = Path(cli_groups.__file__).parent
SDK = Path(__file__).resolve().parents[1]
OLD = re.compile(r'(?<![./\w-])ophiolite (%s)\b(?![-\w])' % '|'.join(map(re.escape, sorted(cli_groups.ALIASES, key=len, reverse=True))))
WAITING = ('contracts',)  # the connector copies move in slice 2


def old_spellings(text):
    """The old spellings TEXT names; `from ophiolite import x` is Python, not the `import` command."""
    return [m.group(0) for m in OLD.finditer(text) if not (m.group(1) == 'import' and text[max(0, m.start() - 5):m.start()] == 'from ')]


def literals(path):
    """(line, text) of every string literal in PATH but the `NOTICE` of cli.py."""
    tree = ast.parse(path.read_text())
    notice = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and [getattr(t, 'id', None) for t in n.targets] == ['NOTICE']}
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in notice]


def modules():
    return sorted(p for p in PACKAGE.rglob('*.py') if p.name != 'cli_groups.py' and not set(p.relative_to(PACKAGE).parts) & set(WAITING))


def texts():
    """The packaged text a person or an agent copies (skills, template READMEs and tests, schemas, notebooks), and the
    SDK's README and AGENTS.md: every file of the package that is not Python and reads as UTF-8."""
    found = [SDK / 'README.md', SDK / 'AGENTS.md']  # the checkout's: an installed package has neither beside it
    for p in sorted(PACKAGE.rglob('*')):
        if p.is_file() and p.suffix not in ('.py', '.pyc') and not set(p.relative_to(PACKAGE).parts) & set(WAITING):
            try: p.read_text(encoding='utf-8')
            except UnicodeDecodeError: continue
            found.append(p)
    return found


def test_the_package_names_every_command_by_its_group():
    found = ['%s:%d %s' % (p.relative_to(PACKAGE), line, old) for p in modules() for line, text in literals(p) for old in old_spellings(text)]
    assert found == []


def test_the_packaged_text_names_every_command_by_its_group():
    found = ['%s:%d %s' % (p.relative_to(PACKAGE.parent), n, old) for p in texts()
             for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) for old in old_spellings(line)]
    assert found == []
    names = {p.relative_to(PACKAGE).as_posix() for p in texts()[2:]}
    assert {'skills/authenticate/SKILL.md', 'templates/notebook/read-and-plot.ipynb', 'templates/map-application/tests/smoke.mjs',
            'schemas/procedure-template-pairs-v1.schema.json'} <= names


def test_the_scan_reads_the_command_line_and_tells_old_from_grouped():
    assert PACKAGE / 'cli.py' in modules() and len(literals(PACKAGE / 'cli.py')) > 1000
    notice = next(n.value.value for n in ast.walk(ast.parse((PACKAGE / 'cli.py').read_text()))
                  if isinstance(n, ast.Assign) and [getattr(t, 'id', None) for t in n.targets] == ['NOTICE'])
    assert old_spellings(notice) == ['ophiolite procedures']  # the one literal the scan leaves out names an old spelling
    assert old_spellings('Run ophiolite login --key again; ophiolite well-imports resume 7') == ['ophiolite login', 'ophiolite well-imports']
    assert old_spellings('Run ophiolite account login; ophiolite exchange well-imports resume 7; from ophiolite import tool') == []
    assert old_spellings('Give the run id: ophiolite import resume 7') == ['ophiolite import']
