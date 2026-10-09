# Notebook gallery

Notebooks that run as downloaded: each needs only an installed SDK and starts with `from ophiolite.gallery import connect`.
Without `OPHIOLITE_URL` they work on a synthetic log served on the reader's own computer; with `OPHIOLITE_URL` and
`OPHIOLITE_PROJECT` they work in that project with the reader's saved sign-in (`ophiolite login`) or `OPHIOLITE_ACCESS_KEY`.

| Folder | What it shows |
|---|---|
| `read-a-well-log/` | Read one gamma-ray curve with its units and depth reference, and plot it |
| `shale-volume-from-gamma-ray/` | Percentile picks, the five methods side by side, publish one result, add a second version |
| `make-a-wavelet/` | A 30 Hz Ricker wavelet, its strongest frequency against the declared one, upload and a second version |
| `make-a-wedge-model/` | Rocks from HON-GT-01, a wedge model, its synthetic and the tuning thickness; publish all three |
| `large-files/` | A seismic volume sent in parts, continued after an interruption, read back by ranges and compared byte for byte |
| `a-well-folder-in-one-report/` | A folder of logs uploaded in one step, one report per file, and the wellbores the logs name |
| `how-was-this-made/` | Two versions of one result, how each was made, what changed, what was made from the log, and making it again |

`gallery.json` lists every notebook (slug, title, sentence, modes, data); the documentation site's gallery page is
generated from it. Each folder holds `notebook.py`, the percent script you edit, and `notebook.ipynb`, built from it:

    python tools/build_notebook.py           # rebuild every notebook
    python tools/build_notebook.py --check   # fails on a hand-edited notebook, an entry without one, or an unlisted folder

The first cell of each notebook holds the install instructions: a virtual environment, `pip install -r requirements.txt`
(the notebook lock with the pinned SDK, published beside the notebooks on the documentation site) and the kernel
registration. Notebooks use synthetic data (or, for the wedge, values measured on the attributed HON-GT-01 excerpt) and are not in the wheel or the sdist.

Tests: `OPHIOLITE_RUN_TEMPLATES=1 python -m pytest -q tests/test_gallery.py` copies each notebook alone to an empty
directory and runs it with a real kernel against the installed SDK (the `templates` CI job, which installs
`ophiolite/templates/notebook/requirements.lock` and the SDK with `pip install --no-deps .`).
