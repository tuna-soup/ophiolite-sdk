# %% [markdown]
# # Map features from a GIS file
# Draw two field outlines as a GIS file stores them (one with a hole), say what the file leaves open, and, in your
# project, upload them as a GeoJSON file and read them back feature for feature.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` everything is computed on your own
# computer and nothing is published. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. Uploading
# there creates a map layer that only you can see until you share it.
# %%
import json
import tempfile
import uuid
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as Outline
from ophiolite.gallery import connect, synthetic

client = connect()
# Two areas in ED50 / UTM zone 31N (EPSG:23031), easting then northing, in metres. The second has a hole: its first ring
# is the outline (counter-clockwise), its second the hole. Coordinates are kept exactly as written; nothing is reprojected.
L_SHAPE = [[540000, 6160000], [544000, 6160000], [544000, 6162000], [542000, 6162000], [542000, 6170000], [540000, 6170000], [540000, 6160000]]
RING = [[546000, 6160000], [550000, 6160000], [550000, 6164000], [546000, 6164000], [546000, 6160000]]
HOLE = [[547000, 6161000], [547000, 6163000], [549000, 6163000], [549000, 6161000], [547000, 6161000]]  # clockwise, as GeoJSON holes are
collection = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [L_SHAPE]}, 'properties': {'FIELD_CODE': 'ELL', 'WELLS': 3}},
    {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [RING, HOLE]}, 'properties': {'FIELD_CODE': 'RING', 'WELLS': 1}}]}
print(len(collection['features']), 'features:', [f['properties']['FIELD_CODE'] for f in collection['features']])
# %% [markdown]
# ## Plan view
# Each area is drawn with its rings as one outline; the hole runs the other way round, so it stays empty. North is at the top
# because the coordinate system says the axes are easting and northing.
# %%
def outline(rings):
    vertices, codes = [], []
    for ring in rings:
        vertices += ring; codes += [Outline.MOVETO] + [Outline.LINETO] * (len(ring) - 2) + [Outline.CLOSEPOLY]
    return Outline(vertices, codes)

fig, ax = plt.subplots(figsize=(5, 5), layout='constrained')
for feature in collection['features']:
    ax.add_patch(PathPatch(outline(feature['geometry']['coordinates']), facecolor='#a9c4e4', edgecolor='#1f5fa8'))
ax.set_xlim(539000, 551000); ax.set_ylim(6159000, 6171000); ax.set_aspect('equal')
ax.set_xlabel('Easting (m) →'); ax.set_ylabel('Northing (m) ↑'); ax.set_title('Two field outlines, EPSG:23031')
fig.savefig('grids-and-gis-files.png', bbox_inches='tight')
plt.close(fig)
rings = collection['features'][1]['geometry']['coordinates']
inside = sum(Outline(ring).contains_point((548000, 6162000)) for ring in rings) % 2 == 1  # even-odd at the centre of the hole
print('Wrote grids-and-gis-files.png; the hole is', 'filled' if inside else 'empty')
# %% [markdown]
# ## What the file leaves open
# A GeoJSON file of these coordinates does not say its coordinate system, so it is declared. A Shapefile states it
# in its `.prj`, a GeoPackage in its tables; a ZMAP+ grid does not say whether its corner values are cell centres or
# edges. `declare` answers, by kind, what a kind asks before it is read; anything not declared stays "Not stated".
# %%
declare = {'geojson/1': {'crs': 'EPSG:23031'}}
print(declare)
# %% [markdown]
# ## Upload it and read it back
# The layer you read back has the features in file order, with the values written.
# %%
if synthetic():
    print('Synthetic mode: nothing is published. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to upload in your project.')
else:
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch) / ('outlines-' + uuid.uuid4().hex[:8]); folder.mkdir()
        (folder / 'outlines.geojson').write_text(json.dumps(collection))
        report = client.upload(folder, attribution='Drawn in the gallery notebook', rights_confirmed=True, declare=declare)
    item = report.items[0]
    layer = client.read_data(item['asset_id'], item['revision'])
    assert [f['properties']['FIELD_CODE'] for f in layer.features] == ['ELL', 'RING'] and layer.context['crs'] == 'EPSG:23031'
    print(layer, item['state'])
