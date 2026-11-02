# ZGY test cubes (E123 SZ)

`small-*.zgy` and their SEG-Y twins `small-*.sgy` are OpenZGY test data from equinor/pyzgy (Equinor ASA) at
`03b9f7bd7b` (`test_data/`), Apache-2.0 (`LICENSE-pyzgy.txt`), copied unmodified. They are synthetic cubes written by
the OpenZGY reference implementation: 5 inlines (1-5) by 5 crosslines (20-24) by 50 samples, step 4.

| File | What it proves |
|---|---|
| `small-32bit.zgy` + `.sgy` | float storage; every sample equals the hand-decoded IBM twin |
| `small-16bit.zgy` + `.sgy`, `small-8bit.zgy` + `.sgy` | int16 and int8 storage scaled by the stated datarange |
| `small-32bit_translated.zgy` + `.sgy` | corners in whole metres (2500, 5000) to (12500, 15000): scalar -1 |
| `small-32bit_rotated.zgy` | rotated corners not exact at any SEG-Y scalar: the refusal case |

`e16-volume.sgy` is a copy of `ophiolite-connectors/tests/fixtures/readers/volume.sgy` (E16, first-party synthetic):
`tests/test_zgy.py` decodes it by hand, writes it as a ZGY with OpenZGY and checks that the conversion gives it back.

Hashes and terms: Integration `docs/release/rights/e123sz-pyzgy-test-cubes-2026-10.json`. A cube written by Petrel is
not among them; it is unproven.
