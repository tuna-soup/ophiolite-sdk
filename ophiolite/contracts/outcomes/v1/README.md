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

`fixtures/valid/` holds declarations the server accepts; each file in `fixtures/invalid/` differs from
`valid/tops-within-5m.json` in one field and names the reason it is refused (`fixtures/expected.json`).
