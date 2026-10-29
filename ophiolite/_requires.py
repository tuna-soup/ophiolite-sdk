"""E112 s4: the Python distributions a procedure lists under `requires`, checked against the interpreter that runs it.

A strict subset of PEP 508: a name, then comma-separated specifiers (~=, ==, !=, <=, >=, <, >) of release versions;
== and != may end in .*. Extras, environment markers, URLs, === and pre-release specifiers are not supported and are
refused with the text. Installed versions are ordered by PEP 440 (epoch, release, dev < pre < final < post; a local
part is ignored), as pip judges an installed distribution. Nothing is installed: the answer names what is missing."""
import importlib.metadata
import re
import shlex
import sys

NAME = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?')
SPECIFIER = re.compile(r'\s*(~=|==|!=|<=|>=|<|>)\s*([0-9]+(?:\.[0-9]+)*)(\.\*)?\s*')
VERSION = re.compile(r'v?(?:(?P<epoch>[0-9]+)!)?(?P<release>[0-9]+(?:\.[0-9]+)*)'
                     r'(?:[-_.]?(?P<pre>a|b|c|rc|alpha|beta|pre|preview)[-_.]?(?P<pre_n>[0-9]+)?)?'
                     r'(?:-(?P<post_implicit>[0-9]+)|[-_.]?(?P<post>post|rev|r)[-_.]?(?P<post_n>[0-9]+)?)?'
                     r'(?:[-_.]?(?P<dev>dev)[-_.]?(?P<dev_n>[0-9]+)?)?(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?', re.I)
PHASE = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'c': 2, 'rc': 2, 'pre': 2, 'preview': 2}


class Malformed(ValueError):
    """A `requires` text outside the supported grammar; `extras` when only its [extras] are the reason."""

    def __init__(self, text, extras=False):
        super().__init__(text)
        self.text, self.extras = text, extras


def parse(text):
    """(name, [(operator, release, wildcard)]) of one `requires` text, or Malformed."""
    if '[' in text or ']' in text:
        raise Malformed(text, extras=bool(re.fullmatch(r'\s*' + NAME.pattern + r'\s*\[[^\]]*\].*', text)))
    head = NAME.match(text.strip())
    if head is None: raise Malformed(text)
    rest, specifiers = text.strip()[head.end():], []
    if rest.strip():
        for part in rest.split(','):
            found = SPECIFIER.fullmatch(part)
            if found is None: raise Malformed(text)
            operator, release, wildcard = found.group(1), tuple(int(n) for n in found.group(2).split('.')), bool(found.group(3))
            if wildcard and operator not in ('==', '!='): raise Malformed(text)
            if operator == '~=' and len(release) < 2: raise Malformed(text)
            specifiers.append((operator, release, wildcard))
    return head.group(0), specifiers


def version_key(text):
    """The PEP 440 order of an installed version's public part, or None when it does not parse."""
    found = VERSION.fullmatch(text.strip())
    if found is None: return None
    release = tuple(int(n) for n in found['release'].split('.'))
    while len(release) > 1 and release[-1] == 0: release = release[:-1]
    post = int(found['post_implicit']) if found['post_implicit'] else int(found['post_n'] or 0) if found['post'] else None
    dev = int(found['dev_n'] or 0) if found['dev'] else None
    pre = (PHASE[found['pre'].lower()], int(found['pre_n'] or 0)) if found['pre'] else None
    # a dev release of the final sorts before its pre-releases; a final sorts after them, a post after the final
    phase = pre if pre is not None else ((-1, 0) if dev is not None and post is None else (3, 0))
    return (int(found['epoch'] or 0), release, phase, -1 if post is None else post, (1, 0) if dev is None else (0, dev))


def _final(release):
    trimmed = release
    while len(trimmed) > 1 and trimmed[-1] == 0: trimmed = trimmed[:-1]
    return (0, trimmed, (3, 0), -1, (1, 0))


def _prefix(key, release):
    padded = key[1] + (0,) * max(0, len(release) - len(key[1]))
    return key[0] == 0 and padded[:len(release)] == release


def satisfies(key, operator, release, wildcard):
    """Whether the installed version (its version_key) meets one specifier."""
    spec = _final(release)
    if operator == '==': return _prefix(key, release) if wildcard else key == spec
    if operator == '!=': return not satisfies(key, '==', release, wildcard)
    if operator == '>=': return key >= spec
    if operator == '<=': return key <= spec
    if operator == '>': return key > spec and not (key[:3] == spec[:3] and key[3] >= 0)  # not a post-release of it
    if operator == '<': return key < spec and not (key[:2] == spec[:2])  # not a pre-release of it
    if operator == '~=': return key >= spec and _prefix(key, release[:-1])
    raise ValueError(operator)


def installed(name):
    """The installed version of distribution `name` in this interpreter (PackageNotFoundError when absent)."""
    return importlib.metadata.version(name)


def unmet(texts, version=None):
    """The requirements this interpreter does not meet, in order: [{'requirement', 'name', 'found', 'readable'}].
    Raises Malformed (with `.index`) for the first text outside the grammar."""
    version = version or installed
    parsed = []
    for index, text in enumerate(texts):
        try: parsed.append((text, *parse(text)))
        except Malformed as error:
            error.index = index
            raise
    missing = []
    for text, name, specifiers in parsed:
        try: found = version(name)
        except importlib.metadata.PackageNotFoundError: found = None
        key = None if found is None else version_key(found)
        if found is None or key is None or not all(satisfies(key, *s) for s in specifiers):
            missing.append({'requirement': text.strip(), 'name': name, 'found': found, 'readable': found is None or key is not None})
    return missing


def install_line(missing):
    """The command that installs them into this interpreter."""
    return '%s -m pip install %s' % (shlex.quote(sys.executable), ' '.join(shlex.quote(m['requirement']) for m in missing))
