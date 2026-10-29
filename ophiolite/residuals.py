"""E119b slice 2 (C4): residuals at wells, a residual per top between a surface and the tops of your selected wellbores,
computed on this computer.

`prepare(client, selection, surface, formation)` binds a saved well set (E119a) before anything is computed. It reads,
as you, the set, every tops version linked as a whole to each member wellbore (following the association pages to the
end), the surface and the trajectories, and refuses with one sentence per defect:
- two tops versions linked to one wellbore;
- no top of the formation on any selected wellbore;
- no member with a trajectory;
- more than 32 distinct versions;
- more than 10 000 rows needed (one per top of the formation, one per member with none);
- a tops depth datum missing, unknown or not the trajectory's, or tops depths not in metres;
- every refusal of `client.well_sets.bind` (E119a).
It returns the four inputs of a residual procedure (`selection`, `tops`, `surface`, `trajectories`, the trajectories in
member order), downloaded, for `client.procedure_run`. The Gateway checks the same bindings again when the run is
reported and when its result is published.

`compute` makes the `well-residual/1` document from typed data: for each member and each top named the formation (in
md order, ties in file order, numbered from 1), E119a's `crossings` and `nearest` pick the crossing nearest the top and
the residual is the top's measured depth minus the crossing's, in metres; otherwise the row names a reason. `rows` is
that rule for one member. The reference procedure, *Residual at wells*, ships in this package (`reference_path()`); its
entry reads its inputs' files with `from_inputs`. Nothing here contacts a server except `prepare` and `run`.
"""
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import geometry
from .errors import Refused
from .readers import ReadRefused, tables, text

SELECTION, TOPS, SURFACE, TRAJECTORY = 'well-set/1', 'well-tops-csv/1', 'esri-ascii-grid/1', 'deviation-csv/1'
OUTPUT = 'well-residual/1'
SCHEMA = 'ophiolite.well-residual/1'
SETTINGS = ('formation', 'display_unit')  # D7: the only settings; the crossing choice and the chord are not settings
MAX_INPUTS = 32
MAX_CROSSINGS = 64  # a row lists at most this many crossings; more is the reason many-crossings
MAX_ROWS = 10_000  # a result has at most this many rows (Connectors well_residual.MAX_ROWS); `prepare` refuses more
VOCABULARY = Path(__file__).resolve().parent / 'contracts' / 'vocabulary' / 'v1' / 'well-residual-reasons.json'
REFERENCE = Path(__file__).resolve().parent / 'reference' / 'residual-at-wells'

# How each of E119a's crossing reasons (contracts/geometry/v1/trajectory.py REASONS) is named in a residual row, one to
# one; the parity test (PG tests/test_residual_reasons_parity.py) holds these keys to every holder of the two lists.
FROM_CROSSINGS = {'grazing': 'grazing', 'along-surface': 'along-surface', 'uncertain': 'uncertain', 'no-surface-data': 'no-surface-data',
                  'ends-above': 'ends-above', 'starts-below': 'starts-below', 'no-trajectory': 'no-trajectory'}
OWN = ('no-top', 'many-crossings')  # the residual-only reasons
# The reasons whose row carries `between`. E119a's `no-surface-data` has an interval, but a residual row drops it (the
# vocabulary's sentence names no depths), so the row's `between` is null.
BETWEEN = ('grazing', 'along-surface', 'uncertain', 'many-crossings')

SENTENCES = {
    'tops-twice': 'Two tops sets are linked to {wellbore}; keep one link.',
    'no-top': 'No selected wellbore has a top named "{formation}".',
    'no-top-unnamed': 'No selected wellbore has a top of the chosen formation.',
    'no-trajectory': 'No selected wellbore has a trajectory, so there is nothing to intersect.',
    'too-many': 'This selection needs {n} versions; a run takes at most 32.',
    'unit': 'Member {n}: the depths of its tops are not in metres.',
    'datum-missing': 'Member {n}: its tops do not declare the depth datum they are measured from; declare it as the trajectory does ({datum}).',
    'datum-differs': 'Member {n}: its tops are measured from {tops} but its trajectory from {trajectory}; a residual needs one depth datum.',
    'formation': 'Name the formation the surface represents (1 to 64 characters).',
    'display-unit': 'Show depths in m or ft.',
    'version': 'Name {what} as @ASSET:REVISION.',
    'local': 'Residual at wells runs on project versions; use ophiolite residuals run.',
}


