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


@dataclass
class ProjectInput:
    """E106: a project version downloaded for a run: its file here, its stored type and declarations, and the exact
    version it is (recorded in run.json, so the run can be reported and published)."""
    path: str
    kind: str
    declared: dict
    asset_id: str
    revision: str


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
    # E105b: the project catalogue
    'changed-before-run': "Not run: the procedure's files changed after they were checked; nothing ran. Run it again.",
    'cache-changed': 'Not run: the copy of this procedure on this computer was changed, so it was removed. Run it again to fetch it from the project.',
    'no-enabled-version': 'Not run: {name} has no enabled version in this project.',
    'no-such-version': 'Not run: there is no version {version} of {name} in this project that you can see.',
    'withdrawn': 'Not run: this procedure was withdrawn on {date}.',
    'trust-needed': 'Not run: this procedure runs code someone else wrote on this computer. Answer the question in a terminal, or add --yes to trust it.',
    'declined': 'Not run: you did not trust this procedure. Nothing ran and nothing was recorded.',
    'bundle-differs': 'Not run: the procedure the project sent does not match its digest; nothing was kept.',
    # E106: project versions as inputs; publishing a run; running a result again
    'project-input-format': 'Not run: give a project version as --input SLOT=@RESULT:REVISION.',
    'project-input-class': 'Not run: {label} reads a file, not a project version.',
    'not-a-run': 'Not published: this folder is not the output of a run (run.json is missing or changed).',
    'local-inputs': 'Not published: this run read files from this computer; run it on project versions (--input SLOT=@RESULT:REVISION) to publish it.',
    'output-changed': 'Not published: {file} changed after the run; run it again.',
    'inputs-differ': 'Not published: the project describes {label} differently from what the run used; run it again.',
    'refused': '{sentence}',
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
        listed = list(inputs.get(slot, ()))
        label, cls, paths = item['label'], item['class'], [str(Path(p.path if isinstance(p, ProjectInput) else p).resolve()) for p in listed]
        if any(isinstance(p, ProjectInput) for p in listed) and (cls != 'version' or item.get('from') == 'file'):
            raise NotRun('project-input-class', f'/inputs/{slot}', label=label)
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
        versions, record[slot] = [], []
        for path, chosen in zip(paths, listed):
            if isinstance(chosen, ProjectInput):  # E106: the stored type and declarations of an exact project version
                if chosen.kind not in item['kinds']: raise NotRun('wrong-kind', f'/inputs/{slot}', {'kind': chosen.kind, 'accepted': item['kinds']}, label=label)
                versions.append(LocalVersion(path, chosen.kind, dict(chosen.declared)))
                record[slot].append({'file': path, 'sha256': _sha256(path), 'kind': chosen.kind, 'declared': dict(chosen.declared),
                                     'asset_id': chosen.asset_id, 'revision': chosen.revision})
                continue
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
            record[slot].append({'file': path, 'sha256': _sha256(path), 'kind': kind, 'declared': given})
        bound[slot] = versions
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


def run(folder, destination, inputs=None, *, kinds=None, declared=None, systems=None, settings=None, expected_digest=None):
    """Run a procedure on this computer and write its outputs, a log and run.json into `destination`, a new folder;
    nothing is published. `inputs` maps slot -> paths; `kinds` and `declared` give a version input's type and
    declarations (an output of an earlier run carries its own); `systems` maps slot -> a local configuration file;
    `settings` are `name=value` texts. With `expected_digest` (E105b), the copy that runs must be exactly that version
    or nothing runs (`changed-before-run`). Raises NotRun; then no destination exists."""
    folder, destination = Path(folder).resolve(), Path(destination).absolute()
    verdict = validate(folder)
    if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
    manifest = verdict['manifest']
    if manifest['step'] in ('send', 'check'): raise NotRun('later-release', '/step', step=manifest['step'])
    if destination.exists() or destination.is_symlink(): raise NotRun('destination-exists', '', {'destination': str(destination)})
    target = destination.parent.resolve() / destination.name
    given = [Path(p.path if isinstance(p, ProjectInput) else p).resolve() for paths in (inputs or {}).values() for p in paths] + [Path(p).resolve() for p in (systems or {}).values()]
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
        copied = contract().digest(snapshot)
        if copied != verdict['digest']: raise NotRun('changed', '', {'validated': verdict['digest']})
        if expected_digest is not None and copied != expected_digest: raise NotRun('changed-before-run', '', {'expected': expected_digest, 'found': copied})
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


