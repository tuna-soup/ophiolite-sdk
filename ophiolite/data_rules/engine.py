"""E144 (slice 0): the data-rule engine's validity stages, `canonical` and the registry check.

Standard library only, and nothing from `asset_connectors`: the SDK carries this file byte for byte (slice 1, D2), so
the gateway and an offline run judge a document and write a block identically. Callers pass what the engine may not
look up itself: the reader-registry profiles, the unit symbols, the registry index and a `read(path)` that answers the
bytes of a registry-relative path (or None).

Stages (strategy §2), each returning None or the first refusal `{stage, code, field, sentence}`:
- `registered(raw, snapshot)`: the submitted bytes hash to the snapshot's entry for the document's id (R1-4: a
  reformatted copy is another document);
- `consistent_rule(doc, profiles, units)` and `consistent_results(block, rules, profiles)`: what the schema cannot say;
- `check_registry(index, read)`: the index, its immutable snapshots and every listed rule file.
The schema stage is the caller's (the published JSON Schema; the gateway's Pydantic models).
"""
import hashlib
import json
import math
import re

INDEX = 'ophiolite.data-rules/1'
SNAPSHOT = 'ophiolite.data-rules-snapshot/1'
SEMVER = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
RULE_ID = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*/[1-9][0-9]*$')
RULE_PATH = re.compile(r'^rules/[a-z][a-z0-9]*(-[a-z0-9]+)*\.json$')
HEX = re.compile(r'^[0-9a-f]{64}$')
NUMERIC = ('quantity', 'number', 'integer')
RESERVED = ('count', 'first')
NOT_A_RULE_KIND = ('well-residual/1',)  # read with ophiolite.residuals, never by a data rule
CONTEXT_ONLY = ('offline', 'no-context')  # not-applicable reasons only a project-context rule may give

