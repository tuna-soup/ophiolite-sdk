"""E88: the wells your files name, in Python — the same list, answers and go back as the workspace's.

`client.well_names.proposals(runs)` lists the names that one to fifty finished folder uploads and table imports wrote
for wells and wellbores, and what each matches among the wells you can read; it changes nothing. `accept` acts on that
list (its `digest`): `create_all` creates every row nothing readable matches as a provisional well, `link_exact_only`
links only the rows whose every name has its one readable match (exact, or a reviewed other name) and creates nothing,
`create`, `is_` and `skip` answer rows by name. `go_back(runs)` removes what the accepts of that set created while nothing
else refers to it; the files stay. `runs` is one id or a sequence of ids (a str is one id, never its characters).

A refusal keeps the server's sentence (the browser's words): what happened, who can change it and what to do next.
"""
import os
import uuid

from .errors import Refused
from .well_imports import _checked

# the refusals well-names answers in words (Integration E88 strategy J4) and the run and entity refusals it passes on
CODES = ('runs-count', 'run-not-finished', 'run-cancelled', 'edit-required', 'list-changed', 'name-unusable', 'entity-unavailable',
         'well-appeared', 'several-match', 'too-many-wells', 'too-many-names', 'list-removed', 'list-accepted', 'other-runs',
         'wells-referred', 'not-yours', 'wells-changed', 'unknown-run', 'entity-removed')
BOTH = 'Choose one: --create-all or --link-exact-only.'
LEAD = 'Nothing is created until you press a button. You can undo it until other data refers to the wells.'
PROVISIONAL = 'Provisional wells have no registry number yet. You can add one later.'
EVIDENCE = 3  # J1: up to three evidence lines a row


def _runs(runs):
    """One id or a sequence of ids, as a list; a str is one id."""
    if isinstance(runs, str): return [runs]
    return list(runs)


def _said(call):
    """A refusal of well-names in the server's own sentence; any other error as the transport raised it."""
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if error.code not in CODES or not error.server_message: raise
        raise type(error)(error.server_message, status=error.status, code=error.code, request_id=error.request_id, remedy=error.remedy,
                          docs=error.docs, server_message=error.server_message, details=error.details) from error


def _n(n, one, many):
    return '%d %s' % (n, one if n == 1 else many)


def missing(proposal):
    """The rows that name a well or wellbore nothing you can read is called: the ones a create would make."""
    return [r for r in proposal['rows'] if any(g['answer'] == 'listed' for g in r['groups'])]


def counts_line(proposal):
    """J1's counts line (`21 files and 2 tables name 9 wells that are not in this project.`), or None when every name
    is a well you can read. Counts are distinct files and tables."""
    rows = missing(proposal)
    if not rows: return None
    sources = {(m['origin'].get('run'), m['origin'].get('file'), 'unit' in m['origin']) for r in rows for g in r['groups'] for m in g['mentions']}
    files, tables = sum(1 for s in sources if not s[2]), sum(1 for s in sources if s[2])
    said = ' and '.join(x for x in (files and _n(files, 'file', 'files'), tables and _n(tables, 'table', 'tables')) if x)
    return '%s %s %s that %s not in this project.' % (said, 'names' if files + tables == 1 else 'name', _n(len(rows), 'well', 'wells'),
                                                      'is' if len(rows) == 1 else 'are')


def evidence(mention):
    """Where a file names it, in words (J1)."""
    o, kind = mention['origin'], 'wellbore' if mention['level'] == 'wellbore' else 'well'
    if 'unit' in o:
        spans = o.get('rows') or []
        rows = ', '.join(('row %d' % a) if a == b else ('rows %d to %d' % (a, b)) for a, b in spans)
        return 'The Well column of %s names the %s%s.' % (os.path.basename(o.get('file') or ''), kind, ', ' + rows if rows else '')
    return 'The LAS header of %s names the %s "%s".' % (os.path.basename(o.get('file') or ''), kind, mention['value'])


def row_lines(row):
    lines = [row['name']]
    for g in row['groups']:
        files = {(m['origin'].get('run'), m['origin'].get('file')) for m in g['mentions'] if 'unit' not in m['origin']}
        tables = {(m['origin'].get('run'), m['origin'].get('file')) for m in g['mentions'] if 'unit' in m['origin']}
        where = ' and '.join(x for x in (files and _n(len(files), 'file', 'files'), tables and _n(len(tables), 'table', 'tables')) if x)
        lines.append('  Named as a %s in %s.' % (g['level'], where))
        if g['answer'] == 'link': lines.append('  A %s you can read has this name.' % g['level'])
        if g['answer'] == 'choose':
            lines.append('  %d %ss you can read are called %s. Choose which one.' % (len(g['candidates']), g['level'], row['name']))
    shown = [m for g in row['groups'] for m in g['mentions']]
    lines += ['  ' + evidence(m) for m in shown[:EVIDENCE]]
    if len(shown) > EVIDENCE: lines.append('  And %d more.' % (len(shown) - EVIDENCE))
    return lines


