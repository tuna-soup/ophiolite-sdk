# Project folder 2 (`ophiolite.project-folder/2`)

A project folder is a directory of ordinary files — Parquet tables, GeoTIFF grids, the originals they were read from —
with one `manifest.json` that lists every file with its size and SHA-256 and says what each item is. Any program may
write one; anyone may read one with pandas, GDAL or QGIS and no Ophiolite server. This page is the whole contract.

The folder is the `folder` block of a portable bundle v2 manifest (`ophiolite.portable-bundle/2`, bundle version
2.14.0 or later for a /2 block, 2.12.0 or later for a /1 block; `MINOR` in `folder.py` is the one answer, and the
fixtures here are 2.14.0 and 2.12.0 accordingly). The block's structure is `folder-schema.json`; every rule beyond
structure is `folder.py` (`validate`), and each rule has a code a reader reports. `kinds.json` is the closed table of
what an item may be.

## What a folder holds

| Path | Role | What it is |
|---|---|---|
| `items/<name>.parquet`, `items/<name>.tif` | `item` | the data, one file per item in `items` |
| `originals/<name>` | `original` | a source file as it was read, byte for byte (`text/csv` or `text/plain`) |
| `recipe.json` | `recipe` | the decisions `ophiolite-mapper` wrote the folder by (only that writer) |
| `lineage/prov.json` | `lineage-prov` | PROV-JSON: which items came from which originals |
| `identity/{entities,aliases,relationships}.parquet` | identity | the wells and wellbores named, their spellings, their parts (none or all three) |
| `osdu/manifest.json` | `osdu-manifest` | an OSDU load manifest of the items (data definitions v0.30.1) |
| `assets/<n>/data.parquet` | `representation` | beside the assets of a server bundle, one per asset |

## Items

Each row of `items` says what one file is: its `path`, its `profile` (a row of `kinds.json`), the `kind` word that
profile gives (`wells`, `well-tops`, `deviation-survey`, `time-depth`, `point-set`, `table`, `well-log`, `grid`), its
OSDU statement — the kind the export matrix (`mapper/v1/export-matrix.json`) names for the profile, or `none` with the
matrix's reason — its `declarations` and its `rows`.

A declaration is `{name, value}`: a name the profile's table target declares (`targets/v1/<target>.json`, for example
`crs`, `depth_unit`) with a value of that declaration's type — an `EPSG:<code>` for a coordinate system, one of the
listed values for a unit or a choice, text, or a number. An item has at most one coordinate system. `rows` is the
number of rows of a Parquet item and `null` for a GeoTIFF.

### Payload rules (what a writer must produce)

| Item | Rule |
|---|---|
| table target `<t>` | one column per field of `targets/v1/<t>.json`, in its order; `identifier`, `name`, `text` and `reference` fields as strings, `number` and `coordinate` fields as float64; every column nullable; field metadata `ophiolite.field` (and `ophiolite.unit` where a unit declaration applies); schema metadata `ophiolite.target` and `ophiolite.declarations` (JSON, sorted keys), and `ophiolite.recipe` only when there is a recipe |
| a target with coordinates (`wells`, `point-set`, `table`) | additionally a `geometry` column of WKB points and GeoParquet 1.1.0 `geo` metadata whose `crs` is the PROJJSON of the item's coordinate system; a reader that ignores GeoParquet still reads x and y |
| `las2/1` | the columns, types and nullability of `items/well-log.parquet` in `mapper/v1/folder-schema.json` (`items`) |
| `geotiff/1` | a baseline GeoTIFF with one band and a `ProjectedCSTypeGeoKey` or `GeographicTypeGeoKey` equal to the item's coordinate system |

### File roles per writer

| Role | writer `ophiolite-mapper` | any other writer |
|---|---|---|
| `recipe` | exactly 1 | none |
| `lineage-prov` | exactly 1 | 0 or 1 |
| `original` | at least 1 when the manifest lists no assets | any number |
| `item` | at least 1 when the manifest lists no assets | at least 1 |
| identity (three roles) | none or all three | none or all three |
| `osdu-manifest` | 0 or 1 | 0 or 1 |
| `representation` | one per asset | one per asset |

## Fields and rules

Written by `tools/folder-spec.py` from `folder-schema.json` and checked against the validator: every rule's code is a
code `folder.py` raises, and `fixtures/invalid/cases.json` holds a case the validator refuses with exactly that code.

<!-- fields:begin -->

