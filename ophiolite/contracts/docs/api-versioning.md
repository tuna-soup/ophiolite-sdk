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

## Errors

Every refusal is `{error, code, message, remedy, docs, request_id}`. `code` is stable; `error` equals
`message` and is kept for clients written before `message` existed. New fields may be added to this
envelope; none is removed without a transition.