# ---------------------------------------------------------------- reported runs (E106)

PROJECT_INPUT = re.compile(r'^@([^:@\s]+):([^:@\s]+)$')
EXTENSIONS = {'las2/1': '.las', 'esri-ascii-grid/1': '.asc', 'well-location/1': '.json', 'wavelet-text/1': '.txt'}
OUTCOME_WORDS = {'same': 'Same result', 'same-newer': 'Same result, newer procedure version', 'same-earlier': 'Same result, earlier procedure version',
                 'different': 'Different result', 'not-compared': 'Not compared', 'no-earlier': 'No earlier result you can read to compare with'}


def before_report(state):
    """Called after publish.json is saved and before the report is sent (tests stop a publish here, row 15)."""


def manifest_of(folder):
    verdict = validate(folder)
    if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
    return verdict['manifest']


def contract_readers():
    return json.loads((CONTRACT.parents[2] / 'connectors' / 'v1' / 'readers.json').read_text(encoding='utf-8'))['readers']


def _extension(profile):
    return EXTENSIONS.get(profile, '.csv')


def _discard(inputs):
    """Remove the downloaded copies of project versions (the run keeps their checksums and exact versions)."""
    for given in (inputs or {}).values():
        for item in given:
            if isinstance(item, ProjectInput): shutil.rmtree(Path(item.path).parent, ignore_errors=True)


def _save(path, value):
    partial = path.with_name(path.name + '.partial')
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(partial, path)


def _text(value):
    """A typed setting as the `name=value` text a run reads."""
    if isinstance(value, bool): return 'true' if value else 'false'
    return value if isinstance(value, str) else repr(value)


def output_command(run_id, role):
    """The command id an output of a run is published under (the server's rule): the same for every retry."""
    return hashlib.sha256(f'{run_id}/{role}'.encode()).hexdigest()


def method_of(procedure, settings):
    """The method a run's output is published with: what the server derives from the run, exactly."""
    return {'name': procedure['label'][:80], 'declared': True, 'library': procedure['name'][:80], 'version': str(procedure['version']),
            'parameters': settings, 'script_sha256': procedure['digest']}


def titled(state, reported, output):
    """The name an output is published under: the name given (or the procedure's label), with the output's role
    when the procedure makes several."""
    name = state.get('name') or reported['procedure']['label']
    return (name if len(reported['outputs']) == 1 else f"{name}: {output['role']}")[:160]


def _outcome_words(receipt, name, kind, reported, earlier=None):
    """{outcome, sentence} for one published output, in words; identifiers stay in the receipt (--json). `earlier` is
    the title of the earlier result a "Same result" names (its name and version)."""
    outcome = (receipt.get('outcome') or {}).get('outcome') or 'published'
    procedure = reported['procedure']
    made = f"made with {procedure['label']} version {procedure['version']} on your computer"
    what = f"{name} ({contract().RULES['kind_words'].get(kind, kind)})"
    if outcome == 'published': return {'outcome': outcome, 'sentence': f'Published {what}, {made}.'}
    sentence = receipt['outcome']['sentence']
    if outcome.startswith('same'): return {'outcome': outcome, 'sentence': f'{sentence}: {earlier or name}. Nothing was published.'}
    return {'outcome': outcome, 'sentence': f'{sentence}: published {what} as a new private result, {made}.'}


