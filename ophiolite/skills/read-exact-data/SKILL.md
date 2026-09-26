---
name: read-exact-data
description: Discover permitted scientific assets and read exact curve revisions with their context.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/scientific-assets","/api/v1/projects/{project}/scientific-assets/{asset}/revisions/{revision}","/api/v1/projects/{project}/scientific-assets/{asset}/revisions/{revision}/representations/{representation}"],"symbols":["ophiolite.Client.assets","ophiolite.Client.read","ophiolite.CurveSet.to_frame","ophiolite.CurveSet.to_numpy","ophiolite.CurveSet.workspace_url"],"errors":["verification-failed","axis-mismatch","incompatible-context","not-found"]} -->

Use the user's permitted selection. Discovery and exact reads need no application
binding or run. Choose each curve explicitly; do not silently use a different
revision when the requested bytes are unavailable.

```python
assets = list(client.assets())
data = client.read(asset_id, exact_revision, ["GR"])
frame, descriptor = data.to_frame()
array, array_descriptor = data.to_numpy()
link = data.workspace_url()
```

Keep the descriptor beside the array or DataFrame. It carries source identity,
units, depth reference, missingness, reader interpretation and exact checksums.
DataFrame metadata is separate until `descriptor.attach(frame)` is explicitly
requested. Missing samples become NaN in numerical views; zero stays zero. The
reader verifies the exact descriptor/body/artifact relation and full arrays.

Multiple curves require matching axes and scientific context. On `axis-mismatch`,
read separately or explicitly choose and document an alignment/conversion; the
SDK does neither automatically. Unknown units remain unknown. Never infer CRS,
datum, well identity or a source revision from a display name. Source revision
strings are opaque. A managed-derived profile may explicitly define a checksum
revision; do not generalize that rule to every source.

An exact Workspace link includes the scientific discriminator, revision and curve.
A fixture can demonstrate that URL contract without serving Workspace. A reader
mapping change refuses; read the exact artifact or upgrade the appropriate reader.
Other recorded/current reader differences remain explicit evidence, not hidden
reproducibility claims. Access to an old revision remains conditional on rights
and declared retention.
