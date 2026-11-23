"""E178: chains — a project's declared order of steps after a new version of an item (`ophiolite.chain/1`), and their
runs (`ophiolite.chain-run/1`). A chain's steps are a tool step checked against one outcome version, a question with
fixed answers, or work done outside Ophiolite; a run is one pass of one chain version over the version that started it
(or the versions a person named), with every act on a step kept with who did it and when.

`client.chains` is a `ChainClient` bound to the client. Each method sends one request and returns the served answer
as it is; the server decides who may declare, enable, dismiss or act (a refusal is the server's, with its reason in
`error.details['reason']` and its sentence from `contracts/vocabulary/v1/chain-reasons.json`). Each write sends a new
command id unless one is given; the same id with the same body answers the stored result.

`state_words`, `run_lines`, `chain_line` and `due_line` say an answer in words (labels and the vocabulary's words; no
step keys, codes, digests or ids), as `ophiolite results chains` and `ophiolite results chain-runs` print by default.
"""
import uuid


def _version(v):
    """{asset_id, revision} from a dict carrying them or an (asset_id, revision) pair."""
    if isinstance(v, dict): return {'asset_id': v['asset_id'], 'revision': v['revision']}
    asset_id, revision = v
    return {'asset_id': asset_id, 'revision': revision}


def _page(body, limit, cursor):
    if limit is not None: body['limit'] = limit
    if cursor is not None: body['cursor'] = cursor
    return body


class ChainClient:
    """The chains of one project and their runs, through `client._post`. Nothing is refused here: the server checks
    every request and every right."""

    def __init__(self, client):
        self._client = client

    def _read(self, area, operation, body):
        return self._client._post(area, operation, body, retry=True)

    def _write(self, area, operation, body, command_id):
        return self._client._post(area, operation, {'command_id': command_id or '%s-%s' % (operation, uuid.uuid4().hex), **body}, retry=True)

    # --- chains ------------------------------------------------------------------------------------------------------

    def declare(self, declaration, *, command_id=None):
        """Declare a chain (`ophiolite.chain/1`); the answer is its entry at version 1."""
        return self._write('chains', 'declare', {'chain': declaration}, command_id)

    def revise(self, chain_id, declaration, *, command_id=None):
        """The chain's next version, when anything differs; earlier versions and their runs are kept unchanged."""
        return self._write('chains', 'revise', {'chain_id': chain_id, 'chain': declaration}, command_id)

    def enable(self, chain_id, *, command_id=None):
        """Enable a chain that is not withdrawn; the answer's `due_stops` counts the due lines no longer listed."""
        return self._write('chains', 'enable', {'chain_id': chain_id}, command_id)

    def disable(self, chain_id, *, command_id=None):
        """Disable a chain; it is kept and its runs go on."""
        return self._write('chains', 'disable', {'chain_id': chain_id}, command_id)

    def withdraw(self, chain_id, *, command_id=None):
        """Withdraw a chain for good; its label is free again and its runs are kept."""
        return self._write('chains', 'withdraw', {'chain_id': chain_id}, command_id)

    def list(self, *, limit=None, cursor=None):
        """One page of the project's chains {project, chains, next}; follow `next` as `cursor`."""
        return self._read('chains', 'list', _page({}, limit, cursor))

    def get(self, chain_id):
        """One chain {current, versions, actions}: every version and every action on it."""
        return self._read('chains', 'get', {'chain_id': chain_id})

    def due(self, chain_id=None, *, limit=None, cursor=None):
        """One page of the item versions a chain should start for and has not (`ophiolite.chain-due/1`), of one
        chain or of every chain; follow `next` as `cursor`."""
        return self._read('chains', 'due', _page({} if chain_id is None else {'chain_id': chain_id}, limit, cursor))

    def dismiss(self, chain_id, asset_id, revision, reason, *, command_id=None):
        """Set one due line aside with your reason: no run starts for that version. The answer is the due page."""
        return self._write('chains', 'dismiss', {'chain_id': chain_id, 'asset_id': asset_id, 'revision': revision, 'reason': reason}, command_id)

    # --- runs --------------------------------------------------------------------------------------------------------

    def run_start(self, chain_id, chain_version, *, trigger=None, inputs=None, command_id=None):
        """Start a run of one chain version over the version that triggered it (`trigger`, for a chain on a version)
        or over the versions you name (`inputs`, for a chain on request); each a {asset_id, revision} or a pair."""
        body = {'chain_id': chain_id, 'chain_version': chain_version}
        if trigger is not None: body['trigger'] = _version(trigger)
        if inputs is not None: body['inputs'] = [_version(v) for v in inputs]
        return self._write('chain-runs', 'start', body, command_id)

    def run_attach(self, run_id, step, result, *, command_id=None):
        """Attach a result version to a tool step; its check under the step's outcome closes the step or refuses it."""
        return self._write('chain-runs', 'attach', {'run_id': run_id, 'step': step, 'result': _version(result)}, command_id)

    def run_choose(self, run_id, step, choice, *, command_id=None):
        """Answer a choice step with one of its choices (by its id)."""
        return self._write('chain-runs', 'choose', {'run_id': run_id, 'step': step, 'choice': choice}, command_id)

    def run_acknowledge(self, run_id, step, label, *, reference=None, command_id=None):
        """Say that a step outside Ophiolite was done, with a label and where it is kept."""
        body = {'run_id': run_id, 'step': step, 'label': label}
        if reference is not None: body['reference'] = reference
        return self._write('chain-runs', 'acknowledge', body, command_id)

    def run_decide(self, run_id, step, apply, reason, *, command_id=None):
        """Decide whether a step whose condition cannot be decided applies, with your reason."""
        return self._write('chain-runs', 'decide', {'run_id': run_id, 'step': step, 'apply': apply, 'reason': reason}, command_id)

    def run_continue(self, run_id, step, reason, *, command_id=None):
        """Continue past a rejected or unchecked tool step with your reason; the check is kept as it was."""
        return self._write('chain-runs', 'continue', {'run_id': run_id, 'step': step, 'reason': reason}, command_id)

    def run_get(self, run_id, *, step=None, cursor=None):
        """One run (`ophiolite.chain-run/1`); with `step` and `cursor`, an older page of that step's acts."""
        body = {'run_id': run_id}
        if step is not None: body['step'] = step
        if cursor is not None: body['cursor'] = cursor
        return self._read('chain-runs', 'get', body)

    def run_list(self, chain_id=None, *, limit=None, cursor=None):
        """One page of the runs of this project or of one chain, newest first {project, runs, next}."""
        return self._read('chain-runs', 'list', _page({} if chain_id is None else {'chain_id': chain_id}, limit, cursor))


