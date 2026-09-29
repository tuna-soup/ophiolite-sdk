# Wells on a map

Preview template version **0.1.0**. Compare `template_version` with the SDK CHANGELOG before upgrading.
`ophiolite init map-application` copies this directory and `../support.py`.

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.lock
npm ci
npx playwright install chromium
make dev          # synthetic wells; no service, credential or data source needed
make test         # backend, TypeScript build, helper tests and a real-browser smoke
```

Open **http://127.0.0.1:56110**. The Python backend (port 56111) holds the Ophiolite credential through the
SDK and answers the page with the wells you may read — GeoJSON in longitude/latitude (the server converts;
nothing is converted in the browser) — and their extent. The page draws them with MapLibre GL on a plain
background: no tile service is contacted; add a basemap you are licensed to use. Each well shows its name;
identifiers, the source revision and row stay under **Technical details**. Wells without a location you may
read are listed, not drawn.

The browser never receives a token. Bootstrap is an explicit POST with a custom header, the exact configured
Origin/Host and same-origin metadata; later calls need the per-start proof held only in browser memory. Vite
preserves Origin/Host and disables CORS; the backend refuses preflight and GET API calls. This protects
against browser cross-origin requests, not against a malicious local process.

## Live mode

Set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT`, sign in with `ophiolite login` (or set `OPHIOLITE_ACCESS_KEY`)
and run `make live`. Expired sign-in: run `ophiolite login`. No well shown: check that a table of wells or a
well-location file you may read is associated with the wells (see the "Wells on a map" guide).
