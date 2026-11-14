"""An agent's side of Ophiolite (E5): propose exact changes, wait for approval, execute, recover.

An agent credential (`oph_agent_…`) is issued by a person in Workspace Settings → Agents and
acts for that person with narrower scopes, budgets and an expiry. Reads work directly. Every
change is proposed first; the gateway hashes the exact request, the person (or their policy)
approves it, and the agent then executes that same request with the plan. If the response is
lost, `recover()` returns what was recorded; executing the same plan again returns the same
response and never runs twice.

E95: `propose(..., evidence=...)` records what the person asked, the model the agent says it used
and where its conversation lives; the person approves the plan naming that record, and `execute`
sends its id as `X-Ophiolite-Evidence`. The reported provider and model are also set on the
caller's current OpenTelemetry span (`ophiolite._genai`); the instruction never is.

    agent = AgentClient('https://ophiolite.example', 'project-id', credential)
    run = agent.run('applications/start', {'id': binding, 'generation': 1, 'command_id': 'run-1',
                                           'application_version': 'my-script/1'},
                    evidence={'instruction': 'Tidy the gamma ray of HON-GT-01.', 'client': 'well-tidy/0.3',
                              'model': {'provider': 'anthropic', 'id': 'claude-sonnet-5-5'},
                              'conversation': {'kind': 'notebook', 'reference': 'thread-4471'}})

E151 s2: a job is one to eight steps `{operation, body}` under one approval. `run_job` proposes them, waits for the
person and runs each step in order; a body value `{"$step": k, "pointer": "/id"}` is part of step k's answer. A step
that needs the person's decision raises `ChoiceRequired` carrying `plan` and `step`. The person answers in the
Workspace or with their own `Client.answer(choice_token, choice)` (`Client.proposals()` lists what waits for them; an
agent credential is refused on both). Then `resume(plan)` replays the completed steps by their command ids
(`uuid5(NAMESPACE, 'plan:step')`, the same in every process) and runs the rest, in this process or a restarted one:

    steps = [{'operation': 'applications/configure', 'body': {'name': 'Gamma correction', 'asset_id': asset,
              'asset_revision': revision, 'curve': 'GR', 'runners': [me], 'command_id': 'cfg-1'}},
             {'operation': 'applications/start', 'body': {'id': {'$step': 1, 'pointer': '/id'},
              'generation': {'$step': 1, 'pointer': '/generation'}, 'command_id': 'run-1',
              'application_version': 'my-script/1'}}]
    try: answers = agent.run_job(steps)
    except ChoiceRequired as asked: answers = agent.resume(asked.plan)  # once the person has answered

A malformed list or a step naming another project raises `Refused` before any request; which operations a job may
run is the gateway's decision. `job(job_id)` is the runner-job reader (E13), and `CHANGES` names single proposals only.

E150 s1: `dry_run(operation, request)` asks what the request would do before proposing it; nothing is kept and no plan
is made. The answer (`DryRun`, ophiolite.agent-dry-run/1) says `would.outcome` ('proceeds' with `would.effects`, or
'refused' with the operation's own `would.refusal`) and a `digest` naming exactly that dry run:

    seen = agent.dry_run('applications/start', {'id': binding, 'generation': 1, 'command_id': 'run-1',
                                                'application_version': 'my-script/1'})
    for effect in seen.would.effects: print(effect.action, effect.count, effect.kind)
"""
import copy
import time
import uuid
from typing import Annotated, List, Literal, Optional
import httpx
from pydantic import BaseModel, ConfigDict, Field
from . import _client_header  # E93
from . import _deprecation  # E148
from . import _genai  # E95
from .errors import (OphioliteError, AuthenticationRequired, PermissionRefused, Unavailable, IntegrityConflict,
                     Refused, Busy, ChoiceRequired, VerificationFailed)

