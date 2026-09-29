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
| `sources list` | `{"selections": [selection]}` |
| `publish-derived` | `{"published": receipt}` |
| `share` | `{"shared", "recipients", "reuse_recipients"}` |
| `status` | `{"state", "project_id", "scopes"}` |
| `list` | `{"assets": [asset]}` |
| `doctor` | `{"configuration", "python", "local_contracts", "server_contracts"?}` |

A refusal with `--json` prints `{"error": {"code", "message", "status", "remedy", "docs", "request_id"}}` on standard
output (the server's own code, remedy, documentation anchor and request id when it sent them) and exits with the code
above. Without `--json`, the message goes to standard error.

## `--dry-run`

`publish-derived` and `share` accept `--dry-run`: the command prints what it would send (`publications/derive` with its
upload header, size and digest; or the recipients a share would set) and exits 0. It reads no credential, sends
nothing and writes nothing — no work folder, no credential file.
