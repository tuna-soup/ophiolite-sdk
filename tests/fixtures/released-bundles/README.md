# Released portable bundles (E148 s2 C3)

Frozen inputs for `tests/test_released_bundles.py`. One directory per bundle version the SDK writer can emit
(1.0, 1.1, 1.10 and 2.0–2.11); every file is pinned there by its sha256 and is never regenerated. A released bundle
version must stay readable by `ophiolite.bundle.open_bundle` from these exact bytes. A file that has to change is a new
directory with its own row in that test. Everything here is synthetic: the content is the SDK's own contract fixtures
(`ophiolite/contracts/assets/v1/fixtures`, authored synthetic data) and literals written for this test.

Written once on 2 November 2026 (lane e148s2, base `edf29d0aecd5`; the SDK code was unchanged at the lane head
`d4b3ca769`), each by the **oldest frozen released writer** that emits its version (strategy R3): the module in
`tests/frozen/` loaded beside the SDK as `test_bundle_package.frozen()` loads it, called as
`write_bundle(<version dir>, items, ...)`. The items come from the SDK test helpers named below.

| Version | Writer | Content (the smallest that triggers the minor) | Helpers |
|---|---|---|---|
| 1.0 | `bundle_1_0` | one LAS curve (`GR`) | `test_bundle.Read` |
| 1.1 | `bundle_2_1` | the LAS curve and one observation group, `groups=[{'name': 'Synthetic group', 'members': [0], ...}]` | `test_bundle.Read`, `test_bundle.grouped` shape |
| 1.10 | `bundle_2_10` | the LAS curve with its source record | `test_bundle_provenance.las_item`, `test_bundle_source_records.recorded` (`RECORD`) |
| 2.0 | `bundle_2_1` | one well-tops asset | `test_bundle.typed_read('tops')` |
| 2.1 | `bundle_2_1` | the tops and one observation group | as 1.1 |
| 2.2 | `bundle_2_2` | one point set | `typed_read('points')` |
| 2.3 | `bundle_2_4` | one polyline set (fault sticks) | `typed_read('faults')` |
| 2.4 | `bundle_2_4` | the tops and a graph: well `well-1` (`Synthetic W`, provisional), wellbore `wellbore-1`, two relationships | `test_bundle_entities.graph` shape, `BORE` |
| 2.5 | `bundle_2_5` | one wavelet | `typed_read('wavelet')` |
| 2.6 | `bundle_2_6` | one time-depth table | `typed_read('time-depth')` |
| 2.7 | `bundle_2_7` | one GeoJSON feature set | `typed_read('feature-set')` |
| 2.8 | `bundle_2_8` | one Shapefile-read feature set with its package | `test_bundle_package.shapefile_read` |
| 2.9 | `bundle_2_9` | the LAS curve with a kept original: 216 bytes of synthetic text, labels made synthetic after the helper | `test_bundle_provenance.read_on_a_computer(Read(), raw=...)` |
| 2.10 | `bundle_2_10` | the tops with a source record | `test_bundle_source_records.recorded(typed_read('tops'))` |
| 2.11 | `ophiolite/bundle.py` (no frozen 2.11 module) | a packaged polyline set: the faults fixture reprofiled to `petrel-faultsticks/1`, read by `asset_connectors.petrel_faults/1`, members `faults.txt` (primary) and `faults.crs` (crs-metadata, one synthetic line) | built as `test_bundle_package.shapefile_read` builds its package (`stored_rows`, `rehash`) |

| 2.17 | `ophiolite/bundle.py` (no frozen 2.17 module) | one wells table (`well-table`, `sql-wells/1`): two synthetic rows `S-1`, `S-2` beside a synthetic source manifest; written on 9 November 2026 (lane e162s2a) | `test_bundle_well_table.table()` |
| 1.18 | `ophiolite/bundle.py` (no frozen 1.18 module) | the LAS curve with a sender in its entry (`reported`: client `qgis-plugin` 1.4.0, host `qgis` 3.34.2, transport `http`, accepted as `las2/1`), the same view also served on its descriptor and left out of the descriptor file; written on 22 November 2026 (lane e182s2b, commit E182 s2b C2) | `test_bundle.Read` with `.sender` set |
| 2.18 | `ophiolite/bundle.py` (no frozen 2.18 module) | the tops with a sender in their entry (`not reported`, transport `mcp`, accepted as `well-tops-csv/1`), served on the descriptor too and left out of its file; written as 1.18 | `typed_read('tops')` with `.sender` set |

The 1.18 and 2.18 descriptor and manifest digests are pinned in `sender-digests.json` beside these directories (their
other files are the 1.10 / 2.10 LAS and tops files, byte for byte).

No frozen writer fell back to a later one: each wrote its version offline.

Limits of "frozen writer". The frozen modules import their siblings from the current SDK (`_core`, `navigation`,
`typed`, `writers`, and `bundle_package` for 2.8–2.10), so those parts of the bytes are what this SDK wrote; and
`exporter.version` in every manifest is the SDK's version at writing (`2026.11.4`), not the release that first shipped
the writer. `created_at` is the time of writing and is frozen with the rest.
