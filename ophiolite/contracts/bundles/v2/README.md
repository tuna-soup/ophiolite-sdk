# Portable bundle 2.0 (`ophiolite.portable-bundle/2`)

Bundle 2 keeps every rule of [bundle 1.0](../v1/README.md) and adds typed assets.
Each asset entry states its `type`:

| `type` | Files per asset |
|---|---|
| `well-log` | `original.las`, `descriptor-<curve>.json`, `curve-<curve>.json` per selected curve (as 1.0) |
| `well-tops`, `trajectory`, `regular-grid-surface` | `original.<csv|asc>` (`original`), `descriptor.json` (`descriptor`), `data.json` (`normalized`, the served `ophiolite.well-tops/1`, `ophiolite.trajectory/1` or `ophiolite.regular-grid-surface/1`) |

A typed selection has `curves: []`. `relationships` is the descriptor block as served to
the exporter; a well log the exporter could not read is `"restricted"` and carries no
identifier. Exporters write `1.0.0` when every selected asset is a well log, so 1.x
readers keep working for curve-only bundles; a 1.x reader refuses 2.0 by its major.

## 1.1 / 2.1 — result groups as observations

An optional `observations.groups` lists the result groups the exporter could see that
contain selected results: the group name, when it was observed, the **selected** members
only (every position in `assets` holding that result) and the recommendation when it
names a selected exact revision the exporter could read (who, when, why), bound by asset
and revision. `meaning` is always `observation-at-export`: a group or recommendation is a
person's organisation at that moment, not a scientific property of the data, and it is
not updated after export. Members and recommendations the exporter could not see are
absent, never counted. The manifest fields `groups` and `recommendations` stay `null`, so
readers that predate observations keep reading these bundles (unknown fields are kept as
extensions). Curve-only bundles with observations are 1.1; bundles with typed data 2.1.

## 2.2 — meshes and point sets; 2.3 — fault sticks and seismic slices

2.2 adds `triangulated-surface` and `point-set` (files as the other typed assets). 2.3 adds
`polyline-set` (fault sticks: `original.txt`, `descriptor.json`, `data.json`) and
`seismic-slice`. A seismic-slice asset carries **no original**: the volume is identified
by `original: {sha256, bytes, included: false}` (the SHA-256 is the revision). Its files are
`descriptor.json` (the volume descriptor as served), `volume.json` (`normalized`, the served
`ophiolite.seismic-volume/1`: grid, sample meaning, header decisions, per-inline chunk
digests) and one `slice-<axis>-<label>.json` per chosen slice (`slice`, the served
`ophiolite.seismic-slice/1`). The selection names the slices (`slices: [{axis, label}]`)
and the asset lists each with its shape and declared scope. Readers check every slice
against the volume description — identity, direction, axes, sample meaning, shape and the
chunks it was read from — so a slice whose meaning changed is refused even when its
checksum was recomputed. A slice is not the complete volume. Exporters write the lowest
minor that expresses the content, so 2.2 readers keep reading older content and refuse
2.3 content.

## 2.5 — wavelets, rock model sections and seismic sections

2.5 adds `wavelet`, `model-section` and `seismic-section` (files as the other typed assets:
`original.txt`, `descriptor.json`, `data.json`, the served `ophiolite.wavelet/1`,
`ophiolite.model-section/1` or `ophiolite.seismic-section/1`). A section whose descriptor
says `origin: synthetic` is exported with its lineage like any result, but an importer
skips it with the reason "A synthetic section is not imported: its model and wavelet are
not part of the project it would join. Import them and compute it again." A 2.4 reader
refuses 2.5 content by its asset types ([fixture](fixtures/manifest-sections.json)).

## 2.6 — time-depth tables

2.6 adds `time-depth` (files as the other typed assets: `original.csv`, `descriptor.json`,
`data.json`, the served `ophiolite.time-depth/1`). The declared context travels in the
descriptor, `seismic_reference_elevation` as canonical decimal text; the wellbore
association travels in the graph form. A 2.5 reader refuses 2.6 content by its asset types
with "An asset has an unknown type."

## 2.7 — feature sets

2.7 adds `feature-set` for single-file feature sets (GeoJSON and GeoPackage: `original.geojson` or
`original.gpkg`, `descriptor.json`, `data.json`, the served `ophiolite.feature-set/1`). A feature set read
from a Shapefile package (its descriptor carries `package`) is refused, as other packages are, until E23c.
A 2.6 reader refuses 2.7 content by its asset types with "An asset has an unknown type."

## 2.8 — packages, recipes and decisions (E23c)

