"""E203 s1 (strategy E203-s1-kind-at-publication, D5): a kind of table checked on this computer, without the server.

A vendored copy of the Platform's pure kind-of-table module (`ophiolite.table-kind/1`): its models, `declaration_problems`,
`problems` and their helpers, `digest` and `sentence`, with the words document (`contracts/vocabulary/v1/
table-kind-words.json`, as synced) and the unit table they read (`table_kind_units.json`: each quantity class and the
symbols of its units, written from the Connectors' units table). Nothing here imports the gateway or the Connectors; a
Platform test compares the functions and the unit table with their sources, and the fixtures' `expected.json` is the
oracle for both.

`check(path)` reads an exported file: a Parquet file's `ophiolite.export` record and its `table_kind` block, or a CSV
file and the `<file>.table-kind.json` written beside it by `client.export_file(..., format='csv')`. It recomputes the
declaration's digest (`digest-differs` when the declaration was changed after export), reads the rows and answers the
problems; `Unreadable` (its `reason` a key of the words) when the file carries no kind or the block cannot be read.
"""
from __future__ import annotations

import csv
import datetime
import decimal
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_serializer, model_validator

from .models.answers import Request

HERE = Path(__file__).resolve().parent
WORDS_PATH = HERE / 'contracts' / 'vocabulary' / 'v1' / 'table-kind-words.json'
UNITS_PATH = HERE / 'table_kind_units.json'
TABLE_KIND = 'ophiolite.table-kind/1'
TYPES = ('text', 'number', 'whole-number', 'date', 'yes-no')
# What a kept column's `logical` type may be for each type of a kind's column; `text` takes any.
FITS = {'number': ('integer', 'float', 'decimal'), 'whole-number': ('integer',), 'date': ('date',), 'yes-no': ('boolean',)}
MEASURED = ('number', 'whole-number')
DECLARATION = ('column-repeated', 'key-not-a-column', 'key-may-be-empty', 'quantity-unknown', 'unit-not-of-quantity', 'quantity-on-text')
CHECK = ('column-missing', 'wrong-type', 'empty', 'unit-missing', 'unit-wrong-dimension', 'key-empty', 'key-repeated')
SIDECAR = '.table-kind.json'  # beside a CSV file: <file>.table-kind.json
EXPORT_KEY = b'ophiolite.export'  # a Parquet file's export record (ophiolite.table-export/1)
REF = ('id', 'word', 'version', 'digest')

_ABSENT = {'json_schema_extra': lambda schema: schema.pop('default', None)}
Word = Annotated[str, Field(pattern=r'^[a-z][a-z0-9-]{0,39}$', description="The project's word for the kind; what a publication names")]
ItemKind = Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9.-]*/[0-9]+$')]
ColumnName = Annotated[str, Field(min_length=1, max_length=1024)]
KindId = Annotated[str, Field(pattern=r'^[0-9a-f]{32}$', description='Minted by the server at random; the same for every version of a kind')]
Hex64 = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class Contract(Request):
    """A declaration read from an exported file is checked as the server checks one sent to it: closed (E187 `Request`)."""
    model_config = ConfigDict(extra='forbid', strict=True)


def _drop_absent(out, *keys):
    for key in keys:
        if out.get(key) is None: out.pop(key, None)
    return out


class TableKindColumn(Contract):
    """One column a table of the kind has: its type, whether it must be present (and read), whether a cell may be
    empty, and for a number its quantity class with the unit the team writes (both or neither; never converted)."""
    name: ColumnName
    type: Literal['text', 'number', 'whole-number', 'date', 'yes-no']
    required: bool
    empty: bool
    quantity: str = Field(default=None, min_length=1, max_length=80, **_ABSENT)
    unit: str = Field(default=None, min_length=1, max_length=32, **_ABSENT)

    @model_validator(mode='after')
    def _together(self):
        if (self.quantity is None) != (self.unit is None): raise ValueError('a quantity is named with its unit, and a unit only with its quantity')
        return self

    @model_serializer(mode='wrap')
    def _absent(self, handler):
        return _drop_absent(handler(self), 'quantity', 'unit')


class TableKindDeclaration(Contract):
    """What a project's members mean by one word for a table, as declared (one version)."""
    word: Word
    label: str = Field(min_length=1, max_length=80)
    row: str = Field(min_length=1, max_length=120)
    columns: list[TableKindColumn] = Field(min_length=1, max_length=64)
    key: list[ColumnName] = Field(min_length=1, max_length=8)
    made_for: list[ItemKind] = Field(default=None, min_length=1, max_length=8, **_ABSENT)
    standard: str = Field(default=None, min_length=1, max_length=120, **_ABSENT)

    @model_validator(mode='after')
    def _key_once(self):
        if len(set(self.key)) != len(self.key): raise ValueError('a key names each column once')
        return self

    @model_serializer(mode='wrap')
    def _absent(self, handler):
        return _drop_absent(handler(self), 'made_for', 'standard')


