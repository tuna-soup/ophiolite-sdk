"""E187 slice 0: which models read and which models send.

An `Answer` reads a gateway answer or a served document. It keeps a field it does not know (in `model_extra`, untyped,
outside the promise) and keeps strict types on the fields it knows, so an added optional answer field never makes a
release refuse the answer. A `Request` checks what this program is about to send and stays closed, so a misspelt
argument is refused before it is sent. Every pydantic model of the package is exactly one of the two
(tests/test_answer_models.py).

`POLICY` names the answers that differ on purpose: the redacted views. A closed one refuses an answer that carries more
than the redacted shape (the SDK's disclosure check); a dropped one never makes such a field reachable. Any change to
it is a change to that check.

A word of a closed vocabulary the release does not know stays a refusal (`refusal`), in words that name the remedy:
ignoring it would change what the answer means.
"""
import re

from pydantic import BaseModel, ConfigDict

POLICY = {'RestrictedManifest': 'forbid', 'RestrictedReceipt': 'forbid', 'RestrictedBinding': 'forbid',
          'RestrictedRun': 'ignore', 'RestrictedResultSummary': 'ignore', 'RestrictedResultPreview': 'ignore'}
NEWER = 'This answer uses a word this release of ophiolite does not know; upgrade ophiolite to read it.'
_WORD_ERRORS = {'literal_error': 'input', 'union_tag_invalid': 'tag'}
_SEGMENT = re.compile(r'^[a-z_][a-z0-9_]{0,63}$')


class Answer(BaseModel):
    """Reads a gateway answer or a served document: unknown fields kept, known fields strict."""
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)


class Request(BaseModel):
    """Checks what this program is about to send: closed."""
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


def _where(loc):
    """The error's location with field names and indices only; any other segment (a dictionary key, a union label)
    becomes `*`, so nothing the server chose is repeated."""
    return '.'.join(str(s) if isinstance(s, int) or (isinstance(s, str) and _SEGMENT.match(s)) else '*' for s in loc)


def _word(e):
    key = _WORD_ERRORS.get(e.get('type'))
    if key == 'input': return isinstance(e.get('input'), str)
    return key == 'tag' and isinstance((e.get('ctx') or {}).get('tag'), str)


def refusal(error, fallback):
    """What an answer site raises for `error`: VerificationFailed(NEWER) when every error is a word of a closed
    vocabulary this release does not know (a string Literal or a string discriminator tag), else the site's own
    `fallback`, so a malformed answer keeps its sentence and exception type. A consequence the fallback states as its
    recovery ("No files were saved.") follows the upgrade sentence: the caller needs it either way (ophiolite-66)."""
    from pydantic import ValidationError
    from ..errors import VerificationFailed
    errors = error.errors() if isinstance(error, ValidationError) else []
    if errors and all(_word(e) for e in errors):
        return VerificationFailed(NEWER, getattr(fallback, 'recovery', ''), details={'at': _where(errors[0].get('loc', ()))})
    return fallback
