"""E168 s1 (D5-D7): the OSDU kinds of the export matrix, read from the packaged table and never computed.

`kinds()` is the matrix's rows; `profiles_for(kind)` is every profile whose row names KIND exactly, in the matrix's
order, and `[]` for a kind no row names. The table is the one `contracts/mapper/v1/osdu_kind.py` reads (s0, D6).
Standard library only: `import ophiolite` stays light.
"""
import json
from pathlib import Path

MATRIX = Path(__file__).resolve().parent / 'contracts' / 'mapper' / 'v1' / 'export-matrix.json'


def _rows():
    return json.loads(MATRIX.read_text(encoding='utf-8'))['rows']  # read on each call: a caller's change never reaches the next answer


def kinds():
    """The export matrix's rows, in its order, each a new dict: profile, kind (or none, the reason) and the rest."""
    return _rows()


def profiles_for(kind):
    """Every profile whose export-matrix row has exactly KIND, in the matrix's order; an empty list when none has."""
    if not isinstance(kind, str):
        raise TypeError('kind is an OSDU kind string, such as osdu:wks:work-product-component--WellLog:1.5.0')
    return [row['profile'] for row in _rows() if row.get('kind') == kind]
