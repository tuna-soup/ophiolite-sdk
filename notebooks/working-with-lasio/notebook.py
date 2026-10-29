# %% [markdown]
# # Working with lasio
# Andy McDonald's "Working With LASIO" with one line changed: the log comes from your project as a `lasio.LASFile`
# instead of from a LAS file on disk; every lasio cell after it runs as written.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it reads a synthetic log served on
# your own computer; nothing real is read. To read your project, put the `configuration.json` from Connect → Use Python
# in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then
# set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter.
#
# **Source.** "07 - Working With LASIO" from [Petrophysics-Python-Series](https://github.com/andymcdgeo/Petrophysics-Python-Series)
# at commit `b6bcfb17f026e8b612cf64ed24d408bb69290d4e`, by Andy McDonald, MIT licence (Copyright (c) 2021 Andy
# McDonald). The original reads the Volve well 15/9-19 composite log; Volve data is Equinor's, under the Equinor Open
# Data Licence (credit Equinor and the Volve licence partners). This notebook ships no Volve data: it reads whatever
# gamma-ray log your project holds.
#
# | Original cell | Here |
# |---|---|
# | `import pandas`, `matplotlib`, `lasio` | kept; `connect` and `to_lasio` imported beside them |
# | `las = lasio.read("Data/15-9-19_SR_COMP.LAS")` | **changed**: `las = to_lasio(client.read(...))` of the longest gamma-ray log |
# | well header loop, `las.well.WELL.value`, curve loops and count | kept |
# | `las.df()`, `head`, `describe`, `info`, `notnull() * 1` | kept |
# | data-coverage plot | **changed**: one track per curve present (the original draws seven) and saved as `working-with-lasio.png` instead of `plt.show()` |
# | seven-track log plot (AC, CALI, DEN, NEU, RDEP, RMED) | **skipped**: it names curves a project log need not have |
#
# `to_lasio` reconstructs the header from the exact version read: `DEPT`, each curve with its declared unit, `NULL`
# −999.25, and the project, asset and revision in `~Other`. The original file's header is what
# `client.download_original` returns.
# %%
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import lasio
from ophiolite.gallery import connect
from ophiolite.lasio import to_lasio

client = connect()
# %%
# was: las = lasio.read("Data/15-9-19_SR_COMP.LAS")
LOG_NAME = None  # None: the longest log with GR you may use; or the exact name of the log to read
log = client.find_log(curves=['GR'], name=LOG_NAME)
las = to_lasio(client.read(log['asset_id'], log['revision'], log['curves']))
# %%
for item in las.well:
    print(f"{item.descr} ({item.mnemonic}): {item.value}")
# %%
las.well.WELL.value
# %%
for curve in las.curves:
    print(curve.mnemonic)
# %%
for count, curve in enumerate(las.curves):
    print(f"Curve: {curve.mnemonic}, Units: {curve.unit}, Description: {curve.descr}")
print(f"There are a total of: {count+1} curves present within this file")
# %%
well = las.df()
# %%
well.head()
# %%
well.describe()
# %%
well.info()
print('Missing GR samples:', int(well['GR'].isna().sum()))
# %%
well_nan = well.notnull() * 1
# %%
well_nan.head()
# %%
fig = plt.figure(figsize=(1 + len(well_nan.columns), 10))
columns = well_nan.columns
axes = [plt.subplot2grid((1, len(columns)), (0, i)) for i in range(len(columns))]

for i, ax in enumerate(axes):
    ax.plot(well_nan.iloc[:, i], well_nan.index, lw=0)
    ax.set_ylim(well_nan.index.max(), well_nan.index.min())
    ax.set_xlim(0, 1)
    ax.set_title(columns[i])
    ax.set_facecolor('whitesmoke')
    ax.fill_betweenx(well_nan.index, 0, well_nan.iloc[:, i], facecolor='red')
    if i > 0:
        plt.setp(ax.get_yticklabels(), visible=False)
    plt.setp(ax.get_xticklabels(), visible=False)

axes[0].set_ylabel('Depth', fontsize=14)
plt.subplots_adjust(wspace=0)
fig.savefig('working-with-lasio.png', bbox_inches='tight')
plt.close(fig)
print('Wrote working-with-lasio.png')
