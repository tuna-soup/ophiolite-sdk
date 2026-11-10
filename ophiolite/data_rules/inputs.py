"""E144 s1 C4: the SDK adapter from `ophiolite.readers` results to the engine's neutral input (strategy §2).

Not carried: Connectors has its own adapter over its readers. A missing sample (None, the header NULL as the reader
gives it) becomes NaN; a LAS curve keeps the mnemonic the file states, so a repeated name stays repeated.
"""
from array import array

NAN = float('nan')


def _column(rows, at):
    return array('d', (NAN if row[at] is None else row[at] for row in rows))


def _null(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def las(log):
    return {'null': _null(log.null), 'index': _column(log.data, 0),
            'curves': [{'mnemonic': c[0], 'unit': c[1], 'values': _column(log.data, at)} for at, c in enumerate(log.curves) if at]}


def tops(table):
    name, md = table.columns.index('name'), table.columns.index('md')
    return {'depth_unit': table.context['depth_unit'], 'depth_datum': table.context.get('depth_datum'),
            'tops': [{'name': row[name], 'md': row[md]} for row in table.rows]}


def deviation(table):
    return {'depth_unit': table.context['depth_unit'], 'depth_datum': table.context.get('depth_datum'),
            'md': _column(table.rows, table.columns.index('md'))}


def _system(context):
    """E144 s2 C4: the declared system's entry of this package's coordinate-systems.json, or None (unknown or
    uncatalogued: in-area-of-use/1 does not apply)."""
    import json
    from importlib.resources import files
    document = json.loads(files('ophiolite').joinpath('contracts/vocabulary/v1/coordinate-systems.json').read_bytes())
    return {s['code']: s for s in document['systems']}.get(context.get('crs'))


def points(table):
    """A point set as `ophiolite.readers` reads it (at most 100,000 nodes): x and y by name, in file order."""
    x, y = table.columns.index('x'), table.columns.index('y')
    return {'system': _system(table.context), 'x': _column(table.rows, x), 'y': _column(table.rows, y)}


def grid(surface):
    """A grid's cell centres from the north row (spatial.py); a missing cell is no node."""
    context = surface.context
    return {'system': _system(context), 'ncols': context['ncols'], 'nrows': context['nrows'],
            'x_first': context['x_first_center'], 'y_first': context['y_first_center'], 'cell': context['cell_size'],
            'present': bytearray(v is not None for row in surface.cells for v in row)}


ADAPTERS = {'las2/1': las, 'well-tops-csv/1': tops, 'deviation-csv/1': deviation, 'points-csv/1': points,
            'esri-ascii-grid/1': grid}
