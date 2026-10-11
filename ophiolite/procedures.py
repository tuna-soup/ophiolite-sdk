"""E105a: procedures — a team's own code, described by a procedure.json, checked here exactly as Ophiolite checks it,
and run on this computer (`run`: a child process, from a fresh copy of exactly the files the digest covers).

The validator is the contract's own file, `ophiolite/contracts/procedures/v1/procedure.py`, byte-identical to the
Platform's (the contract snapshot, SOURCE.json). It is loaded from its source text, so no bytecode is written into
the package. Validating, hashing and packing read files only: nothing is imported from a procedure, and nothing
here contacts a server. A run publishes nothing; its run.json is local and provisional.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'procedures' / 'v1' / 'procedure.py'
_contract = None


def contract():
    """The packaged validator module (loaded once, from source text; reads and writes no bytecode)."""
    global _contract
    if _contract is None:
        module = types.ModuleType('ophiolite_procedure_contract')
        module.__file__ = str(CONTRACT)
        exec(compile(CONTRACT.read_text(encoding='utf-8'), str(CONTRACT), 'exec'), module.__dict__)
        _contract = module
    return _contract


def validate(folder):
    """The verdict on a procedure folder: {'valid', 'sentence', 'rules_version', ...}; a refusal adds 'code' and
    'field' (the JSON path or member path). The same rules_version gives the same verdict on the server."""
    return contract().validate(Path(folder))


def digest(folder):
    """The procedure's identity: sha256 over its member paths and contents (Ophiolite computes it; nobody types it)."""
    return contract().digest(Path(folder))


def pack(folder):
    """The procedure as a deterministic archive (bytes); refused when the folder is not a valid procedure."""
    return contract().pack(Path(folder))


def unpack(data, destination):
    """Check an archive completely, then write it into a new or empty folder; returns the verdict."""
    return contract().unpack_check(data, Path(destination))


# ---------------------------------------------------------------- running on this computer (C5)

LOCAL_RUN = 'ophiolite.local-run/0'  # local and provisional: not in the contracts registry; E106 owns the reported run
SYSTEM_RECORDED = 'configured on this computer'


@dataclass(frozen=True)
class LocalFile:
    """A file given to a read procedure: its path and its file name."""
    path: str
    name: str


@dataclass(frozen=True)
class LocalVersion:
    """Data given to a process procedure: the file, its type (kind) and the declarations recorded beside it."""
    path: str
    kind: str
    declared: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LocalSystem:
    """A source procedure's connection settings, read from a local file; never copied into a record."""
    config: dict = field(repr=False)


def procedure(function):
    """Mark the function a procedure's entry names; `run` refuses an entry that is not marked."""
    function.__ophiolite_procedure__ = True
    return function


SENTENCES = {
    'later-release': 'Not run: running a {step} procedure comes with a later release.',
    'destination-exists': 'Not run: the output folder already exists; name a new one.',
    'overlap': 'Not run: the output folder must be outside the procedure folder and its inputs.',
    'unknown-input': 'Not run: an input was given that this procedure does not read.',
    'missing-input': 'Not run: {label} needs a file.',
    'too-many-inputs': 'Not run: {label} takes one file.',
    'not-a-file': 'Not run: the file for {label} cannot be read.',
    'signature': 'Not run: the file for {label} does not look like the files this procedure reads.',
    'no-kind': 'Not run: say what type of data {label} is (--kind), or give an output of an earlier run.',
    'wrong-kind': 'Not run: {label} cannot read that type of data.',
    'bad-declared': 'Not run: the declarations for {label} must be a JSON object.',
    'system-config': 'Not run: {label} needs its configuration file, holding exactly its settings as text.',
    'setting-format': 'Not run: give each setting as --setting name=value.',
    'setting-unknown': 'Not run: a setting was given that this procedure does not have.',
    'setting-twice': 'Not run: {label} was given more than once.',
    'setting-missing': 'Not run: {label} needs a value.',
    'setting-type': 'Not run: {label} needs {what}.',
    'setting-bounds': 'Not run: {label} is outside its allowed range.',
    'changed': "Not run: the procedure's files changed while it was being prepared; run it again.",
    'not-marked': 'Not run: the entry function is not marked with @procedure.',
    'raised': 'Not run: the procedure stopped with an error. Its details are under --json.',
    'stopped': 'Not run: the procedure stopped before it finished.',
    'returned-wrong': 'Not run: the procedure must return its outputs by name, each made with an ophiolite writer.',
    'missing-output': 'Not run: the procedure did not make {label}.',
    'extra-output': 'Not run: the procedure made an output it does not declare.',
    'wrong-profile': 'Not run: {label} was made as a different type of data than declared.',
}
WHAT = {'number': 'a finite number', 'integer': 'a whole number', 'boolean': 'true or false', 'choice': 'one of its choices', 'string': 'a short text'}
INTEGER = re.compile(r'^[-+]?[0-9]+$')
NUMBER = re.compile(r'^[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?$')


