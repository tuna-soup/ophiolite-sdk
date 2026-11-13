# Held copies (E171, who holds what)

A member asks a project, or one item in it, "who holds this?" and reads one row per connected copy and item: the
application, the version it last confirmed and since when, whether it stays or follows, and whether it is current,
behind or no longer readable. Slice 0 fixes the contract; nothing is recorded or served by it yet (the read
`exchange/holders` answers "not yet" until slice 1).

- `held-copies-schema.json` (`ophiolite.held-copies/1`, generated from `services/project_gateway/held_copies.py`):
  the answer one reader is served (`HeldCopies`), and in `$defs/HoldersRequest` the body of the read:
  `project_id` (equal to the path's project), an optional `item`, `limit` 1 to 500 (default 200) and an opaque
  `cursor` taken from a previous answer's `next`. `next` is null on the last page.

## The fields and how they are computed

All times are RFC 3339 in UTC with a `Z` suffix. `as_of` is when the heads were read (one read per answer);
`complete_since` is the time from which the history is complete (the backfill limit).

- `copy`: opaque, `sha256` of the canonical JSON `[project, actor, holder id]` (sorted keys, no spaces), first 16 hex
  characters. One holder id under two people is two copies. It is never the holder id.
- `application`: `application:<name>` (the suffix grammar of `profiles/v1/source-systems.json`), `script`, or
  **null, which means the copy never declared one**. The word is **the client's declaration**: from slice 1 a
  connector declares its own word (the QGIS plug-in `application:qgis-plugin`, the word it already declares as the
  `system` of a send's source block) and a plain SDK call declares `script`. Copies recorded before slice 1 are backfilled from
  `consumer.applied` events, which carry no word, and read null. The sentence served for null reads as "not said",
  never a guessed word. It is shown as a declaration, never as proof of which program holds the copy. `script` is not
  a source system and is not added to that list.
- `person`: `you`, `named` (with `name` when the member has a usable one) or `a-member` (no name). `key`: the access key's name, present only when the
  reader owns that key. Which of these a reader is served is the server's authorization, not something the document
  can show; `problems` checks only that a name never accompanies `a-member`.
- `version`: the revision the copy holds, `how` it came there (`got` or `sent`), `since` = the first confirmation of
  this revision by this copy after its last different revision, `confirmed_at` = the latest confirmation.
- `mode`: `stays`, `follows` or **null, which means "not said"**: the copy never declared a mode. Nothing served
  claims a choice nobody made.
- `state`, computed at read time against the exact head and never stored: `current`; `behind`, with
  `behind.count` = the number of the item's versions newer than the held one that the reader may read and
  `behind.newest` = the head (revision, author, time); `no-longer-readable` = the copy's person may no longer read the
  head (served only to project administrators and to that person; to everyone else such a row is absent).

Rows are in the order (`item.asset_id`, `version.confirmed_at`, `copy`); one copy appears once per item. When `item`
is set every row is of that item; an item the reader cannot read, or that does not exist, answers `rows: []` in the
same shape.

The codes in this contract (`behind`, `a-member`, the reason codes of `held_copies.problems`) are **not served
words**: what a person reads ("connected application", "newer version available") is the Workspace's to choose, and
never "subscriber".

## Fixtures (counted by hand)

One scenario, project `p-held`, clock `2026-11-10T09:00:00Z` plus whole minutes. Ana is an administrator, Ben a
member. Item `horizon-top` (kind `horizons`): r1 by Ana at 09:00, r2 by Ben at 09:10, r3 by Ana at 09:20. Item
`wells-north` (kind `wells`): w1. Copies:

| Copy | Person, holder | Application | Holds | Mode |
|---|---|---|---|---|
| A `7dd1510b9be8581e` | Ana, holder `5f0c…7e35`, key `qgis-ana` | `application:qgis-plugin` | got r1 at 09:05, again at 09:12; got w1 at 09:25 | stays |
| B `136d32bc9e3c4e68` | Ben, holder `9b2e…6e81` | `script` | got r2 at 09:15 | follows |
| C `cdb697e1bb2a9601` | Ana, holder `c47d…3d26`, signed in (no key) | `application:opendtect` | sent r3 at 09:20 | stays |
| D `94ca0787245c51aa` | Ben, the same holder id as A | null (not said; backfilled before slice 1) | got w1 at 09:25 | null (not said) |

- `valid/held-copies-admin.json`: Ana asks the project at 09:30. Five rows: A behind 2 (r2, r3), B behind 1 (r3), C
  current; on `wells-north` A and D current at the same 09:25, A first by `copy`. A's key shown; Ben `named`.
- `valid/held-copies-member.json`: Ben asks `horizon-top` at 09:30: Ana's rows `a-member` with no key, his own `you`.
- `valid/held-copies-not-readable.json`: Ana asks `horizon-top` at 09:40, after Ben lost read on r3: B
  `no-longer-readable`.
- `valid/held-copies-empty.json`: a reader who cannot read `horizon-top`: `rows: []`.
- `invalid/held-copies-cases.json`: `schema` cases, each refused by the schema at its named path, and `semantic`
  cases, each valid by the schema and refused by `problems` with exactly its reason.
