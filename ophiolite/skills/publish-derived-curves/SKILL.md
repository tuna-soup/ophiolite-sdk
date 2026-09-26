---
name: publish-derived-curves
description: Publish an authorized bounded local calculation with exact inputs and a private recovery folder.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/applications/configure","/api/v1/projects/{project}/applications/start","/api/v1/projects/{project}/applications/publish","/api/v1/projects/{project}/applications/download"],"symbols":["ophiolite.Client.work_folder","ophiolite.publish.WorkFolder.configure","ophiolite.publish.WorkFolder.start","ophiolite.publish.WorkFolder.publish","ophiolite.publish.WorkFolder.download"],"errors":["validation-failed","integrity-conflict","capacity-exceeded","PERMISSION_DENIED"]} -->

Proceed when publication is authorized by the user's task. State the selected
input revision, calculation, destination and audience. Publication and sharing
are separate actions. A run-start records/resolves input; it does not execute code.

```python
work = client.work_folder(private_folder)
binding = work.configure(asset_id, revision, curve="GR", name="Local calculation")
run = work.start(binding, application_version="my-calculation/1",
                 parameters={"factor": 2}, script=script_bytes)
original, view = run.input()
curves = [{"mnemonic": "CALC", "unit": view.unit,
           "description": "Selected values multiplied by two",
           "values": [None if x is None else x * 2 for x in view.values]}]
receipt = work.publish(run, derived_curves=curves)
work.download(receipt)
```

Execution is local and script-declared. Preserve exact input references and state
what code/environment information was supplied or omitted. The SDK validates the
bounded result and the server checks current rights. A receipt names the durable
result; identical retries keep its identity, conflicting inputs refuse. This
workflow creates a separate derived asset, not an implicit update of its parent.

Keep the private folder and its owned input copy. After a lost reply use recovery
from that folder; never invent a replacement command ID to bypass uncertainty.
Do not claim atomicity across unrelated sources, managed execution, universal LAS
conversion or publication beyond the documented sample/upload limits. Unrelated
project members do not gain access merely because a result was published.
