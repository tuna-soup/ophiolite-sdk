# %% [markdown]
# # Layers for a GIS
# Read the layers QGIS opens from your project, every collection page by page as QGIS pages them, and draw the
# wellbore paths and tops in plan view.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it reads two pages written in this
# notebook and nothing is contacted. To read your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. Reading
# changes nothing in the project.
# %%
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic

client = connect()
features = '/api/v1/projects/%s/features' % client.project
# Two pages of a wellbore-paths collection as the server writes them (longitude, latitude; CRS84): the first page
# links to the second, the second links nowhere. The second path has no geometry and says why in `placement`.
PAGES = {
    features + '/collections/wellbore-paths/items?limit=100': {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': 'paths:a', 'geometry': {'type': 'LineString', 'coordinates': [[4.22525, 52.01533], [4.22492, 52.01601], [4.21587, 52.02283]]},
         'properties': {'name': 'HON-GT-01', 'placement': None}}],
        'links': [{'rel': 'next', 'href': client.url + features + '/collections/wellbore-paths/items?limit=100&cursor=1'}]},
    features + '/collections/wellbore-paths/items?limit=100&cursor=1': {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': 'paths:b', 'geometry': None,
         'properties': {'name': 'HON-GT-02', 'placement': 'This survey does not state that its azimuths are from grid north, so it is not drawn on the map.'}}],
        'links': []},
    features + '/collections': {'collections': [{'id': 'wellbore-paths', 'title': 'Wellbore paths'}]},
}


def get(path):
    """One answer of the layers' address: from your project in live mode, from PAGES in synthetic mode."""
    if synthetic(): return PAGES[path]
    answer = client.http.get(client.url + path, headers=client.credential.headers(client.url, client.project))
    answer.raise_for_status()
    return answer.json()


print('Collections:', [c['id'] for c in get(features + '/collections')['collections']])
# %% [markdown]
# ## Every feature, page by page
# A page holds at most 100 features and links to the next one; QGIS follows the same links. The address of the
# next page is the server's, so only its path is asked here.
# %%
def every(collection):
    found, path = [], features + '/collections/%s/items?limit=100' % collection
    while path:
        page = get(path)
        found += page['features']
        link = next((l['href'] for l in page['links'] if l['rel'] == 'next'), None)
        path = link[len(client.url):] if link else None
    return found

layers = {c['id']: every(c['id']) for c in get(features + '/collections')['collections']}
print({collection: len(found) for collection, found in layers.items()})
for feature in layers['wellbore-paths']:
    if feature['geometry'] is None: print(feature['properties']['name'] + ':', feature['properties']['placement'])
# %% [markdown]
# ## Plan view
# The paths that can be placed, with the tops (when the project has some) as dots. Coordinates are longitude and
# latitude, the layers' default; QGIS asks for another coordinate system with `crs=` when its project uses one.
# %%
fig, ax = plt.subplots(figsize=(5, 5), layout='constrained')
for feature in layers['wellbore-paths']:
    if feature['geometry']:
        xs, ys = zip(*[p[:2] for p in feature['geometry']['coordinates']])
        ax.plot(xs, ys, color='#1f5fa8'); ax.annotate(feature['properties']['name'], (xs[0], ys[0]), fontsize=8)
tops = [f['geometry']['coordinates'] for f in layers.get('tops', []) if f['geometry']]
if tops: ax.scatter([p[0] for p in tops], [p[1] for p in tops], s=8, color='#efc54a', zorder=3)
ax.set_xlabel('Longitude (°)'); ax.set_ylabel('Latitude (°)'); ax.set_title('Wellbore paths, plan view')
fig.savefig('layers-for-a-gis.png', bbox_inches='tight')
plt.close(fig)
print('Wrote layers-for-a-gis.png with', sum(1 for f in layers['wellbore-paths'] if f['geometry']), 'paths placed')
