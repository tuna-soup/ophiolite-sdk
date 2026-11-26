"""E187 s1 C1: the classifier of the supported-contracts gate. It compares the frozen closure of the supported contracts
(PG/tests/fixtures/released/supported-<n>/) with the current one and gives every difference exactly one class; the gate
(C3) fails on any difference whose verdict is not pass. Pure functions over parsed JSON; standard library only.

The closure of a listed (group, id): a schema is its file with its own $defs; a profile is its document plus the
schemas it names by payload_schema, context_schema and recipe_schema, the profiles it names by normalized_profile(s),
and the documents it names by mappings and mapped_from, followed recursively. `serves` targets and every `const` id are
named strings, compared and not followed. A followed schema or profile that is not itself listed is a refusal.

Rule B (EPICS.md E187, amended 23 November 2026): an optional property added at a plain `properties` position of an
object (reached from the root without anyOf, oneOf, allOf, not, if/then/else, patternProperties, dependentSchemas,
contains or tuple items, and whose additionalProperties is absent, true or false) is a minor version. It passes only
when the entry's minor version rises, the id is not read by a reader that is strict on purpose, and the id has a reader
row whose test proves the pinned tolerant SDK reads the current answer. Every other new field is a new id.

Meaning text (`description`, `title`, a profile's `interpretation`) and followed documents change only with a bound
reviewed row: {baseline, group, id, pointer, kind, old_sha256, new_sha256, release_note}, kind meaning-reviewed or
document-reviewed, the digests those of the baseline value and the current value at the pointer (value_digest).
Stale, duplicate and unused rows fail, and so does a row on any other class.
"""
import hashlib
import json
from dataclasses import dataclass, field

PASS_CLASSES = ('added-optional-property', 'added-unreferenced-def', 'entry-version')
FAIL_CLASSES = ('closed-object-widened', 'no-reader-proof', 'removed-property', 'made-required', 'type-changed',
                'enum-changed', 'bound-changed', 'pattern-changed', 'named-id-changed', 'document-changed',
                'meaning-text-changed', 'unclassified', 'stale-review', 'duplicate-review', 'unused-review',
                'forbidden-review')
REVIEW_KINDS = {'meaning-reviewed': 'meaning-text-changed', 'document-reviewed': 'document-changed'}

# The keyword census of the registry's schemas at 1.138.0, plus the applicators rule B names. Anything else is unclassified.
KEYWORDS = frozenset({
    '$schema', '$id', '$ref', '$defs', 'x-ophiolite', 'title', 'description', 'type', 'properties', 'required',
    'additionalProperties', 'items', 'prefixItems', 'anyOf', 'oneOf', 'allOf', 'not', 'if', 'then', 'else', 'contains',
    'patternProperties', 'dependentSchemas', 'enum', 'const', 'default', 'pattern', 'discriminator', 'minLength',
    'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems', 'uniqueItems',
    'minContains', 'maxContains', 'minProperties', 'maxProperties'})
BOUNDS = frozenset({'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minItems',
                    'maxItems', 'uniqueItems', 'minContains', 'maxContains', 'minProperties', 'maxProperties'})
MEANING = frozenset({'title', 'description'})
PLAIN_SINGLE = ('items',)
APPLICATOR_SINGLE = ('not', 'if', 'then', 'else', 'contains')
APPLICATOR_LIST = ('anyOf', 'oneOf', 'allOf', 'prefixItems')
APPLICATOR_MAP = ('patternProperties', 'dependentSchemas')
NAMED = frozenset({'$schema', '$id', 'const'})

PROFILE_SCHEMAS = ('payload_schema', 'context_schema', 'recipe_schema')
PROFILE_PROFILES = ('normalized_profile', 'normalized_profiles')
PROFILE_DOCUMENTS = ('mappings', 'mapped_from')
PROFILE_NAMED = frozenset({'schema', 'id', 'serves', *PROFILE_SCHEMAS, *PROFILE_PROFILES, *PROFILE_DOCUMENTS})
PROFILE_MEANING = frozenset({'description', 'title', 'interpretation'})

SENTENCES = {
    'added-optional-property': 'an optional property at an admitted position, with the minor version raised',
    'added-unreferenced-def': 'a definition nothing references was added',
    'entry-version': 'the version rose with the additive change it carries',
    'removed-property': 'a property was removed',
    'made-required': 'a property became required; a required field is a new id',
    'type-changed': 'a type or a reference changed',
    'enum-changed': 'an enumeration changed (a value removed or added)',
    'bound-changed': 'a bound changed',
    'pattern-changed': 'a pattern changed',
    'named-id-changed': 'a named contract id changed',
    'document-changed': 'a followed document changed without a reviewed row',
    'meaning-text-changed': 'meaning-bearing text changed without a reviewed row',
}


