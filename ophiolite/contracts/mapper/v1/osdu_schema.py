"""ophiolite.osdu-schema-validator/1 (E116 s3 D2): the offline check of a document against the vendored OSDU
data-definitions schemas (osdu/<tag>/Generated/, beside this file), run alike by the Platform tests and the
ophiolite-mapper box (its copy, ophiolite_mapper/contract/, is byte-identical).

Standard library only. It applies draft-07 as far as the vendored closure uses it, and no further: the assertions
$ref (a relative file and/or a JSON pointer, resolved inside the vendored Generated/ tree; draft-07 ignores a $ref's
siblings), allOf, oneOf, type, properties, required, additionalProperties, items, minItems, const, enum and pattern
(Python re.search); the annotations $id, $schema, title, description, example, default and format (draft-07: format is
an annotation), and every x-osdu-* keyword. Any other keyword, a $ref to a URL or out of the tree, and an items list
refuse the schema (SchemaRefused, naming it), so a schema this file cannot apply exactly never passes in silence.
The recipe and folder validator (mapper.py structure()) is a different reader and is not this one.
"""
import json
import posixpath
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAG = 'v0.30.1'
ASSERTIONS = frozenset({'$ref', 'allOf', 'oneOf', 'type', 'properties', 'required', 'additionalProperties', 'items',
                        'minItems', 'const', 'enum', 'pattern'})
ANNOTATIONS = frozenset({'$id', '$schema', 'title', 'description', 'example', 'default', 'format'})
TYPES = frozenset({'string', 'number', 'integer', 'boolean', 'object', 'array', 'null'})


class SchemaRefused(Exception):
    """A schema this validator cannot apply exactly: the keyword or reference named."""


def root(tag=TAG, here=HERE):
    """The vendored tree, wherever the copy sits (osdu/<tag> beside the module)."""
    return here / 'osdu' / tag


class Schemas:
    """The vendored schema files, read once each, by their Generated/... path."""

    def __init__(self, base=None):
        self.base = Path(base) if base is not None else root()
        self._files = {}

    def file(self, path):
        if path not in self._files:
            if not path.startswith('Generated/') or posixpath.normpath(path) != path:
                raise SchemaRefused(f'{path} is outside the vendored schemas')
            target = self.base / path
            if not target.is_file(): raise SchemaRefused(f'{path} is not vendored')
            self._files[path] = json.loads(target.read_text(encoding='utf-8'))
        return self._files[path]

    def resolve(self, here, ref):
        """(file, node) a $ref names from the file `here`."""
        if '://' in ref: raise SchemaRefused(f'{here}: $ref {ref} is a remote reference')
        target, _, pointer = ref.partition('#')
        path = posixpath.normpath(posixpath.join(posixpath.dirname(here), target)) if target else here
        if not path.startswith('Generated/'): raise SchemaRefused(f'{here}: $ref {ref} leaves the vendored schemas')
        node = self.file(path)
        for part in [p for p in pointer.split('/') if p]:
            part = part.replace('~1', '/').replace('~0', '~')
            try: node = node[int(part)] if isinstance(node, list) else node[part]
            except (KeyError, IndexError, ValueError): raise SchemaRefused(f'{here}: $ref {ref} names nothing') from None
        return path, node


def _kind(value):
    if value is None: return 'null'
    if isinstance(value, bool): return 'boolean'
    if isinstance(value, int): return 'integer'
    if isinstance(value, float): return 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'array'
    if isinstance(value, dict): return 'object'
    return 'unknown'


def _is(value, name):
    kind = _kind(value)
    if name == 'number': return kind in ('integer', 'number')
    if name == 'integer': return kind == 'integer' or (kind == 'number' and value.is_integer())
    return kind == name


def _equal(a, b):
    """JSON equality: true is not 1, 1 is 1.0."""
    if isinstance(a, bool) or isinstance(b, bool): return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)): return a == b
    if isinstance(a, list) and isinstance(b, list): return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict): return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _known(node, where):
    for key in node:
        if key not in ASSERTIONS and key not in ANNOTATIONS and not key.startswith('x-osdu-'):
            raise SchemaRefused(f'{where}: the keyword {key} is not one this validator applies')
    if isinstance(node.get('items'), list): raise SchemaRefused(f'{where}: items as a list is not applied')


def errors(schemas, file, node, value, path='$'):
    """Every violation as (keyword, instance path), in schema order; [] when the value fits."""
    if isinstance(node, bool): return [] if node else [('false', path)]
    _known(node, file)
    if '$ref' in node:  # draft-07: the siblings of $ref are ignored
        target, sub = schemas.resolve(file, node['$ref'])
        return errors(schemas, target, sub, value, path)
    found = []
    for branch in node.get('allOf', ()):
        found += errors(schemas, file, branch, value, path)
    if 'oneOf' in node:
        fitting = sum(not errors(schemas, file, branch, value, path) for branch in node['oneOf'])
        if fitting != 1: found.append(('oneOf', path))
    if 'type' in node:
        allowed = node['type'] if isinstance(node['type'], list) else [node['type']]
        if not set(allowed) <= TYPES: raise SchemaRefused(f'{file}: type {node["type"]} is not a JSON type')
        if not any(_is(value, t) for t in allowed): return found + [('type', path)]
    if 'const' in node and not _equal(value, node['const']): found.append(('const', path))
    if 'enum' in node and not any(_equal(value, e) for e in node['enum']): found.append(('enum', path))
    if isinstance(value, str) and 'pattern' in node and not re.search(node['pattern'], value): found.append(('pattern', path))
    if isinstance(value, list):
        if len(value) < node.get('minItems', 0): found.append(('minItems', path))
        if 'items' in node:
            for i, item in enumerate(value): found += errors(schemas, file, node['items'], item, f'{path}[{i}]')
    if isinstance(value, dict):
        for key in node.get('required', ()):
            if key not in value: found.append(('required', f'{path}.{key}'))
        props, extra = node.get('properties', {}), node.get('additionalProperties', True)
        for key, item in value.items():
            if key in props: found += errors(schemas, file, props[key], item, f'{path}.{key}')
            elif extra is False: found.append(('additionalProperties', f'{path}.{key}'))
            elif isinstance(extra, dict): found += errors(schemas, file, extra, item, f'{path}.{key}')
    return found


def check(schema_path, value, schemas=None):
    """The violations of `value` against the vendored file `schema_path` (Generated/...)."""
    schemas = schemas or Schemas()
    return errors(schemas, schema_path, schemas.file(schema_path), value)


def kind_file(kind):
    """The vendored file of a kind ('osdu:wks:master-data--Well:1.5.0' -> Generated/master-data/Well.1.5.0.json), or None
    when the kind is not of that form."""
    match = re.fullmatch(r'[\w.-]+:wks:(?:([\w-]+)--)?([\w.]+):(\d+\.\d+\.\d+)', kind or '')
    if not match: return None
    group, name, version = match.groups()
    return f'Generated/{group or "manifest"}/{name}.{version}.json'
