"""E155 s0: check, get and send under an assistant (an agent credential or an assistant sign-in).

An assistant checks what differs and gets the versions it may read exactly as a person's script does (`Exchange`), with
its own key: the transport reads through `AgentClient.reads`, a pending send is bound to the agent's id (not to the
key, which an assistant sign-in refreshes), and no delivery observation is sent (`activity/report` is a person's).

    agent = AgentClient('https://ophiolite.example', 'project-id', credential)
    ex = agent.exchange('work')
    ex.check(); ex.get(item, output='work/tops')
    ex.send_run('runs/shifted', name='Shifted tops', of=held_result, expected=held_revision)

An assistant publishes a result only as a step of a tool run it reported (E166), so `send` is refused before anything
is locked, saved or sent (`run-needed`). `send_run` sends a local run's outputs (a `run.json` folder, E106) as one
`procedure-runs/report` the person approves, bound to what the folder holds: every input at the version held, a new
version based on the version held. The request is saved in `held.json` before the proposal and each output's receipt
as soon as it arrives, so running the same send again continues it and never publishes an output twice.

The core module (`exchange.py`) is vendored into the QGIS plug-in and stays unchanged; everything an assistant adds
lives here.
"""
import hashlib
import json
import uuid
from pathlib import Path

from . import exchange
from .agents import NO_RUN, TOOL_RUN_SENTENCES, PlanDeclined, PlanExpired
from .errors import AuthenticationRequired, IntegrityConflict, PermissionRefused, Refused
from .exchange import ClientTransport, Exchange, ExchangeRefused, Outcome, _refusal, display, failure

# The SDK's copy of the gateway's PUBLIC_DERIVE_PROFILES (project_gateway/publications.py): what a run's output may
# publish as a result. test_agent_exchange_send compares the two.
DERIVE_PROFILES = ('points-csv/1', 'mesh-text/1', 'esri-ascii-grid/1', 'well-tops-csv/1', 'deviation-csv/1', 'opendtect-faultsticks/1', 'las2/1',
                   'well-location/1', 'wavelet-text/1', 'model-section-text/1', 'seismic-section-text/1', 'time-depth-csv/1', 'petrel-well-tops/1',
                   'ogc-geopackage/1', 'well-residual/1')
REPORT = 'procedure-runs/report'
UNFINISHED = 'an earlier send from this folder is unfinished: run it again unchanged, or set it aside'
ENTITY_MISSING = 'name a well or wellbore you can read in this project'  # E155 s2: of_entity names one that is missing or not yours to read


def _sent(f):
    """One sentence per output that landed, in today's sent-new / sent-version words."""
    return ' '.join(exchange.SENTENCES['sent-version' if e.get('version') else 'sent-new'](e) for e in f['sent'])


AGENT_SENTENCES = {
    **exchange.SENTENCES,
    'run-needed': lambda f: NO_RUN,  # E166's no-run words, verbatim: one sentence exists for this
    'upload-needed': lambda f: '%s is a file to upload, not a result; an assistant does not send uploads. Nothing was sent.' % f['name'],
    'proposed': lambda f: 'Waiting for approval to send %s. Nothing is published until it is approved; run the same send again to continue.' % f['name'],
    'declined': lambda f: 'The send of %s was declined. Nothing was published.' % f['name'],
    'expired': lambda f: 'The approval to send %s expired. Nothing was published; send it again to ask again.' % f['name'],
    'sent-run': _sent,
    'sent-part': lambda f: '%s %s was not sent: %s' % (f['sent'], f['name'], f['why']),
    'tool-run-refused': lambda f: f.get('sentence') or TOOL_RUN_SENTENCES.get(f.get('reason'), NO_RUN),  # the gateway's own sentence
}
AGENT_OUTCOMES = tuple(AGENT_SENTENCES)

RunNeeded = _refusal('run-needed', Refused)
UploadNeeded = _refusal('upload-needed', Refused)
Declined = _refusal('declined', PlanDeclined)
Expired = _refusal('expired', PlanExpired)
SentPart = _refusal('sent-part', IntegrityConflict)
ToolRunRefused = _refusal('tool-run-refused', PermissionRefused)
AGENT_REFUSALS = {**exchange.REFUSALS, **{c.outcome: c for c in (RunNeeded, UploadNeeded, Declined, Expired, SentPart, ToolRunRefused)}}


