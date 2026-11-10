"""ophiolite.mapper-validator/1 (E116): the one validator for a mapper recipe and a project folder, and the pure rules
ophiolite-mapper write applies (the effective recipe, the refusal order, binding acknowledgements).

The Platform tests and the ophiolite-mapper box run this same file (the box's copy, ophiolite_mapper/contract/, is
byte-identical), loaded from its source text or imported; it reads its documents from beside itself:

    module = types.ModuleType('ophiolite_mapper_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). recipe-schema.json, folder-schema.json and (1.3.0) reviewed-schema.json give the
structure, applied here by a
small reader of the JSON Schema keywords they use (if/then are applied as the named rules below instead); rules.json
gives every list and sentence; mapping-check-words.json gives each finding code's severity. Nothing here reads a
source, a table or a file: write's digests, checks and rows are slice 1's, and they hand their results to these
functions as data. 1.4.0 (E169 s0): a recipe for an exported bundle, manifest's refusals from what a bundle reader
found (bundle_refusal) and the export report (check_export_report, export-report-schema.json); the bundle itself is
read by the box, which hands its findings here as data.
"""
import copy
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECIPE = 'ophiolite.mapper-recipe/1'
FOLDER = 'ophiolite.project-folder/1'
REVIEWED = 'ophiolite.mapper-reviewed/1'
EXPORT_REPORT = 'ophiolite.osdu-export-report/1'


def _read(name, *fallback):
    path = HERE / name
    if not path.exists() and fallback: path = HERE.joinpath(*fallback)
    return json.loads(path.read_text(encoding='utf-8'))


RULES = _read('rules.json')
RULES_VERSION = RULES['rules_version']
WORDS = RULES['words']
RECIPE_SCHEMA = _read('recipe-schema.json')
FOLDER_SCHEMA = _read('folder-schema.json')
REVIEWED_SCHEMA = _read('reviewed-schema.json')
EXPORT_REPORT_SCHEMA = _read('export-report-schema.json')
# Beside this file in the box; in the Platform tree the mirrored vocabulary (contracts/vocabulary/v1).
CHECK_WORDS = _read('mapping-check-words.json', '..', '..', 'vocabulary', 'v1', 'mapping-check-words.json')
SEVERITY = {code: row['severity'] for code, row in CHECK_WORDS['codes'].items()}
APPLIED = frozenset(RULES['applied_without_decision'])
ENTITY_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$')
PAYLOAD = re.compile(r'^sha256:[0-9a-f]{64}$')
AT = re.compile(r'^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))$')


class MapperError(ValueError):
    """The first problem found: a code (schema-<keyword> for structure, a rule's name otherwise) and a JSON path."""

    def __init__(self, code, path):
        super().__init__(f'{code} at {path}')
        self.code, self.path = code, path


# ---- structure ------------------------------------------------------------------------------------------------------

def _kind(value):
    if value is None: return 'null'
    if isinstance(value, bool): return 'boolean'
    if isinstance(value, int): return 'integer'
    if isinstance(value, float): return 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'array'
    if isinstance(value, dict): return 'object'
    return 'unknown'


def _deref(node, root):
    while isinstance(node, dict) and '$ref' in node:
        target = root
        for part in node['$ref'].removeprefix('#/').split('/'): target = target[part]
        node = target
    return node


def _types(node):
    t = node.get('type')
    if t is None: return None
    return set(t) if isinstance(t, list) else {t}


def _type_ok(kind, allowed):
    return kind in allowed or (kind == 'integer' and 'number' in allowed)


