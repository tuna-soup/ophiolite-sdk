# Ophiolite SDK guide

The reference that was the SDK README. Stability, compatibility and qualification statements are in
[CONTRACTS.md](../CONTRACTS.md).

## Install and read

Python 3.10 or later is required. Install from a reviewed commit of this repository:

```sh
python -m pip install 'git+https://github.com/tuna-soup/ophiolite-sdk@<reviewed-commit>'
```

Once a release is published, the same SDK is on PyPI under the release name:

```sh
python -m pip install 'ophiolite==<release>'
```

The SDK accepts an explicit existing scoped bearer credential.
Browser login can also obtain and privately store an approved application credential.
Do not put credentials in source files or logs.
Provider application credentials also need their approved application grant ID.

```python
import os
from ophiolite import Client, Credential

credential = Credential.bearer(
    os.environ['OPHIOLITE_TOKEN'],
    grant=os.environ.get('OPHIOLITE_GRANT'),
)
with Client(os.environ['OPHIOLITE_URL'], os.environ['OPHIOLITE_PROJECT'], credential) as client:
    data = client.read(asset_id, exact_revision, curves=['GR'])
    print(data.curves[0].axis, data.curves[0].values)
    data.save('new-read-folder')
```

Choose the asset and exact revision from your permitted catalogue or a downloaded
configuration. `Client.from_configuration(path, credential=credential)` accepts
read/local configuration files. No curve or replacement revision is inferred.
Without `credential` it uses the file `OPHIOLITE_CREDENTIAL` names or the sign-in
`ophiolite account login` saved for that address and project, else
`OPHIOLITE_ACCESS_KEY`, as `ophiolite.gallery.connect()` does.

`save` creates a private new directory and refuses an existing one. A single-curve
read writes `artifact.las`, `curve.json` and `descriptor.json`. Multiple curves get
separate curve and descriptor JSON files. JSON is re-serialized for readability;
its saved bytes are not claimed to match the downloaded representation hash.

## Browser login and credential renewal

```python
from ophiolite.auth import device_login

credential = device_login(
    gateway_url, project_id,
    notify=lambda url, message: print(message, url),
)
with Client(gateway_url, project_id, credential) as client:
    data = client.read(asset_id, exact_revision, curves=['GR'])
```

Follow the provider sign-in link, then confirm the application code in Workspace.
Login saves only after approval. The default request grants read access; `write=True`
requests additional write consent but does not establish permission by itself.
`notify` receives the two public browser URLs/codes; it never receives bearer tokens.
No browser opens automatically. Do not forward approval codes to an unknown party.

`Credential.from_file(path)` explicitly opens a saved SDK credential. The default
path is returned by `ophiolite.auth.default_path(gateway_url, project_id)` under
`~/.config/ophiolite/sdk/v1/projects/`. An explicit destination requires a private
0700 directory and 0600 file. Stored credentials are bound to the gateway/project.
The SDK renews an expiring provider session under a cross-process lock and rereads
before renewal, so overlapping callers use the newly saved credentials.

The SDK refuses old kit credential files and never migrates refresh tokens. Run
fresh browser login for the SDK; frozen kit installations retain their separate
cache and authorization. `credential.revoke()` attempts both Workspace and provider
revocation and removes the local cache, reporting any unconfirmed remote revocation.
`credential.delete()` removes only the local cache. Neither cancels a request that
already obtained a credential; server authorization remains decisive. A delayed
renewal cannot recreate a deleted cache. Explicit fresh login creates a new session.

## Scientific arrays and notebook display

Install `ophiolite[numpy]` or `ophiolite[pandas]` from the same reviewed source
revision to enable the optional views. They load only when called.

```python
array, description = data.to_numpy()
frame, description = data.to_frame()
description.attach(frame)  # optional, explicit frame.attrs['ophiolite'] copy
```

Each method returns a separate `Descriptor` carrying the full axis and its unit,
reference and order, per-curve units/counts, source identity, hashes and reader
interpretation. The frame starts with empty `attrs`. Use the companion descriptor
when passing an array to other code; array values alone do not preserve meaning.
Both methods refuse differing axes, units, depth references, interpretation or
source identity. Read incompatible curves separately or explicitly transform them
in your own scientific workflow with a recorded method.

## Async applications

```python
from ophiolite.aio import AsyncClient

async with AsyncClient(gateway_url, project_id, credential) as client:
    data = await client.read(asset_id, exact_revision, curves=['GR'])
    selections = await client.read_many([
        (asset_id, exact_revision, ['GR']),
        (other_asset, other_revision, ['RHOB']),
    ])
```

