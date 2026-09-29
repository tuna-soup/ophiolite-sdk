# Start with a working scientific example

These preview templates start an application on the public SDK. Copy one with `ophiolite init <name>
[--output DIR]` (the templates ship inside the SDK wheel), or from this directory.

- **map-application:** wells on a web map (MapLibre GL); a Python backend holds the credential.
- **derive-and-publish:** read an exact curve, compute a derived curve locally, publish it with its method
  (`publications/derive`), recoverable from a work folder.
- **sync-worker:** keep a local copy of a project current from its event log and act on each change.
- **notebook:** a DataFrame, scientific descriptor and plot, with explicit failures.
- **agent-workflow:** a recoverable calculation recipe with refusal examples.

Keep `support.py` alongside these directories when copying a template. It contains
one shared recipe and the synthetic fixture adapter. Run the templates from their
source directory; they are starting projects, not independently published packages.
Each template includes both the original small LAS fixture and an additional
original synthetic sonic/density LAS file. The default fixture serves the small
five-sample gamma-ray curve. The sonic/density file is supplementary example data;
no hidden import, conversion, alignment or resampling is performed.

Create a virtual environment and install that template's `requirements.lock`.
The SDK reference is the immutable accepted C7 source commit. Locks were resolved
against its built wheel; no developer filesystem path is in the locks. The React
project also requires Node 22 and `npm ci`. See each README for commands.

For real data, set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT`, run `ophiolite login`,
and choose the actions explicitly. The SDK owns private credential discovery and
refresh; `OPHIOLITE_CREDENTIAL` can select an explicit SDK credential file. No
credential belongs in configuration examples, notebooks, browser storage or Git.
The browser backend never returns a gateway/provider token. A real source must
expose a permitted curve; adapt the selected curve in your copied recipe where
necessary. Sharing replaces the requested recipients after reading current grants.

Compare each `template_version` with the SDK CHANGELOG when upgrading. Keep the
original private work folder if a reply is lost. Recovery reads its saved requests
and replies; it does not promise to reconstruct a deleted folder. Inspect grants
after an uncertain sharing response; do not automatically repeat a sharing write.
Synthetic tests are contract examples, not proof of a live identity provider,
customer connector, operating-system isolation or production deployment.

In synthetic mode, exact-version links demonstrate the intended Workspace route.
The tiny fixture server does not serve the Workspace UI; open those links in live
mode against a connected Workspace. The template smoke checks the links and API
flow, not an authenticated navigation into a separate Workspace deployment.
