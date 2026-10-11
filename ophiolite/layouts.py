"""E89: the project's layouts in Python — the same list, words and refusals as the workspace's Layouts page.

A layout remembers how the columns of one kind of table were mapped. `client.layouts().match(columns)` lists the active
layouts a header is, exact or in another order; several are all listed and none is chosen: a layout is only used when
you name it (`imports.from_table(..., layout='Tubbergen tops')` or `ophiolite import table --layout`). Layouts are named
by their name here; ids, digests and the stored document stay in the answers (`--json` puts them under `technical`).

A refusal keeps the server's sentence (the browser's words): what happened, who can change it and what to do next.
"""
import json
import unicodedata
import uuid
from pathlib import Path

from .errors import Refused, Unavailable
from .well_imports import _checked

# the refusals layouts answers in words (Integration E89 strategy J7)
CODES = ('capacity', 'changed', 'command-reused', 'connection-outside', 'does-not-fit', 'edit-required', 'file-changed', 'header-blank',
         'header-repeated', 'kind-unavailable', 'name', 'name-taken', 'needs-connection', 'no-access', 'no-room', 'no-saved-mapping',
         'not-a-layouts-file', 'not-a-table-layout', 'not-downloadable', 'not-found', 'not-valid', 'retired', 'schema-differs',
         'target-changed', 'too-many-layouts')
HOLDS = {'well-tops': 'Well tops', 'wells': 'Wells', 'deviation-survey': 'Deviation survey', 'time-depth': 'Time-depth', 'point-set': 'Points'}
LIST_THEM = 'List them with: ophiolite layouts list.'
NO_SUCH = 'This project has no layout called "%s". ' + LIST_THEM  # J7-11 in the SDK and CLI
RESULT = {'added': 'Added', 'already-here': 'Already here'}


def needs_decision(matches):
    """J8: a table that matches a project layout and was given neither a mapping nor --layout; nothing is added."""
    from .errors import IntegrityConflict
    names = ', '.join('"%s"' % m['name'] for m in matches)
    first = matches[0]['name']
    return IntegrityConflict('Needs your decision: this table matches the layout %s. Add it with --layout "%s".' % (names, first) if len(matches) == 1 else
                             'Needs your decision: this table matches the layouts %s. Add it with --layout and one of their names.' % names, code='needs-decision')


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().replace('_', ' ').replace('-', ' ').split())


def _said(call):
    """A refusal of layouts in the server's own sentence; any other error as the transport raised it."""
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if error.code not in CODES or not error.server_message: raise
        raise type(error)(error.server_message, status=error.status, code=error.code, request_id=error.request_id, remedy=error.remedy,
                          docs=error.docs, server_message=error.server_message, details=error.details) from error


def holds(view):
    """J4: what a layout holds."""
    return 'Well locations (database table)' if view['by'] == 'table' else HOLDS.get(view['target'], 'A table')


def columns_line(view):
    """J4: `4: Well Name, Top, MD (m) and 1 more`, the mapped columns in the file's order; '' for a database table."""
    doc = view.get('layout') or {}
    match = doc.get('match') or {}
    if match.get('by') != 'header': return ''
    order = match['columns']
    labels = [c for v in ((doc.get('mapping') or {}).get('fields') or {}).values() for c in (v if isinstance(v, list) else [v])]
    labels.sort(key=lambda c: order.index(_normal(c)) if _normal(c) in order else len(order))
    shown = labels[:3]
    return '%d: %s%s' % (len(order), ', '.join(shown), ' and %d more' % (len(order) - len(shown)) if len(order) > len(shown) else '')


def _day(at):
    import datetime
    d = datetime.datetime.fromtimestamp(at)  # the reader's day, as the browser shows it
    return '%d %s %d' % (d.day, d.strftime('%B'), d.year)


def list_lines(views, names=None):
    """The list in the workspace's words (J4), one line per layout."""
    who = lambda person: (names or {}).get(person) or 'a project member'
    if not views: return ['No layouts yet. Map a table once and choose "Remember this layout for the project", or import layouts from a file.']
    lines = []
    for v in views:
        used = '%s, %s' % (who(v['last_used']['person']), _day(v['last_used']['at'])) if v.get('last_used') else 'Not used yet'
        extra = [x for x in ('Retired' if v['state'] == 'retired' else '', 'Needs its connection' if v.get('needs_connection') else '') if x]
        lines.append(' · '.join(x for x in (v['name'], holds(v), columns_line(v), 'Made by %s, %s' % (who(v['made_by']), _day(v['made_at'])),
                                            'Last used: ' + used, *extra) if x))
    return lines


def import_lines(answer):
    """J6: `Layout: Result` per layout of the file."""
    return ['%s: %s' % (o['name'], RESULT.get(o['result']) or 'Not added: ' + (o.get('sentence') or 'it was not valid.')) for o in answer['outcomes']]


