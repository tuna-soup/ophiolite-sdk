# Relationships (E20, ADR 0016 §2)

`registry.json` is the only list of relationship predicates Ophiolite accepts. Each predicate has
a class (structural, data association, scientific assertion, derivation), the kinds it joins, how
many objects of one kind a subject may have, whether it binds exact revisions, who asserts it
(people, or Ophiolite itself for derivations) and the evidence it needs. Anything else is refused.

- `part-of`: a wellbore is part of one well; a person's statement is the evidence.
- `of-entity`: an exact revision holds data of a well or wellbore; the evidence names an exact source
  revision (the revision itself, or a header or report that states it) and may add a statement.
- `member-of`: result-group membership, a read-only projection of result groups; never asserted.
- `derived-from`, `supersedes`: recorded by Ophiolite with the run or command that made them.

Associations point from data to entities. No asset payload or metadata carries an entity, with one exception: a
corrected well position (E74b). A derived `well-location/1` item whose first version names a well and derives from a
kept table of wells that located that well (or from another such item) records that well as `correction_of`
(`publications/info`). Its versions must name the same well and keep its coordinate system and elevation reference;
no revision of it is associated with another well; and a table whose association with the well was revoked cannot
start one. Revoking the item's own association is allowed and only stops it locating the well. Every other
`well-location/1` publication is unchanged.
`lineage-schema.json` describes one hop each way from an exact revision.
