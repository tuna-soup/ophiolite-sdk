# Changes

## 0.1.0 — unreleased

Supported 0.x client over preview contracts, installable from reviewed source.
No PyPI/npm publication, stable 1.0 or production-support promise is claimed.

- Curve windows (E100a): `Client.curve_window(asset, revision, curve, top, base, level=|rows=)` (and `AsyncClient`) reads
  the depth window of one exact curve, page by page, verified against the curve's descriptor: every sample at level 0,
  blocks with their extrema above it. A `CurveWindow` is for display: `to_numpy`, `write_curves` and
  `validate_derived_curves` refuse it. `ophiolite curves window` prints or writes the same document. The model
  generator no longer applies a sibling type's constraints to `null`.
- Organisation connections (E39, preview API): `client.org_connections(organization_id)` lists the organisation's
  database connections you use or administer (with an access key, only those you use, in the organisation of its
  project), each with your own access and readiness; it reads the projectless `/api/v1/org-connections/list` and
  refuses an answer outside its shape or for another organisation (`VerificationFailed`). Sign-ins and passwords are
  never answered. Command line: `ophiolite org-connections list --organization ID [--json]`.

- Agents on the record (E95): `AgentClient.propose(..., evidence={instruction, model, conversation, client})` records
  what the person asked, the model the agent reports and where its conversation lives; `execute(..., evidence=id)` sends
  the record's id as `X-Ophiolite-Evidence`; `wait(plan, evidence_id=id)` returns only once the approval names that
  record; `run(..., evidence=...)` does all three. `CHANGES` adds `results/remake-run`. The reported provider and model
  are set as `gen_ai.provider.name` and `gen_ai.request.model` (OpenTelemetry semantic conventions 1.37.0) on the
  caller's current recording span; no span is created and the instruction never reaches telemetry (extra `telemetry`).
  Breaking for approvers: `agents/approve` now needs `evidence` (an id or null) and `evidence_generation` and refuses
  a body without them, naming the field; there is no compatibility window. The SDK pin advances with the release that
  carries this change; an older gateway refuses the `evidence` field and the library does not retry without it.

- Well files (E57, preview API): `client.read_data` returns `TimeDepth` for a time-depth table (`pairs` in file order,
  `context` with the declared depth type, time kind, units and datum, `to_frame()` with a nullable `Float64` velocity
  so an empty cell stays missing). `ophiolite.writers.write_time_depth(pairs, *, depth_type, depth_unit, time_kind,
  time_unit, datum=None, seismic_reference_elevation=None)` writes `time-depth-csv/1` (every declaration required,
  "unknown" allowed; depth and time strictly increasing), publishable with `publish_derived` and
  `ophiolite publish-derived --profile time-depth-csv/1`. Portable bundles carry time-depth tables at 2.6.0, and an
  import declares the seismic reference elevation as its canonical decimal text. LAS uploads read LAS 1.2 and 3.0 as
  delivered; the kind is named "Well log (LAS)".
- Well imports (E42a): `client.well_imports()` previews, starts, steps (`run`), reads, lists and cancels an import of an
  approved well table as wells; `ophiolite well-imports list|status|start [--dry-run]|resume ID|cancel ID` does the same
  and prints every skipped row with its reason. Answers are checked against the pinned contract.
- Wavelets and sections you compute (E53, preview API): `client.read_data` returns `Wavelet` (samples, `spectrum()` and
  `peak_frequency()` on a 1 Hz grid to Nyquist, `frequency_note()` beside the declared frequency), `ModelSection`
  (rocks and a rock-index grid) and `SeismicSection` (every sample, `origin`, `polarity`), checked offline against the
  server's rules. `ophiolite.synthetics` computes `ricker`, `ormsby`, `impedance`, `reflectivity`, `convolve`
  (numpy's mode 'same'), `wedge`, `synthetic(model, wavelet)` and `tuning_thickness` in plain Python; nothing is
  resampled, converted or padded, and each result carries the `method` record to publish it with. `Wavelet.write`,
  `ModelSection.write` and `SeismicSection.write` write the Connectors' text formats. `upload_data(append_to=...,
  expected_parent=...)` adds a version to your own uploaded wavelet, model or section (both or neither). Portable
  bundles carry the three types at 2.5.0; importing one skips a synthetic section with its reason. Two gallery
  notebooks: Make a wavelet, Make a wedge model.

- Shale volume from gamma ray (E52, preview API): `ophiolite.petrophysics` reads the five methods (linear,
  Larionov Tertiary and older rocks, Clavier, Steiber), their constants and the percentile rule from the packaged
  table `ophiolite.shale-volume-methods/1`, the same table the server's calculation uses. `shale_volume(values,
  method=, clean=, shale=)` keeps missing samples missing; `picks_from_percentiles(depth, values, top, base, low=5,
  high=95)` uses type 7 percentiles over [top, base); `shale_volume_method(...)` is the method record the server
  records for the same calculation (library `ophiolite`), refusing an unlisted quantity or an output that is not a
  curve; `calculation_record(...)` is the file's sentence. `write_curves(..., notes=[...])` writes an `~Other`
  section. `ophiolite.gallery.connect()` gives a notebook its client: the packaged synthetic server when
  `OPHIOLITE_URL` is unset, the client a harness bound with `gallery.use(client)`, else the saved sign-in or
  `OPHIOLITE_ACCESS_KEY`. The synthetic server (`ophiolite.testing.synthetic_server`, moved from the templates'
  `support.py`, which imports it) now adds versions to a derived publication with the server's rules and serves
  its read-back and version history. The contract snapshot carries one third-party file, an attributed excerpt of
  NLOG's HONSELERSDIJK-GT-01 log (THIRD_PARTY.md); the public-input check accepts it only with that attribution.

- A connection that works or says which step failed (E51a): one reader (`ophiolite.credential_input`) for every key
  you supply (`--key`, `--key-file`, `--key-stdin`, `OPHIOLITE_ACCESS_KEY`, `Credential.bearer`, `key_login`) trims a
  line break, spaces and a stray `Bearer `, says what it removed (never the value) and refuses only an empty value, a
  space or line break inside, or a control character. `ophiolite doctor --online [--url U --project P]` reports six
  stages — address, tls, credential-arrived, credential-accepted, project-readable, features — stopping at the first
  failure with the server's sentence, stage and remedy, and exits with that stage's code. SDK errors carry the
  server's `stage` and sentence (`error.stage`, `error.server_message`); categories for 401 and 403 are unchanged.

- Wording (owner decision #19): the command line and its errors call the account page's keys **project access
  keys**; nothing else changes (the `--key` option, `OPHIOLITE_ACCESS_KEY`, the saved credential kind and the wire
  format are as before).
- Derived publication (E30b): `ophiolite.writers` (also `WellTops.write`, `Trajectory.write`, `GridSurface.write`,
  `TriangulatedSurface.write`, `PointSet.write`, `PolylineSet.write` and `Curve.write` for LAS 2.0) write a result
  made in Python as the exact file an upload of its type would be, with every declaration required ("unknown" is
  an answer) and values the format cannot carry refused. `Client.publish_derived(written, name=, from_=, method=,
  command_id=)` publishes it from 1-32 exact parents with the declared method (a required command id; a retry
  with the same id returns the same receipt); `WorkFolder.publish_derived` saves the command id and the file's
  digest first and recovers after a crash or a lost reply. CLI `ophiolite publish-derived` (`--command-id` or
  `--work`); skill `derive-and-publish`. `Client.history` names a publication's method in words. Free-form JSON
  objects in contracts are generated as `dict[str, Any]`.

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
