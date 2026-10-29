"""E105a: procedures — a team's own code, described by a procedure.json, checked here exactly as Ophiolite checks it,
and run on this computer (`run`: a child process, from a fresh copy of exactly the files the digest covers).

The validator is the contract's own file, `ophiolite/contracts/procedures/v1/procedure.py`, byte-identical to the
Platform's (the contract snapshot, SOURCE.json). It is loaded from its source text, so no bytecode is written into
the package. Validating, hashing and packing read files only: nothing is imported from a procedure, and nothing
here contacts a server. A run publishes nothing; its run.json is local and provisional.
"""
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import uuid
import warnings
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
    """Data given to a process procedure: the file, its type (kind) and the declarations recorded beside it. E119b: a
    project version also says which version it is and, for a residual run's tops, the wellbore it is linked to."""
    path: str
    kind: str
    declared: dict = field(default_factory=dict)
    asset_id: str | None = None
    revision: str | None = None
    wellbore: str | None = None


@dataclass
class ProjectInput:
    """E106: a project version downloaded for a run: its file here, its stored type and declarations, and the exact
    version it is (recorded in run.json, so the run can be reported and published)."""
    path: str
    kind: str
    declared: dict
    asset_id: str
    revision: str
    wellbore: str | None = None  # E119b: set by residuals.prepare for a tops version


@dataclass(frozen=True)
class LocalSystem:
    """A source procedure's connection settings, read from a local file; never copied into a record."""
    config: dict = field(repr=False)


ITEMS_LIMIT = 1000000  # ophiolite.delivery/1's `items` bound


@dataclass(frozen=True)
class Delivered:
    """A send procedure's answer: the destination committed this delivery, `items` items (made by `delivered`)."""
    items: int


@dataclass(frozen=True)
class Refusal:
    """A send procedure's answer: nothing was written (made by `refused`). The reason is shown on this computer and
    kept in its log; it is never recorded in the project."""
    reason: str


def delivered(items):
    """What a send procedure returns when the destination holds the delivery: `items`, a whole number 0 to 1,000,000."""
    return Delivered(items)


def refused(reason):
    """What a send procedure returns when it wrote nothing, with the reason in words."""
    return Refusal(reason)


@dataclass(frozen=True)
class NotDelivered:
    """A reconcile function's answer: the destination committed a tombstone for this delivery id, so the writer's own
    transaction can no longer commit (made by `not_delivered`; D8, 4-1)."""


@dataclass(frozen=True)
class Unknown:
    """A reconcile function's answer: what became of the delivery cannot be told yet (made by `unknown`)."""


def not_delivered():
    """What a send procedure's `reconcile` returns only after its tombstone for the delivery id committed in the
    destination (a row the writer's transaction inserts first, so the two cannot both commit). The id's absence alone
    is `unknown()`."""
    return NotDelivered()


def unknown():
    """What a send procedure's `reconcile` returns when it cannot tell what became of the delivery."""
    return Unknown()


@dataclass(frozen=True)
class DeliveryAttempt:
    """A send procedure's third argument, `delivery`: the delivery's `id` (write it with the data, in the same
    transaction, so a later run can find out what became of it) and its `system`, the destination's LocalSystem
    (None for a send that names no system)."""
    id: str
    system: object = field(default=None, repr=False)


class Compared:
    """E110 (D9): what a check procedure's entry returns: the outcome and, when it counted, how many were compared
    and how many differed. Nothing else is recorded: no free text."""
    def __init__(self, outcome, compared=None, differed=None):
        self.outcome, self.compared, self.differed = outcome, compared, differed


def compared(outcome, compared=None, differed=None):
    """`return ophiolite.compared('differed', compared=24, differed=3)` from a check procedure's entry."""
    return Compared(outcome, compared, differed)


def procedure(function):
    """Mark the function a procedure's entry names; `run` refuses an entry that is not marked."""
    function.__ophiolite_procedure__ = True
    return function


SENTENCES = {
    'later-release': 'Not run: running a {step} procedure comes with a later release.',
    'requires-missing': 'Not run: {label} needs {names}; {installed}install {it_them} with: {command}',  # E112 s4 (S4-D5)
    'requires-malformed': 'Not run: {label} lists "{text}" under requires; {remedy}',
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
    'system-config': 'Not run: {label} needs its configuration file, holding exactly its settings as text{not_text}.',  # E121 O5
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
    'no-enabled-version': ('Not run: {name} has no enabled version in this project. A project administrator enables one in '  # E121 B5: the way
                           'Settings → Procedures or with ophiolite procedures enable.'),
    'no-such-version': 'Not run: there is no version {version} of {name} in this project that you can see.',
    'withdrawn': 'Not run: this procedure was withdrawn on {date}.',
    'trust-needed': 'Not run: this procedure runs code someone else wrote on this computer. Answer the question in a terminal, or add --yes to trust it.',
    'declined': 'Not run: you did not trust this procedure. Nothing ran and nothing was recorded.',
    'bundle-differs': 'Not run: the procedure the project sent does not match its digest; nothing was kept.',
    # E106: project versions as inputs; publishing a run; running a result again
    'project-input-format': 'Not run: give a project version as --input SLOT=@RESULT:REVISION.',
    'project-input-class': 'Not run: {label} reads a file, not a project version.',
    'project-input-kind': 'Not run: the project did not say what kind of data that version is.',
    'not-a-run': 'Not published: this folder is not the output of a run (run.json is missing or changed).',
    'local-inputs': 'Not published: this run read files from this computer; run it on project versions (--input SLOT=@RESULT:REVISION) to publish it.',
    'output-changed': 'Not published: {file} changed after the run; run it again.',
    # E111 s2 (P-10): an agent's read of one file with a procedure, refused before anything is sent
    'read-version': 'Not read: name the read procedure version to use (its digest).',
    'read-attribution': 'Not read: name who the file is attributed to (attribution); an agent\'s upload does not take the project\'s default.',
    'read-audience': 'Not read: name the members who may read the file (audience), or none for only the person.',
    'read-file-changed': 'Not sent: {file} changed after the person approved it; nothing was sent. Propose it again.',
    'inputs-differ': 'Not published: the project describes {label} differently from what the run used ({which}); run it again.',  # E121 B9
    'refused': '{sentence}',
    # E108: a source procedure's results added to the project
    'not-a-source': "Not run: {name} does not read from a team's system; only a source procedure adds its results this way.",
    'system-words': "Not run: name the team's system in words; its address and passwords stay in the configuration on this computer.",
    'setting-secret': 'A setting looks like an address or a password; put it in the system configuration on this computer.',  # D9 (ii)
    # E109: `ophiolite deliver` (slice 0's `not-available-yet` stays a reason code a host may still meet)
    'not-available-yet': "Delivering to a team's system is not available on this deployment yet.",
    'not-a-send': "Not sent: {name} does not deliver to a team's system; only a send procedure delivers.",
    'windows': 'Delivering from this computer is not supported on Windows yet.',  # R5-1: before anything is launched
    'item-format': 'Not sent: give each item as --item SLOT=NAME, --item SLOT=NAME@N (N its version number) or --item SLOT=@ASSET:REVISION.',
    'item-slot': 'Not sent: this procedure reads more than one kind of version; say which input each item is for (--item SLOT=NAME@N).',
    'item-missing': 'Not sent: there is no item named {name} in this project that you can see.',
    'item-ambiguous': 'Not sent: more than one item you can see is named {name}: {candidates}. Name one as @ASSET:REVISION.',
    'item-version': 'Not sent: {name} has no version {number} that you can see.',
    'item-unreadable': 'Not sent: {name} cannot be read here, so nothing was sent.',
    'delivery-busy': 'Another delivery from this folder is still running on this computer; try again when it has finished.',
    'delivery-pending': "This delivery's outcome is not known yet; it cannot be sent again.",  # R5-1: never relaunched
    'delivery-changed': 'Not sent: the system configuration, the settings or the procedure differ from the delivery waiting in this folder.',
    'delivery-other-person': 'Not sent: the delivery waiting in this folder was started with another access key.',
    'delivery-running': 'This delivery is still running on this computer; try again when it has finished.',  # D8
    'nothing-to-set-aside': 'There is no delivery of {name} waiting in this folder to set aside.',
    'set-aside-known': 'This delivery has an outcome on this computer; run deliver again to record it instead of setting it aside.',
    'set-aside-unreported': 'Not set aside: the project has not recorded the unknown outcome yet ({error}); try again.',
    # E120 (D7): `deliver --as OUTCOME` launches only when the project's gate claims the delivery
    'as-one-version': 'Not sent: deliver as {label} sends one result version; give one --item.',
    'as-refused': '{sentence}',
    # E110 (D9): a check procedure run on this computer; publishing it is `ophiolite checks publish`
    'check-project': 'Not run: a check reports on a project version; give {label} with --item SLOT=ITEM[@N].',
    'check-reference': 'Not run: give the reference as --reference FILE or --reference ITEM@N, as {label} reads.',
    'check-returned': 'Not run: the check returned {reason}',
    'check-wrong': 'Not run: a check procedure must return ophiolite.compared(outcome, compared, differed).',
}
WHAT = {'number': 'a finite number', 'integer': 'a whole number', 'boolean': 'true or false', 'choice': 'one of its choices', 'string': 'a short text'}
INTEGER = re.compile(r'^[-+]?[0-9]+$')
NUMBER = re.compile(r'^[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?$')


class NotRun(Exception):
    """A run that did not happen: `code`, the plain sentence, and technical details for --json only."""

    def __init__(self, code, field='', details=None, **words):
        self.code, self.field, self.details = code, field, details or {}
        super().__init__(SENTENCES[code].format(**words) if code in SENTENCES else words.get('sentence', code))


class ProcedureWarning(UserWarning):
    """E112 s4: registered as given, but something in it this SDK cannot check (a `requires` text outside its grammar)."""


def _and(names):
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _requirements(manifest):
    """E112 s4 (S4-D4): refuse a run or a delivery whose `requires` this interpreter does not meet, naming every missing
    distribution and the command that installs them; a text outside the grammar is refused with its text."""
    from . import _requires
    try: missing = _requires.unmet(manifest.get('requires', []))
    except _requires.Malformed as error:
        remedy = ('extras such as %s cannot be checked; list the package without them.' % re.search(r'\[[^\]]*\]', error.text).group(0) if error.extras
                  else 'write a package name with optional versions, such as psycopg>=3.1.')
        raise NotRun('requires-malformed', f'/requires/{error.index}', {'text': error.text}, label=manifest['label'], text=error.text, remedy=remedy) from None
    if not missing: return
    installed = ''.join(f"{m['name']} {m['found']} is installed{'' if m['readable'] else ', a version this check cannot read'}; "
                        for m in missing if m['found'] is not None)
    raise NotRun('requires-missing', '/requires', {'missing': [{k: m[k] for k in ('requirement', 'name', 'found')} for m in missing]},
                 label=manifest['label'], names=_and([m['name'] if m['found'] is None else m['requirement'] for m in missing]), installed=installed,
                 it_them='it' if len(missing) == 1 else 'them', command=_requires.install_line(missing))


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


NEUTRAL_SYSTEM = "a team's system"  # B6 rev 4 (6): a system label that does not read as a name
NEUTRAL_FOLDER = 'Team system'
THIS_PROCEDURE = 'this procedure'
KEPT = 'The files the procedure made are kept in {path}. To add them by hand: ophiolite upload {path}'


def _binding(name, system, role):
    """E108 S2 (B6 rev 4 (4)): what an output is the next version of: the procedure's name, the system in words, the role."""
    return json.dumps([name, system, role])


