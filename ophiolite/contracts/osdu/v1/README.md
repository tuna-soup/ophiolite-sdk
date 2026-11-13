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

`denied_read` (E167 s1b) says whether the record showed that a person outside the project is refused:
`{"outcome": "shown"}`, or `{"outcome": "not-provable", "reason": "outsider-in-viewers"}` where the edition's bootstrap
put the outside test account in the records' viewers group. Then the sentence continues "; the denied read was not
provable on that edition because its outside test account belonged to the default viewers group", and every page that
names the record carries that clause. The field was added inside `/1` as a coordinated preview break: each copy (the
gateway's, the SDK's snapshot) validates only the document it ships with, and the Workspace reads named fields.

`operator_steps` (E167 s1b ruling, 10 November 2026) names what the load needed that the mapper's manifest alone does not
give: `registered`, the kinds whose schemas the operator registered (the record's `schemas_registered`), and `supplied`,
the fields the load filled outside the manifest's own placeholders (namespace, owners, viewers and legal tag are never
named; today only `data_countries`). Both lists are empty when the record has neither, and the field is null in the
empty state. When either is non-empty the sentence continues after the kinds, before any caveat, e.g. "; the load
registered the Well 1.5.0 schema and supplied the data countries the manifest leaves empty". A record that supplied a
field the contract has no words for is refused. It joined `/1` in the same coordinated preview break as `denied_read`.

The document changes only with a record: `python3 tools/osdu-compatibility.py write --record
docs/osdu-roundtrip/<date>/record.json` writes it, refusing a record without a load, read-back, denied leg, deletion
time or named distribution. A record whose `outsider` block says `denied_leg: "not-provable"` is accepted only with a
known `reason`, the viewers group among the outsider's `groups`, and every failure the outsider's read of one returned
record (each with an outsider preview of 200 and a control read); any other failure still refuses it. `tools/test_osdu_compatibility.py` fails while the document and the newest record
differ. The lane that lands a record also runs `tools/sync.py` and reviews the SDK provenance rows it adds.