class TableKindRef(Contract):
    """What a table published as a kind records: which kind, which version, and its digest."""
    id: KindId
    word: Word
    version: int = Field(ge=1)
    digest: Hex64


# --- the digest, the words and the rules (the Platform's, unchanged) ---------------------------------------------------

def canonical(declaration):
    """The bytes a declaration's digest is taken over: JSON with sorted keys, no spaces, UTF-8."""
    return json.dumps(declaration, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(declaration):
    return hashlib.sha256(canonical(declaration)).hexdigest()


_LOADED = {}


def words():
    """`ophiolite.table-kind-words/1` as this library carries it."""
    if 'words' not in _LOADED: _LOADED['words'] = json.loads(WORDS_PATH.read_text(encoding='utf-8'))
    return _LOADED['words']


def _units():
    """(class key by quantity class name, class key by unit symbol, spellings met in real files)."""
    if 'units' not in _LOADED:
        table = json.loads(UNITS_PATH.read_text(encoding='utf-8'))
        _LOADED['units'] = ({c['name']: k for k, c in table['classes'].items()},
                            {symbol: k for k, c in table['classes'].items() for symbol in c['units']}, table['written_as'])
    return _LOADED['units']


def quantity_class(name):
    """The unit registry's class key for a quantity class name (`length` -> `L`), or None."""
    return _units()[0].get(name)


def unit_class(symbol):
    """The class key of a unit as written (the registry's symbol or one of its spellings), or None; an empty or
    `unknown` unit is not stated."""
    _, classes, written_as = _units()
    text = (symbol or '').strip()
    if text.lower() in ('', 'unknown'): return None
    return classes.get(text) or classes.get(written_as.get(text, ''))


def declaration_problems(declaration):
    """The reason keys a schema-valid declaration (a dict as sent) breaks, sorted, once each."""
    found = set()
    names = [c['name'] for c in declaration['columns']]
    if len(set(names)) != len(names): found.add('column-repeated')
    by_name = {c['name']: c for c in declaration['columns']}
    for name in declaration['key']:
        column = by_name.get(name)
        if column is None: found.add('key-not-a-column')
        elif column['empty'] or not column['required']: found.add('key-may-be-empty')
    for column in declaration['columns']:
        if 'quantity' not in column: continue
        if column['type'] not in MEASURED: found.add('quantity-on-text')
        cls = quantity_class(column['quantity'])
        if cls is None: found.add('quantity-unknown')
        elif unit_class(column['unit']) != cls: found.add('unit-not-of-quantity')
    return sorted(found)


def _text(cell):
    """A cell as text, the form a missing marker is written in: true or false, a number by its shortest form."""
    if isinstance(cell, bool): return 'true' if cell else 'false'
    if isinstance(cell, float): return repr(cell)
    return str(cell)


def _is_empty(cell, marker):
    if cell is None: return True
    if isinstance(cell, str) and not cell.strip(): return True
    return marker is not None and _text(cell) == marker


def _key_value(cell, logical):
    """A key cell compared by value for numbers (`1.0` and `1.00` are one), as it is otherwise."""
    if logical in ('integer', 'decimal', 'float') and not isinstance(cell, bool): return decimal.Decimal(str(cell))
    return cell


def _problem(column, reason, row=None, **detail):
    return {'column': column, 'reason': reason, 'row': row, 'detail': detail}


def problems(declaration, table):
    """What keeps `table` (the `columns`, `declarations` and `rows` of a table-file/1 document) from being a table of
    the kind `declaration` (a valid declaration, as a dict), as `{column, reason, row, detail}` sorted by column then
    reason, one per column and reason; `[]` when it is one. `row` counts data rows from 1 and is null for a reason about
    the whole column. Rows hold the read columns only, so a cell is found by its column's place among those."""
    read = [c['name'] for c in table['columns'] if c['read']]
    kept = {}
    for column in table['columns']: kept.setdefault(column['name'], column)
    notes = table['declarations']['columns']
    found = []
    for column in declaration['columns']:
        name = column['name']
        have = kept.get(name)
        if have is None or not have['read']:
            if column['required']: found.append(_problem(name, 'column-missing'))
            continue
        logical = have['logical']
        if column['type'] in FITS and logical not in FITS[column['type']]: found.append(_problem(name, 'wrong-type', logical=logical))
        note = notes.get(name) or {}
        if 'quantity' in column:
            unit = note.get('unit')
            if unit is None: found.append(_problem(name, 'unit-missing', quantity=column['quantity']))
            elif unit_class(unit) != quantity_class(column['quantity']): found.append(_problem(name, 'unit-wrong-dimension', unit=unit, quantity=column['quantity']))
        at = read.index(name)
        reason = 'key-empty' if name in declaration['key'] else None if column['empty'] else 'empty'
        if reason is not None:
            first = next((i for i, row in enumerate(table['rows'], 1) if _is_empty(row[at], note.get('missing'))), None)
            if first is not None: found.append(_problem(name, reason, first))
    found.extend(_repeated(declaration, table, read, kept, notes))
    return sorted(found, key=lambda p: (p['column'] or '', p['reason']))


def _repeated(declaration, table, read, kept, notes):
    """The first two rows with the same key, among rows whose key cells are all there and not empty."""
    key = declaration['key']
    if any(name not in read for name in key): return []
    places = [(read.index(name), kept[name]['logical'], (notes.get(name) or {}).get('missing')) for name in key]
    seen = {}
    for i, row in enumerate(table['rows'], 1):
        if any(_is_empty(row[at], marker) for at, _, marker in places): continue
        value = tuple(_key_value(row[at], logical) for at, logical, _ in places)
        if value in seen: return [_problem(None, 'key-repeated', i, key=list(key), rows=[seen[value], i])]
        seen[value] = i
    return []


def sentence(problem):
    """A problem as a person reads it: the quantity by its label, never its class name."""
    w = words()
    label = w['quantities'].get(problem['detail'].get('quantity'), problem['detail'].get('quantity'))
    rows = problem['detail'].get('rows') or [None, None]
    return w['reasons'][problem['reason']].format(column=problem['column'], row=problem['row'], unit=problem['detail'].get('unit'),
                                                  quantity=label, first=rows[0], second=rows[1])


# --- an exported file, checked offline ---------------------------------------------------------------------------------

class Unreadable(ValueError):
    """The file could not be checked: `reason` is a key of the words' `offline` or `refusals`; the message its sentence."""

    def __init__(self, reason, **fields):
        self.reason = reason
        w = words()
        super().__init__(((w.get('offline') or {}).get(reason) or w['refusals'][reason]).format(**fields))


def block_of(value):
    """The `{id, word, version, digest, declaration}` block as written, checked: its shape, the declaration's digest
    recomputed (`digest-differs`), the declaration against the contract and its rules (`unreadable`)."""
    if not isinstance(value, dict) or set(value) != {*REF, 'declaration'} or not isinstance(value['declaration'], dict):
        raise Unreadable('unreadable')
    try: TableKindRef.model_validate({k: value[k] for k in REF})
    except ValueError: raise Unreadable('unreadable') from None
    if digest(value['declaration']) != value['digest']: raise Unreadable('digest-differs')
    try: declaration = TableKindDeclaration.model_validate(value['declaration']).model_dump(mode='json')
    except ValueError: raise Unreadable('unreadable') from None
    if declaration != value['declaration'] or declaration['word'] != value['word'] or declaration_problems(declaration):
        raise Unreadable('unreadable')
    return value


def _view(columns, rows):
    """A table-file/1-shaped view of an exported table: `columns` [{name, logical, unit?, missing?}] in file order."""
    return {'columns': [{'name': c['name'], 'logical': c['logical'], 'read': True} for c in columns],
            'declarations': {'columns': {c['name']: {'unit': c.get('unit'), 'missing': c.get('missing')} for c in columns}},
            'rows': rows}


def _cell(value):
    """A Parquet value in the form a kept table holds it: decimals and dates as their exact text."""
    if isinstance(value, decimal.Decimal): return str(value)
    if isinstance(value, datetime.datetime):
        return value.strftime('%Y-%m-%dT%H:%M:%S.%f').rstrip('0').rstrip('.') + ('Z' if value.tzinfo is not None else '')
    if isinstance(value, datetime.date): return value.isoformat()
    return value


def read_parquet(path):
    """(block, view) of an exported Parquet or GeoParquet file: the block from its `ophiolite.export` record, each
    column's type, unit and missing-value marker from its own field metadata (the record's when it has none)."""
    try: import pyarrow.parquet as pq
    except ImportError: raise Unreadable('no-parquet') from None
    try: table = pq.read_table(str(path))
    except (OSError, ValueError): raise Unreadable('unreadable') from None  # pyarrow's ArrowInvalid is a ValueError
    raw = (table.schema.metadata or {}).get(EXPORT_KEY)
    if raw is None: raise Unreadable('no-kind')
    try: record = json.loads(raw)
    except ValueError: raise Unreadable('unreadable') from None
    if not isinstance(record, dict) or record.get('table_kind') is None: raise Unreadable('no-kind')
    block = block_of(record['table_kind'])
    stated = {c.get('name'): c for c in record.get('columns') or () if isinstance(c, dict)}
    columns, cells = [], []
    for field in table.schema:
        notes = {k.decode(): v.decode() for k, v in (field.metadata or {}).items()}
        if 'ophiolite.logical' not in notes and field.name not in stated: continue  # a GeoParquet file's geometry
        given = stated.get(field.name) or {}
        columns.append({'name': field.name, 'logical': notes.get('ophiolite.logical', given.get('logical', 'text')),
                        'unit': notes.get('ophiolite.unit', given.get('unit')), 'missing': notes.get('ophiolite.missing', given.get('missing'))})
        cells.append([_cell(v) for v in table.column(field.name).to_pylist()])
    return block, _view(columns, [list(row) for row in zip(*cells)])


def _typed(text, logical):
    """A CSV cell as a kept table holds it: an empty cell is null; integers, floats and true or false as such."""
    if text == '': return None
    try:
        if logical == 'integer': return int(text)
        if logical == 'float': return float(text)
    except ValueError: return text
    if logical == 'boolean': return {'true': True, 'false': False}.get(text, text)
    return text


def read_csv(path):
    """(block, view) of an exported CSV file and the `<file>.table-kind.json` beside it: the block and each column's
    type, unit and missing-value marker as the export recorded them; a column the sidecar does not name is text."""
    sidecar = Path(str(path) + SIDECAR)
    if not sidecar.is_file(): raise Unreadable('no-kind')
    try: written = json.loads(sidecar.read_text(encoding='utf-8'))
    except ValueError: raise Unreadable('unreadable') from None
    if not isinstance(written, dict) or not isinstance(written.get('columns'), list): raise Unreadable('unreadable')
    block = block_of(written.get('table_kind'))
    stated = {c.get('name'): c for c in written['columns'] if isinstance(c, dict)}
    with open(path, newline='', encoding='utf-8') as handle: lines = list(csv.reader(handle))
    if not lines: raise Unreadable('unreadable')
    columns = [{'name': name, 'logical': (stated.get(name) or {}).get('logical', 'text'), 'unit': (stated.get(name) or {}).get('unit'),
                'missing': (stated.get(name) or {}).get('missing')} for name in lines[0]]
    rows = [[_typed(text, c['logical']) for text, c in zip(line, columns)] + [None] * (len(columns) - len(line)) for line in lines[1:]]
    return block, _view(columns, rows)


def sidecar(table_kind, columns):
    """The `<file>.table-kind.json` written beside an exported CSV file: the block and the columns as exported."""
    return {'table_kind': table_kind, 'columns': columns}


def check(path):
    """{kind: {id, word, version, digest}, problems, sentences} of an exported file checked against the kind written
    with it; `problems` empty when the table is one of the kind. Unreadable when it cannot be checked."""
    path = Path(path)
    with open(path, 'rb') as handle: parquet = handle.read(4) == b'PAR1'
    block, view = read_parquet(path) if parquet else read_csv(path)
    found = problems(block['declaration'], view)
    return {'kind': {k: block[k] for k in REF}, 'problems': found, 'sentences': [sentence(p) for p in found]}


class TableKindClient:
    """E203 s1 (D6): a project's kinds of table through `client._post` (`client.table_kinds`): declare, list, show.
    Nothing is refused here but a declaration that is no JSON object: the server checks every request and every right."""

    def __init__(self, client):
        self._client = client

    def declare(self, declaration, *, expected_version=None, command_id=None):
        """Declare a kind of table, or its next version: the stored version (`ophiolite.table-kind/1`). A quantity may be
        written as the label a person reads; it is stored as its class. The same declaration again stores no version."""
        import uuid
        if not isinstance(declaration, dict): raise ValueError('A declaration is a JSON object: word, label, row, columns and key.')
        body = {'command_id': command_id or 'kind-%s' % uuid.uuid4().hex, 'declaration': declaration}
        if expected_version is not None: body['expected_version'] = expected_version
        return self._client._post('table-kinds', 'declare', body, retry=True)

    def list(self):
        """The project's kinds of table, each at its latest version: [ophiolite.table-kind/1, ...]."""
        return self._client._post('table-kinds', 'list', {}, retry=True)['kinds']

    def show(self, word, version=None):
        """One kind of table at VERSION, or at its latest version without one."""
        return self._client._post('table-kinds', 'show', {'word': word, **({'version': version} if version is not None else {})}, retry=True)
