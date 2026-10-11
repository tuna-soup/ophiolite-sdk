# %% [markdown]
# # A spreadsheet and a database, joined
# Keep a spreadsheet of core samples as it is, with the unit and the missing-value marker of its porosity column, read it
# back as a table, read a well table from a connected database, join the two on the well name and plot the mean
# porosity per operator.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the spreadsheet and the database are
# made on your own computer, joined there, and nothing is sent. To work in your project, put the `configuration.json`
# from Connect → Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a
# project access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you
# start Jupyter. There, keeping the spreadsheet creates a table only you can see until you share it, and the database
# table is the first SQL table you selected in the project that has a `well` column.
# %%
import csv
import sqlite3
import tempfile
import uuid
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from ophiolite.gallery import connect, synthetic

client = connect()
TAG = uuid.uuid4().hex[:6].upper()  # a new file name each run, so a second run keeps a new table
SAMPLES = [('L16-12', 3243.5, 21.5), ('L16-12', 3244.0, -888), ('L16-12', 3245.5, 18.0),
           ('HON-GT-01', 1810.0, 24.0), ('HON-GT-01', 1812.5, 26.0), ('NLW-GT-01', 2100.0, 15.0)]
WELLS = [('L16-12', 'Wintershall Noordzee', 'offshore'), ('HON-GT-01', 'Hydreco', 'onshore'), ('PRW-6', 'NAM', 'onshore')]
folder = Path(tempfile.mkdtemp(prefix='ophiolite-join-'))
spreadsheet = folder / f'core-samples-{TAG}.csv'
with spreadsheet.open('w', newline='') as out:
    writer = csv.writer(out); writer.writerow(['well', 'depth_m', 'porosity']); writer.writerows(SAMPLES)
database = folder / 'wells.sqlite'
with sqlite3.connect(database) as db:
    db.execute('CREATE TABLE wells(well TEXT PRIMARY KEY, operator TEXT, location TEXT)'); db.executemany('INSERT INTO wells VALUES(?,?,?)', WELLS)
print(f'{spreadsheet.name}: {len(SAMPLES)} samples; porosity in %, -888 means missing')
print(f'{database.name}: {len(WELLS)} wells')
# %% [markdown]
# ## Keep the spreadsheet as a table, read the database table
# The spreadsheet is kept exactly as it is; its porosity column says its unit and that -888 is missing. Read back, the
# -888 stays a value until `to_frame(missing="declared")` makes it missing. The database table is read at the exact
# revision the project holds; nothing is copied into wells.
# %%
if synthetic():
    print('Synthetic mode: nothing is sent. Both tables are read on this computer.')
    samples = pd.read_csv(spreadsheet).replace({'porosity': {-888: pd.NA}}).astype({'porosity': 'Float64'})
    with sqlite3.connect(database) as db: wells = pd.read_sql('SELECT * FROM wells', db)
else:
    done = client.imports.from_table(spreadsheet, 'table', columns={'porosity': {'unit': '%', 'missing': '-888'}}, audience=[])
    unit = done['run']['units'][0]
    kept = client.read_data(unit['asset_id'], unit['revision'])
    print(f'Table kept: {len(kept)} rows, revision {kept.revision[:12]}, units {kept.units}')
    samples = kept.to_frame(missing='declared')
    found = [s.read() for s in client.sources() if s.profile == 'table/1']
    snapshot = next((t for t in found if 'well' in t.read_columns), None)
    if snapshot is None: raise SystemExit('Select a SQL table with a `well` column in this project first (Add data → Connect a database).')
    wells = snapshot.to_frame()
    print(f'Database table {snapshot.name!r} at revision {snapshot.revision[:12]}')
# %% [markdown]
# ## Join on the well name
# An inner join keeps the samples whose well is in the database table. A sample of a well the database does not hold
# is left out, and the missing porosity is left out of the mean.
# %%
joined = samples.merge(wells, on='well', how='inner')
print(f'Joined: {len(joined)} samples of {joined["well"].nunique()} wells; left out: {len(samples) - len(joined)} sample(s) of a well not in the database')
means = joined.groupby('operator')['porosity'].mean()
for operator, mean in means.items():
    print(f'{operator}: mean porosity {mean:.2f} %')
fig, axis = plt.subplots(figsize=(6, 2))
axis.barh(list(means.index), [float(v) for v in means.values], color='#5b7f6e')
axis.set_xlabel('Mean porosity (%)'); axis.set_title('Core samples joined to their wells')
fig.savefig('a-spreadsheet-and-a-database-joined.png', bbox_inches='tight')
plt.close(fig)
print('Wrote a-spreadsheet-and-a-database-joined.png')
