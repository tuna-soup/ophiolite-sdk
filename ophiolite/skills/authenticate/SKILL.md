---
name: authenticate
description: Sign in to an Ophiolite project and use the SDK-owned private credential.
---
<!-- sdk-contract: {"routes":["/api/v1/application-access/request","/api/v1/application-access/status"],"symbols":["ophiolite.Client","ophiolite.Credential.from_file","ophiolite.auth.default_path"],"errors":["authentication-required","PERMISSION_DENIED"]} -->

Use this when the user needs authenticated SDK access. Obtain `configuration.json`
from Workspace → Connect → Use Python. It identifies the service/project and is
not a credential. Do not copy provider or gateway tokens into the configuration.

```sh
ophiolite doctor --configuration configuration.json
ophiolite login --configuration configuration.json
ophiolite status --configuration configuration.json
```

Use `login --write` only when publication is part of the authorized task. Login
opens the user's browser for consent; `--no-browser` prints the confirmation flow
for manual use. Provider login alone does not grant project membership or source
access. A refusal is useful evidence; do not substitute an administrator token.

```python
from ophiolite import Client, Credential
from ophiolite.auth import default_path

credential = Credential.from_file(default_path(url, project))
with Client(url, project, credential) as client:
    permitted = list(client.assets())
```

The SDK owns its private namespace, refresh lock and rotation. The old downloaded
kit cache is not imported: perform a fresh SDK login. Do not read the credential
file to inspect token values. Use status to inspect access. On an expired or
revoked credential, sign in again; on permission refusal, ask the owner to check
membership and the requested scope. Logout explicitly revokes application access.
Never claim that a synthetic fixture login qualifies the customer's provider.