CHANGES = ('applications/configure', 'applications/start', 'applications/publish', 'applications/share', 'runners/submit', 'runners/cancel',
           'results/remake-run',  # E94: run an approved calculation again; a person saves
           'procedures/register', 'procedure-runs/report',  # E111: a private version of exact bytes; a run whose outputs publish under its approval
           'upload-runs/start',  # E111 s2 (P-10): one file read with a procedure; its file, convert and output steps run under this approval
           'outcomes/deliver-as', 'procedures/trust',  # E111 s4b (R4-10): a delivery as an outcome; trust in exactly one procedure version
           'verdicts/record',  # E132 s3: a verdict on exactly one result version, for the agent's person
           'publications/share',  # E149 s1: the server admitted it; the declarations say so (test_agent_changes)
           'table-imports/preview', 'table-imports/start', 'table-imports/step', 'well-names/accept',  # E153 s1: a table import's steps
           'well-imports/preview', 'well-imports/start', 'well-imports/step',  # E153 s1b: a database table's import
           'sources/mapping-save', 'layouts/save', 'layouts/keep',  # E153 s1b: the saves of picks the person settled
           'org-connections/request', 'org-connections/request-withdraw',  # E154 s0: a secret-free request for its person; withdraw its own
           'sources/bind')  # E154 s1: a link job's last step; the person confirms the link, the source is kept at the reviewed version
# E153 s1: table-imports/read is proposable, but its bytes go with a job (propose_job / run_job files=), never a single proposal.

# E166 s0 (D3): the gateway's tool-run-refused sentences (reason -> sentence, in its order), the SDK's one copy; E155 and
# other callers import these, never the words from errors.py. {delegator} is filled with the display name of the
# person the assistant acts for. test_tool_run_sentences (gateway) holds this literal equal to the gateway's.
TOOL_RUN_SENTENCES = {'no-run': 'No tool ran this: an assistant publishes a result only as a step of a tool run it reported.',
                      'not-trusted': 'The tool version this run names is not trusted by {delegator}.',
                      'withdrawn': 'The tool version this run names is withdrawn.',
                      'not-verified': 'The tool version this run names is not verified.',
                      'import-as-run': 'An import is source data, not a tool run.'}
NO_RUN = TOOL_RUN_SENTENCES['no-run']

JOB_STEPS = 8  # E151 s2: the jobs/propose request states one to eight steps, each {operation, body}
NAMESPACE = uuid.UUID('f527b633-0784-5370-8bbf-06ac165826a8')  # E151 s2: published; a step's command id is uuid5(NAMESPACE, 'plan:step')
FILE_STEPS = frozenset({'table-imports/read'})  # E153 s1: job steps whose bytes go to their own route (X-Ophiolite-Job-Step)


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class JobChoice(_Strict):
    """E151 s2: one offered choice of a waiting job (job-schema.json $defs/choice)."""
    id: Annotated[str, Field(pattern=r'^c[1-8]$')]
    fragment: Annotated[dict, Field(max_length=16)]


