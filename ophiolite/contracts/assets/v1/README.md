# Scientific assets v1 — bounded pilot

This folder is one entry of the [contracts registry](../../README.md);
`contracts/registry.json` lists its schemas and fixtures with their versions
and lifecycle badges.

M2 adds common exact reads and permission-filtered discovery. M1 fixtures remain
offline examples, not authorization evidence. Deployments with legacy payloads must
complete the documented offline migration before enabling these routes. Publication
uses the existing application protocol; calculation runs externally.

## Identity and representations

`schema.json` is generated from `project_gateway.scientific_assets.Asset`;
`curve-schema.json` from `Curve`, `curve-context-schema.json` from
`ScientificContext` and `summary-schema.json` from `AssetSummary`. All use
existing Pydantic and identify themselves with `$id` and `x-ophiolite`. `/1` is the permanent
version token; pilot is a support status, not a temporary schema suffix.

An asset ID is distinct from its exact revision. A source reference contains its
upstream authority/key/revision/profile. Retention adds a managed custodian without
changing source authority. A calculation creates a separate `ophiolite:derived`
asset whose first revision is the artifact SHA-256. The current run ID is its key.
Identical publication retries must resolve that same asset/revision/receipt;
conflicting requests reject. Recalculation makes another asset, not an implicit
revision append. These publication requirements were qualified in M2; M3 adds bounded recovery evidence.

| Token | Role |
|---|---|
| `las2/1` | Qualified source/artifact profile, including a derived LAS |
| `ophiolite.application-curve/1` | Existing normalized JSON curve schema |
| `application-curve/1` | Existing reader mapping version, not a new data type |
| `portable-las2/1` | Existing application output-slot declaration |
| `ophiolite/well-curve/1` | Different native protobuf profile, strictly increasing MD metres; do not substitute |

Representation kinds distinguish original source files, captured query results,
normalized views and derived artifacts. This M1 LAS profile permits one original
(or derived artifact) and one normalized curve. `captured-result` is vocabulary
reserved for a future qualified query profile, **not** SQL curve support. A retained
LAS capture still exposes the original LAS; it is not a newly generated original.
Digests cover exact returned bytes, not canonicalized JSON. Representation IDs are
opaque selectors, not server paths or credentials. Normalization omits other curves
and headers; the exact artifact retains them. Availability is a statement at read
time, not a guarantee of indefinite retention.

## Interpretation identity

An **interpretation** is the recipe that turned original bytes into the
normalized view: `reader`, `parsing_policy` and `mapping` are its versioned
identity; `lasio_version` is library evidence; `null_policy` is prose. The
live reader emits it (`applications.live_interpretation()`), and every new
upload, release capture and publication records it under
`observation_reader` at retention. A descriptor reports both:

| `interpretation_evidence` | Meaning |
|---|---|
| `live` | source reference; nothing was retained, so nothing was recorded |
| `recorded` | the recorded identity and library equal the live reader's |
| `recorded-differs` | reader, parsing policy or library differ (a pre-E1 record without `parsing_policy` counts as different); both records are shown and the view is served with the live values |
| `not-recorded` | a historical retained row without a mapping record (migrated or pre-E1 capture/upload); nothing is assumed |

