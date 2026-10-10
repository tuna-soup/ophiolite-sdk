"""ophiolite.procedure/1 (E105a): the one validator for a procedure, its bundle digest, and its archive.

The Platform and the SDK run this same file (the SDK's copy is byte-identical, contracts/ snapshot), loaded from its
source text so no bytecode is read or written:

    module = types.ModuleType('ophiolite_procedure_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). It never imports, executes or compiles a procedure's code (R29): an entry is
checked against the folder's file list. rules.json holds every list, limit and sentence; a verdict names its
rules_version, and the same rules_version gives the same verdict wherever this file runs. Registration policy
(ordering, permission, enablement) is not decided here.
"""
import hashlib
import io
import json
import math
import os
import re
import stat
import tarfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = 'ophiolite.procedure/1'
DIGEST_PREFIX = b'ophiolite.procedure-bundle/1\n'
MANIFEST = 'procedure.json'
NOT_MEMBERS = ('__pycache__',)


def _source_module(path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(Path(path).read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


RULES = json.loads((HERE / 'rules.json').read_text(encoding='utf-8'))
RULES_VERSION = RULES['rules_version']
LIMITS = RULES['limits']
labels = _source_module(HERE.parent.parent / 'vocabulary' / 'v1' / 'labels.py', 'ophiolite_label_rule')

FIELDS = {
    'procedure': {'schema', 'name', 'label', 'version', 'version_label', 'step', 'inputs', 'outputs', 'settings', 'entry', 'requires', 'licence'},
    'input': {'slot', 'label', 'class', 'signature', 'config_keys', 'kinds', 'cardinality', 'from'},
    'output': {'role', 'label', 'class', 'kind'},
    'setting': {'key', 'label', 'type', 'unit', 'default', 'minimum', 'maximum', 'choices'},
    'choice': {'value', 'label'},
    'signature': {'extensions', 'head_patterns', 'max_head_bytes'},
}
REQUIRED = {'procedure': ('schema', 'name', 'label', 'version', 'step', 'inputs', 'outputs', 'entry'),
            'input': ('slot', 'label', 'class'), 'output': ('role', 'label', 'class'), 'setting': ('key', 'label', 'type'),
            'choice': ('value', 'label'), 'signature': ('extensions', 'head_patterns', 'max_head_bytes')}
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}(/[a-z0-9][a-z0-9-]{0,62})?$')
IDENTIFIER = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
EXTENSION = re.compile(r'^\.[a-z0-9]{1,10}$')
ENTRY = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*):([A-Za-z_][A-Za-z0-9_]*)$')
REGEX_CHARACTERS = set('\\[](){}|*+?$')
CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f  ]')


class Invalid(ValueError):
    """A procedure Ophiolite does not accept: `code` keys the sentence in rules.json, `field` is the JSON path."""

    def __init__(self, code, field='', **words):
        self.code, self.field, self.words = code, field, words
        super().__init__(sentence(code, **words))


def sentence(code, **words):
    return RULES['sentences'][code].format(**words)


def _where(kind, n=None, m=None):
    return RULES['where'][kind].format(n=n, m=m)


# ---------------------------------------------------------------- the manifest

def _object(value, kind, field, where):
    if not isinstance(value, dict): raise Invalid('not-object', field, where=where)
    unknown = sorted(set(value) - FIELDS[kind])
    if unknown:
        if kind == 'procedure' and any('digest' in key or 'sha256' in key for key in unknown): raise Invalid('digest-field', field + '/' + unknown[0])
        raise Invalid('unknown-field', field + '/' + unknown[0], where=where)
    for key in REQUIRED[kind]:
        if key not in value: raise Invalid('missing-field', field + '/' + key, where=where)
    return value


def _text(value, field, where, limit=None):
    limit = limit or LIMITS['text_characters']
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL.search(value):
        raise Invalid('bad-text', field, where=where)
    return value


def _label(value, field, where):
    _text(value, field, where)
    if labels.engineering_word(value) is not None: raise Invalid('engineering-word', field, where=where)
    if not labels.display_label(value): raise Invalid('unreadable-label', field, where=where)
    return value