class NotRun(Exception):
    """A run that did not happen: `code`, the plain sentence, and technical details for --json only."""

    def __init__(self, code, field='', details=None, **words):
        self.code, self.field, self.details = code, field, details or {}
        super().__init__(SENTENCES[code].format(**words) if code in SENTENCES else words.get('sentence', code))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _setting_values(manifest, given):
    """Settings from `name=value` texts (command-line form), typed strictly and with defaults filled (M4)."""
    declared = {s['key']: s for s in manifest.get('settings', [])}
    raw = {}
    for text in given or ():
        if '=' not in text: raise NotRun('setting-format')
        key, value = text.split('=', 1)
        if key not in declared: raise NotRun('setting-unknown', '/settings', {'given': key})
        if key in raw: raise NotRun('setting-twice', f'/settings/{key}', label=declared[key]['label'])
        raw[key] = value
    values = {}
    for key, setting in declared.items():
        label, kind = setting['label'], setting['type']
        if key not in raw:
            if 'default' not in setting: raise NotRun('setting-missing', f'/settings/{key}', label=label)
            values[key] = setting['default']; continue
        text = raw[key]
        wrong = NotRun('setting-type', f'/settings/{key}', {'given': text, 'type': kind}, label=label, what=WHAT[kind])
        if kind == 'boolean':
            if text not in ('true', 'false'): raise wrong
            value = text == 'true'
        elif kind == 'integer':
            if not INTEGER.match(text): raise wrong
            value = int(text)
        elif kind == 'number':
            if not NUMBER.match(text): raise wrong
            value = float(text)
            if not math.isfinite(value): raise wrong
        elif kind == 'choice':
            if text not in [c['value'] for c in setting['choices']]: raise wrong
            value = text
        else:
            if len(text) > contract().LIMITS['string_setting_characters'] or contract().CONTROL.search(text): raise wrong
            value = text
        if kind in ('number', 'integer') and (value < setting.get('minimum', value) or value > setting.get('maximum', value)):
            raise NotRun('setting-bounds', f'/settings/{key}', {'given': text, 'minimum': setting.get('minimum'), 'maximum': setting.get('maximum')}, label=label)
        values[key] = value
    return values


def _earlier_run(path):
    """The kind and declarations of a file that an earlier local run wrote (its run.json beside it), or None."""
    record = Path(path).parent / 'run.json'
    try: run = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
    if run.get('schema') != LOCAL_RUN: return None
    for output in (run.get('outputs') or {}).values():
        if output.get('file') == Path(path).name: return output.get('profile'), output.get('declared') or {}
    return None


def _matches(item, path):
    signature = item['signature']
    if Path(path).suffix.lower() not in signature['extensions']: return False
    with open(path, 'rb') as handle: head = handle.read(signature['max_head_bytes']).decode('utf-8', 'replace')
    return all(head.startswith(p[1:]) if p.startswith('^') else p in head for p in signature['head_patterns'])


