# Sample index (`ophiolite.sample-index/1`, E211)

A sample project is a bundle in the public store, named by an entry of the sample index. An entry gives the sample's
id (URL-safe, never reused), its title and card text, its bundle by a key relative to the store with the bundle's
SHA-256 and bytes and its manifest's SHA-256, the inputs it was made from, the licence block computed from them, and
its contents taken from the bundle manifest. The index lives in the store, never in the repository (R2); the only
indexes committed are the synthetic fixtures here, and every fixture key starts `synthetic/`.

Each input (a source) keeps its catalogue origin as its Open Subsurface Data record states it (the page a person
opens), the address actually fetched (`acquired_from`), its licence object whole and unchanged, the reading of its
terms by the person who read them (`reading`: the date and whether commercial use is allowed) and the credit a person
sees (`credit`: the publisher's own sentence, or one we wrote from the terms with its evidence).

The rules are `samples.py`, standard library only, loaded from its source text by the gateway
(`project_gateway.sample_index.samples`), the SDK snapshot and E212's publish tool. `entry_problems(entry,
manifest_bytes, rules)` lists an entry's problems as `{code, index, id, path}`; `offered(index, manifests, rules)`
returns the entries a card may be offered for and the problems of the others. Nothing here reads a store, opens a
connection, serves a route or writes a file. The sentences a person reads are
`vocabulary/v1/sample-index-words.json`, one per code.

Counts are never stored: contents are names in lists, and what a sample holds is counted at run time from the data
(the E172 rule).

| File | What it is |
|---|---|
| `sample-index-schema.json` | The index and an entry (generated from `project_gateway/sample_index.py`) |
| `samples.py` | The rules, the structure reader and the codes |
| `fixtures/valid/index-four.json` | Four synthetic entries, one per approved sample id |
| `fixtures/manifests/` | Synthetic bundle manifests (valid `ophiolite.portable-bundle/2`) |
| `fixtures/digests.json` | Each manifest's SHA-256 by `sha256sum`, and the manifest each fixture key stands for |
| `fixtures/invalid/cases.json` | Changes the schema refuses, each at its path |
