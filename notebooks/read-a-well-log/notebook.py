# %% [markdown]
# # Read a well log
# Read one gamma-ray curve exactly as it was uploaded, with its units and depth reference, and plot it.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it reads a synthetic log served on
# your own computer; nothing real is read. With `ophiolite-mapper` installed as well (`pip install
# "ophiolite-mapper[las]"`), the synthetic log is a LAS file on your computer instead: the mapper turns it into a
# project folder, and the curve is read back from that folder. To read your project, put the `configuration.json` from
# Connect → Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a
# project access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you
# start Jupyter.
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

# A synthetic LAS 2.0 log: five gamma-ray samples, the third marked missing with the file's NULL value.
LAS = ('~Version\nVERS. 2.0 : LAS\nWRAP. NO : one row per depth\n~Well\nSTRT.M 100 : start\nSTOP.M 104 : stop\n'
       'STEP.M 1 : step\nNULL. -999.25 : missing\nWELL. SYNTHETIC-1 : well\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma ray\n'
       '~ASCII\n100 45.2\n101 60.1\n102 -999.25\n103 82.0\n104 75.5\n')
mapped = synthetic() and importlib.util.find_spec('ophiolite_mapper') is not None
if mapped:
    import pyarrow.parquet as pq
    from ophiolite.bundle import open_bundle
    from ophiolite_mapper.cli import main as mapper
    work = Path(tempfile.mkdtemp(prefix='ophiolite-mapper-'))
    (work / 'synthetic.las').write_text(LAS, encoding='utf-8')
    assert mapper(['inspect', str(work / 'synthetic.las'), '--no-reviewed']) == 0
    # Your decisions, written into the recipe: the log's well name is a new wellbore, told apart by its name.
    recipe = json.loads((work / 'recipe.json').read_text(encoding='utf-8'))
    you = {'by': 'Gallery reader', 'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    for row in recipe['wells']: row['decision'] = dict(you, action='new-entity')
    recipe['identity']['decision'] = dict(you, action='accept')
    (work / 'recipe.json').write_text(json.dumps(recipe, indent=2), encoding='utf-8')
    assert mapper(['write', str(work / 'recipe.json'), '--out', str(work / 'folder'), '--no-reviewed']) == 0
    folder = open_bundle(str(work / 'folder'))  # every file the folder lists is checked against its checksum
    rows = [row for row in pq.read_table(work / 'folder/items/well-log.parquet').to_pylist() if row['curve'] == 'GR']
    name, unit, depth_unit, reference = 'synthetic.las', rows[0]['unit'], rows[0]['index_unit'], None
    depths, values = [row['index'] for row in rows], [row['value'] for row in rows]
    missing_count = LAS.split('~ASCII')[1].count('-999.25')
    print('Read back from the project folder:', len(folder.folder), 'files checked, items/well-log.parquet among them')
else:
    client = connect()
    # The longest gamma-ray log you may read; to read another, set `log` to its entry in client.assets().
    log = max((asset for asset in client.assets() if 'GR' in asset.get('curves', [])), key=lambda asset: asset.get('sample_count') or 0)
    data = client.read(log['asset_id'], log['revision'], ['GR'])
    curve, descriptor = data.curves[0], data.descriptors[0]
    name, unit, depth_unit, reference = log['name'], curve.unit, curve.context.depth_unit, curve.context.depth_reference
    depths, values, missing_count = curve.axis, curve.values, descriptor.scientific.missing_count
    if synthetic():
        print('With ophiolite-mapper installed (pip install "ophiolite-mapper[las]"), this log is first made into a project folder on this computer.')
print(name, '-', len(values), 'samples of GR in', unit, 'against depth in', depth_unit)
if not mapped:
    print('Depth reference:', reference)
# %% [markdown]
# ## Missing samples stay missing
# A sample the file marks with its NULL value is `None` here, never zero, and a zero stays zero.
# %%
missing = [depth for depth, value in zip(depths, values) if value is None]
assert len(missing) == missing_count
print('Missing samples stay missing:', len(missing), 'of', len(values), 'at', missing, depth_unit)
# %% [markdown]
# ## Plot the samples
# The gap in the line is the missing sample, not a measurement of zero.
# %%
fig, axis = plt.subplots(figsize=(4, 5))
axis.plot(values, depths, marker='o')
axis.set_xlabel(f'Gamma ray ({unit})')
axis.set_ylabel(f'Depth ({depth_unit})')
axis.invert_yaxis()
fig.savefig('read-a-well-log.png', bbox_inches='tight')
plt.close(fig)
print('Wrote read-a-well-log.png')
