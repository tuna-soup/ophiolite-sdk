"""ophiolite.sample-index/1 (E211 s0): the rules of a sample index, as pure functions over documents.

The gateway (project_gateway.sample_index.samples), the SDK (its contracts snapshot) and E212's publish tool run this
same file, loaded from its source text:

    module = types.ModuleType('ophiolite_samples_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). It reads its documents from beside itself and from the contracts tree it sits in
(the same layout in the Platform and in the SDK snapshot): sample-index-schema.json here, the words
(vocabulary/v1/sample-index-words.json) and the bundle manifest schema (bundles/v2/manifest-schema.json). All of them are read when the module is loaded; the checks read no file,
open no connection and start no process. The index, the manifests and the source rules are handed in as data.

A problem is {code, index, id, path}: the code (one of CODES, each with a sentence in the words), the entry's position
in the index (null for the index itself), the entry's id when it has one, and a JSON path in the entry (`$` is the
entry; the index's own paths when `index` is null).
"""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
SAMPLE_INDEX = 'ophiolite.sample-index/1'
WORDS_DOCUMENT = 'ophiolite.sample-index-words/1'
SOURCE_RULES = 'ophiolite.sample-source-rules/1'
# Every code a check can give; each has one sentence in the words and one test case.
CODES = ('index-malformed', 'entry-malformed', 'sample-repeated', 'manifest-missing',
         # C2: the source policy, each source's licence, reading and credit, and the computed block (R-F2, R3, R4, R7)
         'sample-not-approved', 'source-refused', 'acquisition-host', 'licence-malformed', 'not-redistributable',
         'not-anonymous', 'non-commercial', 'licence-not-listed', 'commercial-use-not-read', 'no-attribution-sentence',
         'credit-not-prescribed', 'credit-without-evidence', 'unsupported-combination', 'licence-block-differs',
         # C3: the bundle manifest, its digest, and the contents taken from it
         'manifest-differs', 'manifest-invalid', 'manifest-repeats-item', 'contents-differ')
# The fields of an OSD licence object (record schema, `licence`) the rules read; any other key is kept and not read.
REDISTRIBUTION = ('allowed', 'restricted', 'forbidden', 'unknown')
ATTRIBUTION = ('required', 'not-required', 'unknown')
SPDX = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$')
NON_COMMERCIAL = re.compile(r'(^|-)NC(-|$)')
HOST = re.compile(r'^[a-z][a-z0-9+.-]*://([^/?#:@]+)')


def _read(*parts):
    return json.loads(CONTRACTS.joinpath(*parts).read_text(encoding='utf-8'))


SCHEMA = _read('samples', 'v1', 'sample-index-schema.json')
WORDS = _read('vocabulary', 'v1', 'sample-index-words.json')
MANIFEST_SCHEMA = _read('bundles', 'v2', 'manifest-schema.json')  # C3: ophiolite.portable-bundle/2


# ---- structure: the JSON Schema keywords the sample index and the bundle manifest use -------------------------------
# A first-error reader. Paths follow the reference validator's convention: `required` and `additionalProperties` are
# reported at the object, every other keyword at the value it applies to.

ANNOTATIONS = frozenset(('$schema', '$id', '$defs', 'x-ophiolite', 'title', 'description', 'default', 'examples',
                         'deprecated', 'format', 'discriminator'))
KEYWORDS = frozenset(('$ref', 'type', 'const', 'enum', 'pattern', 'minLength', 'maxLength', 'minimum', 'maximum',
                      'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems', 'uniqueItems', 'items', 'contains',
                      'minContains', 'maxContains', 'required', 'properties', 'additionalProperties', 'maxProperties',
                      'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else')) | ANNOTATIONS


def scan(node, where='#'):
    """Refuse a schema that uses a keyword this reader does not apply (so a new keyword fails loudly, never open)."""
    if isinstance(node, bool): return
    if not isinstance(node, dict): raise ValueError(where + ': a schema is an object')
    unknown = set(node) - KEYWORDS
    if unknown: raise ValueError(where + ': keyword not applied by samples.py: ' + sorted(unknown)[0])
    for key in ('$defs', 'properties'):
        for name, child in node.get(key, {}).items(): scan(child, where + '/' + key + '/' + name)
    for key in ('items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else'):
        if key in node: scan(node[key], where + '/' + key)
    for key in ('allOf', 'anyOf', 'oneOf'):
        for i, child in enumerate(node.get(key, ())): scan(child, where + '/' + key + '/' + str(i))


def _kind(value):
    if value is None: return 'null'
    if isinstance(value, bool): return 'boolean'
    if isinstance(value, int): return 'integer'
    if isinstance(value, float): return 'integer' if value.is_integer() else 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'array'
    if isinstance(value, dict): return 'object'
    return 'unknown'


