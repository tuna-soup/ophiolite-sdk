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
