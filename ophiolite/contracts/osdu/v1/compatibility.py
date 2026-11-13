"""E167 s1: the OSDU compatibility summary (`ophiolite.osdu-compatibility/1`) and its one sentence.

`summary(document)` forms the sentence a person and a tool read; `problems(document)` lists what is wrong with a
document (empty when it is sound) and `check(document)` raises on the first; `from_record(record, path)` builds the
document from a dated load record under `docs/osdu-roundtrip/` and refuses an incomplete one (s0 R13). Standard
library only (Python 3.10): the gateway, `tools/osdu-compatibility.py` and the SDK's synced copy run the same code.

E167 s1b: a record whose hand-written `outsider` block says the denied leg was not provable on its edition is accepted
only when the record evidences it (D1): the reason is a known one shown by the outsider's groups, and every failure is
the outsider's read of one returned record. The document then says so in `denied_read` and in the sentence's caveat.

E167 s1b ruling (10 November 2026, EPICS design 6): `operator_steps` names what the load needed beyond the manifest's
own placeholders, from the record: the schemas the operator registered (`schemas_registered`) and the fields the load
supplied outside the placeholder set (`substitutions`); the sentence gains a clause when either is non-empty.
"""
import re

SCHEMA = 'ophiolite.osdu-compatibility/1'
RECORD_SCHEMA = 'ophiolite.osdu-roundtrip-record/1'
RECORD_PATH = 'storage-in-manifest-order'  # the record's load path, as the harness writes it
LIFECYCLE = 'preview'
NOT_YET = 'not yet verified'
FIELDS = ('schema', 'lifecycle', 'date', 'edition', 'mapper', 'manifest', 'kinds', 'record', 'denied_read', 'operator_steps',
          'summary')
EVIDENCE = ('date', 'edition', 'mapper', 'manifest', 'record', 'denied_read', 'operator_steps')  # null together when empty
PLACEHOLDERS = ('namespace', 'owners', 'viewers', 'legal_tag')  # the manifest's own placeholders: filled, never named
SUPPLIED = {'data_countries': 'the data countries the manifest leaves empty'}  # a second needs a ruling
STEPS = ('registered', 'supplied')
DENIED_LEGS = ('proved', 'not-provable')  # the record's outsider.denied_leg; absent reads as proved
REASONS = {'outsider-in-viewers': 'its outside test account belonged to the default viewers group'}  # a second needs a strategy
CAVEAT = '; the denied read was not provable on that edition because '
OUTSIDER_READ = '{}: the outsider was answered read, not SOURCE_ACCESS_DENIED.'  # the read-back's failure for a 200 preview
SERVICES = ('storage', 'schema-service')
DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
DIGEST = re.compile(r'[0-9a-f]{64}')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?')  # the exact /info string, e.g. 0.27.0-local
KIND = re.compile(r'[a-z0-9]+:wks:(master-data|work-product-component|dataset)--([A-Za-z][A-Za-z0-9.]*):[0-9]+\.[0-9]+\.[0-9]+')
GROUPS = ('master-data', 'work-product-component', 'dataset')  # the sentence names masters, then work products, then files
RECORD_FILE = re.compile(r'docs/osdu-roundtrip/([0-9]{4}-[0-9]{2}-[0-9]{2})/record\.json')


def _name(kind):
    match = KIND.fullmatch(kind)
    return GROUPS.index(match.group(1)), match.group(2)


def _and(words):
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def _load_clause(steps):
    """'; the load registered the Well 1.5.0 schema and supplied …', or '' when the load needed nothing else."""
    acts = []
    if steps['registered']:
        names = [f'{_name(kind)[1]} {kind.rsplit(":", 1)[1]}' for kind in steps['registered']]
        acts.append(f'registered the {_and(names)} schema' + ('s' if len(names) > 1 else ''))
    if steps['supplied']:
        acts.append('supplied ' + _and([SUPPLIED[field] for field in steps['supplied']]))
    return '; the load ' + ' and '.join(acts) if acts else ''


