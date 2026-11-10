# Data rules (E144)

- `data-rule-schema.json` — `ophiolite.data-rule/1`: one document per rule (`id/N`), the kinds it applies to, its
  class (`file-local` or `project-context`), severity, parameters with their admissible range, comparison and source,
  the sentence template and the registry version it first appeared in (`since`).
- `rule-results-schema.json` — `ophiolite.rule-results/1`: the rules run on one version under one registry snapshot,
  one result per rule that applies to the version's kind (`passed`, `failed` with a count and up to five examples,
  `not-applicable` with a reason). No id, time or person: the stored row binds it to its version.
- `registry.json` — `ophiolite.data-rules/1`, the index: every snapshot with its digest; `current` is the last.
- `registries/<version>.json` — immutable snapshots: the released rules, each with its file and digest. A block is
  checked against the snapshot it names.
- `fixtures/` — synthetic documents, valid and refused, grouped by the stage that refuses them; `expected.json` names
  the stage, code and field for each refused one.

The registry and snapshots are authored in Connectors (`asset_connectors/data_rules/v1/`) and copied here byte for byte
by `generate.py --targets`. Slice 0 releases snapshot 1.0.0 with no rules; slice 1 adds the first library.
