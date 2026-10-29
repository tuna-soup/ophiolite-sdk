"""E112 s0: which step x kind pairs `ophiolite procedures new` can start (`ophiolite.procedure-template-pairs/1`).

The list lives beside the starts it describes (D1), independent of what the server accepts; `pairs()` checks it
against the packaged procedure rules when it loads: every step x every kind in exactly one of listed and refused,
each listed pair inside its rules list, the same rules_version."""
import json
import re
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
PAIRS = HERE / 'pairs.json'
SCHEMA = HERE.parent / 'schemas' / 'procedure-template-pairs-v1.schema.json'
RULES = HERE.parent / 'contracts' / 'procedures' / 'v1' / 'rules.json'
NAME = 'ophiolite.procedure-template-pairs/1'
WORD = re.compile(r'^[a-z][a-z0-9-]{1,30}$')
PROFILE = re.compile(r'[a-z0-9][a-z0-9.-]*/[0-9]+')
DEFAULT = 'well-tops-csv/1'
LISTS = {'read': 'read_source_kinds', 'source': 'read_source_kinds', 'process': 'process_kinds', 'send': 'send_kinds'}
VERBS = {'read': 'Read {}', 'source': 'Read {} from a system', 'process': 'Make {}', 'send': 'Send {}', 'check': 'Check {}'}
UNKNOWN = 'There is no kind called "{text}". Kinds: {words}.'
SKELETONS, SAMPLES = HERE / 'skeletons', HERE / 'samples'
WRITERS = {'points-csv/1': 'write_points', 'mesh-text/1': 'write_mesh', 'esri-ascii-grid/1': 'write_grid', 'well-tops-csv/1': 'write_tops',
           'deviation-csv/1': 'write_survey', 'opendtect-faultsticks/1': 'write_sticks', 'las2/1': 'write_curves', 'well-location/1': 'write_location',
           'wavelet-text/1': 'write_wavelet', 'model-section-text/1': 'write_model_section', 'time-depth-csv/1': 'write_time_depth',
           'seismic-section-text/1': 'write_seismic_section', 'well-residual/1': 'well_residual'}
CHECKS = {'well-tops-csv/1': 'check-tops', 'deviation-csv/1': 'check-stations'}
_pairs = None


class PairsError(ValueError):
    """pairs.json disagrees with its contract or with the procedure rules (a packaging fault, not a person's)."""


def _rules():
    return json.loads(RULES.read_text(encoding='utf-8'))


def _check(doc, rules):
    if not isinstance(doc, dict) or doc.get('schema') != NAME: raise PairsError('pairs.json is not %s' % NAME)
    if set(doc) != {'schema', 'rules_version', 'kinds', 'listed', 'refused'}: raise PairsError('pairs.json has other or missing fields')
    if doc['rules_version'] != rules['rules_version']: raise PairsError('pairs.json is for rules %s, not %s' % (doc['rules_version'], rules['rules_version']))
    kinds = doc['kinds']
    if set(kinds) != set(rules['kind_words']): raise PairsError('pairs.json kinds are not the rules kinds')
    words = [k['word'] for k in kinds.values()]
    if not all(WORD.match(w) for w in words) or len(set(words)) != len(words): raise PairsError('pairs.json words are not unique plain words')
    cells = {}
    for state, rows in (('listed', doc['listed']), ('refused', doc['refused'])):
        for row in rows:
            cell = (row['step'], row['kind'])
            if cell in cells: raise PairsError('pairs.json names %s x %s twice' % cell)
            cells[cell] = state
            if state == 'listed' and row['step'] in LISTS and row['kind'] not in rules[LISTS[row['step']]]:
                raise PairsError('pairs.json lists %s x %s, which the rules do not allow' % cell)
            if state == 'refused' and (len(row['sentence']) > 200 or PROFILE.search(row['sentence'])):
                raise PairsError('pairs.json sentence for %s x %s is too long or names a profile' % cell)
    if set(cells) != {(s, k) for s in rules['steps'] for k in kinds}: raise PairsError('pairs.json does not cover every step and kind once')
    return doc


def pairs():
    """The checked pair list (loaded once)."""
    global _pairs
    if _pairs is None: _pairs = _check(json.loads(PAIRS.read_text(encoding='utf-8')), _rules())
    return _pairs


def listed():
    return frozenset((row['step'], row['kind']) for row in pairs()['listed'])


def word(profile):
    return pairs()['kinds'][profile]['word']


def resolve_kind(text):
    """A kind as a person writes it, a word (`well-tops`) or a profile id (`well-tops-csv/1`), to its profile id; None
    when it names no kind."""
    kinds = pairs()['kinds']
    if text in kinds: return text
    return next((profile for profile, k in kinds.items() if k['word'] == text), None)


def refusal(step, text):
    """Why `procedures new --step STEP --kind TEXT` makes nothing in this version, or None when it makes a start."""
    profile = resolve_kind(text)
    if profile is None: return UNKNOWN.format(text=text, words=', '.join(sorted(k['word'] for k in pairs()['kinds'].values())))
    return next((row['sentence'] for row in pairs()['refused'] if (row['step'], row['kind']) == (step, profile)), None)


def default_label(step, profile):
    """--label's default: the step's verb and the kind's name in the rules ("Read well tops (CSV)")."""
    name = _rules()['kind_words'][profile]
    if not (len(name) > 1 and name[1].isupper()): name = name[0].lower() + name[1:]
    return VERBS[step].format(name)