def _bind(manifest, inputs, kinds, declared, systems):
    """The local inputs the entry function receives, per slot, and their record for run.json (D4)."""
    slots = {item['slot']: item for item in manifest['inputs']}
    for slot in (*inputs, *kinds, *declared, *systems):
        if slot not in slots: raise NotRun('unknown-input', '/inputs', {'given': slot})
    bound, record, systems_record = {}, {}, {}
    for slot, item in slots.items():
        label, cls, paths = item['label'], item['class'], [str(Path(p).resolve()) for p in inputs.get(slot, ())]
        if cls == 'system':
            config_path = systems.get(slot)
            if config_path is None: raise NotRun('missing-input', f'/inputs/{slot}', label=label)
            try: config = json.loads(Path(config_path).read_text(encoding='utf-8'))
            except (OSError, ValueError): raise NotRun('system-config', f'/inputs/{slot}', label=label) from None
            if not isinstance(config, dict) or set(config) != set(item.get('config_keys', [])) or not all(isinstance(v, str) for v in config.values()):
                raise NotRun('system-config', f'/inputs/{slot}', {'expected_keys': item.get('config_keys', [])}, label=label)
            bound[slot] = LocalSystem(config); systems_record[slot] = SYSTEM_RECORDED
            continue
        if not paths: raise NotRun('missing-input', f'/inputs/{slot}', label=label)
        if (cls == 'file' or item.get('cardinality') == 'one' or item.get('from') == 'file') and len(paths) > 1:
            raise NotRun('too-many-inputs', f'/inputs/{slot}', label=label)
        for path in paths:
            if not Path(path).is_file(): raise NotRun('not-a-file', f'/inputs/{slot}', {'path': path}, label=label)
        if cls == 'file' or item.get('from') == 'file':
            if cls == 'file' and not all(_matches(item, p) for p in paths): raise NotRun('signature', f'/inputs/{slot}', {'path': paths[0]}, label=label)
            bound[slot] = [LocalFile(p, Path(p).name) for p in paths]
            record[slot] = [{'file': p, 'sha256': _sha256(p)} for p in paths]
            continue
        versions = []
        for path in paths:
            if slot in kinds:
                kind, given = kinds[slot], {}
                if slot in declared:
                    try: given = json.loads(Path(declared[slot]).read_text(encoding='utf-8'))
                    except (OSError, ValueError): given = None
                    if not isinstance(given, dict): raise NotRun('bad-declared', f'/inputs/{slot}', label=label)
            else:
                found = _earlier_run(path)
                if found is None: raise NotRun('no-kind', f'/inputs/{slot}', label=label)
                kind, given = found
            if kind not in item['kinds']: raise NotRun('wrong-kind', f'/inputs/{slot}', {'kind': kind, 'accepted': item['kinds']}, label=label)
            versions.append(LocalVersion(path, kind, given))
        bound[slot] = versions
        record[slot] = [{'file': v.path, 'sha256': _sha256(v.path), 'kind': v.kind, 'declared': v.declared} for v in versions]
    return bound, record, systems_record


def _between(folder):
    """Called after validation and before the snapshot is copied (tests change a file here, D2)."""


def _inside(a, b):
    return a == b or b in a.parents or a in b.parents


CHILD = 'import sys; from ophiolite.procedures import _child; sys.exit(_child(sys.argv[1]))'


def _encode(value):
    if isinstance(value, LocalFile): return {'local': 'file', 'path': value.path, 'name': value.name}
    if isinstance(value, LocalVersion): return {'local': 'version', 'path': value.path, 'kind': value.kind, 'declared': value.declared}
    if isinstance(value, LocalSystem): return {'local': 'system', 'config': value.config}
    return [_encode(v) for v in value]


def _decode(value):
    if isinstance(value, list): return [_decode(v) for v in value]
    kind = value.pop('local')
    return {'file': LocalFile, 'version': LocalVersion, 'system': LocalSystem}[kind](**value)


