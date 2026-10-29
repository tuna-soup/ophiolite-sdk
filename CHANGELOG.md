# Changes

## 0.1.0 — unreleased

Supported 0.x client over preview contracts, installable from reviewed source.
No PyPI/npm publication, stable 1.0 or production-support promise is claimed.

- What is gone from a source (E122 slice 2): `ophiolite upload PATH --source NAME --complete` says the folder is
  everything in that source (`--scope DIR` for one folder of it); a file the source sent before and this send does not
  list is marked gone (nothing is removed), and the report prints the server's sentence as served, e.g. "Not in this
  complete send of Petrel export, so marked gone from the source: `wells/b.las`. Nothing was removed." `--incremental`
  (the default) marks nothing; a source emptied completely is not marked gone. `--complete`, `--incremental` or
  `--scope` without `--source` is a usage error (exit 2, nothing sent). `upload(source_name=, send=, scope=)` sends the
  fields only when given; `Provenance.gone` is the served flag (source, path, run, time and sentence) or None. An
  unfinished upload is continued only when its source name, send and scope are the ones given (an SDK of 2026.10.117
  or earlier continues by its listing, and the send then finishes as it was declared).
- `ophiolite outcomes` declares what a project accepts for residual results (E120 slice 0, contract
  `ophiolite.outcome/1`): `declare --label "Tops within 5 m" --tolerance 5 --procedure NAME --destination NAME`
  (project administrators) prints 'Declared "Tops within 5 m" (enabled, version 1): residual results, every computed
  residual within 5 m; rows not computed are allowed; delivered to Team database.'; `revise NAME` writes the next
  version only when something differs, `enable`, `disable` and `withdraw NAME` change its state (a withdrawn name is
  free again), `list` and `get NAME` read it for every member, with every version and action. Names are words and are
  compared without case. `Client.outcome_declare/revise/enable/disable/withdraw/list/get/named` do the same and
  `ophiolite.outcomes.residual_declaration` builds the declaration. A refusal keeps the server's sentence and its closed
  reason in `error.details['reason']` (`outcome-refused`); a permission refusal exits 3. Nothing is evaluated or
  gated in this slice.
- The well-residual/1 contract (E119b slice 0): `validate.typed_pair` reads an `ophiolite.well-residual/1` pair (one
  row per top, each the residual top MD minus the used crossing's MD in metres, or one of nine reasons it was not
  computed) as `typed.WellResidual` (`rows`, `surface`, `to_frame()`), and refuses a payload whose digests are valid but
  whose rows disagree: "A residual is not its top's measured depth minus the used crossing's", "A row gives a residual
  or a reason, not both", "Rows and their context disagree". A tops context may state its `depth_datum`. A deployment
  refuses to save a residual result in this version; a procedure run publishes one from slice 1.
- Residual at wells, the reference procedure (E119b slice 2): `ophiolite.residuals.reference_path()` is the packaged
  procedure `residual-at-wells` (settings `formation` and `display_unit` only). `residuals.prepare(client, selection,
  surface, formation)` binds before anything is computed: the tops linked to each member's wellbore are found through
  every association page, and it refuses with one sentence when two tops sets are linked to one wellbore, no selected
  wellbore has a top named the formation, no member has a trajectory, the selection needs more than 32 versions, a
  member's tops are not in metres or name another depth datum than its trajectory (compared without case or spaces),
  or the geometry cannot place a member. `residuals.run` runs the procedure through `procedure_run`, and
  `ophiolite residuals run NAME --selection @ASSET:REVISION --surface @ASSET:REVISION --formation DCC --output FOLDER`
  does the same from the command line (nothing is published); the result is
  `ophiolite.well-residual/1` with one row per top named the formation (occurrences in md order, ties in file order):
  the residual top MD minus the nearest crossing's MD (the shallower on a tie), or a reason it was not computed, with
  `between` for `grazing`, `along-surface`, `uncertain` and `many-crossings` (more than 64 crossings) and none for
  `no-surface-data`. `writers.well_residual(document)` writes the document. No GDAL is needed.