def export_bytes(document):
    """The bytes the workspace's Download saves for this export answer (JSON, one-space indent, a final newline)."""
    return (json.dumps(document, indent=1, ensure_ascii=False) + '\n').encode()


class Layouts:
    """layouts/*: list, get, match, save, rename, retire, use_again, keep, update, reconnect, export and import_."""

    def __init__(self, client):
        self.client = client

    def _call(self, operation, body, model):
        answer = _said(lambda: self.client._post('layouts', operation, {'project_id': self.client.project, **body}, retry=True))
        return _checked(model, answer, 'layouts ' + operation)

    def list(self, *, retired=True):
        """This project's layouts, each with who made it and its last use; `retired=False` leaves the retired out."""
        from .models.api import LayoutList
        views = self._call('list', {}, LayoutList)['layouts']
        return views if retired else [v for v in views if v['state'] == 'active']

    def find(self, name):
        """The layout with this name (letter case and spacing aside), or Unavailable with J7-11."""
        for view in self.list():
            if _normal(view['name']) == _normal(name): return view
        raise Unavailable(NO_SUCH % name, code='not-found')

    def get(self, name, *, version=None):
        """One layout by name, at its head or `version`, with its history."""
        from .models.api import LayoutRead
        view = self.find(name)
        return self._call('get', {'asset_id': view['asset_id'], **({'version': version} if version else {})}, LayoutRead)

    def match(self, columns, target=None):
        """The active layouts these column names are (exact, or `how='reordered'`); none is chosen for you."""
        from .models.api import LayoutMatches
        found = self._call('match', {'columns': list(columns)}, LayoutMatches)['matches']
        return [m for m in found if target is None or m['target'] == target]

    def save(self, target, name, columns, fields, *, declarations=None, reading=None, command_id=None):
        """Remember a mapping of these columns as a new layout of the project."""
        from .models.api import LayoutViewAnswer
        layout = {'target': target, 'name': name, 'columns': list(columns), 'mapping': {'fields': dict(fields)}, 'declarations': dict(declarations or {}),
                  'reading': dict(reading or {})}
        return self._call('save', {'command_id': command_id or uuid.uuid4().hex, 'layout': layout}, LayoutViewAnswer)

    def _change(self, operation, name, command_id=None, **extra):
        from .models.api import LayoutViewAnswer
        view = self.find(name)
        return self._call(operation, {'command_id': command_id or uuid.uuid4().hex, 'asset_id': view['asset_id'], 'expected_generation': view['generation'], **extra},
                          LayoutViewAnswer)

    def rename(self, name, new_name, *, command_id=None): return self._change('rename', name, command_id, new_name=new_name)

    def retire(self, name, *, command_id=None):
        """No longer offered for new files; imports that used it keep it in their report."""
        return self._change('retire', name, command_id)

    def use_again(self, name, *, version=None, command_id=None):
        """Offer a retired layout again, or make an earlier version the layout (a new version; nothing is deleted)."""
        return self._change('use-again', name, command_id, **({'version': version} if version else {}))

    def keep(self, connection, table, *, name=None, command_id=None):
        """Keep your saved mapping of a database table as a project layout (named after the connection unless `name`)."""
        from .models.api import LayoutViewAnswer
        body = {'command_id': command_id or uuid.uuid4().hex, 'connection_id': connection, 'key': table, **({'name': name} if name else {})}
        return self._call('keep', body, LayoutViewAnswer)

    def update(self, name, *, command_id=None):
        """Replace a database table layout's mapping with your saved one; the earlier version stays in the history."""
        return self._change('update', name, command_id)

    def reconnect(self, name, connection, table, *, command_id=None):
        """Point a database table layout whose connection left the project at a connection with the same table."""
        return self._change('reconnect', name, command_id, connection_id=connection, key=table)

    def export(self, names=None):
        """The active header layouts (or those named) as one ophiolite.layout-export/1 document."""
        from .models.api import LayoutExport
        return self._call('export', {'names': list(names)} if names else {}, LayoutExport)

    def export_to(self, path, names=None):
        """Write the export as the workspace's Download does; returns the path."""
        path = Path(path)
        path.write_bytes(export_bytes(self.export(names)))
        return path

    def import_(self, source, *, command_id=None):
        """Add the layouts of a layouts file (a path or its parsed document): one outcome each."""
        from .models.api import LayoutImported
        if isinstance(source, (str, Path)):
            try: document = json.loads(Path(source).read_text(encoding='utf-8'))
            except (OSError, ValueError): document = None
        else: document = source
        return self._call('import', {'command_id': command_id or uuid.uuid4().hex, 'document': document}, LayoutImported)


__all__ = ['Layouts', 'columns_line', 'export_bytes', 'holds', 'import_lines', 'list_lines']