SENTENCES = {
    'not-json': 'The document is not JSON.',
    'unregistered-id': 'No released rule has this id.',
    'bytes-differ': 'The document differs from the released rule with this id.',
    'registry-unknown': 'No rule registry with this version was released.',
    'unknown-kind': 'This kind is not one Ophiolite reads.',
    'well-residual-kind': 'Residual results are not checked by data rules.',
    'context-on-file-local': 'A rule that reads one file has no context kinds.',
    'context-missing': 'A rule that reads the project names the kinds it reads.',
    'parameter-names-duplicated': 'Two parameters have the same name.',
    'parameter-reserved': 'This parameter name is reserved for the sentence.',
    'unit-unknown': 'This unit is not in the units table.',
    'unit-not-quantity': 'Only a quantity has a unit.',
    'default-type': 'The default is not of the parameter\'s type.',
    'integer-default-fractional': 'An integer parameter\'s default is a whole number.',
    'bounds-not-numeric': 'Only a number has a minimum or a maximum.',
    'reversed-bounds': 'The minimum is above the maximum.',
    'default-below-minimum': 'The default is below the minimum.',
    'default-above-maximum': 'The default is above the maximum.',
    'compare-missing': 'A number compared with data says whether the comparison is inclusive or exclusive.',
    'compare-not-numeric': 'Only a number is compared with data.',
    'choices-missing': 'A choice lists its choices.',
    'choices-not-choice': 'Only a choice lists choices.',
    'choice-default-not-listed': 'The default is not one of the choices.',
    'brace-unbalanced': 'A brace in the sentence is not closed or not opened.',
    'placeholder-empty': 'The sentence has an empty placeholder.',
    'format-spec': 'A placeholder names a value only, with no format.',
    'placeholder-unknown': 'The sentence names a value the rule does not have.',
    'first-without-examples': 'The sentence names the first example, but the rule keeps none.',
    'kind-unknown': 'This kind is not one Ophiolite reads.',
    'duplicate-rule': 'A rule is listed twice.',
    'unexpected-rule': 'This rule does not apply to the version\'s kind in this registry.',
    'missing-rule': 'A rule that applies to this kind has no result.',
    'out-of-order': 'Results are ordered by rule.',
    'passed-with-count': 'A passed rule counts nothing.',
    'passed-with-examples': 'A passed rule has no examples.',
    'reason-on-result': 'Only a rule that did not apply gives a reason.',
    'failed-without-count': 'A failed rule counts at least one.',
    'failed-without-example': 'A failed rule shows at least one example.',
    'examples-above-count': 'There are more examples than failures.',
    'rows-not-increasing': 'Examples are in the file\'s order, each on a later row.',
    'not-applicable-with-count': 'A rule that did not apply counts nothing.',
    'not-applicable-with-examples': 'A rule that did not apply has no examples.',
    'reason-missing': 'A rule that did not apply says why.',
    'parameter-missing': 'A parameter of the rule has no value as run.',
    'parameter-extra': 'This parameter is not one of the rule\'s.',
    'parameter-type': 'This value is not of the parameter\'s type.',
    'parameter-out-of-bounds': 'This value is outside the parameter\'s range.',
    'offline-on-file-local': 'A rule that reads one file runs offline.',
    'no-context-on-file-local': 'A rule that reads one file needs no context.',
    'context-on-not-applicable': 'A rule that did not apply read no context.',
    'context-empty': 'A rule that reads the project names the versions it read.',
    'context-kind-unexpected': 'The rule does not read this kind.',
    'context-duplicated': 'A context version is named twice.',
    'context-out-of-order': 'Context versions are ordered by kind, item and revision.',
    'index-shape': 'The registry index is not in its published form.',
    'version-invalid': 'A registry version is not a semantic version.',
    'versions-not-ascending': 'Registry versions ascend.',
    'snapshot-path': 'A snapshot lives at registries/<version>.json.',
    'digest-malformed': 'A digest is 64 lowercase hexadecimal characters.',
    'file-missing': 'A listed file is missing.',
    'snapshot-digest-wrong': 'A snapshot differs from its digest.',
    'snapshot-shape': 'A registry snapshot is not in its published form.',
    'current-not-last': 'The current registry is the last snapshot.',
    'rule-id-invalid': 'A rule id is a kebab name and a version.',
    'path-escape': 'A rule file lives under rules/.',
    'ids-duplicated': 'A rule is listed twice in one snapshot.',
    'ids-unordered': 'Rules are listed in id order.',
    'rule-digest-wrong': 'A rule file differs from its digest.',
    'rule-dropped': 'A snapshot keeps every rule of the one before it.',
    'rule-changed-between-snapshots': 'A released rule never changes between snapshots.',
    'since-wrong': 'A rule\'s since is the snapshot it first appears in.',
}


def refusal(stage, code, field):
    return {'stage': stage, 'code': code, 'field': field, 'sentence': SENTENCES[code]}


def canonical(value):
    """The bytes a block is compared and stored as: sorted keys, no spaces, UTF-8, never NaN or infinity."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def _constant(name):
    raise ValueError('not JSON: %s' % name)


def parse(raw):
    """JSON as RFC 8259 has it: NaN and Infinity are refused (ValueError), as is any non-UTF-8 byte."""
    return json.loads(raw.decode('utf-8'), parse_constant=_constant)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _version(text):
    return tuple(int(p) for p in text.split('.'))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# --- registered -------------------------------------------------------------------------------------------------------

def registered(raw, snapshot):
    """The document whose bytes are `raw` is the snapshot's rule with its id, byte for byte."""
    doc = parse(raw)
    entry = next((r for r in snapshot['rules'] if r['id'] == doc.get('id')), None)
    if entry is None: return refusal('registered', 'unregistered-id', 'id')
    if sha256(raw) != entry['sha256']: return refusal('registered', 'bytes-differ', 'id')
    return None


def snapshot_named(index, version, read):
    """The snapshot a block names, parsed, or None when the index has no such version."""
    entry = next((s for s in index['snapshots'] if s['registry_version'] == version), None)
    if entry is None: return None
    return parse(read(entry['path']))


def rules_of(snapshot, read):
    """The snapshot's rule documents, parsed, in id order."""
    return [parse(read(r['path'])) for r in snapshot['rules']]


def rules_for(kind, rules):
    return sorted((r for r in rules if kind in r['kinds']), key=lambda r: r['id'])


