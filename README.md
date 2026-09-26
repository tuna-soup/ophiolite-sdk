# Ophiolite SDK — preview contracts, supported client

The supported 0.x client reads and publishes exact scientific revisions through Ophiolite's
public service API. Contracts remain preview contracts. No production-support or
complete open-source release qualification is claimed.

## Install and read

Python 3.10 or later is required. Install from a reviewed commit of this repository:

```sh
python -m pip install 'git+https://github.com/tuna-soup/ophiolite-sdk@<reviewed-commit>'
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

A read checks identity, lengths, hashes, units, missing values, source references
and reader interpretation. Wrapped and unwrapped LAS are supported through the
server's normalized view. The original LAS artifact stays byte-for-byte intact.
Zero is a value; `None` is a missing sample. Unit labels and depth reference remain
as reported, including unknown meaning. There is no interpolation or conversion.

`save` creates a private new directory and refuses an existing one. A single-curve
read writes `artifact.las`, `curve.json` and `descriptor.json`. Multiple curves get
separate curve and descriptor JSON files. JSON is re-serialized for readability;
its saved bytes are not claimed to match the downloaded representation hash.
The source artifact is exact. This directory is not an E18 portable export bundle.

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

Login/consent polling is bounded to ten minutes per phase. Renewal is never retried
automatically after an uncertain provider response; sign in again when instructed.
A `threading.Event` passed as `cancel` can stop login polling or lock waits. It does
not interrupt an HTTP request already in progress. HTTP timeout is 30 seconds.
POSIX lock behavior is tested on Linux; the Windows locking branch is unqualified.
C3 qualification uses a synthetic rotating provider, not a production identity provider.

## Scientific arrays and notebook display

Install `ophiolite[numpy]` or `ophiolite[pandas]` from the same reviewed source
revision to enable the optional views. They load only when called.

```python
array, description = data.to_numpy()
frame, description = data.to_frame()
description.attach(frame)  # optional, explicit frame.attrs['ophiolite'] copy
```

The NumPy array has shape `(samples, selected curves)`, with float64 columns in
requested order. Missing samples become NaN; real zero stays zero. The DataFrame
uses the exact depth axis as its index, including decreasing or duplicate values.
Neither method sorts, aligns, interpolates, fills gaps or converts units.

Each method returns a separate `Descriptor` carrying the full axis and its unit,
reference and order, per-curve units/counts, source identity, hashes and reader
interpretation. The frame starts with empty `attrs`. Use the companion descriptor
when passing an array to other code; array values alone do not preserve meaning.
Both methods refuse differing axes, units, depth references, interpretation or
source identity. Read incompatible curves separately or explicitly transform them
in your own scientific workflow with a recorded method.

Notebook HTML presents scientific labels, units and counts; identifiers and hashes
are in **Technical details**. The exact-version link opens the first selected curve and requires a Workspace
build with E4 scientific-link support. Older Workspace builds need an upgrade.
The link contains no credential and grants no permission; sign in to Workspace
with permitted read access. An unavailable version is refused instead of replaced
with a newer one. The qualification evidence covers an isolated candidate gateway;
it does not establish support for every deployment.

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

Credential lock waits, file operations and provider HTTP run in a worker thread.
Cancellation waits for an in-progress credential transaction to finish/save, then
propagates; this can take the bounded lock/provider timeout. It never abandons a
rotating refresh token. Cancellation during a scientific response closes that
response and returns no partial `CurveSet`. An injected HTTP client remains owned
by its caller. Async behavior is qualified with the asyncio backend only.

## Recovery and limits

- Authentication failure: obtain a current approved credential and retry.
- Access refusal or unavailable revision: check permission and the exact revision;
  select a different revision explicitly if appropriate.
- Integrity/scientific mismatch: do not use the response; investigate the source or
  reader with the deployment administrator. Nothing is saved by a failed read.
- Different recorded/current interpretation: both records stay in the descriptor;
  `strict_interpretation=True` refuses differences. A changed mapping is refused.
- Existing output folder: choose a new folder; existing files are not overwritten.

The client bounds artifacts to 32 MiB and scientific arrays to 100,000 samples.
Local models/validation import without credentials or a running service. Models
retain additive fields while enforcing declared constraints. The `validation`
extra enables strict JSON Schema checks; see [contracts](docs/contracts.md).

Asynchronous I/O, browser login, publication, the CLI and application templates
remain later E4 commits. Portable export and the independent
bundle reader belong to E18; see [the reader boundary](docs/offline-reader-boundary.md).

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

The gateway lane additionally needs the pinned Platform test runtime and an isolated
PostgreSQL test schema. `OPHIOLITE_REQUIRE_GATEWAY=1` turns missing required cases
into failures. Its current delegate is stubbed; it does not qualify browser consent
or a live deployment. Mutation and independent verification results are recorded in
the Integration E04 strategy, with the exact commands and source revisions.

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
The runnable [public example](examples/public_curve_handoff.py) preserves that unit.

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

Recovery replays a saved exact request and checks the response. A completed folder
returns `None`. Preserve the folder, including requests, metadata and responses;
do not edit it to change a calculation. Changed work needs a new folder. Direct
`client.configure/start/publish` calls are available but are **not recoverable after
a process restart**. A command ID alone is not a recovery handle.

Work folders bind gateway, project and authenticated identity. A fresh approved
grant for the same server-confirmed user can recover. A replacement opaque delegate
cannot: recovery requires the original delegate fingerprint. Credentials are never
written into the work folder. Saved payload and metadata are flushed and fsynced
before a mutation; a folder lock spans checkpoint, request and response. This is
Linux process-restart/durability-order qualification, not a power-loss guarantee.

| Operation | Automatic retries |
|---|---|
| Reads, inspect, options, info, members, results and downloads | Up to three attempts for transient transport/busy responses. |
| Configure, start, upload and publish | Up to three attempts with the same command/body; folders persist them for later recovery. |
| Share | Never; an uncertain response raises `ShareOutcomeUnknown`. |
| Login, refresh and revoke | Never after an ambiguous request outcome. |

Before retrying an uncertain share, read `client.grants(receipt.asset)` and decide
the complete intended audience. Then call `client.share(receipt.asset, read=[...],
reuse=[...])`. This replaces the audience; it is not an additive invitation.
Unavailable grants (non-owner, absent or mismatching exact revision) are refused,
never represented as an empty audience. Publication and sharing are separate.
Restricted result models retain permitted scientific data without fabricating or
exposing inaccessible parent identifiers. Revocation cannot recall earlier exports.

`work.upload_las(path, name=..., attribution=..., audience=[...],
rights_confirmed=True)` persists an owned original copy before sending (8 MiB cap).
Changing/deleting the source file cannot change recovery. Upload permission is
separate from application-grant consent; use an explicitly authorised delegate
client/folder when required. The SDK never falls back to a different credential.
Attribution and rights confirmation are user declarations, not verified licences.

`AsyncClient` exposes the same methods with `await`; its work-folder methods are
also awaited. Credential and folder transactions run off the event loop. Cancellation
drains the active transaction before releasing its lock; it does not undo a server
mutation. Recover from the saved folder after an uncertain interruption.

## Synthetic workflow fixture server

`from ophiolite.testing import fixture_server` provides an in-memory loopback
workflow fixture, including `drop_response_after='publish'` to simulate a lost
reply after commit. It accepts its packaged original synthetic LAS only. It is a
test aid, not an authorization oracle, general LAS service or deployed gateway.
Native gateway and deployment qualification are separate tests. No stable SDK,
production service or complete E17/E18 release is implied by this preview.

## Command line (preview)

Installing the SDK provides `ophiolite`. Use the configuration downloaded from
Workspace: `ophiolite doctor --configuration configuration.json` checks local
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

The old six correction output files and three read output files remain compatible.
Private SDK identity, locks, exact requests/responses and input checkpoints are
additional files; retain the entire folder for recovery. The deprecated pilot kit
uses the same SDK credential transactions when upgraded. Frozen old installations
remain separate and cannot safely share the new credential cache.


## Packaged workflow guides

Run `ophiolite skills path` to locate six installed guides: authenticate, read exact
data, validate locally, publish derived curves, share a result and recover a
publication. They describe public SDK calls and refusal recovery. Keep the original
private work folder after an uncertain publication; read grants before deciding what
to do after an uncertain sharing response. Never retry sharing automatically.
The repository's AGENTS.md records the same scientific and credential boundaries.

## Version and compatibility policy

Python `ophiolite` and TypeScript `@ophiolite/client` share `0.MINOR.PATCH` and one
release tag. PATCH changes fix defects or add APIs. MINOR changes may break APIs,
with a **Breaking** entry in CHANGELOG.md and a one-minor deprecation shim where
feasible. A stable 1.0 promise requires every registry entry the SDK reads to be
supported and the OpenAPI document to be versioned as stable. Source installation
is available; PyPI/npm publication and managed-service release qualification are
separate delivery gates.

Additive contract fields are tolerated while declared constraints remain enforced.
A new schema suffix such as `/2` requires a new model and SDK MINOR. For an unknown
schema, upgrade the SDK or read the exact artifact; do not reinterpret its meaning.
Templates record their own version and SDK version, and CI tests them against the
current SDK. Supported scientific reads currently cover the documented curve
profiles, not arbitrary geoscience types or universal conversion.

The pilot `ophiolite-cli` 0.3.0 compatibility modules remain for one announced
transition release. They are removed in the first versioned E10 release afterward.
Use fresh SDK login; do not import old credential caches. The SDK, TypeScript client,
templates, packaged guides and extracted contracts are Apache-2.0. Server licensing
and the complete open-source release have separate qualification requirements.
