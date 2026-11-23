# Procedures, version 1 (E105a)

A procedure is a team's own code described to Ophiolite: a folder holding `procedure.json` (the manifest,
`ophiolite.procedure/1`) and the Python files it names. This folder holds its contract.

| File | What it is |
|---|---|
| `procedure-schema.json` | the structure of `procedure.json`; structure only |
| `rules.json` | `ophiolite.procedure-rules/1`: the steps, what each step may read and make (literal kind lists), units, limits and every sentence, under one `rules_version` |
| `procedure.py` | the validator of record: `validate(folder)`, `digest(folder)`, `pack(folder)`, `unpack_check(archive, destination)`; standard library only (Python 3.10) |
| `delivery.py` | `ophiolite.delivery/1` (E109): the check of the delivery a send procedure reports, `{delivery_id, state, items}` and nothing else; states `confirmed`, `not-sent`, `unknown`; standard library only |
| `requires.py` | the `requires` grammar (E112 s4; shared in E113 s1): a strict PEP 508 subset and the PEP 440 order of an installed version; `unmet(texts, version)` for the SDK's interpreter, `unmet_against(texts, packages)` for a sandbox image's label; standard library only |
| `tool-verification.json` | `ophiolite.tool-verification/1` (E165, preview): who verified one procedure digest against a check, a publication or (1.1.0, E113 s0) a run Ophiolite made in the project's sandbox, or withdrew a verification; generated from `project_gateway/tool_verifications.py`, its vectors in `fixtures/tool-verification/` |
| `procedure-box.json` | `ophiolite.procedure-box/1` (E113 s1, preview): what the server hands a tool version run in the sandbox, `/box/request.json`, read by the SDK's `ophiolite.box`: the entry, the settings and each exact input version at a path under `/box/inputs`; the bundle is `/box/bundle`; generated from `project_gateway/sandbox.py`. 1.1.0 (E179 s0): the check form, `step: "check"` with `result`, the slot of the one result a team's check answers about; a process request has neither |
| `check-answer.json` | `ophiolite.check-answer/1` (E179 s0, preview): what the outcome form of a check writes to `/output/answer.json` (at most 1 MiB, the only file there): `state` passed, failed or not_compared, the tool's `reason` exactly when not_compared, at most 1000 rows; generated from `project_gateway/outcome_tools.py`, its vectors in `fixtures/check-answer/` |
| `reference-cases.json` | `ophiolite.reference-cases/1` (E180 s0, preview): one version of a project's reference cases for one tool, chosen by a person: per case the exact input versions, the settings, the one result a person accepted (by their verdict) and how the output is compared with it (the E96 rule of the kind, the allowed difference, the curve or the interpretation); how many must pass; the accepted result is never an input |
| `reference-run.json` | `ophiolite.reference-run/1` (E180 s0, preview): one tool version run once on every case of one set version, written once when every case has ended: per case passed, failed with its reason or not counted, the E96 comparison, counts outcome by outcome |
| `fixtures/reference/` | E180 s0: the case sets, runs and route answers counted by hand (residual-fit, three wells, v2 differs by 0.75 m on one row of c2), the restricted forms, and the records the contract refuses, shape and semantic; sentences in `../../vocabulary/v1/reference-reasons.json` |
| `fixtures/sandbox/` | E113 s0: sandbox run requests, the limits a run gets under the ceiling and the words a witnessed result says; s1: which tool versions an image admits (`admission.json`); for `project_gateway/sandbox.py` (no published schema: the ceiling is deployment configuration) |
| `fixtures/` | valid manifests per step, single-defect invalid manifests with their expected code, field and sentence (`expected.json`), and two sample bundles |

**One validator.** The Platform and the SDK run this same `procedure.py` (the SDK's copy is byte-identical through
its contract snapshot) and the same `../../vocabulary/v1/labels.py`. Both are loaded from their source text
(`compile` + `exec` into a fresh module), so no bytecode is read or written next to them. A verdict names its
`rules_version`; the same `rules_version` gives the same verdict wherever it runs. Registration may still refuse a
valid procedure for its own reasons (E105b), in its own sentences.

