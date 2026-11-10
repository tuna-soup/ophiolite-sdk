# Agent declarations (`ophiolite.agent-declarations/1`, E149)

Every operation of the API carries one declaration of what an agent may do with it. The schema is
`declarations-schema.json`; a declaration is `$defs/declaration`.

| Attribute | Values | Meaning |
|---|---|---|
| `reach` | `tool`, `call`, `person` | `tool`: an agent's request is answered and the operation is an MCP tool. `call`: answered over HTTP, no MCP tool. `person`: every agent request is refused. |
| `reason` | for `call`: `file-body`, `unbounded-answer`, `handwritten-route`, `person-area`, `person-setting`, `covered-only`, `frozen-out`; for `person`: `refused-by-gate`, `person-only`, `credential-kinds`, `write-not-admitted` | Why an operation is not a tool. Present exactly when `reach` is not `tool`. |
| `admitted` | `proposable`, `covered`, `both`, `never` | How a change enters: its own approved plan, only as a step of an approved parent, either, or not at all. Every read is `never`. |
| `parent` | an operation | The parent whose approved plan covers the step. Present exactly for `covered` and `both`. |
| `policy` | `true`, `false` | An agent's policy may approve it at proposal. `true` only with `admitted: proposable`. |
| `destructive` | `true` | The change can remove or narrow what exists, so an MCP client asks before it (optional; absent means it only adds). Only on a `tool` that changes something (E149 s1). |
| `note` | text | Why, in a sentence (optional). |

**Derived, never stored.** The guide's word is `read` for a read an agent reaches, `plan` for `proposable` and `both`,
`covered`, or `person`. Whether a change needs a plan stays a scope rule: every change but proposing one. Whether an
operation is an MCP tool is `reach: tool`.

**Rules of the family "Agents through the whole journey".** One record per operation; every list an agent, a client or
the guide reads is built from it (R-A1). Sign-in and identity, credentials and secrets, rights and licences, deletion
and removal, access, membership and invitations, and the approval of anything that publishes, shares or delivers are
`person` forever (R-A2). The operations a policy may approve stay `applications/configure` and `applications/start`
(R-A3).

**Structure here, the rest at the route table.** The schema checks each declaration on its own. Whether a `reach`
other than `person` fits the operation's credential kinds, whether a `tool` answers bounded JSON, whether `admitted`
fits a read, and whether `parent` is an operation are checked against the route table by
`services/project_gateway/agent_declarations.py`.

In E149 slice 0 the declarations were recorded and proved equal to the behaviour of the time. Since slice 1 they serve:
the agent service, the capability answer and the MCP tool list read them, and every MCP tool's annotations are
derived from them (`read_only_hint`: a read; `destructive_hint`: `destructive`; `idempotent_hint`: a read, or a change
whose request requires a `command_id` the server replays).

# Try it first: dry runs, choices and the wait policy (E150)

Three documents, published in E150 slice 0 before anything serves them.

**A dry run (`dry-run-schema.json`, `ophiolite.agent-dry-run/1`).** An agent (or a person) sends the same request as
the real call with `"dry_run": true`: in the JSON body, or for an operation sent as bytes inside its
`X-Ophiolite-Upload` object, with the bytes. The answer says what the real call `would` do (`proceeds` with its
effects, or `refused` with the refusal) and keeps nothing. `digest` is the SHA-256 of the canonical JSON (sorted keys,
no spaces, UTF-8) of `$defs/digest_input`: the request without `dry_run`, or for bytes the header object without
`dry_run` and the SHA-256 the gateway computed of the bytes it received. A proposal will name the dry run its person
saw by this digest (the evidence key `dry_run`, from E150 slice 1b; below).
`dry_run` is never part of a plan's hash: a proposal whose request carries it is refused (`dry-run-refused`,
`in-proposal`).

**A choice (`choice-schema.json`, `ophiolite.agent-choice/1`; `choice.py`, `ophiolite.agent-choice-rules/1`).** When
a step needs a decision only a person can make, the answer is the error envelope with code `choice-required` (409),
the question, two to eight literal choices (`c1`..`cN` in order; each `fragment` is the part of the request choosing
it sends, at most 16 properties and 4096 bytes of canonical JSON), `why` (`class`, `rule`), `answered_by: person` and
a `choice_token`. The token binds the proposal, the job, the step and the digest of the offered choices; its
derivation, the answer route and its record are E151's. An answer is refused with `choice-refused` and one of
`token-used`, `token-foreign`, `token-stale` or `not-the-delegator`; an answer an agent puts into its own request gets
`choice-required` again. Readers run `choice_problems` beside the schema.

