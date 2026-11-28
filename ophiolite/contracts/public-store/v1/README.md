# Public store index (`ophiolite.public-store/1`, E212)

The public store is one bucket, read-only to the world: immutable objects under content-addressed keys
(`datasets/<dataset-id>/<sha256>/<file name>`) and one index, `index.json` at its root, of this schema. Anyone reads
an object whose key they know; nobody lists the bucket; only the publishing tool (`tools/public-store/publish.py`,
controller only) writes it. A store address resolves a key as `<address>/<key>`.

The index is the byte and licence authority per dataset: its id, title, sources (E211's `SampleSource`, verbatim,
each with its OSD licence object whole), the licence block computed from them (E211's `SampleLicence`), the unique
OSD records of its sources in first-appearance order (two sources may share one record), and every object ever
published under it (append-only, at most 16; a key's bytes never change). The optional `samples` names E211's sample
index, stored at the fixed key `samples/index.json`. The index is never in the repository or the image; the only
indexes committed are the synthetic fixtures here, and every fixture dataset id starts `synthetic-`.

The rules are `store.py`, standard library only, loaded from its source text by the SDK snapshot, the publishing tool
and the gateway's tests. It loads E211's `samples/v1/samples.py` the same way and applies its structure reader and its
per-source licence rules. `index_problems(index, rules)` lists an index's problems as `{code, dataset, path}`;
`find(index, sha256)` gives the `{key, bytes}` of the object with that digest over every dataset (a reader matches by
the digest it pins, never by dataset id). Nothing here reads a store, opens a connection or writes a file. The
sentences a person reads are `vocabulary/v1/public-store-words.json`, one per code of the index's own; the licence
sentences are E211's.

| File | What it is |
|---|---|
| `public-store-schema.json` | The index, a dataset, an object (generated from `project_gateway/public_store.py`) |
| `store.py` | The rules and the codes |
| `synthetic-rules.json` | A synthetic source-rules document (E211's format) approving the synthetic dataset ids; tests only |
| `fixtures/valid/store-two.json` | Two synthetic datasets (one of them share-alike), three objects, a sample index |
| `fixtures/invalid/cases.json` | Changes the schema or the rules refuse, each with its paths and problems |
