# %% [markdown]
# # Well paths with wellpathpy
# Andy McDonald's "Creating Well Paths with wellpathpy": a deviation survey becomes a well path with wellpathpy, and
# the same survey, kept in your project with its context declared, gives the same positions through Ophiolite.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it works on a five-station survey
# written here and uploads nothing. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then
# set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. In your
# project the notebook downloads the original's Volve survey from the source repository at a pinned commit, checks
# its SHA-256, and uploads it as an original only you can see until you share it.
#
# **Source.** "31 - Creating Well Paths with wellpathpy" from [Petrophysics-Python-Series](https://github.com/andymcdgeo/Petrophysics-Python-Series)
# at commit `b6bcfb17f026e8b612cf64ed24d408bb69290d4e`, by Andy McDonald, MIT licence (Copyright (c) 2021 Andy
# McDonald). wellpathpy is LGPL-3.0, installed from PyPI. **Data terms.** The survey of the Volve well 15/9-F-12 is
# Equinor's, under the [Equinor Open Data Licence](https://cdn.equinor.com/files/h61q9gi9/global/de6532f6134b9a953f6c41bac47a0c055a3712d3.pdf):
# credit Equinor and the Volve licence partners. It is not part of this notebook or of Ophiolite; it is fetched from
# the source repository when you run in your project.
#
# | Original cell | Here |
# |---|---|
# | `!pip install wellpathpy` | **skipped**: `requirements.txt` installs it |
# | imports, `np.set_printoptions` | kept; `connect`, `synthetic`, `write_survey` imported beside them |
# | `md, inc, azi = wp.read_csv('Data/Volve/15_9-F-12_Survey_Data.csv')` | **changed**: in your project, the pinned file fetched and checked by SHA-256, then the same `wp.read_csv`; synthetic, five stations written here |
# | `deviation`, `minimum_curvature().resample`, `pos.deviation()`, `to_tvdss(datum_elevation=30)`, `to_wellhead(...)`, the data frame | kept |
# | inclination/azimuth plots, the resampled overlay | kept, closed instead of `plt.show()` |
# | plan and section plots | kept with limits from the data (the original's fit only F-12); saved as `well-paths-with-wellpathpy.png` |
# | plotly 3D view | **skipped**: plotly is not in `requirements.txt` |
# | (new) | the survey written with `write_survey`, uploaded with its context (in your project), and Ophiolite's minimum curvature compared with wellpathpy's at every station |
# %%
import hashlib
import tempfile
import urllib.request
import uuid
from pathlib import Path
import wellpathpy as wp
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import numpy as np
np.set_printoptions(suppress=True)
from ophiolite.gallery import connect, synthetic
from ophiolite.typed import minimum_curvature
from ophiolite.writers import write_survey

client = connect()
SOURCE = 'https://raw.githubusercontent.com/andymcdgeo/Petrophysics-Python-Series/b6bcfb17f026e8b612cf64ed24d408bb69290d4e/'
SURVEY = ('Data/Volve/15_9-F-12_Survey_Data.csv', '6770e894657bdc791119e70339561216c4039f65b7d632c19030cee160af9fa2')
CREDIT = 'Volve data: Equinor and the Volve licence partners, Equinor Open Data Licence; survey from Petrophysics-Python-Series (Andy McDonald, MIT)'


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
# was: md, inc, azi = wp.read_csv('Data/Volve/15_9-F-12_Survey_Data.csv')
if synthetic():
    md, inc, azi = (np.array(column, dtype=float) for column in ([0, 100, 200, 300, 400], [0, 0, 10, 20, 30], [0, 0, 45, 45, 60]))
else:
    work = tempfile.TemporaryDirectory()
    md, inc, azi = wp.read_csv(str(fetch(*SURVEY, work.name)))
# %%
md
# %%
dev = wp.deviation(md, inc, azi)
# %%
dev
# %%
fig, ax = plt.subplots(1, 2, figsize=(8,10))

ax1 = plt.subplot2grid((1,2), (0,0))
ax2 = plt.subplot2grid((1,2), (0,1))

ax1.plot(dev.inc, dev.md, color = "black", marker='.', linewidth=0)
ax1.set_ylim(dev.md[-1], 0)
ax1.set_xlim(0, 90)
ax1.set_xlabel('Deviation', fontweight='bold', fontsize=14)
ax1.set_ylabel('Measured Depth', fontweight='bold', fontsize=14)
ax1.grid(color='lightgrey')
ax1.set_axisbelow(True)

ax2.plot(dev.azi, dev.md, color = "black", marker='.', linewidth=0)
ax2.set_ylim(dev.md[-1], 0)
ax2.set_xlim(0, 360)
ax2.set_xlabel('Azimuth', fontweight='bold', fontsize=14)
ax2.grid(color='lightgrey')
ax2.set_axisbelow(True)

