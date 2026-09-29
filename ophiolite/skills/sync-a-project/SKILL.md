---
name: sync-a-project
description: Keep a local copy of a project current from its event log, and resynchronise when told to.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/changes/head","/api/v1/projects/{project}/changes/list","/api/v1/projects/{project}/changes/stream","/api/v1/projects/{project}/catalog/inventory"],"symbols":["ophiolite.Client.sync","ophiolite.sync.Sync.run","ophiolite.sync.Sync.changes","ophiolite.sync.Sync.follow","ophiolite.sync.Sync.resync","ophiolite.sync.Checkpoint"],"errors":["resync-required","PERMISSION_DENIED","authentication-required"]} -->

Use this when an application keeps its own copy of what a person can see in a project
(wells and wellbores, assets at their head, result groups) and must stay current.

```python
sync = client.sync("state/checkpoint.json")
sync.run()                    # a full resynchronisation the first time, then catch-up only
well = sync.cache.get("entity", well_id)
for event in sync.follow():   # live; resumes from the last frame after a reconnect
    sync.run()
```

An event never carries state to trust. It names a subject (`subject_kind`, `subject_id`)
and the client reads that subject again; an event for something you cannot read is never
shown, and a subject you lose access to stops appearing. Do not compare revisions or
generations across kinds to order changes: the order is the event cursor.

`sync.run()` resynchronises when the cache is new, the checkpoint belongs to another
person, capability set or copy of the project (its epoch), or when catch-up raises
`resync-required` (the server pruned or replaced the events after your cursor). The
checkpoint's cursor moves only after every read for a batch has landed, so a failure
repeats the batch instead of skipping it. A refused project access clears the copy.

Other events (sources, subscriptions, review stages, access blocks, approvals) are for
the application to act on: read them from `sync.changes(epoch, after)` or `sync.follow()`.
Routes: POST /api/v1/projects/{project}/changes/head, /api/v1/projects/{project}/changes/list,
/api/v1/projects/{project}/changes/stream (server-sent events with Last-Event-ID) and
/api/v1/projects/{project}/catalog/inventory (what a resynchronisation enumerates).