# --- consistent: a rule document --------------------------------------------------------------------------------------

def template_refusal(template, names, examples, field='words.template'):
    """None, or the first fault of a sentence template: `{{`/`}}` are braces; `{count}`, `{first}` and a parameter name are
    the only placeholders; no format spec or conversion; `{first}` needs examples."""
    allowed, used, i = set(RESERVED) | set(names), set(), 0
    while i < len(template):
        c = template[i]
        if c in '{}' and template[i:i + 2] in ('{{', '}}'):
            i += 2
            continue
        if c == '}': return refusal('consistent', 'brace-unbalanced', field)
        if c == '{':
            end = template.find('}', i + 1)
            inner = template[i + 1:end] if end != -1 else None
            if inner is None or '{' in inner: return refusal('consistent', 'brace-unbalanced', field)
            if inner == '': return refusal('consistent', 'placeholder-empty', field)
            if ':' in inner or '!' in inner: return refusal('consistent', 'format-spec', field)
            if inner not in allowed: return refusal('consistent', 'placeholder-unknown', field)
            used.add(inner)
            i = end + 1
            continue
        i += 1
    if 'first' in used and examples == 'none': return refusal('consistent', 'first-without-examples', 'words.examples')
    return None


def _parameter_refusal(p, at, units):
    numeric, kind = p['type'] in NUMERIC, p['type']
    if kind == 'quantity':
        if p['unit'] not in units: return refusal('consistent', 'unit-unknown', at + '.unit')
    elif p['unit'] is not None: return refusal('consistent', 'unit-not-quantity', at + '.unit')
    d = p['default']
    if numeric and not _is_number(d) or kind == 'choice' and not isinstance(d, str) or kind == 'boolean' and not isinstance(d, bool):
        return refusal('consistent', 'default-type', at + '.default')
    if kind == 'integer' and not float(d).is_integer(): return refusal('consistent', 'integer-default-fractional', at + '.default')
    low, high = p['minimum'], p['maximum']
    if not numeric and (low is not None or high is not None):
        return refusal('consistent', 'bounds-not-numeric', at + ('.minimum' if low is not None else '.maximum'))
    if low is not None and high is not None and low > high: return refusal('consistent', 'reversed-bounds', at + '.minimum')
    if low is not None and d < low: return refusal('consistent', 'default-below-minimum', at + '.default')
    if high is not None and d > high: return refusal('consistent', 'default-above-maximum', at + '.default')
    if numeric and p['compare'] is None: return refusal('consistent', 'compare-missing', at + '.compare')
    if not numeric and p['compare'] is not None: return refusal('consistent', 'compare-not-numeric', at + '.compare')
    if kind == 'choice':
        if p['choices'] is None: return refusal('consistent', 'choices-missing', at + '.choices')
        if d not in p['choices']: return refusal('consistent', 'choice-default-not-listed', at + '.default')
    elif p['choices'] is not None: return refusal('consistent', 'choices-not-choice', at + '.choices')
    return None


def consistent_rule(doc, profiles, units):
    """What a schema-valid rule document must also be: kinds Ophiolite reads, context kinds exactly for a project-context
    rule, parameters whose defaults, bounds, units and comparison agree, and a sentence that names only what it has."""
    for i, kind in enumerate(doc['kinds']):
        if kind in NOT_A_RULE_KIND: return refusal('consistent', 'well-residual-kind', 'kinds[%d]' % i)
        if kind not in profiles: return refusal('consistent', 'unknown-kind', 'kinds[%d]' % i)
    context = doc['context_kinds']
    if doc['class'] == 'file-local' and context is not None: return refusal('consistent', 'context-on-file-local', 'context_kinds')
    if doc['class'] == 'project-context':
        if context is None: return refusal('consistent', 'context-missing', 'context_kinds')
        for i, kind in enumerate(context):
            if kind in NOT_A_RULE_KIND or kind not in profiles: return refusal('consistent', 'unknown-kind', 'context_kinds[%d]' % i)
    names = [p['name'] for p in doc['parameters']]
    for i, p in enumerate(doc['parameters']):
        at = 'parameters[%d]' % i
        if p['name'] in names[:i]: return refusal('consistent', 'parameter-names-duplicated', at + '.name')
        if p['name'] in RESERVED: return refusal('consistent', 'parameter-reserved', at + '.name')
        found = _parameter_refusal(p, at, units)
        if found: return found
    return template_refusal(doc['words']['template'], names, doc['words']['examples'])


