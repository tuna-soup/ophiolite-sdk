# %% [markdown]
# # Where are my wells
# See where the wells you may read are located, draw them, and read one well's data together with its wellbores'.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it reads three synthetic wells served
# on your own computer; nothing real is read. To read your project, put the `configuration.json` from Connect → Use
# Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key);
# then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter.
# Reading changes nothing in the project.
# %%
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect

client = connect()
extent = client.extent()
print(extent['count'], 'wells located, within', extent['bbox'], '(longitude and latitude)')
# %% [markdown]
# ## Every well, located or not
# One row per well you may read: its longitude and latitude when a source you may read states its location, empty
# when none does. The Map in the Workspace draws the same wells; `crs=` asks the server for another coordinate system.
# %%
wells = client.wells(crs='OGC:CRS84')
frame = wells.to_frame()
located = frame[frame['x'].notna()]
print(len(frame), 'wells,', len(located), 'located,', len(frame) - len(located), 'without a location')
print(located[['name', 'x', 'y']].to_string(index=False))
# %% [markdown]
# ## On a map
# The located wells as points, named. No background map is fetched; the picture is drawn here.
# %%
fig, ax = plt.subplots(figsize=(5, 5), layout='constrained')
ax.scatter(located['x'], located['y'], s=24, color='#1f6feb')
for _, row in located.iterrows(): ax.annotate(row['name'], (row['x'], row['y']), fontsize=8)
ax.set_xlabel('Longitude (°)'); ax.set_ylabel('Latitude (°)'); ax.set_title('Wells you can open')
fig.savefig('where-are-my-wells.png', bbox_inches='tight')
plt.close(fig)
print('Wrote where-are-my-wells.png with', len(located), 'wells')
# %% [markdown]
# ## One well's data with its wellbores'
# Logs, tops and surveys are usually filed on a well's wellbores. `include_wellbores=True` reads them together with
# the well's own in one read, each naming the well or wellbore it is filed on: what the well page shows. Set `name`
# to another well to read it.
# %%
from collections import Counter

name = located['name'].iloc[0]
well = client.entity(located.loc[located['name'] == name, 'entity_id'].iloc[0])
on_the_well, with_wellbores = well.assets(), well.assets(include_wellbores=True)
print(name + ':', len(on_the_well), 'filed on the well,', len(with_wellbores), 'with its wellbores')
for entity, count in Counter(item['entity']['name'] for item in with_wellbores).items(): print('  ' + entity + ':', count)