**The wait policy (`agent-policy-schema.json`, `ophiolite.agent-policy/1`).** How long a proposal waits for its person:
1 to 168 whole hours, 24 for a project that never saved one. `$defs/read` and `$defs/save` are the requests of
`projects/agent-policy` (any member) and `projects/agent-policy-save` (an administrator, compare-and-set). A policy
never names an approver, an operation or a class (`agent-policy-refused`).

In E150 slice 0 these are contracts and words only: with the deployment switch on, a dry run and the policy answer
"not available yet"; with it off, nothing changes.

From E150 slice 1 an operation answers its dry run once the gateway has qualified it: the request runs as the real call
does, with every check in its place, and stops at its first change, which is undone. `effects` name what that change
would create, change or remove (a replay of a command that already ran proceeds with no effects); what other rules do
afterwards in reaction to the change (an outcome evaluated after a publication) is not part of `would`. A refusal the
operation's own validation gives (HTTP 400, 409, 410, 413, 422 or 428) is answered inside `would` with the body the
real call would have answered; every other refusal (no right, not found, a budget, the service) stays the real error.
An operation not qualified answers `dry-run-unavailable` with a `reason`: `not-qualified`, `computes` (what it makes
exists only after a computation runs) or `reaches-outside` (the request would fetch from another system).

From E150 slice 1b a proposal names the dry run its person will see: `evidence.dry_run` is the 64-character `digest`
a dry run of the same request answered. The gateway runs that dry run again when the proposal arrives and keeps the
record only when the digest is equal; the record then carries `dry_run {digest, would}`, its identity digest covers
it, and `agents/proposals` shows it. A difference is refused (`dry-run-refused`, `stale`: run it again and propose
with the new digest); a proposal whose operation answers no dry run (not qualified, sent as bytes, the switch off)
and every `jobs/propose` carrying `evidence.dry_run` are refused `not-available`. A refusal on the run again that is
not the operation's validation (no right, not found) stays the real error. Evidence without `dry_run` is unchanged,
its identity digest byte for byte.

# Jobs (E151)

**A job (`job-schema.json`, `ophiolite.agent-job/1`).** An agent proposes up to eight steps in order under one
approval (`jobs/propose`); a later step names an earlier answer by its JSON pointer. After approval it runs them one
at a time by command id (`jobs/step`); each step is checked again against its own route row, with the agent's access
of that moment, and a completed step answers again from its stored answer without running. `jobs/status` answers
this document: the job's state and step, the word a release or failure carries, and per step its operation, state
and the SHA-256 of its stored answer (never the answer). `review_url` is
`<origin>/project/<project>/settings?proposal=<plan hash>#agents`, also in `jobs/propose`'s and `agents/propose`'s
answers. A read computes expiry and never writes it; `jobs/step` and a decline store it.

**A choice (E151 s0 C3).** A step that needs its person's choice answers `choice-required` (409, `choice-schema.json`)
and the job waits at that step; `jobs/status` shows the question, the choices and the `choice_token`, and so does the
next `jobs/step` for it. Only the person the agent acts for answers, with `jobs/answer {choice_token, choice}`; it is
refused as `token-foreign`, `not-the-delegator`, `token-used` or `token-stale` (the job no longer waits there, the plan
expired, or the offer changed). The step then runs its approved body unchanged with the choice as trusted context; a
`choice` in the agent's own request is asked again.

**What waits for the person (`proposals-schema.json`, `ophiolite.agent-proposals/1`, E151 s0 C4).**
`agents/proposals` answers, for the caller as delegator in one project and newest first, every pending plan that has
not expired and every job waiting for a choice: the plan, its operation and the server's summary, the newest evidence
record as `agents/approve` names it (or null), the agent's budgets, the expiry and `review_url`, and for a waiting job
its question, choices and `choice_token`. Another member's plans are never listed; an agent credential cannot read it.

