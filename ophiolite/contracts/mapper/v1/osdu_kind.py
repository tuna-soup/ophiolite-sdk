"""E168 s0 (R-N1, D6): the OSDU kind of a profile, read from `export-matrix.json` and never computed.

`lookup(profile)` is `(kind, None)` for a row with a kind, `(None, reason)` for a row with none (the row's own sentence)
and `(None, NO_ROW)` for a profile the matrix does not list. Standard library only (Python 3.10): the gateway, the
contract generators and the SDK's synced copy read the same function.
"""
import json
from functools import lru_cache
from pathlib import Path

MATRIX = Path(__file__).resolve().parent / 'export-matrix.json'
NO_ROW = 'no correspondence declared'  # the generator's own phrase for a profile without a declared kind


@lru_cache(maxsize=8)
def _rows(path):
    return {row['profile']: row for row in json.loads(Path(path).read_text(encoding='utf-8'))['rows']}


def lookup(profile, matrix=None):
    """(kind, reason) for PROFILE from MATRIX (default: this folder's export-matrix.json); exactly one is None."""
    row = _rows(str(matrix or MATRIX)).get(profile)
    if row is None:
        return None, NO_ROW
    return (row['kind'], None) if row.get('kind') else (None, row['none'])


def pair(profile, matrix=None):
    """The answer fields: {'osdu_kind': ..., 'osdu_kind_reason': ...}."""
    kind, reason = lookup(profile, matrix)
    return {'osdu_kind': kind, 'osdu_kind_reason': reason}