def _declared_sha(declared):
    return hashlib.sha256(json.dumps(declared or {}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def record_of(ran):
    return None if ran is None else ran['run']


def _recovery(made):
    """E108 S1 (B6 rev 4, R3-1): a new directory holding only the outputs the manifest lists, under their output file
    names, for a run whose files were not all added. The run's log.txt and run.json are never in it, so an upload of
    this directory sends nothing of them (an ordinary upload sends every regular file's first bytes to be detected)."""
    out = Path(tempfile.mkdtemp(prefix='ophiolite-source-files-'))
    for _, path, o in made: shutil.copyfile(path, out / Path(o['file']).name)
    return str(out)


def _secretive(text):
    """E108 (D9 ii, iii): the procedure contract's `secret-in-label` rule applied to a value: an address, an @ or a
    secret word. A heuristic for addresses and named secrets; the guarantee is that no configuration value is sent."""
    words = '|'.join(re.escape(w) for w in contract().RULES['secret_words'])
    return '://' in text or '@' in text or re.search(r'(?<![a-z])(' + words + r')s?(?![a-z])', text, re.IGNORECASE) is not None


def _resolved_settings(manifest, settings):
    """The typed settings a run reads. E108 D9 (ii), extended to send by E109 D9 (row 6-6): a source's or a send's
    resolved settings, defaults included, are refused when one looks like an address or a password, before anything runs."""
    values = _setting_values(manifest, settings)
    if manifest['step'] in ('source', 'send'):
        for key, value in values.items():
            if isinstance(value, str) and _secretive(value): raise NotRun('setting-secret', f'/settings/{key}')
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


def parent_slots(manifest):
    """E119b D2: the slots whose versions are parents of a result, by the contract's one rule (`procedure.parent_slots`):
    every slot, except a residual procedure's pinned ones (none in this version)."""
    return contract().parent_slots(manifest)


def run_parents(manifest, record):
    """A local run's parents in the order the Gateway checks them (`procedure_runs.parents`): the registered manifest's
    slot order, then the run's order within a slot, one per version. Never run.json's own order: its keys are sorted."""
    parents = [{'asset_id': v['asset_id'], 'revision': v['revision']} for slot in parent_slots(manifest) for v in record['inputs'].get(slot, [])]
    return list({(p['asset_id'], p['revision']): p for p in parents}.values())


def _bind(manifest, inputs, kinds, declared, systems):
    """The local inputs the entry function receives, per slot, and their record for run.json (D4)."""
    slots = {item['slot']: item for item in manifest['inputs']}
    for slot in (*inputs, *kinds, *declared, *systems):
        if slot not in slots: raise NotRun('unknown-input', '/inputs', {'given': slot})
    bound, record, systems_record = {}, {}, {}
    for slot, item in slots.items():
        listed = list(inputs.get(slot, ()))
        label, cls, paths = item['label'], item['class'], [str(Path(p.path if isinstance(p, ProjectInput) else p).resolve()) for p in listed]
        if any(isinstance(p, ProjectInput) for p in listed) and (cls not in ('version', 'reference') or item.get('from') == 'file'):
            raise NotRun('project-input-class', f'/inputs/{slot}', label=label)
        if cls == 'system':
            config_path = systems.get(slot)
            if config_path is None: raise NotRun('missing-input', f'/inputs/{slot}', label=label)
            try: config = json.loads(Path(config_path).read_text(encoding='utf-8'))
            except (OSError, ValueError): raise NotRun('system-config', f'/inputs/{slot}', label=label, not_text='') from None
            if not isinstance(config, dict) or set(config) != set(item.get('config_keys', [])):
                raise NotRun('system-config', f'/inputs/{slot}', {'expected_keys': item.get('config_keys', [])}, label=label, not_text='')
            other = sorted(k for k, v in config.items() if not isinstance(v, str))  # E121 O5: the keys, never a value
            if other:
                one = len(other) == 1
                raise NotRun('system-config', f'/inputs/{slot}', {'expected_keys': item.get('config_keys', []), 'not_text': other}, label=label,
                             not_text='; %s %s not text: put %s in quotes' % (' and '.join(other), 'is' if one else 'are', 'its value' if one else 'their values'))
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
                versions.append(LocalVersion(path, chosen.kind, dict(chosen.declared), chosen.asset_id, chosen.revision, chosen.wellbore))
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
    if isinstance(value, LocalVersion):  # E119b: the entry is told which project version it reads (None for a local file)
        return {'local': 'version', 'path': value.path, 'kind': value.kind, 'declared': value.declared,
                'asset_id': value.asset_id, 'revision': value.revision, 'wellbore': value.wellbore}
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
    if request.get('reconcile'): return _child_reconcile(function, request, exchange)  # D8: the manifest's reconcile, no marker
    if not getattr(function, '__ophiolite_procedure__', False): return fail('not-marked')
    inputs = {slot: _decode(value) for slot, value in request['inputs'].items()}
    if 'delivery' in request: return _child_send(function, inputs, request, exchange)
    if 'check' in request: return _child_check(function, inputs, request, exchange)
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


def _child_check(function, inputs, request, exchange):
    """E110 (D9): a check's entry is called as `entry(inputs, settings, reference)`; only what `compared(...)` holds is
    written (comparison.json), never what the code printed. The parent checks it."""
    reference = inputs.pop(request['check']['reference'])
    try:
        returned = function(inputs, request['settings'], reference[0] if isinstance(reference, list) and len(reference) == 1 else reference)
    except Exception as error:
        (exchange / 'error.json').write_text(json.dumps({'code': 'raised', 'type': type(error).__name__, 'message': str(error)[:2000]}))
        return 3
    if not isinstance(returned, Compared):
        (exchange / 'error.json').write_text(json.dumps({'code': 'check-wrong', 'returned': type(returned).__name__}))
        return 3
    said = {'outcome': returned.outcome, 'compared': returned.compared, 'differed': returned.differed}
    try: text = json.dumps(said)
    except (TypeError, ValueError): text = json.dumps({'outcome': None, 'compared': None, 'differed': None})
    (exchange / 'comparison.json').write_text(text)
    return 0


def _report_of(manifest, digest, values, bound, input_record, comparison):
    """E110 (D9, M5): check.json, the `procedure-report` that `ophiolite checks publish` sends: the exact subject
    version, the procedure's digest, the reference (a project version, or a file by name and digest), the settings and
    the returned outcome and counts. Refused here as the server would refuse it."""
    from .checks import report_refusal
    subject = next(i for i in manifest['inputs'] if i['class'] == 'version')
    reference = next(i for i in manifest['inputs'] if i['class'] == 'reference')
    given = input_record[subject['slot']][0]
    counts = None if comparison.get('compared') is None and comparison.get('differed') is None else \
        {'compared': comparison.get('compared'), 'differed': comparison.get('differed')}
    if reference.get('from') == 'file':
        made = input_record[reference['slot']][0]
        ref = {'kind': 'file', 'name': Path(made['file']).name[:200], 'digest': made['sha256']}
    else:
        made = input_record[reference['slot']][0]
        ref = {'kind': 'project-version', 'asset_id': made['asset_id'], 'revision': made['revision']}
    report = {'kind': 'procedure-report', 'subject': {'kind': 'result', 'asset_id': given['asset_id'], 'revision': given['revision']},
              'procedure_digest': digest, 'reference': ref, 'settings': values, 'outcome': comparison.get('outcome'), 'counts': counts}
    refusal = report_refusal(report)
    if refusal: raise NotRun('check-returned', '/entry', {'returned': comparison}, reason=refusal[0].lower() + refusal[1:])
    return report


def _child_send(function, inputs, request, exchange):
    """E109 (R4, D3): a send's entry is called as `entry(inputs, settings, delivery)`; what it returns is checked here
    and written as delivery.json: `delivered(items=n)` is confirmed, `refused(reason)` not sent (the reason goes to
    this computer's log only), anything else, an error included, unknown."""
    given = request['delivery']
    attempt = DeliveryAttempt(given['id'], inputs.get(given['system']) if given.get('system') else None)
    try:
        returned = function(inputs, request['settings'], attempt)
    except Exception as error:
        said = {'state': 'unknown', 'said': 'raised', 'type': type(error).__name__, 'message': str(error)[:2000]}
    else:
        if isinstance(returned, Delivered) and type(returned.items) is int and 0 <= returned.items <= ITEMS_LIMIT:
            said = {'state': 'confirmed', 'items': returned.items}
        elif isinstance(returned, Refusal) and isinstance(returned.reason, str):
            said = {'state': 'not-sent', 'reason': returned.reason[:2000]}
        else:
            said = {'state': 'unknown', 'said': 'malformed', 'returned': type(returned).__name__}
    (exchange / 'delivery.json').write_text(json.dumps(said))
    return 0


def _child_reconcile(function, request, exchange):
    """E109 (D3, D8): a send's `reconcile(delivery)` is called with the delivery's id and its system; `delivered(items=n)`
    is confirmed, `not_delivered()` not sent (the destination's tombstone committed, 4-1), anything else, an error
    included, unknown. Written as delivery.json, as the writer's answer is."""
    given = request['delivery']
    system = _decode(dict(given['system'])) if given.get('system') else None
    try:
        returned = function(DeliveryAttempt(given['id'], system))
    except Exception as error:
        said = {'state': 'unknown', 'said': 'raised', 'type': type(error).__name__, 'message': str(error)[:2000]}
    else:
        if isinstance(returned, Delivered) and type(returned.items) is int and 0 <= returned.items <= ITEMS_LIMIT:
            said = {'state': 'confirmed', 'items': returned.items}
        elif isinstance(returned, NotDelivered): said = {'state': 'not-sent'}
        elif isinstance(returned, Unknown): said = {'state': 'unknown', 'said': 'unknown'}
        else: said = {'state': 'unknown', 'said': 'malformed', 'returned': type(returned).__name__}
    (exchange / 'delivery.json').write_text(json.dumps(said))
    return 0


def run(folder, destination, inputs=None, *, kinds=None, declared=None, systems=None, settings=None, expected_digest=None):
    """Run a procedure on this computer and write its outputs, a log and run.json into `destination`, a new folder;
    nothing is published. `inputs` maps slot -> paths; `kinds` and `declared` give a version input's type and
    declarations (an output of an earlier run carries its own); `systems` maps slot -> a local configuration file;
    `settings` are `name=value` texts. With `expected_digest` (E105b), the copy that runs must be exactly that version
    or nothing runs (`changed-before-run`). Raises NotRun; then no destination exists. The result shows itself in a
    notebook with a "Run again" line made from the arguments as they were here (E112 s3)."""
    try: call = copy.deepcopy({'folder': str(Path(folder).resolve()), 'inputs': inputs, 'kinds': kinds, 'declared': declared, 'systems': systems,
                               'settings': settings})
    except Exception: call = None  # no line, and the card says why
    folder, destination = Path(folder).resolve(), Path(destination).absolute()
    verdict = validate(folder)
    if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
    manifest = verdict['manifest']
    _requirements(manifest)  # E112 s4: before the send refusal, a destination or a child process
    if manifest['step'] == 'send': raise NotRun('later-release', '/step', step=manifest['step'])
    if destination.exists() or destination.is_symlink(): raise NotRun('destination-exists', '', {'destination': str(destination)})
    target = destination.parent.resolve() / destination.name
    given = [Path(p.path if isinstance(p, ProjectInput) else p).resolve() for paths in (inputs or {}).values() for p in paths] + [Path(p).resolve() for p in (systems or {}).values()]
    if any(_inside(target, p) for p in [folder] + given): raise NotRun('overlap', '', {'destination': str(target)})
    values = _resolved_settings(manifest, settings)
    bound, input_record, system_record = _bind(manifest, inputs or {}, kinds or {}, declared or {}, systems or {})
    check = manifest['step'] == 'check'
    if check:  # E110 (D9): the report names the exact project version it checked (and the reference version)
        for item in manifest['inputs']:
            if (item['class'] == 'version' or item['class'] == 'reference' and item.get('from') != 'file') and \
                    not all(r.get('asset_id') and r.get('revision') for r in input_record.get(item['slot'], [])):
                raise NotRun('check-project', f"/inputs/{item['slot']}", label=item['label'])
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
                                       'inputs': {slot: _encode(value) for slot, value in bound.items()},
                                       **({'check': {'reference': next(i['slot'] for i in manifest['inputs'] if i['class'] == 'reference')}} if check else {})}))
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        child = subprocess.run([sys.executable, '-B', '-c', CHILD, str(request)], cwd=work, env=env, capture_output=True)
        log = child.stdout + (b'\n--- standard error ---\n' + child.stderr if child.stderr else b'')
        technical = {'exit_status': child.returncode, 'log': log.decode('utf-8', 'replace')[-4000:]}
        if (exchange / 'error.json').exists():
            error = json.loads((exchange / 'error.json').read_text())
            raise NotRun(error.pop('code'), '/entry', {**technical, **error})
        if check:
            if child.returncode != 0 or not (exchange / 'comparison.json').exists(): raise NotRun('stopped', '', technical)
            report = _report_of(manifest, verdict['digest'], values, bound, input_record, json.loads((exchange / 'comparison.json').read_text()))
            partial.mkdir()
            (partial / 'log.txt').write_bytes(log)
            (partial / 'check.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
            record = {'schema': LOCAL_RUN, 'procedure': {'name': manifest['name'], 'version': manifest['version'], 'digest': verdict['digest'],
                                                         'rules_version': verdict['rules_version']},
                      'settings': values, 'inputs': input_record, 'systems': system_record, 'outputs': {}, 'runner': 'this computer'}
            (partial / 'run.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
            os.rename(partial, target)
            outcome = {'passed': 'passed', 'differed': 'differed', 'not_compared': 'not compared'}[report['outcome']]
            sentence = (f"Ran {manifest['label']}, version {manifest['version']}, on this computer: {outcome}. Nothing was published; "
                        f"to report it to the project, run: ophiolite checks publish {destination.name}")
            return _presented({'sentence': sentence, 'destination': str(target), 'run': record, 'report': report}, call, manifest['label'])
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
    return _presented({'sentence': sentence, 'destination': str(target), 'run': record}, call, manifest['label'])


def _presented(result, call, label):
    from .presentation import PresentedRun  # every successful run loads it (s3-D3)
    return PresentedRun.present(result, call, label)


def new(folder, step, label=None, *, kind=None):
    """Write a working start for a step and a kind (E112 s1; well tops when no kind is given): procedure.json,
    procedure.py, its own tests and sample data, made by `procedure_templates.make`; returns `validate` of the folder.
    A pair with no start in this version raises ValueError with its sentence and makes no folder. `process` with no
    kind keeps E105a's start (frozen; ruling 25 Oct): a process start for a kind waits for ophiolite.readers."""
    from . import procedure_templates
    if step == 'process' and kind is None: return _process_start(folder, label or procedure_templates.default_label(step, procedure_templates.DEFAULT))
    return procedure_templates.make(folder, step, procedure_templates.DEFAULT if kind is None else kind, label)


def _process_start(folder, label):
    """E105a's process start: procedure.json and procedure.py that validate as they are, for the person to fill in."""
    folder = Path(folder)
    if folder.exists() or folder.is_symlink(): raise NotRun('destination-exists', '', {'destination': str(folder)})
    name = re.sub(r'[^a-z0-9-]+', '-', folder.name.lower()).strip('-')[:63] or 'procedure'
    manifest = {'schema': 'ophiolite.procedure/1', 'name': name, 'label': label, 'version': 1, 'step': 'process',
                'inputs': [{'slot': 'tops', 'label': 'Tops to use', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'}],
                'outputs': [{'role': 'tops', 'label': 'Tops', 'class': 'version', 'kind': 'well-tops-csv/1'}], 'settings': [], 'entry': 'procedure:main'}
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


def register_request(folder, command_id=None):
    """The procedures/register request for a valid folder: its archive and the archive's sha256 (an agent's plan names
    exactly these bytes, E105b row 7)."""
    import base64
    verdict = validate(folder)
    if not verdict['valid']: raise NotRun('not-valid', verdict['field'], {'code': verdict['code']}, sentence=verdict['sentence'])
    raw = pack(folder)
    sha = hashlib.sha256(raw).hexdigest()
    return {'command_id': command_id or 'register-' + sha[:55], 'archive': base64.b64encode(raw).decode('ascii'), 'archive_sha256': sha}


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


def _outcome_words(receipt, name, kind, reported, earlier=None, for_=None):
    """{outcome, sentence} for one published output, in words; identifiers stay in the receipt (--json). `earlier` is
    the title of the earlier result a "Same result" names (its name and version); `for_` the name of the outcome a
    republished result was published again for (E120)."""
    outcome = (receipt.get('outcome') or {}).get('outcome') or 'published'
    procedure = reported['procedure']
    made = f"made with {procedure['label']} version {procedure['version']} on your computer"
    what = f"{name} ({contract().RULES['kind_words'].get(kind, kind)})"
    if receipt.get('republished'): return {'outcome': 'republished', 'sentence': f'Published again for {for_}: {earlier or name}, the same result.'}
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


# ---------------------------------------------------------------- E109: a send procedure delivers exact versions

INTENT = 'ophiolite.delivery-intent/0'  # local and provisional: a "Deliver as" gate command before its claim is used (E120 5-20)
ATTEMPT = 'ophiolite.delivery-attempt/0'  # local and provisional, as run.json: one delivery's pending record (D2, D8, R5-1)
UNSAID = 'The procedure did not say whether it delivered.'  # M6
RAISED_NEXT = 'Check the system configuration given with --system {slot}, then run the same command to record what happened.'


def _raised(said, system, config):
    """adhoc-e121-claims (O6): for a procedure that raised, the first line of its error (at most 200 characters), each
    value of the system's configuration in it replaced by "…" so no configuration value is ever told, and the
    `--system` slot to check; None for any other answer. Kept on this computer; the report carries only the state."""
    if not isinstance(said, dict) or said.get('said') != 'raised': return None
    line = next((part.strip() for part in str(said.get('message') or '').splitlines() if part.strip()), '') or str(said.get('type') or 'an error')
    def values(value):
        if isinstance(value, dict): return [v for x in value.values() for v in values(x)]
        if isinstance(value, (list, tuple)): return [v for x in value for v in values(x)]
        return [] if value is None or isinstance(value, bool) else [str(value)]
    for value in sorted({v for v in values(config or {}) if len(v) >= 3}, key=len, reverse=True): line = line.replace(value, '…')
    return {'line': line[:200].rstrip('.'), 'slot': system['slot'] if system else None}
ITEM = re.compile(r'^(?![@\s])(.*?[^@\s])(?:@([1-9][0-9]{0,8}))?$')


def _windows():
    return os.name == 'nt'


def _launched(process, folder):
    """Called once the writer runs and its process group is recorded (tests stop the parent here, R5-1)."""


def _fingerprint(systems):
    """The configuration's fingerprint (R1): sha256 over each system's parsed file; kept on this computer only (D9)."""
    given = {}
    for slot, path in sorted((systems or {}).items()):
        try: given[slot] = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError): given[slot] = None
    return hashlib.sha256(json.dumps(given, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _items(manifest, texts):
    """`--item` texts as (slot, name, number or None), in the order given. `SLOT=NAME[@N]`; a bare `NAME[@N]` only when
    the procedure has exactly one version slot (2-4)."""
    slots = [i['slot'] for i in manifest['inputs'] if i['class'] == 'version']
    out = []
    for text in texts or ():
        slot, sep, rest = str(text).partition('=')
        if not sep:  # a name with "=" in it is given with its slot
            if len(slots) != 1: raise NotRun('item-slot', '/inputs', {'given': str(text)})
            slot, rest = slots[0], str(text)
        elif slot not in slots: raise NotRun('unknown-input', '/inputs', {'given': slot})
        if PROJECT_INPUT.match(rest):  # adhoc-e121-identity: the exact version, resolved by _one_item
            out.append((slot, rest, None)); continue
        found = ITEM.match(rest)
        if not found or not found.group(1).strip(): raise NotRun('item-format', f'/inputs/{slot}', {'given': str(text)})
        out.append((slot, found.group(1), int(found.group(2)) if found.group(2) else None))
    return out


def candidates(held, items):
    """Each item as "<name> version <n> (@<asset>:<revision>)" at its head, the number from its history (left out when
    history cannot be read), joined with "; ": what an ambiguous name lists so one can be copied (E121 B10)."""
    words = []
    for item in items:
        number = next((v.get('number') for v in held._history(item) or [] if v.get('revision') == item.get('revision')), None)
        words.append('%s%s (@%s:%s)' % (item.get('name'), '' if number is None else ' version %d' % number, item['asset_id'], item.get('revision')))
    return '; '.join(words)


def _one_item(inventory, held, slot, item_name, number):
    """(item, revision) for one `--item` (adhoc-e121-identity, E121 B10): `@ASSET:REVISION` exactly, when it is a
    version of an item the person can see (its head or in its history), otherwise the plain "no item" refusal, which
    never says whether the pair exists; or NAME[@N] by its name, where two items of one name list both."""
    exact = PROJECT_INPUT.match(item_name)
    if exact:
        asset, revision = exact.groups()
        item = next((i for i in inventory if i.get('asset_id') == asset), None)
        if item is None or revision not in (item.get('revision'), *(v.get('revision') for v in held._history(item) or [])):
            raise NotRun('item-missing', f'/inputs/{slot}', name=item_name)
        return item, revision
    matches = [i for i in inventory if i.get('name') == item_name] or [i for i in inventory if Path(i.get('name') or '').stem == item_name]
    if not matches: raise NotRun('item-missing', f'/inputs/{slot}', name=item_name)
    if len(matches) > 1:
        raise NotRun('item-ambiguous', f'/inputs/{slot}', {'asset_ids': [i['asset_id'] for i in matches]}, name=item_name, candidates=candidates(held, matches))
    item, revision = matches[0], matches[0].get('revision')
    if number is not None:
        revision = next((v.get('revision') for v in held._history(item) or [] if v.get('number') == number), None)
        if revision is None: raise NotRun('item-version', f'/inputs/{slot}', {'asset_id': item['asset_id']}, name=item_name, number=number)
    return item, revision


@contextlib.contextmanager
def _attempt_lock(work, wait, clock=time.monotonic):
    """D8: the folder's attempt lock (`flock`), inherited by the writer, so a second delivery or recovery from this
    folder waits up to `wait` seconds and is then refused; never a timing promise (6-10)."""
    import fcntl
    work.mkdir(parents=True, exist_ok=True)
    fd = os.open(work / 'delivery.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = clock() + max(0.0, float(wait or 0))
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if clock() >= deadline: raise NotRun('delivery-busy') from None
                time.sleep(0.05)
        yield fd
    finally: os.close(fd)


def _pending(work, name):
    """The attempt of procedure `name` this folder still holds (not reported with a final state), or (None, None)."""
    for path in sorted((work / 'deliveries').glob('*/attempt.json')):
        try: attempt = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): attempt = {'procedure': {'name': name}, 'unreadable': True}
        if (attempt.get('procedure') or {}).get('name') == name and not attempt.get('finished'): return path.parent, attempt
    return None, None


def delivery_records(work, name):
    """What the folder WORK holds of procedure `name`'s deliveries, read only (E112 s2, 6-F1): {finished, pending,
    set_aside} attempts in delivery-id order, and `intents`, the outcome-gate intents not yet removed (paths). A
    finished attempt was reported with a final state; a set-aside one was renamed `set-aside.json`. An unreadable
    attempt counts as pending, as `_pending` treats it."""
    work, found = Path(work), {'finished': [], 'pending': [], 'set_aside': [], 'intents': sorted((Path(work) / 'deliveries' / 'intents').glob('*.json'))}
    for path in sorted((work / 'deliveries').glob('*/*.json')):
        if path.name not in ('attempt.json', 'set-aside.json'): continue
        try: attempt = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): attempt = {'procedure': {'name': name}, 'unreadable': True}
        if (attempt.get('procedure') or {}).get('name') != name: continue
        found['set_aside' if path.name == 'set-aside.json' else 'finished' if attempt.get('finished') else 'pending'].append(attempt)
    return found


def _group_alive(group):
    """Whether a process of the writer's recorded process group still runs (hygiene, never proof: D8, 4-1)."""
    if not isinstance(group, int) or group <= 1: return False
    try: os.killpg(group, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True


def _until_finished(group, wait, clock=time.monotonic):
    """Wait up to `wait` seconds for the writer's process group to finish; a group still running is refused (D8)."""
    deadline = clock() + max(0.0, float(wait or 0))
    while _group_alive(group):
        if clock() >= deadline: raise NotRun('delivery-running')
        time.sleep(0.05)


def _run_child(folder, request, lock, launched=None):
    """Run CHILD on `request` in its own process group, holding the folder's attempt lock; the request file holds the
    configuration and is removed when the child ends. Returns (the process, what it said or None)."""
    exchange = Path(request['exchange'])
    exchange.mkdir()
    path = folder / 'request.json'
    path.write_text(json.dumps(request))
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        with open(folder / 'log.txt', 'ab') as log:
            process = subprocess.Popen([sys.executable, '-B', '-c', CHILD, str(path)], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, pass_fds=(lock,))
            if launched is not None: launched(process)
            process.wait()
    finally: path.unlink(missing_ok=True)
    try: said = json.loads((exchange / 'delivery.json').read_text())
    except (OSError, ValueError): said = None
    shutil.rmtree(exchange, ignore_errors=True)
    return process, said


def delivery_words(attempt, again=False):
    """What became of a delivery, in words (the story's sentences, D11, from this computer's side). `again`: said on a
    later run, which never sends again (D8)."""
    result, said = attempt.get('result') or {}, f"{attempt['destination']} by {attempt['procedure']['label']}"
    state = result.get('state')
    if state == 'confirmed':
        n = result.get('items', 0)
        sentence = f"Sent to {said} on this computer: {n} {'item' if n == 1 else 'items'}."
    elif state == 'not-sent': sentence = f'Not sent to {said} on this computer.'
    elif again: sentence = f'Outcome unknown for {said} on this computer. It was not sent again.'
    elif result.get('raised'):  # adhoc-e121-claims (O6): what the procedure's error said first, and what to check
        raised = result['raised']
        sentence = f"Outcome unknown for {said} on this computer. The procedure stopped with an error: {raised['line']}. " + (
            RAISED_NEXT.format(slot=raised['slot']) if raised.get('slot') else 'Run the same command to record what happened.')
    else: sentence = f'Outcome unknown for {said} on this computer. {UNSAID}'
    if attempt.get('reported'): return sentence + ' Recorded in the project.'
    return sentence + ' Not recorded in the project yet: ' + (attempt.get('report_error') or 'the report was not sent.')


class ProcedureClient:
    """Mixed into `Client` (uses its `_post`): the project's catalogue of procedures. Registering keeps a private
    version; an administrator enables it for the project; running a version someone else registered asks once whether
    you trust it (`trust`), then runs it on this computer exactly as `procedures.run` runs a folder."""

    def procedure_register(self, folder, *, command_id=None):
        """Register a procedure folder as a private version of this project (the server computes its digest). A
        `requires` text this SDK cannot check is registered as given, with a ProcedureWarning (E112 s4)."""
        from . import _requires
        request = register_request(folder, command_id)
        manifest = manifest_of(folder)
        for text in manifest.get('requires', []):
            try: _requires.parse(text)
            except _requires.Malformed:
                warnings.warn(f'{manifest["label"]} lists "{text}" under requires, which this SDK cannot check; running it will be refused until it '
                              'is a package name with optional versions.', ProcedureWarning, stacklevel=2)
        return self._post('procedures', 'register', request, retry=True)

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

    def procedure_version(self, name, version=None, *, readable=False):
        """Without `version`: the highest enabled version of `name`. With it: that version, among those you can see
        (your own private ones included). E108 S1 (B6 rev 5, R4-8): with `readable`, a refusal names a version's readable
        label or "this procedure", never the catalogue name (which stays in its details)."""
        found = [v for v in self.procedure_list(name) if v['name'] == name]
        chosen = [v for v in found if (v['state'] == 'enabled' if version is None else v['version'] == version)]
        if not chosen:
            said = name if not readable else next((contract().labels.readable_label(v.get('label')) for v in found
                                                   if contract().labels.readable_label(v.get('label'))), None) or THIS_PROCEDURE
            if version is None: raise NotRun('no-enabled-version', '', {'name': name}, name=said)
            raise NotRun('no-such-version', '', {'name': name, 'version': version}, name=said, version=version)
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
                      systems=None, settings=None, items=(), reference=None):
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
        scratch = Path(tempfile.mkdtemp(prefix='ophiolite-items-')) if items or reference is not None else None
        try:
            if scratch is not None: self._check_inputs(manifest_of(folder), inputs, items, reference, scratch)
            return run(folder, destination, inputs, kinds=kinds, declared=declared, systems=systems, settings=settings, expected_digest=digest)
        finally:
            _discard(inputs)
            if scratch is not None: shutil.rmtree(scratch, ignore_errors=True)

    def _check_inputs(self, manifest, inputs, items, reference, scratch):
        """E110 (D9, 2-M4): `--item SLOT=ITEM[@N]` and `--reference FILE|ITEM@N` as exact project versions, read with
        `read_exact` (the held folder is neither read nor changed), or the reference as a file on this computer."""
        wanted = list(_items(manifest, items))
        slot = next((i for i in manifest['inputs'] if i['class'] == 'reference'), None)
        if reference is not None:
            if slot is None: raise NotRun('unknown-input', '/inputs', {'given': 'reference'})
            text = str(reference)
            found = ITEM.match(text)
            if slot.get('from') == 'file':
                if not Path(text).is_file(): raise NotRun('check-reference', f"/inputs/{slot['slot']}", {'given': text}, label=slot['label'])
                inputs.setdefault(slot['slot'], []).append(text)
            elif found is None or found.group(2) is None:
                raise NotRun('check-reference', f"/inputs/{slot['slot']}", {'given': text}, label=slot['label'])
            else: wanted.append((slot['slot'], found.group(1), int(found.group(2))))
        try: read = self._read_items(wanted, scratch)
        except NotRun as error:  # the item sentences are deliver's; a run says "Not run"
            if str(error).startswith('Not sent:'): error.args = ('Not run:' + str(error)[len('Not sent:'):],)
            raise
        for (s, item, revision), got in read:
            inputs.setdefault(s, []).append(got)

    def _read_items(self, wanted, scratch):
        """[((slot, item, revision), ProjectInput)] for `--item` triples (slot, name, number or None): each named item
        of the inventory, at that version number or its head, read exactly into `scratch`."""
        from .exchange import ClientTransport, Exchange, ExchangeRefused
        from .errors import OphioliteError
        held = Exchange(ClientTransport(self), scratch / 'held')
        try: inventory = list(ClientTransport(self).inventory())
        except OphioliteError as error: raise NotRun('item-unreadable', '/inputs', {'error': type(error).__name__}, name='the project') from None
        out = []
        for n, (slot, item_name, number) in enumerate(wanted):
            item, revision = _one_item(inventory, held, slot, item_name, number)
            try: got = held.read_exact(item, revision, scratch / f'{slot}-{n}')
            except (ExchangeRefused, OphioliteError) as error:
                raise NotRun('item-unreadable', f'/inputs/{slot}', {'asset_id': item['asset_id'], 'revision': revision, 'error': type(error).__name__},
                             name=item_name) from None
            out.append(((slot, item, revision), self._exact_input(scratch / f'{slot}-{n}', item, revision, got)))
        return out

    # ------------------------------------------------------------ E108: a source procedure's first run into the project

    def source_run(self, name, systems, *, settings=None, system_label=None, version=None, prompt=None, yes=False, cache=None,
                   folder=None, attribution=None, audience=None, well_notes='', work=None):
        """Run a source procedure of the project's catalogue on this computer and add what it made to the project
        through one upload, each file naming the version, the team's system (in words) and its output role; the server
        records `sourced_by` from its catalogue. `systems` maps the system slot to its local configuration file, which
        is never sent. `system_label` names the system as people read it (default: the slot's label). `folder` keeps the
        run's files (a new folder); without it they are removed after the upload. Returns {sentence, run, report}.

        E108 S2: `work` is the folder that holds what earlier runs added (E70's held record, `held.json`): each output's
        item and version by (procedure name, system, role). A later run whose outputs and declarations equal the held
        ones sends nothing ("nothing-changed"); otherwise each held output is sent as a new version of its item at the
        version held, and a newer version added meanwhile is E70's `newer-version-exists`, named from the item's
        history. The send is saved in `work` before it starts (the outputs copied there), so a run that stops part way
        is completed by the next one without running the procedure again."""
        import uuid
        from .upload_runs import File, Folder, UploadRun
        if work is not None:
            from .exchange import ClientTransport, Exchange
            held = Exchange(ClientTransport(self), work)
            with held._locked():
                record = held._load()
                pending = record.get('pending_source')
            if pending is not None and pending.get('procedure') == name:  # a send that stopped part way: no new run
                return self._source_send(held, record, pending, None, None)
        chosen = self.procedure_version(name, version, readable=True)
        found = self.procedure_get(chosen['digest'])
        if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=_day(found['withdrawn_at']))
        digest = found['digest']
        local = self._cached(digest, cache)
        manifest = manifest_of(local)
        if manifest['step'] != 'source': raise NotRun('not-a-source', '/step', {'step': manifest['step']}, name=manifest['label'])
        slot = next(i for i in manifest['inputs'] if i['class'] == 'system')
        system = slot['label'] if system_label is None else system_label
        if not isinstance(system, str) or not system.strip() or len(system) > 100 or _secretive(system): raise NotRun('system-words', '/system')
        if not (found['trusted'] or found['mine']):
            if not yes:
                if prompt is None: raise NotRun('trust-needed', '', {'digest': digest})
                if not prompt(question(found)): raise NotRun('declined', '', {'digest': digest})
            self.procedure_trust(digest)
        _before_run(local)
        readable = contract().labels.readable_label(system.strip())
        label = (readable or NEUTRAL_FOLDER)[:160]  # B6 rev 4 (6): the folder and its paths read as words; the exact label is in `source`
        scratch = None if folder is not None else Path(tempfile.mkdtemp(prefix='ophiolite-source-'))
        destination = Path(folder) if folder is not None else scratch / 'run'
        kept, made = None, None
        try:
            ran = run(local, destination, systems=systems, settings=settings, expected_digest=digest)
            record = ran['run']
            made = [(role, Path(ran['destination']) / o['file'], o) for role, o in record['outputs'].items()]
        except BaseException:
            if scratch is not None: shutil.rmtree(scratch, ignore_errors=True)
            raise
        try:
            files = [File(f'{label}/{o["file"]}', path.stat().st_size, o['sha256'], lambda path=path: path.read_bytes(), str(path)) for role, path, o in made]
            listing = [{'path': f.path, 'bytes': f.size, 'sha256': f.sha256, 'source': {'digest': digest, 'system': system, 'role': role},
                        **({'decisions': o['declared']} if o['declared'] else {})} for f, (role, _, o) in zip(files, made)]  # what the output declares
            uploads = self.upload_runs
            body = {'command_id': uuid.uuid4().hex, 'folder_name': label, 'files': listing, 'well_notes': well_notes, 'rights_confirmed': True}
            sent = Folder(label, files)
            body.update(uploads.defaults(sent, attribution, audience, None, False))
            if work is not None:  # E108 S2: what the folder holds decides; the send is saved before it starts
                said = f"Ran {manifest['label']}, version {manifest['version']}, on this computer, reading from {readable or NEUTRAL_SYSTEM}."
                with held._locked():
                    record = held._load()
                    bindings = {f.path: _binding(manifest['name'], system, role) for f, (role, _, _) in zip(files, made)}
                    declared = {f.path: _declared_sha(o['declared']) for f, (_, _, o) in zip(files, made)}
                    mine = [(record.get('sources') or {}).get(bindings[f.path]) for f in files]
                    if all(h is not None and (h['sha256'], h['declared_sha256']) == (f.sha256, declared[f.path]) for h, f in zip(mine, files)):
                        number = {h.get('number') for h in mine}
                        words = held._say('nothing-changed', {'number': number.pop() if len(number) == 1 else None})
                        return {'sentence': said, 'outcome': 'nothing-changed', 'outcome_sentence': words, 'run': record_of(ran), 'report': None, 'kept': None}
                    for entry, h in zip(listing, mine):
                        if h is not None: entry.update(append_to=h['asset_id'], expected_parent=h['revision'])
                    area = held.work / 'pending' / body['command_id']
                    area.mkdir(parents=True, exist_ok=True)
                    for f, (_, path, o) in zip(files, made): shutil.copyfile(path, area / Path(o['file']).name)
                    labels = {o['role']: o['label'] for o in manifest['outputs']}
                    pending = {'procedure': name, 'body': body, 'label': label, 'sentence': said, 'bindings': bindings, 'declared': declared,
                               'names': {f.path: labels.get(role, f.path) for f, (role, _, _) in zip(files, made)},
                               'files': [{'path': f.path, 'file': Path(o['file']).name, 'bytes': f.size, 'sha256': f.sha256} for f, (_, _, o) in zip(files, made)]}
                    record['pending_source'] = pending
                    held._save(record)
                answer = self._source_send(held, record, pending, ran, made)
                return {**answer, 'run': record_of(ran)}
            report = uploads.send(uploads._call('start', body, UploadRun)['run_id'], sent)
            said = {o['role']: o['label'] for o in manifest['outputs']}
            report.names = {f.path: said.get(role, f.path) for f, (role, _, _) in zip(files, made)}
            if not report.ok: kept = _recovery(made)
        except Exception as error:  # B6 rev 5 (R4-3): the procedure ran; its outputs are kept, never its log or run record
            error.kept = _recovery(made)
            if hasattr(error, 'add_note'): error.add_note(KEPT.format(path=error.kept))  # Python 3.11 and later
            raise
        finally:
            if scratch is not None: shutil.rmtree(scratch, ignore_errors=True)
        sentence = f"Ran {manifest['label']}, version {manifest['version']}, on this computer, reading from {readable or NEUTRAL_SYSTEM}."
        return {'sentence': sentence, 'run': record, 'report': report, 'kept': kept}

    def _source_send(self, held, record, pending, ran, made):
        """E108 S2: send a saved source run (its start again under its command id, then each file still waiting) and
        record what each output became. Newer versions added meanwhile end as E70's `newer-version-exists`."""
        from .upload_runs import File, Folder, UploadRun
        area = held.work / 'pending' / pending['body']['command_id']
        files = [File(f['path'], f['bytes'], f['sha256'], lambda p=area / f['file']: p.read_bytes(), str(area / f['file'])) for f in pending['files']]
        uploads = self.upload_runs
        try:
            report = uploads.send(uploads._call('start', pending['body'], UploadRun)['run_id'], Folder(pending['label'], files))
        except Exception as error:
            if made is None:  # a resumed send: its outputs are the saved ones (a first run's are kept by its caller)
                error.kept = str(area)
                if hasattr(error, 'add_note'): error.add_note(KEPT.format(path=error.kept))
            raise
        newer = None
        with held._locked():
            record = held._load()
            sources = record.setdefault('sources', {})
            for item in report.items:
                path = item['path']
                if item['state'] in ('added', 'already-here') and item.get('asset_id') and path in pending['bindings']:
                    sources[pending['bindings'][path]] = {'asset_id': item['asset_id'], 'revision': item['revision'], 'sha256': item['sha256'],
                                                          'declared_sha256': pending['declared'][path]}
                elif item.get('reason_code') == 'newer-version' and newer is None:
                    newer = next((e for e in pending['body']['files'] if e['path'] == path), None)
            finished = report.state == 'closed' or all(i['state'] not in ('waiting', 'reading') for i in report.items)
            if finished:
                record['pending_source'] = None
                if report.ok: shutil.rmtree(area, ignore_errors=True)
            held._save(record)
        if newer is not None:  # E70: another run added a version first; the person gets it or sends theirs as a new item
            item = {'kind': 'uploaded', 'asset_id': newer['append_to']}
            versions = held._history(item) or []
            head = versions[-1] if versions else {}
            held._raise('newer-version-exists', {'name': newer['path'].rsplit('/', 1)[-1], **{k: v for k, v in held._who(head).items() if v is not None}})
        report.names = dict(pending.get('names') or {})
        return {'sentence': pending['sentence'], 'outcome': 'sent', 'report': report, 'kept': None if report.ok else str(area)}

    # ------------------------------------------------------------ E109: a send procedure delivers exact versions

    def _delivery_reporter(self):
        """Who reports (the same as a pending send's owner, E70a): the access key's fingerprint or the grant's person."""
        from .exchange import ClientTransport
        return ClientTransport(self).identity()

    def deliver(self, name, *, systems=None, items=(), settings=None, work='.ophiolite-held', wait=0, prompt=None, yes=False, cache=None,
                version=None, set_aside=False, as_=None):
        """Deliver exact versions to a team's system with a send procedure of the project's catalogue, on this computer.

        Every refusal before launch (Windows, a delivery already running from `work`, the catalogue's selection, trust and
        withdrawal checks, the settings, an item that cannot be bound or read) leaves no pending record and reports
        nothing (D12 i). Then the attempt is saved in `work/deliveries/<delivery id>/` (a new uuid4 delivery id, the
        pinned procedure copy, the versions, the settings, the configuration's fingerprint, who reports) and the writer
        runs once, in its own process group, holding the folder's attempt lock. Its answer is reported to the project
        (`activity/deliver`, procedure-delivery/1) with the destination's label, never its configuration.

        A later call for the same procedure that finds the attempt still pending never runs the writer again (D8): a
        saved outcome is reported again under its saved report id. Otherwise, once the writer's process group has
        finished (waiting up to `wait` seconds), the procedure's `reconcile`, when it declares one, runs from the pinned
        copy with the same configuration and says confirmed, not sent (only through the destination's tombstone) or
        unknown; without one the outcome stays unknown. `set_aside=True` records the outcome as unknown and lets this
        folder start a new delivery. Returns {sentence, delivery_id, state, items, destination, reported}.

        `as_` names an outcome (E120 D7): after every check above and before the pending record, the project's gate
        judges the one delivered version against it and this procedure's destination. A refusal launches nothing and
        raises its sentence; a claim's delivery id (the gate issues it) is the attempt's. The gate's command is kept in
        `work/deliveries/intents/` until the attempt is saved, so a delivery interrupted in between asks again with the
        same command and gets the same claim, launching only while the claim is still valid."""
        if _windows(): raise NotRun('windows')  # R5-1: refused before anything is read, locked or launched
        from .exchange import ClientTransport, Exchange, ExchangeRefused
        from .errors import OphioliteError
        work = Path(work).expanduser().absolute()
        systems = dict(systems or {})
        with _attempt_lock(work, wait) as lock:
            reporter = self._delivery_reporter()
            folder, attempt = _pending(work, name)
            if set_aside: return self._set_aside(name, folder, attempt, reporter)
            if folder is not None: return self._delivery_again(folder, attempt, reporter, systems, settings, lock, wait)
            chosen = self.procedure_version(name, version, readable=True)
            found = self.procedure_get(chosen['digest'])
            if found['state'] == 'withdrawn': raise NotRun('withdrawn', '', {'digest': found['digest']}, date=_day(found['withdrawn_at']))
            digest = found['digest']
            local = self._cached(digest, cache)
            manifest = manifest_of(local)
            if manifest['step'] != 'send': raise NotRun('not-a-send', '/step', {'step': manifest['step']}, name=manifest['label'])
            _requirements(manifest)  # E112 s4: before the trust question, the pending record and the writer (B11 a)
            if not (found['trusted'] or found['mine']):
                if not yes:
                    if prompt is None: raise NotRun('trust-needed', '', {'digest': digest})
                    if not prompt(question(found)): raise NotRun('declined', '', {'digest': digest})
                self.procedure_trust(digest)
            _before_run(local)
            values = _resolved_settings(manifest, settings)
            system = next((i for i in manifest['inputs'] if i['class'] == 'system'), None)
            destination = system['label'] if system else manifest['outputs'][0]['label']  # R4: no system, the delivery's label
            if _secretive(destination): raise NotRun('system-words', '/system')
            wanted = _items(manifest, items)
            held = Exchange(ClientTransport(self), work)
            scratch = Path(tempfile.mkdtemp(prefix='ophiolite-deliver-'))
            try:
                inputs, refs = {}, []
                try: inventory = list(ClientTransport(self).inventory())
                except OphioliteError as error: raise NotRun('item-unreadable', '/inputs', {'error': type(error).__name__}, name='the project') from None
                for n, (slot, item_name, number) in enumerate(wanted):
                    item, revision = _one_item(inventory, held, slot, item_name, number)
                    try: got = held.read_exact(item, revision, scratch / f'{slot}-{n}')
                    except (ExchangeRefused, OphioliteError) as error:
                        raise NotRun('item-unreadable', f'/inputs/{slot}', {'asset_id': item['asset_id'], 'revision': revision, 'error': type(error).__name__},
                                     name=item_name) from None
                    inputs.setdefault(slot, []).append(self._exact_input(scratch / f'{slot}-{n}', item, revision, got))
                    refs.append({'project_id': self.project, 'asset_id': item['asset_id'], 'revision': revision})
                bound, input_record, _ = _bind(manifest, inputs, {}, {}, systems)
                claim, intent = None, None
                if as_ is None: delivery_id = str(uuid.uuid4())  # D2: generated once, saved before the writer runs; a new run is a new delivery
                else:
                    if len(refs) != 1: raise NotRun('as-one-version', '/inputs', {'given': len(refs)}, label=as_)
                    claim, intent = self._deliver_as_gate(work, as_, name, digest, destination, refs[0], reporter)
                    delivery_id = claim['delivery_id']  # E120 (1-5): the id the gate issued and bound to its claim
                folder = work / 'deliveries' / delivery_id
                attempt = {'schema': ATTEMPT, 'delivery_id': delivery_id, 'project': self.project, 'url': self.url, 'reporter': reporter,
                           'procedure': {'name': name, 'digest': digest, 'label': manifest['label'], 'version': manifest['version']},
                           'destination': destination, 'refs': refs, 'slots': [[slot, r['asset_id'], r['revision']] for (slot, _, _), r in zip(wanted, refs)],
                           'inputs': input_record, 'settings': values, 'config_sha256': _fingerprint(systems), 'process_group': None, 'result': None,
                           'reported': False, 'finished': False}
                if claim is not None:
                    attempt['outcome'] = {'claim_id': claim['claim_id'], 'outcome_id': claim['outcome']['id'], 'label': claim['outcome']['label'],
                                          'version': claim['outcome']['version']}
                return self._deliver_once(local, folder, attempt, manifest, bound, values, system, lock,
                                          saved=(lambda: intent.unlink(missing_ok=True)) if intent is not None else None)
            finally: shutil.rmtree(scratch, ignore_errors=True)

    def _exact_input(self, folder, item, revision, got):
        """A version read by `read_exact` as a run's input: its original, its stored type and the declarations its reader takes."""
        described = json.loads((folder / 'descriptor.json').read_text(encoding='utf-8'))
        profile, context = described.get('profile'), described.get('scientific') or {}
        keys = [d['key'] for r in contract_readers() if r['profile'] == profile for d in r['declared']]
        target = folder / ('original' + _extension(profile))
        os.replace(folder / 'original', target)
        return ProjectInput(str(target), profile, {k: context[k] for k in keys if isinstance(context.get(k), str)}, item['asset_id'], revision)

    def _deliver_as_gate(self, work, label, name, digest, destination, ref, reporter):
        """E120 D7 (2-5, 5-20): the gate's claim for one version, delivered by `digest` to `destination`, as the outcome
        named `label`. The command and the complete request are saved before the gate is asked
        (`deliveries/intents/<command id>.json`, under the folder's attempt lock), so asking again after an interruption
        with the same project, person, procedure, result, outcome and destination replays the same command; anything
        else is a new command, judged afresh (5-23). A refusal, or a replayed claim that is no longer valid, removes the
        intent and raises the gate's sentence. Returns (the claim, the intent's path)."""
        outcome = self.outcome_named(label)
        body = {'outcome_id': outcome['outcome_id'], 'asset_id': ref['asset_id'], 'revision': ref['revision'],
                'send': {'procedure_digest': digest, 'label': destination}}
        request = {'url': self.url, 'project': self.project, 'reporter': reporter, 'procedure': name, 'gate': body}
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        intents = work / 'deliveries' / 'intents'
        intents.mkdir(parents=True, exist_ok=True)
        intent = None
        for path in sorted(intents.glob('*.json')):
            try: kept = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError): continue
            if kept.get('request_sha256') == fingerprint: intent, command = path, kept['command_id']
        if intent is None:
            command = 'deliver-as-' + uuid.uuid4().hex
            intent = intents / (command + '.json')
            _save(intent, {'schema': INTENT, 'command_id': command, 'request_sha256': fingerprint, 'request': request, 'outcome': outcome['label']})
        claim = self._post('outcomes', 'deliver-as', {**body, 'command_id': command}, retry=True)
        current = claim.get('current') or {'valid': claim['state'] == 'claimed', 'reason': claim['reason'], 'sentence': claim['sentence']}
        if claim['state'] != 'claimed' or not current['valid']:
            intent.unlink(missing_ok=True)
            told = current if claim['state'] == 'claimed' else claim
            raise NotRun('as-refused', '', {'reason': told['reason'], 'claim_id': claim['claim_id']}, sentence=told['sentence'])
        return claim, intent

    def _deliver_once(self, local, folder, attempt, manifest, bound, values, system, lock, saved=None):
        """Save the attempt, then run the writer once from the pinned copy and report what it said."""
        snapshot = folder / 'procedure'
        folder.mkdir(parents=True)
        for path, raw in contract().read_members(local).items():
            member = snapshot.joinpath(*path.split('/'))
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(raw)
        if contract().digest(snapshot) != attempt['procedure']['digest']:
            shutil.rmtree(folder, ignore_errors=True)
            raise NotRun('changed-before-run', '', {'expected': attempt['procedure']['digest']})
        _save(folder / 'attempt.json', attempt)  # D2, R5-1: saved before the writer runs
        if saved is not None: saved()  # E120: the gate's intent is used once the attempt holds its claim's id
        def launched(process):
            attempt['process_group'] = process.pid  # R5-1: the writer's own group (its session leader)
            _save(folder / 'attempt.json', attempt)
            _launched(process, folder)
        # the request holds the configuration and is removed when the writer ends; the attempt keeps only its fingerprint
        process, said = _run_child(folder, {'snapshot': str(snapshot), 'exchange': str(folder / 'exchange'), 'entry': manifest['entry'], 'settings': values,
                                            'inputs': {slot: _encode(value) for slot, value in bound.items()},
                                            'delivery': {'id': attempt['delivery_id'], 'system': system['slot'] if system else None}}, lock, launched)
        raised = _raised(said, system, bound[system['slot']].config if system and isinstance(bound.get(system['slot']), LocalSystem) else None)
        return self._outcome(folder, attempt, said or {'state': 'unknown', 'said': 'stopped', 'exit_status': process.returncode}, raised=raised)

    def _outcome(self, folder, attempt, said, again=False, raised=None):
        """Keep what the procedure said in the log (its words never leave this computer, D3), save the outcome with a
        fresh report id before reporting it (R2), and report it. `raised` (O6): its error's first line without
        configuration values and the slot to check, kept in the attempt for the sentence; never in the report."""
        with open(folder / 'log.txt', 'ab') as log:
            log.write(('\n--- what the procedure said ---\n' + json.dumps(said, indent=2) + '\n').encode())
        state = said['state']
        attempt['result'] = {'state': state, 'items': said.get('items', 0) if state == 'confirmed' else 0, 'event_id': 'delivery-report-' + uuid.uuid4().hex}
        if raised: attempt['result']['raised'] = raised
        _save(folder / 'attempt.json', attempt)
        return self._report_delivery(folder, attempt, again)

    def _report_delivery(self, folder, attempt, again=False):
        """Report the saved outcome under its saved report id; a final state accepted ends the attempt here."""
        from .errors import OphioliteError
        from .models.delivery import DeliveryObservation
        result = attempt['result']
        body = DeliveryObservation(project_id=attempt['project'], event_id=result['event_id'], refs=attempt['refs'], procedure={
            k: attempt['procedure'][k] for k in ('digest', 'label', 'version')}, destination=attempt['destination'], delivery={
            'delivery_id': attempt['delivery_id'], 'state': result['state'], 'items': result['items']}).model_dump()
        try:
            answer = self._post('activity', 'deliver', body)
            if not (isinstance(answer, dict) and answer.get('accepted') is True and answer.get('delivery_id') == attempt['delivery_id']):
                raise ValueError('the project did not accept the report')
            attempt.update(reported=True, report_error=None, finished=result['state'] != 'unknown')
        except (OphioliteError, ValueError) as error:
            # the project's own sentence when it gave one (E51a server_message), e.g. why it refused the report
            attempt.update(reported=False, report_error=getattr(error, 'server_message', None) or str(error) or type(error).__name__)
        _save(folder / 'attempt.json', attempt)
        return {'sentence': delivery_words(attempt, again), 'delivery_id': attempt['delivery_id'], 'state': result['state'], 'items': result['items'],
                'destination': attempt['destination'], 'reported': attempt['reported'], 'folder': str(folder)}

    def _delivery_again(self, folder, attempt, reporter, systems, settings, lock, wait):
        """A pending attempt (R5-1, D8): checked against what is given now and never launched again. A saved final outcome
        is reported again; otherwise, once the writer's group has finished, `reconcile` (when declared) tells it."""
        if attempt.get('unreadable'): raise NotRun('delivery-pending', '', {'folder': str(folder)})
        if attempt.get('reporter') != reporter: raise NotRun('delivery-other-person', '', {'folder': str(folder)})
        snapshot = folder / 'procedure'
        try: same = contract().digest(snapshot) == attempt['procedure']['digest']
        except Exception: same = False
        if not same: raise NotRun('delivery-changed', '', {'folder': str(folder), 'changed': 'procedure'})
        manifest = manifest_of(snapshot)
        try: values = _setting_values(manifest, settings)
        except NotRun: values = None
        if values != attempt.get('settings'): raise NotRun('delivery-changed', '', {'folder': str(folder), 'changed': 'settings'})
        if _fingerprint(systems) != attempt.get('config_sha256'): raise NotRun('delivery-changed', '', {'folder': str(folder), 'changed': 'configuration'})
        result = attempt.get('result')
        if result and result['state'] != 'unknown': return self._report_delivery(folder, attempt, again=True)  # replayed, R2
        _until_finished(attempt.get('process_group'), wait)
        if manifest.get('reconcile'):
            said = self._reconcile(folder, attempt, manifest, systems, lock)
            if said['state'] != 'unknown': return self._outcome(folder, attempt, said, again=True)
        if not result:  # the writer stopped before its answer was saved: unknown, recorded once (D8)
            attempt['result'] = {'state': 'unknown', 'items': 0, 'event_id': 'delivery-report-' + uuid.uuid4().hex}
            _save(folder / 'attempt.json', attempt)
        return self._report_delivery(folder, attempt, again=True)  # a repeated unknown is the server's no-op (R2)

    def _reconcile(self, folder, attempt, manifest, systems, lock):
        """Run the manifest's `reconcile(delivery)` from the pinned copy with the configuration given now (its
        fingerprint was checked), holding the folder's attempt lock (D8); what it said, or unknown."""
        system = next((i for i in manifest['inputs'] if i['class'] == 'system'), None)
        config = None
        if system is not None:
            try: config = json.loads(Path(systems[system['slot']]).read_text(encoding='utf-8'))
            except (KeyError, OSError, ValueError): config = None
            if not isinstance(config, dict): return {'state': 'unknown', 'said': 'no-configuration'}
        process, said = _run_child(folder, {'snapshot': str(folder / 'procedure'), 'exchange': str(folder / 'reconcile'), 'entry': manifest['reconcile'],
                                            'reconcile': True, 'settings': attempt.get('settings') or {}, 'inputs': {},
                                            'delivery': {'id': attempt['delivery_id'], 'system': _encode(LocalSystem(config)) if system else None}}, lock)
        return said or {'state': 'unknown', 'said': 'stopped', 'exit_status': process.returncode}

    def _set_aside(self, name, folder, attempt, reporter):
        """D8: the pending delivery's outcome stays unknown in the project and this folder no longer waits for it (its
        attempt is kept as set-aside.json, beside the log)."""
        if folder is None: raise NotRun('nothing-to-set-aside', '', name=name)
        if not attempt.get('unreadable'):
            if attempt.get('reporter') != reporter: raise NotRun('delivery-other-person', '', {'folder': str(folder)})
            result = attempt.get('result')
            if result and result['state'] != 'unknown': raise NotRun('set-aside-known', '', {'folder': str(folder)})
            if not result:
                attempt['result'] = {'state': 'unknown', 'items': 0, 'event_id': 'delivery-report-' + uuid.uuid4().hex}
                _save(folder / 'attempt.json', attempt)
            if not attempt.get('reported'):
                self._report_delivery(folder, attempt, again=True)
                if not attempt.get('reported'): raise NotRun('set-aside-unreported', '', {'folder': str(folder)}, error=attempt.get('report_error'))
            attempt['set_aside'] = True
            _save(folder / 'attempt.json', attempt)
        os.replace(folder / 'attempt.json', folder / 'set-aside.json')
        destination = attempt.get('destination') or 'the destination'
        return {'sentence': f'Set aside: the outcome of this delivery to {destination} stays unknown in the project; this folder no longer waits for it.',
                'delivery_id': attempt.get('delivery_id'), 'state': 'unknown', 'items': 0, 'destination': attempt.get('destination'),
                'reported': bool(attempt.get('reported')), 'folder': str(folder)}

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

    def _download_version(self, asset, revision, stem, profile=None, declared=None, wellbore=None):
        """One exact version for a run: its original, its stored type and declarations (given by the server for a run
        made again; otherwise read from its typed description). E120 s6 (D-19): a run made again also keeps the
        wellbore the server recorded for a residual run's tops version."""
        stem.parent.mkdir(parents=True, exist_ok=True)
        if profile is None:
            from urllib.parse import quote
            from . import _core
            from .client import PROFILES
            from .errors import Incompatible
            path = self.prefix + '/' + quote(asset, safe='') + '/revisions/' + quote(revision, safe='')
            try:
                described = self._json(path + '?' + PROFILES[1:], 256 * 1024)
            except Incompatible:  # a well log is described per curve: its first curve's description names its type
                return self._download_log(asset, revision, stem)
            _core.verify_typed_descriptor(described, self.project, asset, revision)
            profile, context = described['profile'], described.get('scientific') or {}
            keys = [d['key'] for r in contract_readers() if r['profile'] == profile for d in r['declared']]
            declared = {k: context[k] for k in keys if isinstance(context.get(k), str)}
        target = stem.with_suffix(_extension(profile))
        self.download_original(asset, revision, target)
        return ProjectInput(str(target), profile, dict(declared or {}), asset, revision, wellbore)

    def procedure_publish(self, folder, *, name=None, again_of=None, for_outcome=None):
        """Report a run of a catalogue version on project versions, then publish each of its outputs under the run. The
        report's command id is saved in the run folder (publish.json) before anything is sent, and every output is
        published under a command id derived from the run, so publishing again after a stop or a lost answer resumes:
        one run, each output once. `for_outcome` (an outcome's name, or {outcome_id, label}; E120) publishes the same
        result of a run made again for that outcome; it is saved with the command id, so a resume still sends it.
        Returns {sentence, run, outputs: [{role, outcome, sentence, receipt}]}."""
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
            if for_outcome is not None:
                found = self.outcome_named(for_outcome) if isinstance(for_outcome, str) else for_outcome
                state['for_outcome'] = {'outcome_id': found['outcome_id'], 'label': found['label']}
            _save(state_path, state)
        chosen = state.get('for_outcome')
        before_report(state)
        body = {'command_id': state['command_id'], 'procedure': {'digest': record['procedure']['digest']}, 'settings': record['settings'],
                'inputs': {slot: [{'asset_id': v['asset_id'], 'revision': v['revision']} for v in versions] for slot, versions in record['inputs'].items()},
                'outputs': outputs, 'again_of': state.get('again_of')}
        reported = self._reported(lambda: self._post('procedure-runs', 'report', body, retry=True))
        for slot, versions in record['inputs'].items():
            for i, (used, stored) in enumerate(zip(versions, reported['inputs'].get(slot, []))):
                if stored.get('restricted') or (stored.get('profile'), stored.get('declared') or {}) != (used['kind'], used['declared'] or {}):
                    # E121 B9: which input of the slot, and what differs; the declaration keys only in the details
                    mine, kept = used['declared'] or {}, stored.get('declared') or {}
                    details = {'index': i, 'asset_id': used['asset_id'], 'revision': used['revision']}
                    if stored.get('restricted'): what = 'you can no longer read it'
                    else:
                        what = ' and '.join(w for w, d in (('its type', stored.get('profile') != used['kind']), ('its declarations', kept != mine)) if d)
                        details.update(kind={'run': used['kind'], 'project': stored.get('profile')}, declared_keys=sorted(k for k in {*mine, *kept} if mine.get(k) != kept.get(k)))
                    raise NotRun('inputs-differ', f'/inputs/{slot}', details, label=slot,
                                 which=what if len(versions) == 1 else 'input %d of %d: %s' % (i + 1, len(versions), what))
        done = {o['role']: o for o in reported['outputs'] if o['outcome'] is not None}
        method = method_of(reported['procedure'], reported['settings'])
        parents = run_parents(self.procedure_get(record['procedure']['digest'])['manifest'], record)
        results = []
        for output in reported['outputs']:
            role = output['role']
            if role in done:
                receipt = done[role]['receipt']
            else:
                local = record['outputs'][role]
                raw = (folder / local['file']).read_bytes()
                receipt = self._run_output(raw, local['profile'], local['declared'], titled(state, reported, output), parents, method, reported['run_id'], role,
                                           **({'for_outcome': chosen['outcome_id']} if chosen else {}))  # an ordinary publish calls as before
            earlier = self._title_of(receipt) if (receipt.get('outcome') or {}).get('outcome', '').startswith('same') else None
            words = _outcome_words(receipt, titled(state, reported, output), output['kind'], reported, earlier, chosen and chosen['label'])
            results.append({'role': role, 'kind': output['kind'], 'receipt': receipt, **words})
        state['run_id'] = reported['run_id']; _save(state_path, state)
        return {'sentence': '\n'.join(r['sentence'] for r in results), 'run': self.procedure_run_get(reported['run_id']), 'outputs': results}

    def _download_log(self, asset, revision, stem):
        """A well-log version: its original, then the verified description of its first value curve, which must say
        las2/1 (the reader declares nothing for a log)."""
        from . import las_header
        target = stem.with_suffix(_extension('las2/1'))
        self.download_original(asset, revision, target)
        first = next((c.mnemonic for c in las_header.curves(target.read_bytes())[1:]), None)
        described = self.describe(asset, revision, first) if first else None
        if getattr(described, 'profile', None) != 'las2/1':
            target.unlink(missing_ok=True)
            raise NotRun('project-input-kind', '', {'asset_id': asset, 'revision': revision})
        return ProjectInput(str(target), 'las2/1', {}, asset, revision)

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
        from .errors import OphioliteError
        try: return call()
        except OphioliteError as error:  # a refusal of any status (a result you cannot read is 404) carries the closed code
            if getattr(error, 'code', None) == 'procedure-run-refused': raise NotRun('refused', '', {'reason': getattr(error, 'details', {}).get('reason')}, sentence=error.message) from None
            raise

    def _run_output(self, raw, profile, declared, name, parents, method, run_id, role, for_outcome=None):
        """publications/derive for one output of a run: the command id is the run's for this role (a retry is the same
        command); the receipt is the published result, or the earlier result for a run made again with the same result
        (published again for the outcome `for_outcome` names, E120)."""
        from .writers import WrittenOriginal
        procedure = {'id': run_id, 'role': role, **({'for_outcome': for_outcome} if for_outcome else {})}
        receipt = self._reported(lambda: self.publish_derived(WrittenOriginal(raw, profile, dict(declared or {})), name=name[:160], from_=parents, method=method,
                                                              command_id=output_command(run_id, role), procedure=procedure))
        return receipt.model_dump(mode='json', exclude_none=True)

    def procedure_run_get(self, run_id):
        return self._post('procedure-runs', 'get', {'run_id': run_id}, retry=True)

    def procedure_prepare_again(self, asset, revision):
        return self._reported(lambda: self._post('procedure-runs', 'prepare-again', {'asset_id': asset, 'revision': revision}, retry=True))

    def procedure_again(self, asset, revision, destination, *, version=None, folder=None, prompt=None, yes=False, cache=None, name=None, for_=None):
        """Run a procedure-made result again on this computer and publish it under the new run: the server says per
        output whether it is the same result (nothing published) or a new private result made again from the earlier
        one. `version` runs another catalogue version of the same procedure; `folder` runs a local copy whose digest is
        a catalogue version. `for_` (an outcome's name, E120) publishes the same result again for that outcome, so its
        current version evaluates it; the name is resolved before anything runs."""
        outcome = None if for_ is None else self.outcome_named(for_)
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
            inputs = {slot: [self._download_version(b['asset_id'], b['revision'], work / f'{slot}-{n}', b['profile'], b['declared'] or {},
                                                    b.get('wellbore'))
                             for n, b in enumerate(bindings)] for slot, bindings in prepared['inputs'].items()}
            settings = [f'{k}={_text(v)}' for k, v in prepared['settings'].items() if k in {s['key'] for s in manifest.get('settings', [])}]
            _before_run(local)
            ran = run(local, destination, inputs, settings=settings, expected_digest=found['digest'])
        finally: shutil.rmtree(work, ignore_errors=True)
        published = self.procedure_publish(destination, name=name, again_of={'asset_id': asset, 'revision': revision}, for_outcome=outcome)
        return {**published, 'ran': ran['sentence']}


def agent_register(agent, folder, summary='', *, command_id=None, evidence=None, **wait):
    """E111: an agent registers a procedure folder as a private version through a plan the person approves (the plan
    names exactly these archive bytes). `agent` is an `ophiolite.agents.AgentClient`."""
    return agent.run('procedures/register', register_request(folder, command_id), summary, evidence=evidence, **wait)


class AgentRun:
    """E111 s1: an agent reports a run made on this computer (a `run.json` folder) and publishes its outputs under the
    one approval the person gives the report. The report names how each output is published (`publish`: its name, and
    optionally the well it is about or the earlier result it is a new version of); the gateway writes each output's
    `publications/derive` in full from the stored run, and the agent sends exactly those, under the report's plan: one
    charge for the report, each output once, nothing more once the person stops the run. The report's command id is
    saved in the folder (agent-run.json) before anything is sent, so reporting again after a lost answer is the same
    plan and the same run, and an output already published answers its receipt.

    `again_of` ({asset_id, revision}; E112 s3, D-44) reports the run as a run again of that earlier result, as a person's
    `procedure_publish` does. It is saved with the command id on the first request, and every later request, from this
    object or a new one over the folder, must give the same one (a state saved without it counts as none). It is in
    the request only when set, so an ordinary report is the same request as before.

        agent = AgentClient('https://ophiolite.example', 'project-id', credential)
        done = AgentRun(agent, 'runs/shifted-tops', name='Shifted Chalk tops').report('Publish the shifted tops')
    """
    STATE = 'agent-run.json'

    def __init__(self, agent, folder, *, name, publish=None, again_of=None):
        from .errors import Refused
        if not isinstance(name, str) or not name.strip():
            raise Refused('Give the results a name (up to 160 characters); the person approves it with the run.')
        if again_of is not None and not (isinstance(again_of, dict) and set(again_of) == {'asset_id', 'revision'}
                                         and all(isinstance(v, str) and v for v in again_of.values())):
            raise Refused('Give again_of as {"asset_id": ..., "revision": ...}: the earlier result this run is a run again of.')
        self.agent, self.folder, self.name, self.publish = agent, Path(folder), name, dict(publish or {})
        self.again_of = dict(again_of) if again_of is not None else None

    def _record(self):
        try: record = json.loads((self.folder / 'run.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): raise NotRun('not-a-run') from None
        if record.get('schema') != LOCAL_RUN: raise NotRun('not-a-run')
        if record.get('systems') or any('asset_id' not in v for versions in record['inputs'].values() for v in versions): raise NotRun('local-inputs')
        return record

    def _raw(self, record, role, sha256):
        """An output's bytes, refused before anything is sent when the file is not the one reported (and approved)."""
        output = record['outputs'][role]
        path = self.folder / output['file']
        raw = path.read_bytes() if path.is_file() else None
        if raw is None or hashlib.sha256(raw).hexdigest() != sha256: raise NotRun('output-changed', f'/outputs/{role}', file=output['file'])
        return raw

    def request(self):
        """The procedure-runs/report request the person approves: the run, as reported, and how each output is published."""
        record = self._record()
        outputs = [{'role': role, 'sha256': o['sha256'], 'bytes': len(self._raw(record, role, o['sha256'])), 'declared': o['declared']}
                   for role, o in record['outputs'].items()]
        state_path = self.folder / self.STATE
        try: state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError): state = None
        if state is None:  # saved before the report is proposed: a lost answer is the same command, so the same plan
            state = {'schema': 'ophiolite.agent-run/1', 'command_id': 'run-' + uuid.uuid4().hex,
                     **({'again_of': self.again_of} if self.again_of is not None else {})}
            _save(state_path, state)
        elif state.get('again_of') != self.again_of:
            from .errors import Refused
            raise Refused('This run was first reported as a run again of another result; report it with the same one.')
        several = len(record['outputs']) > 1
        publish = {}
        for role in record['outputs']:
            entry = {'name': (f'{self.name}: {role}' if several else self.name)[:160], **(self.publish.get(role) or {})}
            publish[role] = {k: v for k, v in entry.items() if v is not None}
        return {'command_id': state['command_id'], 'procedure': {'digest': record['procedure']['digest']}, 'settings': record['settings'],
                'inputs': {slot: [{'asset_id': v['asset_id'], 'revision': v['revision']} for v in versions] for slot, versions in record['inputs'].items()},
                'outputs': outputs, 'publish': publish, **({'again_of': state['again_of']} if state.get('again_of') is not None else {})}

    def steps(self, request, reported):
        """role → (the publications/derive request, the output's bytes) for each output not yet published: the same
        request the gateway writes from the stored run, field for field."""
        from .publish import derive_request
        from .writers import WrittenOriginal
        record = self._record()
        parents = run_parents(self.agent.read('procedures/get', {'digest': record['procedure']['digest']})['manifest'], record)
        method, approved = method_of(reported['procedure'], reported['settings']), {o['role']: o['sha256'] for o in request['outputs']}
        steps = {}
        for output in reported['outputs']:
            role = output['role']
            if output.get('outcome') is not None: continue
            local, entry = record['outputs'][role], request['publish'][role]
            raw = self._raw(record, role, approved[role])
            header, _ = derive_request(self.agent.project, WrittenOriginal(raw, local['profile'], dict(local['declared'] or {})), name=entry['name'],
                                       from_=parents, method=method, command_id=output_command(reported['run_id'], role), of_entity=entry.get('of_entity'),
                                       new_version_of=entry.get('new_version_of'), expected_parent=entry.get('expected_parent'),
                                       procedure={'id': reported['run_id'], 'role': role})
            steps[role] = (header, raw)
        return steps

    def report(self, summary='', *, evidence=None, **wait):
        """Propose the report, wait for the person's approval, report the run, then publish each output under that
        approval. Safe to repeat. Returns {plan, run_id, outputs: [{role, receipt}]}."""
        request = self.request()
        proposed = self.agent.propose('procedure-runs/report', request, summary, evidence=evidence)
        plan, record = proposed['hash'], (proposed.get('evidence') if evidence is not None else None)
        self.agent.wait(plan, evidence_id=record, **wait)
        reported = self.agent.execute('procedure-runs/report', request, plan, record)
        receipts = {o['role']: o['receipt'] for o in reported['outputs'] if o.get('outcome') is not None}
        for role, (header, raw) in self.steps(request, reported).items():
            receipts[role] = self.agent.execute_step('publications/derive', header, plan, record, raw=raw)
        return {'plan': plan, 'run_id': reported['run_id'], 'outputs': [{'role': o['role'], 'receipt': receipts[o['role']]} for o in reported['outputs']]}


AGENT_READ = 'ophiolite.agent-read/1'
HEAD = 65536  # the gateway's head: a file's first 64 KiB (asset_connectors.detect.HEAD)


class _AgentCatalogue(ProcedureClient):
    """The catalogue reads `intake._run` makes (get, bundle), sent with the agent's credential. Trusting is a change an
    agent proposes; it is never sent from here (a version neither trusted nor the agent's own is refused, `trust-needed`)."""

    def __init__(self, agent):
        self.agent, self.project = agent, agent.project

    def _post(self, area, operation, body, retry=False):
        return self.agent._post(area, operation, body)


class AgentRead:
    """E111 s2 (P-10): an agent reads one file on this computer with a read procedure version and uploads the file and
    what the procedure made under the one approval the person gives `upload-runs/start`. The procedure runs here first
    (`intake._run`: the version is fetched and checked by digest; one neither trusted nor the agent's own is refused);
    the start names the file, its first 64 KiB, the original and each output by bytes and sha256, so the steps the
    approval covers are exactly these bytes: the file's head, the declaration, the original when kept, then each output.
    The start and the run's outputs are saved (agent-read.json) before anything is proposed: reading again after a lost
    answer is the same plan, and each step already done answers what it answered. A staged original that expired before
    an output is sent again once.

        agent = AgentClient('https://ophiolite.example', 'project-id', credential)
        done = AgentRead(agent, 'end of well report.pdf', version=digest, attribution='NLOG.NL').read('Read the end of well report')
    """
    STATE = 'agent-read.json'

    def __init__(self, agent, path, *, version, attribution=None, audience=(), keep_original=False, settings=None, folder_name=None, folder=None, cache=None):
        if not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{64}', version): raise NotRun('read-version')
        # An agent's start names its settings: the project's defaults are taken only after a person checked them (E90).
        if not isinstance(attribution, str) or not attribution.strip(): raise NotRun('read-attribution')
        if isinstance(audience, str) or not all(isinstance(m, str) for m in audience): raise NotRun('read-audience')
        self.attribution, self.audience = attribution, list(audience)
        self.agent, self.path, self.version, self.keep = agent, Path(path), version, bool(keep_original)
        self.settings, self.folder_name, self.folder, self.cache = settings, (folder_name or Path(path).name)[:160], folder, cache

    def _state(self, sha256):
        from . import intake
        return Path(self.folder or intake.state_root()) / ('agent-%s-%s' % (sha256[:32], self.version[:16]))

    def request(self):
        """(the upload-runs/start request the person approves, the state folder, what the run saved); the procedure runs
        only when no saved read of this file with this version exists."""
        from . import intake
        size, sha256 = self.path.stat().st_size, intake._sha256(self.path)
        state = self._state(sha256)
        try: saved = json.loads((state / self.STATE).read_text(encoding='utf-8'))
        except (OSError, ValueError): saved = None
        if not (isinstance(saved, dict) and saved.get('schema') == AGENT_READ): saved = None
        if saved is not None and saved['request']['conversion']['keep_original'] != self.keep:
            raise intake.refused('keep-changed', {'keep_original': not self.keep}, how='with' if not self.keep else 'without',
                                 flag='with keep_original' if not self.keep else 'without keep_original', state=str(state))
        if saved is None:
            row = {'run_id': None, 'ordinal': 0, 'path': self.path.name, 'bytes': size, 'sha256': sha256, 'procedures': [{'digest': self.version}]}
            made = intake._run(_AgentCatalogue(self.agent), row, self.path, state, None, self.settings, None, False, self.cache, self.keep)
            body = made['body']
            with open(self.path, 'rb') as handle: head = handle.read(HEAD)
            conversion = {'command_id': body['command_id'], 'procedure': body['procedure'], 'original': body['original'], 'roles': body['roles'],
                          'keep_original': self.keep, 'settings': body['settings'], 'head': {'bytes': len(head), 'sha256': hashlib.sha256(head).hexdigest()}}
            request = {'command_id': 'read-' + uuid.uuid4().hex, 'folder_name': self.folder_name, 'rights_confirmed': True, 'reads': ['procedures'],
                       'attribution': self.attribution, 'audience': self.audience,
                       'files': [{'path': self.path.name, 'bytes': size, 'sha256': sha256}], 'conversion': conversion}
            saved = {'schema': AGENT_READ, 'request': request, 'attempt': made['attempt'], 'outputs': made['outputs'], 'body': {'roles': body['roles']}}
            _save(state / self.STATE, saved)  # before the start is proposed: a lost answer is the same command, so the same plan
        return saved['request'], state, saved

    def _bytes(self, request, state, saved):
        """The original and each output, refused before anything is sent when a file is not the one approved."""
        from . import intake
        original = request['conversion']['original']
        raw = self.path.read_bytes() if self.path.is_file() else None
        if raw is None or len(raw) != original['bytes'] or hashlib.sha256(raw).hexdigest() != original['sha256']:
            raise NotRun('read-file-changed', '/files/0', file=self.path.name)
        return raw, intake._saved_outputs(state, saved)

    @staticmethod
    def steps(request, run_id):
        """step → (operation, request without project_id, its bytes key or None), in the order the approval covers them."""
        at, c = {'run_id': run_id, 'ordinal': 0}, request['conversion']
        out = [('file:head', 'upload-runs/file', {**at, 'mode': 'head', 'reads': ['procedures']}, 'head'),
               ('convert', 'upload-runs/convert', {**at, **{k: v for k, v in c.items() if k != 'head'}}, None)]
        if c['keep_original']: out.append(('convert-original', 'upload-runs/convert-original', dict(at), 'original'))
        out += [('convert-output:' + r['role'], 'upload-runs/convert-output', {**at, 'role': r['role']}, r['role']) for r in c['roles']]
        return out

    def read(self, summary='', *, evidence=None, **wait):
        """Run the procedure here (once), propose the start, wait for the person's approval, start the upload, then send
        each step the approval covers. Safe to repeat. Returns {plan, run_id, conversion, state}."""
        from .errors import IntegrityConflict
        request, state, saved = self.request()
        proposed = self.agent.propose('upload-runs/start', request, summary, evidence=evidence)
        plan, record = proposed['hash'], (proposed.get('evidence') if evidence is not None else None)
        self.agent.wait(plan, evidence_id=record, **wait)
        original, outputs = self._bytes(request, state, saved)  # after approval, before anything is sent
        raw = {'head': original[:HEAD], 'original': original, **outputs}
        started = self.agent.execute('upload-runs/start', request, plan, record)
        answer, resent = None, False
        for step, operation, body, key in self.steps(request, started['run_id']):
            try: answer = self.agent.execute_step(operation, body, plan, record, raw=raw[key] if key else None)
            except IntegrityConflict as error:  # the staged original expired before this output: send it again once, then the output
                if resent or not request['conversion']['keep_original'] or not step.startswith('convert-output:') or ((getattr(error, 'details', None) or {}).get('reason') != 'original-expired'): raise
                resent = True
                self.agent.execute_step('upload-runs/convert-original', {'run_id': started['run_id'], 'ordinal': 0}, plan, record, raw=original)
                answer = self.agent.execute_step(operation, body, plan, record, raw=raw[key])
        return {'plan': plan, 'run_id': started['run_id'], 'conversion': (answer or {}).get('conversion'), 'state': str(state)}
