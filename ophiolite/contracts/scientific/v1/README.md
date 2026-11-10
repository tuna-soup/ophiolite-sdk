# Scientific exchange profiles, version 1

Both profiles are entries of the [contracts registry](../../README.md) with
structural JSON Schemas beside this file (`well-curve-schema.json`,
`scalar-map-schema.json`); the cross-field rules below stay executable in
`project_gateway.catalog.validate_snapshot`.

Status: native-backend pilot contracts. These profiles describe normalized
`ExternalSnapshot` JSON from Platform's protobuf API. They do not establish OSDU
certification, native application editing, or correctness of an interpretation.
A conformance result is distinct from publication readiness or scientific approval.

Run the fixtures without a server, database, identity provider or Ophiolite UI:

```sh
python -m pip install 'pydantic>=2,<3'
PYTHONPATH=services python -m project_gateway.validate_exchange contracts/scientific/v1/fixtures/well-curve.json
PYTHONPATH=services python -m project_gateway.validate_exchange contracts/scientific/v1/fixtures/scalar-map.json
```

Fixtures are synthetic: three depth samples and a 2×2 scalar grid. No geographic
or vertical truth is asserted. Both contain one null. Expected finite ranges are
10–30 and 1–4 respectively. The implementation and positive/negative fixtures are
in `services/project_gateway/catalog.py` and `tests/test_catalog.py`.

## Common contract

Exact identity is `(project_id, asset_id, revision)`; revisions are positive decimal
**strings**, never JavaScript numbers. A snapshot does not independently contain its
project identity: retain the exact reference alongside it. Source revision is a
separate source-provided identifier/digest and cannot replace publication revision.
A scientific description preserves both source metadata and this exact reference.

Both profiles contain 1–100,000 samples, explicit nonempty value units, numeric
values or protobuf JSON `"NaN"` null markers, and no infinity. The Python validator
also accepts IEEE NaN from an in-memory protobuf conversion. Export consumers must
preserve nulls, not replace them with zero. Original files, normalized values,
rendered pixels and derived results are different representations.

An optional `original_sha256` identifies retained original bytes of this revision;
retrieve through the exact authorized original API and verify SHA-256. It is not
proof of permission to redistribute. Derived revisions may have no original.
Unknown fields remain in the source payload/metadata; the validator must not
silently discard extensions or rewrite scientific values.

## `ophiolite/well-curve/1`

`kind=curve`. `values` and `measured_depth` have identical length. Depths are finite,
strictly increasing and `depth_unit=m`. `well_id`, `md_datum`, `curve_type` and
`unit` are explicit, nonempty strings. An explicitly unknown depth datum is allowed;
it does not qualify true-vertical-depth conversion. LAS import converts declared
feet to metres; the original retains source encoding. No well trajectory or
horizontal CRS is inferred from a curve. Duplicate/decreasing depths are rejected.

This profile is different from `ophiolite.application-curve/1` (the
source-preserving normalized LAS curve) and must not be substituted for it.
The only sanctioned path between them is the declared one-way mapping
`mappings/v1/application-curve-to-well-curve.json`
(`project_gateway.curve_mapping.to_well_curve`), which requires the caller to
supply measured-depth evidence (`axis_kind='MD'`), a `well_id` and an
`md_datum` (`'unknown'` allowed), and refuses feet, unordered or duplicate
depths, blank units and empty curves instead of converting, reordering or
inventing. Shared terms are in `vocabulary/v1/vocabulary.json`.

## `ophiolite/scalar-map/1`

`kind=scalar-map`; `scalar_map` contains positive integer width/height and row-major
values of length width×height. `first_x`/`first_y` are sample centers (protobuf omitted
numeric fields mean zero); positive `step_x` and `step_y` mean columns increase x
and rows **decrease** y. Geometry is finite. This represents a regular numerical
map, not arbitrary meshes, categorical resampling or an application's edit model.