`describe` and `read` are awaited; `assets()` is an async iterator. `read_many`
returns results in input order and cancels/drains peers on failure. Every read uses
the same scientific verification as the synchronous client. Arrays, DataFrames and
notebook display use the returned `CurveSet` normally. Reads do not write files.

## Developer checks

```sh
python -m pip install '.[dev,numpy,pandas,validation]'
python -m build
python -m venv .wheel
.wheel/bin/python -m pip install dist/ophiolite-0.1.0-py3-none-any.whl
OPHIOLITE_TEST_WHEEL_PYTHON="$PWD/.wheel/bin/python" python -m pytest -q tests --ignore=tests/gateway
python tools/generate_models.py --check
python tools/check_public_inputs.py --artifact dist/ophiolite-0.1.0-py3-none-any.whl --artifact dist/ophiolite-0.1.0.tar.gz
```

## Local calculation, publication and recovery

Use an approved write credential and a private work folder for recoverable work:

```python
work = client.work_folder('my-calculation')
binding = work.configure(asset_id, exact_revision, curve='GR', name='My calculation')
run = work.start(binding, application_version='my-script/1', parameters={'factor': 2})
original, view = run.input()
receipt = work.publish(run, derived_curves=[{
    'mnemonic': 'GR_CALC', 'unit': 'gAPI', 'description': 'GR multiplied by two',
    'values': [None if value is None else value * 2 for value in view.values],
}])
work.download(receipt)
```

Run Python locally; `start` records and resolves a run, it does not execute your
script. Supply a `script=bytes` to record its digest. Declared method/version and
parameters establish traceability, not verified execution or rerun equivalence.
Only use the example's gAPI label when that is the selected curve's actual unit.
The runnable [public example](../examples/public_curve_handoff.py) preserves that unit.

Publication creates a separate derived asset; it does not edit the input, grant
access or silently append a revision. Validate all source curve names, explicit
LAS NULL, sample counts and derived names/units before sending. Missing values
stay `None`; zero stays zero. The SDK header parser currently requires UTF-8 and
refuses duplicate source mnemonics, even when a server reader can rename them.
It performs no resampling, unit conversion or scientific inference. Unsupported
headers/values raise `ValidationFailed` or `Refused` before publication.

After a lost response or process restart, reopen the same folder:

```python
result = client.recover('my-calculation')
```

To correct a result you published, publish the new values with
`new_version_of=previous_receipt`: they become the next version of the same
result, and the revision you reviewed is the expected parent — if someone added a
newer version meanwhile the server refuses with `IntegrityConflict` and nothing
changes. Earlier versions stay exactly readable; `client.history(result)` lists
them. `input_update.newer_revision_available` on a result summary only tells you
that its input has a newer version; nothing is recalculated.

`work.upload_las(path, name=..., attribution=..., audience=[...],
rights_confirmed=True)` persists an owned original copy before sending (up to 32 MiB; a deployment may set a lower limit, which its refusal names).
Changing/deleting the source file cannot change recovery. Upload permission is
separate from application-grant consent; use an explicitly authorised delegate
client/folder when required. The SDK never falls back to a different credential.
Attribution and rights confirmation are user declarations, not verified licences.

`AsyncClient` exposes the same methods with `await`; its work-folder methods are
also awaited. Credential and folder transactions run off the event loop. Cancellation
drains the active transaction before releasing its lock; it does not undo a server
mutation. Recover from the saved folder after an uncertain interruption.

## Command line (preview)

Installing the SDK provides `ophiolite`. Use the configuration downloaded from
Workspace: `ophiolite account doctor --configuration configuration.json` checks local
configuration and the packaged contract version without reading credentials or
contacting a server. Add `--online` explicitly to compare the service contract.

`login --no-browser` prints the sign-in and approval links. Add `--write` only for
publication consent. Credentials use the SDK namespace described above; old flat
kit caches are refused unchanged. Run fresh login rather than copying tokens.
`status` checks the approved grant, and `logout` revokes/removes the SDK session.

`list` discovers permitted assets. `fetch --asset ... --revision ... --curve GR
--output new-folder` reads exact data and preserves the pilot's file formatting.
For a calculation configuration, use `prepare --asset ... --revision ... --curve GR
--name Example --script calculation.py --parameters parameters.json --work run`.
An existing configured binding or `--release ... --curve ... --name ...` is also
supported. Prepare only fetches input; it never executes Python or publishes.

