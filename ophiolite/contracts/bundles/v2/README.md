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
