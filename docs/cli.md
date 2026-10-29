# The `ophiolite` command line: exit codes, `--json` and `--dry-run`

Run it as `ophiolite <verb>` (the installed script) or `python -m ophiolite <verb>`.

## Exit codes

| Code | Meaning | Typical cause |
|---|---|---|
| 0 | Done | |
| 1 | Refused or invalid | A field the server or the SDK refused (`INVALID_ARGUMENT`), an answer outside its documented shape, a local file problem |
| 2 | Usage | An unknown verb, option or choice (argparse) |
| 3 | Sign-in or permission | 401 or 403: sign in again, or use a credential that reaches the project |
| 4 | Not found or conflict | 404, 409 or 410: list again, or read the current state and repeat the change |
| 5 | Busy or unavailable | 429 or 503 after the retries, or no answer from the server |

## `--json`

Every verb accepts `--json`. The result is one JSON object on standard output:

| Verb | Shape |
|---|---|
| `projects` | `{"projects": [{id, name, role, can_administer, organization_id}]}` |
| `orgs` | `{"organizations": [{id, name}]}` |
| `entities` | `{"entities": [{entity_id, kind, name}]}` |
| `wells list` | `{"wells": [{entity_id, name, location}], "crs", "untransformed"}` |
| `wells list --with-source` | the same, each well with `source: {state, reason, row}`: `state` is `joined`, `no origin` or `not readable`; `row` the original columns asked for with `--column NAME` (repeat; default all), null unless joined |
| `wells extent` | `{"extent": {crs, bbox, count, untransformed}}` |
| `changes head` | `{"head": {epoch, cursor}}` |
| `changes list` | `{"changes": [event]}` |
| `changes follow` | one event object per line, as they happen |
| `sources list` | `{"selections": [selection]}` (the selections you bound; every profile) |
| `sources describe ID` | `{"source": {id, name, profile, revision, sha256, bytes, crs, row_count, columns, mapped_columns, mapping, null_counts, unresolved}}` |
| `sources read ID` | `{"source": {id, name, profile, revision, sha256, crs, original, columns, row_count}, "rows": [row]}`; with `--out`: `{"source": {…}, "out": path}` |
| `well-imports list` | `{"imports": [import summary]}` |
| `well-imports status`, `start`, `resume`, `cancel` | `{"import": import}` (the documented `WellImport`: state, words, reason, counts, skipped, superseded, …) |
| `well-imports start --dry-run` | `{"preview": preview}` (counts, skipped rows, possible duplicates, wells already here) |
| `import table FILE --dry-run` | `{"preview": preview}` (the documented table-import preview: sets per well, skipped rows, sets not added, room) |
| `import table FILE`, `import resume ID` | `{"import": run, "preview": preview}` (`preview` only for `table`; the run: state, words, reason, counts, one unit per set) |
| `import list` | `{"imports": [run summary]}` |
| `import status`, `pause`, `cancel` | `{"import": run}` |
| `upload` | `{"upload": report}` (the documented `UploadRun`: state, label, counts, and every file with its state, kind, what was read, sentence and item) |
| `publish-derived` | `{"published": receipt}` |
| `share` | `{"shared", "recipients", "reuse_recipients"}` |
| `status` | `{"state", "project_id", "scopes"}` |
| `access-history` | `{"entries": [entry]}`; with `--export`: `{"out": path}` (see below) |
| `teams` | `{"teams": [team]}`; with `--team`: `{"team": team}` |
| `list` | `{"assets": [asset]}` |
| `doctor` | `{"configuration", "python", "local_contracts", "server_contracts"?}` |
| `check`, `get`, `send` | `{"outcome", "sentence", "facts", "technical"}` (see below) |
| `checks publish` | `{"published": [stored check]}` (each an `ophiolite.check/1` record with its `id`, `witness`, `recorded_by`, `command_id`, `at`) |
| `checks list` | `{"records": [stored check], "groups": [{key, latest, earlier, disagreement}]}` |
| `checks compare` | the stored comparison with `bound`, and `interpretation`, `sentence` or `fields` when they apply |
| `checks publishers list`, `add`, `remove` | `{"publishers": [{principal, kind, granted_by, at}]}` |

