# API versions and deprecation

How the Ophiolite public API (`/api/v1/`) changes, and how a client knows what a deployment serves.
Served at `/api/v1/contracts/docs/api-versioning.md` as the registry document `ophiolite.policy/api-versioning/1`.

## What the version numbers mean

- **`/api/v1/`** is the only path version. It changes only for a break that cannot be expressed as a
  transition (below); none is planned.
- **`info.version` `1.0.0`** in `/api/v1/openapi.json`; each operation states its stability in
  `x-ophiolite-stability`. A `supported` operation changes only as this page says: additively, or by a
  transition. A `pilot` operation is tested and documented, but is not yet a supported, unattended
  service contract. Supported today: the four volume-window routes under
  `/api/v1/projects/{project}/scientific-assets/{asset}/revisions/{revision}/`: `GET volume-windows`,
  `GET volume-windows/pieces/{index}`, `GET volume-windows/file-header` and
  `GET volume-windows/headers/{index}`. Every other operation is `pilot`.
- **The contracts registry version** (`version` in `/api/v1/contracts`, also
  `info.x-ophiolite-contracts.registry_version` in the OpenAPI document) is semver and moves with every
  change to a published schema, profile, route or document. A client compares it with the version it was
  built against: an older deployment may lack routes the client knows (the SDK then reports them as not
  applicable rather than failing), a newer one only adds.
- **Contract ids end in a permanent version token** (`las2/1`, `ophiolite.well-location/1`). Additive
  changes keep the id and raise the entry's semver; a breaking change is a new id (`/2`), served beside
  the old one for the transition.

## Additive changes (no transition)

A release may, without notice:

- add an operation, a route, a response field, an optional request field, an enum value in a response,
  an error code (every code has a heading on the errors page), a header, or a registry entry;
- document an existing shape more precisely (a request or response schema that describes what the
  operation already accepted and answered);
- relax a limit.

Clients must ignore response fields and codes they do not know, and must not depend on field order.

## Breaking changes (a transition)

These need a transition:

- removing or renaming an operation, route, field or code;
- making a request narrower than it was: a new required field, a stricter type or range, rejecting
  fields that were accepted — including when an operation that accepted an unschematized object gains a
  validated model that rejects some of what it used to accept;
- changing the meaning of a field or of a status code.

A transition keeps the old form working and marks it:

1. The old route, alias or field is listed under `x-ophiolite-deprecated-aliases` (routes) or marked
   `deprecated: true` in its schema (fields), and every successful answer through it carries `Deprecation`
   (RFC 9745) and `Sunset` (RFC 8594) headers, with `Link: <successor>; rel="successor-version"` when
   there is one. Every deprecated route is listed in `ophiolite.policy/deprecations/1`
   (`/api/v1/contracts/deprecations/v1/deprecations.json`); the OpenAPI document projects it
   (`deprecated: true` on operations, `x-ophiolite-deprecated-aliases` for aliases).
2. The deprecation date, the sunset date and the removal condition are recorded in the release notes and
   in `docs/api-routes.md`; the sunset is at least one release after the deprecation. For routes, the
   dates and the condition are the registry entry's.
3. Removal happens only after the sunset **and** the condition (for the legacy aliases: every caller in
   `docs/api-routes.md` has moved). Today the legacy browser aliases are deprecated
   `@1790294400` (2026-09-25) with sunset Wed, 31 Mar 2027.

## The Python SDK and the TypeScript client

The rule is [ADR 0015](../../../docs/decisions/0015-supported-developer-surface.md)'s, as it stands:

- Python and TypeScript share `0.MINOR.PATCH` and one tag. PATCH fixes defects or adds APIs.
- MINOR may break APIs, with a CHANGELOG "Breaking" entry and a one-minor shim where feasible. Releases are
  numbered by date, so the shim lasts one release: its removal is announced in the CHANGELOG one release
  ahead and lands in a later release.
- A new schema suffix such as `/2` requires a new model and a MINOR.
- A stable 1.0 promise requires every registry entry the SDK reads to be supported and the OpenAPI document
  to be versioned as stable.

No other support window is stated. When a server answers a deprecated route, the SDK warns once per route
and the command line shows the warning on standard error.

## Profiles and stored items

