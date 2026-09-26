---
name: share-result
description: Inspect grants and apply an explicitly authorized recipient change without retrying an uncertain write.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/applications/result-list","/api/v1/projects/{project}/applications/share","/api/v1/projects/{project}/las-uploads/info","/api/v1/projects/{project}/las-uploads/share"],"symbols":["ophiolite.Client.grants","ophiolite.Client.share"],"errors":["share-outcome-unknown","integrity-conflict","PERMISSION_DENIED","verification-failed"]} -->

Read grants first. Confirm the user's requested read and reuse recipients from
the active task; existing authorization persists. Do not infer that a publication
request also authorizes broader sharing. Read permission and permission to reuse
input for a derived result are distinct claims.

```python
from ophiolite.errors import IntegrityConflict, ShareOutcomeUnknown

before = client.grants(receipt)
try:
    updated = client.share(receipt, read=read_recipients, reuse=reuse_recipients,
                           expected_generation=before.generation)
except (IntegrityConflict, ShareOutcomeUnknown):
    observed = client.grants(receipt)
    # Report the observed state; do not decide a new audience automatically.
```

Sharing replaces the specified recipient sets under the server's current policy,
conditional on the generation you read. The SDK itself repeats a lost request
once with the same command; that replay is refused (`integrity-conflict`) if the
recipients changed meanwhile, so it cannot undo a revocation. On
`integrity-conflict` or `share-outcome-unknown`, read grants and show the observed
state before choosing another action. Do not retry automatically beyond that one
SDK replay, including from an agent recovery loop. If `before.generation` is None the server does not support
conditional sharing; report that instead of sharing unconditionally.

Restricted results deliberately omit inaccessible parent identifiers, hashes,
arbitrary parameters and reports. Do not reconstruct or cache those fields from
another identity's response. Revocation cannot recall an already exported copy;
retention and upstream rights remain separate. Report a permission refusal with
its recovery guidance instead of substituting another principal.
