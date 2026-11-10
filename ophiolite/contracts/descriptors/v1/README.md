# Release descriptors (`ophiolite.citation/1`, `ophiolite.release-descriptors/1`)

A release says, in the standards research infrastructures and dataset indexes already read, what it is. Beside its
`manifest.json`, a bundle or project folder may carry three descriptors: `ro-crate-metadata.json` (RO-Crate 1.1),
`croissant.json` (Croissant 1.0) and `datacite.json` (DataCite kernel-4.3 JSON). Each is derived from the manifest's
`citation` block, its files and its tables; a reader compares each with the manifest and refuses one that disagrees.
This page is the whole contract (E147 slice 0); no writer writes a descriptor yet (slices 1 to 3).

The block is `citation` in a bundle v2 manifest at bundle version **2.15.0** or later (`MINOR` in `descriptors.py`).
Its structure is `citation-schema.json`; every rule beyond structure, and the comparison, is `descriptors.py`, which the
Platform and the SDK run alike from its source text. `mapping.json` is the table below; `fixtures/` holds two valid
releases, a starter pack's citation and one invalid case per refusal.

## The citation block

| Field | Type | Required | Rule |
|---|---|---|---|
| `schema` | `"ophiolite.citation/1"` | yes | - |
| `title` | string | yes | 1..300 characters |
| `description` | string | yes | 1..5000 characters; required since E147 s1, as RO-Crate 1.1 requires the root's `description` (roc-validator check 8.2) |
| `published` | date `YYYY-MM-DD` | yes | a date that exists |
| `version` | string | no | 1..80 characters |
| `creators[]` | `{name, kind, identifier?}` | yes | 1..64, order kept; `kind` `person` or `organisation`; a person's identifier an ORCID URL, an organisation's a ROR URL |
| `publisher` | `{name, identifier?}` | yes | an organisation; identifier a ROR URL |
| `licence` | `{spdx}` or null | yes | `CC0-1.0`, `CC-BY-4.0`, `PDDL-1.0` or `ODC-By-1.0` (the open licences of the rights policy, by exact SPDX id); null when the rights basis is not an open licence |
| `notice` | string | exactly when `licence` is null | the terms in one or a few sentences |
| `doi` | null | yes | null until a registration record sets it (slice 5) |
| `prov` | `{path: "prov.json", sha256, bytes}` | no | a bundle's PROV-JSON beside the manifest, digested like a file; a project folder's PROV is its `lineage/prov.json` row, so a manifest with a folder has none |
| `descriptors[]` | names | yes | `ro-crate-metadata.json`, `croissant.json`, `datacite.json`, each at most once; the descriptors at the bundle's root |

At 2.15 an asset file row (`BundleFileV2`) gains `media_type` (the folder rows' list plus `application/octet-stream`
and `application/ld+json`). A manifest with a citation carries it on every asset file row: a descriptor's
`encodingFormat` comes from it, never from a file's name.

A starter pack (slice 3) takes `title` from `starter.json`'s title, `description` from its summary, `published` from
the date of `built_at`, `licence` from `licence.spdx`, `publisher` Open Subsurface Data, and `creators` from the
publisher its OSD catalogue record names (`fixtures/valid/starter-citation.json`; below, "Starter packs").

## The mapping

What `check()` compares, descriptor by descriptor. A path selects a list member by a key, written `[key=value]`: an
RO-Crate node `$.@graph[@id=./]`, a FileObject `$.distribution[@id=<path>]`, a DataCite description
`$.descriptions[descriptionType=Abstract]`. Anything outside these places is free. The Croissant `dataType` of a table
field is its target field's kind: `identifier`, `name`, `text`, `reference` → `sc:Text`; `number`, `coordinate` →
`sc:Float`.

<!-- mapping:begin -->

