"""E87: a table becomes typed sets in one call — the same journey as the workspace's.

`client.imports.from_table(path, target, mapping=...)` reads the file (it is kept as your private input), previews what
would be added (nothing is kept), and unless `dry_run` starts the run you reviewed and steps it to the end. A target is
wells, well tops, a deviation survey, a point set or time-depth pairs; tops, surveys and time-depth land one set per
well of the table. Without a mapping, a table in Ophiolite's standard layout for the target needs none.

Every answer is checked against its documented shape before it is returned. The words of a review and of a result are
the workspace's (`review_lines`, `unit_words`, `problem_words`): the same file gives the same sentences in both.
"""
import base64
import uuid
from pathlib import Path

from .errors import Refused, VerificationFailed
from .publish import json_bytes
from .well_imports import _checked

FINAL = ('complete', 'complete-with-skipped', 'cancelled', 'incomplete')
STOPPED = ('paused', 'resumable', 'needs-review')
TARGETS = ('wells', 'well-tops', 'deviation-survey', 'point-set', 'time-depth')
NOUNS = {'wells': ('well', 'wells'), 'well-tops': ('top', 'tops'), 'time-depth': ('depth and time pair', 'depth and time pairs'),
         'deviation-survey': ('survey station', 'survey stations'), 'point-set': ('point', 'points')}
SET_NOUN = {'well-tops': 'tops', 'time-depth': 'time-depth', 'deviation-survey': 'deviation survey', 'point-set': 'points'}
SET_HEAD = {'well-tops': 'Tops', 'time-depth': 'Time-depth pairs', 'deviation-survey': 'Deviation surveys', 'point-set': 'Point sets'}
VALUE_WORDS = {'not-numeric': 'is not a number', 'non-finite': 'is not a finite number', 'value-missing': 'is empty',
               'out-of-range': 'is outside the range this field allows', 'not-increasing': 'is not larger than in the row before',
               'text-too-long': 'is too long', 'mixed-units': 'is in another unit than the rows before'}
LINK_REASON = {'unmatched': 'No well named {well} was found, so these are not linked yet.',
               'ambiguous-wellbore': '{well} has more than one wellbore, so these are not linked yet. Choose one from the well.',
               'no-wellbore': '{well} has no wellbore yet, so these are not linked yet.',
               'no-longer-visible': 'The wellbore is no longer visible to you, so these are not linked yet.',
               'linked-elsewhere': 'These are already linked to another wellbore, so they are not linked again.'}


# J10: the sentences a refusal is said in, as the workspace says them (tableImportModel.ts refusal)
UNREADABLE = 'Ophiolite could not read this file as a table. Ask whoever sent it for a CSV or Excel file.'
NOT_YET = 'Ophiolite cannot add this kind of table yet. Keeping a table as it is comes with a later release. Nothing was added.'
CHANGED = 'This import changed since you reviewed it. Review it again.'
RUNNING = 'Another import is still running in this project. Wait for it to finish or stop it.'
NOT_ADMINISTRATOR = 'Only a project administrator can add wells from a table. Ask one to do it.'
NOT_CONTRIBUTOR = 'Only contributors can add this. Ask the project owner for access.'
LOOK_AGAIN = 'This table changed after you looked at it. Open it again from your files.'
NOT_CHECKED = 'This could not be checked. Technical details have the reason.'
SAID = (UNREADABLE, NOT_YET, CHANGED, RUNNING, NOT_ADMINISTRATOR, NOT_CONTRIBUTOR, LOOK_AGAIN, 'Answer the questions about how to read this table first.',
        'No set of this table can be added; correct the rows the check names')
ROOM = r'^This would add [\d,]+ sets? but this project has room for [\d,]+ more\. Remove sets you no longer need, or ask your project administrator\.$'
MOVING = r'^This project cannot be moved yet: '
MIXED = r'^The depths in this series use both (metres|feet) and (metres|feet)\. Fix the file and add it again\.$'  # the mapping's unit and a column's own unit differ


def _from_words(text):
    """A sentence of the packaged mapping words, filled: the mapping engine's refusals are written from them."""
    import re
    from .targets import _words
    return any(re.match('^' + re.sub(r'\\\{\w+\\\}', '.+', re.escape(c['template'])) + '$', text) for c in _words()['codes'].values() if c.get('template'))


