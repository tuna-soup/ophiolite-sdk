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
External data is limited to the attributed excerpt below. A changed or uncovered input must be
reviewed before public push; the checker never supplies its own rights grant.
The Platform repository as a whole has not been relicensed by this SDK notice.

## Preview template dependencies

The templates lock additional plotting/notebook tools (Matplotlib, Jupyter,
nbclient, ipykernel), test tools and the React/Vite browser toolchain. Their source
and browser binaries are not vendored in the SDK. Installations use the original
distributions and their included notices. See each requirements.lock and the React
package-lock.json for exact resolved packages. This bounded SDK/template input
audit does not qualify the complete E17 open-source distribution.

## Third-party data: the HON-GT-01 gamma-ray excerpt (E52)

`ophiolite/contracts/scientific/v1/fixtures/hon-gt-01-gamma-ray-excerpt.las` (SHA-256 `8f7dce3351e8dba04479cb0b0714c49cb3a210f2b2b6e7279f07f37d7c222515`)
is copied from Ophiolite Platform's contracts and is not original Ophiolite work and not Apache-2.0.

Source: NLOG.NL (www.nlog.nl), well HONSELERSDIJK-GT-01. Modified: only the depth rows 2466.0-2621.0 m and the curves DEPTH and GR are kept, and STRT/STOP changed to match.

The source file is NLOG's composite log `5682_hongt01_2012_comp.las`, used under the NLOG disclaimer
(<https://www.nlog.nl/disclaimer>, `LicenseRef-NLOG-Disclaimer-2016-08-09`; the Dutch text prevails), which permits
copying, distribution and editing with source attribution. The rights review is recorded in Ophiolite Integration
`docs/release/rights/`.