`run --work run` executes the unchanged prepared script locally with your operating
system permissions. Inspect its `curves.json`, then explicitly `publish --work run`.
Use `recover --work run` after a lost response. `share --asset ... --read colleague
--reuse colleague` replaces the audience; read/reuse rights are checked separately.
The offset example remains explicit: `correct --start 100 --stop 104 --offset 1
--publish` plus the input selection and `--output new-folder`. Values outside the
interval and missing samples remain unchanged. This example is not scientific
approval. All commands accept `--configuration` and optional `--credentials`.

## Agents (preview)

`ophiolite.agents.AgentClient` acts for the person who issued its key (Workspace
Settings → Agents): it proposes an exact change, waits for the person's approval and
executes that same request. With `evidence=` (E95) a proposal also records what the
person asked, the model the agent says it used and where its conversation lives:

```python
agent = AgentClient(url, project, credential)
proposed = agent.propose('applications/publish', {'id': run, 'changes': changes},
                         evidence={'instruction': 'Tidy the gamma ray of HON-GT-01.',
                                   'model': {'provider': 'anthropic', 'id': 'claude-sonnet-5-5'},
                                   'conversation': {'kind': 'notebook', 'reference': 'thread-4471'},
                                   'client': 'well-tidy/0.3'})
agent.wait(proposed['hash'], evidence_id=proposed['evidence'])  # until the approval names this record
agent.execute('applications/publish', {'id': run, 'changes': changes}, proposed['hash'], proposed['evidence'])
```

`agent.run(..., evidence=...)` does the three steps. The project setting decides whether
the instruction text is kept or only its fingerprint; it is never sent anywhere else.
Inside a program that has its own OpenTelemetry span, that span gains
`gen_ai.provider.name` and `gen_ai.request.model` (semantic conventions 1.37.0) and
nothing more; the library creates no span. Install `ophiolite[telemetry]` for this.

The person approves naming the evidence they read: `agents/approve` takes `evidence`
(a record id, or null) and `evidence_generation`, and refuses a body without them.
Agents may also propose `results/remake-run`; saving the remade result is the person's.

A job (E151) is one to eight steps `{operation, body}` under one approval. A body value
`{"$step": k, "pointer": "/id"}` is part of step k's answer:

```python
from ophiolite.errors import ChoiceRequired

steps = [{'operation': 'applications/configure', 'body': {'name': 'Gamma correction', 'asset_id': asset,
          'asset_revision': revision, 'curve': 'GR', 'runners': [me], 'command_id': 'cfg-1'}},
         {'operation': 'applications/start', 'body': {'id': {'$step': 1, 'pointer': '/id'},
          'generation': {'$step': 1, 'pointer': '/generation'}, 'command_id': 'run-1',
          'application_version': 'my-script/1'}}]
try:
    answers = agent.run_job(steps, evidence=evidence)   # propose, wait for the approval, run each step
except ChoiceRequired as asked:                         # a step needs the person's decision
    ...                                                 # asked.question, asked.choices, asked.plan, asked.step
    answers = agent.resume(asked.plan)                  # after the person answered: carry on from that step
```

- `propose_job(steps, *, evidence=None)` copies each body and adds this client's `project_id`
  when absent. A malformed list or a step naming another project raises `Refused` (a
  `ValueError`) before any request. Which operations a job may run is the gateway's decision.
- `job_status(plan)` is checked against `ophiolite.agent-job/1` without the `validation` extra.
- `step(plan, step, *, evidence_id=None, command_id=None)` sends the command id
  `uuid5(ophiolite.agents.NAMESPACE, f'{plan}:{step}')` by default, the same in every process.
- `resume(plan)` waits while the plan is pending, replays completed steps by those ids (their
  recorded answers; nothing is written again) and runs the rest. It also works in a restarted
  process. A completed step whose answer was never stored raises `CommandOwned`, which the SDK
  cannot recover.
- A declined or expired job raises `PlanDeclined` or `PlanExpired`; a failed one raises its word.
  `job(job_id)` is still the runner-job reader.

The person's side is on `Client`. `proposals()` lists every pending plan and every job waiting
for their choice (checked against `ophiolite.agent-proposals/1`). `answer(choice_token, choice)`
answers one with a choice id (`'c1'` … `'c8'`). An agent credential is refused on both by the
gateway (`agent-refused`). A used, foreign or stale token, or another person's job, raises
`ChoiceRefused` (code `choice-refused`) with `details['reason']`.

## Packaged workflow guides

Run `ophiolite tools skills path` to locate six installed guides: authenticate, read exact
data, validate locally, publish derived curves, share a result and recover a
publication. They describe public SDK calls and refusal recovery. Keep the original
private work folder after an uncertain publication; read grants before deciding what
to do after an uncertain sharing response. Never retry sharing automatically.
The repository's AGENTS.md records the same scientific and credential boundaries.
