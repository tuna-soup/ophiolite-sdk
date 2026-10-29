"""E112 s2: recipes. A recipe (`ophiolite.recipe/1`, written by the person) names the steps a person would type, in
order: run a residual procedure on this computer, publish the run, read the result's outcome states, deliver the
result. `run` takes them one at a time, each in its own folder under the work folder, and records each in the work
folder's journal (`ophiolite.recipe-journal/1`) before and after it runs.

A crash, a refusal or a lost answer stops the recipe with the step's own sentence. The same call again continues from
the first step that is not finished, with that step's own recovery state: the run folder's `run.json`, E106's
`publish.json`, E109's pending delivery. There is no outer command id (2-F3): every write is an existing SDK call with
its own ids and its own authorisation on the server. A step is `failed` (and taken again as a new attempt in a new
folder) only when it provably had no effect; anything uncertain is `stopped` (the same attempt and folder again), and
a delivery whose outcome is unknown is only ever asked again (E109: reported again or reconciled, never sent again).

The uploads and the well set are not steps: a run again starts from a chosen well-set version, given as an input."""
import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from .procedures import PROJECT_INPUT, NotRun, _secretive, _windows

RECIPE, JOURNAL = 'ophiolite.recipe/1', 'ophiolite.recipe-journal/1'
SCHEMAS = Path(__file__).resolve().parent / 'schemas'
INPUT = re.compile(r'[a-z][a-z0-9_]{0,30}')
ID = re.compile(r'[a-z][a-z0-9-]{0,30}')
ROLE = re.compile(r'[a-z][a-z0-9_-]{0,63}')
FINAL = ('finished', 'set_aside')
WORDS = {'finished': 'Finished', 'set_aside': 'Set aside', 'waiting': 'Waiting'}  # everything else: Needs attention
SENTENCES = {
    'recipe-unreadable': 'Not run: {path} is not a recipe this version can read.',
    'recipe-invalid': 'Not run: the recipe is not valid at {where}: {what}.',
    'recipe-journal': 'Not run: {path} is not a recipe journal this version can read; use a new folder.',
    'recipe-busy': 'This recipe is already running in this folder.',
    'recipe-changed': 'Not run: {work} holds a run of another recipe; run it again with the recipe it started with, or use a new folder.',
    'recipe-principal': 'Not run: {work} was started by another person, project or server; use a new folder.',
    'recipe-inputs': "Not run: {what}; give the inputs this folder's run started with, or use a new folder.",
    'recipe-input': 'Not run: {what}.',
    'recipe-set-aside': 'Not run: only a delivery whose outcome is unknown can be set aside; {what}.',
}


def _refused(code, field='', details=None, **words):
    return NotRun(code, field, details, sentence=SENTENCES[code].format(**words))


# ---------------------------------------------------------------- the recipe

def _text(lo, hi):
    return lambda v: None if isinstance(v, str) and lo <= len(v) <= hi else 'must be text of %d to %d characters' % (lo, hi)


def _version(v):
    return None if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 'must be a whole number from 1'


def _unit(v):
    return None if v in ('m', 'ft') else 'must be m or ft'


def _settings(v):
    if not isinstance(v, dict) or len(v) > 32: return 'must be an object of at most 32 settings'
    bad = next((k for k, x in v.items() if not (INPUT.fullmatch(k) and isinstance(x, str) and len(x) <= 1000)), None)
    return None if bad is None else 'has the setting %r, which is not a name with a text value' % bad


INPUT_REF, STEP_REF, ROLE_REF, SYSTEMS = 'input', 'step', 'role', 'systems'  # references, checked against the recipe
# per step kind: key -> (check or a reference kind, required); a reference kind is (what, the type or step kinds it names)
FIELDS = {
    'residuals': {'procedure': (_text(1, 160), True), 'version': (_version, True), 'selection': ((INPUT_REF, 'item'), True),
                  'surface': ((INPUT_REF, 'item'), True), 'formation': (_text(1, 64), True), 'display_unit': (_unit, False)},
    'publish': {'run': ((STEP_REF, 'residuals'), True), 'name': (_text(1, 160), True), 'for': (_text(1, 80), False)},
    'states': {'result': ((ROLE_REF, 'publish'), True)},
    'deliver': {'procedure': (_text(1, 160), True), 'version': (_version, False), 'item': ((ROLE_REF, 'publish'), True),
                'as': (_text(1, 80), False), 'systems': ((SYSTEMS, 'file'), True), 'settings': (_settings, False)},
}