2.8 carries a revision that was read from a **source package**: a point set read with an import recipe
(Petrel or OpendTect, its descriptor `package.recipe` is set) or a feature set read from a Shapefile's members
(`package.recipe` is `null`). Nothing new is invented about what an interpretation is; the bundle carries what
the server stored for that revision, exactly, and nothing a reader of the revision could not already read. The
asset `type` stays `point-set` or `feature-set`, so tools that only need the values keep their dispatch. Three
file roles are added, each allowed only on an asset with a `package` block:

| Role | File | Content |
|---|---|---|
| `package` | `package.json` | the stored package manifest row, exact bytes (at most once) |
| `companion` | `companion-<k>.bin` | one per non-primary member, exact bytes; `k` counts the non-primary members from 1 in package order (0-8) |
| `interpretation` | `interpretation.json` | the stored interpretation row, exact bytes: `ophiolite.recipe-execution/1` (recipe document, its SHA-256, decisions with their evidence, execution) or `ophiolite.package-read/1` for a Shapefile (at most once) |

The primary member is the asset's `original`. Member names may be up to 200 characters of any script; bundle paths
stay `[A-Za-z0-9._-]`, so the names live in the asset's `package` block, a **projection** of the descriptor's
`package` record that readers compare field by field:

| `package` field | Equals |
|---|---|
| `package_digest` | the descriptor's `package.package_digest`, recomputed from the member records |
| `members[*].name, role, sha256, bytes` | the descriptor's member record and the stored package row's member (`digest` there) |
| `members[*].file` | bundle only: the path holding the member's exact bytes, listed in `files` |
| `recipe` | the descriptor's `package.recipe` (`reference` and `sha256`), or `null` for a Shapefile |
| `interpretation` | bundle only: the path of the interpretation file, or `null` |

Readers check on open, each with its own sentence: the projection agrees with the descriptor and the stored row;
every member file matches its record; the package digest recomputes; the primary is the original; the recipe
SHA-256 recomputes from the carried recipe document and equals the descriptor's; the decisions and execution equal
the descriptor's; the interpretation and package rows are the ones the descriptor's revision manifest lists, when it
has one. Checksums and these checks prove the parts agree with each other, not that the bundle is the original
revision: a fully consistent rewrite is not detectable without a digest from a trusted party, and readers say so.