def _same(a, b):
    if _kind(a) != _kind(b) and {_kind(a), _kind(b)} - {'integer', 'number'}: return False
    if isinstance(a, dict): return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list): return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _type_ok(value, allowed):
    allowed = {allowed} if isinstance(allowed, str) else set(allowed)
    kind = _kind(value)
    return kind in allowed or (kind == 'integer' and 'number' in allowed)


def _ref(root, ref):
    node = root
    for part in ref.removeprefix('#/').split('/'): node = node[part.replace('~1', '/').replace('~0', '~')]
    return node


def first_error(node, value, root, path='$'):
    """The path of the first keyword `value` breaks under `node` (resolved in `root`), or None when it is valid."""
    if node is True: return None
    if node is False: return path
    if '$ref' in node:
        found = first_error(_ref(root, node['$ref']), value, root, path)
        if found is not None: return found
    if 'type' in node and not _type_ok(value, node['type']): return path
    if 'const' in node and not _same(value, node['const']): return path
    if 'enum' in node and not any(_same(value, option) for option in node['enum']): return path
    for key in ('allOf',):
        for child in node.get(key, ()):
            found = first_error(child, value, root, path)
            if found is not None: return found
    if 'anyOf' in node and not any(first_error(child, value, root, path) is None for child in node['anyOf']): return path
    if 'oneOf' in node and sum(first_error(child, value, root, path) is None for child in node['oneOf']) != 1: return path
    if 'not' in node and first_error(node['not'], value, root, path) is None: return path
    if 'if' in node:
        branch = node.get('then') if first_error(node['if'], value, root, path) is None else node.get('else')
        if branch is not None:
            found = first_error(branch, value, root, path)
            if found is not None: return found
    kind = _kind(value)
    if kind == 'string':
        if len(value) < node.get('minLength', 0) or len(value) > node.get('maxLength', len(value)): return path
        if 'pattern' in node and not re.search(node['pattern'], value): return path
    if kind in ('integer', 'number'):
        if value < node.get('minimum', value) or value > node.get('maximum', value): return path
        if 'exclusiveMinimum' in node and value <= node['exclusiveMinimum']: return path
        if 'exclusiveMaximum' in node and value >= node['exclusiveMaximum']: return path
    if kind == 'array':
        if len(value) < node.get('minItems', 0) or len(value) > node.get('maxItems', len(value)): return path
        if node.get('uniqueItems') and any(_same(a, b) for i, a in enumerate(value) for b in value[i + 1:]): return path
        if 'contains' in node:
            matching = sum(first_error(node['contains'], item, root, path) is None for item in value)
            if matching < node.get('minContains', 1) or matching > node.get('maxContains', matching): return path
        if 'items' in node:
            for i, item in enumerate(value):
                found = first_error(node['items'], item, root, f'{path}[{i}]')
                if found is not None: return found
    if kind == 'object':
        if len(value) > node.get('maxProperties', len(value)): return path
        if any(key not in value for key in node.get('required', ())): return path
        props = node.get('properties', {})
        extra = node.get('additionalProperties', True)
        if extra is False and any(key not in props for key in value): return path
        for key, item in value.items():
            child = props[key] if key in props else (extra if isinstance(extra, dict) else None)
            if child is not None:
                found = first_error(child, item, root, f'{path}.{key}')
                if found is not None: return found
    return None


scan(SCHEMA)
scan(MANIFEST_SCHEMA)
ENTRY = {**SCHEMA['$defs']['SampleEntry'], '$defs': SCHEMA['$defs']}
# The index without its entries' structure: each entry is checked on its own, so one malformed entry leaves the others.
INDEX = {**SCHEMA, 'properties': {**SCHEMA['properties'],
                                  'samples': {k: v for k, v in SCHEMA['properties']['samples'].items() if k != 'items'}}}


# ---- problems -------------------------------------------------------------------------------------------------------

def problem(code, path, index=None, ident=None):
    if code not in CODES: raise ValueError('not a sample index code: ' + code)
    return {'code': code, 'index': index, 'id': ident, 'path': path}


def sentence(code, sample):
    """The sentence a person reads for a code, with the sample's name (its title, or its id)."""
    return WORDS['reasons'][code].format(sample=sample)


def _ident(entry):
    ident = entry.get('id') if isinstance(entry, dict) else None
    return ident if isinstance(ident, str) else None


# ---- C2: licence, credit and source policy ----------------------------------------------------------------------------
# After OSD E40 design 4(d): every input `redistribution: allowed`; one SPDX id shared by all inputs or null for all,
# else an unsupported combination; `attribution: required` when any input requires it (an `unknown` one counts as
# required: it fails closed); `share_alike: true` when any input has it; each input's licence object kept whole.

