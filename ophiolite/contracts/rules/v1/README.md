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

## Rule evidence (E189)

`rule-evidence-schema.json` (`ophiolite.rule-evidence/1`) is one released rule run on one version with a team's
parameter values, for a chain step's `rule` criterion. `parameters` holds every parameter the rule declares, defaults
filled in; `parameters_sha256` is the sha256 of those parameters as `json.dumps(parameters, sort_keys=True,
separators=(',', ':'))` with each `number` or `quantity` value first made a float, so 150 and 150.0 give one digest.
The record is keyed by `(asset_id, revision, rule, parameters_sha256)` and, like a rule-results block, carries no id,
time or person. `result` is the rule-results/1 result of that run. `fixtures/evidence-gr-200.json` and
`evidence-gr-150.json` are one version run with a maximum of 200 (passed) and 150 (three rows fail). Nothing writes
or serves these records before E189 slice 2.