def said(error, *, reading=False):
    """What a refused call says (J10); the service's own text stays on the error as server_message."""
    import re
    status, text = error.status or 0, error.server_message or ''
    if status == 413 and error.code != 'capacity-exceeded': return error.message  # the deployment's own limit sentence
    if reading and status == 400: return UNREADABLE
    if text in SAID or re.match(ROOM, text) or re.match(MOVING, text) or re.match(MIXED, text): return text
    if status == 409: return RUNNING if re.search('already running', text) else CHANGED
    if status == 403: return NOT_CONTRIBUTOR
    if status == 400 and text and len(text) <= 500 and not re.search(r'[0-9a-f]{16}|[\x00-\x1f]', text) and _from_words(text): return text
    return NOT_CHECKED


def _said(call, *, reading=False):
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if not error.status or error.code == 'verification-failed': raise
        raise type(error)(said(error, reading=reading), status=error.status, code=error.code, request_id=error.request_id,
                          server_message=error.server_message) from error


def _count(n, one, many):
    return '{:,} {}'.format(n, one if n == 1 else many)


def _label(target, field):
    from .targets import document
    try: found = [f for f in document(target)['fields'] if f['name'] == field]
    except KeyError: found = []
    return found[0]['label'] if found else None


def problem_words(problem, target):
    """A skipped row in words: `Row 17, Measured depth: "17x9.0" is not a number.`"""
    row, code, field = problem.get('row'), problem['code'], problem.get('field')
    at = 'Row {:,}'.format(row) if row else 'A row'
    if code == 'comment-row': return at + ' is a comment row.'
    if code == 'reference-missing' or (field == 'well' and code == 'value-missing'): return at + ': no well.'
    label = _label(target, field) or 'A value'
    what = VALUE_WORDS.get(code)
    if not what: return '%s, %s: this value cannot be added.' % (at, label)
    value = problem.get('value')
    shown = '' if value is None or value == '' else '"%s"' % _shown(value)[:40]
    return '%s, %s: %s.' % (at, label, (shown + ' ' + what) if shown else 'the value ' + what)


def _shown(value):
    # as the browser prints a number: 90.0 is "90"
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def unit_problem_words(problem, target):
    """A set refused whole (a series whose depth goes back, a set over the reader's limit), prefixed by its well."""
    noun = SET_NOUN.get(target, 'set')
    if problem['code'] == 'too-many-rows':
        said = 'The %s for %s have %s rows, more than Ophiolite adds in one set. Split the file.' % (noun, problem.get('well') or 'this table', '{:,}'.format(int(problem['value'])))
    elif problem['code'] == 'not-increasing':
        field = problem.get('field')
        said = 'Row %s%s has a depth that does not increase, so this series was not added. Fix the file and add it again.' % (
            problem.get('row'), ', ' + (_label(target, field) or '') if field and field not in ('md', 'depth') else '')
    else:
        said = problem_words(problem, target).rstrip('.') + ', so this series was not added. Fix the file and add it again.'
    return (problem['well'] + ': ' if problem.get('well') else '') + said


def review_lines(review):
    """A preview of sets in words, as the workspace's review shows it."""
    target = review['target']
    if target == 'wells':  # one line of counts, then each skipped row's reasons (the workspace's wells review)
        c = review['counts']
        from .well_imports import words  # E42a's reasons, as the wells import says them
        return ['{:,} wells to create · {:,} already here · {:,} rows skipped'.format(c['create'], c['already_here'], c['skipped'])] + [
            '  Row {:,}{}: {}'.format(s['source_row'], ' (%s)' % s['row_key'] if s.get('row_key') else '', words(s)) for s in review['skipped']]
    landing = [u for u in review['units'] if u['action'] == 'land']
    sets = lambda n: _count(n, 'set', 'sets')
    linked = [u for u in review['units'] if u.get('well') is not None]
    missing = [u for u in linked if not u.get('wellbore')]
    lines = ['%s to add: %s%s' % (SET_HEAD.get(target, target), sets(len(landing)),
                                  ' (' + ', '.join('%s: %s' % (u.get('well') or u['label'], _count(u['rows'], 'row', 'rows')) for u in landing) + ')' if landing else ''),
             'Already here: ' + sets(review['counts']['already_here']), 'Skipped rows: {:,}'.format(review['counts']['skipped_rows'])]
    lines += ['  ' + problem_words(p, target) for p in review['skipped']] + ['  Row %d: no well.' % r for r in review['no_well']]
    lines += ['Not added: ' + unit_problem_words(p, target) for p in review['skipped_units']]
    if linked: lines.append('Wells found: %d of %d' % (len(linked) - len(missing), len(linked)))
    if missing:
        lines.append('Wells not found: %s. %s %s are added without a link to a well.' % (', '.join(u['well'] for u in missing), 'Its' if len(missing) == 1 else 'Their', NOUNS[target][1]))
    lines.append('This adds {:,} of the {} left in this project.'.format(len(landing), _count(review['room']['uploads'], 'upload', 'uploads')))
    return lines


