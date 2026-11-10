# Surveys (E142, D103–D105)

A survey is one unit: an OpendTect survey, or any application's project, with its cube, 2D lines, horizons, faults,
wells, time-depth models and picksets, and the relations between them. Slice 0 fixes the contract; nothing is stored
or served by it yet.

- `survey-revision-schema.json` (`ophiolite.survey-revision/1`): one complete, immutable revision. Its name, its
  identity (`authority` `<system>:<instance>` and `key`, the producer's container; or provisional), the producer
  reference, the default context (CRS, domain, units: defaults only, a member's own always win), every member and
  every relation. A member is an exact revision in a role; a `well` member also names the well or wellbore its
  revision is associated with (`of-entity`). A relation joins two members. A rename is a new revision; an unchanged
  survey always resolves to the same data.
- `survey-schema.json` (`ophiolite.survey/1`): one page as one reader may see it. Only members the reader may read,
  in role order then by item and revision (never by name), the relations whose both ends the reader may read, the
  authorised count and the cursor. An entity the reader may not read is `{"withheld": true}`. The live view
  (`view: latest`) resolves each member to the newest revision the reader may read when it is read; it is never a
  survey revision.
- `roles.json` (`ophiolite.survey-roles/1`): the served profiles each role admits and the roles each relation joins.

The relations are registered in `../../relationships/v1/registry.json` (1.2.0) as read-only projections.
