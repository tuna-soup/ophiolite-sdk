# Changes

## 0.1.0 — unreleased

Supported 0.x client over preview contracts, installable from reviewed source.
No PyPI/npm publication, stable 1.0 or production-support promise is claimed.

- Revision manifests /2 (E30a, asset contract 1.11.0): the reader accepts `ophiolite.revision-manifest/2`,
  whose digest also covers the declared `method` (`MethodRecord`: name, library, version, parameters,
  script digest), and requires it to be the descriptor's `derivation.method`; a `/1` manifest verifies
  exactly as before. `Asset.parents` holds up to 32 parents.

- Project events (E28): `client.sync(path)` returns a `Sync` that keeps a local copy of a project current
  from its event log — `run()` resynchronises the first time (entities, `catalog/inventory`, result
  groups, stamped with the head captured first) and catches up afterwards; `changes(epoch, after)` pages
  the log; `follow()` streams it as server-sent events and resumes with Last-Event-ID; a durable
  `Checkpoint` advances only after a batch's reads landed. `ResyncRequired` (`resync-required`) is the
  server's CURSOR_EXPIRED. `ophiolite.sync_cache.Cache` implements the fencing rules. Skill
  `sync-a-project`.

- Application reach (E27): `ophiolite.connect(url, credential)` returns an `Account` whose
  `projects()` and `organizations()` list what the credential reaches before a project is chosen
  (one project for an access key or an approved application; every project for a browser sign-in),
  and `account.client(project)` opens the ordinary project client. `Credential.discovery_headers(url)`
  serves those two calls only. `ophiolite projects` and `ophiolite orgs` print the same (`--json`).
  `device_login` asks for capability 3, which adds the project's data reads and discovery to the
  application operations and no new writes.

- Access keys (E25a): `ophiolite login --key` (or `auth.key_login`) saves an access key created on
  the account page as its own credential kind, used as a plain Bearer by later processes;
  `OPHIOLITE_ACCESS_KEY` alone is used for one process and nothing is saved. `status` is local for a
  key; `logout` removes only the local copy (remove the key on the account page to stop it).
  `Credential.kind` and `Credential.summary()` describe a credential without its secret.

- Recipe-read point sets (E23a): Petrel points-with-attributes and OpendTect x-y-z
  horizon exports read as `PointSet` with `version == 2`: number, text and category
  attribute columns (`Float64`, `string`, `category`) named by their grammar-safe
  names, exact labels in `frame.attrs['source_names']`; `decisions` (`Decision` with
  its `Evidence`), `status`/`unresolved` (`needs-decision` while any field of context
  is undecided) and `recipe` (`Recipe`). Typed data is verified against the normalized
  profile its descriptor names, and the exact artifact is matched by kind. Portable
  export refuses these assets until bundles can hold the source package.

- E7 transition release: `share()` requires `expected_generation` (from
  `grants()`); servers refuse unconditional replacement with 428 `condition-required`.

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
- Result groups and diffs (E8): `result_groups()` lists the groups you can see with only the
  members and recommendation you may open; `diff(a, b)` names parameter, input and sample
  changes between two exact result versions.
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