- The well-set/1 contract (E119a slice 0): `validate.typed_pair` reads an `ophiolite.well-set/1` pair (a label and 1 to
  29 members, each a well and a wellbore by id with one trajectory revision and its frame, or neither) and refuses a
  payload whose digests are valid but whose members disagree: "A wellbore appears twice in the set", "A member has a
  frame without a trajectory, or a trajectory without a frame", "Members and their context disagree". A deployment
  refuses to save a set in this version; saving and reading one back come with slice 1.
- Private well sets (E119a slice 1): `client.well_sets` saves a set (`save`), adds its next version (`new_version`),
  lists your sets (`list`) and reads one at an exact version as `typed.WellSet` (`label`, `members`, `to_frame()`).
  `from_list(label, wellbores, frames=, choose=)` builds the document from wellbores: each takes the well it is part
  of and its one deviation survey; where a wellbore has two or more trajectory versions it is refused until `choose`
  names one by its label, and the refusal lists the versions by readable label or "Trajectory version of <date>",
  never by an identifier. A set is saved with no audience and stays with its author: the server checks every member
  (well and wellbore readable and associated, trajectory a usable deviation survey of that wellbore, frame CRS
  projected in metres) and refuses each sharing route. A server refusal reads as the server's own sentence, member by member, with its closed reason and field
  (`members[1]`) in `Refused.details`; this holds for every refusal that states a closed reason.
- One trajectory geometry, and a member placed in the world (E119a slice 2): `ophiolite.geometry` runs the contract
  module `contracts/geometry/v1/trajectory.py`, the file the Platform runs too (`minimum_curvature`, `interpolate`,
  `place`, `offset_bound`, `refusals()`). `Trajectory.minimum_curvature()`, `typed.minimum_curvature` and
  `transform.vertical_depth` now compute through it and give the same results as before within 1e-9 m, with the same
  refusals and no new dogleg limit. `client.well_sets.bind(well_set, member, surface)` checks one member again on the
  server (as at saving; nothing is stored), reads its trajectory at the saved version and returns `Bound`: `stations`
  `(md, x, y, z)` in the frame's coordinate system with z the depth below the frame's datum, `positions(mds)` and
  `surface_sign`. Otherwise it refuses with one sentence naming the member: the server's reason (`well-set:<key>`) or
  what the geometry cannot place (`geometry:<key>`: north, datum, coordinate system, units, a surface in time, tie-in).
- Every crossing, or why not (E119a slice 3): `ophiolite.intersection.crossings(bound, surface)` takes a member bound
  with `client.well_sets.bind` and the grid surface read with `client.read_data`, and returns every crossing the one
  geometry can prove (`md`, bracketed by `low` and `high` to 0.01 m) or rows naming why a crossing is not given, one of
  `grazing`, `along-surface` ("within 0.01 m of the surface from about <a> to about <b>"), `uncertain`,
  `no-surface-data`, `ends-above`, `starts-below` and `no-trajectory` (`bound` None), with `coverage` and the
  evaluation count. `intersection.nearest(result, md)` picks the crossing nearest a measured depth (the shallower on a
  tie) only with full coverage and no blocking row, and otherwise names the reason; `intersection.reasons()` gives each
  reason's sentence. A surface the member cannot be placed against is refused as `bind` refuses it (`geometry:<key>`).
- `ophiolite upload FOLDER --source NAME` names where the files come from (E122 slice 1): sending the folder again
  under the same name prints the project's sentence after the report line, "Compared with the last send of Petrel
  export: 2 unchanged, 1 changed, 0 new."; an unchanged file is not added again and a changed one is its result's
  next version. `UploadRuns.upload(..., source_name=NAME)` does the same and `Report.text` prints the served sentence as
  served; without a name the report is the line it was. The `deliver --item` label is not part of this slice.
