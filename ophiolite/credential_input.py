"""E51a: one reader for a credential a person supplies (an argument, OPHIOLITE_ACCESS_KEY, --key-file, --key-stdin).

A terminal, a file or a hand selection adds a line break, spaces or a leading "Bearer " to a key. The reader removes
those and says what it removed, never the value, so the person knows another application's field (QGIS) still needs
the corrected value. It refuses only an empty value, a space or line break inside it, or a control character; it never
refuses a credential for its prefix (a provider or automation credential passes through unchanged). The saved-store
loader keeps its own rule and does not use this reader. The gateway stays strict.
"""
import re

from .errors import Refused

MAX_BYTES = 4096
SOURCES = {'argument': 'the key you gave', 'environment': 'OPHIOLITE_ACCESS_KEY', 'file': 'the key file', 'stdin': 'standard input'}
NOTES = {'line-break': 'A line break', 'surrounding-space': 'Space around the key', 'bearer-prefix': 'A leading "Bearer "'}
BEARER = re.compile(r'^bearer[ \t]+', re.IGNORECASE)


def read_credential(value, *, source):
    """(credential, notes): the value with a surrounding line break, spaces and one leading "Bearer " removed, and the
    names of what was removed (a tuple of 'line-break', 'surrounding-space', 'bearer-prefix'). Refused otherwise."""
    where = SOURCES.get(source, 'the credential')
    if isinstance(value, bytes):
        try: value = value.decode('utf-8')
        except UnicodeDecodeError: raise Refused('The credential in %s is not text.' % where) from None
    if not isinstance(value, str): raise Refused('No credential in %s.' % where)
    if len(value.encode('utf-8')) > MAX_BYTES: raise Refused('The credential in %s is longer than 4 KiB; that is not a key.' % where)
    core = value.strip()
    edges = value[:len(value) - len(value.lstrip())] + value[len(value.rstrip()):]
    notes = []
    if '\n' in edges or '\r' in edges: notes.append('line-break')
    if any(c not in '\r\n' for c in edges): notes.append('surrounding-space')
    prefix = BEARER.match(core)
    if prefix:
        core = core[prefix.end():]; notes.append('bearer-prefix')
    if not core: raise Refused('The credential in %s is empty.' % where)
    if any(c.isspace() for c in core):
        raise Refused('The credential in %s has a space or line break inside it; copy it again with its Copy button.' % where)
    if any(ord(c) < 32 or ord(c) == 127 for c in core):
        raise Refused('The credential in %s contains a control character; copy it again with its Copy button.' % where)
    return core, tuple(notes)


def notice(notes):
    """The sentence the command line prints (to stderr) when the reader removed something; None when nothing was."""
    if not notes: return None
    removed = ' and '.join(NOTES[n] if i == 0 else NOTES[n][0].lower() + NOTES[n][1:] for i, n in enumerate(notes))
    return removed + " was removed from what you supplied; the application's field needs the corrected value (the key alone after Bearer and one space)."
