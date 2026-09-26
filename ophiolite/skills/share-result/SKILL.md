---
name: share-result
description: Inspect grants and apply an explicitly authorized recipient change without retrying an uncertain write.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/applications/result-list","/api/v1/projects/{project}/applications/share","/api/v1/projects/{project}/las-uploads/info","/api/v1/projects/{project}/las-uploads/share"],"symbols":["ophiolite.Client.grants","ophiolite.Client.share"],"errors":["share-outcome-unknown","PERMISSION_DENIED","verification-failed"]} -->

Read grants first. Confirm the user's requested read and reuse recipients from
the active task; existing authorization persists. Do not infer that a publication
request also authorizes broader sharing. Read permission and permission to reuse
input for a derived result are distinct claims.

```python
from ophiolite.errors import ShareOutcomeUnknown

before = client.grants(receipt)
try:
    updated = client.share(receipt, read=read_recipients, reuse=reuse_recipients)
except ShareOutcomeUnknown:
    observed = client.grants(receipt)
    # Report the observed state; do not repeat the write automatically.
```

Sharing replaces the specified recipient sets under the server's current policy.
It is attempted once. On `share-outcome-unknown`, read grants first and show the
observed state before choosing another action. A timeout is not proof that nothing
changed. Do not retry automatically, including from an agent recovery loop.

Restricted results deliberately omit inaccessible parent identifiers, hashes,
arbitrary parameters and reports. Do not reconstruct or cache those fields from
another identity's response. Revocation cannot recall an already exported copy;
retention and upstream rights remain separate. Report a permission refusal with
its recovery guidance instead of substituting another principal.