- `ophiolite deliver` recovers a delivery whose computer stopped (E109 slice 2, no contract change): the next run of
  the same procedure in the folder never runs the writer again. It calls the manifest's `reconcile` (`module:function`,
  run from the pinned copy only with the attempt's configuration), whose `delivered(items=N)` is sent,
  `ophiolite.not_delivered()` not sent (only after the destination committed a tombstone for the id), and anything
  else, `ophiolite.unknown()` or an error included, "Outcome unknown for ... It was not sent again."; without a
  `reconcile` the outcome stays unknown. `--wait SECONDS` waits for a writer still running on this computer ("This
  delivery is still running on this computer; try again when it has finished."), and `--set-aside` records the
  outcome as unknown in the project and moves `attempt.json` to `set-aside.json`, exit 0. The tops-to-team-db example
  declares `reconcile` (a `withdrawn` row in `team.deliveries`, which gains a nullable `items` column).
- `ophiolite deliver NAME --system SLOT=FILE --item SLOT=ITEM[@N]` delivers (E109 slice 1, no contract change): a send
  procedure of the project's catalogue (`--version`, `--yes` as for `source run`) runs once on this computer with exact
  versions (read by `Exchange.read_exact`, which never changes what the folder holds) and its outcome is reported to
  the project: "Sent to Team tops database by Tops to team DB on this computer: 3 items.", "Not sent to ...", or
  "Outcome unknown for ..." when the writer said nothing valid; exit 0 only when sent and recorded. The entry is
  `entry(inputs, settings, delivery)` with `delivery.id` and `delivery.system`; it returns `ophiolite.delivered(items=N)`
  or `ophiolite.refused(reason)` (the reason stays on this computer). The attempt is written under
  `.ophiolite-held/deliveries/` before the writer starts and holds no configuration; a delivery whose outcome is not
  known yet is never sent again ("This delivery's outcome is not known yet; it cannot be sent again."). Refused before
  anything starts: Windows, an unbound or ambiguous item, an unreadable version, a setting that looks like an address or
  a password, and the catalogue's own refusals. `--set-aside` comes with a later release. `procedures new --step send`
  writes a send scaffold; `ophiolite.testing.MemoryDeliveries` keeps deliveries by the server's rules for tests.
- A send procedure names its destination and returns a delivery (E109 slice 0, contract only; procedure rules 1.1.0,
  registry 1.46.0). A send procedure reads one or more versions and at most one team's system, and may name a
  `reconcile` function (`module:function` of its folder); `ophiolite procedures validate` says "Valid: Tops to team DB,
  version 1. It reads Well tops (CSV) and Team tops database and makes a delivery." and refuses two systems or a bad
  `reconcile` in words. `ophiolite.models.delivery` holds the closed payload `ophiolite.delivery/1` (`Delivery`:
  `delivery_id`, `state` confirmed, not-sent or unknown, `items` 0 to 1,000,000), checked by the packaged contract file
  `contracts/procedures/v1/delivery.py` (the server runs the same file), and the report body `DeliveryObservation`
  (profile `procedure-delivery/1`). `ophiolite deliver NAME --system SLOT=FILE --item SLOT=ITEM[@N]` exists and refuses
  with "Delivering to a team's system is not available on this deployment yet." (reason code `not-available-yet`,
  exit 1), reading and writing nothing; running a send procedure with `procedures run` is still a later release. The
  generated client gains `activity/deliver` and `activity/deliveries`, which the server does not serve yet.
- The upload receipt carries the digest of the stored bytes (E108 slice 0, additive): `UploadResult.sha256` is the
  server's `sha256` field, or `None` from a server before E108; it is kept as given, beside `revision`, which may differ
  from it when a version's identity is given by a rule. A scientific asset's `acquisition.sourced_by` (scientific-asset/1
  1.25.0, registry 1.39.0) names the source procedure that made an uploaded file from a team's system. A bundle import
  keeps it as the exporting project recorded it, in `acquisition.origin.sourced_by` (E108 slice 1; scientific-asset/1
  1.26.0, registry 1.40.0). `ophiolite source run NAME --system SLOT=FILE` (`Client.source_run`) runs a source
  procedure of the project on this computer and adds what it makes through one upload: each file names the version,
  the team's system in words (`--system-label`, default the procedure's name for it) and its output role, and the
  server records `sourced_by` from its catalogue. The configuration, log.txt and run.json are never sent. A setting
  whose resolved value (a default included) looks like an address or a password is refused before the run ("A setting
  looks like an address or a password; put it in the system configuration on this computer."). E108 slice 1: the first
  run; a later run that finds a changed version comes with a later slice. E108 slice 1 (amendment B6): a run whose
  files are not all added, or whose upload fails after the procedure ran, keeps **only the outputs** in a new folder
  and returns its path (`kept`, also on the exception) with the line "The files the procedure made are kept in PATH.
  To add them by hand: ophiolite upload PATH"; its log.txt and run.json are never in that folder. The report names
  each file by its output label; a system label that does not read as a name is shown as "a team's system" (the folder
  as "Team system") while `source.system` keeps it exactly; a version that is not available is named by its label or
  "this procedure" (the catalogue name stays in `--json`'s details). New reason codes a source file may end with:
  `source-changed`, `source-shared`, `source-audience`, `source-withdrawn` and `source-several`, each with its sentence.
  E108 slice 2: a later run becomes a version. `source run --work DIR` (default `.ophiolite-held`, as
  `check`/`get`/`send`; `Client.source_run(work=)`) remembers each output's item and version by procedure, system and
  role: a run whose files and declarations equal the held ones sends nothing ("nothing-changed"); otherwise each file
  is sent as the next version of its item, and a version added meanwhile is E70's `newer-version-exists`, named from
  the item's history. A run that stops part way is completed by the next one under the same command id without running
  the procedure again. A receipt is checked by its `sha256` when the server gives one (`publish.receipt_matches`),
  since a version added by upload has a revision that is not the bytes' digest. An uploaded item's history is readable
  (`kind` `uploaded`). New reason codes: `newer-version`, `earlier-version`, `version-refused` (registry 1.41.0).
  E108 slice 3: a colleague receives the newer version. `check` names a version 2 added by upload or by a later source
  run, and `get` saves it with its number (a well log with its curves; a version 2 that changed only its declarations
  keeps the same file and a new descriptor). This amends E70a's adapter row 127 (the refusal of a newer version of an
  uploaded item, `cannot-read-here`, is gone). Sending content equal to an earlier version, not the latest, is the new
  outcome `earlier-version` ("This content was version N on D.", the day in UTC; exit 4), apart from `nothing-changed`
  for the latest version's content. The What's next card gives such a version its kind's command (registry 1.42.0:
  qgis-reach/1 drops its `uploaded-successor` row).
