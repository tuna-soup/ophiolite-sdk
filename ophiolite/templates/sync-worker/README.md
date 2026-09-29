# A worker that keeps a project's copy current

Preview template version **0.1.0**. Compare `template_version` with the SDK CHANGELOG before upgrading. Keep
`../support.py` alongside this directory (`ophiolite init sync-worker` copies both).

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.lock
python -m pytest -q tests          # against a synthetic event log; no service needed
export OPHIOLITE_URL=https://ophiolite.example OPHIOLITE_PROJECT=my-project
ophiolite login                    # or set OPHIOLITE_ACCESS_KEY
python worker.py --checkpoint state/checkpoint.json
```

The worker catches up from its checkpoint (a first run, a new epoch or another credential resyncs everything
it may read), then follows the project's changes live and prints one line per change. Put what your
application does in `act()`. The checkpoint's cursor advances only after the local copy is updated, so a crash
repeats a change rather than skipping one; events carry no state — re-read the subject before acting.