| Citation or manifest | RO-Crate 1.1 | Croissant 1.0 | DataCite kernel-4.3 JSON |
|---|---|---|---|
| constants | `@context` [`https://w3id.org/ro/crate/1.1/context`, {`sha256`: `https://schema.org/sha256`}]; node `ro-crate-metadata.json`: `conformsTo` `https://w3id.org/ro/crate/1.1`, `about` `./` | `@context` the Croissant 1.0 context; `conformsTo` `http://mlcommons.org/croissant/1.0`; `@type` `sc:Dataset` | `schemaVersion` `http://datacite.org/schema/kernel-4`; `types.resourceTypeGeneral` `Dataset` |
| node identity | root `./`; a File's `@id` is its manifest path; a creator's is its identifier or `#creator-<n>` (from 1); the publisher's its identifier or `#publisher` | a FileObject's `@id` is its manifest path; a recordSet's the table's name; a field's `<table>/<field>`; creators and publisher as in RO-Crate | - |
| `title` | root `name` | `name` | `titles[0].title` |
| `description` | root `description` | `description` | `descriptions[descriptionType=Abstract].description` |
| `creators[]` (order kept) | root `author`: the creators' `@id`s in order; each node `@type` `Person` or `Organization`, `name` | `creator[i]`: `@type`, `name`, `@id` | `creators[i]`: `name`, `nameType` `Personal` or `Organizational`, `nameIdentifiers[0]` `nameIdentifier` and `nameIdentifierScheme` (`ORCID`, `ROR`) |
| `publisher` | root `publisher`: a node `@type` `Organization`, `name` | `publisher`: `@type` `Organization`, `name`, `@id` | `publisher` (its name; a string in 4.3) |
| `published` | root `datePublished` | `datePublished` | `publicationYear` (its year), `dates[dateType=Issued].date` |
| `version` | root `version` | `version` | `version` |
| `licence.spdx` | root `license` `https://spdx.org/licenses/<id>` (the exact string) | `license` (the same string) | `rightsList`: exactly one entry, `rightsIdentifier` `<id>`, `rightsIdentifierScheme` `SPDX` |
| `licence` null | root `license` `#licence`: a `CreativeWork` named `No open licence` whose `description` is the notice | no `license` | no `rightsList` |
| `notice` | root `conditionsOfAccess` | `conditionsOfAccess` | `descriptions[descriptionType=Other].description` |
| `doi` null | no root `identifier` | no `identifier`, no `citeAs` | no `identifiers` |
| files (asset and folder rows) | root `hasPart`: the set of their paths with `manifest.json` and `prov.json`; each a File with `sha256`, `contentSize` (the bytes as a string), `encodingFormat` (the row's `media_type`); no other File | `distribution`: one FileObject each, `contentUrl` (the path), `sha256`, `contentSize` `<bytes> B`, `encodingFormat`; no other | `sizes` [`<total> bytes`], `formats` the sorted distinct media types; no file digest |
| tables (a /2 folder's table-target items; from 2.16 a bundle's typed tables) | - | one `recordSet` per table, its `field` the field `@id`s in target order; each field `name`, `dataType` (field kinds), `source.fileObject` (the item's path, or the asset's `data.json`), `source.extract.column` (folder: the field's name) or `source.extract.jsonPath` (bundle: the path of the bundle tables table, and no `column`) | - |
| `prov` (a bundle's PROV-JSON) | File `prov.json`: `sha256`, `contentSize`, `encodingFormat` `application/json`, `conformsTo` `https://www.w3.org/submissions/prov-json/`; a /2 folder's PROV is its `lineage/prov.json` row | - | - |
| `manifest.json` | a File: `encodingFormat` `application/json`, no `sha256` | - | - |

<!-- mapping:end -->

A descriptor's bytes are not digested in the manifest (each is written after it, and RO-Crate lists the manifest): a
reader derives what each must hold and compares. `prov.json` is digested (`citation.prov`).

## Refusals

A reader checks the citation first, then each listed descriptor in the order `descriptors` names them, and names the
first problem by its code, its file and a JSON path in it. `descriptors.py` decides the codes of the first table from
the manifest and the descriptors' bytes; the reader decides the second before it parses anything.

<!-- codes:begin -->

| Code | When |
|---|---|
| `citation-minor` | a manifest with a citation is not a bundle v2 manifest at 2.15.0 or later |
| `citation-schema` | the block breaks `citation-schema.json`, names an unknown descriptor, has a date that does not exist, an identifier of the other kind's scheme, one identifier with two names (two creators, or a creator and the publisher; at the later `name`), no notice with a null licence, or a `prov` beside a project folder |
| `citation-media-type` | an asset file row of a manifest with a citation has no `media_type` |
| `notice-without-null-licence` | a notice beside an open licence |
| `descriptor-repeated` | a descriptor named twice |
| `descriptor-unreadable` | a descriptor is not UTF-8 JSON of an object, holds NaN or Infinity, or (the reader's) is a link or lies under one, is not a regular file, exceeds the file limit or takes the bundle over its total |
| `descriptor-disagrees` | a value of the mapping differs from what the manifest gives, or a descriptor lists a file, creator or field the manifest does not |
| `starter-record` | a starter pack's catalogue record (in `evidence.json`) names no publisher |
| `starter-artefact` | a starter pack's artefact is not `{path, sha256, bytes}`, or one path is listed twice with another digest or size |
| `episodes-manifest` | a work-episodes folder's `trajectories.json` is not JSON of an object that passes `ophiolite.work-episodes/1`, has no `tier` or `files` (an export before 1.2.0), or lists no `turns.jsonl` |
| `file-missing` | (the reader's) a listed descriptor or `prov.json` is absent |
| `file-digest` | (the reader's) `prov.json` does not match `citation.prov` |

<!-- codes:end -->

The default line says what disagrees in words (`not verified: the licence in croissant.json disagrees with the
manifest.`, `WORDS` in `descriptors.py`; "with starter.json" for a starter pack); the code and
`croissant.json:$.license` are details.

## Readers and versions

A reader from 2.15 lists the descriptors and `prov.json` among a bundle's files and compares them. A reader before
2.15 does not know them: it reports each as a file the manifest does not list (`file-unlisted`), and its `pack`
refuses them. A manifest without a citation reads as before.

A reader from 2.16 compares a cited bundle's typed tables (below). A 2.15 reader expects no record set in a bundle's
Croissant, so it refuses a 2.16 bundle that has tables (`descriptor-disagrees` at `$.recordSet[@id=…].field`); a cited
bundle without tables stays 2.15, and a 2.15 bundle reads on a 2.16 reader as before (no tables are derived below 2.16).

## Bundle tables (2.16)

From bundle 2.16 (`TABLES_MINOR`), `inputs()` gives, after a folder's tables, one table per typed bundle asset whose
profile `BUNDLE_TABLES` names and whose `normalized` file is a `data.json` (`bundle_tables(assets)`, which the SDK's
writer also asks). Its id is `<asset folder>/<target>` (`assets/0/well-tops`), its file the `data.json` path, and each
field reads the normalized document by a JSON path (`extract.jsonPath`, with no `column`); its `dataType` is the table
target's field kind, as for a folder.

| Profile | Target | Fields and JSON paths |
|---|---|---|
| `well-tops-csv/1` | `well-tops` | `name` `$.tops[*].name`, `md` `$.tops[*].md`, `tvd` `$.tops[*].tvd`, `source` `$.tops[*].source` |
| `deviation-csv/1` | `deviation-survey` | `md` `$.stations[*].md`, `inclination` `$.stations[*].inclination`, `azimuth` `$.stations[*].azimuth`, `tvd` `$.stations[*].tvd` |
| `time-depth-csv/1` | `time-depth` | `depth` `$.depth[*]`, `time` `$.time[*]` |
| `points-csv/1` | `point-set` | `x` `$.points[*][0]`, `y` `$.points[*][1]`, `z` `$.points[*][2]` |

A Croissant reader (mlcroissant 1.1.1) reads each as records: the listed columns, in row order, with nulls kept. Not
described yet (E147 s2c): a time-depth `velocity` (null when absent, which the reader cannot take), point-set
attributes, the point-columns form (`data.ophpts`, which gives no table), an asset's `well`, and `sql-wells/1` and the
`table-*/1` profiles, which are not exported as typed bundle assets.

## Starter packs

A starter pack (Open Subsurface Data's `osd.starter/1`) has no manifest. Its citation is derived, never stored
(`starter_citation(starter, record)`, E147 s3 R-2): the table at the top of this page, with one organisation creator,
the publisher its catalogue record names (the record `evidence.json` holds; R-1, until OSD carries an originator
field), a null licence and `PACK_NOTICE` when the pack licence is not open (the `export_licence` rule), no DOI and the
three descriptors. Its files (`starter_files`) are the artefacts of every target, each path once in the order first
listed, at `files/<path>` with their digest and size from `starter.json` and a media type by suffix (`STARTER_MEDIA`;
`application/octet-stream` otherwise). It has no tables (E147 s2c). The RO-Crate names `starter.json` where a bundle's
names `manifest.json` ("The starter pack document"), and DataCite's `resourceType` is `Starter pack`
(`starter_documents`). `verify_starter(starter, record, raw)` compares the three descriptors as `verify` does; the SDK
reads the pack's files and re-hashes its artefacts first.

## Work-episodes folders

A work-episodes folder (`export_trajectories`, `ophiolite.work-episodes/1` at 1.2.0 with `tier` and `files`) has one
descriptor, `croissant.json`, and its citation is derived from `trajectories.json`'s bytes, never stored
(`episodes_citation`, E160 s0 D3): the deployment as title, organisation creator and publisher; a sentence of
purpose, mode and counts; the UTC date of `exported_at`; the release as version; the one licence the values rely on,
else a null licence with `EPISODES_NOTICE` naming each (or `EPISODES_UNLICENSED` for none); no DOI. Its files
(`episodes_files`) are `trajectories.json` (the digest and size of its bytes) and each file it lists, with a media type
by suffix (`EPISODES_MEDIA`). Its one record set, `turns` over `turns.jsonl`, has a field per scalar place of a
`ophiolite.work-turn/1` line (`TURN_FIELDS`: a column and, one level down, a `transform.jsonPath`; never a list):
the places of `work-turn.json` that `work-turn-mapping.json` names, a closed object of scalars expanded,
`action.instruction` only outside shape mode. The lists and objects of a line are read whole from `turns.jsonl`
(`ophiolite.trajectories.load_turns`). The Croissant also carries the responsible-AI places (`episodes_rai`):
`rai:dataCollection` (consent, tier, release, cursor), `rai:personalSensitiveInformation` (the manifest's linkage
sentence), `rai:dataUseCases` (the purpose) and `usageInfo` (each rights basis as `<basis> v<version> sha256:<hex>`,
absent when there is none). `verify_episodes(manifest_raw, raw)` compares it as `verify` does and returns the
citation; `episodes_documents(manifest_raw)` writes it. The SDK reads the folder and checks `turns.jsonl` first.

## Writing

`documents(citation, files, tables, resource_type)` (E147 s1) writes the descriptors a citation lists from what
`inputs()` returns, and `serialize()` gives their bytes (two-space JSON, UTF-8, one closing newline). Every compared
place comes from the same helpers as `expected()`; the rest is the writer's, fixed by the valid fixtures and not a
conformance requirement: the licence's SPDX name (`LICENCE_NAMES`), a file's name (its base name; "Lineage
(PROV-JSON)" for a folder's lineage row, "Provenance (PROV-JSON)" for `prov.json`, "The bundle manifest"), one node
per identifier, the graph order (metadata, root, creators, publisher, licence, manifest, `prov.json`, files), `hasPart`
in manifest order then `prov.json` then `manifest.json`, a DataCite `schemeUri` per scheme, and `resource_type` as
DataCite's `resourceType` (`Project folder`, `Well log bundle`). It writes no `keywords`. The written documents equal
the folder-field and bundle-tables fixtures, and the bundle-wells ones without their two `keywords`.

`export_licence(licences)` (E147 s2) gives an export's `licence` and `notice` from each file's own licence (a catalogue
file's `acquisition.listed_in.licence`, `None` for a file without one): the SPDX id when every file carries the same
open licence (an id in `LICENCE_NAMES`, `redistribution` `allowed`, not share-alike: the Platform's `open_licence`),
otherwise a null licence with one of two literal sentences, `MIXED` when every file states a licence and `UNSTATED`
when one does not.

## Fixtures

`fixtures/valid/` holds three releases, one starter pack and one citation, all synthetic. `bundle-wells/` (8 files) is a 2.15 bundle of one
LAS curve (`assets/0/`: the original, its descriptor and the normalized curve, the SDK's own synthetic contract
fixtures), `prov.json`, a citation with two persons (one with an ORCID), a ROR publisher, `CC-BY-4.0` and a version,
and the three descriptors written by hand. `folder-field/` (6 files) is the E117 synthetic-field project folder
(`examples/folders/synthetic-field/`) at 2.15: its wells item and `lineage/prov.json`, a citation with a null licence
and a notice, and the three descriptors with one Croissant recordSet for the wells table. `bundle-tables/` (16 files)
is a 2.16 bundle of four typed assets from the SDK's released synthetic bundles: the 2.0 well tops, a second tops
asset with other values, the 2.6 time-depth table (its original with LF line endings) and the 2.2 point set, each with
its original, descriptor and `data.json`; a citation, and the three descriptors as `documents()` writes them, the
Croissant with four record sets. `starter-pack/` (5 files) is a starter pack's `starter.json` with a Python and a
ResInsight target sharing `ATTRIBUTION.md` (five distinct artefacts, CC-BY-4.0), its `evidence.json` with the catalogue
record, and the three descriptors as `starter_documents()` writes them; it holds no artefact bytes (the contract
compares values). `starter-citation.json` is a starter pack's citation. `episodes-shape/` (4 files),
`episodes-auto/` (4 files) and `episodes-empty/` (4 files) are work-episodes folders: the work-turns fixtures'
`episodes.jsonl` and `turns.jsonl` byte for byte, a `trajectories.json` naming one licence and one rights basis
(shape), two of each (auto) or none and no episodes (empty), and the `croissant.json` `episodes_documents()` writes,
one line a place. `fixtures/invalid/cases.json` (69 cases)
changes one thing per case and names the code, file
and place the check reports; its `reader` cases are the bundle reader's, its `starter` cases a starter pack's, its
`episodes` cases a work-episodes folder's.
