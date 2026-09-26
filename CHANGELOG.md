# Changes

## 0.1.0 — unreleased

Supported 0.x client over preview contracts, installable from reviewed source.
No PyPI/npm publication, stable 1.0 or production-support promise is claimed.

- Sync and async exact curve reads with typed contracts, scientific verification,
  NumPy/DataFrame views, descriptors and exact Workspace links.
- SDK-owned browser credentials, bounded local validation, publication work folders,
  recovery and explicit sharing. Local execution remains local.
- SDK CLI with transitional pilot compatibility modules, generated TypeScript
  transport, four tested starter templates and six packaged workflow guides.

### Breaking and migration

Fresh SDK login replaces use of the old pilot credential cache. Never copy the old
cache into the SDK namespace. `ophiolite-cli` 0.3.0 compatibility modules are
retained for one announced transition release and removed in the first versioned
E10 release afterward. Retain the original private work folder for recovery;
sharing is a separate action and is never retried automatically.

### Version policy

Python and TypeScript share 0.MINOR.PATCH and one tag. PATCH: fixes and additive
APIs. MINOR: breaking changes documented here, with a one-minor shim where feasible.
A new schema suffix requires a new model and MINOR. 1.0 requires supported registry
entries for all SDK reads and stable versioned OpenAPI. See README.md for scope,
licensing and separate publication/service release gates.
