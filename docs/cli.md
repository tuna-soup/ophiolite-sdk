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
| `wells extent` | `{"extent": {crs, bbox, count, untransformed}}` |
| `changes head` | `{"head": {epoch, cursor}}` |
| `changes list` | `{"changes": [event]}` |
| `changes follow` | one event object per line, as they happen |
| `sources list` | `{"selections": [selection]}` (the selections you bound; every profile) |
| `sources describe ID` | `{"source": {id, name, profile, revision, sha256, bytes, crs, row_count, columns, mapped_columns, mapping, null_counts, unresolved}}` |
| `sources read ID` | `{"source": {id, name, profile, revision, sha256, crs, original, columns, row_count}, "rows": [row]}`; with `--out`: `{"source": {…}, "out": path}` |
| `publish-derived` | `{"published": receipt}` |
| `share` | `{"shared", "recipients", "reuse_recipients"}` |
| `status` | `{"state", "project_id", "scopes"}` |
| `list` | `{"assets": [asset]}` |
| `doctor` | `{"configuration", "python", "local_contracts", "server_contracts"?}` |

A refusal with `--json` prints `{"error": {"code", "message", "status", "remedy", "docs", "request_id"}}` on standard
output (the server's own code, remedy, documentation anchor and request id when it sent them) and exits with the code
above. Without `--json`, the message goes to standard error.

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

## `--dry-run`

`publish-derived` and `share` accept `--dry-run`: the command prints what it would send (`publications/derive` with its
upload header, size and digest; or the recipients a share would set) and exits 0. It reads no credential, sends
nothing and writes nothing — no work folder, no credential file.
