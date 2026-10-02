# Scientific fixtures

| File | What it is | Origin |
|---|---|---|
| `well-curve.json`, `scalar-map.json` | Synthetic examples of the two native exchange profiles | Written for Ophiolite |
| `hon-gt-01-gamma-ray-excerpt.las` | An excerpt of a real well log: HON-GT-01, depth 2466.0-2621.0 m, curves DEPTH and GR (1,551 rows) | NLOG.NL (below) |

## HON-GT-01 excerpt (E52)

Source: NLOG.NL, the Dutch oil and gas portal, composite log `5682_hongt01_2012_comp.las` of well HONSELERSDIJK-GT-01
(SHA-256 `cfa223bc…f537`, 2,984,666 bytes), used under the NLOG disclaimer (<https://www.nlog.nl/disclaimer>), which permits
copying, distribution and editing with source attribution (`LicenseRef-NLOG-Disclaimer-2016-08-09`; the Dutch text prevails).

**Modified:** only the depth rows 2466.0-2621.0 m are kept, only the curves DEPTH and GR, and the `STRT`/`STOP` header lines are
changed to match. Two comment lines at the top say so. Every other header line and every kept value is unchanged.
SHA-256 of the excerpt: `8f7dce3351e8dba04479cb0b0714c49cb3a210f2b2b6e7279f07f37d7c222515`.

The shale-volume table (`../shale-volume-methods.json`, `hon_cases`) holds the values both runtimes must reproduce from it.
