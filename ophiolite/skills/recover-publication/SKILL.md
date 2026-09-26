---
name: recover-publication
description: Resume an exact saved SDK request from its original private work folder after interruption.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/applications/configure","/api/v1/projects/{project}/applications/start","/api/v1/projects/{project}/applications/publish","/api/v1/projects/{project}/las-uploads/upload"],"symbols":["ophiolite.Client.recover"],"errors":["recovery-unavailable","integrity-conflict","authentication-required","verification-failed"]} -->

Recovery requires the original private work folder. Preserve its owner record,
requests, responses, script/input checkpoints and owned upload copy. Never edit
those records, move another user's state into the folder or regenerate command
identities to make a refusal disappear.

```python
recovered = client.recover(private_folder)
```

```sh
ophiolite recover --configuration configuration.json --work private-folder
```

The SDK validates saved request/body identities, credential ownership and durable
responses. It replays an unresolved operation with the same identity; completed
responses are reused locally. A fully completed folder can return `None` because
nothing remains to send. That is a successful no-op, not a new publication.

Deleted/corrupt folders or unavailable credential ownership cannot be reconstructed
from a receipt alone. Report `recovery-unavailable`, sign in as the appropriate
principal where required, and keep evidence of the refusal. Do not claim recovery
from arbitrary disk loss or a different deployment. Retrying reads is distinct
from replaying a saved publication. Sharing has no durable retry journal here:
after an uncertain share, read grants first; never replay sharing automatically.
