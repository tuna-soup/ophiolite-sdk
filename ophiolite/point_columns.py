"""E139 s2 (S2-6): the stored columns form of a point set above 100,000 nodes (`ophiolite.point-columns/1`), read offline:

    b'OPHPTS1\\n' | u32 LE header length | canonical JSON header | for each of header.columns: count x f64 LE

`view` keeps the Platform codec's structural and numeric checks (`project_gateway/point_columns.py` `decode`): the magic,
a header length inside the body, the header written canonically, columns x, y, z exactly when the file has z, then the
attributes, the count agreeing with the context and the total length; nothing infinite, every missing value the one quiet
NaN, x and y never missing. The header's contract, the context's extents and missing-z count, the source identity and the
interpretation are checked by `validate.typed_pair` as for every typed payload. The result is an in-memory view in the
point-set shape (missing as None); it is never claimed to be a valid `ophiolite.point-set/1` document."""
from array import array
import json
import math
import struct
import sys

from .errors import VerificationFailed

SCHEMA = 'ophiolite.point-columns/1'
MAGIC = b'OPHPTS1\n'
CANONICAL_NAN = 0x7FF8000000000000
DAMAGED = 'The point set’s columns are damaged.'


def _column(raw, at, count, kind):
    values = array(kind)
    values.frombytes(raw[at:at + 8 * count])
    if sys.byteorder == 'big': values.byteswap()
    return values


def _refuse(what):
    raise VerificationFailed(DAMAGED, 'No files were saved.', details={'check': what})


def view(raw):
    """(header, {'points': [[x, y, z or None]], 'attributes': [{'name', 'values'}]}) of the stored bytes RAW."""
    raw = bytes(raw)
    start = len(MAGIC) + 4
    if len(raw) < start or raw[:len(MAGIC)] != MAGIC: _refuse('magic')
    size, = struct.unpack('<I', raw[len(MAGIC):start])
    if len(raw) < start + size: _refuse('header length')
    text = raw[start:start + size]
    try: header = json.loads(text)
    except (ValueError, UnicodeError): _refuse('header')
    if not isinstance(header, dict) or json.dumps(header, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() != text: _refuse('header not canonical')
    context, count, names = header.get('context'), header.get('count'), header.get('columns')
    if header.get('schema') != SCHEMA or header.get('encoding') != 'f64le' or not isinstance(context, dict): _refuse('schema')
    if type(count) is not int or count < 1 or count != context.get('count'): _refuse('count')
    attributes, z = context.get('attributes'), context.get('z_provided') is True
    if not isinstance(attributes, list) or names != ['x', 'y', *(['z'] if z else []), *attributes]: _refuse('columns')
    body = start + size
    if len(raw) != body + 8 * count * len(names): _refuse('total length')
    columns = {}
    for k, name in enumerate(names):
        at = body + 8 * count * k
        values, bits = _column(raw, at, count, 'd'), _column(raw, at, count, 'Q')
        if any(math.isinf(v) for v in values): _refuse('infinite value')
        if any(bits[i] != CANONICAL_NAN for i, v in enumerate(values) if v != v): _refuse('a missing value that is not the one NaN')
        columns[name] = [v if v == v else None for v in values]
    if None in columns['x'] or None in columns['y']: _refuse('x and y')
    zs = columns.get('z') or [None] * count
    return header, {'points': [[a, b, c] for a, b, c in zip(columns['x'], columns['y'], zs)],
                    'attributes': [{'name': n, 'values': columns[n]} for n in attributes]}