def made():
    """E112 s1, s1p: the pairs `make` writes a working start for: every listed pair (the process starts read their
    input with ophiolite.readers, E128)."""
    return listed()


def _written(profile, values):
    from .. import writers
    return getattr(writers, WRITERS[profile])(**values)


def _sample(word):
    return json.loads((SAMPLES / f'{word}.json').read_text(encoding='utf-8'))


def _parts(step, profile, label, name):
    """The manifest and the other files of a start, {relative path: bytes}."""
    word, words = pairs()['kinds'][profile]['word'], _rules()['kind_words'][profile]
    fill = {'label': label.replace('"', "'").replace('\\', '/'), 'words': words[0].lower() + words[1:] if not words[1:2].isupper() else words,
            'writer': WRITERS[profile], 'profile': profile, 'ident': re.sub('[^a-z0-9]', '_', word)}
    output = [{'role': 'data', 'label': words, 'class': 'version', 'kind': profile}]
    files, settings, more = {}, [], {}
    if step == 'read':
        inputs = [{'slot': 'file', 'label': 'File to read', 'class': 'file', 'signature': {'extensions': ['.json'], 'head_patterns': [], 'max_head_bytes': 4096}}]
        files['data/sample.json'] = (SAMPLES / f'{word}.json').read_bytes()
    elif step == 'source':
        inputs = [{'slot': 'system', 'label': 'Folder to read from', 'class': 'system', 'config_keys': ['folder']}]
        files['data/source/sample.json'] = (SAMPLES / f'{word}.json').read_bytes()
    elif step == 'send':
        inputs = [{'slot': 'data', 'label': words, 'class': 'version', 'kinds': [profile], 'cardinality': 'many'},
                  {'slot': 'destination', 'label': 'Folder to send to', 'class': 'system', 'config_keys': ['folder']}]
        output, more = [{'role': 'delivery', 'label': 'Sent ' + fill['words'], 'class': 'delivery'}], {'reconcile': 'procedure:reconcile'}
        sample = _written(profile, _sample(word))
        files['data/' + sample.filename] = sample.bytes
        fill.update(file=sample.filename, declared=repr(sample.declared))
    elif step == 'process':  # E112 s1p: one body per kind reads its input with ophiolite.readers and writes it again
        inputs = [{'slot': 'data', 'label': words, 'class': 'version', 'kinds': [profile], 'cardinality': 'one'}]
        sample = _written(profile, _sample(word))
        files['data/' + sample.filename] = sample.bytes
        if sample.declared: files['data/declared.json'] = (json.dumps(sample.declared, indent=2, sort_keys=True) + '\n').encode()
        fill.update(file=sample.filename, declared=repr(sample.declared))
    else:
        inputs = [{'slot': 'data', 'label': words, 'class': 'version', 'kinds': [profile], 'cardinality': 'one'},
                  {'slot': 'reference', 'label': 'Reference', 'class': 'reference', 'from': 'version', 'kinds': [profile], 'cardinality': 'one'}]
        output = [{'role': 'comparison', 'label': 'Comparison', 'class': 'comparison'}]
        settings = [{'key': 'tolerance', 'label': 'Largest difference that still matches', 'type': 'number', 'default': 1.0}]
        given = _sample(f'check-{word}')
        for part, values in (('data', given['data']), ('reference-pass', given['pass']), ('reference-differ', given['differ'])):
            written = _written(profile, values)
            files[f'data/{part}{Path(written.filename).suffix}'] = written.bytes
        fill.update(extension=Path(written.filename).suffix, declared=repr(written.declared))
    if step in ('read', 'source'): fill['declared'] = repr(_written(profile, _sample(word)).declared)
    body = CHECKS[profile] if step == 'check' else f'process-{word}' if step == 'process' else step
    files['procedure.py'] = Template((SKELETONS / f'{body}.py.tmpl').read_text(encoding='utf-8')).substitute(fill).encode()
    files['tests/test_procedure.py'] = Template((SKELETONS / f'test-{step}.py.tmpl').read_text(encoding='utf-8')).substitute(fill).encode()
    from .._version import __version__
    files['template.json'] = (json.dumps({'step': step, 'kind': profile, 'pairs_rules_version': pairs()['rules_version'], 'sdk_version': __version__},
                                         indent=2) + '\n').encode()
    manifest = {'schema': 'ophiolite.procedure/1', 'name': name, 'label': label, 'version': 1, 'step': step, 'inputs': inputs, 'outputs': output,
                'settings': settings, 'requires': [], 'entry': 'procedure:main', **more}  # E112 s4: every start imports only the SDK
    return manifest, files


def make(folder, step, kind, label=None):
    """E112 s1: write a working start for a made pair (`made()`): procedure.json, procedure.py, template.json, its own
    tests and its sample data; returns `procedures.validate` of the folder. `kind` is a word or a profile id."""
    from .. import procedures
    profile = resolve_kind(kind)
    refused = refusal(step, kind)
    if refused: raise ValueError(refused)
    folder = Path(folder)
    if folder.exists() or folder.is_symlink(): raise procedures.NotRun('destination-exists', '', {'destination': str(folder)})
    label = label or default_label(step, profile)
    name = re.sub(r'[^a-z0-9-]+', '-', folder.name.lower()).strip('-')[:63] or 'procedure'
    manifest, files = _parts(step, profile, label, name)
    files['procedure.json'] = (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode()
    for path, raw in sorted(files.items()):
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(raw)
    return procedures.validate(folder)
