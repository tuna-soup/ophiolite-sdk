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