plt.close(fig)
# %%
depth_step = 1
depths = list(range(0, int(dev.md[-1]) + 1, depth_step))
# %%
pos = dev.minimum_curvature().resample(depths = depths)
# %%
pos
# %%
resampled_dev = pos.deviation()
# %%
resampled_dev
# %%
fig, ax = plt.subplots(1, 3, figsize=(15,5))
ax1, ax2, ax3 = ax

ax1.plot(pos.easting, pos.northing, color = "black", linewidth=2)
ax1.set_xlabel('West (-) / East (+)', fontweight='bold', fontsize=14)
ax1.set_ylabel('South (-) / North (+)', fontweight='bold', fontsize=14)
ax1.grid(color='lightgrey')
ax1.set_axisbelow(True)

ax2.plot(pos.easting, pos.depth, color = "black", linewidth=2)
ax2.invert_yaxis()
ax2.set_xlabel('West (-) / East (+)', fontweight='bold', fontsize=14)
ax2.set_ylabel('Depth', fontweight='bold', fontsize=14)
ax2.grid(color='lightgrey')
ax2.set_axisbelow(True)

ax3.plot(pos.northing, pos.depth, color = "black", linewidth=2)
ax3.invert_yaxis()
ax3.set_xlabel('South (-) / North (+)', fontweight='bold', fontsize=14)
ax3.set_ylabel('Depth', fontweight='bold', fontsize=14)
ax3.grid(color='lightgrey')
ax3.set_axisbelow(True)

plt.tight_layout()
fig.savefig('well-paths-with-wellpathpy.png', bbox_inches='tight')
plt.close(fig)
print('Wrote well-paths-with-wellpathpy.png')
# %%
pos_tvdss = pos.to_tvdss(datum_elevation=30)
# %%
pos_tvdss
# %%
wellhead_northing = 6478572
wellhead_easting = 435050

pos_wellhead = pos.to_wellhead(surface_northing=wellhead_northing,
                               surface_easting=wellhead_easting)
# %%
pos_wellhead.northing
# %%
import pandas as pd
# %%
data = {'MD':resampled_dev.md,
        'AZI':resampled_dev.azi,
        'INC':resampled_dev.inc,
        'TVD':pos.depth,
        'TVDSS':pos_tvdss.depth,
        'YLOC':pos.northing,
        'XLOC':pos.easting,
        'NORTHING': pos_wellhead.northing,
        'EASTING': pos_wellhead.easting}

df = pd.DataFrame(data)
# %%
df
# %% [markdown]
# ## The same survey in Ophiolite
# The stations are written as a deviation survey with the context the source gives: metres, and the 30 m datum the
# example assumes for `to_tvdss`, declared as that assumption; the source does not state the azimuth reference, so it
# is declared unknown. The wellhead coordinates above are the example's.
# Ophiolite's minimum curvature (offsets from the first station) is compared with wellpathpy's at every station.
# %%
stations = [{'md': float(m), 'inclination': float(i), 'azimuth': float(a)} for m, i, a in zip(md, inc, azi)]
DATUM = 'Assumed 30 m above sea level, as in the source example (to_tvdss datum_elevation=30); not survey metadata'
written = write_survey(stations, depth_unit='m', azimuth_reference='unknown', depth_datum=DATUM)
if synthetic():
    print(f'Synthetic mode: nothing is uploaded. In your project upload_data would add this deviation survey as an original with the context declared.')
    offsets = minimum_curvature(stations)
else:
    receipt = client.upload_data(written.bytes, filename='15_9-F-12-survey.csv', profile=written.profile, declared=written.declared,
                                 name='15/9-F-12 deviation survey (Petrophysics-Python-Series 31)', attribution=CREDIT, audience=[],
                                 rights_confirmed=True, command_id=uuid.uuid4().hex)
    trajectory = client.read_data(receipt.asset_id, receipt.revision)
    context = trajectory.data['context']
    print('Read back:', len(trajectory.stations), 'stations; depth unit', context['depth_unit'], '- datum', context.get('depth_datum'),
          '- azimuth reference', context.get('azimuth_reference', 'unknown'))
    assert context['depth_unit'] == 'm' and context.get('depth_datum') == DATUM
    offsets = trajectory.minimum_curvature()
reference = dev.minimum_curvature()
worst = max(max(abs(o['dtvd'] - reference.depth[k]), abs(o['dnorth'] - reference.northing[k]), abs(o['deast'] - reference.easting[k]))
            for k, o in enumerate(offsets))
for k in (range(len(offsets)) if len(offsets) <= 10 else (1, 60, len(offsets) - 1)):
    o = offsets[k]
    print(f"station {k} md {o['md']:g}: TVD {o['dtvd']:.4f} north {o['dnorth']:.4f} east {o['deast']:.4f}")
print(f'Ophiolite and wellpathpy agree within 0.01 m at all {len(offsets)} stations' if worst <= 0.01 else f'They differ by {worst} m')
assert worst <= 0.01, worst
