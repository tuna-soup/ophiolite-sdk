# OSDU compatibility, version 1 (E167 s1)

One small document says what Ophiolite has shown about loading its OSDU manifests: nothing yet, or one dated load
record under `docs/osdu-roundtrip/<date>/record.json` in the Integration repository (E167 slice 0). Every deployment
serves it at `GET /api/v1/contracts/osdu/v1/compatibility.json`, without credentials; the Workspace and any tool read
it there, and the SDK carries the same bytes in its contract snapshot.

| File | What it is |
|---|---|
| `compatibility.json` | `ophiolite.osdu-compatibility/1`: the summary. With no kinds every other value is `null` and `summary` is "not yet verified"; otherwise the record's date, edition (distribution name and version, with the Storage and Schema service versions it was read from), the manifest's producer version (`mapper`), the manifest's sha256, the kinds loaded and the record's path, and the sentence they form |
| `compatibility-schema.json` | the structure of `compatibility.json` |
| `compatibility.py` | `ophiolite.osdu-compatibility-check/1`: `summary`, `problems`, `check`, `from_record`, `empty`; standard library only (Python 3.10). The gateway refuses to start on a document `check` refuses |
| `fixtures/valid/filled.json` | a synthetic filled document (made-up date, edition, digest and kind versions) |

The sentence is "compatibility shown on <date> against <edition> <version>, mapper <version>, manifest <digest>,
kinds <names>": masters first, then work products, then files. It never says "verified" except in the empty state's
"not yet verified". The lifecycle is `preview`.

The document changes only with a record: `python3 tools/osdu-compatibility.py write --record
docs/osdu-roundtrip/<date>/record.json` writes it, refusing a record without a load, read-back, denied leg, deletion
time or named distribution. `tools/test_osdu_compatibility.py` fails while the document and the newest record
differ. The lane that lands a record also runs `tools/sync.py` and reviews the SDK provenance rows it adds.
