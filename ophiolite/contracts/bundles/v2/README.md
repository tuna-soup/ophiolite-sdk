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