def _child(request_path):
    """In the child process: import the entry from the snapshot, call it, and hand each returned original back as
    bytes plus {profile, declared, filename} (D1). The parent checks everything."""
    import importlib
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    exchange = Path(request['exchange'])
    def fail(code, **details):
        (exchange / 'error.json').write_text(json.dumps({'code': code, **details}))
        return 3
    sys.path.insert(0, request['snapshot'])
    module_name, function_name = request['entry'].split(':')
    try:
        function = getattr(importlib.import_module(module_name), function_name)
    except Exception as error:
        return fail('raised', type=type(error).__name__, message=str(error)[:2000])
    if not getattr(function, '__ophiolite_procedure__', False): return fail('not-marked')
    inputs = {slot: _decode(value) for slot, value in request['inputs'].items()}
    try:
        returned = function(inputs, request['settings'])
    except Exception as error:
        return fail('raised', type=type(error).__name__, message=str(error)[:2000])
    if not isinstance(returned, dict): return fail('returned-wrong')
    outputs = {}
    for n, (role, original) in enumerate(returned.items()):
        if not all(hasattr(original, a) for a in ('bytes', 'profile', 'declared', 'filename')) or not isinstance(original.bytes, bytes):
            return fail('returned-wrong', role=str(role))
        (exchange / f'{n}.bytes').write_bytes(original.bytes)
        outputs[str(role)] = {'file': f'{n}.bytes', 'profile': original.profile, 'declared': dict(original.declared), 'filename': original.filename}
    (exchange / 'outputs.json').write_text(json.dumps(outputs))
    return 0