def limits(rows=None, size=None):
    """D-36: the sentence a result over either limit is refused with, naming its size as far as it is known: rows at
    binding, rows and bytes when written. Connectors' `well_residual.limits`, the same text (tested equal)."""
    told = ['{:,} {}{}'.format(n, word, '' if n == 1 else 's').replace(',', ' ') for n, word in ((rows, 'row'), (size, 'byte')) if n is not None]
    return 'A residual result has 1 to 10 000 rows and is at most 8 MiB' + ('; this one has ' + ' and '.join(told) if told else '') + '.'


def _sentence(key, **words):
    return Refused(SENTENCES[key].format(**words), details={'reason': 'residuals:' + key})


def reference_path():
    """The folder of the shipped reference procedure, *Residual at wells* (procedure.json and entry.py)."""
    return REFERENCE


def reasons():
    """{key: sentence} of the nine reasons a residual row gives (the packaged vocabulary, in order)."""
    document = json.loads(VOCABULARY.read_text(encoding='utf-8'))
    return {k['key']: k['sentence'] for k in document['sections'][0]['keys']}


def sentence(row):
    """The sentence a person reads for a row that gives a reason; <a> and <b> are its `between` to the centimetre."""
    text, between = reasons()[row['reason']], row['between']
    if between is not None: text = text.replace('<a>', '%.2f' % between[0]).replace('<b>', '%.2f' % between[1])
    return text


# ---------------------------------------------------------------- computing (no server)

def _fold(value):
    return value.strip().casefold() if isinstance(value, str) else ''


def required(tops, formation):
    """[(occurrence, index, md)] of the tops named FORMATION exactly: md order, ties in file order, numbered from 1."""
    named = sorted((t['md'], i) for i, t in enumerate(tops) if t['name'] == formation and t.get('md') is not None)
    return [(k, i, md) for k, (md, i) in enumerate(named, 1)]


def needed(members, tops, formation):
    """The rows a run makes (adhoc-d17, S4-D5): per member, one for each top named FORMATION in TOPS {wellbore: typed
    tops} (the occurrences), or one `no-top` row when it has none."""
    return sum(len(required(tops.get(m['wellbore']) or [], formation)) or 1 for m in members)


def _row(wellbore, occurrence, top, trajectory, crossings=(), used=None, residual=None, reason=None, between=None):
    return {'wellbore': wellbore, 'occurrence': occurrence, 'top': top, 'trajectory': trajectory,
            'crossings': [{'md': c['md'], 'low': c['low'], 'high': c['high']} for c in crossings], 'used': used, 'residual': residual,
            'unit': 'm', 'reason': reason, 'between': list(between) if between is not None else None}


def _between(found, reason, stations):
    for r in found['rows']:
        if r['reason'] == reason and r['between'] is not None: return r['between']
    return [stations[0]['md'], stations[-1]['md']]  # a block the geometry names without a row: the whole path


def rows(wellbore, tops_ref, tops, trajectory_ref, survey, found, formation):
    """The rows of one member: TOPS_REF {asset_id, revision} and TOPS (typed tops, or None for a member without a tops
    version), TRAJECTORY_REF and SURVEY ({'context', 'stations'}, or None), FOUND the geometry's `crossings` result for
    that path (None without one)."""
    wanted = required(tops or [], formation)
    if not wanted: return [_row(wellbore, 0, None, trajectory_ref, reason='no-top')]
    out = []
    for k, index, md in wanted:
        top = {'asset_id': tops_ref['asset_id'], 'revision': tops_ref['revision'], 'index': index, 'md': md}
        if survey is None:
            out.append(_row(wellbore, k, top, None, reason=FROM_CROSSINGS['no-trajectory'])); continue
        listed = found['crossings']
        if len(listed) > MAX_CROSSINGS:
            out.append(_row(wellbore, k, top, trajectory_ref, reason='many-crossings', between=[listed[0]['md'], listed[-1]['md']])); continue
        pick = geometry.contract().nearest(found, md)
        if pick['reason'] is None:
            crossing = pick['crossing']
            out.append(_row(wellbore, k, top, trajectory_ref, listed, pick['index'], md - crossing['md'])); continue
        reason = FROM_CROSSINGS[pick['reason']]
        between = _between(found, pick['reason'], survey['stations']) if reason in BETWEEN else None
        out.append(_row(wellbore, k, top, trajectory_ref, listed, reason=reason, between=between))
    return out