class AgentTransport(ClientTransport):
    """`ClientTransport` over `agent.reads`: the same inventory, result history and exact reads, with the agent's
    credential. Who sends is the agent's id from capabilities/describe (asked once per object); nothing is reported."""
    report = None  # activity/report is a person's operation: a receipt's `reported` stays None and nothing is sent
    release = None  # E171 s1: exchange/release is a person's operation too; `release_copy` answers None and sends nothing

    def __init__(self, agent):
        ClientTransport.__init__(self, agent.reads)
        self.agent, self._identity = agent, None

    def identity(self):
        if self._identity is None:
            principal = (self.agent.capabilities() or {}).get('principal') or {}
            ident = (principal.get('agent') or {}).get('id') if principal.get('kind') == 'agent' else None
            if not isinstance(ident, str) or not ident:
                raise AuthenticationRequired('This credential is not an assistant\'s; use the agent credential or the assistant sign-in.')
            self._identity = {'kind': 'agent', 'agent_id': ident}
        return dict(self._identity)


def _named(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 160


class AgentExchange(Exchange):
    """`Exchange` for an assistant: `check`, `fetch`, `get`, `read_exact` and `abandon_pending` as a person's script has
    them; `send` is refused (`run-needed`) and `send_run` sends a tool run's outputs under one approval."""
    def __init__(self, transport, work, *, sentences=None, lock_timeout=3.0, **kw):
        if sentences is not None:
            missing = [code for code in AGENT_OUTCOMES if not callable(sentences.get(code))]
            if missing: raise ValueError('The sentence table has no sentence for: ' + ', '.join(missing))
        Exchange.__init__(self, transport, work, sentences=sentences or AGENT_SENTENCES, lock_timeout=lock_timeout, **kw)

    def _raise(self, code, facts=None, technical=None, error=None):
        facts = facts or {}
        if error is not None:
            technical = dict(technical or {}, code=getattr(error, 'code', None), status=getattr(error, 'status', None),
                             stage=getattr(error, 'stage', None), server_message=getattr(error, 'server_message', None) or str(error))
        raise AGENT_REFUSALS[code](self._say(code, facts), facts, technical) from error

    def send(self, *args, **kwargs):
        """Refused before the folder is locked or anything is sent: an assistant publishes only a tool run's outputs."""
        self._raise('run-needed', {})

    # -- send a tool run ---------------------------------------------------------------------------------------------

    def send_run(self, folder, *, name, of=None, expected=None, of_entity=None, summary='', evidence=None, dry_run=False, wait=True, **wait_kw):
        """Send the outputs of the local run in `folder` (run.json) as one procedure-runs/report the person approves.
        `name` names the results: a string (several outputs read "<name>: <output label>") or {role: name}. `of` is the
        held result an output is a new version of (with several outputs, {role: held id}); `expected` the revision it
        builds on (or {role: revision}), only with `of`. `of_entity` (E155 s2) is the well or wellbore an output is
        about (an entity id, or {role: entity id}; a role left out is about none): read once with entities/get and kept
        with the send, so continuing it reads nothing again. Every input of the run must be held at the version it read.
        Answers `proposed` while the person has not decided (run it again to continue), `sent-run` once every output
        is published, or with `dry_run=True` the report's dry run (nothing saved). Refusals: see AGENT_SENTENCES."""
        from .procedures import AgentRun, NotRun
        agent = self.transport.agent
        folder = Path(folder).expanduser().absolute()
        try: run_bytes = (folder / 'run.json').read_bytes()
        except OSError: raise NotRun('not-a-run') from None
        local = AgentRun(agent, folder, name='results')._record()
        roles = list(local['outputs'])
        for role in roles:  # (a) a file that is not a result is an upload, which an assistant does not send
            if local['outputs'][role].get('profile') not in DERIVE_PROFILES:
                self._raise('upload-needed', {'name': display(local['outputs'][role].get('file'), 'This file')},
                            {'role': role, 'profile': local['outputs'][role].get('profile')})
        of_map, expected_map = self._per_role(of, roles), self._per_role(expected, roles)
        entity_map = self._per_role(of_entity, roles, 'give the well or wellbore by output when the run made several')
        if set(expected_map) - set(of_map):
            self._raise('not-valid', {'reasons': 'name the item this is a new version of, together with the version it builds on'})
        if not (set(name) == set(roles) and all(_named(v) for v in name.values()) if isinstance(name, dict) else _named(name)):
            self._raise('not-valid', {'reasons': 'give the results a name of up to 160 characters, or one name per output'})
        asked = json.loads(json.dumps({'name': name, 'folder': str(folder), 'run_sha256': hashlib.sha256(run_bytes).hexdigest(), 'of': of, 'expected': expected,
                                       **({'of_entity': of_entity} if of_entity is not None else {})}))  # absent when unused: older pending sends continue
        with self._locked():
            record = self._load()
            pending, first = record.get('pending'), False
            if pending:  # (b) continue an existing send, from what it froze
                identity = self.transport.identity()
                facts = {'name': display(pending['request'].get('name'), 'an item')}
                if pending.get('owner') != identity: self._raise('outcome-unknown', {**facts, 'other_key': True})
                if pending.get('kind') != 'run' or {k: v for k, v in pending['request'].items() if k != 'names'} != asked:
                    self._raise('not-valid', {'reasons': UNFINISHED})
            else:  # (c) a new send: bound to the versions this folder holds
                pending = self._new(record, local, roles, of_map, expected_map, asked, name, entity_map)
                first = True
            names = pending['request']['names']
            title = display(name, None) if isinstance(name, str) else None
            facts = {'name': title or ', '.join(display(names[r], 'a result') for r in roles)}
            about = pending['resolved'].get('of_entity') or {}  # E155 s2: as frozen when the send began
            publish = {r: {'name': names[r], 'new_version_of': of_map.get(r), 'expected_parent': pending['resolved']['expected_parent'][r],
                           'of_entity': about.get(r)} for r in roles}
            run = AgentRun(agent, folder, name=name if isinstance(name, str) else names[roles[0]], publish=publish)
            if dry_run:
                request = run.request()
                try: return agent.dry_run(REPORT, request)
                except ExchangeRefused: raise
                except Exception as error: self._transport_error(error, refused='access-refused', facts=facts)
            if first: self._fresh_command(record, folder)  # (d) a fresh attempt after a definitive decline or expiry
            request = run.request()  # AgentRun's own refusals (output-changed) pass through; a kept record stays
            if first:
                pending['command_id'] = request['command_id']
                record['pending'] = pending; self._save(record)  # saved BEFORE anything is sent
            elif request['command_id'] != pending['command_id']:
                self._raise('not-valid', {'reasons': UNFINISHED})
            reported = self._report(agent, request, pending, first, facts, summary, evidence, wait, wait_kw)
            if isinstance(reported, Outcome): return reported
            return self._publish(agent, run, request, reported, pending, roles, of_map, facts)

    def _per_role(self, value, roles, reasons='give the held item and its version by output when the run made several'):
        if value is None: return {}
        if len(roles) == 1 and isinstance(value, str) and value: return {roles[0]: value}
        if isinstance(value, dict) and set(value) <= set(roles) and all(isinstance(v, str) and v for v in value.values()): return dict(value)
        self._raise('not-valid', {'reasons': reasons})

    def _entities(self, entity_map, name):
        """E155 s2: {role: {kind, entity_id}}, each entity read once with entities/get; one that is missing or not the
        person's to read is refused here, before anything is proposed."""
        found = {}
        for ident in dict.fromkeys(entity_map.values()):
            try: doc = self.transport.agent.read('entities/get', {'entity_id': ident})
            except ExchangeRefused: raise
            except Exception as error:
                if getattr(error, 'status', None) in (404, 410): self._raise('not-valid', {'reasons': ENTITY_MISSING}, {'entity_id': ident}, error=error)
                self._transport_error(error, refused='access-refused', facts={'name': display(name, 'the results')})
            if doc.get('kind') not in ('well', 'wellbore'): self._raise('not-valid', {'reasons': ENTITY_MISSING}, {'entity_id': ident})
            found[ident] = {'kind': doc['kind'], 'entity_id': ident}
        return {role: found[ident] for role, ident in entity_map.items()}

    def _new(self, record, local, roles, of_map, expected_map, asked, name, entity_map=None):
        """Steps (c) and the pending record (not saved yet): every check here refuses before any request."""
        held = record['items']
        inputs = [{'asset_id': v['asset_id'], 'revision': v['revision']} for versions in local['inputs'].values() for v in versions]
        for i in inputs:  # the parent is the version the folder holds, never the head
            entry = held.get(i['asset_id'])
            if entry is None or entry.get('revision') != i['revision']:
                self._raise('not-held', {'name': self._name(entry, 'that item')}, {'asset_id': i['asset_id'], 'revision': i['revision']})
        for role, ident in of_map.items():
            if ident not in held: self._raise('not-held', {'name': 'that item'}, {'asset_id': ident})
            if held[ident].get('kind') == 'uploaded': self._raise('upload-needed', {'name': self._name(held[ident])}, {'asset_id': ident})
        for role, revision in expected_map.items():  # before the content check: identical bytes are still refused
            if revision != held[of_map[role]]['revision']: self._raise('newer-version-exists', {'name': self._name(held[of_map[role]])})
        for role, ident in of_map.items():
            if local['outputs'][role]['sha256'] == held[ident].get('revision'):
                self._raise('nothing-changed', {'name': self._name(held[ident]), 'number': held[ident].get('number')})
        identity = self.transport.identity()
        names = self._names(name, roles, local)
        resolved = {'inputs': inputs, 'expected_parent': {r: held[of_map[r]]['revision'] if r in of_map else None for r in roles}}
        if entity_map: resolved['of_entity'] = self._entities(entity_map, name)  # frozen: a resumed send never reads it again
        return {'kind': 'run', 'command_id': None, 'request': {**asked, 'names': names}, 'resolved': resolved, 'owner': identity, 'started': self.clock(),
                'plan': None, 'evidence': None, 'receipts': {}, 'refused': None}

    def _names(self, name, roles, local):
        """Explicit names for every output: several outputs read "<name>: <the manifest's output label>", never a role id."""
        if isinstance(name, dict): return {r: name[r] for r in roles}
        if len(roles) == 1: return {roles[0]: name}
        try: manifest = self.transport.agent.read('procedures/get', {'digest': local['procedure']['digest']})['manifest']
        except ExchangeRefused: raise
        except Exception as error: self._transport_error(error, refused='access-refused', facts={'name': display(name, 'the results')})
        labels = {o.get('role'): o.get('label') for o in manifest.get('outputs') or []}
        return {r: ('%s: %s' % (name, labels[r] if _named(labels.get(r)) else 'result %d' % i))[:160] for i, r in enumerate(roles, 1)}

    def _fresh_command(self, record, folder):
        from .procedures import AgentRun, _save
        path = folder / AgentRun.STATE
        try: state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return
        if state.get('command_id') in (record.get('closed_runs') or []):
            _save(path, {**state, 'command_id': 'run-' + uuid.uuid4().hex})

    def _keep(self, pending):
        record = self._load(); record['pending'] = pending; self._save(record)

    def _close(self, pending):
        """A definitive decline or expiry: the plan can never run; the next send is a fresh attempt (a new command id)."""
        record = self._load(); record['pending'] = None
        record['closed_runs'] = sorted(set(record.get('closed_runs') or []) | {pending['command_id']})
        self._save(record)

    def _report(self, agent, request, pending, first, facts, summary, evidence, wait, wait_kw):
        """(e) propose (once: a lost answer proposes the same request again, the same plan), wait, execute the report."""
        try:
            if pending.get('plan') is None:
                proposed = agent.propose(REPORT, request, summary, evidence=evidence)
                pending['plan'], pending['evidence'] = proposed['hash'], proposed.get('evidence') if evidence is not None else None
                self._keep(pending)
            plan = pending['plan']
            try: agent.wait(plan, evidence_id=pending['evidence'], **dict(wait_kw, **({} if wait else {'timeout': 0})))
            except PlanExpired as ended:
                if ended.code == 'plan-pending':
                    return Outcome('proposed', self._say('proposed', facts), facts, {'plan': plan, 'command_id': pending['command_id']})
                self._close(pending); self._raise('expired', facts, {'plan': plan, 'command_id': pending['command_id']})
            except PlanDeclined:
                self._close(pending); self._raise('declined', facts, {'plan': plan, 'command_id': pending['command_id']})
            return agent.execute(REPORT, request, plan, pending['evidence'])
        except ExchangeRefused: raise
        except Exception as error:
            if getattr(error, 'code', None) == 'tool-run-refused':  # E166 at the report: nothing ran, nothing is kept
                self._clear(); self._tool_refused(error, facts)
            kind = failure(error)
            if kind == 'could-not-reach': self._raise('outcome-unknown', facts, {'command_id': pending['command_id']}, error=error)
            if first and pending.get('plan') is None and kind != 'rate-limited': self._clear()  # refused before anything was kept
            self._transport_error(error, refused='access-refused', facts=facts)

    def _tool_refused(self, error, facts):
        reason = (getattr(error, 'details', None) or {}).get('reason')
        self._raise('tool-run-refused', {**facts, 'sentence': getattr(error, 'server_message', None) or str(error).split('\n')[0], 'reason': reason},
                    {'reason': reason}, error=error)

    def _landed(self, pending, role, receipt):
        """A published output: its receipt in the pending record and the folder holding it, before the next step runs."""
        number = receipt.get('revision_number', receipt.get('number'))
        pending['receipts'][role] = {'asset_id': receipt['asset_id'], 'revision': receipt['revision'], 'number': number}
        record = self._load()
        record['items'][receipt['asset_id']] = {'asset_id': receipt['asset_id'], 'name': pending['request']['names'][role], 'kind': 'derived',
                                                'revision': receipt['revision'], 'number': number, 'got_at': self.clock(), 'sent': True, 'output': None,
                                                **exchange._kept(record['items'].get(receipt['asset_id']))}  # E173 s0: note, words, mode
        record['pending'] = pending
        self._save(record)

    def _said(self, pending, roles, of_map):
        return [{'name': display(pending['request']['names'][r], 'the result'), 'number': pending['receipts'][r]['number'], 'version': r in of_map}
                for r in roles if r in pending['receipts']]

    def _publish(self, agent, run, request, reported, pending, roles, of_map, facts):
        """(f) each output once, in the report's order, its receipt saved as it arrives; (g) the send ends."""
        from .procedures import NotRun
        plan, order = pending['plan'], [o['role'] for o in reported['outputs']]
        for o in reported['outputs']:
            if o.get('outcome') is not None and o['role'] not in pending['receipts']: self._landed(pending, o['role'], o['receipt'])
        if pending.get('refused') is not None: pending['refused'] = None; self._keep(pending)  # a repeat retries the rest
        try: steps = run.steps(request, reported)
        except (ExchangeRefused, NotRun): raise
        except Exception as error: self._step_failed(error, pending, None, None, of_map, order)
        for role, (header, raw) in steps.items():
            if role in pending['receipts']: continue
            try: receipt = agent.execute_step('publications/derive', header, plan, pending['evidence'], raw=raw)
            except Exception as error: self._step_failed(error, pending, role, raw, of_map, order)
            self._landed(pending, role, receipt)
        record = self._load(); record['pending'] = None; self._save(record)
        sent = self._said(pending, order, of_map)
        outputs = [{'role': r, **pending['receipts'][r]} for r in order]
        return Outcome('sent-run', self._say('sent-run', {'sent': sent}), {'sent': sent}, {'plan': plan, 'run_id': reported['run_id'], 'outputs': outputs})

    def _step_failed(self, error, pending, role, raw, of_map, order):
        """A step that did not publish: the record is kept; with outputs already sent, the answer says what was sent."""
        names = pending['request']['names']
        facts = {'name': display(names[role], 'the result') if role else display(pending['request'].get('name'), 'the results')}
        try:
            if getattr(error, 'code', None) == 'tool-run-refused': self._tool_refused(error, facts)
            kind = failure(error)
            if kind == 'stale' and role is not None: self._stale(error, of_map.get(role), raw, facts)
            if kind == 'could-not-reach': self._raise('outcome-unknown', facts, {'command_id': pending['command_id']}, error=error)
            self._transport_error(error, refused='access-refused', facts=facts)
        except ExchangeRefused as refusal:
            if role is None or refusal.outcome == 'outcome-unknown': raise
            pending['refused'] = {'role': role, 'outcome': refusal.outcome}; self._keep(pending)
            if not pending['receipts']: raise
            sent = self._say('sent-run', {'sent': self._said(pending, order, of_map)})
            part = {'sent': sent, 'name': facts['name'], 'why': refusal.sentence}
            self._raise('sent-part', part, {'refused': pending['refused'], 'command_id': pending['command_id'],
                                            'outputs': [{'role': r, **pending['receipts'][r]} for r in order if r in pending['receipts']]})