def _secret(value, where):
    """(where, the key) of the first key, at any depth, that names a secret (the procedure rules' secret words)."""
    if isinstance(value, dict):
        for k, v in value.items():
            if _secretive(str(k)): return '%s/%s' % (where, k), str(k)
            found = _secret(v, '%s/%s' % (where, k))
            if found: return found
    if isinstance(value, list):
        for i, v in enumerate(value):
            found = _secret(v, '%s/%d' % (where, i))
            if found: return found
    return None


def _reference(value, kind, wanted, inputs, earlier):
    """Why VALUE is not a reference of KIND naming WANTED (an input type, or the step kind it must come from), or None."""
    if kind == SYSTEMS:
        if not isinstance(value, dict) or not 1 <= len(value) <= 8: return 'must map each system slot to a file input, as {"db": {"input": NAME}}'
        for slot, ref in value.items():
            if not INPUT.fullmatch(slot): return 'has the slot %r, which is not a slot name' % slot
            why = _reference(ref, INPUT_REF, wanted, inputs, earlier)
            if why: return 'slot %s %s' % (slot, why)
        return None
    if kind == INPUT_REF:
        if not (isinstance(value, dict) and set(value) == {'input'} and isinstance(value['input'], str)): return 'must name an input, as {"input": NAME}'
        name = value['input']
        if name not in inputs: return 'names the input %s, which the recipe does not declare' % name
        if inputs[name]['type'] != wanted: return 'names the input %s, which is a %s, not a %s' % (name, inputs[name]['type'], wanted)
        return None
    keys = {'from', 'role'} if kind == ROLE_REF else {'from'}
    shape = '{"from": ID, "role": ROLE}' if kind == ROLE_REF else '{"from": ID}'
    if not (isinstance(value, dict) and set(value) == keys and isinstance(value['from'], str)): return 'must name an earlier %s step, as %s' % (wanted, shape)
    if kind == ROLE_REF and not (isinstance(value['role'], str) and ROLE.fullmatch(value['role'])): return 'must name an output role of that step'
    ref = value['from']
    if ref not in earlier: return 'names the step %s, which is not an earlier step of the recipe' % ref
    if earlier[ref] != wanted:
        return 'names the step %s, a %s step%s' % (ref, earlier[ref], ', which makes nothing a later step can use' if earlier[ref] in ('states', 'deliver') else
                                                   ', not a %s step' % wanted)
    return None


def check(doc):
    """Refuse a recipe that is not `ophiolite.recipe/1`, with the place and the reason (NotRun `recipe-invalid`)."""
    def bad(where, what): raise _refused('recipe-invalid', where, {}, where=where or 'its top', what=what)
    if not isinstance(doc, dict): bad('', 'a recipe is a JSON object')
    found = _secret(doc, '')
    if found: bad(found[0], 'the key %r names a secret; a recipe holds no credential or configuration value' % found[1])
    for key in doc:
        if key not in ('schema', 'name', 'inputs', 'steps'): bad('/' + key, 'a recipe has no such field')
    if doc.get('schema') != RECIPE: bad('/schema', 'it must be "%s"' % RECIPE)
    why = _text(1, 80)(doc.get('name'))
    if why: bad('/name', why)
    inputs = doc.get('inputs')
    if not isinstance(inputs, dict) or not 1 <= len(inputs) <= 16: bad('/inputs', 'it must name 1 to 16 inputs')
    for name, spec in inputs.items():
        if not INPUT.fullmatch(name): bad('/inputs/' + name, 'an input name is a lowercase word of letters, digits and _')
        if not (isinstance(spec, dict) and set(spec) == {'type'} and spec['type'] in ('item', 'file')): bad('/inputs/' + name, 'it must be {"type": "item"} or {"type": "file"}')
    steps = doc.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 16: bad('/steps', 'it must list 1 to 16 steps')
    earlier = {}
    for n, step in enumerate(steps):
        where = '/steps/%d' % n
        if not isinstance(step, dict) or set(step) != {'id', 'step', 'with'}: bad(where, 'a step is exactly {"id", "step", "with"}')
        if not (isinstance(step['id'], str) and ID.fullmatch(step['id'])): bad(where + '/id', 'a step id is a lowercase word of letters, digits and -')
        if step['id'] in earlier: bad(where + '/id', 'two steps are called %s; each step needs its own id' % step['id'])
        if step['step'] not in FIELDS: bad(where + '/step', 'a step is one of %s' % ', '.join(FIELDS))
        given, fields = step['with'], FIELDS[step['step']]
        if not isinstance(given, dict): bad(where + '/with', 'it must be an object')
        for key in given:
            if key not in fields: bad('%s/with/%s' % (where, key), 'a %s step takes %s' % (step['step'], ', '.join(fields)))
        for key, (rule, required) in fields.items():
            if key not in given:
                if required: bad('%s/with/%s' % (where, key), 'it is missing')
                continue
            why = _reference(given[key], rule[0], rule[1], inputs, earlier) if isinstance(rule, tuple) else rule(given[key])
            if why: bad('%s/with/%s' % (where, key), why)
        earlier[step['id']] = step['step']
    return doc