def compute(members, tops, trajectories, grid, surface, formation, display_unit='m', *, max_eval=None):
    """The `well-residual/1` document. MEMBERS: the well set's members in order; TOPS: {wellbore: ({asset_id, revision},
    [typed tops])}; TRAJECTORIES: {(asset_id, revision): {'context', 'stations'}}; GRID: the surface's {'context',
    'values'}; SURFACE: its {asset_id, revision}. Raises Refused when a member's path cannot be placed."""
    module, out = geometry.contract(), []
    for m in members:
        ref, given = tops.get(m['wellbore'], (None, None))
        path = m.get('trajectory')
        survey = trajectories[(path['asset_id'], path['revision'])] if path is not None else None
        found = None
        if survey is not None and required(given or [], formation):
            found = module.crossings(survey, m['frame'], grid, **({} if max_eval is None else {'max_eval': max_eval}))
            if found['refusal'] is not None:
                raise Refused(module.REFUSALS[found['refusal']], details={'reason': 'geometry:' + found['refusal']})
        trajectory_ref = {'asset_id': path['asset_id'], 'revision': path['revision']} if path is not None else None
        out.extend(rows(m['wellbore'], ref, given, trajectory_ref, survey, found, formation))
    return {'schema': SCHEMA, 'correspondence': {'formation': formation}, 'display_unit': display_unit,
            'surface': {'asset_id': surface['asset_id'], 'revision': surface['revision']}, 'rows': out}


def summary(document):
    """The counts a reader states: rows, computed, not computed, members and members with no computed row."""
    rows_, computed = document['rows'], sum(r['residual'] is not None for r in document['rows'])
    members, placed = {r['wellbore'] for r in rows_}, {r['wellbore'] for r in rows_ if r['residual'] is not None}
    return {'type': 'well-residual', 'count': len(rows_), 'computed': computed, 'not_computed': len(rows_) - computed,
            'members': len(members), 'members_not_computed': len(members - placed), 'formation': document['correspondence']['formation'],
            'display_unit': document['display_unit']}


# ---------------------------------------------------------------- the entry's reading of its input files

class Unreadable(ValueError):
    """An input file the reference procedure cannot read in the readers' grammar (E128 s4: the readers' sentence)."""


def _parse(parse, kind, path, declared):
    try:
        return parse(kind, Path(path).read_bytes(), declared)
    except ReadRefused as error:
        raise Unreadable(str(error)) from error


def _columns(table):
    return {c.strip().lower(): i for i, c in enumerate(table.columns)}


def read_tops(path):
    """[{name, md}] of a well tops CSV, in file order (the index a residual row names). A view over ophiolite.readers."""
    table = _parse(tables._parse, TOPS, path, None)
    at = _columns(table)
    return [{'name': r[at['name']], 'md': r[at['md']]} for r in table.rows]


SURVEY_CONTEXT = ('type', 'depth_unit', 'angle_unit', 'azimuth_reference', 'depth_datum')


def read_survey(path, declared):
    """{'context', 'stations'} of a deviation survey CSV with its declarations. A view over ophiolite.readers."""
    table = _parse(tables._parse, TRAJECTORY, path, declared)
    at = _columns(table)
    cell = lambda row, name: row[at[name]] if name in at else None  # noqa: E731
    return {'context': {k: table.context[k] for k in SURVEY_CONTEXT},
            'stations': [{'md': cell(r, 'md'), 'inclination': cell(r, 'inclination'), 'azimuth': cell(r, 'azimuth'),
                          'tvd': cell(r, 'tvd')} for r in table.rows]}


GRID_CONTEXT = ('type', 'crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum', 'registration', 'row_order',
                'ncols', 'nrows', 'cell_size', 'x_first_center', 'y_first_center')


