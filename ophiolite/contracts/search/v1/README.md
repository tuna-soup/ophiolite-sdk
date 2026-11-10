# Organisation search (E145)

- `search-request-schema.json` — `ophiolite.search-request/2`: a question to every project of one organisation the
  caller may read: `organization_id`, words (`text`, `method`) and the filters `kinds`, `well`, `bbox`, `since`,
  `until`, `published_by`, `projects`, `include_archived`, with `cursor` and `limit`. Unknown keys are refused, naming
  them; an explicit null is never an absent field.
- `search-schema.json` — `ophiolite.search/2`: the answer: a page of current versions ordered by score (rounded to 6
  places), project, name and asset; `matched` and the `kind`, `project` and `well` facets over every readable match;
  `next_cursor`; `not_searched_by_meaning`.
- `search-meaning-schema.json` — `ophiolite.search/3` (E145 s2b): the answer to a question by meaning, served beside
  `/2`, which every answer by words keeps. The same shape with `method` `embedding`; each `score` is the cosine of the
  question and the version's description rounded to 6 places, above 0 and at most 1 (`score-above-one`); `why` lists
  the question's words the row contains and may be empty; `not_searched_by_meaning` counts the readable versions
  matching the question's filters that the caller may not use with models, which were not sent to the model.
- `filters.json` — `ophiolite.search/filters/1`: the closed list of question fields with their types and limits, which
  fields bind the question, the default coordinate system of a box, the order, the page cap and the sentence of the
  unknown-filter refusal. Hand-authored; tested equal to the request model.
- `fixtures/requests.json`, `fixtures/answers.json`, `fixtures/answers-meaning.json` (`/3`) — synthetic questions and answers, valid and refused; each refused
  case names the stage that refuses it first (`schema` or `consistent`), its field and reason, and whether the published
  JSON Schema alone refuses it (`schema_expressible`).

A box (`bbox`) bounds x (easting or longitude, `minx`..`maxx`) and y (northing or latitude, `miny`..`maxy`) of the named
system whatever its axis order, inclusive; it is stated in one of the systems a read can convert to (`target: true` in
`vocabulary/v1/coordinate-systems.json`). The schemas are generated from `project_gateway/org_search.py` by
`generate.py --schemas`; the consistency rules (`check_request`, `check_answer`) are what the schema cannot say.

Search by meaning runs only on a deployment with `OPHIOLITE_EMBEDDING_COMMAND`, without network access (E14). The
command is the model's identity: stored vectors and cursors are keyed by it. The operator names an immutable model
version in the command (a path or tag carrying the weights' digest) and changes the command whenever the model
changes; a model replaced behind an unchanged command keeps the old vectors and cursors.
