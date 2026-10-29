# %% [markdown]
# # Wells from SQL Server and Oracle
# Read the same table of wells from a SQL Server and an Oracle database selected in your project, each at the exact
# revision the project holds, check that both give the same wells at the same coordinates, and plot them.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` three Groningen wells, typed below as
# each system returns them, are compared on your own computer and nothing is sent. To work in your project, put the
# `configuration.json` from Connect → Use Python in this folder and run `ophiolite login` here; then set
# `OPHIOLITE_URL`, `OPHIOLITE_PROJECT`, `OPHIOLITE_SQLSERVER_SOURCE` and `OPHIOLITE_ORACLE_SOURCE` (the ids of the
# two sources, from `client.sources()`) before you start Jupyter. Ophiolite only reads; nothing is written to either
# database.
# %%
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from ophiolite.gallery import connect, synthetic

client = connect()
# %% [markdown]
# ## Read each source at its revision
# A read is verified against the revision the project recorded; the frame says its coordinate system and revision.
# Oracle keeps no empty strings (an empty string is NULL there), so an empty operator in SQL Server is missing in
# Oracle; coordinates are as stored in both.
# %%
if synthetic():
    print('Synthetic mode: nothing is sent. Three wells, as each system returns them, are compared on this computer.')
    COLUMNS = ['well_id', 'name', 'operator', 'x', 'y', 'depth']
    SQLSERVER = [('ALO-01', 'ALLARDSOOG-01', 'Nederlandse Aardolie Maatschappij B.V.', 217009.52200567, 568544.1263913, 1748.0),
                 ('ALO-01-S1', 'ALLARDSOOG-01-SIDETRACK1', 'Nederlandse Aardolie Maatschappij B.V.', 217009.52200567, 568544.1263913, 3180.0),
                 ('W-EMPTY', 'An operator left empty', '', 256275.37461672, 591633.13225594, None)]
    ORACLE = [row if row[2] else row[:2] + (None,) + row[3:] for row in SQLSERVER]  # Oracle: an empty string is NULL
    frames = {}
    for system, rows in (('SQL Server', SQLSERVER), ('Oracle', ORACLE)):
        frame = pd.DataFrame(rows, columns=COLUMNS)
        frame.attrs.update(crs='EPSG:28992', revision='synthetic-' + system.lower().replace(' ', ''))
        frames[system] = frame
else:
    sources = {'SQL Server': os.environ.get('OPHIOLITE_SQLSERVER_SOURCE'), 'Oracle': os.environ.get('OPHIOLITE_ORACLE_SOURCE')}
    if not all(sources.values()):
        raise SystemExit('Set OPHIOLITE_SQLSERVER_SOURCE and OPHIOLITE_ORACLE_SOURCE to the ids of the two sources (client.sources()).')
    frames = {}
    for system, source_id in sources.items():
        source = client.source(source_id)
        frames[system] = source.read(expect_revision=source.revision).to_frame()
for system, frame in frames.items():
    print(f'{system}: {len(frame)} wells in {frame.attrs["crs"]} at revision {frame.attrs["revision"][:12]}')
# %% [markdown]
# ## The same wells at the same coordinates
# Both reads are joined on the well identifier. Any well only one system holds, or whose coordinates differ, is listed.
# %%
a, b = (frames[s].set_index('well_id') for s in ('SQL Server', 'Oracle'))
only = sorted(set(a.index) ^ set(b.index))
both = a.index.intersection(b.index)
moved = [w for w in both if (a.at[w, 'x'], a.at[w, 'y']) != (b.at[w, 'x'], b.at[w, 'y'])]
print(f'In both: {len(both)} wells; in one only: {len(only)}; at other coordinates: {len(moved)}')
first = {system: frame.set_index('well_id').loc['ALO-01'] for system, frame in frames.items()}
for system, well in first.items():
    print(f'ALO-01 in {system}: {well["name"]} at x {float(well["x"])!r}, y {float(well["y"])!r}')
missing = {system: int(frame['operator'].isna().sum()) if 'operator' in frame else 'not mapped' for system, frame in frames.items()}
print('Wells without an operator:', missing)  # a column the mapping leaves out is not in the frame
fig, axis = plt.subplots(figsize=(5, 5))
axis.scatter(a['x'], a['y'], s=18, color='#5b7f6e', label='SQL Server')
axis.scatter(b['x'], b['y'], s=4, color='#c06030', label='Oracle')
axis.set_xlabel('x (m)'); axis.set_ylabel('y (m)'); axis.set_title('Wells from SQL Server and Oracle'); axis.legend()
fig.savefig('wells-from-sql-server-and-oracle.png', bbox_inches='tight')
plt.close(fig)
print('Wrote wells-from-sql-server-and-oracle.png')
