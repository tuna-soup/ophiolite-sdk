"""E160 s0 (D2): one work-episode row as one `ophiolite.work-turn/1` line, and back, driven by work-turn-mapping.json.

Standard library only. The Platform and the SDK load this file from its source text (never by a path import, so no
bytecode lands beside the contract); both then run the same table. `turn(episode, n)` is the line of the episode's
n-th row (1-based), `turns(episode)` every line in row order, and `row(line)` the row a line came from:
canonical(row(turn(e, n))) == canonical(e['rows'][n - 1]) for every row. A line whose optional group is half null is
refused with `TurnError`, naming the group.
"""
import copy
import json
from pathlib import Path

MAPPING = json.loads(Path(__file__).with_name('work-turn-mapping.json').read_text(encoding='utf-8'))
ENTRIES = tuple(MAPPING['entries'])
GROUPS = MAPPING['groups']
_MISSING = object()


class TurnError(ValueError):
    """A row or line the table cannot carry; `place` names the source path, line place or group."""

    def __init__(self, place, text):
        ValueError.__init__(self, '%s: %s' % (place, text))
        self.place = place


def canonical(value):
    """The server's canonical JSON bytes (sorted keys, no spaces, no NaN, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False).encode()


def _get(value, path):
    for step in path.split('.'):
        if not isinstance(value, dict) or step not in value: return _MISSING
        value = value[step]
    return value


def _put(value, path, new):
    *head, last = path.split('.')
    for step in head: value = value.setdefault(step, {})
    value[last] = copy.deepcopy(new)


def turn(episode, n):
    """The line of the episode's n-th row (1-based)."""
    if not 1 <= n <= len(episode['rows']): raise TurnError('n', 'the episode has no row %d' % n)
    row, mode = episode['rows'][n - 1], episode['mode']
    line = {'n': n}
    for entry in ENTRIES:
        if mode not in entry['modes']: continue
        source, _, path = entry['from'].partition('.')
        found = _get(episode if source == 'episode' else row, path)
        if found is _MISSING:
            if entry['group'] is None: raise TurnError(entry['from'], 'the row does not hold it')
            continue
        _put(line, entry['to'], found)
    for group, places in GROUPS.items():
        if group not in row:
            for place in places['null']: _put(line, place, None)
    return line


def turns(episode):
    """Every line of the episode, in row order."""
    return [turn(episode, n) for n in range(1, len(episode['rows']) + 1)]


def row(line):
    """The row a line came from: the inverse of `turn` over the same table."""
    mode, absent = line.get('mode'), set()
    for group, places in GROUPS.items():
        nulls = [_get(line, place) is None for place in places['null']]
        if any(nulls) and not all(nulls): raise TurnError(group, 'the places of an optional group are all null or none is')
        if all(nulls): absent.add(group)
    found = {}
    for entry in ENTRIES:
        if mode not in entry['modes'] or not entry['from'].startswith('row.') or entry['group'] in absent: continue
        value = _get(line, entry['to'])
        if value is _MISSING: raise TurnError(entry['to'], 'the line does not hold it')
        _put(found, entry['from'][len('row.'):], value)
    return found
