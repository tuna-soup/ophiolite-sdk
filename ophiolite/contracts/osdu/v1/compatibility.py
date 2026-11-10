"""E167 s1: the OSDU compatibility summary (`ophiolite.osdu-compatibility/1`) and its one sentence.

`summary(document)` forms the sentence a person and a tool read; `problems(document)` lists what is wrong with a
document (empty when it is sound) and `check(document)` raises on the first; `from_record(record, path)` builds the
document from a dated load record under `docs/osdu-roundtrip/` and refuses an incomplete one (s0 R13). Standard
library only (Python 3.10): the gateway, `tools/osdu-compatibility.py` and the SDK's synced copy run the same code.
"""
import re

SCHEMA = 'ophiolite.osdu-compatibility/1'
RECORD_SCHEMA = 'ophiolite.osdu-roundtrip-record/1'
RECORD_PATH = 'storage-in-manifest-order'  # the record's load path, as the harness writes it
LIFECYCLE = 'preview'
NOT_YET = 'not yet verified'
FIELDS = ('schema', 'lifecycle', 'date', 'edition', 'mapper', 'manifest', 'kinds', 'record', 'summary')
EVIDENCE = ('date', 'edition', 'mapper', 'manifest', 'record')  # null together in the empty state, set together otherwise
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


def summary(document):
    """The sentence: NOT_YET without kinds, else date, edition, mapper (the producer), manifest digest and kind names."""
    if not document.get('kinds'):
        return NOT_YET
    names = ', '.join(name for _, name in sorted(_name(kind) for kind in document['kinds']))
    edition = document['edition']
    return (f"compatibility shown on {document['date']} against {edition['name']} {edition['version']}, "
            f"mapper {document['mapper']}, manifest {document['manifest']}, kinds {names}")


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
            found.append('With no kinds the document holds no date, edition, mapper, manifest or record.')
    elif any(document[key] is None for key in EVIDENCE):
        found.append('With kinds the document must hold the date, edition, mapper, manifest and record.')
    else:
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


def _steps(readback, returned):
    steps = readback.get('steps') if isinstance(readback, dict) else None
    if not isinstance(steps, list):
        return 'The record has no read-back.'
    if readback.get('failures') != []:
        return 'The read-back has failures.'
    read = {s.get('id') for s in steps if s.get('person') == 'reader' and s.get('bind') == 200 and s.get('export') == 200}
    denied = {s.get('id') for s in steps if s.get('person') == 'outsider' and 'preview' in s and s['preview'] != 200}
    if any(ident not in read for ident in returned):
        return 'A returned record was not read back by the project.'
    if any(ident not in denied for ident in returned):
        return 'A returned record was not refused to the outsider.'
    return None


def from_record(record, path):
    """The document for a complete load RECORD found at PATH (repository-relative); ValueError on an incomplete one."""
    if not isinstance(record, dict) or record.get('schema') != RECORD_SCHEMA:
        raise ValueError(f'The record is not {RECORD_SCHEMA}.')
    if record.get('harness') is not True:
        raise ValueError('The record was not written by the harness.')
    if record.get('check_only') is not False:
        raise ValueError('The record is a check-only run, not a load.')
    if record.get('failures') != []:
        raise ValueError('The record has failures.')
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
    problem = _steps(record.get('readback'), list(returned))
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
                'summary': ''}
    document['summary'] = summary(document) if all(isinstance(k, str) and KIND.fullmatch(k) for k in kinds) else ''
    check(document)
    return document


def empty():
    """The shipped state: no record has landed."""
    return {'schema': SCHEMA, 'lifecycle': LIFECYCLE, 'date': None, 'edition': None, 'mapper': None, 'manifest': None,
            'kinds': [], 'record': None, 'summary': NOT_YET}
