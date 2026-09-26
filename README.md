# Ophiolite SDK — read-only preview

This E4 implementation reads exact scientific revisions through Ophiolite's
public service API. Contracts are preview contracts. No production-support or
complete open-source release qualification is claimed.

## Install and read

Python 3.10 or later is required. Install from a reviewed commit of this repository:

```sh
python -m pip install 'git+https://github.com/tuna-soup/ophiolite-sdk@<reviewed-commit>'
```

The read-only foundation accepts an explicit existing scoped bearer credential.
Browser login and credential storage arrive in E4 C3. Configure credentials through
your approved environment mechanism; do not put them in source files or logs.
Provider application credentials also need their approved application grant ID.

```python
import os
from ophiolite import Client, Credential

credential = Credential.bearer(
    os.environ['OPHIOLITE_TOKEN'],
    grant=os.environ.get('OPHIOLITE_GRANT'),
)
with Client(os.environ['OPHIOLITE_URL'], os.environ['OPHIOLITE_PROJECT'], credential) as client:
    data = client.read(asset_id, exact_revision, curves=['GR'])
    print(data.curves[0].axis, data.curves[0].values)
    data.save('new-read-folder')
```

Choose the asset and exact revision from your permitted catalogue or a downloaded
configuration. `Client.from_configuration(path, credential=credential)` accepts
read/local configuration files. No curve or replacement revision is inferred.

A read checks identity, lengths, hashes, units, missing values, source references
and reader interpretation. Wrapped and unwrapped LAS are supported through the
server's normalized view. The original LAS artifact stays byte-for-byte intact.
Zero is a value; `None` is a missing sample. Unit labels and depth reference remain
as reported, including unknown meaning. There is no interpolation or conversion.

`save` creates a private new directory and refuses an existing one. A single-curve
read writes `artifact.las`, `curve.json` and `descriptor.json`. Multiple curves get
separate curve and descriptor JSON files. JSON is re-serialized for readability;
its saved bytes are not claimed to match the downloaded representation hash.
The source artifact is exact. This directory is not an E18 portable export bundle.

## Scientific arrays and notebook display

Install `ophiolite[numpy]` or `ophiolite[pandas]` from the same reviewed source
revision to enable the optional views. They load only when called.

```python
array, description = data.to_numpy()
frame, description = data.to_frame()
description.attach(frame)  # optional, explicit frame.attrs['ophiolite'] copy
```

The NumPy array has shape `(samples, selected curves)`, with float64 columns in
requested order. Missing samples become NaN; real zero stays zero. The DataFrame
uses the exact depth axis as its index, including decreasing or duplicate values.
Neither method sorts, aligns, interpolates, fills gaps or converts units.

Each method returns a separate `Descriptor` carrying the full axis and its unit,
reference and order, per-curve units/counts, source identity, hashes and reader
interpretation. The frame starts with empty `attrs`. Use the companion descriptor
when passing an array to other code; array values alone do not preserve meaning.
Both methods refuse differing axes, units, depth references, interpretation or
source identity. Read incompatible curves separately or explicitly transform them
in your own scientific workflow with a recorded method.

Notebook HTML presents scientific labels, units and counts; identifiers and hashes
are in **Technical details**. The exact-version link opens the first selected curve and requires a Workspace
build with E4 scientific-link support. Older Workspace builds need an upgrade.
The link contains no credential and grants no permission; sign in to Workspace
with permitted read access. An unavailable version is refused instead of replaced
with a newer one. The qualification evidence covers an isolated candidate gateway;
it does not establish support for every deployment.

## Recovery and limits

- Authentication failure: obtain a current approved credential and retry.
- Access refusal or unavailable revision: check permission and the exact revision;
  select a different revision explicitly if appropriate.
- Integrity/scientific mismatch: do not use the response; investigate the source or
  reader with the deployment administrator. Nothing is saved by a failed read.
- Different recorded/current interpretation: both records stay in the descriptor;
  `strict_interpretation=True` refuses differences. A changed mapping is refused.
- Existing output folder: choose a new folder; existing files are not overwritten.

The client bounds artifacts to 32 MiB and scientific arrays to 100,000 samples.
Local models/validation import without credentials or a running service. Models
retain additive fields while enforcing declared constraints. The `validation`
extra enables strict JSON Schema checks; see [contracts](docs/contracts.md).

Asynchronous I/O, browser login, publication, the CLI and application templates
remain later E4 commits. Portable export and the independent
bundle reader belong to E18; see [the reader boundary](docs/offline-reader-boundary.md).

## Developer checks

```sh
python -m pip install '.[dev,numpy,pandas,validation]'
python -m build
python -m venv .wheel
.wheel/bin/python -m pip install dist/ophiolite-0.1.0-py3-none-any.whl
OPHIOLITE_TEST_WHEEL_PYTHON="$PWD/.wheel/bin/python" python -m pytest -q tests --ignore=tests/gateway
python tools/generate_models.py --check
python tools/check_public_inputs.py --artifact dist/ophiolite-0.1.0-py3-none-any.whl --artifact dist/ophiolite-0.1.0.tar.gz
```

The gateway lane additionally needs the pinned Platform test runtime and an isolated
PostgreSQL test schema. `OPHIOLITE_REQUIRE_GATEWAY=1` turns missing required cases
into failures. Its current delegate is stubbed; it does not qualify browser consent
or a live deployment. Mutation and independent verification results are recorded in
the Integration E04 strategy, with the exact commands and source revisions.
