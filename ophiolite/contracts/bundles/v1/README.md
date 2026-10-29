# Portable bundle 1.0 (`ophiolite.portable-bundle/1`)

A bundle is a **directory** whose only entry point is `manifest.json`
(`manifest-schema.json`). It holds exactly the selected exact revisions — never a
claim to be a complete project — with, per asset and per selected curve:

| File | Role | Contract |
|---|---|---|
| `assets/<n>/original.las` | `original` | exact bytes as retained (when authorised) |
| `assets/<n>/descriptor-<curve>.json` | `descriptor` | `ophiolite.scientific-asset/1` as served |
| `assets/<n>/curve-<curve>.json` | `normalized` | `ophiolite.application-curve/1` as served |

Every file is listed with its SHA-256 and size. Readers must refuse: another
`bundle_version` major, a digest or size mismatch, paths outside `assets/<n>/`,
links, duplicate paths, files above the declared limits and non-finite JSON.
Unlisted files are ignored and reported. Zero stays zero; missing values are
`null`; units, depth reference and missing-value markers are the served ones;
unknown context stays unknown. Parents appear only as the server permitted them
(`parent_visibility: restricted` carries no identifiers or counts). `history` is
the served E8 block for managed results. `groups` and `recommendations` are
explicitly `null` in 1.0.

Checksums prove integrity of the copy, not authorship or scientific correctness.
Exported copies cannot be recalled; holding one grants no new upstream, sharing or
AI-training rights. Bundle 1.0 is additive-extensible: new optional fields raise the
minor version; a breaking change raises the major.

## 1.10 / 2.10 — source records (E122 s5b)

An asset entry may carry `source_record`: where that exact revision came from, as the exporting gateway served it
(`ophiolite.source-provenance/1`, [schema](../../scientific/v1/source-provenance.json)), unchanged, wrapped with the
`asset_id` and `revision` it was served for (the record itself names neither). The wrapper has exactly `schema`,
`asset_id`, `revision` and `record`; the sentence the gateway words it with, who read it and whether the item is now
gone are not carried. A revision stored before records began carries no key. Exporters write minor 10 only when a
record travels; the major is the content's (1.10 for well logs, 2.10 for typed data). When the exporting server has no
source records, `observations.source_records_omitted` says so and the minor follows the observation rule (1.1 / 2.1).

Readers check before using the asset: the wrapper's four keys and schema, its identity equal to the entry's, the
record valid against its schema (every object closed), and a version of at least 1.10 / 2.10. Released readers before
1.10 ignore the key and open the bundle as they did ([fixture](fixtures/manifest-source-records.json)).