def read_grid(path, declared):
    """{'context', 'values'} of an ESRI ASCII grid with its declarations: row 0 northmost, a NODATA cell None. A view over
    ophiolite.readers."""
    grid = _parse(text._parse, SURFACE, path, declared)
    return {'context': {k: grid.context[k] for k in GRID_CONTEXT}, 'values': [v for row in grid.cells for v in row]}


def from_inputs(inputs, settings):
    """The document a residual procedure's entry returns, from its four inputs (`LocalVersion`s naming their project
    versions; tops name their wellbore) and its settings."""
    given = [v for slot in ('selection', 'tops', 'surface', 'trajectories') for v in inputs.get(slot, [])]
    if not given or any(v.asset_id is None or v.revision is None for v in given) or any(v.wellbore is None for v in inputs.get('tops', [])):
        raise Refused(SENTENCES['local'])
    members = json.loads(Path(inputs['selection'][0].path).read_text(encoding='utf-8'))['members']
    tops = {v.wellbore: ({'asset_id': v.asset_id, 'revision': v.revision}, read_tops(v.path)) for v in inputs.get('tops', [])}
    paths = {(v.asset_id, v.revision): read_survey(v.path, v.declared) for v in inputs.get('trajectories', [])}
    surface = inputs['surface'][0]
    return compute(members, tops, paths, read_grid(surface.path, surface.declared), {'asset_id': surface.asset_id, 'revision': surface.revision},
                   settings['formation'], settings['display_unit'])


# ---------------------------------------------------------------- binding on this computer (talks to the server)

@dataclass
class Prepared:
    """What `prepare` bound: the run's inputs per slot (downloaded `ProjectInput`s) and its settings as name=value."""
    inputs: dict
    settings: list
    members: list = field(default_factory=list)
    work: str | None = None

    def discard(self):
        if self.work: shutil.rmtree(self.work, ignore_errors=True)


def _version(value, what):
    from .procedures import PROJECT_INPUT
    if isinstance(value, str):
        found = PROJECT_INPUT.match(value)
        if found is None: raise _sentence('version', what=what)
        return found.group(1), found.group(2)
    if isinstance(value, dict): return value['asset_id'], value['revision']
    if isinstance(value, (tuple, list)) and len(value) == 2: return tuple(value)
    return value.asset_id, value.revision


def _readable_formation(formation):
    from .well_sets import _readable as readable
    return readable(formation)


def _readable(name):
    from .well_sets import UNNAMED_WELLBORE, _readable as readable
    return readable(name) or UNNAMED_WELLBORE


def linked(client, wellbores):
    """{wellbore: [(asset_id, revision)]}: the tops versions linked as a whole (no `row`) to each wellbore that you may
    read, from every page of `entities/associations`, and {wellbore: its name}."""
    out, names, cursor, seen = {b: [] for b in wellbores}, {}, None, set()
    while True:
        page = client._entities('associations', {'kind': 'wellbore', 'profile': TOPS, 'limit': 100, **({'cursor': cursor} if cursor else {})})
        for item in page['items']:
            bore = (item.get('entity') or {}).get('entity_id')
            if bore not in out or item.get('row') or (item.get('association') or {}).get('row'): continue  # E119b s4: the Gateway sends "row": null for a whole-file link
            pair = (item['asset_id'], item['revision'])
            if pair not in out[bore]: out[bore].append(pair)
            names[bore] = (item.get('entity') or {}).get('name')
        cursor = page.get('next_cursor')
        if not cursor: return out, names
        if cursor in seen: raise Refused('The association pages repeat a cursor; nothing was computed.')
        seen.add(cursor)