A refusal with `--json` prints `{"error": {"code", "message", "status", "remedy", "docs", "request_id"}}` on standard
output (the server's own code, remedy, documentation anchor and request id when it sent them) and exits with the code
above. Without `--json`, the message goes to standard error. A refusal from `check`, `get` or `send` also carries
`"outcome"`, `"sentence"`, `"facts"` and `"technical"` (the server's own words are only there).
A refusal from `checks` also carries `"field"`, the one field the server refused (for example `reference.digest`);
the sentence never names it.

## `check`, `get` and `send`

The same three actions as `Client.exchange()` in Python (guide: Exchange data between applications). A folder,
`--work` (default `.ophiolite-held`), remembers what you hold; keep one per application or script.

```sh
ophiolite check
ophiolite get --item ID --output surface            # a well log: add --curve GR (repeat)
ophiolite send porosity.csv --profile points-csv/1 --name "Porosity points" --how kriging --based-on ID [--declare crs=EPSG:28992] [--of ID]
```

`send` builds only on items you hold (`--based-on`, and `--of` for the next version of an item you wrote); the version it
replaces is the one you hold, so a newer version added by someone else is never overwritten. Running the same send again
after an interrupted one never publishes twice.

| Outcome | Exit | Sentence (start) |
|---|---|---|
| `nothing-new`, `updates`, `access-changed` | 0 | "Nothing is newer than what you hold." / "1 newer: …" / "You can no longer see …" |
| `got`, `already-latest` | 0 | "Got {name}, version {k}. You now hold it; saved in …" (an upload: "…, version {k} by {who}, {when}. …") / "You already hold the latest version of …" |
| `sent-new`, `sent-version` | 0 | "Sent {name} as a new item; it is private until you share it." / "Sent {name} as version {k}. Version {k-1} is kept." |
| `cannot-read-here`, `damaged`, `not-valid`, `not-held`, `too-large` | 1 | "This kind of item cannot be received by this script yet: …" / "The data did not match its fingerprint. Nothing was kept." / "The project refused this: …" / "You can only build on items you hold. …" / "The file is larger than this project accepts. …" |
| `access-refused`, `sign-in-needed` | 3 | "The project did not allow this with this access key, so nothing was sent. …" / "Your access key is not accepted any more. Ask for a new one." |
| `not-visible`, `map-unavailable`, `newer-version-exists`, `nothing-changed`, `earlier-version` | 4 | "You can no longer see …" / "That version of the map is not available …" / "Version {k} was added by {who}, {when}. Your change was not sent. …" / "This is the same as version {j}; nothing was sent." / "This content was version {j} on {day}." (the version you hold is newer; nothing was sent) |
| `outcome-unknown`, `folder-busy`, `rate-limited`, `could-not-reach` | 5 | "An earlier send of {name} may or may not have arrived. Run the same send again …" / "Another program is using this folder. …" / "The project is busy. …" / "Could not reach the project. …" |

## `checks`

Checks against a reference (E96). `check` above is a different command and is unchanged.

```sh
ophiolite checks publish checks/20261007/            # a check folder, or a folder of them (python -m conformance.checks produce DIR)
ophiolite checks list --asset A --revision R [--earlier]
ophiolite checks list --implementation ophiolite.shale-volume --version 1
ophiolite checks compare --asset A --revision R --file ref.las [--curve VSH] [--tolerance 0.001]
ophiolite checks publishers add|remove PRINCIPAL [--workload]
ophiolite checks publishers list
```

`publish` sends each folder's `check.json`, `fixture.*`, `reference.*`, `output.json` and `request.json` (and a grid's
`interpretation.json`); project administrators and the people or workloads they named may publish. The server repeats
the calculation when it runs the same implementation and release ("checked by the server"); otherwise the record is
kept as reported. Sending the same folder again answers the record already kept. `compare` keeps the comparison on that
result for you (and administrators who can read it); it is never a check of the method. `--tolerance` is in the file's
unit for the curve (or `--unit`), or a fraction with `--relative`. `publishers` changes who may publish; only an
administrator may.

| Refusal | Sentence | `field` |
|---|---|---|
| No permission | "Publishing checks needs permission. Ask a project administrator." | `permission` |
| Another release | "Not published: the check was made for release 2026.10.55, not the release this server runs." | `release.digest` |
| A changed file | "Not published: the reference file does not match the recorded file." | `reference.digest` (also `fixture.digest`, `output.digest`) |
| Past the wait | "Not published: the server did not finish the check in time. Nothing was saved." | `timeout` |
| Busy | "Not published: the server is busy. Try again." | `capacity` |
| Too many kept | "You have saved 20 comparisons on this result. Ask a project administrator to review them." | `limit` |

## `sources`

`sources list` shows the source selections you bound in this project. `sources describe ID` and `sources read ID` are
for SQL well-location tables (`sql-wells/1`); other kinds are refused before anything is sent (exit 1). Both make one
full, verified read (`describe` keeps only the shape): the returned source must be the one selected and its sha256 must
equal its revision, otherwise exit 1 (`source-checksum-mismatch`). `--expect-revision R` exits 4
(`source-revision-differs`) with no rows when the server returns another revision. `read` prints CSV, or with `--json`
the documented object (no pandas needed); `--original` gives every source column as given instead of the mapped view.
`--out FILE` (`.csv` or `.json`) writes the rows to a file of your own — not shared, not kept up to date — atomically,
and refuses to replace an existing file without `--force`. A refused or failed read writes nothing. Source refusals:
`SOURCE_NEEDS_REVIEW` and `SOURCE_DETACHED` exit 4, `SOURCE_ACCESS_DENIED` exits 3, `SOURCE_OFFLINE` and `SOURCE_PENDING`
exit 5 after the retries.

## `well-imports`

`well-imports start --connection ID --table KEY --mapping FILE [--audience PERSON]…` imports a copy of an approved
database's well table as wells (project administrators; the database must allow copying and declare its identifiers).
It previews the table, starts the import from that preview, prints `Import ID started. If it stops, continue with:
ophiolite well-imports resume ID`, and steps it to the end. The result names what was added, already here and skipped,
lists every skipped row with its reason in words, and every well whose location comes from other evidence. With
`--dry-run` it prints the preview and keeps nothing. `resume ID` continues an interrupted import from any process, with
no row run twice; `cancel ID` stops it (the wells already added stay); `status ID` and `list` read. An import that
pauses (`Ready to resume`, `Needs review`) exits 4 with its reason.

## `upload`

`upload PATH --attribution TEXT --rights-confirmed [--audience PERSON]…` uploads a folder (or a `.zip`) as one folder
upload: every file is listed with its size and digest, its first 64 KiB is sent so the server can say what kind of file
it is, and the whole file follows only when the server asks for it (in parts above the deployment's request limit).
It prints one line per outcome and every file that was not added with its reason; `--report FILE` writes the report
as CSV (`path,result,kind,read,reason,asset`) or, for a `.json` name, the whole report. Exit 0 when every file is Added
or Already here, 4 when any is not (the report is still written), 1 when the folder or zip was refused before anything
was sent (more than 500 files, a link, a zip entry outside the folder, over the file limit, more than 100 times its packed
size, or more than 512 MiB unpacked in total). `--declare KIND:KEY=VALUE` (repeat) answers the files of that kind that
need you to say what their values mean (other kinds are not touched), `--skip-decisions` skips every other file that
needs a decision, and `--associate-matches` links each file to the one wellbore whose name its header names. Running
the same command again continues the unfinished upload of the same folder (same paths, sizes and digests) and sends
only the files not yet added; `--new` starts another upload. `--project ID` names another project than the
configuration's.

The basis of a folder's files (E123): files that state the same coordinate system, units and datum are one block, and
files that state none of it are proposed as one group. The report prints the server's sentence for each block or
proposal and, under it, the files it means (up to five, then "and N more"):

```text
Maps - 4 files - Finished with files not added. 0 Added, 0 Already here, 4 Needs your decision, 0 Not read, 0 Not supported
These 4 files state no basis. Do they share one?
    Maps/a.txt, Maps/b.txt, Maps/c.txt and Maps/d.txt
```

`--share-basis` confirms every proposal (the files share one basis) and `--own-basis` declines it (each file has its
own); `--basis ITEM=VALUE` (repeat) then answers that item for every file or group that asks it, with ITEM in words:
coordinate system, map unit, vertical unit, vertical values, vertical datum, depth unit or time unit. A file that cannot
take an answer keeps its own question with the reason. In Python, `Report.basis` lists the blocks and then the
proposals as `BasisBlock`s (`target`, `kind` block or proposal, `state` stated, proposed, confirmed or declined,
`members` in the served order, `stated` keyed by item words, `open` every item still asked of the group or of any of
its files, and the served `sentence` or `''`), and `Report.conflicts` lists `(path, item, stated, answered)` for each
file whose stated value differs from the answer given for its group. Both are empty when the server serves no basis.

`--fidelity FILE` (E127 s2), for a catalogue manifest on this computer, writes the catalogue's fidelity document
(`osd.fidelity/1`) after the report: per file the manifest lists, converted (with the item, its kind and the reader),
failed (with the reason) or skipped. The manifest is read again and must be the file the upload read. When any file's
outcome cannot be stated exactly (an address, no or several manifests, a file without a SHA-256 the manifest states, no
catalogue snapshot, a file still being read), nothing is written, the report stays, and the command exits 1 with the
reason. `UploadRuns.fidelity(report, path, out)` does the same in Python.

## Giving a project access key

`login`, `projects` and `orgs` take a key with `--key KEY`, `--key-file FILE` or `--key-stdin` (at most 4 KiB), in that
order, else `OPHIOLITE_ACCESS_KEY`; every other command uses `OPHIOLITE_ACCESS_KEY` when no credential is saved. Each
goes through one reader: a line break or spaces around the key and a leading `Bearer ` are removed and the command
says so on standard error (and as `normalised` in `--json`), because another application's field — QGIS's
authentication setting — still needs the corrected value. A key that is empty, has a space or line break inside it,
or contains a control character is refused (exit 1); an explicitly empty `OPHIOLITE_ACCESS_KEY` is refused, not
ignored. A credential is never refused for its prefix. Saved credentials are read as they were saved.

## `doctor --online`

`ophiolite doctor --online` (with `configuration.json`, or `--url U --project P` and a key from `--key-file`,
`--key-stdin`, `--key` or `OPHIOLITE_ACCESS_KEY`) checks, in order, and stops at the first failure: **address** (the
name resolves), **tls** (the server answers its contracts index; https with a trusted certificate), **credential-arrived**
(the server received a bearer credential), **credential-accepted** (it was accepted), **project-readable** (it reaches the
project's wells description) and **features** (one collections request and one first page: `numberMatched`, otherwise
"at least N"; zero wells is a warning). A refusal is reported with the server's own sentence, its `stage` and remedy.
No redirect is followed and no `next` link requested, so the key goes nowhere but the given address. An unreachable
private deployment says "cannot reach the server: check Tailscale". A key given directly has no expiry the server can
report. Exit codes: 5 address or tls, 3 a credential or project stage, 4 features. `--json` prints `stages`,
`normalised` and the earlier `server_contracts`, `reach` and `reach_ok`.

## Reading access history and teams

Two read verbs show who had access to what, and when, and the teams that give it. They change nothing.

- `ophiolite access-history --project` lists the configuration's project's history, newest first (project
  administrators); `ophiolite access-history --person USER_ID --organization ORG` lists one person's history in the
  organisation (its owners; projects you do not administer are left out). Filters: `--kind KIND` (repeat), `--since`
  and `--until` (an instant or a day, UTC; `--since` inclusive). `--export csv|jsonl --out FILE` writes the whole
  history as one file (at most 10,000 entries) and prints only where it went. `--json` prints `{"entries": [entry]}`
  (or `{"out": path}`); an entry has `id`, `at`, `kind`, `parts`, `actor`, `on_behalf_of`, `credential_kind`,
  `through`, `subject`, `project`, `from`, `to`, `role` and `details`.
- `ophiolite teams` lists the project's teams and their grants (administrators); `ophiolite teams --organization ORG`
  lists the organisation's teams (owners), and `--team TEAM` one team's people. `--json` prints `{"teams": [team]}`
  (`{"team": team}` with `--team`).

In Python: `Client.access_history(kinds=, person=, actor=, since=, until=)`, `Client.access_teams()` and
`Client.export_access_history(format, dest)` read the client's project; `Account.teams(organization_id)`,
`Account.team(organization_id, team_id)`, `Account.person_history(organization_id, user_id, ...)` and
`Account.export_person_history(organization_id, user_id, format, dest)` read an organisation. Every page is followed.

Authenticate with an access key (`ophiolite login --key`, `OPHIOLITE_ACCESS_KEY`, or `Credential.bearer(key)`);
a saved sign-in is refused: the SDK does not send it (`access-key-required`, exit 1). The deployment refuses an
application you signed in to with `HISTORY_GRANT_REFUSED` and an agent, whoever it acts for, with
`HISTORY_AGENT_REFUSED` (exit 3); anyone who is not an administrator of the project, or an owner of the organisation
for a person's history, gets `PERMISSION_DENIED` with the deployment's sentence.

## `--dry-run`

`publish-derived` and `share` accept `--dry-run` (`well-imports start --dry-run` is the server's preview, above): the command prints what it would send (`publications/derive` with its
upload header, size and digest; or the recipients a share would set) and exits 0. It reads no credential, sends
nothing and writes nothing — no work folder, no credential file.

## `recipes`

`recipes run RECIPE --work FOLDER --input NAME=VALUE…` runs a recipe (`ophiolite.recipe/1`, a JSON file you write)
one step at a time: `residuals` (a residual procedure on this computer), `publish` (the run), `states` (the result's
outcome states) and `deliver` (the result, by its exact version, optionally `as` an outcome). Give an item input as
`ITEM`, `ITEM@N` or `@ASSET:REVISION`, a file input as its path; each is bound once, before any step. Each step runs
in its own folder under FOLDER and is recorded in `FOLDER/journal.json`. A recipe holds no credential or
configuration value: a key that names a secret is refused.

When a step stops (a crash, a refusal or a lost answer), run the same command again: it continues from the first step
not finished, with that step's own record, so a committed publication is not made twice and a finished delivery is
never sent again. A delivery whose outcome is unknown is asked again, never sent again; `--set-aside STEP` sets it
aside and the recipe continues. The same command with another recipe, other inputs, a changed input file, or as
another person, project or server is refused before any step; use a new FOLDER to run again for a new well-set
version. `--yes` runs procedure versions you have not trusted; without it such a step fails with the reason.

| Exit | Meaning |
|---|---|
| 0 | Every step finished or was set aside |
| 1 | Refused before any step, or a step failed or stopped (its sentence is printed) |
| 4 | A delivery's outcome is unknown |
| 2 | Usage |

`recipes show FOLDER` says where the recipe is, one line per step (Finished, Needs attention, Waiting or Set aside),
from this computer only; `--json` prints the journal.

## `starter`

`starter build DEFINITION --out FOLDER --catalogue records.json --verification DIR --custody DIR` builds a starter
pack (Open Subsurface Data `osd.starter/1`) of one catalogue record from a pack definition
(`ophiolite.starter-definition/1`, a JSON file you write). Before anything is sent it checks the definition, each
local input against the SHA-256 and size the definition names, every decision a well needs (crs, vertical-datum,
depth-reference, depth-kind, units, nulls, names), the LAS heads those decisions describe, each input's evidence
(the record's latest verification or a held deposit custody document) and the pack licence those give. It then adds
each input to the project at an exact version and writes, in FOLDER: `starter.json` (`unpublished: true`, no artefact
keys yet), `fidelity/<pack>.json`, and the python target under `files/` (an import script, one well-head GeoJSON per
well in WGS84, and `ATTRIBUTION.md`). It needs the starter extra: `pip install 'ophiolite[starter]'`.

`FOLDER/landing.json` records each input's upload before any of its content is sent. When a build stops, run the same
command again: an input already added is not sent again, and an upload that was started is read back from its run.
The same command with another server, project, definition or evidence file is refused; use a new FOLDER.

`starter finalise FOLDER --custody DIR` (this computer only) checks the pack again and writes each artefact's key from
the held `derived` custody document with its SHA-256, as the upload of `files/` wrote it. A refusal on any artefact
leaves `starter.json` unchanged. The pack stays unpublished. The definition, the decisions and resuming are described
in [starter packs](starter-packs.md).

| Exit | Meaning |
|---|---|
| 0 | Built or finalised |
| 1 | Refused (its sentence is printed); nothing more is written |
| 3 | This access key may not add files to the project (the inputs added before it are kept in landing.json) |
| 4 | An input has a newer version in the project than the one the pack was built from; build in a new FOLDER |
| 2 | Usage |
