# API versions and deprecation

How the Ophiolite public API (`/api/v1/`) changes, and how a client knows what a deployment serves.
Served at `/api/v1/contracts/docs/api-versioning.md` as the registry document `ophiolite.policy/api-versioning/1`.

## What the version numbers mean

- **`/api/v1/`** is the only path version. It changes only for a break that cannot be expressed as a
  transition (below); none is planned.
- **`info.version` `1.0.0-pilot`** in `/api/v1/openapi.json` marks the whole API as a pilot: routes and
  shapes are tested and documented, but the deployment is not yet a supported, unattended service
  contract. The suffix is dropped when the first operation is declared supported.
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
   `deprecated: true` in its schema (fields), and every answer through it carries `Deprecation`
   (RFC 9745) and `Sunset` (RFC 8594) headers, with `Link: <successor>; rel="successor-version"` when
   there is one.
2. The deprecation date, the sunset date and the removal condition are recorded in the release notes and
   in `docs/api-routes.md`; the sunset is at least one release after the deprecation.
3. Removal happens only after the sunset **and** the condition (for the legacy aliases: every caller in
   `docs/api-routes.md` has moved). Today the legacy browser aliases are deprecated
   `@1790294400` (2026-09-25) with sunset Wed, 31 Mar 2027.

## Errors

Every refusal is `{error, code, message, remedy, docs, request_id}`. `code` is stable; `error` equals
`message` and is kept for clients written before `message` existed. New fields may be added to this
envelope; none is removed without a transition.