def list_lines(proposal):
    """The list in the workspace's words (J1): heading, counts, then one block per row."""
    if not proposal['rows']: return ['No file in these runs names a well that needs an answer.']
    lines = ['Wells named in your files'] + [x for x in (counts_line(proposal),) if x] + [LEAD]
    for row in proposal['rows']: lines += row_lines(row)
    if missing(proposal): lines.append(PROVISIONAL)
    return lines


def result_line(accepted, names=None):
    """J2: what one accept did. `names` {entity_id: name} words the other names it recorded."""
    c = accepted['created']
    said = ['Created %s and %s.' % (_n(c['wells'], 'well', 'wells'), _n(c['wellbores'], 'wellbore', 'wellbores')),
            'Linked %s.' % _n(accepted['linked'], 'file or sheet', 'files and sheets')]
    seen = []
    for a in accepted['aliases']:
        target = (names or {}).get(a['entity_id'])
        if target and (a['as_written'], target) not in seen:
            seen.append((a['as_written'], target)); said.append('%s is now another name for %s.' % (a['as_written'], target))
    said.append('%d not linked.' % accepted['unlinked'] if accepted['unlinked'] else '0 left.')
    return ' '.join(said)


def went_back_line(back):
    """J3: what go back removed."""
    if back['state'] == 'nothing': return 'Nothing to remove: the wells from these files were removed already.'
    r = back['removed']
    return 'Removed %s and %s. The files are not linked to a well.' % (_n(r['wells'], 'well', 'wells'), _n(r['wellbores'], 'wellbore', 'wellbores'))


class WellNames:
    """well-names/*: propose, accept, aliases and go-back."""

    def __init__(self, client):
        self.client = client

    def _call(self, operation, body, model):
        answer = _said(lambda: self.client._post('well-names', operation, body, retry=True))
        return _checked(model, answer, 'well names ' + operation)

    def proposals(self, runs):
        """The list over these runs (1 to 50, each counted once); reads and writes nothing."""
        from .models.api import WellNamesProposal
        return self._call('propose', {'runs': _runs(runs)}, WellNamesProposal)

    def _row(self, proposal, name):
        """The row a name answers: as written in a file, as listed, or normalised."""
        for r in proposal['rows']:
            if name in (r['normalised'], r['name']) or any(m['value'] == name for g in r['groups'] for m in g['mentions']): return r['normalised']
        raise Refused('No row of this list is called %s. Open the list again to see its names.' % name)

    def accept(self, runs, *, digest, create=None, create_all=False, is_=None, skip=(), link_exact_only=False, command_id=None):
        """Act on the list with this digest. `create` names rows to create, `is_` {name: entity id} says a row is a well
        or wellbore you have (its spelling stays as another name for it), `skip` answers rows Not this one. The same
        command id returns the same answer."""
        from .models.api import WellNamesAccepted
        if create_all and link_exact_only: raise Refused(BOTH)
        if not digest: raise Refused('Accept the list you reviewed: give the digest of its proposals.')
        runs, body = _runs(runs), {}
        if create or is_ or skip or link_exact_only:
            proposal = self.proposals(runs)
            if create: body['create'] = sorted({self._row(proposal, n) for n in create})
            if is_: body['is'] = {self._row(proposal, n): getattr(e, 'entity_id', e) for n, e in is_.items()}
            if skip: body['skip'] = sorted({self._row(proposal, n) for n in skip})
            if link_exact_only: body['link'] = [r['normalised'] for r in proposal['rows'] if r['groups'] and all(g['answer'] == 'link' for g in r['groups'])]
        if create_all: body['create'] = 'all'
        body.update({'runs': runs, 'digest': digest, 'command_id': command_id or uuid.uuid4().hex})
        return self._call('accept', body, WellNamesAccepted)

    def aliases(self, entity):
        """The other names of a well or wellbore you can read: as written, who answered and when."""
        from .models.api import WellAliases
        return self._call('aliases', {'entity_id': getattr(entity, 'entity_id', entity)}, WellAliases)['aliases']

    def go_back(self, runs):
        """Remove what the accepts of this set of runs created, while nothing else refers to it. The files stay."""
        from .models.api import WellNamesWentBack
        return self._call('go-back', {'runs': _runs(runs)}, WellNamesWentBack)


__all__ = ['WellNames', 'counts_line', 'list_lines', 'result_line', 'went_back_line']