A `mapping` difference refuses the normalized view (`422
incompatible-context`: "Normalized view would be reinterpreted under a
different mapping"); the exact artifact stays readable. `recorded_interpretation`
uses `RecordedInterpretation`, which represents any past version, so an unknown
`reader/2` in a record is still shown and compared. CLI 0.2 compares only the
two live interpretations; it cannot see `recorded_interpretation` (E4 does).

`fixtures/frozen/pre-e1/` holds byte copies of the fixtures as committed
before this identity existed; they validate through the defaults and are never
regenerated (the generator refuses to write there).

## Scientific rules and conformance

The existing application reader supplies source-native depth, units, curve name,
LAS NULL marker and reader/lasio/mapping/parsing policy. JSON `null` means missing;
zero is an actual measurement. Empty unit strings mean unknown, never dimensionless.
Nonfinite value samples become null under the recorded reader policy; a missing or
nonfinite depth rejects. The validator accepts finite axes in their original order,
including decreasing/duplicate depths. `axis_order`, `axis_duplicates`, unit status,
missing count and sample count are observed facts, not endorsements or conversions.
No CRS, MD/TVD meaning, datum, well identity or physical quantity is inferred.

The interval-offset slot accepts unknown units because start/stop and offset are
explicitly in the source's own coordinate/value units. It preserves row identity,
axis and null mask, rejects a result equal to the LAS NULL marker, nonfinite
results and more than 1,000 changed samples. A scientific application requiring
ordered MD metres or GR/gAPI must check those stricter requirements itself; this
contract does not establish the OpendTect Float32 or host-import gate.

Structural JSON Schema cannot express every cross-field constraint. Executable
validation additionally checks paired arrays; marker/zero/null distinctions;
representation kind/profile/media agreement; unique representations/operations;
origin/authority/custody/retention/lineage consistency; derived artifact revision;
unit status and observed counts; and capability/permission separation.
`validate_pair()` also checks normalized byte length/digest, source reference,
artifact digest, exact scientific facts and interpretation. These are data
conformance checks, not proof a source declaration or calculation is scientifically
correct. Historical data may lack interpretation evidence; the contract must expose an
explicit unavailable/unknown representation instead of inventing fields to fit v1.

`authorization: {status: not-evaluated}` has no allowed operations. An evaluated
response carries identity, UTC timestamp and allowed operations, a subset of the
supported operations. Offline fixtures never assert grants. Cached evaluation
cannot authorize a later call; every server read/export/run/publication must check
current rights. Lineage does not grant access to parents, and its visibility must
be filtered. Method/code/environment references are explicitly script-declared;
missing environment capture prevents a guarantee of computational reproduction.

## Public operations (served since M2; described by openapi/v1)

The live `GET /api/v1/openapi.json` is the single description of every route,
and `contracts/openapi/v1/openapi.json` is its committed snapshot (equality
tested; the scientific path fragment `openapi/v1/scientific-assets.paths.json`
is a generator input, not a public document). `GET /api/v1/contracts` serves
the registry index and `GET /api/v1/contracts/<path>` every document it lists.
Use browser-authorized scoped identity or existing approved machine identity.
Read/export scope is distinct from compute/publication scope.

- `GET /api/v1/projects/{project}/scientific-assets?limit=...&cursor=...`: authorized
  discovery only, 1–100 items, opaque cursor, default 25. An empty list is valid.
- `GET /api/v1/projects/{project}/scientific-assets/{asset}/revisions/{revision}`:
  exact descriptor, no run required. Never substitute current content.
- `GET .../representations/{representation}`: exact bytes with matching media type,
  length and SHA-256 from descriptor. Bounded pilot payload, no range/streaming claim.
- Publication remains the separate scoped application operation in M2; its receipt
  must identify a durable readable asset revision and respect private-by-default
  audience. This document does not replace the current publication request schema.

Error body is flat: `{ "error": "message", "code": "code" }`. New scientific
routes use `not-found`404 for missing/inaccessible/wrong revision (including withdrawn
roots), `incompatible-context`422, `integrity-conflict`409 and `capacity-exceeded`413.
Identity/scope errors retain the existing401/403 codes. Legacy application/release
routes retain their existing errors. Neither path reveals private existence.

M2 discovery uses summary-schema.json, not full per-curve descriptors. It does not
parse all payloads. A curve is required for descriptors and normalized reads; the
representation id is `curve:<mnemonic>`. `artifact` is curve-independent. Missing
historic parsing context is not invented; current normalization identifies its
reader version. Current observations in discovery are not historic reader evidence.
Parent references are omitted only when `parent_visibility=restricted`; exact
private lineage remains server-side. This refines the previously unserved proposal.

## Display words (scientific-asset 1.3.0, asset-summary 1.2.0)

Descriptors and discovery summaries carry an optional `display` object: plain
words for people, computed by `services/project_gateway/display.py`. Profile
words are the registry's `display_name` and `description`; enum words are owned
by `display.py`. The identifiers stay in their own fields; `display` never
replaces or renames them, and clients keep identifiers under a Technical details
disclosure.

| `display` field | Words | From |
|---|---|---|
| `type`, `type_help` | registry `display_name` / `description`; `Data type not registered` for an unknown id | `profile` |
| `source` | `Uploaded by you` / `Uploaded by a project member` / `Result of <calculation>` / connection name / `Connected source` | `authority`, uploader, run, connection inventory |
| `held_as` | `Linked` · `Saved copy` · `Result` | `origin` |
| `updates` | `Keeps up to date` · `Locked to this version` · `Ask me first` | `origin`, `mode`, `expected_revision` |
| `version` | `{at, by: {id, label}, ordinal, of, source_version}`; never polling time | upload time, run publication, release creation, short OSDU record version |
| `method`, `settings` | `Interval offset, version 1`; `From depth 100 to 103, add 2` (known methods only, else `null`) | `application_version`, `parameters` |
| `evidence` | `Declared by the source` · `Declared by the script` · `Recorded calculation` | `provenance.evidence` |
| `built_on` | `an uploaded file` / `an earlier result` / connection name; `Not shown` when the parent is restricted | authorized `parents` only |
| `available_as` | `original file`, `captured result file`, `result file`, `curve table`; `(not kept for this version)` when unavailable | representation kind, media type and profile together |

Other gateway payloads gain the same kind of object without a published schema:
source selections (`/api/sources/list`, with `status` and `last_checked`),
`preview` (`checked`, `declares`), `mapping-report` (`type`), calculation setups
and runs (`/api/applications/list`, `result-preview`, `result-list`), release
options, and `get`/`preview` where `display.assets[<index>]` sits beside the
manifest, never inside it (the manifest digest and export bytes are unchanged),
and native descriptions (`/api/catalog/describe`).

This is an additive 1.x change. Old fixtures without `display` validate against
the new models and schemas, and clients that read by key (the CLI 0.2 reader,
kept byte for byte in `services/project_gateway/tests/fixtures/cli-0.2/`) keep
reading and verifying. One direction is not covered: the published schemas say
`additionalProperties: false`, so a client that validates a new response against
a pinned older schema document (scientific-asset 1.2.0 or earlier, asset-summary
1.1.0 or earlier) rejects it and must take the current document.

Audience endpoints also expose optional `display.member_names`: exact authorized
account IDs map to existing account names. It is emitted for upload-member lists
and, only to the sharer, original-info/result-preview audiences. Lookup happens
after the service authorizes and only for IDs in its response, never arbitrary
request IDs. Missing/blank names and names equal to IDs are omitted. This is not
a directory or a grant; original audience IDs and authorization remain unchanged.
Consumers must distinguish missing/duplicate labels and retain exact identity in
technical details. No new scientific schema field or payload identity is introduced.

## Compatibility and verification

Changing required fields, meanings, auth semantics or scientific interpretation
requires a new schema/profile version. Additive optional fields are compatible;
servers validate known fields strictly, consumers must negotiate the documented
version rather than reinterpret unknown semantics. A transition release supports
the prior documented pilot version with migration examples and an announced cutoff.
Emergency security restrictions are documented exceptions. Stored revisions remain
decodable. No stable general SDK is promised.

From Platform with the existing qualified environment:

```sh
PYTHONPATH=services python contracts/tools/generate.py
PYTHONPATH=services python -m pytest services/project_gateway/tests/test_scientific_assets.py services/project_gateway/tests/test_contracts_registry.py
```

Fixtures are authored synthetic data (not observed wells), including a real zero
and missing sample. Their generator uses the qualified current reader. Optional
`OPHIOLITE_NLOG_LAS` runs conformance over downloaded HON-GT-01; report whether it
ran. Schema equality is tested against Pydantic generation; no claim of an external
JSON-Schema engine test. See the [offline user example](../../../docs/scientific-assets.md)
and [migration inventory](../../../docs/scientific-asset-migration.md).

## Typed assets (1.5.0, E11)

Three further source profiles are served through the same envelope: `well-tops-csv/1`,
`deviation-csv/1` and `esri-ascii-grid/1`. Each has one exact original (`artifact`,
`text/csv` or `text/plain`) and one normalized representation (`data`,
`application/json`) whose schema is `ophiolite.well-tops/1`, `ophiolite.trajectory/1`
or `ophiolite.regular-grid-surface/1`. `scientific` is then the typed context
(`ophiolite.typed-context/1`) including an assessed fidelity report, and
`interpretation` names `asset_connectors.typed_reader/1`. Declared context the
uploader did not know is the value `unknown`. `relationships.well_log` carries the
exact well log a tops or trajectory upload was explicitly associated with, or
`"restricted"` when the caller cannot read it. Readers before 1.5.0 refuse typed
descriptors as contract-invalid; curve descriptors are unchanged. Fixtures:
`fixtures/{tops,trajectory,grid}{.original,-data.json,.json}`.
