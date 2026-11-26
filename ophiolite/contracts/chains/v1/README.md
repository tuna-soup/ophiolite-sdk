# Chains (E178)

A chain is a project's declared order of steps after a new version of an item. `chain-schema.json`
(`ophiolite.chain/1`) is the declaration: what starts it (`trigger`: a new version of an item kind, inside a well set
when `selection` names one, or a person's request) and one to sixteen `steps` in order. A step is one of three kinds,
each with exactly its block:

- `tool`: a procedure, named by name, whose result is checked against one outcome **version** (`outcome {id,
  version}`); `made_from` names earlier unconditional tool steps whose results this result must be made from.
- `choice`: a question with two to eight fixed answers, answered by a person (`chain-runs/choose`).
- `outside`: work done outside Ophiolite; a person says it was done, with a label and a reference.

A step `follows` earlier steps only (so a chain has no loops) and may apply only when a condition holds
(`applies_when`): a measure of an earlier tool step's acceptance record (`ophiolite.outcome-check/1` `measures`, the
names listed by the outcome rule in `../../outcomes/v1/rules.json`) compared with a value, in metres or feet for a
quantity and without a unit for a count. The record's number is never converted; a limit in the other unit is
converted into the record's unit. A condition over a record without measures (written before E178 slice 2, or one
whose evaluation stopped at an earlier gate) cannot be decided, and a person decides.

`chain-run-schema.json` (`ophiolite.chain-run/1`) is one pass of one chain version over one trigger. The whole
declaration of that version and each tool step's procedure digest are frozen at start. Each step has a state
(`waiting-for-earlier`, `open`, `not-checked`, `accepted`, `rejected`, `did-not-apply`, `undecided`, `skipped`,
`chosen`, `acknowledged`, `continued`; the closed ones are accepted, did-not-apply, skipped, chosen, acknowledged and
continued), its condition as read, its latest result with that result's check, and every act on it with who did it
(the person always; the assistant and the job plan only when an assistant acted under an approval) and when. Acts are
paged: `acts` is the newest page of at most fifty, `acts_count` all of them, `acts_next` the cursor for the older
page. A step that names an outcome version that is no longer current closes only through a record that already
exists or a person's continue, because outcomes are evaluated for their current version only. The run's state is
computed at read: stopped when a step is rejected, done when every step is closed, waiting when a step is undecided,
not checked, or an open choice or outside step, otherwise open.

`chain-due-schema.json` (`ophiolite.chain-due/1`) lists the item versions a chain should start for: versions of the
trigger's kind published after the chain version was enabled, with no run and no dismissal for that chain, item and
version. It is read from the kept item versions, never from the change log, which is pruned. A version is due only
when published strictly after the enabled version's `enabled` action; versions published while a chain is turned off
are never due. Revising a chain never moves its enabled version. The window belongs to the trigger (E178 s2a): enabling
a newer version whose trigger (`on`, `kind` and `selection`) is the same as the enabled one keeps the window, so lines
already due stay listed, now under the newer version; enabling a version with another trigger, or enabling after a
disable or a withdrawal, starts a new window, and the enable answers `due_stops`, how many lines the caller could read
before that are no longer listed (also in a person's dry run of the enable; an assistant cannot enable). A selection
that is not a well set, or that does not exist or the declarer cannot read, is refused with the reason `selection`,
one sentence for each of the two cases (`chain-reasons.json` `selection`). A well set named as `selection` is read when the due
list is read, so a set edited later changes what is due; a version is inside it when it is linked as a whole revision
(`of-entity`, not a single row) to a wellbore that is a member of the set's current version. Only versions the reader
may read are listed, and a reader who cannot read the well set sees no lines for that chain.

The schemas own shape. What a schema cannot say is `chains.chain_problems` and `chains.run_problems` (keys and
follows, made-from and conditions, step and run states against the frozen declaration, acts, and a count measure
that is not a whole number, which no generator can say for "an integer when the unit is null"). Refusal sentences,
the job-step admission sentence, step state words and comparison words are
`../../vocabulary/v1/chain-reasons.json`.

`fixtures/valid/` holds the four-step chain "After new tops" and its runs and due lists, counted by hand;
`fixtures/invalid/chain-cases.json` and `run-cases.json` each change one valid fixture and name the path the schema
refuses or the reasons the structural rules give. Slice 0 publishes the contracts and declares the routes, which
answer that chains are not available on this deployment yet.

## Criteria, proof and sign-off (E189, 1.1.0)

`chain/1` and `chain-run/1` 1.1.0 add, and change nothing released: a step kind `work` (a person makes the result
outside the platform and attaches it; its `work` block names the result kind and the steps it is made from), a
step's `done` list (1 to 16 criteria, each with one proof of kind `made-from`, `current-input`, `rule`, `outcome` or
`attachment`, and the role that signs off), and the chain's `roles` (up to 8, each listing its holders by member id,
sorted). `done` is allowed on `work` and `tool` steps only; a `work` step must have it. On a run, a step with `done`
carries the criteria view (`criteria`: the revision, one item per criterion in declared order with its state and
proofs, the sign-off and what changed since) and the states `criteria-not-met`, `waits-for-sign-off`, `signed-off`
and `done-with-exception`; the person acts `signed`, `excepted` and `exception-withdrawn` are added, and a version
declared with criteria reads `closes_on: proof`. The contract records who signed and who excepted; it has no rule
that they differ.