# --- consistent: a result block ---------------------------------------------------------------------------------------

def _value_refusal(p, value, at):
    kind = p['type']
    if kind in NUMERIC:
        if not _is_number(value) or kind == 'integer' and not float(value).is_integer():
            return refusal('consistent', 'parameter-type', at)
        if p['minimum'] is not None and value < p['minimum'] or p['maximum'] is not None and value > p['maximum']:
            return refusal('consistent', 'parameter-out-of-bounds', at)
    elif kind == 'choice':
        if not isinstance(value, str): return refusal('consistent', 'parameter-type', at)
        if value not in p['choices']: return refusal('consistent', 'parameter-out-of-bounds', at)
    elif not isinstance(value, bool): return refusal('consistent', 'parameter-type', at)
    return None


def _state_refusal(result, at):
    state, count, examples, reason = result['state'], result['count'], result['examples'], result['reason']
    if state == 'passed':
        if count != 0: return refusal('consistent', 'passed-with-count', at + '.count')
        if examples: return refusal('consistent', 'passed-with-examples', at + '.examples')
        if reason is not None: return refusal('consistent', 'reason-on-result', at + '.reason')
    elif state == 'failed':
        if count is None or count < 1: return refusal('consistent', 'failed-without-count', at + '.count')
        if not examples: return refusal('consistent', 'failed-without-example', at + '.examples')
        if len(examples) > min(5, count): return refusal('consistent', 'examples-above-count', at + '.examples')
        rows = [e['row'] for e in examples]
        if any(b <= a for a, b in zip(rows, rows[1:])): return refusal('consistent', 'rows-not-increasing', at + '.examples')
        if reason is not None: return refusal('consistent', 'reason-on-result', at + '.reason')
    else:
        if count is not None: return refusal('consistent', 'not-applicable-with-count', at + '.count')
        if examples: return refusal('consistent', 'not-applicable-with-examples', at + '.examples')
        if reason is None: return refusal('consistent', 'reason-missing', at + '.reason')
    return None


def _context_refusal(rule, result, at):
    context = result['context']
    if rule['class'] == 'file-local':
        if context is not None: return refusal('consistent', 'context-on-file-local', at + '.context')
        if result['reason'] == 'offline': return refusal('consistent', 'offline-on-file-local', at + '.reason')
        if result['reason'] == 'no-context': return refusal('consistent', 'no-context-on-file-local', at + '.reason')
        return None
    if result['state'] == 'not-applicable':
        return refusal('consistent', 'context-on-not-applicable', at + '.context') if context is not None else None
    if not context: return refusal('consistent', 'context-empty', at + '.context')
    keys = []
    for j, c in enumerate(context):
        if c['kind'] not in rule['context_kinds']: return refusal('consistent', 'context-kind-unexpected', '%s.context[%d].kind' % (at, j))
        if (c['asset_id'], c['revision']) in [(k[1], k[2]) for k in keys]:
            return refusal('consistent', 'context-duplicated', '%s.context[%d]' % (at, j))
        keys.append((c['kind'], c['asset_id'], c['revision']))
    if keys != sorted(keys): return refusal('consistent', 'context-out-of-order', at + '.context')
    return None  # E144 s1b D6: a rule reads one of its context kinds or several; no kind must appear


