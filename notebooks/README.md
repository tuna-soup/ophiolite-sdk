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
| `grids-and-gis-files/` | Two field outlines drawn as a GIS file stores them (a hole kept empty), what the file leaves open, upload and read back |
| `layers-for-a-gis/` | The layers QGIS opens, read page by page, a path that cannot be placed and why, the paths in plan view |
| `how-was-this-made/` | Two versions of one result, how each was made, what changed, what was made from the log, and making it again |
| `open-it-here/` | A result shown by name and version, its exact version opened in the Workspace, and Send again run twice, then refused after a newer version |
| `well-logs-in-a-bucket/` | A storage folder of logs browsed, added read from your storage each time, and a changed file reported because no copy was kept |
| `share-a-procedure/` | A procedure checked and run on your computer, added privately, enabled, then trusted once and run by a colleague |
| `start-a-procedure-from-a-template/` | Two working starts made from templates, a pair with no start refused, and every step and kind with a start |
| `a-recipe-runs-again/` | The residual report's steps as a recipe, checked, and in your project run step by step in a kept work folder |
| `run-it-again/` | A template-made procedure run on your computer, its card's "Run again" line run again, then refused after a change |
| `who-has-access-until-when/` | The projects you reach and the last day your access to each lasts, and who has access to this project, through what, and until when |
| `a-spreadsheet-and-a-database-joined/` | A spreadsheet kept as it is with its unit and missing-value marker, a database table read at its revision, and the two joined on the well name |
| `wells-from-sql-server-and-oracle/` | The same table of wells read from SQL Server and from Oracle at their revisions, compared well by well and plotted |
| `public-repository-to-map/` | Wells searched in NLOG, what it holds for each one, their positions brought in and drawn on a map |
| `petrophysical-calculations/` | Petrophysics-Python-Series 05: shale volume and density porosity from a project log, published back with its exact parent |
| `working-with-lasio/` | Petrophysics-Python-Series 07: a project log as a lasio LASFile, the original's lasio cells unchanged |
| `csv-file-to-las-file/` | Petrophysics-Python-Series 22: a LAS file built with lasio from a table, uploaded as an original |
| `well-paths-with-wellpathpy/` | Petrophysics-Python-Series 31: a deviation survey as a well path with wellpathpy and through Ophiolite, compared |

`gallery.json` lists every notebook (slug, title, sentence, modes, data; a notebook adapted from elsewhere also names
its source in `attribution`, the `data_terms` of the data it uses and the `minimum_sdk` it needs); the documentation site's gallery page is
generated from it. Each folder holds `notebook.py`, the percent script you edit, and `notebook.ipynb`, built from it:

    python tools/build_notebook.py           # rebuild every notebook
    python tools/build_notebook.py --check   # fails on a hand-edited notebook, an entry without one, or an unlisted folder

The first cell of each notebook holds the install instructions: a virtual environment, `pip install -r requirements.txt`
(the notebook lock with the pinned SDK, published beside the notebooks on the documentation site) and the kernel
registration. Notebooks use synthetic data (or, for the wedge, values measured on the attributed HON-GT-01 excerpt; the four
Petrophysics-Python-Series notebooks fetch Volve data from their source repository by SHA-256 only in your project) and
are not in the wheel or the sdist.

Tests: `OPHIOLITE_RUN_TEMPLATES=1 python -m pytest -q tests/test_gallery.py` copies each notebook alone to an empty
directory and runs it with a real kernel against the installed SDK (the `templates` CI job, which installs
`ophiolite/templates/notebook/requirements.lock` and the SDK with `pip install --no-deps .`).