- Tables kept as they are and file downloads (E58b, preview API): `client.imports.from_table(path, "table",
  columns={column: {'unit', 'quantity', 'missing', 'description'}})` keeps a CSV, Excel or Parquet file as it is;
  `client.read_data(asset, revision)` returns `Table` (`rows`, `columns`, `key`, `declarations`, `units`, `not_read`
  with one warning naming those columns, and `to_frame(missing=, decimal=)` on the frame code of SQL tables read as
  tables). `client.export_file(asset, revision, path, format=, curves=)` and `Table.download(path, format=)` save an
  exact revision (a kept table, tops, a trajectory, a point set or a LAS log) as one Parquet, GeoParquet (point sets)
  or CSV file written by the server; `source.read().download(path, format=)` saves a connected SQL table. Every
  download is checked against the digest and the revision the server states, through the same partial-file rule as
  `download_original`, and nothing is saved otherwise; a connected selection that moved since the read is
  `SourceRevisionDiffers`, one that can no longer be read keeps the server's refusal. No pyarrow is needed to download.
  Command line: `ophiolite read-data --asset A --revision R --format parquet|geoparquet|csv --out FILE [--curve C]`.
  Gallery: "A spreadsheet and a database, joined".
- A scientific read refused with 422 (`Incompatible`) now carries the server's own sentence as its message when the
  server gives one (for example why an export cannot be written); without one, the message stays "This scientific
  context is not supported." (H48).