def consistent_results(block, rules, profiles):
    """What a schema-valid block must also be against the rules of the snapshot it names: one result per rule that
    applies to its kind, in rule order, each state with its count, examples and reason, the parameters as run within
    the rule's, and context exactly where a project-context rule read some."""
    if block['kind'] not in profiles: return refusal('consistent', 'kind-unknown', 'kind')
    expected = [r['id'] for r in rules_for(block['kind'], rules)]
    ids = [r['rule'] for r in block['results']]
    for i, rule in enumerate(ids):
        if rule in ids[:i]: return refusal('consistent', 'duplicate-rule', 'results[%d].rule' % i)
        if rule not in expected: return refusal('consistent', 'unexpected-rule', 'results[%d].rule' % i)
    for rule in expected:
        if rule not in ids: return refusal('consistent', 'missing-rule', 'results')
    if ids != sorted(ids): return refusal('consistent', 'out-of-order', 'results')
    by_id = {r['id']: r for r in rules}
    for i, result in enumerate(block['results']):
        at, rule = 'results[%d]' % i, by_id[result['rule']]
        found = _state_refusal(result, at)
        if found: return found
        names = [p['name'] for p in rule['parameters']]
        for name in names:
            if name not in result['parameters']: return refusal('consistent', 'parameter-missing', '%s.parameters.%s' % (at, name))
        for name, value in result['parameters'].items():
            if name not in names: return refusal('consistent', 'parameter-extra', '%s.parameters.%s' % (at, name))
            found = _value_refusal(rule['parameters'][names.index(name)], value, '%s.parameters.%s' % (at, name))
            if found: return found
        found = _context_refusal(rule, result, at)
        if found: return found
    return None


# --- the registry -----------------------------------------------------------------------------------------------------

def _snapshot_refusal(entry, snapshot, at, read, seen):
    if not isinstance(snapshot, dict) or set(snapshot) != {'schema', 'registry_version', 'rules'} or snapshot['schema'] != SNAPSHOT \
            or snapshot['registry_version'] != entry['registry_version'] or not isinstance(snapshot['rules'], list):
        return refusal('registry', 'snapshot-shape', at)
    ids = []
    for j, rule in enumerate(snapshot['rules']):
        here = '%s.rules[%d]' % (at, j)
        if not isinstance(rule, dict) or set(rule) != {'id', 'path', 'sha256'}: return refusal('registry', 'snapshot-shape', here)
        if not isinstance(rule['id'], str) or not RULE_ID.match(rule['id']): return refusal('registry', 'rule-id-invalid', here + '.id')
        if not isinstance(rule['path'], str) or not RULE_PATH.match(rule['path']): return refusal('registry', 'path-escape', here + '.path')
        if not isinstance(rule['sha256'], str) or not HEX.match(rule['sha256']): return refusal('registry', 'digest-malformed', here + '.sha256')
        if rule['id'] in ids: return refusal('registry', 'ids-duplicated', here + '.id')
        if ids and rule['id'] < ids[-1]: return refusal('registry', 'ids-unordered', here + '.id')
        ids.append(rule['id'])
        raw = read(rule['path'])
        if raw is None: return refusal('registry', 'file-missing', here + '.path')
        if sha256(raw) != rule['sha256']: return refusal('registry', 'rule-digest-wrong', here + '.sha256')
        if rule['id'] in seen and seen[rule['id']] != rule['sha256']:
            return refusal('registry', 'rule-changed-between-snapshots', here + '.sha256')
        if rule['id'] not in seen:
            seen[rule['id']] = rule['sha256']
            if parse(raw).get('since') != entry['registry_version']: return refusal('registry', 'since-wrong', here + '.id')
    return None


