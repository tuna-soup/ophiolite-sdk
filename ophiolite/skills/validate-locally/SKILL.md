---
name: validate-locally
description: Validate scientific contracts and proposed curve results without contacting a service.
---
<!-- sdk-contract: {"routes":[],"symbols":["ophiolite.validate.schema","ophiolite.validate.pair","ophiolite.publish.validate_derived_curves"],"errors":["verification-failed","validation-failed","incompatible-context"]} -->

Local validation neither authenticates nor publishes. Install the `validation`
extra for JSON-schema validation. Use the pinned known schema/profile; unknown
contracts need an explicit SDK upgrade or access to the exact artifact.

```python
from ophiolite import validate
from ophiolite.publish import validate_derived_curves

validate.schema(value, "ophiolite.application-curve/1")
validate.pair(descriptor_json, exact_normalized_bytes)
validate_derived_curves(curves, source=original_las, sample_count=sample_count)
```

Pass the exact bytes to pair validation; reserializing equivalent JSON changes its
byte identity. Schema shape alone is insufficient: finite samples, real calendar
times, registered profiles, source identity, interpretation agreement, axis facts
and missing-value rules are checked as appropriate. Byte integrity alone does not
establish scientific validity or permission.

Derived curves need supported distinct mnemonics, units/descriptions and one value
per original sample. Retain nulls; never emit the LAS NULL marker as a measurement.
Check collisions against every source curve, including unselected curves. Do not
silently invent units or resample. Report all supplied violations and ask for the
scientific decision that is actually missing. A local validation success does not
promise that the server will accept publication, grant rights or retain data.