- Colleagues sign in to your application (E33, preview API): `ophiolite.oauth_app.OAuthApp(url, application, client_id,
  redirect_uri, store=FileStore(dir), client_secret=...)` runs your server's own leg with the identity provider
  (`begin()`/`callback()`: code + PKCE S256 with your registration's client, state and nonce checked), sends the person
  to Ophiolite's consent page (`consent_url()`/`consented()`), and exchanges the provider token and the consent handle
  for an opaque application credential (`credential(person)`, `client(person, project)`). Provider tokens, the handle
  and the credential stay in the server-side store, one private file per person; refreshes of one person are
  serialised, a rotated refresh token is written before the exchange that uses it, and a lost rotation or a removed
  approval raises `SignInRequired` or `ConsentRequired`. The map-application template gains `server/sign_in.py`.
- Buckets as sources (E59, preview API): `client.browse(connection, prefix=None, cursor=None)` answers one page of a
  storage connection's folder (subfolders, then files with their size, tag, the kind their name suggests and whether
  it is read in place; `next_cursor` continues it). `client.import_storage(connection, prefix, keep_copy=False, ...)`
  adds every file below the folder in one upload and returns its `Report`: read from your storage each time, or with
  `keep_copy=True` added as a copy when the organisation allows copies. The gateway reads each object with your own
  sign-in to the storage; the SDK sends the connection and each key, never a file byte, and takes no storage key.
  An object above the deployment's request limit is left out with its sentence (`report.left_out`). Command line:
  `ophiolite sources browse CONNECTION [--prefix P] [--cursor C]` and `ophiolite sources import CONNECTION [--prefix P]
  [--keep-copy] --attribution A --rights-confirmed [--report r.csv]`; `list`, `describe` and `read` are unchanged.
- A project's catalogue of procedures (E105b): `ophiolite procedures register <folder>` keeps a private version
  (`list`, `show NAME [--version N]`; administrators `enable` and `withdraw`; `trust NAME --version N`), and
  `procedures run --from-project NAME [--version N]` runs the highest enabled version, or the numbered one you can
  see, on this computer. A version someone else registered asks once, with who registered it, the date and the
  exact digest, before anything runs (`--yes` answers it); the answer is recorded as your trust. Before every run the
  version is read again (a withdrawal ends it) and the local copy is checked by digest; `procedures.run` takes
  `expected_digest=` and refuses `changed-before-run` when the copy that would run is another. `Client.procedure_*`
  give the same from Python; a refusal keeps the server's sentence and its closed `reason`.
  The gallery notebook `share-a-procedure` shows both sides; `ophiolite.gallery.colleague()` gives a notebook a
  second member's client (`gallery.use(client, colleague=...)`, or `OPHIOLITE_COLLEAGUE_ACCESS_KEY`).
- When access ends (E67a, read-only): `Account.projects()` rows always carry `access_ends_at`, the instant (UTC) your
  direct grant on that project ends, or `None` when it does not end (no end date, or a team also gives access); a
  project whose access has ended is not listed. `ProjectEntry` declares the field (a number is refused).
  `ophiolite projects` prints the last permitted day as a UTC date in every zone ("ends 14 Nov 2026" for
  `2026-11-15T00:00:00Z`); `--json` carries the instant. The gallery notebook "Who has access, and until when" reads
  your own ends and, for a project administrator, who has access through what and until when (`access/effective`);
  the synthetic server answers both. No SDK write method sets an end date.
- Wells from SQL Server and Oracle (E61): a source selected from a SQL Server or Oracle table reads like any other
  (`client.source(id).read(expect_revision=...).to_frame()`). Gallery: "Wells from SQL Server and Oracle".
