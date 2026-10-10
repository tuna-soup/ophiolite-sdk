# Ophiolite contracts registry

`contracts/` is one registry. The index `registry.json` lists every schema,
profile and document Ophiolite publishes, each with its id, version, lifecycle
badge and registry-relative path. The directory references nothing outside
itself, so it can move to a public Contracts repository without renaming.

| Folder | Holds |
|---|---|
| `registry.json`, `registry-schema.json` | the index and its own structural schema |
| `profiles/v1/*.json`, `profile-schema.json` | one document per profile: display name, description, role, media types, rules |
| `assets/v1/` | the scientific asset envelope, the normalized LAS curve, the curve context, the discovery summary, synthetic fixtures |
| `scientific/v1/` | the two native protobuf exchange profiles and their structural schemas; `shale-volume-methods.json` (E52), the one table of shale-volume formulas, constants and reference values both runtimes are held to, with the HON-GT-01 excerpt it is checked against |
| `vocabulary/v1/` | shared terms; `quantities.json` (E52), the closed list of curve quantities with their OSDU LogCurveFamily names; `labels.py` (E105a), the one rule for a label a person reads, standard-library Python loaded from its source text |
| `procedures/v1/` | the procedure contract (E105a): `procedure-schema.json` (structure of `procedure.json`), `rules.json` (step lists, units, limits, sentences, `rules_version`), `procedure.py` (the one validator, bundle digest and archive check, run alike by the Platform and the SDK), `fixtures/` |
| `relationships/v1/` | the relationship predicate registry (E20) and the lineage document schema |
| `entities/v1/` | the entity (well, wellbore) and entity-assets schemas (E20) |
| `connectors/v1/` | the connector semantics vocabulary, copied byte for byte into Connectors and pinned by digest there |
| `tools/generate.py` | maintainer generator for every derived document |

The gateway loads the index and every document it names at start
(`project_gateway.contracts_registry.load()`, called from `create_app`). A
missing or malformed document refuses startup with the offending path; it
does not fail the first request. Server modules import `contracts_registry`
for ids, roles, rules and display names; they never carry a profile literal.

## Ids and versions