| Field | Type | Required | Limits |
|---|---|---|---|
| `schema` | `"ophiolite.project-folder/2"` | yes | - |
| `writer` | object | yes | - |
| `writer.name` | string | yes | 1..80 characters |
| `writer.version` | string | yes | 1..80 characters |
| `recipe` | object | no | - |
| `recipe.path` | `"recipe.json"` | yes | - |
| `recipe.sha256` | string | yes | pattern `^[0-9a-f]{64}$` |
| `osdu` | object | yes | - |
| `osdu.tag` | `"v0.30.1"` | yes | - |
| `osdu.commit` | `"ff89d87caa43d05d1341dcaa6d258e1186ec8aa6"` | yes | - |
| `osdu.namespace` | string | yes | pattern `^([A-Za-z0-9][A-Za-z0-9-]{0,63}\|\{\{NAMESPACE\}\})$` |
| `items` | array | yes | 1..256 rows |
| `items[]` | object | - | - |
| `items[].path` | string | yes | pattern `^items/[a-z][a-z0-9-]{0,63}\.(parquet\|tif)$` |
| `items[].profile` | string | yes | 1..128 characters |
| `items[].kind` | string | yes | pattern `^[a-z][a-z0-9-]{0,63}$` |
| `items[].osdu` | `{kind}` or `{none}` | yes | - |
| `items[].osdu.kind` | string | yes | 1..200 characters |
| `items[].osdu.none` | string | yes | 1..200 characters |
| `items[].declarations` | array | yes | 0..32 rows |
| `items[].declarations[]` | object | - | - |
| `items[].declarations[].name` | string | yes | 1..64 characters |
| `items[].declarations[].value` | number or string | yes | - |
| `items[].rows` | integer or null | yes | 0.. |
| `files` | array | yes | 2..1006 rows |
| `files[]` | object | - | - |
| `files[].path` | string | yes | pattern `^(recipe\.json\|identity/(entities\|aliases\|relationships)\.parquet\|lineage/prov\.json\|osdu/manifest\.json\|assets/[0-9]{1,3}/data\.parquet\|originals/[A-Za-z0-9._-]{1,120}\|items/[a-z][a-z0-9-]{0,63}\.(parquet\|tif))$` |
| `files[].role` | one of `recipe`, `representation`, `identity-entities`, `identity-aliases`, `identity-relationships`, `lineage-prov`, `osdu-manifest`, `original`, `item` | yes | - |
| `files[].media_type` | one of `application/json`, `application/vnd.apache.parquet`, `text/csv`, `text/plain`, `image/tiff` | yes | - |
| `files[].asset` | integer or null | yes | 0..999 |
| `files[].sha256` | string | yes | pattern `^[0-9a-f]{64}$` |
| `files[].bytes` | integer | yes | 0.. |

| Field | Rule | Code |
|---|---|---|
| the manifest | a bundle v2 manifest (`ophiolite.portable-bundle/2`), version 2.14.0 or later for /2 (2.12.0 or later for /1), its `assets` a list | `manifest-invalid` |
| `schema` | `ophiolite.project-folder/2`, or `/1` (read by the mapper validator); nothing else | `schema-unknown` |
| `recipe` | present exactly when `writer.name` is `ophiolite-mapper` | `recipe-writer` |
| `files[].path` | listed once | `path-repeated` |
| `files[].path` | not a path an asset of the manifest lists | `path-in-asset` |
| `files[].media_type` | one of its role's media types; an item's is its profile's (`kinds.json`) | `media-type` |
| `files[].asset` | a `representation` names its asset | `asset-missing` |
| `files[].asset` | an asset of the manifest | `asset-unknown` |
| `files[]` | one row per asset for `representation`, one for each single-file role | `role-repeated` |
| `files[].path` | the role's path or pattern | `role-path` |
| `files[].asset` | null for every role but `representation` | `asset-misplaced` |
| `files` | each role's count for the writer (the page's table above) | `role-count` |
| `files` | none or all three identity tables | `identity-partial` |
| `recipe.sha256` | the digest of the `recipe` file's row | `recipe-digest` |
| `items[].path` | listed once | `item-repeated` |
| `items[].profile` | a profile of `kinds.json` and of the export matrix | `profile-unknown` |
| `items[].kind` | the profile's kind word | `kind-profile` |
| `items[].path` | ends in the profile's suffix | `item-suffix` |
| `items[]`, `files[]` | every item has its file row of role `item`, and every such row its item | `item-file` |
| `items[].osdu` | the export matrix's statement for the profile: its `kind`, or `none` with its reason | `osdu-kind` |
| `items[].declarations` | names the profile declares, each once, with a value of its type | `declaration-unknown` |
| `items[].declarations` | one coordinate system per item | `crs-conflict` |
| `items[].rows` | a count for a Parquet item, null for a GeoTIFF | `rows-type` |

<!-- fields:end -->

## Reading a folder

A reader **must** check every file's size and SHA-256 against its row, that `items` and the item files agree, and the
kinds table and matrix strings; `ophiolite.folder.check(path)` does all of it and names the first problem. A reader
**may** ignore `osdu/manifest.json`, `lineage/prov.json`, the identity tables, `recipe.json`, `geometry` when it reads
x and y, and schema-metadata keys it does not know.

Versions are told apart by `folder.schema` (the folder) and `bundle_version` (the envelope). A
`ophiolite.project-folder/1` block — what `ophiolite-mapper` writes today — stays readable by its own validator
(`mapper/v1/mapper.py`); `translate_1` reads it as /2 (its items from the verified recipe, never guessed) without
rewriting anything on disk.

## Fixtures

`fixtures/valid/` holds four folders built from synthetic data only by `fixtures/build.py`: `recipe-wells` and
`wells-grid` (/2, with and without a recipe; `wells-grid` carries GeoParquet geometry and a 2×2 GeoTIFF in
EPSG:28992), `v1-wells` and `v1-las` (/1, as `ophiolite-mapper write` makes them). `fixtures/invalid/cases.json`
changes one thing per case and names the code and place the validator reports.
