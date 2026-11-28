# The item an activity row acted on (adhoc-activity-item-names)

A project's Activity says what happened and who did it. From this release a row that acted on one data item also
says which item: one block, `item`, stored with the row as it was at the action.

- `item-schema.json` (`ophiolite.activity-item/1`, generated from `services/project_gateway/activity_item.py`):
  `{id, kind, name, revision?, place?}`. `kind` is the item's kind as it is stored for it (for example
  `external-scalar-map`), or `project`. Every item but a project names the exact `revision` the row acted on. `place`
  is the wellbore the item is linked to (`{id, kind: "wellbore", name}`), only where the writer held one.

Where it is stored: `data.item` on an activity row (an upload, a derived result, a share, a completed operation, a
native report, a project setting), and `data.detail.item` on an action row that no item-bearing activity row follows
(creating a project, a map import, an AI-use self-grant, a verdict on a version). The activity event's own schema,
`ophiolite.activity/1`, is unchanged: `data` was always a free document.

Who sees it: a row is shown to exactly the people it was shown to before. The block on it is shown to a reader of that
exact version now; anyone else reads the row without it, its id included. A project item is shown to every reader of
the row; a place only to readers of that wellbore.

What it never is: a back-filled name. Rows written before this release carry no `item`, and none is made up for them.
The name is the one the item had at the action; a later rename does not change it.