**Never imported.** Validating, hashing, packing and unpacking read files only; the entry (`module:function`) is
checked against the file list (R29).

**The digest.** `sha256("ophiolite.procedure-bundle/1\n" + for each member path in sorted order: path + "\0" +
sha256-hex(bytes) + "\n")`. Members are the regular UTF-8 files of the folder, at most 200 files and 1 MiB, with
paths in one canonical spelling (`./a` and `a//b` are refused, not normalised); `__pycache__/` and `*.pyc` are not
members. File order and timestamps cannot change the digest; any byte can.

**The archive.** `pack` writes a deterministic ustar archive (sorted, mtime 0, owner 0, mode 0644, files only).
`unpack_check` refuses links, devices, unsafe or repeated names, non-text members and oversize content, and a
destination that exists and is not an empty real folder, before it writes anything.

**A send names its destination (E109, rules 1.1.0).** A send procedure reads one or more versions and may name one
`system` input: the team's system it delivers to, labelled in words without an address or credentials (the
configuration stays on the person's computer). A send that names no system still validates; its delivery output's
label names the destination. A send may also name `reconcile` (`module:function`, checked against the file list as
the entry is), which answers what happened to a delivery whose outcome is not known. Its run returns
`ophiolite.delivery/1`, checked by `delivery.py`: the delivery id (a uuid4 made once, before the writer runs), the
state (`confirmed`, `not-sent` or `unknown`) and the item count (0 to 1,000,000). Nothing else is part of it; a
writer's reason stays on the computer.

**A residual procedure reads a fixed set of slots (E119b, rules 1.2.0).** A process procedure that makes
`well-residual/1` reads exactly four slots: `selection` (one `well-set/1`), `tops` (one or more `well-tops-csv/1`),
`surface` (one `esri-ascii-grid/1`) and `trajectories` (`deviation-csv/1`, cardinality `many`), with the settings
`formation` (text) and `display_unit` (`m` or `ft`), and makes one `residuals` output; any other shape is refused with
its own key (`rules.json` `residual_procedure`). `parent_slots` names the slots whose versions are a result's parents:
every slot in this version, the selection included.

**A residual result may be sent (E120, rules 1.3.0).** `send_kinds` includes `well-residual/1`, so a send procedure
can deliver a residual result, for example as an outcome's destination (`fixtures/valid/send-residual.json`).

**A read procedure may write a SEG-Y volume (E123 SZ, rules 1.4.0).** `read_source_kinds` and `kind_words` include
`segy/1`, so a procedure that reads a file on the person's computer (the SDK's "Read a ZGY cube on your computer")
can land what it converted as a seismic volume. A volume is still never made by a process procedure, sent or checked:
`process_kinds`, `process_input_kinds` and `send_kinds` are unchanged.

**A check may answer an outcome (E179, rules 1.5.0).** A `check` manifest with a `result` input is the outcome form
(`outcome_form(manifest)`): exactly one `result` input (kinds from `process_kinds`, cardinality one), any number of
`version` inputs (the versions the result was made from), no `reference`, and one output of class `answer` with no
`kind`; its payload is `ophiolite.check-answer/1`. Only Ophiolite runs it, in the project's sandbox, when an outcome
that names its digest is evaluated (E179 slice 1); it is never reported or run on the person's computer. Every other
`check` manifest is E110's comparison, unchanged (`fixtures/valid/check-outcome.json`; `answer_words` names the form).

**A kept copy of a wells table may be read (E181 s1, rules 1.6.0).** `process_input_kinds` and `kind_words` include
`sql-wells/1`, the kept copy of a wells table ("Well locations from a SQL table"): a process or check tool may declare
it as an input, bound like any other input to one exact kept-copy version, whose original (the `ophiolite.sql-wells/1`
document) the tool reads as `<slot>-<n>.json`. A tool never makes, reads from a file or sends one: `process_kinds`,
`read_source_kinds` and `send_kinds` are unchanged, and a residual slot still takes only its own kind
(`residual-slot-kind`). Who may give a kept copy is unchanged: binding it needs reuse, which a kept copy grants a
project administrator only.