def structure(node, value, root, path='$'):
    """Apply the JSON Schema keywords the mapper schemas use; raise MapperError('schema-<keyword>', path)."""
    node = _deref(node, root)
    if 'anyOf' in node:
        branches = [_deref(b, root) for b in node['anyOf']]
        fitting = [b for b in branches if _types(b) is None or _type_ok(_kind(value), _types(b))]
        if len(fitting) == 1: structure(fitting[0], value, root, path)
        elif not any(_passes(b, value, root) for b in fitting): raise MapperError('schema-anyOf', path)
    kind = _kind(value)
    allowed = _types(node)
    if allowed is not None and not _type_ok(kind, allowed): raise MapperError('schema-type', path)
    if 'const' in node and (value != node['const'] or _kind(node['const']) != kind): raise MapperError('schema-const', path)
    if 'enum' in node and value not in node['enum']: raise MapperError('schema-enum', path)
    if kind == 'string':
        if len(value) < node.get('minLength', 0) or len(value) > node.get('maxLength', len(value)): raise MapperError('schema-length', path)
        if 'pattern' in node and not re.search(node['pattern'], value): raise MapperError('schema-pattern', path)
    if kind in ('integer', 'number'):
        if value < node.get('minimum', value) or value > node.get('maximum', value): raise MapperError('schema-range', path)
    if kind == 'array':
        if len(value) < node.get('minItems', 0) or len(value) > node.get('maxItems', len(value)): raise MapperError('schema-items', path)
        if 'items' in node:
            for i, item in enumerate(value): structure(node['items'], item, root, f'{path}[{i}]')
    if kind == 'object':
        if len(value) > node.get('maxProperties', len(value)): raise MapperError('schema-items', path)
        for key in node.get('required', ()):
            if key not in value: raise MapperError('schema-required', f'{path}.{key}')
        props = node.get('properties', {})
        extra = node.get('additionalProperties', True)
        for key, item in value.items():
            if key in props: structure(props[key], item, root, f'{path}.{key}')
            elif extra is False: raise MapperError('schema-additionalProperties', f'{path}.{key}')
            elif isinstance(extra, dict): structure(extra, item, root, f'{path}.{key}')


def _passes(node, value, root):
    try: structure(node, value, root)
    except MapperError: return False
    return True


def at_valid(text):
    """RFC 3339 date-time with a zone (JSON Schema's format is an annotation only, so it is checked here)."""
    m = AT.match(text) if isinstance(text, str) else None
    if not m: return False
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    try:
        datetime(year, month, day, hour, minute, second)
        if m.group(8) != 'Z':
            hours, minutes = int(m.group(9)), int(m.group(10))
            if minutes > 59: return False
            timezone(timedelta(hours=hours, minutes=minutes))
    except ValueError:
        return False
    return True


def endpoint_clean(text):
    """https://host[:port][/path] and nothing else: no user or password, no query, no fragment. 1.4 (E116 s4): or plain
    http to http://127.0.0.1:<port> exactly, the bucket client's own loopback rule (no other loopback form, no IPv6)."""
    try: parts = urllib.parse.urlsplit(text)
    except ValueError: return False
    if parts.scheme not in ('https', 'http') or not parts.hostname or '@' in parts.netloc: return False
    if parts.query or parts.fragment or '?' in text or '#' in text: return False
    try: port = parts.port
    except ValueError: return False
    if parts.scheme == 'http' and (parts.netloc != f'127.0.0.1:{port}' or port is None or parts.path not in ('', '/')): return False
    return True


# ---- the recipe -----------------------------------------------------------------------------------------------------

def _decision(row, allowed, path, value_key=None):
    d = row.get('decision')
    if d is None: return None
    if not at_valid(d['at']): raise MapperError('at-invalid', f'{path}.decision.at')
    action = d['action']
    if action not in allowed: raise MapperError('decision-misplaced', f'{path}.decision.action')
    if (action == 'choose') != ('column' in d): raise MapperError('choose-column', f'{path}.decision')
    if action == 'choose' and d['column'] is None: raise MapperError('decision-empty', f'{path}.decision.column')
    if action == 'accept' and value_key is not None and row[value_key] is None: raise MapperError('decision-empty', f'{path}.decision')
    return action


def workbook(recipe):
    """1.3.0: whether the recipe's source is a file named as a workbook (rules.json reading.workbook_suffixes)."""
    source = recipe['source']
    suffixes = tuple(RULES['reading']['workbook_suffixes'])
    return source['kind'] == 'file' and source['locator']['path'].lower().endswith(suffixes)


def _check_reading(recipe, eff):
    """1.3.0: reading rows belong to a file and a workbook needs its sheet and header row; each row's value and evidence
    are its name's (rules.json reading.rows), and a decision on it is an accept of a value."""
    rows = recipe.get('reading')
    if rows is not None and recipe['source']['kind'] != 'file': raise MapperError('reading-misplaced', '$.reading')
    seen = set()
    for i, row in enumerate(rows or ()):
        path = f'$.reading[{i}]'
        if row['name'] in seen: raise MapperError('reading-repeated', f'{path}.name')
        seen.add(row['name'])
        spec, value = RULES['reading']['rows'][row['name']], row['value']
        if value is None: ok = spec['nullable']
        elif spec['type'] == 'integer': ok = isinstance(value, int) and not isinstance(value, bool) and value >= spec['min']
        else: ok = isinstance(value, str) and len(value) <= spec['max']
        if not ok: raise MapperError('reading-value', f'{path}.value')
        if row['evidence'] not in spec['evidence']: raise MapperError('reading-evidence', f'{path}.evidence')
        _decision(row, eff['reading']['actions'], path, 'value')
    if workbook(recipe) and not {'sheet', 'header_row'} <= seen: raise MapperError('reading-missing', '$.reading')