def check_registry(index, read):
    """None, or the first fault of the index, its snapshots or a listed rule file. Snapshots are immutable: each keeps
    the rules of the one before, byte for byte, and a rule's `since` is the snapshot it first appears in."""
    if not isinstance(index, dict) or set(index) != {'schema', 'id', 'current', 'snapshots'} or index['schema'] != INDEX \
            or index['id'] != INDEX or not isinstance(index['snapshots'], list) or not index['snapshots']:
        return refusal('registry', 'index-shape', '')
    seen, previous, previous_ids = {}, None, []
    for i, entry in enumerate(index['snapshots']):
        at = 'snapshots[%d]' % i
        if not isinstance(entry, dict) or set(entry) != {'registry_version', 'path', 'sha256'}: return refusal('registry', 'index-shape', at)
        version = entry['registry_version']
        if not isinstance(version, str) or not SEMVER.match(version): return refusal('registry', 'version-invalid', at + '.registry_version')
        if previous is not None and _version(version) <= _version(previous): return refusal('registry', 'versions-not-ascending', at + '.registry_version')
        if entry['path'] != 'registries/%s.json' % version: return refusal('registry', 'snapshot-path', at + '.path')
        if not isinstance(entry['sha256'], str) or not HEX.match(entry['sha256']): return refusal('registry', 'digest-malformed', at + '.sha256')
        raw = read(entry['path'])
        if raw is None: return refusal('registry', 'file-missing', at + '.path')
        if sha256(raw) != entry['sha256']: return refusal('registry', 'snapshot-digest-wrong', at + '.sha256')
        snapshot = parse(raw)
        found = _snapshot_refusal(entry, snapshot, at, read, seen)
        if found: return found
        ids = [r['id'] for r in snapshot['rules']]
        if any(r not in ids for r in previous_ids): return refusal('registry', 'rule-dropped', at)
        previous, previous_ids = version, ids
    if index['current'] != previous: return refusal('registry', 'current-not-last', 'current')
    return None


# --- the run (slice 1) ------------------------------------------------------------------------------------------------

RESULTS = 'ophiolite.rule-results/1'
EXAMPLES = 5


def finite(value):
    """A sample as a block holds it: a float, or None for a missing (NaN) one."""
    return None if value is None or value != value else float(value)


class Failures:
    """What an evaluator found, in row order: every failure counted, the first five kept as examples."""

    def __init__(self):
        self.count, self.examples = 0, []

    def add(self, row, depth, value):
        self.count += 1
        if len(self.examples) < EXAMPLES:
            self.examples.append({'row': row, 'depth': finite(depth), 'value': value if isinstance(value, str) else finite(value)})


def _result(rule, parameters, found, context=None):
    result = {'rule': rule['id'], 'parameters': parameters, 'context': None}
    if isinstance(found, str):
        result.update(state='not-applicable', count=None, examples=[], reason=found)
    else:
        result.update(state='failed' if found.count else 'passed', count=found.count, examples=found.examples, reason=None,
                      context=context)
    return result


def context_results(rules, kind, data, *, quantities, context):
    """E144 s1b: the results of the project-context rules among `rules_for(kind, rules)`, in id order. `context` None is
    an offline run (`offline`); `{'path': None}` is a project with no usable path (`no-context`); otherwise
    `{'version': {asset_id, revision, kind}, 'path': {depth_unit, datum, first, last}}`, named by a passed or failed
    result only (a `no-context` from the evaluator keeps context null)."""
    from . import tops
    results = []
    for rule in rules_for(kind, rules):
        if rule['class'] != 'project-context': continue
        parameters = {p['name']: p['default'] for p in rule['parameters']}
        if context is None: found = 'offline'
        elif context.get('path') is None: found = 'no-context'
        else: found = tops.CONTEXT_EVALUATORS[rule['id']](data, parameters, quantities, context)
        results.append(_result(rule, parameters, found, None if isinstance(found, str) else [context['version']]))
    return results


def run(rules, kind, data, *, registry_version, quantities, context=None):
    """The block for one file: the rules of `rules` (one snapshot's documents) whose kinds include `kind`, in id order,
    each run with its defaults over `data`, the neutral input (strategy §2). `quantities` is the parsed
    `ophiolite.quantities/1` document. An evaluator answers Failures, or the reason the rule does not apply. A
    project-context rule runs over `context` (see `context_results`; None offline)."""
    from . import logs, spatial, tops, trajectories
    evaluators = dict(logs.EVALUATORS, **spatial.EVALUATORS, **tops.EVALUATORS, **trajectories.EVALUATORS)
    contextual = {r['rule']: r for r in context_results(rules, kind, data, quantities=quantities, context=context)}
    results = []
    for rule in rules_for(kind, rules):
        if rule['id'] in contextual:
            results.append(contextual[rule['id']])
            continue
        parameters = {p['name']: p['default'] for p in rule['parameters']}
        results.append(_result(rule, parameters, evaluators[rule['id']](data, parameters, quantities)))
    return {'schema': RESULTS, 'kind': kind, 'registry_version': registry_version, 'results': results}