A **profile** is a versioned id that names a bounded meaning of bytes, for
example `las2/1` ("a LAS 2.0 file") or `ophiolite.application-curve/1` ("one
curve normalized exactly as the source stored it"). A **schema** is a JSON
Schema document. A normalized profile shares its id with the payload schema it
names.

The id grammar is `^[a-z0-9][a-z0-9.-]*(/[a-z0-9.-]+)*/[0-9]+$`. It is the
only constraint a JSON Schema places on a profile field; membership is
executable (`contracts_registry.require_registered`), not schematic, so
registering a profile never regenerates the envelope.

The trailing `/1` is the permanent version token that every stored reference
already carries. The semver in the index describes the schema *document*:
additive 1.x changes keep the id; a breaking change is a new id suffix.

Every generated schema identifies itself with `$schema`, `$id`
(`https://ophiolite.dev/contracts/<path>`) and `x-ophiolite` (`id`,
`version`, `lifecycle`); the loader refuses an index entry that disagrees
with its file.

## Lifecycle badges

- `preview`: served and tested, but the deployment may replace it with a new
  id suffix inside the program without a transition release. Every current
  pilot schema and profile is `preview` because none has qualification
  criteria beyond its own fixtures.
- `supported`: qualification criteria are written in the entry
  (`qualified_by`), only additive 1.x changes are allowed, and deprecation
  requires a transition release with an announced cutoff.
- `deprecated`: still served until the `cutoff` date recorded in the entry;
  consumers must move to the entry named in `replaced_by`.

## Profiles

Profile documents carry the human `display_name` and `description` (the
Workspace shows these, never the id, in its default layer), the profile
`kind` (`source` or `normalized`), which envelope schemas the profile is
served through (`serves`; today only `las2/1` is served through
`ophiolite.scientific-asset/1`), and for normalized profiles the
`payload_schema` that validates their bytes. Source profiles mirror their
entry in `connectors/v1/contract.json` under `connector`; a test proves the
mirror agrees so the Connectors digest pin stays valid.

The two native exchange profiles (`ophiolite/well-curve/1`,
`ophiolite/scalar-map/1`) have structural schemas under `scientific/v1/`;
their cross-field rules (equal lengths, strictly increasing depths, grid
shape) stay executable in `project_gateway.catalog.validate_snapshot`.

## Adding a profile

1. Write `profiles/v1/<slug>.json` (`schema`, `id`, `kind`, `lifecycle`,
   `display_name`, `description`) and list it under `profiles[]` with the
   same values.
2. If the profile has a payload schema, add the schema file with `$schema`,
   `$id` and `x-ophiolite`, and list it under `schemas[]`.
3. Add fixtures under `documents[]` with the schema they validate against.
4. Run the tests: `test_contracts_registry.py` checks the index, the files and
   the connector mirror.

A new profile is a registration; it is not served through the envelope until
its document says `serves` and carries `role`, `media_types`,
`normalized_profile`, `context_schema` and `representation_rules`
(`artifact_kind_by_origin`, `normalized`, `total`). `Asset.consistent()` and
`Representation.consistent()` read those rules; the origin-to-artifact-kind
rule is never loosened by registration.

### The seam for profile-specific context (E11)

In E1 `Asset.scientific` stays `ScientificContext`, published as its own
schema `ophiolite.curve-context/1`, and the `las2/1` document names it as
`context_schema`. The additive path for the first non-LAS profile is:

1. Register the profile and its context schema; name the schema in the
   profile document's `context_schema`.
2. Add a `model_validator(mode='before')` on `Asset` that selects the context
   model from `registry.profile(profile)['context_schema']`, and make
   `scientific` a union of the registered context models.
3. Dispatch the reader by profile (`applications.curve` is the LAS reader
   today; `las2/1.normalized_profile` records that its normalized form is
   `ophiolite.application-curve/1`).

Descriptors with `las2/1` and a `ScientificContext` body remain valid, so the
envelope id `ophiolite.scientific-asset/1` does not change.

## Served routes

- `GET /api/v1/contracts` returns `registry.json`.
- `GET /api/v1/contracts/<path>` returns the document at that registry-relative
  path, only if the index lists it (`schemas[].path`, `profiles[].path`,
  `documents[].path`); anything else is `404 not-found` and no filesystem
  lookup happens. Schema ids contain `/`, so documents are addressed by path;
  the index maps ids to paths.
- Both are public descriptions carrying no project data and are the one
  exemption, beside `/api/v1/openapi.json`, from the machine-credential rule
  of the `/api/v1/` boundary (exact index or subtree only).

`openapi/v1/openapi.json` is the committed snapshot of the live
`/api/v1/openapi.json`: automation routes, scientific asset routes and the two
registry routes in one document whose `info.x-ophiolite-contracts` names the
registry version and the served profiles. `openapi/v1/scientific-assets.paths.json`
is the generator input for the scientific paths, not a public document.

## Generated types

`generated/v1/ophiolite-contracts.ts` is emitted from every schema listed in
the index (`contracts/tools/generate.py --types`) and equality-tested. The
emitter supports exactly: `object` with `required` (a missing name becomes
`?`), `enum`/`const` (literal unions), `anyOf`/`oneOf` (explicit unions; a
discriminated `oneOf` keeps its members as named types so `status` narrows),
`array`, local `$ref`, the scalar types and `type: [..., "null"]`. Any other
keyword (`allOf`, `not`, `patternProperties`, an `additionalProperties`
schema, a bare `object`) makes generation fail naming the path; `if`/`then`
beside a type is a value rule (E54: an original's `bytes` bound) and emits
nothing, alone it fails as a schema with no type;
it never emits `any` or `unknown`. A schema without `additionalProperties:
false` still gets no index signature: contracts forbid extras. The Workspace
commits an exact copy with compile-time checks; Integration checks the bytes.

Fixtures are additionally validated by an external JSON Schema engine
(`jsonschema`, a test requirement installed by Integration) against the
schema each `documents[]` entry names; the tests skip, naming the
requirement, where the engine is absent.

## Upgrades

Refusing every read after a reader or library patch would make each upgrade
an outage for every retained asset, so only a `mapping` difference refuses.
Qualifying a reader or library upgrade as equivalent is the deployment's job:
before rollout, run the registry fixtures
(`test_scientific_assets.py::test_fixture_matches_actual_qualified_reader`,
`test_contracts_registry.py`) against the new environment. Until a record is
re-qualified, the descriptor says `recorded-differs` and shows both records.
A change of meaning is a new `parsing_policy` or `mapping` id, never a silent
edit of an existing one; `profiles/v1/application-curve.json` declares the
current triple and a test proves the live reader agrees.

## Regeneration

From the Platform root with the qualified Connectors on the path:

```sh
PYTHONPATH=services python contracts/tools/generate.py            # all derived documents
PYTHONPATH=services python contracts/tools/generate.py --schemas  # Pydantic-generated schemas only
PYTHONPATH=services python contracts/tools/generate.py --fixtures # synthetic fixtures only
```

Pydantic models remain the executable source; each published schema has an
equality test against `model_json_schema()`. The generator never writes under
`assets/v1/fixtures/frozen/`.