def load(path):
    """The recipe at PATH, checked (`check`); NotRun with one sentence otherwise."""
    path = Path(path)
    try: doc = json.loads(path.read_bytes().decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError): raise _refused('recipe-unreadable', '', {'path': str(path)}, path=path) from None
    return check(doc)


def _canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


# ---------------------------------------------------------------- the journal

def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def _save(path, journal):
    """Whole-file atomic replace (a temporary file of mode 0600 beside it, then os.replace); no durability claim."""
    fd, partial = tempfile.mkstemp(dir=path.parent, prefix='.journal-', suffix='.partial')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(json.dumps(journal, indent=2, sort_keys=True) + '\n')
        os.replace(partial, path)
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise


def read(work):
    """The journal of WORK (`ophiolite.recipe-journal/1`), or NotRun `recipe-journal`."""
    path = Path(work).expanduser().absolute() / 'journal.json'
    try: journal = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): raise _refused('recipe-journal', '', {'path': str(path)}, path=path) from None
    if not isinstance(journal, dict) or journal.get('schema') != JOURNAL or not isinstance(journal.get('steps'), list):
        raise _refused('recipe-journal', '', {'path': str(path)}, path=path)
    return journal


def _principal(client):
    from .exchange import ClientTransport
    return {'url': client.url, 'project': client.project, 'identity': ClientTransport(client).identity()}


def _given(doc, inputs):
    """The inputs as given, one value per declared input and no other."""
    inputs = {k: str(v) for k, v in (inputs or {}).items()}
    for name in inputs:
        if name not in doc['inputs']: raise _refused('recipe-input', '/inputs/' + name, {}, what='the recipe has no input called %s' % name)
    for name in doc['inputs']:
        if name not in inputs: raise _refused('recipe-input', '/inputs/' + name, {}, what='the input %s is missing; give it as --input %s=VALUE' % (name, name))
    return inputs


def _bind(client, doc, inputs):
    """Each input bound once, before any step: an item resolved to its exact version, a file hashed."""
    bindings = {}
    for name, spec in doc['inputs'].items():
        text = inputs[name]
        if spec['type'] == 'item':
            asset, revision = client.result_version(text)
            bindings[name] = {'type': 'item', 'text': text, 'asset_id': asset, 'revision': revision}
        else:
            path = Path(text).expanduser().absolute()
            if not path.is_file(): raise _refused('recipe-input', '/inputs/' + name, {}, what='the input %s names %s, which is not a file' % (name, path))
            bindings[name] = {'type': 'file', 'path': str(path), 'sha256': _sha256(path), 'size': path.stat().st_size}
    return bindings


def _same_inputs(journal, inputs, work):
    """Refuse a resume whose inputs differ from those the run started with; an item is never resolved again."""
    for name, bound in journal['bindings'].items():
        if bound['type'] == 'item':
            if inputs[name] != bound['text']: raise _refused('recipe-inputs', '/inputs/' + name, {}, work=work, what='the input %s was %s, not %s' % (name, bound['text'], inputs[name]))
            continue
        path = Path(inputs[name]).expanduser().absolute()
        if str(path) != bound['path']: raise _refused('recipe-inputs', '/inputs/' + name, {}, work=work, what='the input %s was %s, not %s' % (name, bound['path'], path))
        if not path.is_file() or path.stat().st_size != bound['size'] or _sha256(path) != bound['sha256']:
            raise _refused('recipe-inputs', '/inputs/' + name, {}, work=work, what='%s has changed since this run started' % path)