def prepare(client, selection, surface, formation, *, display_unit='m'):
    """Bind SELECTION (a saved well set version: '@ASSET:REVISION', {asset_id, revision} or a receipt) and SURFACE (the
    same) for FORMATION before anything is computed; a `Prepared` with the four inputs, or Refused with one sentence."""
    if not isinstance(formation, str) or not 1 <= len(formation) <= 64: raise _sentence('formation')
    if display_unit not in ('m', 'ft'): raise _sentence('display-unit')
    chosen, grid_ref = _version(selection, 'the selection'), _version(surface, 'the surface')
    well_set = client.well_sets.read(*chosen)
    members = [dict(m) for m in well_set.members]
    by_bore, names = linked(client, [m['wellbore'] for m in members])
    for i, m in enumerate(members):
        if len(by_bore[m['wellbore']]) > 1: raise _sentence('tops-twice', wellbore=_readable(names.get(m['wellbore'])))
    typed = {pair: client.read_data(*pair) for pairs in by_bore.values() for pair in pairs}
    if not any(required(typed[by_bore[m['wellbore']][0]].tops, formation) for m in members if by_bore[m['wellbore']]):
        name = _readable_formation(formation)  # E119b s5 6-12: a readable name, never the raw key
        if name is None: raise Refused(SENTENCES['no-top-unnamed'], details={'reason': 'residuals:no-top'})
        raise _sentence('no-top', formation=name)
    rows_needed = needed(members, {m['wellbore']: typed[by_bore[m['wellbore']][0]].tops for m in members if by_bore[m['wellbore']]}, formation)
    if rows_needed > MAX_ROWS: raise Refused(limits(rows_needed), details={'reason': 'residuals:row-count'})  # D-36: rows only, nothing written yet
    paths = [(m['trajectory']['asset_id'], m['trajectory']['revision']) for m in members if m['trajectory'] is not None]
    if not paths: raise _sentence('no-trajectory')
    tops_pairs = [by_bore[m['wellbore']][0] for m in members if by_bore[m['wellbore']]]
    distinct = {chosen, grid_ref, *tops_pairs, *paths}
    if len(distinct) > MAX_INPUTS: raise _sentence('too-many', n=len(distinct))
    surveys = {pair: client.read_data(*pair) for pair in paths}
    for n, m in enumerate(members, 1):  # D5: the tops' declared datum is the trajectory's (trimmed, case-folded)
        if not by_bore[m['wellbore']]: continue
        context = typed[by_bore[m['wellbore']][0]].context
        if context.get('depth_unit') != 'm': raise _sentence('unit', n=n)
        if m['trajectory'] is None: continue  # 3-7: nothing to compare with
        theirs = surveys[(m['trajectory']['asset_id'], m['trajectory']['revision'])].context.get('depth_datum')
        mine = context.get('depth_datum')
        if _fold(mine) in ('', 'unknown') or _fold(theirs) in ('', 'unknown'): raise _sentence('datum-missing', n=n, datum=theirs or 'unknown')
        if _fold(mine) != _fold(theirs): raise _sentence('datum-differs', n=n, tops=mine.strip(), trajectory=theirs.strip())
    grid = client.read_data(*grid_ref)
    for i, m in enumerate(members):  # E119a's bind refusals, each naming the member and the defect
        if m['trajectory'] is not None: client.well_sets.bind(well_set, i, grid)
    work = Path(tempfile.mkdtemp(prefix='ophiolite-residuals-'))
    try:
        get = lambda pair, stem: client._download_version(pair[0], pair[1], work / stem)  # noqa: E731
        tops_in = []
        for n, m in enumerate(members):
            if by_bore[m['wellbore']]:
                got = get(by_bore[m['wellbore']][0], 'tops-%d' % n); got.wellbore = m['wellbore']; tops_in.append(got)
        inputs = {'selection': [get(chosen, 'selection')], 'tops': tops_in, 'surface': [get(grid_ref, 'surface')],
                  'trajectories': [get(pair, 'trajectory-%d' % n) for n, pair in enumerate(paths)]}
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return Prepared(inputs, ['formation=' + formation, 'display_unit=' + display_unit], members, str(work))


def run(client, name, destination, selection, surface, formation, *, display_unit='m', version=None, yes=False, prompt=None):
    """`prepare`, then run the residual procedure NAME of the project's catalogue on this computer (`procedure_run`)."""
    prepared = prepare(client, selection, surface, formation, display_unit=display_unit)
    try:
        return client.procedure_run(name, destination, prepared.inputs, version=version, yes=yes, prompt=prompt, settings=prepared.settings)
    finally:
        prepared.discard()
