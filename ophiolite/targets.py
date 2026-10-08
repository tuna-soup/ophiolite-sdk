"""E86: what each type of table needs, read from the packaged contracts (no server, no engine).

`targets()` lists the table targets the registry names; `target(name)` gives one as the generated `TableTarget` model, with
`.field_names`, `.reader_names` and `.declaration(name)`. `render(target, report, group, declarations)` gives the plain
sentence for one mapping-check group from the packaged words file and coordinate-system catalogue: the same contract as
Connectors' `table_engine.render` and the Workspace's `render`, all three equal to the shared render cases.
"""
import json
from functools import lru_cache
from importlib.resources import files

from .models.generated import TableTarget

__all__ = ['Target', 'targets', 'target', 'document', 'render']


def _read(path):
    return json.loads(files('ophiolite').joinpath('contracts', path).read_text(encoding='utf-8'))


@lru_cache(maxsize=None)
def _paths():
    """{name: path} of every table-target document the packaged registry lists, in its order."""
    return {d['id'].split('/')[1]: d['path'] for d in _read('registry.json')['documents'] if d['kind'] == 'table-target'}


@lru_cache(maxsize=None)
def _raw(name):
    paths = _paths()
    if name not in paths: raise KeyError('No table type is named %r; ophiolite targets lists them.' % name)
    return _read(paths[name])


def document(name):
    """The target document exactly as packaged (a fresh copy)."""
    return json.loads(json.dumps(_raw(name)))


class Target(TableTarget):
    """A table target: the generated model with the names a reader needs."""

    @property
    def field_names(self):
        return [f.name for f in self.fields]

    @property
    def reader_names(self):
        """{field: the name a reader gives the column} for the fields a reader fills by a fixed name."""
        return {f.name: f.canonical for f in self.fields if getattr(f, 'canonical', None)}

    def declaration(self, name):
        found = next((d for d in self.declarations if d.name == name), None)
        if found is None: raise KeyError('%s has no declaration named %r' % (self.display_name, name))
        return found


def target(name):
    return Target.model_validate(_raw(name))


def targets():
    return [target(name) for name in _paths()]


@lru_cache(maxsize=None)
def _words():
    return _read('vocabulary/v1/mapping-check-words.json')


@lru_cache(maxsize=None)
def _systems():
    return {s['code']: s for s in _read('vocabulary/v1/coordinate-systems.json')['systems']}


def _text(value):
    """A value as the Workspace's String(value) writes it, so the three renderers agree."""
    if value is None: return 'null'
    if isinstance(value, bool): return 'true' if value else 'false'
    if isinstance(value, float):
        if value != value: return 'NaN'
        if value in (float('inf'), float('-inf')): return 'Infinity' if value > 0 else '-Infinity'
        if value.is_integer() and abs(value) < 1e21: return str(int(value))
        return repr(value)
    return str(value)


def _examples(words, code, group):
    rule = words['codes'].get(code, {}).get('examples', 'none')
    if rule == 'none': return ''
    form = words['examples'][rule]
    shown = []
    for e in group['examples'][:form['max']]:
        text, cut = _text(e['value']), e['truncated']
        if form['cut'] is not None and len(text) > form['cut']: text, cut = text[:form['cut']], True
        shown.append(text + (form['truncated'] if cut else ''))
    if not shown: return ''
    joined = form['join'].join(shown[:-1]) + form['last'] + shown[-1] if form.get('last') and len(shown) > 1 else form['join'].join(shown)
    return form['lead'] + joined


def render(target, report, group, declarations):
    """The sentence for one group. `target` is a name, a `TableTarget` or a document; an unknown code reads as
    `mapping-invalid`."""
    doc = _raw(target) if isinstance(target, str) else target.model_dump(by_alias=True) if isinstance(target, TableTarget) else target
    words = _words()
    code = group['code'] if group['code'] in words['codes'] else 'mapping-invalid'
    p = group.get('params') or {}
    item = next((x for x in doc['fields'] + doc['declarations'] if x['name'] == group.get('field')), None)
    noun = p.get('noun') or (item['noun'] if item else words['nouns'].get(group.get('field') or '', words['noun_fallback']))
    entity = p.get('entity') or (item and (item.get('entity') or item.get('to'))) or words['entity_fallback']
    n, total = group.get('rows') or 0, report.get('rows_checked', 0)
    of = words['of'].format(n='{:,}'.format(n), rows='{:,}'.format(total) + ' ' + words['rows'][0 if total == 1 else 1])
    entry = _systems().get((declarations or {}).get('crs') or '')
    name = (entry['name'] if entry['geographic'] else '%s (%s)' % (entry['name'], entry['unit'])) if entry else ''
    bounds = item.get('bounds') if item else None
    low, high = p.get('low', bounds and bounds['min']), p.get('high', bounds and bounds['max'])
    span = words['range']['exclusive_high' if bounds and not bounds['max_inclusive'] else 'inclusive'].format(low=_text(low), high=_text(high))
    limit = p.get('limit', item and item.get('max_length'))
    return words['codes'][code]['template'].format(of=of, noun=noun, entity=entity, examples=_examples(words, code, group), range=span, limit=limit,
                                                   system=words['system'].format(system_name=name) if name else '', system_name=name or words['system_fallback'])
