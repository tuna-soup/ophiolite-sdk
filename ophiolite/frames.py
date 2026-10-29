"""E126a: write a pandas DataFrame as the LAS file `write_curves` makes, so a notebook publishes what it computed.

The frame's index is the depth and each written column needs a declared unit. Missing values (`NaN`, `None`,
`pd.NA`) are written as the null marker and read back as missing; they never become a number. Only the depth, the
column order, the values and the units you declare are carried: dtypes, `attrs` and index or column names are not.
Importing this module imports nothing outside the SDK (pandas is not imported; the frame brings its own methods).
"""
from .errors import ValidationFailed
from .writers import WrittenOriginal, write_curves


def _missing(value):
    if value is None: return True
    try: return bool(value != value)  # NaN is the one float unequal to itself
    except TypeError: return True  # pd.NA refuses a truth value: it is missing


def _exact(value, where):
    """The float a sample or depth is written as; an integer a binary64 float cannot hold exactly is refused."""
    number = float(value)
    if not isinstance(value, float) and hasattr(value, '__index__') and int(number) != int(value):
        raise ValidationFailed([f'{int(value)} in {where} cannot be written exactly; nothing is rounded.'])
    return number


def write_frame(frame, units, *, depth_unit=None, notes=(), well='DERIVED', filename='derived.las') -> WrittenOriginal:
    """A DataFrame (index = depth, numeric columns) as a `las2/1` `WrittenOriginal` for `Client.publish_derived`.

    `units` maps every column to its declared unit ({'GR': 'gAPI'}); a column without one is refused, and nothing is
    inferred. `NaN`, `None` and `pd.NA` become missing; a real sample equal to the null marker -999.25, a missing or
    repeated depth, and an integer or a float wider than 64 bits that a 64-bit float cannot hold exactly are refused. Values are written in their shortest exact
    spelling, so an exact read returns the same floats. Not carried: dtypes, `frame.attrs`, the index and column names, and any other frame metadata."""
    if not all(hasattr(frame, a) for a in ('index', 'columns', 'dtypes')):
        raise ValidationFailed(['Pass a pandas DataFrame whose index is the depth.'])
    units = dict(units or {})
    columns = list(frame.columns)
    repeated = sorted({str(c) for c in columns if columns.count(c) > 1})
    if repeated: raise ValidationFailed([f'Column labels must be distinct: {repeated}.'])
    unitless = [c for c in columns if c not in units]
    if unitless: raise ValidationFailed([f'Declare a unit for {unitless}; nothing is inferred.'])
    unknown = [c for c in units if c not in columns]
    if unknown: raise ValidationFailed([f'These units name no column: {unknown}.'])
    textual = [c for c in columns if getattr(frame[c].dtype, 'kind', 'O') not in 'fiu']
    if textual: raise ValidationFailed([f'Column {textual} is not numeric; write numbers only.'])
    wide = [c for c in columns if frame[c].dtype.kind == 'f' and frame[c].dtype.itemsize > 8]
    if wide: raise ValidationFailed([f'Column {wide} is wider than a 64-bit float and cannot be written exactly; nothing is rounded.'])
    if getattr(frame.index.dtype, 'kind', 'O') == 'f' and frame.index.dtype.itemsize > 8:
        raise ValidationFailed(['The depth is wider than a 64-bit float and cannot be written exactly; nothing is rounded.'])
    depth = list(frame.index)
    if any(_missing(d) for d in depth): raise ValidationFailed(['Depth cannot be missing.'])
    depth, seen = [_exact(d, 'the depth') for d in depth], set()
    for d in depth:
        if d in seen: raise ValidationFailed([f'Depths must be distinct; {d!r} appears more than once.'])
        seen.add(d)
    curves = {str(c): (units[c], [None if _missing(v) else _exact(v, str(c)) for v in frame[c].tolist()]) for c in columns}
    return write_curves(depth, curves, depth_unit=depth_unit, well=well, filename=filename, notes=notes)