def over(source):
    """What a source's digest is taken over (rules.json over); 1.4.0: an exported bundle's is its bytes when the path
    names a .zip (bundle.bytes_suffix, in any case) and its members when it names a folder."""
    rule = RULES['bundle']
    if source['kind'] == 'bundle' and source['locator']['path'].lower().endswith(rule['bytes_suffix']): return 'bytes'
    return RULES['over'][source['kind']]


def _check_bundle(recipe):
    """1.4.0: a bundle is read by portable-bundle/2 into OSDU records, and its recipe decides nothing: the bundle carries
    identity, units and nulls as exported, and manifest's refusals are the command's, never findings."""
    rule = RULES['bundle']
    if recipe['source']['reader'] != rule['reader']: raise MapperError('reader-mismatch', '$.source.reader')
    if [recipe['target']['kind'], recipe['target']['id']] != rule['target']: raise MapperError('target-mismatch', '$.target')
    if 'identity' in recipe: raise MapperError('bundle-recipe-shape', '$.identity')
    for key, empty in (('layout', None), ('fields', []), ('columns', {}), ('declarations', []), ('missing', []),
                       ('wells', []), ('findings', [])):
        if recipe[key] != empty: raise MapperError('bundle-recipe-shape', f'$.{key}')


def check_recipe(recipe):
    """Raise MapperError for the first problem of a recipe, structure first, then the rules in document order."""
    structure(RECIPE_SCHEMA, recipe, RECIPE_SCHEMA)
    eff = RULES['effective']
    if recipe['created']['rules_version'] != RULES_VERSION: raise MapperError('rules-version', '$.created.rules_version')
    if not at_valid(recipe['created']['at']): raise MapperError('at-invalid', '$.created.at')
    source = recipe['source']
    structure(RECIPE_SCHEMA['$defs'][f'locator-{source["kind"]}'], source['locator'], RECIPE_SCHEMA, '$.source.locator')
    if source['digest']['over'] != over(source): raise MapperError('over-mismatch', '$.source.digest.over')
    if source['kind'] == 'bucket-prefix' and not endpoint_clean(source['locator']['endpoint']):
        raise MapperError('locator-credentials', '$.source.locator.endpoint')
    if source['kind'] == 'bundle': _check_bundle(recipe)
    elif recipe['target']['kind'] == RULES['bundle']['target'][0]: raise MapperError('target-mismatch', '$.target.kind')
    _check_reading(recipe, eff)
    if recipe['layout'] is not None: _decision(recipe['layout'], eff['layout']['actions'], '$.layout')
    profile = recipe['target']['kind'] == 'reader-profile'
    identity = recipe.get('identity')
    if identity is not None:  # 1.2.0: external ids from a column of the table; provisional ones from the keys written
        if (identity['basis'] == 'external') != (identity['column'] is not None) or (profile and identity['basis'] != 'provisional'):
            raise MapperError('identity-basis', '$.identity')
        _decision(identity, eff['identity']['actions'], '$.identity')
    well_rules = {**eff['well'], **(eff['well-reader-profile'] if profile else {})}
    seen = set()
    for i, row in enumerate(recipe['fields']):
        path = f'$.fields[{i}]'
        if row['field'] in seen: raise MapperError('field-repeated', f'{path}.field')
        seen.add(row['field'])
        choices = [row['column']] + ([row['decision']['column']] if row['decision'] and 'column' in row['decision'] else [])
        if not row['multiple'] and any(isinstance(c, list) for c in choices): raise MapperError('column-list', path)
        # 1.3.0: a previously reviewed column says whose pick it is (reuse) and whether it is prefilled or only offered
        reviewed = row['evidence'] == 'previously-reviewed'
        if reviewed != ('reuse' in row) or reviewed != ('apply' in row):
            raise MapperError('reuse-missing' if reviewed else 'reuse-misplaced', path)
        if reviewed and row['apply'] not in RULES['reuse'][row['reuse']]: raise MapperError('reuse-apply', f'{path}.apply')
        _decision(row, eff['field']['actions'], path, 'column')
    seen = set()
    for i, row in enumerate(recipe['declarations']):
        path = f'$.declarations[{i}]'
        if row['name'] in seen: raise MapperError('declaration-repeated', f'{path}.name')
        seen.add(row['name'])
        _decision(row, eff['declaration']['actions'], path, 'value')
    seen = set()
    for i, row in enumerate(recipe['wells']):
        path = f'$.wells[{i}]'
        if row['spelling'] in seen: raise MapperError('well-repeated', f'{path}.spelling')
        seen.add(row['spelling'])
        if row['match'] != 'none' and row['canonical'] is None: raise MapperError('canonical-missing', f'{path}.canonical')
        action = _decision(row, well_rules[row['match']]['actions'], path)
        if action == 'new-entity' and row['entity'] is None: raise MapperError('decision-empty', f'{path}.entity')
        # a LAS WELL names a wellbore, which names its well; a well has no parent
        if row['entity'] is not None and row['entity']['kind'] == 'well' and 'well' in row['entity']:
            raise MapperError('decision-misplaced', f'{path}.entity.well')
    seen = set()
    for i, row in enumerate(recipe['findings']):
        path = f'$.findings[{i}]'
        if row['code'] not in SEVERITY: raise MapperError('finding-unknown', f'{path}.code')
        if (row['field'], row['code']) in seen: raise MapperError('finding-repeated', path)
        seen.add((row['field'], row['code']))
        if row['acknowledged'] is not None and not at_valid(row['acknowledged']['at']): raise MapperError('at-invalid', f'{path}.acknowledged.at')
    return recipe