Exporters write 2.8 only for an asset with a package; every other asset keeps the minor it had. Released readers
refuse a 2.8 package bundle and never misread it: a 2.2-2.7 reader refuses a point set by its file roles ("Bundle
1.0 carries exactly one original per asset and only known file roles."), a 2.1 reader by its type ("An asset has an
unknown type."), and a Shapefile feature set by its type below 2.7 and by its roles in 2.7 ([fixture](fixtures/manifest-package.json)).
The interpretation of an import recipe 2 (attributed events) travels in a portable form in a later minor; until
then an exporter refuses it. Not carried: the private recipe asset (only its pin and rules), display names of the
people who decided. Carried as before and stated here: the descriptor's `authorization.evaluated_for` and a group
recommendation's `by` name the exporter's account; the source files are kept byte for byte and may contain names.

## 2.10 — source records (E122 s5b)

The same rule as [1.10](../v1/README.md#110--210--source-records-e122-s5b): an asset entry may carry `source_record`,
the revision's `ophiolite.source-provenance/1` record as the gateway served it, unchanged, wrapped with its `asset_id`
and `revision`; exporters write 2.10 only when a record travels (any typed content, an entity graph or a kept original
keeps the major at 2), and `observations.source_records_omitted` when the server has no source records. The record
names a source system, its instance and a path or native id, which may contain names; it carries no words, reader or
person. Readers before 2.10 open such a bundle exactly as the same export without records
([fixture](fixtures/manifest-source-records.json)).

## 2.11 — a packaged polyline set (E123 S1f-c)

A package block, its package file, companions and interpretation file are allowed on a `polyline-set` asset as on a
point set or feature set (2.8): Petrel fault sticks travel with their `.crsmeta.xml` companion and their
`ophiolite.package-read/1` interpretation. Exporters write 2.11 only when such a set travels; every other export keeps
its minor. Readers before 2.11 refuse the bundle on its file roles ("Bundle 1.0 carries exactly one original per asset
and only known file roles."); they never read it without the package.

## 2.12 — a project folder (E116 s1)

A manifest may carry a top-level `folder` block, `ophiolite.project-folder/1`
([schema](../../mapper/v1/folder-schema.json)), checked by `mapper/v1/mapper.py` `validate_folder` with the manifest:
the files `ophiolite-mapper write` adds beside the assets, each with its path, role, media type, size and SHA-256.
With a folder block, and only with one, `assets` and `selection` may be empty: a folder the box writes alone holds no
exact server revision (an asset is one, verified against its original), so its sources travel as the block's
`originals/<name>` and its typed tables as `items/<target>.parquet`. Readers from 2.12 verify every folder file as an
asset file (no link on the way, size, digest, the bundle's file and total limits) and count them as listed. Readers
before 2.12 refuse a folder written by the box alone ("The bundle lists no assets or too many."); a bundle that carries
the block beside server assets they read as before, its core payloads checked, with the folder files listed as
unlisted.

## 2.13 — surveys (E142 s0)

A manifest may carry a top-level `surveys` list (at least one entry when present): each survey as the exporter could
read it at export ([survey revision](../../surveys/v1/README.md)) with its id, name, identity, producer reference,
default context, the revision exported (`meaning: survey-at-export`) or the base revision of a live view
(`survey-latest-at-export`), and `complete`, true only when every member of that revision is listed. A member is
`{role, asset_id, revision, entity_ref, asset}`: `asset` is the position in `assets` holding exactly that revision
when its bytes travel, else `null` (membership travels without the bytes); `entity_ref` is an `entity_id` of the
manifest's `entities` (2.4), so two members of one provisional well share it and two same-named provisional wells have
two. A relation names two members by asset and revision. `survey_contract.portable_problems` checks the block beside
the schema (`survey-asset-position`, `survey-asset-revision`, `survey-entity-ref`, then every survey rule on the
rebuilt snapshot). The `selection` and `assets` caps stay 128. The 2.12 schema accepts a 2.13 manifest (the block
is an extension to it); what a reader keeps of it on import is E142 s2, and a partial block never replaces a survey on import.

## 2.14 — a project folder of its own format (E117 s1)

The `folder` block may be `ophiolite.project-folder/2` ([the format's page](../../folders/v1/README.md)), which any
program may write: it lists each item with its kind, profile, OSDU kind, declarations and row count beside the files.
A /2 block needs bundle 2.14 or later (`folders/v1/folder.py` `MINOR` is the one answer; a /1 block keeps 2.12) and is
checked by `folders/v1/folder.py` `validate`; a /1 block is checked as in 2.12. Readers from 2.14 verify a /2 block's
files exactly as a /1 block's and list its items. A /2 block beside server assets is not read yet. Readers before
2.14 refuse a /2 block: their 2.12 check applies the /1 rules to it and names the first one it breaks.

## 2.15 — a release says what it is (E147 s0)

A manifest may carry a `citation` block ([the release descriptors page](../../descriptors/v1/README.md),
`ophiolite.citation/1`): title, creators, publisher, publication date, version, an open licence by its SPDX id or a
notice, and the standard descriptors at the bundle's root derived from it (`ro-crate-metadata.json`, `croissant.json`,
`datacite.json`). A bundle's own PROV-JSON travels as `prov.json`, digested in `citation.prov`. An asset file row may
carry `media_type`; a manifest with a citation needs bundle 2.15 or later and a `media_type` on every asset file row
(`descriptors/v1/descriptors.py` `validate_citation`). Descriptor bytes are not digested: a reader derives what each
must hold from the manifest and refuses one that disagrees (`descriptor-disagrees`, naming the file and the place).
Readers before 2.15 report the descriptors and `prov.json` as files the manifest does not list, and their `pack`
refuses them. Nothing writes a citation yet.

## 2.20 — what the SDK writer already wrote (E211 s1, additive)

The schema now admits what the SDK writer (`ophiolite/bundle.py` `write_bundle`, with `client.export`'s graph)
already wrote but 2.19 refused. They were found when the F3 sample's 2.17 bundle was checked against the schema
(ruling 26 Nov, named scope):

- the `well-table` asset type, the accepted rows a wells import kept (bundle 2.17, E162 s2a);
- `row` on a relationship's subject, the row of a table of wells an association names (E29);
- `null` for a relationship evidence's `source` and `statement`, as `entities/v1` serves an association's evidence
  and the writer copies it;
- `observations.entities_omitted`, why no wells and wellbores travel (E22b), for example "not requested".

Every change only widens: nothing becomes required, nothing is renamed or tightened, and every manifest that 2.19
admitted is still admitted. The v1 schema is unchanged (a 1.x manifest's `observations.entities_omitted` is still
refused there). A writer still names the lowest minor its content needs, so a bundle with a wells table stays 2.17.0.
`test_bundle_contract.py` removes each widening and compares the result with 2.19 byte for byte.
