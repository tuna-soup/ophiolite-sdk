# Kinds of table (`ophiolite.table-kind/1`, E203)

A project's members say once what a word such as `casing-design` means for a table: what one row is, the columns it
has, whether each must be present (and read) and whether its cells may be empty, for a number the quantity class of
the unit registry (`asset_connectors.units`) with the unit the team writes, and the key. Each version is immutable; its
digest is the SHA-256 of the declaration's canonical JSON (sorted keys, no spaces, UTF-8). The label is what a person
reads and is never matched.

A table is checked against a version by `project_gateway.table_kinds.problems` over the `columns`, `declarations` and
`rows` of its `ophiolite.table-file/1` content. Nothing is converted: a depth in feet where the kind writes metres is
a length and passes; a depth in bar is refused with the column, the unit and the quantity. The person's words are
`vocabulary/v1/table-kind-words.json`, which gives each quantity class its label ("energy per volume" reads
"pressure"); the class is what is stored.

Slice 0 (this version, preview) is the contract, the check, the words and the fixtures; every route answers "not
yet". Processes do not name kinds of table (D126).

| File | What it is |
|---|---|
| `table-kind-schema.json` | The version record; the reference a published table records, the list and the request bodies in `$defs` |
| `fixtures/valid/` | Casing strings at versions 1 and 2, and a kind keyed on two columns |
| `fixtures/digests.json` | Each declaration's digest, computed once and written by hand |
| `fixtures/tables.json`, `fixtures/expected.json` | Synthetic tables and, written by hand, what each lacks to be a table of each kind |
| `fixtures/labels.json` | A quantity as written (the label) and as stored (the class), and the sentence a refusal reads |
| `fixtures/invalid/declaration-cases.json` | Declarations the schema refuses, and ones that break a rule of a kind |
