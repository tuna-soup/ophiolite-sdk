# Outcomes (E120)

An outcome is a project's declared acceptance over a kind of result: a built-in rule with its settings, the inputs a
result must be made from, and the send procedure and destination it is delivered by. `outcome-schema.json`
(`ophiolite.outcome/1`) is the declaration's shape; `rules.json` (`ophiolite.outcome-rules/1`) lists what may be
declared; the refusal reasons are `../../vocabulary/v1/outcome-reasons.json` (`ophiolite.outcome-reasons/1`).

The JSON schema owns shape only. Rule membership, per-rule settings and inputs are checked by the server against
`rules.json`. Each change to an outcome is a new version that is never altered.

From slice 1 the server evaluates every enabled outcome over a result of its kind after the result is published,
with the declarer's reading rights, and keeps the acceptance record `outcome-check-schema.json`
(`ophiolite.outcome-check/1`): the outcome version, the evaluator (`outcome-evaluator/1`, rule version 1), the exact
result and publication, the bound input versions, the verdict (`accepted`, `rejected`, `not_compared`), its reason (the
vocabulary's `checks`) and the rows. A record is never changed; one acceptance key gives one record. A result's
states are derived from its records and the outcome's state for readers of the result. Nothing is gated yet.

From E144 slice 4 a declaration may name data rules (`rule.data_rules`, sorted, once each, at most eight): the ones
its kind lists in `rules.json` `data_rules`, released in the current data-rule snapshot (`../../rules/v1/registry.json`)
and reading one of its inputs (refused `data_rules` otherwise). A declaration that names none is the one it was before,
byte for byte. They are run on the bound input versions after the validity and inputs checks and before the built-in
rule; a record of such a version carries them in `data_rules`.

From E178 slice 0 (version 1.2.0 of the record, `rules_version` 1.2.0) each rule lists in `rules.json` `measures` the
numbers its evaluation records, and a record may carry them in `measures` (sorted by name, once each): a quantity in
the result's display unit without rounding, or a whole count with no unit. For `well-residual-within/1`,
`largest_residual` is the largest absolute residual over every computed row (not only the rows a record lists), and
`computed`, `passing`, `failing` and `not_computed` count every row. The evaluator writes the block from E178 slice 2,
only when rows were computed; a record written before, or one whose evaluation stopped at an earlier gate, has no
block and keeps its key set byte for byte. A chain step's condition (`ophiolite.chain/1`) names one measure; over a
record without it the condition cannot be decided. `fixtures/checks/with-measures.json` is a record with the block,
counted by hand.

`fixtures/valid/` holds declarations the server accepts; each file in `fixtures/invalid/` differs from
`valid/tops-within-5m.json` in one field and names the reason it is refused (`fixtures/expected.json`).

From E176 a candidate result can be tried before it is published: `outcomes/try` takes the header
`publications/derive` would take and the candidate's bytes, and answers `outcome-trial-schema.json`
(`ophiolite.outcome-trial/1`) with `trial: true`. It names, per enabled outcome of the kind, what the outcome would say:
`accepted`, `rejected`, `not_compared` (the record's verdicts and reasons), `not_evaluated` (the declarer cannot read a
bound input) or `not_tried` (reserved for rules that run as tools). Rows are one projection of the record's rows,
`{key, measure, value, unit, limit, pass, reason}`, with `value` in the tolerance's unit, complete counts and at most 20
per list. A trial writes nothing. Each entry is one variant of a union discriminated by `would`, so the schema states
which reason, sentence and rows a verdict may carry. From E178 slice 2 (version 1.2.0) an accepted, rejected or not
compared entry may carry `measures`, the record's own block under the same rules, absent when the evaluation stopped at
an earlier gate and never served to the Python SDK or command line up to release 2026.11.19, whose reader is strict
(`fixtures/trial/valid/measured.json`). `fixtures/trial/valid/` holds answers both readers take;
`fixtures/trial/invalid/cases.json` changes one of them in one place per case. Until slice 1 the operation answers
that it is not available on this deployment yet.