def needs_identity(recipe):
    """1.2.0: whether write needs the recipe's identity decision (a table of wells, a LAS profile)."""
    return [recipe['target']['kind'], recipe['target']['id']] in RULES['identity_targets']


def effective(recipe):
    """What write applies: {mapping: the table engine's {fields, declarations, missing, columns}, layout, identity
    (the accepted identity block or None), wells: {matched: {spelling: canonical}, new: {spelling: entity}, unmatched:
    [spelling]}, undecided: [(row kind, name)]}. The snapshot (findings, evidence) only decides what applies without a
    decision; it is never applied itself. An undecided identity is ('identity', None) for the block and ('identity',
    spelling) for an exact row of a reader profile that has no new-entity decision yet."""
    undecided, fields, declarations, reading = [], {}, {}, {}
    for row in recipe.get('reading', ()):  # 1.3.0: a guessed or unstated reading choice applies only when accepted
        action = row['decision']['action'] if row['decision'] else None
        if action == 'accept' or (action is None and row['evidence'] in APPLIED): reading[row['name']] = row['value']
        else: undecided.append(('reading', row['name']))
    for row in recipe['fields']:
        d = row['decision']
        action = d['action'] if d else None
        if action is None:
            # 1.3.0: a previously reviewed column applies only when prefilled; an offered one waits for a decision
            applied = row['evidence'] in APPLIED and (row['evidence'] != 'previously-reviewed' or row['apply'] == 'prefilled')
            column = row['column'] if applied else None
            if not applied and row['required']: undecided.append(('field', row['field']))
        elif action == 'accept': column = row['column']
        elif action == 'choose': column = d['column']
        else: column = None
        fields[row['field']] = column
    for row in recipe['declarations']:
        d = row['decision']
        action = d['action'] if d else None
        if action is None:
            if row['evidence'] in APPLIED: value = row['value']
            else:
                value = None
                if row['evidence'] == 'inferred' and row['value'] is not None: undecided.append(('declaration', row['name']))
        elif action == 'accept': value = row['value']
        else: value = None
        if value is not None: declarations[row['name']] = value
    layout = recipe['layout']
    chosen = None
    if layout is not None:
        action = layout['decision']['action'] if layout['decision'] else None
        if action == 'accept' or (action is None and layout['evidence'] in APPLIED): chosen = layout['id']
        elif action is None: undecided.append(('layout', layout['id']))
    identity = recipe.get('identity')
    accepted = identity is not None and identity['decision'] is not None
    if needs_identity(recipe) and not accepted: undecided.append(('identity', None))
    profile = recipe['target']['kind'] == 'reader-profile'
    matched, new, unmatched = {}, {}, []
    for row in recipe['wells']:
        action = row['decision']['action'] if row['decision'] else None
        if action == 'new-entity': new[row['spelling']] = copy.deepcopy(row['entity'])
        elif profile and row['match'] == 'exact': undecided.append(('identity', row['spelling']))
        elif row['match'] in ('exact', 'alias') or action == 'accept-alias': matched[row['spelling']] = row['canonical']
        elif row['match'] == 'normalised' and action is None: undecided.append(('well', row['spelling']))
        else: unmatched.append(row['spelling'])
    mapping = {'fields': fields, 'declarations': declarations, 'missing': list(recipe['missing']),
               'columns': {label: dict(value) for label, value in recipe['columns'].items()}}
    return {'mapping': mapping, 'layout': chosen, 'identity': copy.deepcopy(identity) if accepted else None,
            'wells': {'matched': matched, 'new': new, 'unmatched': unmatched}, 'reading': reading, 'undecided': undecided}