def _list(value, field, where, limit, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit: raise Invalid('bad-list', field, where=where)
    return value


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _identifier(value, field, where, seen):
    if not isinstance(value, str) or not IDENTIFIER.match(value): raise Invalid('bad-identifier', field, where=where)
    if value in seen: raise Invalid('duplicate-identifier', field, where=where)
    seen.add(value)


def _kinds(value, field, where, allowed):
    if not isinstance(value, list) or not value or len(set(value)) != len(value) or not all(isinstance(k, str) for k in value):
        raise Invalid('kind-not-allowed', field, where=where)
    for k in value:
        if k not in allowed: raise Invalid('kind-not-allowed', field, where=where)


def _signature(value, field, where):
    if not isinstance(value, dict): raise Invalid('bad-signature', field, where=where)
    unknown = sorted(set(value) - FIELDS['signature'])
    if unknown: raise Invalid('unknown-field', field + '/' + unknown[0], where=where)
    if any(key not in value for key in REQUIRED['signature']): raise Invalid('bad-signature', field, where=where)
    extensions, patterns, head = value['extensions'], value['head_patterns'], value['max_head_bytes']
    if (not isinstance(extensions, list) or not 1 <= len(extensions) <= LIMITS['extensions'] or len(set(map(str, extensions))) != len(extensions)
            or not all(isinstance(e, str) and EXTENSION.match(e) for e in extensions)):
        raise Invalid('bad-signature', field + '/extensions', where=where)
    if not isinstance(patterns, list) or len(patterns) > LIMITS['head_patterns']: raise Invalid('bad-signature', field + '/head_patterns', where=where)
    for i, pattern in enumerate(patterns):
        _text(pattern, f'{field}/head_patterns/{i}', where)
        if REGEX_CHARACTERS & set(pattern[1:] if pattern.startswith('^') else pattern) or pattern[1:].startswith('^'):
            raise Invalid('regex-pattern', f'{field}/head_patterns/{i}', where=where)
    if not _integer(head) or not 1 <= head <= LIMITS['max_head_bytes']: raise Invalid('bad-signature', field + '/max_head_bytes', where=where)


def _input(item, i, step, slots):
    field, where = f'/inputs/{i}', _where('input', i + 1)
    _object(item, 'input', field, where)
    _identifier(item['slot'], field + '/slot', where, slots)
    _label(item['label'], field + '/label', where)
    cls = item['class']
    allowed = {'read': ('file',), 'source': ('system',), 'process': ('version',), 'send': ('version',), 'check': ('version', 'reference')}[step]
    if cls not in allowed: raise Invalid('wrong-input-class', field + '/class', where=where)
    extra = {'file': {'signature'}, 'system': {'config_keys'}, 'version': {'kinds', 'cardinality'}, 'reference': {'from', 'kinds', 'cardinality'}}[cls]
    stray = sorted(set(item) - {'slot', 'label', 'class'} - extra)
    if stray: raise Invalid('unknown-field', field + '/' + stray[0], where=where)
    if cls == 'file':
        if 'signature' not in item: raise Invalid('missing-field', field + '/signature', where=where)
        _signature(item['signature'], field + '/signature', where)
    elif cls == 'system':
        lowered = item['label'].lower()
        if '://' in lowered or '@' in lowered or any(re.search(r'(?<![a-z])' + w + r's?(?![a-z])', lowered) for w in RULES['secret_words']):
            raise Invalid('secret-in-label', field + '/label', where=where)
        keys = item.get('config_keys', [])
        _list(keys, field + '/config_keys', where, LIMITS['config_keys'])
        seen = set()
        for j, key in enumerate(keys): _identifier(key, f'{field}/config_keys/{j}', where, seen)
    else:
        if cls == 'reference':
            if item.get('from') not in ('file', 'version'): raise Invalid('wrong-input-class', field + '/from', where=where)
            if item['from'] == 'file':
                stray = sorted(set(item) & {'kinds', 'cardinality'})
                if stray: raise Invalid('unknown-field', field + '/' + stray[0], where=where)
                return
        if 'kinds' not in item: raise Invalid('missing-field', field + '/kinds', where=where)
        allowed_kinds = RULES['send_kinds'] if step == 'send' else RULES['process_input_kinds']
        _kinds(item['kinds'], field + '/kinds', where, allowed_kinds)
        if item.get('cardinality') not in ('one', 'many'): raise Invalid('bad-cardinality', field + '/cardinality', where=where)
        if step == 'check' and item['cardinality'] != 'one': raise Invalid('bad-cardinality', field + '/cardinality', where=where)


def _output(item, i, step, roles):
    field, where = f'/outputs/{i}', _where('output', i + 1)
    _object(item, 'output', field, where)
    _identifier(item['role'], field + '/role', where, roles)
    _label(item['label'], field + '/label', where)
    cls = {'read': 'version', 'source': 'version', 'process': 'version', 'send': 'delivery', 'check': 'comparison'}[step]
    if item['class'] != cls: raise Invalid('wrong-output-class', field + '/class', where=where)
    if cls == 'version':
        kinds = RULES['process_kinds'] if step == 'process' else RULES['read_source_kinds']
        if 'kind' not in item: raise Invalid('missing-field', field + '/kind', where=where)
        if item['kind'] not in kinds: raise Invalid('kind-not-allowed', field + '/kind', where=where)
    elif 'kind' in item:
        raise Invalid('unknown-field', field + '/kind', where=where)  # delivery and comparison payloads come with E109, E110


def _setting(item, i, keys):
    field, where = f'/settings/{i}', _where('setting', i + 1)
    _object(item, 'setting', field, where)
    _identifier(item['key'], field + '/key', where, keys)
    _label(item['label'], field + '/label', where)
    kind = item['type']
    if kind not in RULES['setting_types']: raise Invalid('bad-type', field + '/type', where=where)
    allowed = {'number': {'unit', 'default', 'minimum', 'maximum'}, 'integer': {'unit', 'default', 'minimum', 'maximum'},
               'string': {'default'}, 'choice': {'default', 'choices'}, 'boolean': {'default'}}[kind]
    stray = sorted(set(item) - {'key', 'label', 'type'} - allowed)
    if stray: raise Invalid('unknown-field', field + '/' + stray[0], where=where)
    if 'unit' in item and item['unit'] not in RULES['units']: raise Invalid('bad-unit', field + '/unit', where=where)
    fits = {'number': _number, 'integer': _integer, 'boolean': lambda v: isinstance(v, bool),
            'string': lambda v: isinstance(v, str) and len(v) <= LIMITS['string_setting_characters'] and not CONTROL.search(v)}.get(kind)
    if kind in ('number', 'integer'):
        for bound in ('minimum', 'maximum'):
            if bound in item and not fits(item[bound]): raise Invalid('bad-bounds', f'{field}/{bound}', where=where)
        if 'minimum' in item and 'maximum' in item and item['minimum'] > item['maximum']: raise Invalid('bad-bounds', field + '/maximum', where=where)
    if kind == 'choice':
        choices = item.get('choices')
        if not isinstance(choices, list) or not 2 <= len(choices) <= LIMITS['choices']: raise Invalid('bad-choices', field + '/choices', where=where)
        values = set()
        for j, choice in enumerate(choices):
            cfield, cwhere = f'{field}/choices/{j}', _where('choice', i + 1, j + 1)
            _object(choice, 'choice', cfield, cwhere)
            if not isinstance(choice['value'], str) or not IDENTIFIER.match(choice['value']) or choice['value'] in values:
                raise Invalid('bad-choices', cfield + '/value', where=where)
            values.add(choice['value'])
            _label(choice['label'], cfield + '/label', cwhere)
        fits = lambda v: v in values  # noqa: E731 (a choice's default is one of its values, never its label)
    if 'default' in item:
        value = item['default']
        if not fits(value) or (kind in ('number', 'integer') and (value < item.get('minimum', value) or value > item.get('maximum', value))):
            raise Invalid('bad-default', field + '/default', where=where)


def _entry(value, members):
    match = ENTRY.match(value) if isinstance(value, str) else None
    if not match: raise Invalid('bad-entry', '/entry')
    module = match.group(1).replace('.', '/')
    if module + '.py' not in members and module + '/__init__.py' not in members: raise Invalid('missing-file', '/entry')


def check_manifest(manifest, members):
    """Raise Invalid for the first defect of a parsed manifest, given the bundle's member paths; return it otherwise."""
    _object(manifest, 'procedure', '', _where('procedure'))
    if manifest['schema'] != SCHEMA: raise Invalid('wrong-schema', '/schema')
    if not isinstance(manifest['name'], str) or not NAME.match(manifest['name']): raise Invalid('bad-name', '/name')
    _label(manifest['label'], '/label', _where('procedure'))
    if not _integer(manifest['version']) or not 1 <= manifest['version'] <= LIMITS['version']: raise Invalid('bad-version', '/version')
    if 'version_label' in manifest: _label(manifest['version_label'], '/version_label', _where('version_label'))
    step = manifest['step']
    if step not in RULES['steps']: raise Invalid('bad-step', '/step')
    inputs = _list(manifest['inputs'], '/inputs', _where('procedure'), LIMITS['inputs'], 1)
    slots = set()
    for i, item in enumerate(inputs): _input(item, i, step, slots)
    classes = [item['class'] for item in inputs]
    if step in ('read', 'source') and len(inputs) != 1: raise Invalid('wrong-input-count', '/inputs')
    if step == 'check' and sorted(classes) != ['reference', 'version']: raise Invalid('wrong-input-count', '/inputs')
    outputs = _list(manifest['outputs'], '/outputs', _where('procedure'), LIMITS['outputs'], 1)
    roles = set()
    for i, item in enumerate(outputs): _output(item, i, step, roles)
    if step in ('send', 'check') and len(outputs) != 1: raise Invalid('wrong-output-count', '/outputs')
    keys = set()
    for i, item in enumerate(_list(manifest.get('settings', []), '/settings', _where('procedure'), LIMITS['settings'])): _setting(item, i, keys)
    _entry(manifest['entry'], members)
    for i, item in enumerate(_list(manifest.get('requires', []), '/requires', _where('procedure'), LIMITS['requires'])):
        _text(item, f'/requires/{i}', _where('procedure'))
    if 'licence' in manifest: _text(manifest['licence'], '/licence', _where('procedure'))
    return manifest


def _no_constant(name):
    raise ValueError(name)


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys): raise ValueError('duplicate key')
    return dict(pairs)