`metadata_json` is an object with `unit` matching the outer unit, nonempty
`coordinate_unit`, `crs_status` (unknown/local/source-declared/verified), and an
explicit `vertical_reference` object. Source-declared/verified CRS requires `crs`.
The validator checks presence/consistency, not whether a CRS definition or claimed
verification is geodetically correct. Connector spatial validation remains required.
A horizontal CRS does not identify a vertical datum. A map in metres is not
necessarily elevation: porosity, depth, time and elevation need distinct meaning.
Never use scalar values as heights without an appropriate scientific declaration.

## Provenance and loss

A source claim is displayed as source-declared. A recorded lineage object is
reported as recorded derivation, not automatically as a reproducible or observed
execution. Preserve exact input references, declared operations and parameters.
The metadata's `losses` remain readable; scientific descriptions preserve the whole
object. Styles/native edit histories are not implied by exchange conformance.

Profiles constrain the existing public snapshot contract; they do not replace an
OSDU schema. A future OSDU adapter must separately prove mappings, exact versions,
permissions and recovery against the same fixtures and domain payload APIs.
Breaking meaning/encoding changes require a new profile version and migration
instructions. Independent implementers can run these tests without our server.

## `ophiolite.verdict/1` (preview)

`verdict.json`: a person's accepted or rejected on one exact result version, with a reason (required to reject, at
most 2000 code points, kept as written, no NUL), what it was judged against (an outcome version or a check key), the
earlier verdict of the same author on the same version it supersedes, and who gave it; the current verdict is the
last link of each author's chain, never the latest timestamp. Fixtures for the record, the requests, the chains, the
words and the id are in `fixtures/verdict/`; a deployment that does not record verdicts yet answers "Recording
verdicts is not available on this deployment yet."

## `ophiolite.behaviour-consent/1` (preview)

`behaviour-consent.json`: one step of a person's consent that a record of their own work may be used for training or
evaluation. Per person and purpose the steps form one chain ordered by `sequence`: a grant opens an interval and the
next step closes it (a grant after a grant is a revision, a withdrawal closes without opening, so a later grant never
covers the gap). A grant covers all five items (`own-actions`, `command-parameters`, `verdicts`, `published-checks`,
`agent-plan-digests`), never data values; `instruction-text` is the one extra. The consent id is
`consent-` + the first 32 hex digits of sha256(person, a newline, the canonical body without the id). Eligibility
also needs the deployment's capture to be `by-consent`. Fixtures for the records, requests, transitions, intervals,
settings, texts and words are in `fixtures/behaviour-consent/`.

## `ophiolite.work-episodes/1` and `ophiolite.work-episode/1` (preview)

`work-episodes.json` is the manifest of a folder of work episodes a model may learn from; `work-episode.json` is one
episode, one line of the folder's `episodes.jsonl`. An episode is one person's or one agent's consecutive actions in one
project, consecutive rows less than `window_seconds` apart (default 14400), each with its inputs, outputs, checks,
outcomes and verdicts. `mode` chooses the branch: `shape` holds only digests, pseudonyms (`kind-` + 32 hex digits of
sha256(salt, the kind, a newline, the id)) and words of closed sets; `values` also holds the values the data rights
allow. The episode id is `episode-` + 32 hex digits of sha256 of the canonical JSON array
`["work-episode/1", salt_id, project, actor id, first action id]`; the split (`split/1`) buckets sha256 of
`["split/1", seed, episode_id]` (its first 8 hex digits modulo 1000) against the fractions per thousand. Digests and
action ids link to the named record for anyone who can read the deployment: this is pseudonymisation, not anonymity.