UNDECIDED = {'field-undecided': ('field', 'declaration'), 'layout-undecided': ('layout',), 'alias-undecided': ('well',),
             'identity-undecided': ('identity',), 'reading-undecided': ('reading',)}


def made_with(recipe):
    """The rules_version a parsed recipe says it was made with, or None when it does not say so readably."""
    created = recipe.get('created') if isinstance(recipe, dict) else None
    version = created.get('rules_version') if isinstance(created, dict) else None
    return version if isinstance(version, str) else None


def refusal(recipe, digest_now):
    """The first of write's refusals recipe-outdated to reading-undecided, in rules.json's refusal_order, for a parsed
    recipe and the source's digest now, as (code, details), or None. recipe-missing is the command's; mapping-incomplete,
    alias-conflict and finding-unacknowledged need the table engine's results (unacknowledged below). A recipe made with
    other rules is outdated before it is judged by these ones (1.2.0): its details name the version it was made with."""
    version = made_with(recipe)
    try: check_recipe(recipe); problem = None
    except MapperError as error: problem = error
    undecided = effective(recipe)['undecided'] if problem is None else []
    for code in RULES['refusal_order']:
        if code == 'recipe-outdated' and version is not None and version != RULES_VERSION: return code, {'rules_version': version}
        if code == 'recipe-invalid' and problem is not None: return code, {'code': problem.code, 'path': problem.path}
        if problem is not None: continue
        if code == 'source-changed' and digest_now != recipe['source']['digest']['value']: return code, {}
        for kind, name in undecided:
            if kind in UNDECIDED.get(code, ()):
                if kind == 'well':
                    row = next(r for r in recipe['wells'] if r['spelling'] == name)
                    return code, {'spelling': name, 'canonical': row['canonical']}
                if kind == 'identity': return code, ({'spelling': name} if name is not None else {'path': '$.identity'})
                return code, {kind: name}
    return None


def unacknowledged(groups, recipe):
    """The engine's finding groups (diagnose's {field, code, rows, ...}) that block write: a blocking severity, taken
    from mapping-check-words and never from the group or the recipe, with rows, and no acknowledgement in the recipe
    for the same field, code and row count. Structural groups (rows None) are mapping-incomplete, not listed here."""
    blocking = set(RULES['blocking_severities'])
    bound = {(f['field'], f['code'], f['rows']) for f in recipe['findings'] if f['acknowledged'] is not None}
    return [g for g in groups if SEVERITY.get(g['code']) in blocking and g['rows'] is not None
            and (g['field'], g['code'], g['rows']) not in bound]


def sentence(code, **values):
    """The person's sentence for a refusal or a not-yet answer; values are labels the person wrote, never codes."""
    return WORDS[code].format(**values)


# ---- an exported bundle (1.4.0, E169 s0) ----------------------------------------------------------------------------

def bundle_refusal(recipe, digest_now, facts):
    """The first of manifest's refusals in rules.json's manifest_refusal_order, as (code, details), or None. FACTS is
    what the box's bundle reader found, as data: {read: None or a bundle_unreadable key, folder: whether the path is a
    project folder rather than an export, wells: whether the bundle carries its wells and wellbores, logs: [{asset_id,
    name, wellbores: how many wellbores the log is associated with}] for the logs it would write, wellbores:
    [{entity_id, name, wells: how many wells it is part of}] for the wellbores those logs name}. No edge is ever chosen
    by position: a count other than one refuses. recipe-missing is the command's. A recipe that is not a bundle's is
    recipe-invalid (source-not-bundle) after the version and structure checks."""
    order = RULES['manifest_refusal_order']
    answer = refusal(recipe, digest_now)
    if answer is not None and answer[0] in order[:order.index('source-changed')]: return answer
    if recipe['source']['kind'] != 'bundle': return 'recipe-invalid', {'code': 'source-not-bundle', 'path': '$.source.kind'}
    if answer is not None: return answer  # source-changed: a bundle recipe has nothing left undecided
    if facts['read'] is not None and facts['read'] not in RULES['bundle_unreadable']: raise ValueError(facts['read'])
    for code in order[order.index('source-changed') + 1:]:
        if code == 'bundle-unreadable' and facts['read'] is not None: return code, {'why': facts['read']}
        if code == 'bundle-is-folder' and facts['folder']: return code, {}
        if code == 'bundle-without-wells' and not facts['wells']: return code, {}
        if code == 'association-ambiguous':
            for log in facts['logs']:
                if log['wellbores'] > 1: return code, {'thing': 'log', 'asset_id': log['asset_id'], 'name': log['name']}
            for bore in facts['wellbores']:
                if bore['wells'] > 1: return code, {'thing': 'wellbore', 'entity_id': bore['entity_id'], 'name': bore['name']}
        if code == 'association-missing':
            for log in facts['logs']:
                if log['wellbores'] == 0: return code, {'asset_id': log['asset_id'], 'name': log['name']}
        if code == 'wellbore-without-well':
            for bore in facts['wellbores']:
                if bore['wells'] == 0: return code, {'entity_id': bore['entity_id'], 'name': bore['name']}
    return None