class JobStep(_Strict):
    """E151 s2: one step of a job as jobs/status shows it (job-schema.json $defs/step)."""
    operation: Annotated[str, Field(pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$')]
    state: Literal['pending', 'reserved', 'completed']
    answer_sha256: Optional[Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]]


class JobStatus(_Strict):
    """E151 s2: the answer of jobs/status, mirroring the synced ophiolite.agent-job/1 (job-schema.json); the optional
    fields may be absent, never null. Checked without the optional `validation` extra (tests/test_agent_jobs_sdk.py)."""
    plan: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    state: Literal['pending', 'declined', 'expired', 'running', 'waiting', 'completed', 'released', 'failed']
    step: Annotated[int, Field(ge=1, le=JOB_STEPS)]
    word: Annotated[str, Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')] = None
    question: Annotated[str, Field(min_length=1, max_length=300)] = None
    choices: Annotated[List[JobChoice], Field(min_length=2, max_length=8)] = None
    choice_token: Annotated[str, Field(pattern=r'^ct1\.[A-Za-z0-9_-]{43}$')] = None
    steps: Annotated[List[JobStep], Field(min_length=1, max_length=JOB_STEPS)]
    review_url: Annotated[str, Field(min_length=1, max_length=2048)]


class DryEffect(_Strict):
    """E150 s1: one effect the real call would have (dry-run-schema.json $defs/effect)."""
    action: Literal['create', 'change', 'remove']
    kind: Annotated[str, Field(pattern=r'^[a-z][a-z-]{0,31}$')]
    count: Annotated[int, Field(ge=1, le=100000)]
    label: Annotated[str, Field(min_length=1, max_length=200)] = None


class DryRefusal(_Strict):
    """E150 s1: the operation's own refusal, answered inside `would` (dry-run-schema.json $defs/refusal)."""
    code: Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
    message: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')] = None


class DryWould(_Strict):
    outcome: Literal['proceeds', 'refused']
    effects: Annotated[List[DryEffect], Field(max_length=64)]
    refusal: DryRefusal = None


class DryRun(_Strict):
    """E150 s1: the answer of a dry run, mirroring the synced ophiolite.agent-dry-run/1 (dry-run-schema.json). `would`
    is what the same request would do; nothing was kept. `digest` names exactly this dry run."""
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)
    schema_: Literal['ophiolite.agent-dry-run/1'] = Field(alias='schema')
    dry_run: Literal[True]
    operation: Annotated[str, Field(pattern=r'^[a-z0-9-]+/[a-z0-9-]+$', max_length=128)]
    project_id: Annotated[str, Field(min_length=1, max_length=200)]
    would: DryWould
    digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class PlanDeclined(OphioliteError): code = 'plan-declined'
class PlanExpired(OphioliteError): code = 'plan-expired'
class BudgetExhausted(OphioliteError): code = 'budget-exhausted'
class CommandOwned(IntegrityConflict): code = 'command-owned'


class _AgentAuth:
    """E111 s4a (D-A3): the `Client` credential of `AgentClient.reads`: the agent's headers, asked again on every request."""
    def __init__(self, agent):
        self.agent = agent

    def headers(self, url, project):
        return dict(self.agent._auth())


class AgentClient:
    def __init__(self, base_url, project, credential, *, http=None):
        """`credential` is an agent key (`oph_agent_…`) or, for an assistant acting through your own
        sign-in, the saved credential from `device_login(..., assistant='name')`."""
        from .auth import Credential
        self.url, self.project = base_url.rstrip('/'), project
        self.http = http or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
        self._notifier = _deprecation.Notifier()  # E148: shared with `reads`, so a route warns once for both
        if isinstance(credential, Credential):
            self._credential, self._headers = credential, None
        elif isinstance(credential, str) and credential.startswith('oph_agent_'):
            self._credential, self._headers = None, {'Authorization': 'Bearer ' + credential}
        else:
            raise AuthenticationRequired('Use the agent credential shown once in Settings → Agents, or an assistant sign-in.')

    def _auth(self):
        return self._credential.headers(self.url, self.project) if self._credential else self._headers

    @property
    def reads(self):
        """E111 s4a (D-A3): a read-only `Client` acting with this agent's credential, so `residuals.prepare(agent, ...)`
        and `agent.well_sets.bind` read as for a person; the gateway decides as the agent's person within its project and
        read scope. Every request asks `_auth()` again (an assistant sign-in is refreshed); a write it sends is refused."""
        if getattr(self, '_reads', None) is None:
            from .client import Client
            self._reads = Client(self.url, self.project, credential=_AgentAuth(self), http=self.http)
            self._reads._notifier = _deprecation.of(self)  # E148: one warning per route for the agent and its reads
        return self._reads

    @property
    def well_sets(self):
        """E111 s4a: read and check your person's well sets (`ophiolite.well_sets.WellSets`; read and bind)."""
        return self.reads.well_sets

    def read_data(self, asset, revision):
        """E111 s4a: an exact version, as `Client.read_data` reads it."""
        return self.reads.read_data(asset, revision)

    def exchange(self, work, *, sentences=None, lock_timeout=3.0):
        """E155 s0: check for updates and get latest in the work folder `work` with this agent's credential
        (`ophiolite.agent_exchange.AgentExchange`). Its `send` asks for a tool run: an assistant publishes a result only as
        a step of a run it reported."""
        from .agent_exchange import AgentExchange, AgentTransport
        return AgentExchange(AgentTransport(self), work, sentences=sentences, lock_timeout=lock_timeout)

    def _entities(self, operation, body):
        return self.reads._entities(operation, body)

    def _download_version(self, *args, **kwargs):
        return self.reads._download_version(*args, **kwargs)

    def _post(self, area, operation, body, plan=None, evidence=None, raw=None, job_step=None):
        headers = _client_header.stamp({**self._auth(), **({'X-Ophiolite-Plan': plan} if plan else {}),
                                        **({'X-Ophiolite-Evidence': evidence} if evidence else {}),  # E93; E95
                                        **({'X-Ophiolite-Job-Step': job_step} if job_step else {})})  # E153 s1: a job's file step
        url = '%s/api/v1/projects/%s/%s/%s' % (self.url, self.project, area, operation)
        try:
            if raw is None:
                response = self.http.post(url, json={'project_id': self.project, **body}, headers=headers)
            else:  # E111: an octet-stream step; its request travels whole in X-Ophiolite-Upload, as publications/derive reads it
                import base64
                from .publish import json_bytes
                upload = base64.b64encode(json_bytes({'project_id': self.project, **body})).decode()
                response = self.http.post(url, content=raw, headers={**headers, 'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': upload})
        except httpx.HTTPError:
            raise Unavailable('Cannot reach the service. Check its address and network connection.', code='unreachable') from None
        _deprecation.note(_deprecation.of(self), 'POST', url, response)
        if response.status_code == 200: return response.json()
        from .application_transport import envelope, carried, WORDS
        meta = envelope(response)  # E31: bounded, and the server's remedy, docs and request id travel on
        code, message = meta.get('code', ''), meta.get('message') or 'The request was refused.'
        kind = {'budget-exhausted': BudgetExhausted, 'command-owned': CommandOwned, **WORDS}.get(code)  # E150: a choice, the dry-run words
        if kind is None:
            kind = {401: AuthenticationRequired, 403: PermissionRefused, 404: Unavailable, 409: IntegrityConflict,
                    429: BudgetExhausted, 503: Busy}.get(response.status_code, Refused)
        raise kind(message, meta.get('remedy', ''), status=response.status_code, code=code or None, **carried(meta))

    def read(self, operation, body=None):
        """A read operation such as 'applications/result-list'; reads need no plan."""
        area, name = operation.split('/', 1)
        return self._post(area, name, body or {})

    def procedure_fetch(self, digest, *, cache=None):
        """E155 s2 (C4): the checked local folder of the tool version `digest`, fetched with this agent's key. Before
        any bundle bytes it refuses, in the gateway's tool-run order, what a run of it would be refused for: a read or
        source step (`import-as-run`), withdrawn, not verified (`agent_exchange.ToolRunRefused`), and a version not
        enabled yet (`procedures.NotRun('not-enabled')`). A version the agent cannot see answers as the server does
        (not found). Trust is the person's and is asked at the send (`send_run`'s `not-trusted`), never here."""
        from .agent_exchange import ToolRunRefused
        from .procedures import NotRun, _AgentCatalogue
        found = self.read('procedures/get', {'digest': digest})
        reason = ('import-as-run' if (found.get('manifest') or {}).get('step') in ('read', 'source') else
                  'withdrawn' if found.get('state') == 'withdrawn' else None)
        if reason is None and found.get('state') != 'enabled': raise NotRun('not-enabled', '', {'digest': digest})
        if reason is None and (found.get('verification') or {}).get('state') != 'verified': reason = 'not-verified'
        if reason is not None:
            sentence = TOOL_RUN_SENTENCES[reason]
            raise ToolRunRefused(sentence, {'sentence': sentence, 'reason': reason}, {'reason': reason, 'digest': digest})
        return _AgentCatalogue(self)._cached(digest, cache)

    def capabilities(self):
        """What this agent may ask for: every operation with eligibility, whether it needs a plan,
        the agent's scopes, budgets (used by the admission rule) and expiry, and the MCP endpoint."""
        return self._post('capabilities', 'describe', {})

    def mcp_settings(self):
        """The address and header an MCP client needs to use this agent key over the remote MCP endpoint.
        (An assistant's MCP client signs in itself; its access token expires and is refreshed by that client.)"""
        if self._headers is None: raise Refused('An assistant\'s MCP client signs in itself; no key is handed over.')
        return mcp_settings(self.url, self._headers['Authorization'][7:])

    def propose(self, operation, request, summary='', *, evidence=None, dry_run=None):
        """Propose the exact request. `evidence` (E95), when given: `instruction` (what the person asked, as you received
        it), `model` ({provider, id, label?}), `conversation` ({kind, reference, label?}) and `client` (product/version).
        The answer's `evidence` is the record's id; pass it to `wait` and `execute`. `dry_run` (E150 s1b): the `DryRun`
        of this same request, or its digest, sent in the evidence so the person sees what it would do; the gateway runs
        it again and refuses `stale` (DryRunRefused) when the answer changed. It needs `evidence`."""
        if operation not in CHANGES: raise Refused('Agents change application configurations, runs, publications, recipients, runner jobs, recalculations, procedure runs, deliveries as an outcome, trust in a procedure version, verdicts on a result, table imports, table mappings, layouts and requests for an organization database only.')
        if dry_run is not None: evidence = self._with_dry_run(operation, evidence, dry_run)
        body = {'operation': operation, 'request': {'project_id': self.project, **request}, 'summary': summary}
        if evidence is not None:
            body['evidence'] = evidence
            _genai.annotate(evidence)
        return self._post('agents', 'propose', body)

    def _with_dry_run(self, operation, evidence, dry_run):
        """A copy of `evidence` naming the dry run (the caller's dict is never changed)."""
        import re
        if evidence is None: raise ValueError('A dry run is named in the evidence: pass evidence with dry_run.')
        if isinstance(dry_run, DryRun):
            if (dry_run.operation, dry_run.project_id) != (operation, self.project): raise ValueError('The dry run names another operation or project.')
            named = dry_run.digest
        else: named = dry_run
        if not (isinstance(named, str) and re.fullmatch('[0-9a-f]{64}', named)): raise ValueError('dry_run: a DryRun or its 64-character digest.')
        if evidence.get('dry_run') not in (None, named): raise ValueError('The evidence already names another dry run.')
        return {**evidence, 'dry_run': named}

    def dry_run(self, operation, request, *, raw=None):
        """E150 s1: what `operation` with `request` would do, kept nowhere, as a `DryRun`; no proposal, no plan. With `raw`
        (an octet-stream operation such as publications/derive) the bytes travel as the real call sends them. A refusal
        of the operation's own (a stale generation, a bad value) is `would.refusal`; a right the real call would refuse,
        or an operation with no dry run here (`DryRunUnavailable`), is raised as that error."""
        area, name = operation.split('/', 1)
        answer = self._post(area, name, {**request, 'dry_run': True}, raw=raw)
        from pydantic import ValidationError
        try: dry = DryRun.model_validate(answer)
        except ValidationError: raise VerificationFailed('The dry run does not satisfy ophiolite.agent-dry-run/1.') from None
        if (dry.operation, dry.project_id) != (operation, self.project): raise VerificationFailed('The dry run names another operation or project.')
        return dry

    def status(self, plan):
        return self._post('agents', 'status', {'hash': plan})['state']

    def wait(self, plan, *, evidence_id=None, timeout=3600, interval=5, clock=time.monotonic, sleep=time.sleep):
        """Until the person decides: returns on approval, raises when declined or expired. With `evidence_id` (E95) it
        returns only once the approval names that record: a plan approved with earlier evidence keeps waiting."""
        return self._decided(plan, evidence_id=evidence_id, timeout=timeout, interval=interval, clock=clock, sleep=sleep)['state']

    def _decided(self, plan, *, evidence_id=None, timeout=3600, interval=5, clock=time.monotonic, sleep=time.sleep):
        """`wait`'s loop; answers the approving `agents/status` answer (E151 s2: `resume` reads its evidence id)."""
        deadline = clock() + timeout
        while True:
            answer = self._post('agents', 'status', {'hash': plan})
            state = answer['state']
            if state in ('approved', 'consumed') and (evidence_id is None or answer.get('evidence_approved') == evidence_id): return answer
            if state == 'consumed': raise IntegrityConflict('The plan already ran with other evidence; propose again.', code='evidence-superseded')
            if state == 'declined': raise PlanDeclined('The person declined this plan.')
            if state == 'expired': raise PlanExpired('The plan expired before a decision; propose it again.')
            if clock() >= deadline: raise PlanExpired('No decision within the wait; the plan stays pending.', code='plan-pending')
            sleep(interval)

    def execute(self, operation, request, plan, evidence=None):
        """Execute the approved plan; `evidence` is the record id `propose` answered (sent as X-Ophiolite-Evidence)."""
        area, name = operation.split('/', 1)
        return self._post(area, name, request, plan, evidence)

    def execute_step(self, operation, request, plan, evidence=None, *, raw=None):
        """E111: one step an approved plan covers (a report's `publications/derive` per output), sent under the parent
        plan: JSON, or with `raw` the file's bytes and the request in X-Ophiolite-Upload. The request must equal the step
        the approval names, field for field; sending it again answers the recorded receipt and never runs twice."""
        area, name = operation.split('/', 1)
        return self._post(area, name, request, plan, evidence, raw)

    def run(self, operation, request, summary='', *, evidence=None, **wait):
        """Propose, wait for approval, execute. Safe to repeat: the same request is the same plan."""
        proposed = self.propose(operation, request, summary, evidence=evidence)
        record = proposed.get('evidence') if evidence is not None else None
        self.wait(proposed['hash'], evidence_id=record, **wait)
        return self.execute(operation, request, proposed['hash'], record)

    def job(self, job_id):
        """A runner job (E13): state, reason, limits, bounded logs and the published result."""
        return self._post('runners', 'job', {'id': job_id})

    def recover(self, *, command_id=None, plan=None):
        """The recorded outcome of an execution whose response was lost."""
        if bool(command_id) == bool(plan): raise Refused('Name either the command id or the plan.')
        return self._post('agents', 'command', {'command_id': command_id} if command_id else {'plan': plan})

    # --- E151 s2: jobs, several steps under one approval -------------------------------------------------------------

    def propose_job(self, steps, *, evidence=None, files=None):
        """Propose a job: 1 to 8 steps `{operation, body}`, run in order under one approval. A body value
        `{"$step": k, "pointer": "/..."}` is part of earlier step k's answer. Each body is copied and names this client's
        project (`project_id` is added when absent); a step naming another project, or a malformed list, is refused here
        (`Refused`, a `ValueError`) before any request. Which operations a job may run is the gateway's decision, in its
        words. `evidence` as for `propose`; the answer's `evidence` is the record's id. `files` (E153 s1): `{step: bytes}`
        for each file step (`table-imports/read`), whose body gains the file's `bytes` and `sha256`; a file step without
        its bytes, or whose body names other bytes, is refused here."""
        body = {'steps': self._job_steps(steps, files)}
        if evidence is not None:
            body['evidence'] = evidence
            _genai.annotate(evidence)
        proposed = self._post('jobs', 'propose', body)
        self._file_steps[proposed['hash']] = {i: s['body'] for i, s in enumerate(body['steps'], 1) if s['operation'] in FILE_STEPS}
        return proposed

    @property
    def _file_steps(self):  # E153 s1: the approved bodies of this process's file steps, by plan, for resume
        return self.__dict__.setdefault('_job_files', {})

    def _job_steps(self, steps, files=None):
        if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= JOB_STEPS:
            raise Refused('A job has 1 to %d steps.' % JOB_STEPS)
        copied = []
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict) or not isinstance(step.get('operation'), str) or not isinstance(step.get('body'), dict):
                raise Refused('Step %d is {operation, body}, with the body an object.' % i)
            step = copy.deepcopy(step)  # the caller's dicts are never changed
            if step['body'].setdefault('project_id', self.project) != self.project:
                raise Refused('Step %d names another project; a job runs in this client\'s project only.' % i)
            if step['operation'] in FILE_STEPS: self._name_file(i, step['body'], (files or {}).get(i))
            copied.append(step)
        return copied

    @staticmethod
    def _name_file(i, body, raw):
        """E153 s1: a file step's body names its bytes by size and sha256 (the gateway compares both with what is sent)."""
        import hashlib
        if not isinstance(raw, (bytes, bytearray)) or not raw: raise Refused('Step %d reads a file: pass its bytes as files={%d: ...}.' % (i, i))
        named = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        for key, value in named.items():
            if body.setdefault(key, value) != value: raise Refused('Step %d names other bytes than the file passed for it (%s).' % (i, key))

    def job_status(self, plan):
        """The job's state, step by step (ophiolite.agent-job/1), checked against the synced schema: `state`, the `step`
        it stands at, a `word` when released or failed, each step's state and answer digest, a waiting job's question,
        and `review_url`, the page where the person reviews it."""
        answer = self._post('jobs', 'status', {'plan': plan})
        from pydantic import ValidationError
        try: JobStatus.model_validate(answer)
        except ValidationError: raise VerificationFailed('The job status does not satisfy ophiolite.agent-job/1.') from None
        if answer.get('plan') != plan: raise VerificationFailed('The job status names another plan.')
        return answer

    def step(self, plan, step, *, evidence_id=None, command_id=None):
        """Run step `step` (from 1) of the approved job `plan`; a completed step answers its recorded answer again and
        writes nothing. `command_id` defaults to `uuid5(NAMESPACE, f'{plan}:{step}')`, the same in every process, so a
        lost response is retried, and a restarted process resumes, with the same id. `evidence_id` is sent as
        X-Ophiolite-Evidence. A step needing the person's decision raises `ChoiceRequired` with `plan` and `step` set."""
        command = command_id or str(uuid.uuid5(NAMESPACE, '%s:%s' % (plan, step)))
        try:
            return self._post('jobs', 'step', {'plan': plan, 'step': step, 'command_id': command}, evidence=evidence_id)
        except ChoiceRequired as asked:
            asked.plan, asked.step = plan, step
            raise

    def run_job(self, steps, *, evidence=None, files=None, **wait):
        """Propose the steps, wait for the person's approval (`wait`'s keywords), run each step in order and return
        their answers. Safe to repeat: the same steps are the same plan, and completed steps answer again. Raises
        `ChoiceRequired` (with `plan` and `step`) when a step needs the person's decision; answer it, then `resume(plan)`.
        `files` (E153 s1): `{step: bytes}` for each file step, as for `propose_job`; a missing file raises before any request."""
        proposed = self.propose_job(steps, evidence=evidence, files=files)
        record = proposed.get('evidence') if evidence is not None else None
        self.wait(proposed['hash'], evidence_id=record, **wait)
        return self._job_run(proposed['hash'], record, files)

    def resume(self, plan, *, files=None, **wait):
        """Carry on with the job `plan`, after a choice, a timeout or a restart: wait while it is pending, then replay its
        completed steps by their ids and run the rest; returns every step's answer in order. A completed step whose
        answer was never stored raises `CommandOwned`; the SDK cannot recover that answer. A file step that has not run
        needs its bytes in `files` and its body from this process's `propose_job`; after a restart, call `run_job` with
        the same steps and files instead (the same plan)."""
        approved = self._decided(plan, **wait)
        return self._job_run(plan, approved.get('evidence_approved'), files)

    def _job_run(self, plan, evidence, files=None):
        status = self.job_status(plan)
        state, word = status['state'], status.get('word')
        if 'declined' in (state, word): raise PlanDeclined('The person declined this job.')
        if 'expired' in (state, word): raise PlanExpired('The job expired before it finished; propose it again.')
        if state in ('released', 'failed'):
            kind = {'command-owned': CommandOwned, 'budget-exhausted': BudgetExhausted}.get(word, Refused)
            raise kind('The job %s at step %d (%s).' % (state, status['step'], word), code=word)
        sending = {}  # E153 s1: each file step still to run, checked before any step request
        for i, s in enumerate(status['steps'], 1):
            if s['operation'] not in FILE_STEPS or s['state'] == 'completed': continue
            body, raw = self._file_steps.get(plan, {}).get(i), (files or {}).get(i)
            if body is None: raise Refused('Step %d reads a file this process did not propose; call run_job with the same steps and files.' % i)
            self._name_file(i, dict(body), raw)
            sending[i] = (s['operation'], body, raw)
        answers = []
        for i in range(1, len(status['steps']) + 1):
            if i in sending: answers.append(self.send_file_step(plan, i, *sending[i], evidence_id=evidence))
            else: answers.append(self.step(plan, i, evidence_id=evidence))  # a completed step replays
        return answers

    def send_file_step(self, plan, step, operation, body, raw, *, evidence_id=None, command_id=None):
        """E153 s1: run file step `step` of the approved job `plan` on its own route: `raw` with `body` (the approved
        step's, naming the bytes) in X-Ophiolite-Upload and X-Ophiolite-Job-Step "<step> <command_id>"; the command id
        is the one `step` uses, so a completed step answers its stored answer again."""
        command = command_id or str(uuid.uuid5(NAMESPACE, '%s:%s' % (plan, step)))
        area, name = operation.split('/', 1)
        return self._post(area, name, {k: v for k, v in body.items() if k != 'project_id'}, plan, evidence_id, bytes(raw), '%d %s' % (step, command))


def mcp_settings(base_url, credential):
    """MCP client settings for an agent credential: the streamable HTTP endpoint and its header.
    The credential is sent to that endpoint only; keep the returned value as secret as the key."""
    if not isinstance(credential, str) or not credential.startswith('oph_agent_'):
        raise AuthenticationRequired('Use the agent credential shown once in Settings → Agents.')
    url = base_url.rstrip('/')
    if not url.startswith('https://') and not url.startswith(('http://127.0.0.1', 'http://localhost', 'http://[::1]')):
        raise Refused('Use the HTTPS address of the service (plain HTTP only for this computer).')
    return {'url': url + '/mcp', 'transport': 'streamable-http', 'headers': {'Authorization': 'Bearer ' + credential}}
