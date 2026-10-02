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
# your own computer; nothing real is read. To read your project, put the `configuration.json` from Connect → Use Python
# in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then
# set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter.
# %%
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect

client = connect()
# The longest gamma-ray log you may read; to read another, set `log` to its entry in client.assets().
log = max((asset for asset in client.assets() if 'GR' in asset.get('curves', [])), key=lambda asset: asset.get('sample_count') or 0)
data = client.read(log['asset_id'], log['revision'], ['GR'])
curve, descriptor = data.curves[0], data.descriptors[0]
print(log['name'], '-', len(curve.values), 'samples of GR in', curve.unit, 'against depth in', curve.context.depth_unit)
print('Depth reference:', curve.context.depth_reference)
# %% [markdown]
# ## Missing samples stay missing
# A sample the file marks with its NULL value is `None` here, never zero, and a zero stays zero.
# %%
missing = [depth for depth, value in zip(curve.axis, curve.values) if value is None]
assert len(missing) == descriptor.scientific.missing_count
print('Missing samples stay missing:', len(missing), 'of', len(curve.values), 'at', missing, curve.context.depth_unit)
# %% [markdown]
# ## Plot the samples
# The gap in the line is the missing sample, not a measurement of zero.
# %%
fig, axis = plt.subplots(figsize=(4, 5))
axis.plot(curve.values, curve.axis, marker='o')
axis.set_xlabel(f'Gamma ray ({curve.unit})')
axis.set_ylabel(f'Depth ({curve.context.depth_unit})')
axis.invert_yaxis()
fig.savefig('read-a-well-log.png', bbox_inches='tight')
plt.close(fig)
print('Wrote read-a-well-log.png')
