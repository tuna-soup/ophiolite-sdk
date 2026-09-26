# Scientific contracts and local validation

`ophiolite/contracts/SOURCE.json` pins the immutable source commit, contract tree,
registry version and every copied file's digest. The maintainer sync tool checks
tracked path coverage and bytes against Platform. A later Platform CLI-only commit
may share that contract tree; it need not change the captured contract-source SHA.

Generated Pydantic models enforce declared types, patterns, bounds and finite
numbers. Unknown additive fields are retained. Semantic validation checks custody,
retention, exact source/parent identities, registry membership, real calendar times,
representation roles/counts, sample meaning and descriptor/view agreement.

```python
from ophiolite import validate
asset_model, curve_model = validate.pair(descriptor, downloaded_normalized_bytes)
```

This local operation performs no network or credential lookup. It checks normalized
bytes against the descriptor. The network client's additional verification checks
the downloaded source artifact and the originally requested asset/revision/curve.
For strict schema validation install `ophiolite[validation]` and call
`validate.schema(value, schema_id, strict=True)`. Strict mode rejects unknown fields;
normal client reads retain additive fields.

Scientific identity compares declared fields, not unrelated additive labels. Live
interpretation equality includes the declared null policy. Recorded evidence follows
the service policy: mapping differences refuse normalization; reader, parsing-policy
or library-version differences produce `recorded-differs`; a null-policy-only change
does not change that evidence label. Both records remain available.

Units are labels supplied by the source. Empty units stay unknown. Depth axis values,
order, duplicates, index name, reference, zero values and null positions are retained.
No CRS/datum transformation, alignment, interpolation or native-edit capability is
implied. Server authorization remains authoritative; descriptor operations are not
an access grant.

The scientific-negative corpus uses correctly hashed malformed payloads so semantic
failures cannot be hidden by checksum failure. The synthetic public-route recording
retains exact bodies and excludes request credentials. Rights/provenance records are
in `tests/fixtures/PROVENANCE.json`; unreviewed inputs block public publication.


`CurveSet.to_numpy()` and `to_frame()` return `(values, Descriptor)`. NumPy values
are a two-dimensional float64 array; DataFrame columns preserve requested curve
order and its index preserves every depth. None maps to NaN with no filling.
Both share the same compatibility checks: complete coordinate equality, depth
unit and status, depth index/reference, declared interpretation fields and exact
project/asset/revision/source reference. Additive metadata does not create false
identity differences. Mismatches raise `AxisMismatch` with curve names, reason and,
for coordinate mismatch, the first differing index. No implicit unit conversion
or CRS interpretation is provided. `Descriptor.attach(frame)` explicitly writes a
serialized metadata copy to `frame.attrs['ophiolite']`; it does not bind later edits
or make a transformed frame scientifically equivalent to the original.


`CurveSet.evidence` maps selected curve mnemonics to the SDK's reader-history
status. Older responses lacking both evidence and recorded-reader fields report
`not-available`; generated wire-model defaults do not establish that evidence.
The separate view Descriptor and notebook use this derived status. Saved wire
fields retain their original presence. This compatibility status adds no server
enum and claims no comparison when the earlier reader record is unavailable.


Credential files use `ophiolite.sdk-credential/1`, an envelope containing
`credential`, an integer `generation`, and a per-login `family`. No flat legacy
fields are accepted. `Credential.open` aliases `from_file`; `headers(url, project)`
checks scope and performs serialized renewal. `update(tokens)` atomically persists
only against the generation this instance observed; stale explicit updates refuse.
`save()` rereads under the lock and cannot overwrite a newer token snapshot.
`delete()` and `revoke()` share that lock. Instances from a replaced login family
cannot read, overwrite or delete the new session. The adjacent lock file persists
after deletion to preserve one lock identity across waiting processes.

Authentication requests refuse redirects, foreign provider endpoints and oversized
responses. Only approved error categories are returned; arbitrary provider bodies
are excluded from exceptions. Provider token rotation must return both an access
and refresh token with a finite positive lifetime. No automatic request replay is
performed. Local scientific validation still performs no login or cache discovery.