An attachment proof's label is 1 to 80 characters with no control character and no space at either end, in
Unicode normal form C (the model checks the form; the schema cannot), compared exactly (E191). A rule proof names a
released rule and its parameter values; the rule must apply to the step's result kind and every value must be in
the rule's type and bounds (`rule-parameters`). The released 1.0.0 files are kept as digests under
`fixtures/frozen/`: 1.1.0 with exactly these additions taken away hashes to them.

`fixtures/valid/chain-p.json` is the pressure study after new velocities and its `run-p-*.json` runs, counted by
hand; `fixtures/invalid/criteria-cases.json` holds the refusals. Until E189 slice 1 a served declare or revise that
uses any of this answers 503 with the sentence `chains.CRITERIA_UNAVAILABLE`, and stores nothing.

## Kinds of work, applies, and taking a step out (E190, 1.2.0; step-criteria 1.1.0)

`chain/1` and `chain-run/1` 1.2.0 add, and change nothing released: the chain's `job_kinds` (1 to 8, each a key and
the team's label), and an `applies` list on a step and on a criterion (1 to 8 listed keys, sorted, each once;
absent means every kind). On a run, `job_kind` names the run's kind (present exactly when the chain lists kinds),
`counts` gives how many steps apply and how many do not, the step and criterion state `does-not-apply` carries its
cause in `not_applying` (`job-kind`, or `taken-out` with who, when and the reason), and the person acts `taken-out`
and `put-back` name the step, or one criterion of it, with a reason (1 to 500 characters). `does-not-apply` is a
closed state: a step that follows it may open. `step-criteria/1` 1.1.0 adds an item's `not_applying` and the
revision causes `taken-out` and `put-back`.

The schema cannot say these, so `chains.chain_problems` does: a kind listed twice (`duplicate-job-kind`), an
`applies` naming a kind the chain does not list (`applies-unknown-kind`), a criterion wider than its step
(`applies-wider-than-step`), a step limited to fewer kinds than a step made from its result
(`applies-data-successor`), and a condition or a current-input criterion reading a step limited to fewer kinds than
its own (`applies-reads-limited`). `chains.run_problems` checks what one response shows: `job_kind` against the
chain (`job-kind-mismatch`), a step outside the run's kind not reading `does-not-apply` (`state-disagrees`), the
cause against the state and the act shown (`not-applying-mismatch`; an act on an older page is not guessed), a step
made from a taken-out step still applying (`made-from-taken-out`), and the counts (`counts-mismatch`). A step that
does not apply has no `condition`, and is never closed after a step that is open. The order of take-out and put-back
over the whole journal is checked where the act is written (E190 slice 1), not in a response.

The released 1.1.0 chain files and the 1.0.0 step-criteria file are kept as digests under `fixtures/frozen/`.
`fixtures/valid/chain-k.json` ("Before drilling a well") and its `run-k-*.json` runs, with `chain-k-b.json` and
`run-kb-taken-out-both.json`, are counted by hand; `fixtures/criteria/k-criterion-exception-*.json` are the revisions
behind `run-k-criterion-exception`, and `fixtures/invalid/applies-cases.json` holds the refusals. The words are
`ophiolite.applies-words/1`. Until E190 slice 1 a served declare or revise that uses kinds of work answers 503 with
the sentence `job_kinds.UNAVAILABLE`, before anything is checked, and stores nothing.