def parse_manifest(raw):
    """procedure.json as a dict: strict JSON (no NaN or Infinity, no repeated key), or Invalid('not-json')."""
    try: return json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw, parse_constant=_no_constant, object_pairs_hook=_pairs)
    except ValueError: raise Invalid('not-json', '') from None


# ---------------------------------------------------------------- the bundle

def canonical(path):
    """True for the one accepted spelling of a member path: `/`-separated parts, none empty, `.` or `..`; no
    leading or trailing `/`, backslash or control character; at most 160 characters. `./a` is refused, not
    normalised (M6)."""
    if not isinstance(path, str) or not path or len(path) > LIMITS['path_characters'] or '\\' in path or CONTROL.search(path): return False
    return all(part not in ('', '.', '..') for part in path.split('/'))


def _listdir(directory):
    """One folder's entries (the walk's only source of order; tests replace it to force orders, M3)."""
    with os.scandir(directory) as entries:
        return [entry.name for entry in entries]


def _excluded(parts):
    return any(part in NOT_MEMBERS for part in parts[:-1]) or parts[-1] in NOT_MEMBERS or parts[-1].endswith('.pyc')


def read_members(folder):
    """{path: bytes} of every member of a bundle folder, or Invalid. `__pycache__/` and `*.pyc` are never members."""
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir(): raise Invalid('no-manifest', '')
    files, total, pending = {}, 0, [()]
    while pending:
        parts = pending.pop()
        for name in _listdir(folder.joinpath(*parts)):
            here = parts + (name,)
            if _excluded(here): continue
            path = folder.joinpath(*here)
            mode = os.lstat(path).st_mode
            if stat.S_ISDIR(mode): pending.append(here); continue
            relative = '/'.join(here)
            if not stat.S_ISREG(mode) or not canonical(relative): raise Invalid('bad-member', relative)
            if len(files) == LIMITS['files']: raise Invalid('too-many-files', '')
            raw = path.read_bytes(); total += len(raw)
            if total > LIMITS['bytes']: raise Invalid('too-large', '')
            try: raw.decode('utf-8')
            except UnicodeDecodeError: raise Invalid('not-text', relative) from None
            files[relative] = raw
    if MANIFEST not in files: raise Invalid('no-manifest', '')
    return files


