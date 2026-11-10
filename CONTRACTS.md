# Stability, compatibility and qualification statements of the Ophiolite SDK

Schema validation and the scientific contracts the models check are described in [docs/contracts.md](docs/contracts.md).
How to use the SDK is in [docs/sdk-guide.md](docs/sdk-guide.md).

## Ophiolite SDK — preview contracts, supported client

The supported 0.x client reads and publishes exact scientific revisions through Ophiolite's
public service API. Contracts remain preview contracts. No production-support or
complete open-source release qualification is claimed.

## Install and read

A read checks identity, lengths, hashes, units, missing values, source references
and reader interpretation. Wrapped and unwrapped LAS are supported through the
server's normalized view. The original LAS artifact stays byte-for-byte intact.
Zero is a value; `None` is a missing sample. Unit labels and depth reference remain
as reported, including unknown meaning. There is no interpolation or conversion.

The source artifact is exact. This directory is not an E18 portable export bundle.

## Browser login and credential renewal

Login/consent polling is bounded to ten minutes per phase. Renewal is never retried
automatically after an uncertain provider response; sign in again when instructed.
A `threading.Event` passed as `cancel` can stop login polling or lock waits. It does
not interrupt an HTTP request already in progress. HTTP timeout is 30 seconds.
POSIX lock behavior is tested on Linux; the Windows locking branch is unqualified.
C3 qualification uses a synthetic rotating provider, not a production identity provider.

## Scientific arrays and notebook display

The NumPy array has shape `(samples, selected curves)`, with float64 columns in
requested order. Missing samples become NaN; real zero stays zero. The DataFrame
uses the exact depth axis as its index, including decreasing or duplicate values.
Neither method sorts, aligns, interpolates, fills gaps or converts units.

Notebook HTML presents scientific labels, units and counts; identifiers and hashes
are in **Technical details**. The exact-version link opens the first selected curve and requires a Workspace
build with E4 scientific-link support. Older Workspace builds need an upgrade.
The link contains no credential and grants no permission; sign in to Workspace
with permitted read access. An unavailable version is refused instead of replaced
with a newer one. The qualification evidence covers an isolated candidate gateway;
it does not establish support for every deployment.

## Async applications

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

The gateway lane additionally needs the pinned Platform test runtime and an isolated
PostgreSQL test schema. `OPHIOLITE_REQUIRE_GATEWAY=1` turns missing required cases
into failures. Its current delegate is stubbed; it does not qualify browser consent
or a live deployment. Mutation and independent verification results are recorded in
the Integration E04 strategy, with the exact commands and source revisions.

## Local calculation, publication and recovery

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
| Share with `expected_generation` | Once more with the identical command: returns the applied result, or `IntegrityConflict` if anyone changed the recipients meanwhile. |
| Login, refresh and revoke | Never after an ambiguous request outcome. |

Read `grants = client.grants(receipt.asset)`, decide the complete intended
audience, then call `client.share(receipt.asset, read=[...], reuse=[...],
expected_generation=grants.generation)`. This replaces the audience; it is not an
additive invitation. If someone changed the recipients after your read, the
server refuses with `IntegrityConflict` and nothing changes: read again and
decide. A lost response is retried once automatically and can never undo a later
revocation. Servers without conditional sharing report `generation=None`; the
conditional form then refuses without sending anything. `expected_generation` is
required: since the E7 transition release servers refuse unconditional replacement (428).
Unavailable grants (non-owner, absent or mismatching exact revision) are refused,
never represented as an empty audience. Publication and sharing are separate.
Restricted result models retain permitted scientific data without fabricating or
exposing inaccessible parent identifiers. Revocation cannot recall earlier exports.

## Synthetic workflow fixture server

`from ophiolite.testing import fixture_server` provides an in-memory loopback
workflow fixture, including `drop_response_after='publish'` to simulate a lost
reply after commit. It accepts its packaged original synthetic LAS only. It is a
test aid, not an authorization oracle, general LAS service or deployed gateway.
Native gateway and deployment qualification are separate tests. No stable SDK,
production service or complete E17/E18 release is implied by this preview.

## Command line (preview)

The old six correction output files and three read output files remain compatible.
Private SDK identity, locks, exact requests/responses and input checkpoints are
additional files; retain the entire folder for recovery. The deprecated pilot kit
uses the same SDK credential transactions when upgraded. Frozen old installations
remain separate and cannot safely share the new credential cache.

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
