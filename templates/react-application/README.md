# A local React scientific application

Preview template version **0.1.0**. Compare `template_version` with the SDK
CHANGELOG before upgrading. Keep `../support.py` alongside this directory.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
npm ci
npx playwright install chromium
make dev
# In a separate terminal using the same virtual environment:
make test
```

The default development command uses only the original synthetic loopback fixture.
No customer service, credential or data source is needed. The five-sample curve
contains zero and a missing sample; units and depth reference remain explicit.
The included sonic/density file is additional synthetic example data, not an
automatically converted second source.

Open **http://127.0.0.1:56110**. The Python backend uses port 56111. Both ports are
fixed and loopback-only; stop your own conflicting process before starting.
Select data → Read curve → choose a new curve name → Stage calculation → Validate
→ Publish derived curve. Enter explicit recipients before choosing Share result.
Technical details stay in a disclosure. Exact source/result links open Workspace.

The backend uses `ophiolite.auth` through the SDK. Bootstrap is an explicit POST
with a custom header, exact configured Origin/Host and browser same-origin metadata.
Later API calls require the random per-start proof, kept only in browser memory.
Vite preserves Origin/Host and disables CORS; the backend rejects preflight and GET
API calls. Reload after backend restart. This protects against browser cross-origin
requests; it does not isolate a malicious local process that can spoof HTTP headers.

`make test` includes a real Chromium/Vite/backend workflow, refusal cases, request
inspection, one-attempt lost-sharing handling and axe checks. Set `CHROMIUM_PATH`
only when using an existing Chromium binary. Fixture fault controls exist only in
explicit synthetic mode. They are absent in live mode.

## Live mode and recovery

Set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT`, sign in with `ophiolite login` and
use `make live`. Optional `OPHIOLITE_CREDENTIAL` selects an explicit private SDK
credential file. Do not put credentials in the configuration example. The example
expects a permitted gamma-ray curve; adapt the selection explicitly for your data.
Set `OPHIOLITE_WORK` to a private persistent parent directory for the live work folder.

Expired credential: run `ophiolite login`. Revoked access: ask the owner to check
permissions. Different axes/units: read separately or align explicitly. Capacity
refusal: select a smaller input. Changed input: read and verify the exact version
again. Invalid names, source-curve collisions and the LAS missing marker refuse
locally. A lost publication reply needs the original work folder. An uncertain
share needs a grants read first; this template does not automatically repeat it.

No production support, live identity-provider qualification, automatic conversion
or synchronisation is claimed by these synthetic examples.

In synthetic mode, exact-version links demonstrate the intended Workspace route.
The tiny fixture server does not serve the Workspace UI; open those links in live
mode against a connected Workspace. The template smoke checks the links and API
flow, not an authenticated navigation into a separate Workspace deployment.
