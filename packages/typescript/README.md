# Ophiolite browser client — preview

`@ophiolite/client` reads exact scientific revisions and exposes generated API
operations. Credentials are supplied by the host application and never stored by
this package. It has no filesystem access, credential cache or automatic retries.
This is a preview contract, not a stable SDK or production-support promise.

```ts
import { Client } from '@ophiolite/client';
import { postProjectsProjectApplicationsList } from '@ophiolite/client/operations';

// Run on the authenticated Workspace origin; obtain CSRF from /session.
const client = new Client(location.origin, { mode: 'session', csrf: () => csrf });
const curve = await client.readCurve(project, assetId, exactRevision, 'GR');
console.log(curve.curve.axis, curve.curve.values);
const applications = await postProjectsProjectApplicationsList(client, {
  path: { project }, body: { project_id: project }
}); // unknown: this route has no complete response schema in the pinned API.
```

A non-session host can supply a bearer token and application grant through
`{ mode: 'bearer', token: async () => ({ token, grant }) }`. Each request calls the
supplier once and uses `credentials: 'omit'`. The host owns token refresh and
secure storage. Session mode sends its CSRF header and includes session cookies.
Explicit `{ mode: 'none' }` supplies neither. HTTPS is required except on loopback.
Redirects are refused and credentials never follow a redirect to another origin.

## Exact scientific reads

`readCurve` checks the requested project, asset, revision and curve; verifies the
normalized byte count and SHA-256; validates structural and scientific rules; and
returns every coordinate and sample without resampling. Missing samples are
`null`, never zero. Units, depth reference and reader interpretation are preserved;
no CRS, unit conversion or depth alignment is inferred. Source revisions are opaque
identifiers. The bounded managed-derived profile additionally defines the revision
as the exact artifact checksum. Changed reader mappings are incompatible: read the
exact artifact instead. A changed reader version retains `recorded-differs` evidence.

Integrity failures raise `VerificationFailed`. Authentication, permissions,
conflicts, capacity and temporary availability use the SDK error categories.
Server diagnostics and arbitrary identifiers are not embedded in error messages.
A response is limited to 32 MiB; an upload is limited to 8 MiB.

## Application workflow and recovery

Generated operations support configure, start, original, read, publish, download,
share and result-list, plus LAS upload/info, with runtime response adapters based
on the pinned gateway recordings. Supply the declared request fields and stable
command IDs explicitly. Upload uses raw `Uint8Array` bytes plus
`options.upload` (`project_id`, `command_id`, `filename`, `name`, `attribution`,
`audience`, `rights_confirmed: true`, optional `well_notes`). The package encodes
that metadata in `X-Ophiolite-Upload`; it is not an HTTP bearer credential.

Owned and restricted runs/results have a `visibility` discriminator. Restricted
values expose no source reference, input checksum, arbitrary parameters, binding
ID, manifest parent or report. Narrow on `visibility` before accessing owner fields.
This normalization does not grant access: the gateway remains the authority.

There is one HTTP attempt per call. In particular, sharing never retries.
`ShareOutcomeUnknown` means that the reply was lost, truncated or invalid after a
sharing request. Read the current grants before deciding whether to share again.
There is no browser work-folder journal or unattended durable recovery; use the
Python SDK for that workflow. A generic generated download returns its declared
payload; `readCurve` is the high-level operation that verifies the descriptor/body
pair. Do not infer verified scientific integrity from an arbitrary API response.

## API coverage and development

`operation-coverage.json` records request and response coverage separately for all
152 pinned `/api/v1` operations. `schema` means the snapshot supplies a type;
`tested-override` means a named adapter has recorded gateway evidence. Generic or
missing response schemas are explicitly `unknown`. Generated type signatures do
not manufacture runtime validation for unsupported operations. The JSON schemas,
profile rules and generated contract types are embedded locally; no schema fetches
or server are needed for local scientific validation.

Run from the SDK repository:

```sh
python3 tools/generate_ts_client.py --check
npm ci --ignore-scripts --prefix packages/typescript
npm test --prefix packages/typescript
```

Node 22 is the qualified test runtime. The distributed sources use browser Fetch,
Web Crypto and typed arrays; Node imports exist only in excluded test sources.
Tests serve synthetic recordings through a local HTTP server. They cover full
arrays, restricted results, credential separation, lost replies and the same
independently inventoried invalid scientific cases as Python. Live Workspace proxy
qualification is recorded separately in the implementation strategy; synthetic
recordings alone are not a live deployment claim.
