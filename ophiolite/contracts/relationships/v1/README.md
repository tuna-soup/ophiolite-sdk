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

Associations point from data to entities. No asset payload or metadata carries an entity.
`lineage-schema.json` describes one hop each way from an exact revision.