def summary(document):
    """The sentence: NOT_YET without kinds, else date, edition, mapper (the producer), manifest digest and kind names,
    what the load needed beyond the manifest, and the caveat when the denied read was not provable."""
    if not document.get('kinds'):
        return NOT_YET
    names = ', '.join(name for _, name in sorted(_name(kind) for kind in document['kinds']))
    edition = document['edition']
    caveat = (CAVEAT + REASONS[document['denied_read']['reason']]
              if document['denied_read']['outcome'] == 'not-provable' else '')
    return (f"compatibility shown on {document['date']} against {edition['name']} {edition['version']}, "
            f"mapper {document['mapper']}, manifest {document['manifest']}, kinds {names}"
            f"{_load_clause(document['operator_steps'])}{caveat}")


def _operator_steps(value):
    if not isinstance(value, dict) or set(value) != set(STEPS) or not all(isinstance(value[k], list) for k in STEPS):
        return 'The operator steps must be {"registered": [<kind>, ...], "supplied": [<field>, ...]}.'
    if not all(isinstance(k, str) and KIND.fullmatch(k) for k in value['registered']):
        return 'Each registered schema must be an OSDU kind such as osdu:wks:master-data--Well:1.0.0.'
    if not all(f in SUPPLIED for f in value['supplied']):
        return f'Each supplied field must be one of: {", ".join(SUPPLIED)}.'
    if any(len(set(value[k])) != len(value[k]) or value[k] != sorted(value[k]) for k in STEPS):
        return 'The operator steps must be sorted and listed once each.'
    return None


def _denied_read(value):
    if value == {'outcome': 'shown'}:
        return None
    if not isinstance(value, dict) or set(value) != {'outcome', 'reason'} or value['outcome'] != 'not-provable':
        return 'The denied read must be {"outcome": "shown"} or {"outcome": "not-provable", "reason": <reason>}.'
    if value['reason'] not in REASONS:
        return f'The denied read\'s reason must be one of: {", ".join(REASONS)}.'
    return None


def _edition(edition):
    if not isinstance(edition, dict) or set(edition) != {'name', 'version', 'services'}:
        return 'The edition must name its distribution, version and services.'
    if not isinstance(edition['name'], str) or not edition['name'].strip() or not VERSION.fullmatch(str(edition['version'])):
        return 'The edition must have a name and a version such as 0.27.0.'
    services = edition['services']
    if not isinstance(services, dict) or set(services) != set(SERVICES) or any(services[s] != edition['version'] for s in SERVICES):
        return 'The Storage and Schema service versions must equal the edition version.'
    return None


def problems(document):
    """Every defect of DOCUMENT, each as one sentence; empty when the document is sound."""
    if not isinstance(document, dict) or set(document) != set(FIELDS):
        return [f'The document must have exactly the fields {", ".join(FIELDS)}.']
    found = []
    if document['schema'] != SCHEMA:
        found.append(f'The schema must be {SCHEMA}.')
    if document['lifecycle'] != LIFECYCLE:
        found.append(f'The lifecycle must be {LIFECYCLE}.')
    kinds = document['kinds']
    if not isinstance(kinds, list) or not all(isinstance(k, str) and KIND.fullmatch(k) for k in kinds):
        return found + ['Each kind must be an OSDU kind such as osdu:wks:master-data--Well:1.0.0.']
    if len(set(kinds)) != len(kinds) or kinds != sorted(kinds):
        found.append('The kinds must be sorted and listed once each.')
    if not kinds:
        if any(document[key] is not None for key in EVIDENCE):
            found.append('With no kinds the document holds no date, edition, mapper, manifest, record, denied read or '
                         'operator steps.')
    elif any(document[key] is None for key in EVIDENCE):
        found.append('With kinds the document must hold the date, edition, mapper, manifest, record, denied read and '
                     'operator steps.')
    else:
        problem = _denied_read(document['denied_read']) or _operator_steps(document['operator_steps'])
        if problem:
            return found + [problem]
        dated = isinstance(document['date'], str) and DATE.fullmatch(document['date'])
        if not dated:
            found.append('The date must be written as YYYY-MM-DD.')
        problem = _edition(document['edition'])
        if problem:
            return found + [problem]
        if not isinstance(document['mapper'], str) or not VERSION.fullmatch(document['mapper']):
            found.append('The mapper version must be written as 0.4.0.')
        if not isinstance(document['manifest'], str) or not DIGEST.fullmatch(document['manifest']):
            found.append('The manifest digest must be 64 lowercase hexadecimal characters.')
        match = RECORD_FILE.fullmatch(str(document['record']))
        if not match or (dated and match.group(1) != document['date']):
            found.append('The record must be docs/osdu-roundtrip/<date>/record.json for the same date.')
    if found:
        return found
    expected = summary(document)
    if kinds and 'verified' in expected:
        return ['A shown compatibility never says verified.']
    if document['summary'] != expected:
        return [f'The summary must read: {expected}']
    return []


