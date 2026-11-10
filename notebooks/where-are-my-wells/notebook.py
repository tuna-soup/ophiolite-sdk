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
# on your own computer; nothing real is read. With `ophiolite-mapper` installed as well (`pip install
# ophiolite-mapper`), the three synthetic wells are a table on your computer instead: the mapper turns it into a
# project folder, and the wells are read back from that folder. To read your project, put the `configuration.json` from
# Connect → Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a
# project access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you
# start Jupyter. Reading changes nothing in the project.
# %%
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic

# Three synthetic wells, their surface location in easting and northing (metres, ED50 / UTM zone 31N).
TABLE = ('UWI,Well name,Easting,Northing\nSYN-0001,Synthetic 1,431000.0,6521000.0\nSYN-0002,Synthetic 2,431250.5,6521125.0\n'
         'SYN-0003,Synthetic 3,432100.0,6520400.0\n')
CRS = 'EPSG:23031'
mapped = synthetic() and importlib.util.find_spec('ophiolite_mapper') is not None
if mapped:
    import pyarrow.parquet as pq
    from ophiolite.bundle import open_bundle
    from ophiolite_mapper.cli import main as mapper
    work = Path(tempfile.mkdtemp(prefix='ophiolite-mapper-'))
    (work / 'wells.csv').write_text(TABLE, encoding='utf-8')
    assert mapper(['inspect', str(work / 'wells.csv'), '--target', 'wells', '--no-reviewed']) == 0
    # Your decisions, written into the recipe: each suggested column accepted, the coordinate system stated, the
    # wells told apart by their UWI.
    recipe = json.loads((work / 'recipe.json').read_text(encoding='utf-8'))
    you = {'by': 'Gallery reader', 'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    for row in recipe['fields']: row['decision'] = dict(you, action='accept' if row['column'] else 'leave-unmapped')
    for row in recipe['declarations']:
        if row['name'] == 'crs': row['value'], row['decision'] = CRS, dict(you, action='accept')
    recipe['identity']['decision'] = dict(you, action='accept')
    (work / 'recipe.json').write_text(json.dumps(recipe, indent=2), encoding='utf-8')
    assert mapper(['write', str(work / 'recipe.json'), '--out', str(work / 'folder'), '--no-reviewed']) == 0
    folder = open_bundle(str(work / 'folder'))  # every file the folder lists is checked against its checksum
    frame = pq.read_table(work / 'folder/items/wells.parquet').to_pandas()
    print('Read back from the project folder:', len(folder.folder), 'files checked, items/wells.parquet among them')
    print(int(frame['x'].notna().sum()), 'wells located, in', CRS, '(easting and northing, metres)')
    axes = ('Easting (m)', 'Northing (m)')
else:
    client = connect()
    extent = client.extent()
    print(extent['count'], 'wells located, within', extent['bbox'], '(longitude and latitude)')
    axes = ('Longitude (°)', 'Latitude (°)')
    if synthetic():
        print('With ophiolite-mapper installed (pip install ophiolite-mapper), these wells are first made into a project folder on this computer.')
# %% [markdown]
# ## Every well, located or not
# One row per well you may read: its longitude and latitude when a source you may read states its location, empty
# when none does. The Map in the Workspace draws the same wells; `crs=` asks the server for another coordinate system.
# From the mapper's folder, the wells are in the coordinate system the recipe states. The mapper's table holds the
# three located wells only: a well without a location is left out, because writing it needs an acknowledgement in the
# recipe.
# %%
if not mapped:
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
ax.set_xlabel(axes[0]); ax.set_ylabel(axes[1]); ax.set_title('Wells you can open')
fig.savefig('where-are-my-wells.png', bbox_inches='tight')
plt.close(fig)
print('Wrote where-are-my-wells.png with', len(located), 'wells')
# %% [markdown]
# ## One well's data with its wellbores'
# Logs, tops and surveys are usually filed on a well's wellbores. `include_wellbores=True` reads them together with
# the well's own in one read, each naming the well or wellbore it is filed on: what the well page shows. Set `name`
# to another well to read it. A project folder holds no data filed on its wells, so this part reads a project.
# %%
from collections import Counter

if mapped:
    print('The project folder holds the wells only; set OPHIOLITE_URL to read a well with its wellbores in your project.')
else:
    name = located['name'].iloc[0]
    well = client.entity(located.loc[located['name'] == name, 'entity_id'].iloc[0])
    on_the_well, with_wellbores = well.assets(), well.assets(include_wellbores=True)
    print(name + ':', len(on_the_well), 'filed on the well,', len(with_wellbores), 'with its wellbores')
    for entity, count in Counter(item['entity']['name'] for item in with_wellbores).items(): print('  ' + entity + ':', count)
