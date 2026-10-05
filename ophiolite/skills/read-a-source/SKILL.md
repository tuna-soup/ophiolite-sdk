---
name: read-a-source
description: Read a connected SQL well-location table (a source selection) from Python or the command line, verified against its revision and checksum.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/sources/list","/api/v1/projects/{project}/sources/export","/api/v1/projects/{project}/entities/list","/api/v1/projects/{project}/releases/list","/api/v1/projects/{project}/releases/get","/api/v1/projects/{project}/releases/download-snapshot","/api/v1/projects/{project}/releases/download"],"symbols":["ophiolite.Client","ophiolite.locations.Wells","ophiolite.well_sources.with_source","ophiolite.sources.Source","ophiolite.sources.SourceSnapshot","ophiolite.sources.SourceDescription","ophiolite.aio.AsyncSource","ophiolite.errors.SourceRevisionDiffers","ophiolite.errors.SourceChecksumMismatch","ophiolite.errors.SourceNotSupported","ophiolite.errors.SourceNotFound","ophiolite.errors.SourceNeedsReview","ophiolite.errors.SourceRevisionUnavailable","ophiolite.errors.SourceDetached"],"errors":["source-not-found","source-not-supported","source-checksum-mismatch","source-revision-differs","SOURCE_NEEDS_REVIEW","SOURCE_REVISION_UNAVAILABLE","SOURCE_DETACHED","PERMISSION_DENIED","capacity-exceeded"]} -->

Use this when the user wants the rows of a table connected to their project — for
example a SQL well-location table — rather than the project's wells. A source
selection is something the user bound in the Workspace; a caller lists and reads
only the selections they bound themselves (another member's are not listed). An
access key with read scope is enough.

```sh
ophiolite sources list --json
ophiolite sources describe SOURCE_ID --json
ophiolite sources read SOURCE_ID --expect-revision REVISION --out rows.csv
```

```python
from ophiolite import Client

with Client(url, project, credential) as client:
    for source in client.sources():
        print(source.id, source.name, source.profile, source.state, source.revision)
    source = client.source(source_id)          # by id; a name never matches
    snapshot = source.read(expect_revision=source.revision)
    frame = snapshot.to_frame()                # the mapped view; to_frame(original=True) for every column
    print(frame.attrs["crs"], frame.attrs["revision"], len(snapshot))
```

From a project well to its source row (E50c): wells imported from a table are located
by a row of the copy the import kept. `with_source` reads those copies under their own
permission check and keeps every well, marked `joined`, `no origin` or `not readable`.

```python
wells = client.wells()
frame = wells.with_source(columns=["operator"])   # columns=None: every original column
print(frame[["name", "source_state", "source_reason", "source.operator"]])
```

```sh
ophiolite wells list --with-source --column operator --json
```

Rules to keep:

- A source row is not a project well. `read()` returns the table's own fields and
  creates no wells or entities. Wells from `client.wells()` carry only a reference
  to the source row they were located from.
- Only SQL well-location tables (`sql-wells/1`) are read in this release; other
  kinds are listed but refused before any request (`source-not-supported`).
- Every read is verified: the returned source must be the selected one, and the
  payload's sha256 must equal the manifest's sha256 and the revision
  (`source-checksum-mismatch` otherwise; read again). The checksum guards transport
  and decoding, not authenticity.
- `expect_revision` checks what the server returned; it never asks for an older
  revision. On `source-revision-differs` no rows are exposed: decide whether the new
  revision is the one wanted, then read again. `SOURCE_REVISION_UNAVAILABLE` means
  the upstream row changed and the held revision can no longer be read.
- `describe()` costs one full read. Coordinates are in the declared CRS
  (`snapshot.crs`); nothing is converted.
- `SOURCE_NEEDS_REVIEW` carries the server's words (also when a table is over the
  server's bound); the mapping is reviewed in the Workspace. `SOURCE_DETACHED`: the
  selection was removed; a project administrator resumes it. A response over the
  SDK's bound raises `capacity-exceeded` with the bound in bytes.
- `with_source` joins the row that supplies the location `wells()` returned (the
  newest one you may read), from the kept copy, not the live table. `no origin`: no
  source row you may read locates the well (none, or one you may not read: the server
  shows neither). `not readable`: the copy was withdrawn, is under review, or is no
  longer yours to read; `source_reason` says which. A copy whose bytes do not match
  the revision raises `source-checksum-mismatch`; nothing is returned.
- Never retry a refusal in a loop, never pass a database credential, and never
  present a written `--out` file as shared or kept up to date: it is the user's own copy.