@dataclass(frozen=True)
class Finding:
    group: str
    id: str
    pointer: str
    cls: str
    verdict: str
    sentence: str
    old: object = field(default=None, compare=False, repr=False)
    new: object = field(default=None, compare=False, repr=False)


def value_digest(value):
    """The sha256 of a value as a reviewed row names it: canonical JSON, keys sorted, UTF-8."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _esc(name):
    return str(name).replace('~', '~0').replace('/', '~1')


def _finding(group, cid, pointer, cls, detail=None, old=None, new=None, verdict=None):
    verdict = verdict or ('pass' if cls in PASS_CLASSES else 'fail')
    text = detail or SENTENCES.get(cls, cls)
    return Finding(group, cid, pointer, cls, verdict, f'{group} {cid} at {pointer or "/"}: {text} ({cls})', old, new)


# ---- the closure ---------------------------------------------------------------------------------------------------

def _names(value):
    if value is None: return []
    return [value] if isinstance(value, str) else list(value)


def closure(registry, load, listed):
    """{(group, id): {'version', 'body'}} for the listed entries and what they follow, and the refusals (sentences).

    registry is registry.json parsed; load(path) returns a registry path's parsed JSON; listed is (group, id) pairs with
    group one of schemas, profiles, documents."""
    index = {(group, entry['id']): entry for group in ('schemas', 'profiles', 'documents') for entry in registry[group]}
    listed = set(listed)
    members, refusals, todo = {}, [], sorted(listed)
    while todo:
        key = todo.pop(0)
        if key in members: continue
        entry = index.get(key)
        if entry is None:
            refusals.append(f'{key[0]} {key[1]} is named but not in the registry'); continue
        body = load(entry['path'])
        members[key] = {'version': entry.get('version'), 'body': body}
        if key[0] != 'profiles': continue
        follows = ([('schemas', n) for k in PROFILE_SCHEMAS for n in _names(body.get(k))]
                   + [('profiles', n) for k in PROFILE_PROFILES for n in _names(body.get(k))]
                   + [('documents', n) for k in PROFILE_DOCUMENTS for n in _names(body.get(k))])
        for follow in follows:
            if follow[0] != 'documents' and follow not in listed:
                refusals.append(f'profiles {key[1]} follows {follow[0]} {follow[1]}, which is not listed')
            if follow not in members: todo.append(follow)
    return members, refusals


# ---- positions -----------------------------------------------------------------------------------------------------

def _resolve(schema, ref):
    if not isinstance(ref, str) or not ref.startswith('#/'): return None, None
    node = schema
    for part in ref[2:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if not isinstance(node, dict) or part not in node: return None, None
        node = node[part]
    return node, ref[1:]


def _plainness(schema):
    """{pointer: set of bools}: every object node the root reaches, and whether each path reaching it was plain."""
    seen, flags, todo = set(), {}, [(schema, '', True)]
    while todo:
        node, ptr, plain = todo.pop()
        if (ptr, plain) in seen or not isinstance(node, dict): continue
        seen.add((ptr, plain))
        flags.setdefault(ptr, set()).add(plain)
        if '$ref' in node:
            target, tptr = _resolve(schema, node['$ref'])
            if target is not None: todo.append((target, tptr, plain))
        for name, sub in (node.get('properties') or {}).items():
            todo.append((sub, f'{ptr}/properties/{_esc(name)}', plain))
        if isinstance(node.get('items'), dict): todo.append((node['items'], f'{ptr}/items', plain))
        if isinstance(node.get('additionalProperties'), dict):
            todo.append((node['additionalProperties'], f'{ptr}/additionalProperties', False))
        for k in APPLICATOR_SINGLE:
            if isinstance(node.get(k), dict): todo.append((node[k], f'{ptr}/{k}', False))
        for k in APPLICATOR_LIST + ('items',):
            if isinstance(node.get(k), list):
                todo.extend((sub, f'{ptr}/{k}/{i}', False) for i, sub in enumerate(node[k]))
        for k in APPLICATOR_MAP:
            for name, sub in (node.get(k) or {}).items(): todo.append((sub, f'{ptr}/{k}/{_esc(name)}', False))
    return flags


def _open_to_addition(node):
    return isinstance(node, dict) and isinstance(node.get('properties'), dict) and not isinstance(node.get('additionalProperties'), dict)


def admitted_positions(schema):
    """The pointers of the objects where rule B admits an optional property: plain on every path, properties declared,
    additionalProperties absent, true or false. C4 injects at these; the gate admits additions only here."""
    out = []
    for ptr, flags in _plainness(schema).items():
        node, _ = _resolve(schema, '#' + ptr) if ptr else (schema, '')
        if flags == {True} and _open_to_addition(node): out.append(ptr)
    return sorted(out)


# ---- schema differences --------------------------------------------------------------------------------------------

def _refs(node, out):
    if isinstance(node, dict):
        if isinstance(node.get('$ref'), str): out.add(node['$ref'])
        for v in node.values(): _refs(v, out)
    elif isinstance(node, list):
        for v in node: _refs(v, out)
    return out


def _unknown_keywords(node, ptr):
    """Pointers of keywords outside the census inside a schema subtree (added subtrees are checked whole)."""
    out = []
    if not isinstance(node, dict): return out
    for k, v in node.items():
        here = f'{ptr}/{_esc(k)}'
        if k not in KEYWORDS: out.append(here); continue
        if k in ('properties', '$defs') + APPLICATOR_MAP and isinstance(v, dict):
            for name, sub in v.items(): out += _unknown_keywords(sub, f'{here}/{_esc(name)}')
        elif k in ('items', 'additionalProperties') + APPLICATOR_SINGLE and isinstance(v, dict):
            out += _unknown_keywords(v, here)
        elif isinstance(v, list) and k in APPLICATOR_LIST + ('items',):
            for i, sub in enumerate(v): out += _unknown_keywords(sub, f'{here}/{i}')
    return out


class _SchemaDiff:
    def __init__(self, group, cid, old, new):
        self.group, self.id, self.old_root, self.new_root = group, cid, old, new
        self.findings, self.additions, self.added_defs = [], [], {}

    def add(self, pointer, cls, detail=None, old=None, new=None):
        self.findings.append(_finding(self.group, self.id, pointer, cls, detail, old, new))

    def node(self, old, new, ptr):
        if old == new: return
        if not (isinstance(old, dict) and isinstance(new, dict)):
            self.add(ptr, 'type-changed', old=old, new=new); return
        for k in sorted(set(old) | set(new), key=str):
            here = f'{ptr}/{_esc(k)}'
            a, b = old.get(k), new.get(k)
            if a == b: continue
            if k not in KEYWORDS:
                self.add(here, 'unclassified', f'the keyword {k} is outside the census', a, b)
            elif k == 'properties':
                self.properties(a or {}, b or {}, here, new)
            elif k == '$defs':
                self.defs(a or {}, b or {}, here)
            elif k == 'required':
                gained, lost = set(b or []) - set(a or []), set(a or []) - set(b or [])
                for name in sorted(gained):
                    if name in (old.get('properties') or {}):
                        self.add(f'{ptr}/properties/{_esc(name)}', 'made-required')
                for name in sorted(lost):
                    self.add(f'{ptr}/properties/{_esc(name)}', 'unclassified', 'a property stopped being required')
            elif k == 'additionalProperties':
                if isinstance(a, dict) and isinstance(b, dict): self.node(a, b, here)
                elif a is False: self.add(here, 'closed-object-widened', 'a closed object was opened to any property')
                else: self.add(here, 'type-changed', 'additionalProperties changed', a, b)
            elif k in PLAIN_SINGLE + APPLICATOR_SINGLE:
                if isinstance(a, list) and isinstance(b, list): self.lists(a, b, here)
                elif a is None or b is None: self.add(here, 'type-changed', f'{k} was added or removed', a, b)
                else: self.node(a, b, here)
            elif k in APPLICATOR_LIST:
                if not (isinstance(a, list) and isinstance(b, list)): self.add(here, 'type-changed', f'{k} was added or removed', a, b)
                else: self.lists(a, b, here)
            elif k in APPLICATOR_MAP:
                if not (isinstance(a, dict) and isinstance(b, dict)) or set(a) != set(b):
                    self.add(here, 'type-changed', f'the names of {k} changed', a, b)
                else:
                    for name in sorted(a): self.node(a[name], b[name], f'{here}/{_esc(name)}')
            elif k in MEANING: self.add(here, 'meaning-text-changed', old=a, new=b)
            elif k in BOUNDS: self.add(here, 'bound-changed', old=a, new=b)
            elif k == 'pattern': self.add(here, 'pattern-changed', old=a, new=b)
            elif k == 'enum': self.add(here, 'enum-changed', old=a, new=b)
            elif k in NAMED: self.add(here, 'named-id-changed', old=a, new=b)
            elif k in ('type', '$ref'): self.add(here, 'type-changed', old=a, new=b)
            elif k == 'x-ophiolite': self.x_ophiolite(a or {}, b or {}, here)
            else: self.add(here, 'unclassified', f'{k} changed', a, b)

    def lists(self, a, b, here):
        if len(a) != len(b): self.add(here, 'type-changed', 'the number of alternatives changed', a, b); return
        for i, (x, y) in enumerate(zip(a, b)): self.node(x, y, f'{here}/{i}')

    def properties(self, a, b, here, owner):
        for name in sorted(set(a) | set(b)):
            ptr = f'{here}/{_esc(name)}'
            if name not in b: self.add(ptr, 'removed-property', old=a[name])
            elif name not in a: self.additions.append((ptr, name, owner, b[name]))
            else: self.node(a[name], b[name], ptr)

    def defs(self, a, b, here):
        for name in sorted(set(a) | set(b)):
            ptr = f'{here}/{_esc(name)}'
            if name not in b: self.add(ptr, 'removed-property', 'a definition was removed', a[name])
            elif name not in a: self.added_defs[ptr] = b[name]
            else: self.node(a[name], b[name], ptr)

    def x_ophiolite(self, a, b, here):
        for k in sorted(set(a) | set(b)):
            if k == 'version' or a.get(k) == b.get(k): continue
            cls = 'named-id-changed' if k == 'id' else 'unclassified'
            self.add(f'{here}/{_esc(k)}', cls, None if cls != 'unclassified' else f'x-ophiolite {k} changed', a.get(k), b.get(k))


def _version(text):
    try: return tuple(int(p) for p in str(text).split('.'))
    except ValueError: return None


def _schema_findings(group, cid, frozen, current, strict_readers, reader_ids):
    old, new = frozen['body'], current['body']
    diff = _SchemaDiff(group, cid, old, new)
    diff.node(old, new, '')
    v_old = _version(frozen.get('version') or (old.get('x-ophiolite') or {}).get('version'))
    v_new = _version(current.get('version') or (new.get('x-ophiolite') or {}).get('version'))
    minor = bool(v_old and v_new and len(v_old) == len(v_new) == 3 and v_new[0] == v_old[0] and v_new[1] > v_old[1])
    plain = _plainness(new)

    added_ptrs = [ptr for ptr, *_ in diff.additions]
    inside_added = set()
    for ptr, name, owner, sub in diff.additions:
        inside_added |= _refs(sub, set())
    # an added definition is part of an addition when only added subtrees (or definitions they reach) reference it
    absorbed, changed = set(), True
    while changed:
        changed = False
        for dptr, sub in diff.added_defs.items():
            if '#' + dptr in inside_added and dptr not in absorbed:
                absorbed.add(dptr); inside_added |= _refs(sub, set()); changed = True
    outside = set()
    stripped = json.loads(json.dumps(new))
    for ptr in added_ptrs + sorted(diff.added_defs):
        parent, _ = _resolve(stripped, '#' + ptr.rsplit('/', 1)[0])
        if isinstance(parent, dict): parent.pop(ptr.rsplit('/', 1)[1].replace('~1', '/').replace('~0', '~'), None)
    _refs(stripped, outside)
    for dptr, sub in sorted(diff.added_defs.items()):
        unknown = _unknown_keywords(sub, dptr)
        if '#' + dptr in outside:
            diff.add(dptr, 'type-changed', 'an added definition is referenced from a position that existed')
        elif unknown:
            for u in unknown: diff.add(u, 'unclassified', 'a keyword inside an added subtree is outside the census')
        elif dptr not in absorbed:
            diff.add(dptr, 'added-unreferenced-def')

    for ptr, name, owner, sub in diff.additions:
        parent = ptr.rsplit('/properties/', 1)[0]
        unknown = _unknown_keywords(sub, ptr)
        if name in (owner.get('required') or []): diff.add(ptr, 'made-required', 'a property was added as required; a required field is a new id')
        elif unknown:
            for u in unknown: diff.add(u, 'unclassified', 'a keyword inside an added subtree is outside the census')
        elif plain.get(parent) != {True} or not _open_to_addition(owner):
            diff.add(ptr, 'closed-object-widened', 'a property was added at a position that is not a plain properties position')
        elif cid in strict_readers:
            diff.add(ptr, 'closed-object-widened', 'a property was added to a contract a reader reads strictly on purpose; a new field is a new id')
        elif not minor:
            diff.add(ptr, 'closed-object-widened', 'a property was added to a closed object without the minor version rising')
        elif cid not in reader_ids:
            diff.add(ptr, 'no-reader-proof', 'a property was added to a contract no reader row proves the pinned SDK reads')
        else:
            diff.add(ptr, 'added-optional-property')
    return diff.findings, (v_old, v_new, minor)


def _json_diff(a, b, ptr, out):
    if a == b: return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str): _json_diff(a.get(k), b.get(k), f'{ptr}/{_esc(k)}', out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)): _json_diff(x, y, f'{ptr}/{i}', out)
    else:
        out.append((ptr, a, b))


def _profile_findings(cid, old, new):
    out, diffs = [], []
    _json_diff(old, new, '', diffs)
    for ptr, a, b in diffs:
        parts = ptr.split('/')
        if len(parts) > 1 and parts[1] in PROFILE_NAMED: cls = 'named-id-changed'
        elif parts[-1] in PROFILE_MEANING and isinstance(a, str) and isinstance(b, str): cls = 'meaning-text-changed'
        else: cls = 'document-changed'
        out.append(_finding('profiles', cid, ptr, cls, old=a, new=b))
    return out


# ---- the classifier ------------------------------------------------------------------------------------------------

def classify(frozen, current, *, strict_readers=(), reader_ids=(), reviewed=(), baseline='supported-1'):
    """Every difference between two closures (closure()'s first value), one Finding each, in a stable order.

    strict_readers: schema ids read by a reader that is strict on purpose; reader_ids: schema ids with a C4 reader row;
    reviewed: the rows of supported-changes.json; baseline: the frozen copy's name."""
    findings, versions = [], {}
    for key in sorted(frozen):
        group, cid = key
        if key not in current:
            findings.append(_finding(group, cid, '', 'named-id-changed', 'the contract is no longer in the closure')); continue
        old, new = frozen[key], current[key]
        if group == 'schemas':
            found, versions[key] = _schema_findings(group, cid, old, new, set(strict_readers), set(reader_ids))
            findings += found
        elif group == 'profiles':
            findings += _profile_findings(cid, old['body'], new['body'])
        elif old['body'] != new['body']:
            findings.append(_finding(group, cid, '', 'document-changed', old=old['body'], new=new['body']))

    findings = _apply_reviews(findings, reviewed, baseline)

    for key, (v_old, v_new, minor) in sorted(versions.items()):
        if v_old == v_new: continue
        group, cid = key
        own = [f for f in findings if (f.group, f.id) == key]
        admitted = any(f.cls == 'added-optional-property' for f in own)
        passing = any(f.verdict == 'pass' for f in own)
        patch = bool(v_old and v_new and len(v_old) == len(v_new) == 3 and v_new[:2] == v_old[:2] and v_new[2] > v_old[2])
        if minor and admitted or patch and passing:
            findings.append(_finding(group, cid, '/x-ophiolite/version', 'entry-version'))
        else:
            findings.append(_finding(group, cid, '/x-ophiolite/version', 'entry-version',
                                     'the version changed without an additive change that needs it', verdict='fail'))
    return findings


def _apply_reviews(findings, reviewed, baseline):
    by_key, extra, seen = {}, [], set()
    for f in findings: by_key.setdefault((f.group, f.id, f.pointer), []).append(f)
    used = {}
    for row in reviewed:
        key = (row.get('group'), row.get('id'), row.get('pointer'))
        label = f'{key[0]} {key[1]}'
        where = key[2]
        if key in seen:
            extra.append(_finding(*key, 'duplicate-review', 'a second reviewed row names the same pointer')); continue
        seen.add(key)
        wanted = REVIEW_KINDS.get(row.get('kind'))
        matches = by_key.get(key, [])
        if wanted is None or matches and not any(f.cls == wanted for f in matches):
            extra.append(_finding(*key, 'forbidden-review', 'a reviewed row may only bind changed meaning text or a changed document')); continue
        target = [f for f in matches if f.cls == wanted]
        if not target:
            extra.append(_finding(*key, 'unused-review', f'no difference of {label} at {where or "/"} needs this reviewed row')); continue
        f = target[0]
        if row.get('baseline') != baseline or row.get('old_sha256') != value_digest(f.old):
            extra.append(_finding(*key, 'stale-review', 'the reviewed row does not bind the baseline value')); continue
        if row.get('new_sha256') != value_digest(f.new):
            extra.append(_finding(*key, 'stale-review', 'the reviewed row does not bind the current value')); continue
        used[id(f)] = row
    out = [Finding(f.group, f.id, f.pointer, f.cls, 'pass', f.sentence.replace('without a reviewed row', 'with a bound reviewed row'), f.old, f.new)
           if id(f) in used else f for f in findings]
    return out + extra


def failures(findings):
    return [f for f in findings if f.verdict != 'pass']
