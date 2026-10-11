"""ophiolite.label-rule/1 (E105a, S3): the one rule for a label a person reads, shared by the Platform's display layer
and the procedure validator (contracts/procedures/v1/procedure.py), and copied byte for byte into the SDK.

Standard library only. Callers load this file by path from its source text (no bytecode is read or written), so the
SDK's contract snapshot stays exactly the tracked files. The rule body is E93's, with E96's row 45 (an e-mail
address or a lowercase dotted identifier as a word), moved here verbatim from project_gateway.display.
"""
import re

LABEL_LIMIT = 80

# R16: words that belong under Technical details only, never in a label a person reads by default
ENGINEERING_WORDS = ('lineage', 'provenance', 'derivation', 'replay', 'diff', 'trace', 'hash', 'digest', 'prov', 'request id')
_WORD = {w: re.compile(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', re.I) for w in ENGINEERING_WORDS}

_UUID = re.compile(r'[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}')
_HEX_SUFFIX = re.compile(r'[-_.:#]?(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{4,}$')
_HEX_TOKEN = re.compile(r'(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}')
_KEBAB = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)+$')
_EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
_DOTTED = re.compile(r'^[a-z]{3,}[a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$')  # E96 row 45: `ophiolite.shale-volume`, never "J.R.R." or "2.1"


def label_text(label):
    """The owner's own words as plain text: control characters removed, at most 80 characters."""
    text = re.sub(r'[\x00-\x1f\x7f-\x9f  ]', '', label if isinstance(label, str) else '').strip()
    return text[:LABEL_LIMIT]


def readable_label(text):
    """E93: the one rule for a label a person reads (agent, workload and client names): the label as plain text when
    it reads as a name, else None (callers show neutral words: "An agent", "An unnamed program"). Refused: UUIDs, a
    hex suffix (`alice-7f3a`), long hex runs, snake_case and kebab-case tokens and paths, and (E96, row 45) an e-mail
    address or a lowercase dotted identifier as a word of the label. Names with Unicode and ordinary punctuation pass
    ("Clara", "Renée", "Well tidy", "Jean-Luc", "J.R.R. Tolkien", "QGIS 3.34"). `label_text` removes controls and
    bounds the length only; it is not this check."""
    value = label_text(text)
    if not value or not any(c.isalpha() for c in value): return None
    if '/' in value or '\\' in value or '_' in value: return None
    if _UUID.search(value) or _HEX_TOKEN.search(value): return None
    if any(_HEX_SUFFIX.search(word) and not word.isalpha() for word in value.split()): return None
    if _KEBAB.match(value): return None
    if _EMAIL.search(value) or any(_DOTTED.match(word.strip('()[],;:"\'')) for word in value.split()): return None
    return value


def engineering_word(text):
    """The first R16 engineering word in the text, or None."""
    return next((w for w, pattern in _WORD.items() if pattern.search(text if isinstance(text, str) else '')), None)


def display_label(text):
    """A label shown by default (registry entries, procedures): readable as it stands (nothing removed or cut) and
    free of engineering words."""
    value = readable_label(text) if isinstance(text, str) else None
    return value is not None and value == text.strip() and engineering_word(value) is None