# Getting data in: the evidence of a mapping (E153)

**A mapping evidence row (`mapping-evidence-schema.json`, `ophiolite.agent-mapping-evidence/1`, E153 s0).** The row
the gateway derives for every pick of a mapping, published before anything changes an answer: the rows of a database
table's `column_basis` and the `fields` and `declarations` of a file landing's layout basis. A client never states it.

| Attribute | Values | Meaning |
|---|---|---|
| `field` or `declaration` | a name | The target field picked, or a layout's stated declaration; exactly one. |
| `class` | `declared`, `previously-reviewed`, `inferred`, `none` | Stated by the connection or by you; equal to an earlier review; the engine's suggestion; nothing picked. |
| `by` | text or null | Who stated it: `the connection`, `you`, or the suggestion's rule. Null for `none` and `previously-reviewed`. |
| `reuse` | `same-table`, `layout`, null | Which earlier review: the same table with the same schema digest, or a saved layout. Null except for `previously-reviewed`. |
| `supported_by` | `{mapping_version}`, `{import_id}`, `{layout, version}`, null | Exactly one tag: a reviewed mapping, a reviewed import, or a layout at its immutable version. Present and not null exactly for `previously-reviewed`. |
| `how` | `exact`, `reordered` | The layout's match; present exactly when `reuse` is `layout`. |

The schema checks the shape and these cross-field rules; it cannot know who asked. That an agent's request never
yields `by: you` is the server's rule (E153 slice 1). In slice 0 this is the contract only: no answer changes.

# Precedents (`precedents-schema.json`, `ophiolite.agent-precedents/1`, E158)

An assistant may ask, before it proposes a plan, for the accepted past results on the operation it is about to
propose: `agents/precedents {project_id, operation, input_kinds?, limit?}` (`$defs/request`; `limit` 1 to 20,
default 5). The answer lists at most `limit` result versions, `project_id`'s first and then the newest qualifying
verdict first. A version qualifies when, counting each author's current verdict only, at least one person accepted it
and nobody rejected it; withdrawing a result is a rejection. Only projects the person may read and the credential may
reach are searched (an agent: its one project), and only versions the person may open today appear.

Each precedent has two parts. `shape` is always present and is made only of the work-episode shape allowlist: the
operation, the registered parameters with the registry's units, the input kinds and digests, the outcome state, the
verdict word and the time, plus `verdict_ids`, the qualifying verdicts. `detail` (every current verdict's reason and
the method record) is present only when the person may read the version's content; otherwise it is `null`.

`request_sha256` is the SHA-256 of the canonical request (sorted keys, compact, ASCII-escaped) with its defaults
filled in. **Reserved for slice 2:** a plan's evidence gains `precedents` (`$defs/evidence`), one entry per answer
the agent read before proposing (the request and response digests, the verdict ids and the versions), an empty list
when it read none and never null. Until then the route answers that precedents are not available yet.

# A result from a tool run (`tool-run-refused`, E166)

An assistant publishes a result only as a step of a tool run it reported. `publications/derive` is declared
`admitted: covered` with parent `procedure-runs/report`: a derive runs under the completed report's approved plan and
is never proposed on its own. The refusal is the error envelope with code `tool-run-refused` (403) and a closed
`reason`, each with its sentence:

| `reason` | Sentence |
|---|---|
| `no-run` | No tool ran this: an assistant publishes a result only as a step of a tool run it reported. |
| `not-trusted` | The tool version this run names is not trusted by {delegator}. |
| `withdrawn` | The tool version this run names is withdrawn. |
| `not-verified` | The tool version this run names is not verified. |
| `import-as-run` | An import is source data, not a tool run. |

`{delegator}` is the display name of the person the assistant acts for, as the approval card shows it. The Python
SDK carries the same sentences as `ophiolite.agents.TOOL_RUN_SENTENCES` (and `NO_RUN`). Over MCP the answer carries the
code and the sentence, not `reason`.

In E166 slice 0 only `no-run` is answered: a derive proposed with `agents/propose`, and a derive sent without a
completed report that covers it (no plan, a malformed plan, or a plan that does not cover it). A person's own derive is
unchanged. The other four reasons are declared now and answered from slice 1. The sentences attribute the result to
the run the assistant reported; they do not attest that the tool ran.