def refusal_sentence(code, details, path=None):
    """The person's sentence for one of manifest's bundle refusals from bundle_refusal's details: the reason and the
    kinds of thing in words from rules.json's closed lists, the name as exported, the path as given; never an id."""
    values = {'path': path} if path is not None else {}
    if code == 'bundle-unreadable': values['why'] = RULES['bundle_unreadable'][details['why']]
    if code == 'association-ambiguous': values.update(RULES['association_things'][details['thing']])
    if 'name' in details: values['name'] = details['name']
    return sentence(code, **values)


def unwritten_entry(reason, detail=None):
    """An unwritten asset's reason, sentence and detail: the sentence is rules.json's for the reason and names nothing;
    DETAIL (the export matrix row's own reason, technical) goes only to the report's detail field."""
    if reason not in RULES['unwritten']: raise ValueError(reason)
    return {'reason': reason, 'sentence': WORDS[reason], 'detail': detail}


def _record_kind(record_id):
    parts = record_id.split(':')
    return parts[0], parts[1]


def check_export_report(doc, recipe=None):
    """Raise MapperError for the first problem of osdu/export-report.json: structure, then the rules its schema cannot
    state. Records and unwritten partition the bundle's (asset_id, revision) pairs, no pair twice, and together count
    bundle.assets; every id has one namespace and its kind's type; a log's wellbore is a listed master; each unwritten
    sentence is rules.json's for its reason; each loss is a listed pair's, once; empty says whether each list is empty;
    the manifest's counts per kind are the masters' and the records'. RECIPE, when given, binds the bundle digest."""
    structure(EXPORT_REPORT_SCHEMA, doc, EXPORT_REPORT_SCHEMA)
    if doc['mapper']['rules_version'] != RULES_VERSION: raise MapperError('rules-version', '$.mapper.rules_version')
    namespaces, entities, bores, wells = set(), set(), set(), 0
    for i, row in enumerate(doc['masters']):
        path = f'$.masters[{i}]'
        ns, kind = _record_kind(row['record_id'])
        if kind != 'master-data--' + row['kind'].capitalize(): raise MapperError('record-kind', f'{path}.record_id')
        if row['entity_id'] in entities: raise MapperError('master-repeated', f'{path}.entity_id')
        entities.add(row['entity_id'])
        namespaces.add(ns)
        if row['kind'] == 'wellbore': bores.add(row['record_id'])
        else: wells += 1
    pairs, payloads = set(), set()
    for i, row in enumerate(doc['records']):
        path = f'$.records[{i}]'
        ns, kind = _record_kind(row['record_id'])
        if kind != 'work-product-component--WellLog': raise MapperError('record-kind', f'{path}.record_id')
        namespaces.add(ns)
        if row['wellbore_record_id'] not in bores: raise MapperError('wellbore-unknown', f'{path}.wellbore_record_id')
        if row['payload']['path'] in payloads: raise MapperError('payload-repeated', f'{path}.payload.path')
        payloads.add(row['payload']['path'])
        if (row['asset_id'], row['revision']) in pairs: raise MapperError('pair-repeated', path)
        pairs.add((row['asset_id'], row['revision']))
    if len(namespaces) > 1: raise MapperError('namespace-mixed', '$')
    for i, row in enumerate(doc['unwritten']):
        path = f'$.unwritten[{i}]'
        if row['sentence'] != WORDS[row['reason']]: raise MapperError('sentence-mismatch', f'{path}.sentence')
        if (row['asset_id'], row['revision']) in pairs: raise MapperError('pair-repeated', path)
        pairs.add((row['asset_id'], row['revision']))
    if len(pairs) != doc['bundle']['assets']: raise MapperError('assets-count', '$.bundle.assets')
    seen = set()
    for i, row in enumerate(doc['losses']):
        path = f'$.losses[{i}]'
        if (row['asset_id'], row['revision']) not in pairs: raise MapperError('loss-unknown', path)
        key = (row['asset_id'], row['revision'], row['origin'], row['text'])
        if key in seen: raise MapperError('loss-repeated', path)
        seen.add(key)
    for key in ('unwritten', 'losses'):
        if doc['empty'][key] != (not doc[key]): raise MapperError('empty-mismatch', f'$.empty.{key}')
    expected = {'osdu:wks:master-data--Well:1.5.0': wells, 'osdu:wks:master-data--Wellbore:1.5.1': len(bores),
                'osdu:wks:work-product-component--WellLog:1.5.0': len(doc['records']),
                'osdu:wks:dataset--File.Generic:1.1.0': len(doc['records'])}
    if doc['manifest']['kinds'] != {k: v for k, v in expected.items() if v}: raise MapperError('kinds-count', '$.manifest.kinds')
    if recipe is not None and doc['bundle']['digest'] != recipe['source']['digest']: raise MapperError('bundle-digest', '$.bundle.digest')
    return doc


