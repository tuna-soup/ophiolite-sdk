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