Rules JSON Schema does not express here, which a consumer checks: the fractions sum to 1000; `counts.episodes` is
`values + shape`; an episode's `start` and `end` are its first and last row's `at`, its rows are ordered by
(`at`, `action_id`) and consecutive rows are less than the manifest's `window_seconds` apart; every `final` entry names an
output of the episode, once per outcome; every split follows `split/1`; a `shape` export holds shape episodes only.
Fixtures for the source rows, joins, consent, segmentation, rights, pseudonyms, splits, the shape episodes and a
manifest are in `fixtures/work-episodes/` (synthetic). A deployment that does not export yet answers "Exporting the
trajectory of work is not available on this deployment yet."

Version 1.2.0 (E160) adds two optional properties, never null: `tier`, the deployment tier of the capture setting the
export ran under, and `files`, the payload files with their size and SHA-256. A 1.1.0 manifest stays valid. Who
enforces what (`fixtures/work-episodes/invalid-manifests.json` holds one case per row):

| Rule | JSON Schema | The model (`WorkEpisodes`) |
|---|---|---|
| `tier` is one of the five deployment tiers | yes | yes |
| a file name is `episodes.jsonl`, `episodes.parquet` or `turns.jsonl` (never the manifest or a descriptor) | yes | yes |
| `bytes` is not negative; `sha256` is 64 lower-case hex digits | yes | yes |
| at most three files | yes | yes |
| `episodes.jsonl` is listed | no | yes |
| each name once, in the order `episodes.jsonl`, `episodes.parquet`, `turns.jsonl` | no | yes |
| `bytes` and `sha256` match the file in the folder | no | no: the SDK's `load` will (E160 slice 1) |

## `ophiolite.work-turn/1` (preview): turns

`work-turn.json` is one line of a folder's `turns.jsonl`: one row of an episode as what was in front of the person or
agent (`observation`), what they did (`action`) and how it was judged (`judgement`), with the episode's id, mode and
split and the row's 1-based position `n`. The line re-arranges the row and converts back byte for byte; nothing is
summarised and no reward is invented. `work-turn-mapping.json` is the one table, and `work_turns.py` (standard library
only; the Platform and the SDK load it from its source text) runs it both ways: `turn(episode, n)`, `turns(episode)`
and `row(line)`.

| Row (or episode) | Line |
|---|---|
| `episode.episode_id`, `episode.mode`, `episode.split` | `episode`, `mode`, `split` |
| `attempt.chain`, `.n`, `.from`, `.continued` | `attempt.chain`, `.n`, `.from`, `.continued` |
| `attempt.ended` | `judgement.attempt_ended` |
| `offered`, `inputs` | `observation.offered`, `observation.inputs` |
| `action_id`, `at`, `operation`, `parameters`, `through`, `on_behalf_of`, `plan`, `outputs` | `action.` the same name |
| `request`, `instruction` (values only) | `action.request`, `action.instruction` |
| `checks`, `outcomes`, `verdicts` | `judgement.` the same name |
| `omitted` | `omitted` |

A row without `attempt` has `attempt` and `judgement.attempt_ended` null; a row without `offered` has
`observation.offered` null (present, never omitted). A line with one of `attempt` and `judgement.attempt_ended` null
and the other set is refused by the model and by `row`. A shape line carries the shape row's parts only (no request,
instruction, reason, name, label or row key). Fixtures: `fixtures/work-turns/` (`shape`, `auto` mixing a shape and a
values episode, `empty`, and `invalid-cases.json`).

## `ophiolite.profile-migration/1` (preview)

`profile-migration.json`: a stored item moved to a released profile version. A move never edits a stored revision: it
writes a new revision of the same item and one record naming the revision moved from (the item's head when the move
started) and the new one, the profile and the stored SHA-256 of each revision's `data` form, the release that ran the
move (`null` when the deployment names none), the system actor `system:profile-migration` and the time (ISO-8601 UTC).
The two profiles are of the same kind and never equal. One record per item, from revision and to profile; a revision is
the `to` of at most one record. Fixtures are in `fixtures/profile-migration/` (`valid.json`; `same-profile.json`, which
a consumer refuses).