# ---------------------------------------------------------------- the steps

class Context:
    """What a step reads: the client, the work folder, the bindings and the earlier steps' results."""

    def __init__(self, client, work, journal, yes, wait):
        self.client, self.work, self.journal, self.yes, self.wait = client, work, journal, yes, wait

    def item(self, ref):
        bound = self.journal['bindings'][ref['input']]
        return '@%s:%s' % (bound['asset_id'], bound['revision'])

    def file(self, ref):
        return self.journal['bindings'][ref['input']]['path']

    def result(self, ref):
        return next(s for s in self.journal['steps'] if s['id'] == ref['from'])['result']

    def output(self, ref):
        """`@ASSET:REVISION` of an earlier publish step's output ROLE; NotRun when that step published no such role."""
        outputs = self.result(ref)['outputs']
        if ref['role'] not in outputs:
            raise _refused('recipe-input', '', {'role': ref['role']}, what='step %s published no output called %s; it published %s' % (
                ref['from'], ref['role'], ', '.join(sorted(outputs)) or 'none'))
        return '@%s:%s' % (outputs[ref['role']]['asset_id'], outputs[ref['role']]['revision'])


def _residuals(ctx, step, folder):
    """Run the residual procedure into `<folder>/run`, a new folder (O4: its parent is made here). A `run.json` left
    by an earlier attempt is that run, finished: nothing is published by a run, so it is never taken again."""
    from . import residuals
    w, target = step['with'], folder / 'run'
    if (target / 'run.json').is_file():
        record, sentence = json.loads((target / 'run.json').read_text(encoding='utf-8')), 'Ran %s on this computer.' % w['procedure']
    else:
        folder.mkdir(parents=True, exist_ok=True)
        said = residuals.run(ctx.client, w['procedure'], target, ctx.item(w['selection']), ctx.item(w['surface']), w['formation'],
                             display_unit=w.get('display_unit', 'm'), version=w['version'], yes=ctx.yes)
        record, sentence = said['run'], said['sentence']
    outputs = {role: o['sha256'] for role, o in record['outputs'].items()}
    return 'finished', {'run': target.relative_to(ctx.work).as_posix(), 'digest': record['procedure']['digest'], 'outputs': outputs}, sentence


def _publish(ctx, step, folder):
    """E106's publish of the run folder; its `publish.json` makes a repeat the same report (one run, each output once)."""
    w = step['with']
    run = ctx.work / ctx.result(w['run'])['run']
    said = ctx.client.procedure_publish(run, name=w['name'], for_outcome=w.get('for'))
    outputs = {o['role']: {'asset_id': o['receipt']['asset_id'], 'revision': o['receipt']['revision']} for o in said['outputs']}
    run_id = json.loads((run / 'publish.json').read_text(encoding='utf-8'))['run_id']  # saved by E106 once the report is accepted
    return 'finished', {'run_id': run_id, 'outputs': outputs}, said['sentence']


def _states(ctx, step, folder):
    from .outcomes import state_lines
    asset, revision = PROJECT_INPUT.match(ctx.output(step['with']['result'])).groups()
    said = ctx.client.outcome_states(asset, revision)
    return 'finished', {'outcomes': [{'label': o['label'], 'version': o['version'], 'state': o['state']} for o in said['outcomes']]}, state_lines(said)


def _outcome(state, reported):
    """The step's state for a delivery's answer (6-D2): only a confirmed outcome the project recorded is finished."""
    if state == 'confirmed': return 'finished' if reported else 'stopped'  # deliver again reports it, never sends again
    if state == 'not-sent' and reported: return 'failed'  # E109's tombstone: nothing was sent, a new attempt is safe
    return 'unknown'