# ---- the reviewed file (1.3.0, E116 s4) ----------------------------------------------------------------------------

def check_reviewed(doc):
    """Raise MapperError for the first problem of ophiolite-reviewed.json: structure, each table's locator as its
    source kind's in the recipe schema (a bucket by endpoint, region, bucket and prefix, without credentials), a sheet
    only for a file, the timestamps, one pick per (target, table, schema digest) and one alias per (target, spelling)."""
    structure(REVIEWED_SCHEMA, doc, REVIEWED_SCHEMA)
    keys = set()
    for i, row in enumerate(doc['picks']):
        path = f'$.picks[{i}]'
        table = row['table']
        structure(RECIPE_SCHEMA['$defs'][f'locator-{table["kind"]}'], table['locator'], RECIPE_SCHEMA, f'{path}.table.locator')
        if table['kind'] == 'bucket-prefix' and not endpoint_clean(table['locator']['endpoint']):
            raise MapperError('locator-credentials', f'{path}.table.locator.endpoint')
        if table['sheet'] is not None and table['kind'] != 'file': raise MapperError('reading-misplaced', f'{path}.table.sheet')
        if not at_valid(row['at']): raise MapperError('at-invalid', f'{path}.at')
        key = json.dumps([row['target'], table, row['schema_digest']], sort_keys=True)
        if key in keys: raise MapperError('pick-repeated', path)
        keys.add(key)
    keys = set()
    for i, row in enumerate(doc['aliases']):
        path = f'$.aliases[{i}]'
        if not at_valid(row['at']): raise MapperError('at-invalid', f'{path}.at')
        if (row['target'], row['spelling']) in keys: raise MapperError('alias-repeated', path)
        keys.add((row['target'], row['spelling']))
    return doc


# ---- the project folder ---------------------------------------------------------------------------------------------