def _licence_fields(licence, at):
    """The first malformed field the rules read in a source's licence object, as a path, or None."""
    if not isinstance(licence.get('name'), str) or not licence['name']: return at + '.name'
    if licence.get('redistribution') not in REDISTRIBUTION: return at + '.redistribution'
    if licence.get('attribution') not in ATTRIBUTION: return at + '.attribution'
    spdx = licence.get('spdx')
    if spdx is not None and not (isinstance(spdx, str) and SPDX.match(spdx)): return at + '.spdx'
    if 'share_alike' in licence and not isinstance(licence['share_alike'], bool): return at + '.share_alike'
    if 'statement' in licence and not (isinstance(licence['statement'], str) and licence['statement']): return at + '.statement'
    return None


def _host(url):
    match = HOST.match(url)
    return match.group(1).lower() if match else None


def _source_problems(source, at, rules):
    """(code, path) of each rule one source breaks."""
    out = []
    record = source['osd_record']
    if record in rules['refused_records']: out.append(('source-refused', at + '.osd_record'))
    hosts = rules['acquisition_hosts'].get(record)
    if hosts is not None and _host(source['acquired_from']['url']) not in [h.lower() for h in hosts]:
        out.append(('acquisition-host', at + '.acquired_from.url'))
    if source['origin']['access'] != 'anonymous': out.append(('not-anonymous', at + '.origin.access'))
    if not source['acquired_from']['url'].startswith('https://'): out.append(('not-anonymous', at + '.acquired_from.url'))
    licence = source['licence']
    malformed = _licence_fields(licence, at + '.licence')
    if malformed is not None: return out + [('licence-malformed', malformed)]
    if licence['redistribution'] != 'allowed': out.append(('not-redistributable', at + '.licence.redistribution'))
    spdx = licence.get('spdx')
    if spdx is not None:
        if NON_COMMERCIAL.search(spdx): out.append(('non-commercial', at + '.licence.spdx'))
        elif spdx not in rules['spdx']: out.append(('licence-not-listed', at + '.licence.spdx'))
    use = source['reading']['commercial_use']
    if use == 'not-allowed': out.append(('non-commercial', at + '.reading.commercial_use'))
    elif use != 'allowed': out.append(('commercial-use-not-read', at + '.reading.commercial_use'))
    credit = source.get('credit')
    if credit is None:
        if licence['attribution'] != 'not-required': out.append(('no-attribution-sentence', at + '.credit'))
    elif credit['kind'] == 'prescribed':
        if credit['text'] != licence.get('statement'): out.append(('credit-not-prescribed', at + '.credit.text'))
    elif 'evidence' not in credit: out.append(('credit-without-evidence', at + '.credit.evidence'))
    return out


def computed_licence(sources):
    """The licence block an entry must state, computed from its (valid) sources; None for an unsupported combination
    (an SPDX id beside a null one, or two different ids)."""
    spdx = {source['licence'].get('spdx') for source in sources}
    if len(spdx) != 1: return None
    statements = []
    for source in sources:
        text = (source.get('credit') or {}).get('text')
        if text is not None and text not in statements: statements.append(text)
    return {'spdx': spdx.pop(), 'redistribution': 'allowed',
            'attribution': 'required' if any(s['licence']['attribution'] != 'not-required' for s in sources) else 'not-required',
            'share_alike': any(s['licence'].get('share_alike') is True for s in sources), 'statements': statements}


def licence_problems(sample_id, sources, licence, rules):
    """(code, path) of each policy and licence rule a well-formed sample id, source list and licence block break, paths
    rooted as in an entry (`$.id`, `$.sources[i]...`, `$.licence...`). Public for the public store (E212 s0), whose
    datasets carry the same sources and licence block."""
    if not isinstance(rules, dict) or rules.get('schema') != SOURCE_RULES: raise ValueError('the source rules are not ' + SOURCE_RULES)
    out = []
    if sample_id not in rules['approved_samples'] or sample_id in rules['refused_samples']: out.append(('sample-not-approved', '$.id'))
    for i, source in enumerate(sources): out.extend(_source_problems(source, f'$.sources[{i}]', rules))
    if any(code != 'sample-not-approved' for code, _ in out): return out
    block = computed_licence(sources)
    if block is None: return out + [('unsupported-combination', '$.sources')]
    for key in ('spdx', 'redistribution', 'attribution', 'share_alike', 'statements'):
        if not _same(block[key], licence[key]): return out + [('licence-block-differs', '$.licence.' + key)]
    return out