def unit_words(unit, target, well=None, rows=None):
    """One set of a run: (its name, what became of it). `well` and `rows` come from the preview the run started from."""
    one, many = NOUNS.get(target, ('row', 'rows'))
    name = '%s %s' % (well or unit['label'], SET_NOUN.get(target, 'set'))
    amount = '' if rows is None else ': ' + _count(rows, one, many)
    if unit.get('receipt') == 'reused': result = 'Already here'
    elif unit.get('receipt') == 'removed': result = 'Not added: it was removed after it was added, so it is not added again.'
    elif unit['outcome'] == 'skipped':
        result = 'Not added: a set with this name and other content is already here.' if unit.get('reason') == 'same-name-other-content' \
            else 'Not added: Ophiolite could not add this set. Technical details have the reason.'
    elif unit['outcome'] == 'planned': result = 'Not added yet'
    elif unit.get('wellbore'): result = 'Added%s, linked to well %s' % (amount, unit['wellbore']['name'])
    elif unit.get('reason') in LINK_REASON: result = 'Added%s. %s' % (amount, LINK_REASON[unit['reason']].format(well=well or unit['label']))
    else: result = 'Added%s%s' % (amount, ' for well ' + well if target == 'time-depth' and well else '')
    return name, result


def result_lines(run, review=None):
    """A run in words: its state, then one line per set (as the workspace's result table) or the wells' counts."""
    lines = [run['words']] + ([run['reason']] if run.get('reason') and run['state'] in STOPPED + ('cancelled',) else [])
    if run['target'] == 'wells':
        c = run['counts']
        return lines + ['{:,} wells added · {:,} already here · {:,} rows skipped'.format(c['created'], c['already_here'], c['skipped'])]
    planned = {u['unit']: u for u in (review or {}).get('units', [])}
    for unit in run['units']:
        name, result = unit_words(unit, run['target'], planned.get(unit['unit'], {}).get('well'), planned.get(unit['unit'], {}).get('rows'))
        lines.append('%s: %s' % (name, result))
    import re
    refused = lambda p: re.sub(r'^Row', 'row', re.sub(r', so this series was not added\. Fix the file and add it again\.$', '.', unit_problem_words({**p, 'well': None}, run['target'])))
    return lines + ['%s %s: Not added: %s' % (p.get('well') or '', SET_NOUN.get(run['target'], 'set'), refused(p)) for p in (review or {}).get('skipped_units', [])]


def parse_mapping(given, columns=None):
    """--map FIELD=COLUMN pairs (repeat, or join with commas) as {field: column}; a field given twice is a list (a point
    set's attributes). Column names are the table's own and may hold spaces."""
    import re
    fields = {}
    for text in given or ():
        for pair in re.split(r',(?=\s*[A-Za-z_][A-Za-z0-9_]*\s*=)', text):
            field, eq, column = pair.partition('=')
            field, column = field.strip(), column.strip()
            if not (field and eq and column): raise Refused('Give each column as FIELD=COLUMN, for example --map name=Formation,md=Top MD (m).')
            if columns is not None and column not in columns:
                raise Refused('This table has no column named %r. Its columns: %s.' % (column, ', '.join(columns)))
            if field in fields: fields[field] = (fields[field] if isinstance(fields[field], list) else [fields[field]]) + [column]
            else: fields[field] = column
    return fields