# --- words ----------------------------------------------------------------------------------------------------------

def _contract(path):
    import importlib.resources
    import json
    return json.loads(importlib.resources.files('ophiolite').joinpath('contracts/' + path).read_bytes())


def vocabulary():
    """`ophiolite.chain-reasons/1`: the reasons' sentences, the step states' and the comparisons' words."""
    return _contract('vocabulary/v1/chain-reasons.json')


def measure_words(name):
    """A measure's words as the outcome rules give them (rules.json `measures`), else its name."""
    for kind in _contract('outcomes/v1/rules.json')['kinds'].values():
        for rule in kind.get('rules', {}).values():
            if name in rule.get('measures', {}): return rule['measures'][name]['words']
    return name


def _shown(number):
    return '%s' % (int(number) if float(number).is_integer() else number)


def state_words(step, words=None):
    """The words a person reads for a served step's state, its condition filled in (as the server's job sentence)."""
    words = words or vocabulary()
    text, condition = words['states'][step['state']], step.get('condition')
    if condition is None: return text
    value = condition['value']
    compared = words['comparisons'][condition['comparison']]
    if isinstance(value, list): compared, value = compared.replace('{low}', _shown(value[0])).replace('{high}', _shown(value[1])), ''
    out = text.replace('{measure words}', measure_words(condition['measure'])).replace('{comparison words}', compared)
    out = out.replace('{read}', '' if condition['read'] is None else _shown(condition['read'])).replace('{value}', _shown(value) if value != '' else '')
    return ' '.join(out.replace('{unit}', condition['unit'] or '').split())


RUN_STATES = {'open': 'open', 'waiting': 'waiting for a person', 'stopped': 'stopped at a rejected step', 'done': 'done'}
VERDICTS = {'accepted': 'accepted', 'rejected': 'rejected', 'not_compared': 'not compared'}


def _by(actor):
    return actor['person'] if actor.get('agent') is None else 'an assistant for %s' % actor['person']