def _rules_problems(entry, rules):
    """(code, path) of each policy and licence rule a well-formed entry breaks."""
    return licence_problems(entry['id'], entry['sources'], entry['licence'], rules)


# ---- C3: contents from the bundle manifest ----------------------------------------------------------------------------
# The contents of an entry are the manifest's, never typed by hand: one {type, asset_id, revision, name} per asset (name
# null when absent or null) sorted by (type, asset_id, revision), one {kind, entity_id, name} per entity (an absent list
# is empty) sorted by (kind, entity_id). Lists, never sets: multiplicity is kept. An asset id and an entity id may be
# equal; they are different sections. A path in the manifest is written `manifest:<path>`.

def _refuse_constant(value):
    raise ValueError('not a JSON number: ' + value)


def projection(manifest):
    """The contents a valid manifest gives (the manifest is not changed)."""
    assets = [{'type': a['type'], 'asset_id': a['asset_id'], 'revision': a['revision'], 'name': a.get('name')} for a in manifest['assets']]
    entities = [{'kind': e['kind'], 'entity_id': e['entity_id'], 'name': e['name']} for e in manifest.get('entities') or []]
    return {'assets': sorted(assets, key=lambda a: (a['type'], a['asset_id'], a['revision'])),
            'entities': sorted(entities, key=lambda e: (e['kind'], e['entity_id']))}


def _manifest_problems(entry, manifest_bytes):
    """(code, path) of the first problem of an entry's manifest and contents: the digest, the manifest's structure, a
    repeated item, then the first projected item the entry's contents differ at."""
    if hashlib.sha256(manifest_bytes).hexdigest() != entry['bundle']['manifest_sha256']: return [('manifest-differs', '$.bundle.manifest_sha256')]
    try: manifest = json.loads(manifest_bytes.decode('utf-8'), parse_constant=_refuse_constant)
    except ValueError: return [('manifest-invalid', 'manifest:$')]
    found = first_error(MANIFEST_SCHEMA, manifest, MANIFEST_SCHEMA)
    if found is not None: return [('manifest-invalid', 'manifest:' + found)]
    seen = set()
    for j, asset in enumerate(manifest['assets']):
        if (asset['asset_id'], asset['revision']) in seen: return [('manifest-repeats-item', f'manifest:$.assets[{j}]')]
        seen.add((asset['asset_id'], asset['revision']))
    seen = set()
    for j, entity in enumerate(manifest.get('entities') or []):
        if entity['entity_id'] in seen: return [('manifest-repeats-item', f'manifest:$.entities[{j}]')]
        seen.add(entity['entity_id'])
    expected = projection(manifest)
    for section in ('assets', 'entities'):
        stated, made = entry['contents'][section], expected[section]
        for k in range(max(len(stated), len(made))):
            if k >= len(stated) or k >= len(made) or not _same(stated[k], made[k]): return [('contents-differ', f'$.contents.{section}[{k}]')]
    return []


def entry_problems(entry, manifest_bytes, rules, index=None):
    """Every problem of one entry: its structure first (nothing else is read from an entry that is malformed), then
    the source policy and the licence (`rules` is the `ophiolite.sample-source-rules/1` document), then its manifest
    (`manifest_bytes` is None when the index's manifests do not hold its bundle's)."""
    ident = _ident(entry)
    found = first_error(ENTRY, entry, ENTRY)
    if found is not None: return [problem('entry-malformed', found, index, ident)]
    out = [problem(code, path, index, ident) for code, path in _rules_problems(entry, rules)]
    if manifest_bytes is None: out.append(problem('manifest-missing', '$.bundle.key', index, ident))
    else: out.extend(problem(code, path, index, ident) for code, path in _manifest_problems(entry, manifest_bytes))
    return out


def offered(index, manifests, rules):
    """The entries a card may be offered for, and the problems of the others. `manifests` maps a bundle key to its
    manifest's bytes. A problem in one entry leaves the other entries offered; an id given twice offers neither."""
    found = first_error(INDEX, index, SCHEMA)
    if found is not None: return [], [problem('index-malformed', found)]
    entries = index['samples']
    seen = {}
    for entry in entries:
        ident = _ident(entry)
        if ident is not None: seen[ident] = seen.get(ident, 0) + 1
    good, problems = [], []
    for position, entry in enumerate(entries):
        ident = _ident(entry)
        key = entry.get('bundle', {}).get('key') if isinstance(entry, dict) and isinstance(entry.get('bundle'), dict) else None
        own = entry_problems(entry, manifests.get(key) if isinstance(key, str) else None, rules, position)
        if ident is not None and seen[ident] > 1: own.append(problem('sample-repeated', '$.id', position, ident))
        if own: problems.extend(own)
        else: good.append(entry)
    return good, problems
