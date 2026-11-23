# What a change touches (E177)

Before or after a new version of an item is published, a person, a script or an assistant asks "what rests on the
version this replaces?" and reads one answer: the results made from it however many steps away, the outcomes accepted
on it and the connected copies that hold it. Slice 0 fixes the contract; nothing is computed or served by it yet (the
read `changes/affected` answers "not yet" until slice 1). Nothing in the answer is ever stored, and nothing is
invalidated, started or notified by reading it.

- `affected-schema.json` (`ophiolite.affected/1`, generated from `services/project_gateway/affected.py`): the answer
  one reader is served (`Affected`), and in `$defs/AffectedRequest` the body of the read: `project_id` (equal to the
  path's project), `asset_id` (the asked item), `against` (`head`, the default, or `next`), `limit` 1 to 500
  (default 200) and an opaque `cursor` taken from a previous answer's `next`. `next` is null on the last page.

## The fields and how they are computed

All times are RFC 3339 in UTC with a `Z` suffix. Each page is one read at its `as_of`: heads, access and counts are
read then.

- `asked`: the requested asset id, echoed. `item`: the asked item and its head, or **null when the item is unknown or
  the reader may not open it** (the same answer for both: existence is not told); then there are no rows and the
  counts are 0.
- `against`: `head` answers after a publication: what rests on a version that is not the head. `next` answers before
  the act: what rests on any version, the head included, that is, what will rest on an older version once the next
  is published.
- Rows, one of three kinds (`kind` is the discriminator):
  - `result`: an item other than the asked one whose **head** is reached, through one or more recorded edges
    (`derived-from` relationships and the lineage of maps written before E94), from a version of the asked item
    (with `head`: not its head). `distance` is the fewest edges; `rests_on` is the asked item's version at that
    distance, on a tie the newest. With `head`, an item whose head is reached only from the asked item's head is not
    a row. One row per item. A path starts at the asked version it leaves from; it never passes through another
    version of the asked item.
  - `acceptance`: an outcome that `outcomes/states` reads as accepted (its current version, not disabled or
    withdrawn, no conflict, the latest eligible publication) at the **head** of a result item that is a `result` row
    or whose deciding record's inputs name an older version of the asked item. `check_id` is that record.
    `accepted_on` is the newest version of the asked item, other than the head, that the record's inputs name, else
    the result row's `rests_on`; `newest` is the asked item's head. The acceptance is not invalidated: it stays the
    acceptance of its key, and the result's own states are unchanged.
  - `held`: the item's held copies exactly as `exchange/holders` (`ophiolite.held-copies/1`) serves them to this
    reader, not recomputed; its disclosure is E171's.
- `counts`: totals over the whole answer as read at this page's `as_of`, of rows the reader may open. A row the reader
  may not open is omitted (an acceptance on a result the reader may not open goes with it), `restricted` is true and
  nothing counts it.
- `without_inputs`: the project's items the reader may open, other than the asked one, whose head has no recorded
  input. They can be in no row; the line reads "N items in this project have no recorded inputs".
- `complete`: false when the walk reached its node cap; the counts are then "at least". Walked nodes and held rows
  draw on one read budget, so `complete: false` means this answer reached its read limit.

Rows are in the order: results by (`distance`, `item.asset_id`), then acceptances by (`outcome.id`,
`result.asset_id`), then held copies in E171's order. Pages are read afresh: a row that moved between two pages may
appear twice or not at all, as with held copies.

`affected.problems(doc, first_page)` checks the structure only, and the held rows by `held_copies.problems` (its
reasons prefixed `held:`); whether a reader may open a row is the server's authorization. The reason codes and the
field names are not served words: the words a person reads are the Workspace's.

## Fixtures (counted by hand)

- `valid/affected-*.json`: two scenarios. `p-affected` (the charter's): tops version 1, a horizon made from it, a
  residual made from the horizon and the tops and accepted under one outcome, an uploaded map, two held copies;
  answers after tops version 2, after a horizon version 2 made from tops version 2, for a member who may not open the
  residual, before tops version 2 against `next`, and for an item the reader may not open. `p-chain`: three tops
  versions, a result two steps away, a tie in distance, two paths, an acceptance reached only through the walk;
  two pages, one page against `next`, and an answer that reached the node cap.
- `invalid/affected-cases.json`: one defect per rule; `schema` cases are refused by the schema at their paths,
  `semantic` cases pass the schema and are refused by `problems` with their reason.