def _plural(n, one, many):
    return '%d %s' % (n, one if n == 1 else many)


def chain_line(entry):
    """One chain in words: its name, state and version, what starts it and its steps by label."""
    d = entry['declaration']
    start = 'starts on request' if d['trigger']['on'] == 'request' else 'starts after a new version'
    return '"%s" (%s, version %d), %s; %s: %s.' % (d['label'], entry['state'], entry['version'], start, _plural(len(d['steps']), 'step', 'steps'),
                                                   ', '.join(s['label'] for s in d['steps']))


def detail_lines(detail):
    """A chain with every version and every action, in words."""
    lines = [chain_line(detail['current'])]
    lines += ['Version %d, declared by %s.' % (v['version'], _by(v['declared_by'])) for v in detail['versions']]
    lines += ['%d. %s by %s (version %d).' % (n, a['action'].capitalize(), _by(a['by']), a['version']) for n, a in enumerate(detail['actions'], 1)]
    return lines


def due_line(line, names=None):
    """One due line: the chain and the item version it should start for."""
    item = (names or {}).get((line['trigger']['asset_id'], line['trigger']['revision']), 'a new version of an item')
    return '"%s" version %d is due for %s.' % (line['chain']['label'], line['chain']['version'], item)


def _act_words(act, declared, words):
    who = _by(act['by'])
    if act['act'] == 'attached':
        check = act.get('check')
        return 'A result was attached by %s%s.' % (who, '' if check is None else '; its check: ' + VERDICTS[check['verdict']])
    if act['act'] == 'refused': return 'A result from %s was refused: %s' % (who, words['reasons'][act['refusal']])
    if act['act'] == 'chose':
        label = next((c['label'] for c in (declared.get('choice') or {}).get('choices', ()) if c['id'] == act['choice']), act['choice'])
        return '%s answered "%s".' % (who, label)
    if act['act'] == 'acknowledged':
        return '%s said "%s" was done outside%s.' % (who, act['label'], '' if act.get('reference') is None else ', kept at %s' % act['reference'])
    said = {'applied': 'decided it applies', 'skipped': 'skipped it', 'continued': 'continued despite the check'}[act['act']]
    return '%s %s: %s' % (who, said, act['reason'])


def run_line(run, names=None):
    """A run's first line (or a listed run's only line): its chain version, what it runs over, its state and who
    started it."""
    trigger = run['trigger']
    if trigger['on'] == 'version': over = (names or {}).get((trigger['asset_id'], trigger['revision']), 'a new version of an item')
    else: over = _plural(len(trigger['inputs']), 'version a person named', 'versions a person named')
    return '"%s" version %d over %s: %s. Started by %s.' % (run['chain']['label'], run['chain']['version'], over, RUN_STATES[run['state']], _by(run['started']['by']))


def run_lines(run, names=None, words=None):
    """A run in words: its first line, then each step by label with its state and its acts."""
    words = words or vocabulary()
    declared = {s['key']: s for s in run['chain']['declaration']['steps']}
    lines = [run_line(run, names)]
    for s in run['steps']:
        lines.append('%s: %s' % (s['label'], state_words(s, words)))
        if s.get('newer') is not None: lines.append('  A newer version of an input this step reads exists.')
        older = s['acts_count'] - len(s['acts'])
        if older: lines.append('  %s not shown.' % _plural(older, 'older act', 'older acts'))
        lines += ['  ' + _act_words(a, declared[s['key']], words) for a in s['acts']]
    return lines


def version_names(client, pairs):
    """{(asset_id, revision): '"NAME" version N'} for the item versions you can see among `pairs` (one inventory read)."""
    import tempfile
    from .exchange import ClientTransport, Exchange
    pairs = set(pairs)
    if not pairs: return {}
    transport = ClientTransport(client)
    out = {}
    with tempfile.TemporaryDirectory() as scratch:
        held = Exchange(transport, scratch)
        for item in transport.inventory():
            wanted = {r for a, r in pairs if a == item.get('asset_id')}
            if not wanted: continue
            for v in held._history(item) or []:
                if v.get('revision') in wanted: out[(item['asset_id'], v['revision'])] = 'version %s of "%s"' % (v.get('number'), item.get('name'))
            if item.get('revision') in wanted and (item['asset_id'], item['revision']) not in out:
                out[(item['asset_id'], item['revision'])] = 'the latest version of "%s"' % item.get('name')
    return out