def _deliver(ctx, step, folder, set_aside=False):
    """E109's deliver from this step's own folder. The folder's records decide first (6-F1): a finished attempt is the
    step's answer and a set-aside is set aside, with no call; only a pending attempt is delivered again (reported or
    reconciled, never sent again); an empty folder delivers once."""
    from .procedures import delivery_records, delivery_words
    w = step['with']
    w_name = w['procedure']
    held = delivery_records(folder, w_name)
    if not held['pending']:
        if held['finished']:
            done = held['finished'][-1]
            result = {'delivery_id': done['delivery_id'], 'state': done['result']['state'], 'items': done['result']['items'], 'reported': True}
            return _outcome(result['state'], True), result, delivery_words(done, again=True)
        if held['set_aside']:
            kept = held['set_aside'][-1]
            return 'set_aside', {'delivery_id': kept.get('delivery_id'), 'state': 'unknown', 'items': 0, 'reported': bool(kept.get('reported'))}, (
                'Set aside: the outcome of this delivery to %s stays unknown in the project.' % (kept.get('destination') or 'the destination'))
    if set_aside and not held['pending']: raise _refused('recipe-set-aside', '', {'step': step['id']}, what='step %s holds no delivery waiting for its outcome' % step['id'])
    folder.mkdir(parents=True, exist_ok=True)
    settings = ['%s=%s' % kv for kv in sorted((w.get('settings') or {}).items())] or None
    said = ctx.client.deliver(w_name, systems={slot: ctx.file(ref) for slot, ref in w['systems'].items()}, items=[ctx.output(w['item'])],
                              settings=settings, work=folder, wait=ctx.wait, yes=ctx.yes, version=w.get('version'), set_aside=set_aside, as_=w.get('as'))
    result = {'delivery_id': said['delivery_id'], 'state': said['state'], 'items': said['items'], 'reported': bool(said['reported'])}
    return ('set_aside' if set_aside else _outcome(said['state'], said['reported'])), result, said['sentence']


def _effects(ctx, step, folder):
    """After a step raised: 'none' when it provably had no effect (a new attempt is safe), 'pending' when a delivery
    waits for its outcome, otherwise 'some' (S2-D1)."""
    kind = step['step']
    if kind in ('residuals', 'states'): return 'none'  # a local run (nothing published) and a read
    if kind == 'publish':
        try: run = ctx.work / ctx.result(step['with']['run'])['run']
        except (KeyError, StopIteration, TypeError): return 'none'
        return 'some' if (run / 'publish.json').exists() else 'none'
    from .procedures import delivery_records
    held = delivery_records(folder, step['with']['procedure'])
    if held['pending']: return 'pending'
    return 'some' if held['finished'] or held['set_aside'] or held['intents'] else 'none'


_STEPS = {'residuals': _residuals, 'publish': _publish, 'states': _states, 'deliver': _deliver}  # fixed: one per step kind (6-P2)


def _summary(doc, journal, work, stopped=None):
    steps, total = journal['steps'], len(journal['steps'])
    if stopped is None:
        return {'state': 'finished', 'sentence': 'Finished: all %d steps of "%s".' % (total, doc['name']), 'work': str(work), 'steps': steps}
    n, entry = stopped
    if entry['state'] == 'unknown':
        sentence = 'Step %d of %d (%s): %s Run the same command again to ask again, or set it aside with --set-aside %s.' % (n, total, entry['id'], entry['sentence'], entry['id'])
    else:
        sentence = 'Stopped at step %d of %d (%s): %s Run the same command again to continue.' % (n, total, entry['id'], entry['sentence'])
    return {'state': entry['state'], 'sentence': sentence, 'work': str(work), 'steps': steps}


def _presented(result, call, name):
    from .presentation import PresentedRecipe  # every returned run loads it (s3-D3)
    return PresentedRecipe.present(result, call, name)