# ---------------------------------------------------------------- the project catalogue (E105b)

def cache_root():
    """Where fetched catalogue versions are kept, one folder per digest (OPHIOLITE_PROCEDURE_CACHE, else the user cache)."""
    given = os.environ.get('OPHIOLITE_PROCEDURE_CACHE')
    if given: return Path(given)
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'ophiolite' / 'procedures'


def _day(at):
    import time
    return time.strftime('%-d %B %Y', time.gmtime(at))


def question(version):
    """What a person is asked before running a version they do not trust yet: who registered it, when it was enabled
    (or registered), and the exact digest."""
    when = _day(version.get('enabled_at') or version['added_at'])
    return {'label': version['label'], 'version': version['version'], 'by': version['added_by'], 'date': when, 'digest': version['digest'],
            'text': (f"{version['label']}, version {version['version']}, was registered by {version['added_by']} and enabled on {when}. "
                     f"Running it runs their code on this computer. Trust this version ({version['digest']})?")}


def _before_run(folder):
    """Called after the cached copy was checked and before it runs (tests change a file here, row 4)."""


class ProcedureClient:
    """Mixed into `Client` (uses its `_post`): the project's catalogue of procedures. Registering keeps a private
    version; an administrator enables it for the project; running a version someone else registered asks once whether
    you trust it (`trust`), then runs it on this computer exactly as `procedures.run` runs a folder."""

    def procedure_register(self, folder, *, command_id=None):
        """Register a procedure folder as a private version of this project (the server computes its digest)."""
        verdict = validate(folder)
        if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
        raw = pack(folder)
        sha = hashlib.sha256(raw).hexdigest()
        import base64
        body = {'command_id': command_id or 'register-' + sha[:55], 'archive': base64.b64encode(raw).decode('ascii'), 'archive_sha256': sha}
        return self._post('procedures', 'register', body, retry=True)

    def procedure_list(self, name=None):
        """The versions you can see, by name then version number, each with its words, state and whether you trust it."""
        return self._post('procedures', 'list', {'name': name} if name else {}, retry=True)['versions']

    def procedure_get(self, digest):
        return self._post('procedures', 'get', {'digest': digest}, retry=True)

    def procedure_bundle(self, digest):
        """The version's archive, checked here: its sha256 and the digest of the files it holds."""
        import base64
        out = self._post('procedures', 'bundle', {'digest': digest}, retry=True)
        raw = base64.b64decode(out['archive'])
        try: same = hashlib.sha256(raw).hexdigest() == out['archive_sha256'] and contract().digest_of(contract().read_archive(raw)) == digest
        except Exception: same = False
        if not same: raise NotRun('bundle-differs', '', {'digest': digest})
        return raw

    def _procedure_change(self, operation, digest, command_id):
        return self._post('procedures', operation, {'command_id': command_id or f'{operation}-{digest[:48]}', 'digest': digest}, retry=True)

    def procedure_enable(self, digest, *, command_id=None):
        return self._procedure_change('enable', digest, command_id)

    def procedure_withdraw(self, digest, *, command_id=None):
        return self._procedure_change('withdraw', digest, command_id)

    def procedure_trust(self, digest, *, command_id=None):
        return self._procedure_change('trust', digest, command_id)

    def procedure_version(self, name, version=None):
        """Without `version`: the highest enabled version of `name`. With it: that version, among those you can see
        (your own private ones included)."""
        found = [v for v in self.procedure_list(name) if v['name'] == name]
        chosen = [v for v in found if (v['state'] == 'enabled' if version is None else v['version'] == version)]
        if not chosen:
            if version is None: raise NotRun('no-enabled-version', '', {'name': name}, name=name)
            raise NotRun('no-such-version', '', {'name': name, 'version': version}, name=name, version=version)
        return max(chosen, key=lambda v: v['version'])

    def _cached(self, digest, cache=None):
        """The checked local copy of a version: a copy that no longer has its digest is removed and refused."""
        root = Path(cache) if cache else cache_root()
        folder = root / digest
        if folder.exists() or folder.is_symlink():
            try: same = folder.is_dir() and not folder.is_symlink() and contract().digest(folder) == digest
            except Exception: same = False
            if not same:
                shutil.rmtree(folder, ignore_errors=True)
                if folder.is_symlink() or folder.exists(): folder.unlink()
                raise NotRun('cache-changed', '', {'digest': digest})
            return folder
        raw = self.procedure_bundle(digest)
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='.fetch-', dir=root))
        try:
            verdict = unpack(raw, work / 'p')
            if not verdict.get('valid') or verdict.get('digest') != digest: raise NotRun('bundle-differs', '', {'digest': digest})
            os.rename(work / 'p', folder)
        finally: shutil.rmtree(work, ignore_errors=True)
        return folder

    def procedure_run(self, name, destination, inputs=None, *, version=None, prompt=None, yes=False, cache=None, kinds=None, declared=None,
                      systems=None, settings=None):
        """Run a catalogue version on this computer. The version is read again before every run (a withdrawal ends
        it), the local copy is checked by digest, and a version you neither registered nor trust asks `prompt(question)`
        once (or `yes=True` answers it); the answer is recorded as your trust. Nothing runs before that."""
        chosen = self.procedure_version(name, version)
        found = self.procedure_get(chosen['digest'])
        if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=_day(found['withdrawn_at']))
        digest = found['digest']
        folder = self._cached(digest, cache)
        if not (found['trusted'] or found['mine']):
            if not yes:
                if prompt is None: raise NotRun('trust-needed', '', {'digest': digest})
                if not prompt(question(found)): raise NotRun('declined', '', {'digest': digest})
            self.procedure_trust(digest)
        _before_run(folder)
        inputs = self._project_inputs(inputs or {})
        try: return run(folder, destination, inputs, kinds=kinds, declared=declared, systems=systems, settings=settings, expected_digest=digest)
        finally: _discard(inputs)

    # ------------------------------------------------------------ E106: project versions, reported runs, again

    def _project_inputs(self, inputs):
        """Each `@RESULT:REVISION` input downloaded as exactly that version, with its stored type and declarations
        (the typed descriptor's profile, and its context for the declarations the reader takes); other inputs as given."""
        out, work = {}, None
        try:
            for slot, given in inputs.items():
                out[slot] = []
                for n, text in enumerate(given):
                    found = PROJECT_INPUT.match(str(text)) if isinstance(text, str) else None
                    if found is None and isinstance(text, str) and text.startswith('@'): raise NotRun('project-input-format', f'/inputs/{slot}')
                    if found is None:
                        out[slot].append(text); continue
                    work = work or Path(tempfile.mkdtemp(prefix='ophiolite-inputs-'))
                    out[slot].append(self._download_version(found.group(1), found.group(2), work / f'{slot}-{n}'))
        except BaseException:
            _discard(out); shutil.rmtree(work, ignore_errors=True) if work else None
            raise
        return out

    def _download_version(self, asset, revision, stem, profile=None, declared=None):
        """One exact version for a run: its original, its stored type and declarations (given by the server for a run
        made again; otherwise read from its typed description)."""
        if profile is None:
            from urllib.parse import quote
            from . import _core
            from .client import PROFILES
            path = self.prefix + '/' + quote(asset, safe='') + '/revisions/' + quote(revision, safe='')
            described = self._json(path + '?' + PROFILES[1:], 256 * 1024)
            _core.verify_typed_descriptor(described, self.project, asset, revision)
            profile, context = described['profile'], described.get('scientific') or {}
            keys = [d['key'] for r in contract_readers() if r['profile'] == profile for d in r['declared']]
            declared = {k: context[k] for k in keys if isinstance(context.get(k), str)}
        stem.parent.mkdir(parents=True, exist_ok=True)
        target = stem.with_suffix(_extension(profile))
        self.download_original(asset, revision, target)
        return ProjectInput(str(target), profile, dict(declared or {}), asset, revision)

    def procedure_publish(self, folder, *, name=None, again_of=None):
        """Report a run of a catalogue version on project versions, then publish each of its outputs under the run. The
        report's command id is saved in the run folder (publish.json) before anything is sent, and every output is
        published under a command id derived from the run, so publishing again after a stop or a lost answer resumes:
        one run, each output once. Returns {sentence, run, outputs: [{role, outcome, sentence, receipt}]}."""
        folder = Path(folder)
        try: record = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): raise NotRun('not-a-run') from None
        if record.get('schema') != LOCAL_RUN: raise NotRun('not-a-run')
        if record.get('systems') or any('asset_id' not in v for versions in record['inputs'].values() for v in versions): raise NotRun('local-inputs')
        outputs = []
        for role, output in record['outputs'].items():
            path = folder / output['file']
            if not path.is_file() or _sha256(path) != output['sha256']: raise NotRun('output-changed', f'/outputs/{role}', file=output['file'])
            outputs.append({'role': role, 'sha256': output['sha256'], 'bytes': path.stat().st_size, 'declared': output['declared']})
        state_path = folder / 'publish.json'
        try: state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError): state = None
        if state is None:  # saved before the report is sent (row 15): a lost answer is the same command again
            import uuid
            state = {'schema': 'ophiolite.procedure-publish/1', 'command_id': 'run-' + uuid.uuid4().hex, 'name': name, 'again_of': again_of}
            _save(state_path, state)
        before_report(state)
        body = {'command_id': state['command_id'], 'procedure': {'digest': record['procedure']['digest']}, 'settings': record['settings'],
                'inputs': {slot: [{'asset_id': v['asset_id'], 'revision': v['revision']} for v in versions] for slot, versions in record['inputs'].items()},
                'outputs': outputs, 'again_of': state.get('again_of')}
        reported = self._reported(lambda: self._post('procedure-runs', 'report', body, retry=True))
        for slot, versions in record['inputs'].items():
            for used, stored in zip(versions, reported['inputs'].get(slot, [])):
                if stored.get('restricted') or (stored.get('profile'), stored.get('declared') or {}) != (used['kind'], used['declared'] or {}):
                    raise NotRun('inputs-differ', f'/inputs/{slot}', label=slot)
        done = {o['role']: o for o in reported['outputs'] if o['outcome'] is not None}
        method = method_of(reported['procedure'], reported['settings'])
        parents = [{'asset_id': v['asset_id'], 'revision': v['revision']} for slot in record['inputs'] for v in record['inputs'][slot]]
        parents = list({(p['asset_id'], p['revision']): p for p in parents}.values())
        results = []
        for output in reported['outputs']:
            role = output['role']
            if role in done:
                receipt = done[role]['receipt']
            else:
                local = record['outputs'][role]
                raw = (folder / local['file']).read_bytes()
                receipt = self._run_output(raw, local['profile'], local['declared'], titled(state, reported, output), parents, method, reported['run_id'], role)
            earlier = self._title_of(receipt) if (receipt.get('outcome') or {}).get('outcome', '').startswith('same') else None
            results.append({'role': role, 'kind': output['kind'], 'receipt': receipt, **_outcome_words(receipt, titled(state, reported, output), output['kind'], reported, earlier)})
        state['run_id'] = reported['run_id']; _save(state_path, state)
        return {'sentence': '\n'.join(r['sentence'] for r in results), 'run': self.procedure_run_get(reported['run_id']), 'outputs': results}

    def _named(self, reference):
        """A result's story node (its name and version), or {} when the story does not answer."""
        from .errors import OphioliteError
        try: return next(n for n in self.story(reference['asset_id'], reference['revision'], limit=1)['nodes'] if n.get('asset_id') == reference['asset_id'])
        except (OphioliteError, StopIteration, KeyError): return {}

    def _title_of(self, reference):
        node = self._named(reference)
        if not node.get('name'): return None
        return node['name'] + (', version %d' % node['version'] if node.get('version') else '')

    def _reported(self, call):
        from .errors import Refused, IntegrityConflict
        try: return call()
        except (Refused, IntegrityConflict) as error:
            if getattr(error, 'code', None) == 'procedure-run-refused': raise NotRun('refused', '', {'reason': getattr(error, 'details', {}).get('reason')}, sentence=error.message) from None
            raise

    def _run_output(self, raw, profile, declared, name, parents, method, run_id, role):
        """publications/derive for one output of a run: the command id is the run's for this role (a retry is the same
        command); the receipt is the published result, or the earlier result for a run made again with the same result."""
        from .writers import WrittenOriginal
        receipt = self._reported(lambda: self.publish_derived(WrittenOriginal(raw, profile, dict(declared or {})), name=name[:160], from_=parents, method=method,
                                                              command_id=output_command(run_id, role), procedure={'id': run_id, 'role': role}))
        return receipt.model_dump(mode='json', exclude_none=True)

    def procedure_run_get(self, run_id):
        return self._post('procedure-runs', 'get', {'run_id': run_id}, retry=True)

    def procedure_prepare_again(self, asset, revision):
        return self._reported(lambda: self._post('procedure-runs', 'prepare-again', {'asset_id': asset, 'revision': revision}, retry=True))

    def procedure_again(self, asset, revision, destination, *, version=None, folder=None, prompt=None, yes=False, cache=None, name=None):
        """Run a procedure-made result again on this computer and publish it under the new run: the server says per
        output whether it is the same result (nothing published) or a new private result made again from the earlier
        one. `version` runs another catalogue version of the same procedure; `folder` runs a local copy whose digest is
        a catalogue version."""
        prepared = self.procedure_prepare_again(asset, revision)
        words = prepared['procedure']
        if name is None:  # a new result made again is named after the earlier one
            earlier = self._named({'asset_id': asset, 'revision': revision}).get('name')
            name = earlier and (earlier[:146] + ' (made again)')
        if folder is not None:
            local = Path(folder)
            found = self.procedure_get(digest(local))
            if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=_day(found['withdrawn_at']))
        else:
            chosen = self.procedure_version(words['name'], version) if version is not None else {'digest': words['digest']}
            found = self.procedure_get(chosen['digest'])
            if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=_day(found['withdrawn_at']))
            local = self._cached(found['digest'], cache)
            if not (found['trusted'] or found['mine']):
                if not yes:
                    if prompt is None: raise NotRun('trust-needed', '', {'digest': found['digest']})
                    if not prompt(question(found)): raise NotRun('declined', '', {'digest': found['digest']})
                self.procedure_trust(found['digest'])
        manifest = manifest_of(local)
        work = Path(tempfile.mkdtemp(prefix='ophiolite-inputs-'))
        try:
            inputs = {slot: [self._download_version(b['asset_id'], b['revision'], work / f'{slot}-{n}', b['profile'], b['declared'] or {})
                             for n, b in enumerate(bindings)] for slot, bindings in prepared['inputs'].items()}
            settings = [f'{k}={_text(v)}' for k, v in prepared['settings'].items() if k in {s['key'] for s in manifest.get('settings', [])}]
            _before_run(local)
            ran = run(local, destination, inputs, settings=settings, expected_digest=found['digest'])
        finally: shutil.rmtree(work, ignore_errors=True)
        published = self.procedure_publish(destination, name=name, again_of={'asset_id': asset, 'revision': revision})
        return {**published, 'ran': ran['sentence']}