def digest_of(files):
    """sha256 over the sorted member paths and each member's sha256: order and timestamps cannot change it."""
    h = hashlib.sha256(DIGEST_PREFIX)
    for path in sorted(files):
        h.update(path.encode('utf-8') + b'\0' + hashlib.sha256(files[path]).hexdigest().encode('ascii') + b'\n')
    return h.hexdigest()


def digest(folder):
    return digest_of(read_members(folder))


def _words(manifest):
    kinds = RULES['kind_words']
    def one(item):
        if item['class'] == 'file': return 'a file (' + ', '.join(item['signature']['extensions']) + ')'
        if item['class'] == 'system': return item['label']
        if item['class'] == 'reference' and item['from'] == 'file': return 'a reference file'
        return ' or '.join(kinds[k] for k in item['kinds'])
    def made(item):
        return {'delivery': 'a delivery', 'comparison': 'a comparison'}.get(item['class']) or kinds[item['kind']]
    return ' and '.join(one(i) for i in manifest['inputs']), ' and '.join(made(o) for o in manifest['outputs'])


def check_files(files):
    """The verdict on a bundle given as {path: bytes} (already read): the manifest, its digest and its words."""
    if len(files) > LIMITS['files']: raise Invalid('too-many-files', '')
    if sum(len(raw) for raw in files.values()) > LIMITS['bytes']: raise Invalid('too-large', '')
    for path, raw in files.items():
        if not canonical(path) or _excluded(tuple(path.split('/'))): raise Invalid('bad-member', path)
        try: raw.decode('utf-8')
        except UnicodeDecodeError: raise Invalid('not-text', path) from None
    if MANIFEST not in files: raise Invalid('no-manifest', '')
    manifest = check_manifest(parse_manifest(files[MANIFEST]), set(files))
    reads, makes = _words(manifest)
    return {'valid': True, 'rules_version': RULES_VERSION, 'manifest': manifest, 'digest': digest_of(files),
            'sentence': sentence('valid', label=manifest['label'], version=manifest['version'], reads=reads, makes=makes)}