def run(client, recipe, work, inputs=None, *, set_aside=None, yes=False, wait=0):
    """Run RECIPE (a path) in WORK (a folder: new, or the one an earlier run of this recipe used) with INPUTS
    ({name: value}: an item as ITEM, ITEM@N or @ASSET:REVISION; a file as its path). Returns {state, sentence, work,
    steps}: `state` is finished, failed, stopped or unknown (the step it stopped at). Refusals before any step raise
    NotRun and enter no step: another runner in WORK, another recipe, person, project or server, other inputs.
    `set_aside` names an unknown delivery step to set aside (E109); `yes` runs versions you have not trusted. The result
    shows itself in a notebook; once finished, with a "Run again" line made from the inputs as they were here (E112 s3)."""
    from .exchange import Busy_, folder_lock
    try: call = copy.deepcopy({'recipe': str(Path(recipe).expanduser().absolute()), 'inputs': inputs})
    except Exception: call = None  # no line, and the card says why
    doc = load(recipe)
    if _windows() and any(s['step'] == 'deliver' for s in doc['steps']): raise NotRun('windows')  # E109 D8, before the journal
    inputs = _given(doc, inputs)
    work = Path(work).expanduser().absolute()
    work.mkdir(parents=True, exist_ok=True)
    lock = folder_lock(work / 'journal.lock', timeout=0)
    try: lock.__enter__()
    except Busy_: raise _refused('recipe-busy', '', {'work': str(work)}) from None
    try:
        path = work / 'journal.json'
        principal = _principal(client)
        if path.exists():
            journal = read(work)
            if journal.get('recipe_sha256') != hashlib.sha256(_canonical(doc)).hexdigest(): raise _refused('recipe-changed', '', {}, work=work)
            if journal.get('principal') != principal: raise _refused('recipe-principal', '', {}, work=work)
            _same_inputs(journal, inputs, work)
        else:
            journal = {'schema': JOURNAL, 'recipe_name': doc['name'], 'recipe_sha256': hashlib.sha256(_canonical(doc)).hexdigest(), 'run_id': uuid.uuid4().hex,
                       'principal': principal, 'bindings': _bind(client, doc, inputs),
                       'steps': [{'id': s['id'], 'step': s['step'], 'state': 'waiting', 'attempt': 1, 'folder': None, 'result': None, 'sentence': None,
                                  'decided_by': None} for s in doc['steps']]}
        if set_aside is not None:
            entry = next((s for s in journal['steps'] if s['id'] == set_aside), None)
            if entry is None or entry['step'] != 'deliver' or entry['state'] != 'unknown':
                raise _refused('recipe-set-aside', '', {'step': set_aside}, what='step %s is %s' % (set_aside, 'not in this recipe' if entry is None else
                                                                                                    'a %s step that is %s' % (entry['step'], entry['state'])))
        _save(path, journal)  # the bindings, before any step
        ctx = Context(client, work, journal, yes, wait)
        for n, (step, entry) in enumerate(zip(doc['steps'], journal['steps']), 1):
            if entry['state'] in FINAL: continue
            if entry['state'] == 'failed': entry['attempt'] += 1  # provably no effect: a new attempt, in a new folder
            entry['folder'] = 'steps/%d-%s/a%d' % (n, step['id'], entry['attempt'])
            folder = work / entry['folder']
            entry.update(state='started', sentence=None)
            _save(path, journal)  # 1-M2: the intent, before the step is entered
            try:
                if step['id'] == set_aside:
                    state, result, sentence = _deliver(ctx, step, folder, set_aside=True)
                    if state == 'set_aside': entry['decided_by'] = principal['identity']
                else: state, result, sentence = _STEPS[step['step']](ctx, step, folder)
            except Exception as error:  # noqa: BLE001 (every refusal and failure is classified, never swallowed: it stops the recipe)
                state = {'none': 'failed', 'pending': 'unknown', 'some': 'stopped'}[_effects(ctx, step, folder)]
                result, sentence = entry['result'], str(error) or type(error).__name__
            entry.update(state=state, result=result, sentence=sentence)
            _save(path, journal)
            if state not in FINAL: return _presented(_summary(doc, journal, work, (n, entry)), call, doc['name'])
        return _presented(_summary(doc, journal, work), call, doc['name'])
    finally:
        lock.__exit__(None, None, None)


def show(work):
    """The journal of WORK in words, one line per step (Finished, Needs attention, Waiting or Set aside), read on this
    computer only; {lines, journal}."""
    journal = read(work)
    lines = ['%s: %d steps' % (journal.get('recipe_name'), len(journal['steps']))]
    for n, s in enumerate(journal['steps'], 1):
        word = WORDS.get(s['state'], 'Needs attention')
        lines.append('%d. %s (%s): %s%s' % (n, s['id'], s['step'], word, '' if s['state'] in ('finished', 'waiting') or not s.get('sentence') else ': ' + s['sentence']))
    return {'lines': lines, 'journal': journal}
