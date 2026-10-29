# %% [markdown]
# # CSV file to LAS file
# Andy McDonald's "CSV File to LAS File": build a LAS file from a table with lasio, then upload it to your project as
# an original in one call instead of writing it to disk.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it builds the file from a small table
# written here and uploads nothing. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then
# set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. In your
# project the notebook downloads the original's Volve table from the source repository at a pinned commit, checks its
# SHA-256, and uploads the file it builds as an original only you can see until you share it.
#
# **Source.** "22 - CSV File to LAS File" from [Petrophysics-Python-Series](https://github.com/andymcdgeo/Petrophysics-Python-Series)
# at commit `b6bcfb17f026e8b612cf64ed24d408bb69290d4e`, by Andy McDonald, MIT licence (Copyright (c) 2021 Andy
# McDonald). **Data terms.** The table of the Volve well 15/9-19 is Equinor's, under the
# [Equinor Open Data Licence](https://cdn.equinor.com/files/h61q9gi9/global/de6532f6134b9a953f6c41bac47a0c055a3712d3.pdf):
# credit Equinor and the Volve licence partners. It is not part of this notebook or of Ophiolite; it is fetched from
# the source repository when you run in your project.
#
# | Original cell | Here |
# |---|---|
# | `import lasio`, `pandas` | kept; `connect`, `synthetic` and `lasio_bytes` imported beside them |
# | `pd.read_csv('Data/Notebook 22/...')` | **changed**: in your project, the pinned file fetched and checked by SHA-256; synthetic, a three-row table written here |
# | `head`, `info`, `LASFile()`, `header`, `curves`, the four well names, `HeaderItem` cells | kept |
# | `las_file.add_curve(...)` | **changed** to `las_file.append_curve(...)`: lasio 0.32 has no `add_curve` |
# | `las_file.write('Output/...')` (twice) | **changed**: `lasio_bytes(las_file)` and, in your project, `client.upload_las(...)`; nothing is written beside the notebook |
# | the units list and the loop adding each column | kept (synthetic: the units of its three columns) |
# | (new) | in your project, the uploaded original downloaded and read back with lasio |
# %%
import hashlib
import tempfile
import urllib.request
import uuid
from pathlib import Path
import lasio
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic
from ophiolite.lasio import lasio_bytes

client = connect()
SOURCE = 'https://raw.githubusercontent.com/andymcdgeo/Petrophysics-Python-Series/b6bcfb17f026e8b612cf64ed24d408bb69290d4e/'
TABLE = ('Data/Notebook 22/Notebook 22 - VOLVE - 15_9-19.csv', '5bf611aac9c8d58433edf7f9adfb992320390b8fae01056dc044ce73ebad1c06')
CREDIT = 'Volve data: Equinor and the Volve licence partners, Equinor Open Data Licence; table from Petrophysics-Python-Series (Andy McDonald, MIT)'


def fetch(path, sha256, folder):
    """The pinned upstream file, refused unless its SHA-256 is the one named here."""
    try:
        raw = urllib.request.urlopen(SOURCE + urllib.request.quote(path), timeout=60).read()
    except OSError as error:
        raise SystemExit(f'Upstream unreachable ({error}); in your project this notebook needs the pinned Volve file. Nothing was uploaded.')
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise SystemExit(f'{path} differs from the pinned copy (sha256 {sha256}); nothing was uploaded.')
    target = Path(folder) / Path(path).name
    target.write_bytes(raw)
    return target
# %%
# was: data = pd.read_csv('Data/Notebook 22/Notebook 22 - VOLVE - 15_9-19.csv')
if synthetic():
    data = pd.DataFrame({'DEPTH': [100.0, 101.0, 102.0], 'GR': [10.0, None, 30.0], 'RHOB': [2.45, 2.50, 2.55]})
else:
    work = tempfile.TemporaryDirectory()
    data = pd.read_csv(fetch(*TABLE, work.name))
# %%
data.head()
# %%
data.info()
# %%
las_file = lasio.LASFile()
# %%
las_file.header
# %%
las_file.curves
# %%
well_name = 'Random Well'
field_name = 'Random Field'
uwi = '123456789'
country = 'Random Country'
# %%
las_file.well['WELL'] = lasio.HeaderItem('WELL', value=well_name)
las_file.well['FLD'] = lasio.HeaderItem('FLD', value=field_name)
las_file.well['UWI'] = lasio.HeaderItem('UWI', value=uwi)
las_file.well['CTRY'] = lasio.HeaderItem('CTRY', value=country)
# %%
las_file.header
# %%
# was: las_file.add_curve('DEPT', data['DEPTH'], unit='m')
las_file.append_curve('DEPT', data['DEPTH'], unit='m')
# %%
units = ['m',
 'inches',
 'unitless',
 'us/ft',
 'us/ft',
 'us/ft',
 'us/ft',
 'API',
 'v/v_decimal',
 'v/v_decimal',
 'v/v_decimal',
 'v/v_decimal',
 'v/v_decimal',
 'g/cm3',
 'g/cm3',
 'ohm.m',
 'ohm.m',
 'degC']
if synthetic():
    units = ['m', 'API', 'g/cm3']  # the three columns of the synthetic table
# %%
for col, unit in zip(data.columns, units):
    if col != 'DEPTH':
        las_file.append_curve(col, data[col], unit=unit)
# %%
las_file.curves
# %%
las_file['GR']
# %%
fig, ax = plt.subplots(figsize=(3, 6))
ax.plot(las_file['GR'], las_file['DEPT'], color='green')
ax.set_xlabel('GR (API)')
ax.set_ylabel('Depth (m)')
ax.invert_yaxis()
fig.savefig('csv-file-to-las-file.png', bbox_inches='tight')
plt.close(fig)
print('Wrote csv-file-to-las-file.png')
# %% [markdown]
# ## Upload instead of writing to disk
# `lasio_bytes` writes the file as LAS 2.0 bytes and checks that Ophiolite reads its header back; `upload_las` adds
# it to your project as an original, with the data's credit.
# %%
# was: las_file.write('Output/Notebook 22/OutputLAS_FINAL.las')
raw = lasio_bytes(las_file)
back = lasio.read(raw.decode())
print(f'Built a LAS file of {len(back.curves)} curves and {len(back.index)} rows')
if synthetic():
    print(f'Synthetic mode: nothing is uploaded. In your project upload_las would add this {len(back.curves)}-curve file as an original.')
else:
    receipt = client.upload_las(raw, name='15/9-19 from CSV (Petrophysics-Python-Series 22)', attribution=CREDIT,
                                audience=[], rights_confirmed=True, filename='15_9-19-from-csv.las', command_id=uuid.uuid4().hex)
    original = Path(work.name) / 'uploaded.las'
    client.download_original(receipt.asset_id, receipt.revision, original)
    uploaded = lasio.read(str(original))
    print(f'Uploaded {receipt.asset_id[:12]}: {len(uploaded.curves)} curves, {len(uploaded.index)} rows read back with lasio')