def validate_folder(block, manifest, recipe=None):
    """Raise MapperError for the first problem of a manifest's folder block, read with the enclosing manifest. RECIPE,
    the folder's recipe.json once a reader has verified its bytes, also binds every item to the recipe's table target
    (1.1, E116 s1)."""
    structure(FOLDER_SCHEMA, block, FOLDER_SCHEMA, '$.folder')
    roles = FOLDER_SCHEMA['roles']
    assets = manifest.get('assets', [])
    listed = {f['path'] for a in assets for f in a.get('files', [])}
    paths, counts, per_asset = set(), {}, set()
    for i, row in enumerate(block['files']):
        path = f'$.folder.files[{i}]'
        rule = roles[row['role']]
        if row['path'] in paths: raise MapperError('path-repeated', f'{path}.path')
        paths.add(row['path'])
        if row['path'] in listed: raise MapperError('path-in-asset', f'{path}.path')
        if row['media_type'] not in rule.get('media_types', [rule.get('media_type')]): raise MapperError('media-type', f'{path}.media_type')
        if rule['asset']:
            if row['asset'] is None: raise MapperError('asset-missing', f'{path}.asset')
            if row['asset'] >= len(assets): raise MapperError('asset-unknown', f'{path}.asset')
            if row['asset'] in per_asset: raise MapperError('role-repeated', path)
            per_asset.add(row['asset'])
            if row['path'] != rule['path'].format(asset=row['asset']): raise MapperError('role-path', f'{path}.path')
        elif row['asset'] is not None: raise MapperError('asset-misplaced', f'{path}.asset')
        elif 'pattern' in rule:  # 1.1: originals and items, any number of each, each under its own name
            if not re.fullmatch(rule['pattern'], row['path']) or row['path'].rsplit('/', 1)[1] in ('.', '..'):
                raise MapperError('role-path', f'{path}.path')
        else:
            if counts.get(row['role']): raise MapperError('role-repeated', path)
            if row['path'] != rule['path']: raise MapperError('role-path', f'{path}.path')
        counts[row['role']] = counts.get(row['role'], 0) + 1
    for role, rule in roles.items():
        if rule['count'] == 'one' and counts.get(role) != 1: raise MapperError('role-count', f'$.folder.files:{role}')
        if rule['count'] == 'without-assets' and not assets and not counts.get(role): raise MapperError('role-count', f'$.folder.files:{role}')
    identity = [r for r, rule in roles.items() if rule['count'] == 'identity']
    if 0 < sum(counts.get(r, 0) for r in identity) < len(identity): raise MapperError('identity-partial', '$.folder.files')
    recipe_row = next(r for r in block['files'] if r['role'] == 'recipe')
    if recipe_row['sha256'] != block['recipe']['sha256']: raise MapperError('recipe-digest', '$.folder.recipe.sha256')
    if recipe is not None:
        target = recipe.get('target') if isinstance(recipe, dict) and isinstance(recipe.get('target'), dict) else {}
        # a table target names its item; a reader profile's item is the stem folder-schema.json's profile_items gives (1.2)
        stem = {'table-target': target.get('id'),
                'reader-profile': FOLDER_SCHEMA['profile_items'].get(target.get('id'))}.get(target.get('kind'))
        for i, row in enumerate(block['files']):
            if row['role'] == 'item' and (stem is None or row['path'][len('items/'):-len('.parquet')] != stem):
                raise MapperError('item-target', f'$.folder.files[{i}].path')
    return block


def check_tables(tables):
    """Raise MapperError for the first problem of identity rows {table path: [row]}: the columns folder-schema.json
    lists, their nulls and values, the entity grammar, each relationship's kinds per predicate (E20's directions) and
    that every entity a row names exists."""
    spec = FOLDER_SCHEMA['tables']
    for name, rows in tables.items():
        if name not in spec: raise MapperError('table-unknown', name)
        columns = {c['column']: c for c in spec[name]}
        for i, row in enumerate(rows):
            path = f'{name}[{i}]'
            if set(row) != set(columns): raise MapperError('table-columns', path)
            for key, c in columns.items():
                value = row[key]
                if value is None:
                    if not c['nullable']: raise MapperError('table-null', f'{path}.{key}')
                elif not isinstance(value, str): raise MapperError('table-type', f'{path}.{key}')
                elif 'values' in c and value not in c['values']: raise MapperError('table-value', f'{path}.{key}')
    entities = {}
    for i, row in enumerate(tables.get('identity/entities.parquet', [])):
        if not ENTITY_ID.match(row['entity_id']): raise MapperError('entity-id', f'identity/entities.parquet[{i}].entity_id')
        if row['entity_id'] in entities: raise MapperError('entity-repeated', f'identity/entities.parquet[{i}].entity_id')
        entities[row['entity_id']] = row['kind']
    for i, row in enumerate(tables.get('identity/aliases.parquet', [])):
        if row['entity_id'] not in entities: raise MapperError('entity-unknown', f'identity/aliases.parquet[{i}].entity_id')
    predicates = FOLDER_SCHEMA['predicates']
    for i, row in enumerate(tables.get('identity/relationships.parquet', [])):
        path = f'identity/relationships.parquet[{i}]'
        rule = predicates[row['predicate']]
        if row['subject_kind'] not in rule['subject_kind'] or row['object_kind'] not in rule['object_kind']:
            raise MapperError('predicate-kinds', path)
        if row['subject_kind'] == 'payload':
            if not PAYLOAD.match(row['subject']): raise MapperError('payload-subject', f'{path}.subject')
        elif entities.get(row['subject']) != row['subject_kind']: raise MapperError('entity-unknown', f'{path}.subject')
        if entities.get(row['object']) != row['object_kind']: raise MapperError('entity-unknown', f'{path}.object')
    return tables