def check(document):
    """Raise ValueError naming the first defect of DOCUMENT."""
    found = problems(document)
    if found:
        raise ValueError(found[0])


def _outsider(record):
    """(denied_leg, reason) from the record's hand-written outsider block; ValueError when the block is unsound."""
    block = record.get('outsider', {})
    if not isinstance(block, dict):
        raise ValueError('The record\'s outsider block must be an object.')
    leg = block.get('denied_leg', 'proved')
    if leg not in DENIED_LEGS:
        raise ValueError(f'The record\'s denied leg must be one of: {", ".join(DENIED_LEGS)}.')
    if leg == 'proved':
        if 'reason' in block:
            raise ValueError('A proved denied leg gives no reason.')
        return leg, None
    if 'reason' not in block:
        raise ValueError('A denied leg not provable must give its reason.')
    if block['reason'] not in REASONS:
        raise ValueError(f'The reason must be one of: {", ".join(REASONS)}.')
    groups = block.get('groups')
    if not isinstance(groups, list) or not groups or not all(isinstance(g, str) and g.strip() for g in groups):
        raise ValueError('The outsider\'s groups must be a list of group names.')
    facts = record.get('facts')
    if not isinstance(facts, dict) or facts.get('viewers') not in groups:
        raise ValueError('The outsider\'s groups do not hold the viewers group, so the reason is not shown.')
    return leg, block['reason']


def _failures(record, returned, leg):
    failures, readback = record.get('failures'), record.get('readback')
    if leg == 'proved':
        if failures != []:
            return 'The record has failures.'
        if isinstance(readback, dict) and readback.get('failures') != []:
            return 'The read-back has failures.'
        return None
    if not isinstance(readback, dict) or readback.get('failures') != failures:
        return 'The record\'s failures and the read-back\'s failures differ.'
    expected = [OUTSIDER_READ.format(ident) for ident in returned]
    if not isinstance(failures, list) or any(f not in expected for f in failures):
        return 'A failure other than the outsider\'s read of a returned record remains.'
    if sorted(failures) != sorted(expected):
        return 'The failures must name the outsider\'s read of each returned record once.'
    return None


def _steps(readback, returned, leg):
    steps = readback.get('steps') if isinstance(readback, dict) else None
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        return 'The record has no read-back.'
    read = {s.get('id') for s in steps if s.get('person') == 'reader' and s.get('bind') == 200 and s.get('export') == 200}
    if any(ident not in read for ident in returned):
        return 'A returned record was not read back by the project.'
    previews = {}
    for step in steps:
        if step.get('person') == 'outsider' and 'preview' in step:
            previews.setdefault(step.get('id'), []).append(step['preview'])
    if any(len(previews.get(ident, [])) != 1 for ident in returned):
        return 'Each returned record must have exactly one outsider preview.'
    if leg == 'proved':
        if any(previews[ident] != [403] for ident in returned):
            return 'A returned record was not refused to the outsider.'
        return None
    if any(previews[ident] != [200] for ident in returned):
        return 'An outsider preview contradicts the outsider\'s read failure.'
    if not any(s.get('person') == 'outsider' and s.get('bind') == 200 and s.get('id') not in returned for s in steps):
        return 'The record has no control read by the outsider.'
    return None