- Grids and GIS files (E56, preview API): `client.read_data` returns `FeatureSet` for map features from a Shapefile,
  a GeoPackage layer or a GeoJSON file (`features` in file order with coordinates as stored, `fields`, `to_frame()`
  with one row per feature), checked offline against the server's rules; ZMAP+, CPS-3 and IRAP grids read as
  `GridSurface`. `upload` answers a question a file asks only once it is read (a GeoPackage layer, a grid's corners)
  from `declare` and sends it again, at most three sends; `declare` also takes a file's path,
  `{'a.gpkg': {'ogc-geopackage/1': {'layer': 'fields'}}}`, which wins over its kind field by field. An open file is
  refused with a sentence; pass a path. Portable bundles carry GeoJSON and GeoPackage feature sets and the new grid
  formats at 2.7.0; a Shapefile-read feature set is not exported yet (its companion files), and a CPS-3 grid is
  imported by uploading its file again.
- Organisation connections (E39, preview API): `client.org_connections(organization_id)` lists the organisation's
  database connections you use or administer (with an access key, only those you use, in the organisation of its
  project), each with your own access and readiness; it reads the projectless `/api/v1/org-connections/list` and
  refuses an answer outside its shape or for another organisation (`VerificationFailed`). Sign-ins and passwords are
  never answered. Command line: `ophiolite org-connections list --organization ID [--json]`.

- Checks against a reference (E96): `client.check_publish(folder)`, `check_list(asset=, revision=)` or
  `check_list(implementation=, version=)`, `check_compare(asset, revision, file, curve=, tolerance=)` and
  `check_publishers(action, principal, kind=)`; `ophiolite checks publish | list | compare | publishers add|remove|list`
  print them in words and `--json` prints the route's answer. A check refusal's field (`reference.digest`, `timeout`, …)
  is on the error (`error.details['field']`, `"field"` in `--json`) and never in the sentence; a check refused at 503
  (past the wait, or busy) is not retried. `ophiolite check` (E70a) is unchanged.
- Curve windows (E100a): `Client.curve_window(asset, revision, curve, top, base, level=|rows=)` (and `AsyncClient`) reads
  the depth window of one exact curve, page by page, verified against the curve's descriptor: every sample at level 0,
  blocks with their extrema above it. A `CurveWindow` is for display: `to_numpy`, `write_curves` and
  `validate_derived_curves` refuse it. `ophiolite curves window` prints or writes the same document. The model
  generator no longer applies a sibling type's constraints to `null`.
- Agents on the record (E95): `AgentClient.propose(..., evidence={instruction, model, conversation, client})` records
  what the person asked, the model the agent reports and where its conversation lives; `execute(..., evidence=id)` sends
  the record's id as `X-Ophiolite-Evidence`; `wait(plan, evidence_id=id)` returns only once the approval names that
  record; `run(..., evidence=...)` does all three. `CHANGES` adds `results/remake-run`. The reported provider and model
  are set as `gen_ai.provider.name` and `gen_ai.request.model` (OpenTelemetry semantic conventions 1.37.0) on the
  caller's current recording span; no span is created and the instruction never reaches telemetry (extra `telemetry`).
  Breaking for approvers: `agents/approve` now needs `evidence` (an id or null) and `evidence_generation` and refuses
  a body without them, naming the field; there is no compatibility window. The SDK pin advances with the release that
  carries this change; an older gateway refuses the `evidence` field and the library does not retry without it.
- Tables to typed sets (E87, preview API): `client.imports.from_table(path, target, mapping, dry_run=...)` reads a CSV or
  Excel table (kept as your private input), previews what would be added and, unless `dry_run`, starts the reviewed
  run and steps it to the end: wells, well tops, deviation surveys, point sets or time-depth pairs, one set per well.
  `ophiolite import table FILE --target T --map FIELD=COLUMN [--dry-run]` does the same, and `import list|status|pause|
  resume|cancel ID` reads and steers a run. The review and result are in the workspace's words, one line per set;
  each refusal is said in its sentence with the service's own text as `server_message`.

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
