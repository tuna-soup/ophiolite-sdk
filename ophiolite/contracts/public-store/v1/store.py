"""ophiolite.public-store/1 (E212 s0): the rules of the public store's index, as pure functions over documents.

The SDK (its contracts snapshot), the publishing tool (tools/public-store) and the gateway's tests run this same file,
loaded from its source text:

    module = types.ModuleType('ophiolite_public_store_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). It reads its documents from beside itself and from the contracts tree it sits in
(the same layout in the Platform and in the SDK snapshot): public-store-schema.json here, the words
(vocabulary/v1/public-store-words.json), and E211's rules module samples/v1/samples.py, loaded the same way, whose
structure reader and per-source licence rules it applies. All of them are read when the module is loaded; the checks
read no file, open no connection and start no process. The index and the source rules are handed in as data.

A problem is {code, dataset, path}: the code (one of CODES), the dataset's id when the problem is a dataset's (null for
the index itself), and a JSON path in the index.
"""
import copy
import json
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
PUBLIC_STORE = 'ophiolite.public-store/1'
WORDS_DOCUMENT = 'ophiolite.public-store-words/1'
INDEX_KEY = 'index.json'
SAMPLES_KEY = 'samples/index.json'
MAX_INDEX_BYTES = 1024 * 1024  # a serialized index above this is refused, by the publishing tool and by a reader
MAX_OBJECTS = 16  # per dataset (O1, strategy Q6): append-only, then a ruling


def _read(*parts):
    return json.loads(CONTRACTS.joinpath(*parts).read_text(encoding='utf-8'))


def _load(path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


SAMPLES = _load(CONTRACTS / 'samples' / 'v1' / 'samples.py', 'ophiolite_samples_contract')
SCHEMA = _read('public-store', 'v1', 'public-store-schema.json')
WORDS = _read('vocabulary', 'v1', 'public-store-words.json')
# The index's own codes, then the per-source licence and policy codes of E211 (their sentences are E211's words).
OWN_CODES = ('index-malformed', 'dataset-repeated', 'key-repeated', 'key-outside-dataset', 'records-differ', 'too-many-objects')
LICENCE_CODES = ('sample-not-approved', 'source-refused', 'acquisition-host', 'licence-malformed', 'not-redistributable',
                 'not-anonymous', 'non-commercial', 'licence-not-listed', 'commercial-use-not-read', 'no-attribution-sentence',
                 'credit-not-prescribed', 'credit-without-evidence', 'unsupported-combination', 'licence-block-differs')
CODES = OWN_CODES + LICENCE_CODES

SAMPLES.scan(SCHEMA)
# The structure without the object bound: a dataset above it is named by its own code (too-many-objects), not as a
# malformed index; every other bound stays in the structure.
STRUCTURE = copy.deepcopy(SCHEMA)
STRUCTURE['$defs']['StoreDataset']['properties']['objects'].pop('maxItems')


def licence_problems(sample_id, sources, licence, rules):
    """(code, path) of each source-policy and licence rule a well-formed dataset breaks, paths rooted at the dataset
    (`$.id`, `$.sources[i]...`, `$.licence...`): samples.licence_problems, the one place the store reaches E211's
    per-source rules."""
    return SAMPLES.licence_problems(sample_id, sources, licence, rules)


def problem(code, path, dataset=None):
    if code not in CODES: raise ValueError('not a public store code: ' + code)
    return {'code': code, 'dataset': dataset, 'path': path}


def sentence(code, dataset):
    """The sentence a person reads for a code, with the dataset's name (its title, or its id)."""
    if code in OWN_CODES: return WORDS['reasons'][code].format(dataset=dataset)
    return SAMPLES.sentence(code, dataset)


def records(sources):
    """The unique OSD records of the sources, in first-appearance order (two sources may share one record)."""
    out = []
    for source in sources:
        if source['osd_record'] not in out: out.append(source['osd_record'])
    return out


def index_problems(index, rules):
    """Every problem of an index: its structure first (nothing else is read from an index that is malformed), then for
    each dataset its id, bound, records, object keys and licence (`rules` is the `ophiolite.sample-source-rules/1`
    document)."""
    found = SAMPLES.first_error(STRUCTURE, index, STRUCTURE)
    if found is not None: return [problem('index-malformed', found)]
    out, ids, keys = [], set(), set()
    for i, dataset in enumerate(index['datasets']):
        at, ident = '$.datasets[%d]' % i, dataset['id']
        if ident in ids: out.append(problem('dataset-repeated', at + '.id', ident))
        ids.add(ident)
        if len(dataset['objects']) > MAX_OBJECTS: out.append(problem('too-many-objects', at + '.objects', ident))
        if dataset['osd_records'] != records(dataset['sources']): out.append(problem('records-differ', at + '.osd_records', ident))
        for j, item in enumerate(dataset['objects']):
            where = '%s.objects[%d].key' % (at, j)
            prefix = 'datasets/%s/%s/' % (ident, item['sha256'])
            name = item['key'][len(prefix):]
            if not item['key'].startswith(prefix) or not name or '/' in name: out.append(problem('key-outside-dataset', where, ident))
            if item['key'] in keys: out.append(problem('key-repeated', where, ident))
            keys.add(item['key'])
        for code, path in licence_problems(ident, dataset['sources'], dataset['licence'], rules):
            out.append(problem(code, at + path[1:], ident))
    return out


def find(index, sha256):
    """{key, bytes} of the object whose digest is `sha256`, over every dataset's every object; None when none is."""
    for dataset in index['datasets']:
        for item in dataset['objects']:
            if item['sha256'] == sha256: return {'key': item['key'], 'bytes': item['bytes']}
    return None


def key_for(dataset, sha256, name):
    """The content-addressed key of an object (the name must fit the store's key type; a caller refuses one that does
    not, never changes it)."""
    return 'datasets/%s/%s/%s' % (dataset, sha256, name)


def key_fits(key):
    """True when `key` is of the store's key type (E211's `Key`: lower-case relative folders, a file name that
    keeps its capitals, no `..`)."""
    return SAMPLES.first_error(SCHEMA['$defs']['StoreObject']['properties']['key'], key, SCHEMA) is None
