# Dependencies and copied inputs

Python dependencies are installed separately, not copied into this source tree:
HTTPX, Pydantic and their dependencies; optional NumPy, pandas and jsonschema.
An installed dependency inventory and licence review is required before release.
No assertion about that complete transitive inventory is made here.

The contract snapshot comes from Ophiolite Platform at the immutable revision
in `ophiolite/contracts/SOURCE.json`. E4's reviewed SDK/contract licence decision
covers the intended original-code boundary. The reviewed snapshot is inventoried by exact path/hash/source revision in
`tests/fixtures/PROVENANCE.json`. The synthetic LAS comes from the tracked
maintainer generator literal; frozen fixtures retain their historical bytes.
No external data acquisition is included. A changed or uncovered input must be
reviewed before public push; the checker never supplies its own rights grant.
The Platform repository as a whole has not been relicensed by this SDK notice.