def _steps_needed(record):
    """`operator_steps` from the record's schemas_registered and substitutions; ValueError when either is unsound."""
    schemas = record.get('schemas_registered', [])
    if not isinstance(schemas, list) or not all(isinstance(s, dict) and isinstance(s.get('kind'), str)
                                                and KIND.fullmatch(s['kind']) for s in schemas):
        raise ValueError('Each registered schema must name its OSDU kind.')
    acts = record.get('substitutions', {})
    if not isinstance(acts, dict) or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in acts.values()):
        raise ValueError('The substitutions must count each act.')
    supplied = sorted(field for field, count in acts.items() if count and field not in PLACEHOLDERS)
    unnamed = [field for field in supplied if field not in SUPPLIED]
    if unnamed:
        raise ValueError(f'The load supplied {", ".join(unnamed)}, which the summary has no words for.')
    return {'registered': sorted({s['kind'] for s in schemas}), 'supplied': supplied}


def from_record(record, path):
    """The document for a complete load RECORD found at PATH (repository-relative); ValueError on an incomplete one."""
    if not isinstance(record, dict) or record.get('schema') != RECORD_SCHEMA:
        raise ValueError(f'The record is not {RECORD_SCHEMA}.')
    if record.get('harness') is not True:
        raise ValueError('The record was not written by the harness.')
    if record.get('check_only') is not False:
        raise ValueError('The record is a check-only run, not a load.')
    leg, reason = _outsider(record)
    if record.get('path') != RECORD_PATH:
        raise ValueError(f'The record path must be {RECORD_PATH}.')
    if not isinstance(record.get('deleted_at'), str) or not record['deleted_at'].strip():
        raise ValueError('The record does not say when the instance was deleted.')
    kinds = record.get('kinds')
    if not isinstance(kinds, list) or not kinds:
        raise ValueError('The record names no kinds.')
    returned = record.get('returned')
    if not isinstance(returned, (list, dict)) or not returned:
        raise ValueError('The record returned no records.')
    problem = _failures(record, list(returned), leg) or _steps(record.get('readback'), list(returned), leg)
    if problem:
        raise ValueError(problem)
    distribution = record.get('distribution')
    if not isinstance(distribution, dict) or not isinstance(distribution.get('name'), str) or 'version' not in distribution:
        raise ValueError('The record does not name its distribution.')
    edition = record.get('edition')
    services = {}
    for service in SERVICES:
        info = edition.get(service) if isinstance(edition, dict) else None
        if not isinstance(info, dict) or 'version' not in info:
            raise ValueError(f'The record has no {service} version.')
        services[service] = info['version']
    if any(version != distribution['version'] for version in services.values()):
        raise ValueError('The distribution version differs from a service version.')
    manifest = record.get('manifest') or {}
    producer = manifest.get('producer') if isinstance(manifest, dict) else None
    if not isinstance(producer, dict) or 'version' not in producer:
        raise ValueError('The record does not name the manifest producer.')
    document = {'schema': SCHEMA, 'lifecycle': LIFECYCLE, 'date': record.get('date'),
                'edition': {'name': distribution['name'], 'version': distribution['version'], 'services': services},
                'mapper': producer['version'], 'manifest': manifest.get('sha256'), 'kinds': sorted(kinds), 'record': path,
                'denied_read': {'outcome': 'shown'} if leg == 'proved' else {'outcome': 'not-provable', 'reason': reason},
                'operator_steps': _steps_needed(record), 'summary': ''}
    document['summary'] = summary(document) if all(isinstance(k, str) and KIND.fullmatch(k) for k in kinds) else ''
    check(document)
    return document


def empty():
    """The shipped state: no record has landed."""
    return {'schema': SCHEMA, 'lifecycle': LIFECYCLE, 'date': None, 'edition': None, 'mapper': None, 'manifest': None,
            'kinds': [], 'record': None, 'denied_read': None, 'operator_steps': None, 'summary': NOT_YET}