def validate(folder):
    """The verdict on a bundle folder, never raising for a defect of the procedure: {'valid', 'sentence',
    'rules_version', ...}; a refusal adds 'code' and 'field' (the JSON path or member path)."""
    try: return check_files(read_members(folder))
    except Invalid as error:
        return {'valid': False, 'rules_version': RULES_VERSION, 'sentence': str(error), 'code': error.code, 'field': error.field}


# ---------------------------------------------------------------- the archive

def pack_files(files):
    """A deterministic tar (ustar, sorted, mtime 0, owner 0, mode 0644, files only) of {path: bytes}."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for path in sorted(files):
            info = tarfile.TarInfo(path)
            info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(files[path]), 0, 0o644, 0, 0, '', ''
            tar.addfile(info, io.BytesIO(files[path]))
    return out.getvalue()


def pack(folder):
    files = read_members(folder)
    check_files(files)
    return pack_files(files)


def read_archive(data):
    """{path: bytes} from an archive, refusing links, devices, unsafe or repeated names and oversize content from
    the headers before any member's content is read."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
            members = tar.getmembers()
            names = [m.name for m in members]
            if len(members) > LIMITS['files']: raise Invalid('too-many-files', '')
            if len(set(names)) != len(names): raise Invalid('bad-archive', '')
            if sum(m.size for m in members) > LIMITS['bytes']: raise Invalid('too-large', '')
            for m in members:
                if not m.isreg() or not canonical(m.name) or _excluded(tuple(m.name.split('/'))): raise Invalid('bad-archive', m.name)
            return {m.name: tar.extractfile(m).read() for m in members}
    except tarfile.TarError:
        raise Invalid('bad-archive', '') from None


def unpack_check(data, destination):
    """Check an archive completely, then write it into `destination` (absent, or an empty real folder). Nothing is
    written when anything is refused. Returns the verdict of check_files."""
    files = read_archive(data)
    verdict = check_files(files)
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise Invalid('bad-destination', '')
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(files):
        target = destination.joinpath(*path.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'xb') as handle: handle.write(files[path])
    return verdict