class Imports:
    """table-imports/*: read, preview, start, step, status, list, pause, resume, cancel, and `from_table` for all of it."""

    def __init__(self, client):
        self.client = client

    def _call(self, operation, body, *models):
        answer = _said(lambda: self.client._post('table-imports', operation, body, retry=True))
        for model in models:
            try: return _checked(model, answer, 'table import ' + operation)
            except VerificationFailed: continue
        raise VerificationFailed('The table import %s answered outside its documented shape.' % operation)

    def read(self, source, *, name=None, reading=None):
        """Keep the file as your private input and say how it was read (`context.decisions`), its columns and the
        standard layouts its header is. `reading` asks again: sheet, header_row, delimiter, decimal_mark, encoding."""
        from .models.api import TableImportRead
        raw = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
        name = name or (Path(source).name if isinstance(source, (str, Path)) else None)
        if not name: raise Refused('Name the file: read(data, name="tops.csv").')
        meta = {'project_id': self.client.project, 'name': name, 'bytes': len(raw), **({'reading': reading} if reading else {})}
        headers = {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json_bytes(meta)).decode()}
        return _checked(TableImportRead, _said(lambda: self.client._post_bytes('table-imports', 'read', raw, extra_headers=headers), reading=True), 'table import read')

    def _body(self, read, target, mapping, *, reading=None, well=None, separate=None, authority=None):
        if target not in TARGETS: raise Refused('Say what the table holds: one of %s.' % ', '.join(TARGETS))
        mapping = {**mapping, 'schema_digest': read['schema_digest']}
        if target == 'wells': mapping.setdefault('entity', 'well')
        return {'target': target, 'input_id': read['input_id'], 'mapping': mapping, **({'reading': reading} if reading else {}),
                **({'well': well} if well else {}), **({'separate': list(separate)} if separate else {}), **({'authority': authority} if authority else {})}

    def preview(self, read, target, mapping, **options):
        """What a start would add (sets per well, rows skipped with their reasons, wells found); nothing is kept."""
        from .models.api import TableSetsPreviewAnswer, TableWellsPreviewAnswer
        return self._call('preview', self._body(read, target, mapping, **options), TableSetsPreviewAnswer, TableWellsPreviewAnswer)

    def start(self, read, target, mapping, *, preview_digest, audience=(), command_id=None, **options):
        """Add what the preview with this digest said; the same command id returns the same run. Run it with `run`."""
        if not preview_digest: raise Refused('Start the import you reviewed: give the preview_digest of its preview.')
        body = {**self._body(read, target, mapping, **options), 'preview_digest': preview_digest, 'audience': list(audience),
                'command_id': command_id or uuid.uuid4().hex}
        return self._run('start', body)

    def _run(self, operation, body):
        from .models.api import TableSetImport, TableWellsImport
        return self._call(operation, body, TableSetImport, TableWellsImport)

    def step(self, ident): return self._run('step', {'id': ident})
    def status(self, ident): return self._run('status', {'id': ident})
    def pause(self, ident): return self._run('pause', {'id': ident})
    def resume(self, ident): return self._run('resume', {'id': ident})

    def cancel(self, ident):
        """Stop an unfinished run (the person who started it, or a project administrator); sets already added stay."""
        return self._run('cancel', {'id': ident})

    def list(self, target=None):
        from .models.api import TableImportsListAnswer
        return self._call('list', {**({'target': target} if target else {})}, TableImportsListAnswer)['imports']

    def run(self, ident, *, progress=None, max_steps=100000):
        """Step until the run is finished, cancelled or paused, and return its last answer. Safe to call again after an
        interruption, from any process."""
        for _ in range(max_steps):
            answer = self.step(ident)
            if progress: progress(answer)
            if answer['state'] in FINAL or answer['state'] in STOPPED: return answer
        raise VerificationFailed('The import did not finish in %d steps; run it again to continue.' % max_steps)

    def from_table(self, source, target, mapping=None, *, declarations=None, name=None, reading=None, well=None, separate=None,
                   authority=None, audience=(), command_id=None, dry_run=False, progress=None, on_start=None):
        """Read, preview and (unless dry_run) start and run: returns {'read', 'preview', 'run'} ('run' is None for a dry
        run, which adds nothing). `mapping` is {field: column}; omitted, the table must be in the target's standard layout."""
        read = self.read(source, name=name, reading=reading)
        if read.get('columns') is None: raise Refused('Answer the questions about how to read this table first: give reading=%s.' % sorted(
            d['field'] for d in read['context'].get('decisions', []) if d.get('status') == 'needs-decision'))
        columns = [c['name'] for c in read['columns']]
        layout = next((l for l in read.get('layouts') or [] if l['target'] == target), None)
        if mapping is None and layout is None:
            raise Refused('Say which column holds each value (mapping={field: column}); this table is not in the standard layout. Its columns: %s.' % ', '.join(columns))
        fields = dict(layout['fields']) if mapping is None else dict(mapping)
        for column in [c for v in fields.values() for c in (v if isinstance(v, list) else [v])]:
            if column not in columns: raise Refused('This table has no column named %r. Its columns: %s.' % (column, ', '.join(columns)))
        declared = {**((layout or {}).get('declarations') or {}), **(declarations or {})}
        body = {'fields': fields, **(declared if target == 'wells' else {'declarations': declared})}
        options = {'reading': reading, 'well': well, 'separate': separate, 'authority': authority}
        review = self.preview(read, target, body, **options)
        if dry_run: return {'read': read, 'preview': review, 'run': None}
        started = self.start(read, target, body, preview_digest=review['preview_digest'], audience=audience, command_id=command_id, **options)
        if on_start: on_start(started)  # its id, before the first step: an interrupted run is resumed with run(id)
        return {'read': read, 'preview': review, 'run': self.run(started['id'], progress=progress)}
