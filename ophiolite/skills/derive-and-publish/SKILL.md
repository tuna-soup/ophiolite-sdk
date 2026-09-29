---
name: derive-and-publish
description: Publish a file you computed in Python from exact revisions, with the method you used, recoverably.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/publications/derive","/api/v1/projects/{project}/applications/result-history"],"symbols":["ophiolite.client.Client.read_data","ophiolite.typed.TriangulatedSurface.write","ophiolite.writers.WrittenOriginal","ophiolite.client.Client.publish_derived","ophiolite.publish.WorkFolder.publish_derived","ophiolite.client.Client.history"],"errors":["validation-failed","recovery-unavailable","integrity-conflict","PERMISSION_DENIED"]} -->

Proceed when publishing is part of the user's task. State the exact parent
revisions, the method you will declare, and that the result starts private to
its author. Publishing and sharing are separate actions.

Read the parents at exact revisions, compute locally, then write the result with
the writer of its type. Every declaration (CRS, units, value meaning) is a keyword
you must give; write "unknown" when it is not known. Nothing is inferred.

```python
from ophiolite.typed import TriangulatedSurface

work = client.work_folder(private_folder)
points = client.read_data(asset_id, revision)          # a point set at an exact revision
xy = [(x, y) for x, y, z in points.points]
triangles = my_triangulation(xy)                       # for example scipy.spatial.Delaunay
written = TriangulatedSurface.write([tuple(p) for p in points.points], triangles,
    crs=points.context["crs"], xy_unit=points.context["xy_unit"], z_unit=points.context["z_unit"],
    z_meaning=points.context["z_meaning"], positive=points.context["positive"],
    vertical_datum=points.context["vertical_datum"])
receipt = work.publish_derived(written, name="Top surface", from_=[points.descriptor],
    method={"name": "scipy.spatial.Delaunay", "library": "scipy", "version": "1.14.1",
            "parameters": {}})
history = client.history({"asset_id": receipt.asset_id, "revision": receipt.revision,
                          "authority": "ophiolite:derived"})
```

`Client.publish_derived` needs a `command_id` you keep: retrying with the same id
returns the same receipt; a new id can publish twice. Prefer the work folder, which
saves the command id and the file's digest before sending, so a crash or a lost
reply is recovered by calling it again with the same file. A different file while a
publication is unfinished is refused as `recovery-unavailable`.

The server rechecks at publication that you may still reuse every parent and that
every original they came from still admits you (`PERMISSION_DENIED` otherwise). A
command id reused for a different request is `integrity-conflict`. A value the
format cannot carry (a real value equal to the NODATA or null marker, a missing
fault-stick coordinate) is `validation-failed`, never altered. A new version of
your own result uses `new_version_of` and `expected_parent` and must come from the
same originals.

The method is recorded exactly and shown in words only for names Ophiolite
documents; any other name appears as "Method declared by its publisher", with the
exact name under Technical details. It is script-declared: code and environment
are not captured unless you say so in the parameters.