def run(folder, destination, inputs=None, *, kinds=None, declared=None, systems=None, settings=None):
    """Run a procedure on this computer and write its outputs, a log and run.json into `destination`, a new folder;
    nothing is published. `inputs` maps slot -> paths; `kinds` and `declared` give a version input's type and
    declarations (an output of an earlier run carries its own); `systems` maps slot -> a local configuration file;
    `settings` are `name=value` texts. Raises NotRun; then no destination exists."""
    folder, destination = Path(folder).resolve(), Path(destination).absolute()
    verdict = validate(folder)
    if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
    manifest = verdict['manifest']
    if manifest['step'] in ('send', 'check'): raise NotRun('later-release', '/step', step=manifest['step'])
    if destination.exists() or destination.is_symlink(): raise NotRun('destination-exists', '', {'destination': str(destination)})
    target = destination.parent.resolve() / destination.name
    given = [Path(p).resolve() for paths in (inputs or {}).values() for p in paths] + [Path(p).resolve() for p in (systems or {}).values()]
    if any(_inside(target, p) for p in [folder] + given): raise NotRun('overlap', '', {'destination': str(target)})
    values = _setting_values(manifest, settings)
    bound, input_record, system_record = _bind(manifest, inputs or {}, kinds or {}, declared or {}, systems or {})
    work = Path(tempfile.mkdtemp(prefix='ophiolite-procedure-'))
    partial = target.parent / f'{target.name}.partial-{os.getpid()}'
    try:
        _between(folder)
        snapshot, exchange = work / 'snapshot', work / 'exchange'
        files = contract().read_members(folder)
        for path, raw in files.items():
            member = snapshot.joinpath(*path.split('/'))
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(raw)
        exchange.mkdir()
        if contract().digest(snapshot) != verdict['digest']: raise NotRun('changed', '', {'validated': verdict['digest']})
        request = work / 'request.json'
        request.write_text(json.dumps({'snapshot': str(snapshot), 'exchange': str(exchange), 'entry': manifest['entry'], 'settings': values,
                                       'inputs': {slot: _encode(value) for slot, value in bound.items()}}))
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        child = subprocess.run([sys.executable, '-B', '-c', CHILD, str(request)], cwd=work, env=env, capture_output=True)
        log = child.stdout + (b'\n--- standard error ---\n' + child.stderr if child.stderr else b'')
        technical = {'exit_status': child.returncode, 'log': log.decode('utf-8', 'replace')[-4000:]}
        if (exchange / 'error.json').exists():
            error = json.loads((exchange / 'error.json').read_text())
            raise NotRun(error.pop('code'), '/entry', {**technical, **error})
        if child.returncode != 0 or not (exchange / 'outputs.json').exists(): raise NotRun('stopped', '', technical)
        made = json.loads((exchange / 'outputs.json').read_text())
        roles = {o['role']: o for o in manifest['outputs']}
        for role, output in roles.items():
            if role not in made: raise NotRun('missing-output', f'/outputs/{role}', technical, label=output['label'])
        if set(made) - set(roles): raise NotRun('extra-output', '/outputs', {**technical, 'made': sorted(made)})
        for role, output in roles.items():
            if made[role]['profile'] != output.get('kind'):
                raise NotRun('wrong-profile', f'/outputs/{role}', {'profile': made[role]['profile'], 'kind': output.get('kind')}, label=output['label'])
        partial.mkdir()
        outputs = {}
        for role, output in made.items():
            name = role + Path(output['filename']).suffix
            if name in ('log.txt', 'run.json'): name = role + '-output' + Path(output['filename']).suffix  # the run's own files keep their names
            shutil.copyfile(exchange / output['file'], partial / name)
            outputs[role] = {'file': name, 'sha256': _sha256(partial / name), 'profile': output['profile'], 'declared': output['declared']}
        (partial / 'log.txt').write_bytes(log)
        record = {'schema': LOCAL_RUN, 'procedure': {'name': manifest['name'], 'version': manifest['version'], 'digest': verdict['digest'],
                                                     'rules_version': verdict['rules_version']},
                  'settings': values, 'inputs': input_record, 'systems': system_record, 'outputs': outputs, 'runner': 'this computer'}
        (partial / 'run.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        os.rename(partial, target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    words = contract().RULES['kind_words']
    made_words = ', '.join(f"{words[o['profile']]} ({destination.name}/{o['file']})" for o in outputs.values())
    sentence = f"Ran {manifest['label']}, version {manifest['version']}, on this computer: made {made_words}. Nothing was published."
    return {'sentence': sentence, 'destination': str(target), 'run': record}


def new(folder, step, label):
    """Write a starting procedure folder for a step: procedure.json and procedure.py that validate as they are."""
    folder = Path(folder)
    if folder.exists() or folder.is_symlink(): raise NotRun('destination-exists', '', {'destination': str(folder)})
    name = re.sub(r'[^a-z0-9-]+', '-', folder.name.lower()).strip('-')[:63] or 'procedure'
    inputs = {'read': [{'slot': 'file', 'label': 'File to read', 'class': 'file', 'signature': {'extensions': ['.csv'], 'head_patterns': [], 'max_head_bytes': 4096}}],
              'source': [{'slot': 'system', 'label': 'System to read from', 'class': 'system', 'config_keys': []}],
              'process': [{'slot': 'tops', 'label': 'Tops to use', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'}],
              'send': [{'slot': 'data', 'label': 'Data to send', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'many'}],
              'check': [{'slot': 'data', 'label': 'Data to check', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'},
                        {'slot': 'reference', 'label': 'Reference file', 'class': 'reference', 'from': 'file'}]}[step]
    outputs = {'send': [{'role': 'delivery', 'label': 'Sent data', 'class': 'delivery'}],
               'check': [{'role': 'comparison', 'label': 'Comparison', 'class': 'comparison'}]}.get(step, [{'role': 'tops', 'label': 'Tops', 'class': 'version', 'kind': 'well-tops-csv/1'}])
    manifest = {'schema': 'ophiolite.procedure/1', 'name': name, 'label': label, 'version': 1, 'step': step, 'inputs': inputs, 'outputs': outputs,
                'settings': [], 'entry': 'procedure:main'}
    code = ('"""%s."""\nfrom ophiolite import procedure\n\n\n@procedure\ndef main(inputs, settings):\n'
            '    """Return each output by its role, made with an ophiolite writer (ophiolite.writers)."""\n'
            '    raise NotImplementedError("Write what this procedure does.")\n') % label
    folder.mkdir(parents=True)
    (folder / 'procedure.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (folder / 'procedure.py').write_text(code, encoding='utf-8')
    return validate(folder)
