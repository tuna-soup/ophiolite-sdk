# Samples of the procedure starts

Each file here holds the arguments of one Ophiolite writer (`ophiolite.writers`) for one kind. `ophiolite procedures
new --step STEP --kind KIND` copies the kind's sample into the start it makes (`data/`), so a new start runs, and
passes its own tests, before you change it. `check-*.json` hold a version to check and two references, one that
matches and one that differs.

All values are synthetic: wells, names, coordinates and measurements were made up for these samples and describe no
real place or survey. They were written for Ophiolite (E112, October 2026) and are distributed under the SDK's
licence, Apache-2.0. `residual.json` is a copy of the Ophiolite Connectors test fixture
`ophiolite-connectors/tests/fixtures/well_residual/three-rows.json`, which is also synthetic Ophiolite data under
Apache-2.0.