A profile id `kind/N` never changes meaning. A break is `kind/N+1`, served beside `N`. ADR 0015's rule
holds as it stands: historical revisions stay decodable, no committed data is silently reinterpreted, and
documented emergency security exceptions are kept. A stronger promise is in force: every released `N`
stays decodable, proven by frozen fixtures. The server reads a frozen file of every released profile, as
first released (`services/project_gateway/tests/test_released_profiles.py`), and the SDK reads a frozen
bundle of every released bundle version (`tests/test_released_bundles.py`); a change that stops reading
one fails the build. Decodable is not permission: who may read a retained item does not change.

## Supported contracts

Every schema and profile in the registry carries a lifecycle. Most are `preview`: served and tested, but
replaceable by a new id inside the program without a transition. The contracts the MVP journey moves are
`supported`. The list was measured on 24 November 2026: every schema and profile id that travelled in a request
or an answer of one whole run of the journey, from the sources to QGIS. The transfer receipt was added after a
second whole run on 25 November 2026, once the receipt work (E184) had closed. Each entry's `qualified_by`
names the run that measured it:

| Contract | Schema | Profile |
|---|---|---|
| `deviation-csv/1` | | yes |
| `esri-ascii-grid/1` | | yes |
| `ophiolite.asset-summary/1` | yes | |
| `ophiolite.entity/1` | yes | |
| `ophiolite.held-copies/1` | yes | |
| `ophiolite.point-columns/1` | yes | yes |
| `ophiolite.point-set/1` | yes | yes |
| `ophiolite.regular-grid-surface/1` | yes | yes |
| `ophiolite.sender/1` | yes | |
| `ophiolite.source-provenance/1` | yes | |
| `ophiolite.trajectory/1` | yes | yes |
| `ophiolite.transfer-receipt/1` | yes | |
| `ophiolite.typed-context/1` | yes | |
| `ophiolite.well-location/1` | yes | |
| `ophiolite.well-tops/1` | yes | yes |
| `points-csv/1` | | yes |
| `sql-wells/1` | | yes |
| `well-tops-csv/1` | | yes |

What `supported` promises:

- **Only additive change.** A supported schema may gain an optional field, and only in a minor version
  of its entry. A validator should therefore use the version it reads, not the version it was written
  against. Nothing is removed, made required, narrowed or renamed. A field that is not optional, a new
  enumeration value, or a changed type is a new id (`/2`), served beside the old one.
- **Readable by the SDK you have.** The promise covers the Python SDK from release 2026.11.25. That is the
  first published release that ignores answer fields it does not know. The build reads the current
  answer of every supported schema with that release, as published. A new field reaches a supported schema
  only when that release still reads it.
- **A reader you write yourself should ignore fields it does not know.** Supported answers change only by
  adding optional fields, so a reader that ignores unknown fields keeps working.
- **Some contracts change only by a new id.** A profile is a document that no SDK parses: it changes only by
  a new id. The same holds for a supported schema that no SDK entry point reads (`ophiolite.typed-context/1`),
  because nothing can show that an added field is read. It holds as well for the transfer receipt
  (`ophiolite.transfer-receipt/1`): the exchange check in the SDK and in the QGIS plug-in refuses a receipt
  it does not fully know before anything is done, so any new field is a new id.
- **A deprecation needs a transition release and an announced cutoff**, as for routes above.
- **At least 12 months' notice.** When a supported contract is replaced by a new id, the old id keeps being
  served for at least 12 months after its deprecation is announced.
- **The build enforces it.** Each supported contract, and the documents it names, is kept as a frozen copy
  (`supported-1`; the transfer receipt and its code document `ophiolite.transfer-codes/1`, version 1.0.0, in
  `supported-2`). A change the gate does not recognise as additive fails the build. A changed description,
  title or interpretation passes only with a reviewed release-note row.

Not marked, and why:

- `ophiolite.scientific-asset/1`: the envelope every stored item shares. It still changes too often to promise.
- `ophiolite.transfer-receipts/1`, the page of receipts: no journey step reads it yet.
- The `/1` curve shapes (`las2/1`, `ophiolite.application-curve/1`, `ophiolite/well-curve/1`): the journey still
  serves LAS curves in the `/1` shape, and its successor `ophiolite.well-log-curve/1` is not yet what the
  journey reads.

How long a release stays supported is ADR 0015's rule, as above; this section does not add a release support
window. The 12 months above is how long an old contract id keeps being served after its deprecation is
announced, not how long a release is supported.

## Errors

Every refusal is `{error, code, message, remedy, docs, request_id}`. `code` is stable; `error` equals
`message` and is kept for clients written before `message` existed. New fields may be added to this
envelope; none is removed without a transition.
