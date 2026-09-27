# Changes

## 0.1.0 — unreleased

Supported 0.x client over preview contracts, installable from reviewed source.
No PyPI/npm publication, stable 1.0 or production-support promise is claimed.

- Sync and async exact curve reads with typed contracts, scientific verification,
  NumPy/DataFrame views, descriptors and exact Workspace links.
- SDK-owned browser credentials, bounded local validation, publication work folders,
  recovery and explicit sharing. Local execution remains local.
- Result versions: `publish(..., new_version_of=receipt)` adds the next version of
  your own result with the reviewed revision as expected parent (a newer head is
  refused); `history(asset)` lists every version; summaries carry
  `revision_number`/`revision_count` and a derived `input_update` flag.
- Conditional sharing: `grants().generation` and `share(..., expected_generation=)`
  with one idempotent replay after a lost response; a replay never undoes a later
  revocation. Unconditional `share()` is deprecated for one transition release.
- Typed data (E11): `read_data(asset, revision)` returns `WellTops`, `Trajectory`
  or `GridSurface` with the exact original, verified descriptor and data (DataFrame
  and array views); `Trajectory.minimum_curvature()` is an explicit calculation of
  offsets from the first station. `ophiolite read-data`. Portable bundle 2.0 carries
  all four types; curve-only exports stay 1.0.
- SDK CLI with transitional pilot compatibility modules, generated TypeScript
  transport, four tested starter templates and six packaged workflow guides.

- POSIX CLI calculations create private output files by default, including on macOS.
  Checkpoint permission errors retain their actionable diagnostic.

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
