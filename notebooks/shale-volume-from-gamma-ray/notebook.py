# %% [markdown]
# # Shale volume from gamma ray
# Pick clean and shale values from a gamma-ray log, compare the five methods Ophiolite lists, publish one result with
# its method and picks recorded, read it back, and add a second version with a changed pick.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it works on a synthetic log served on
# your own computer; nothing real is read or published. To work in your project, run
# `ophiolite login --url <address> --project <project>` and set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` before you
# start Jupyter. Publishing there creates a result that only you can see until you share it.
# %%
import math
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite import petrophysics as pp
from ophiolite.gallery import connect, synthetic
from ophiolite.writers import write_curves

client = connect()
log = next(asset for asset in client.assets() if 'GR' in asset.get('curves', []))
gr = client.read(log['asset_id'], log['revision'], ['GR']).curves[0]
depth, values, depth_unit = gr.axis, gr.values, gr.context.depth_unit
print(log['name'], '-', len(values), 'samples of GR in', gr.unit)
# %% [markdown]
# ## Clean and shale values from percentiles
# The clean value is the 5th percentile and the shale value the 95th percentile of the samples in the interval
# [top, base); missing samples are left out. Here the interval is the whole log.
# %%
top, base = depth[0], depth[-1] + (depth[-1] - depth[-2])
picks = pp.picks_from_percentiles(depth, values, top, base, depth_unit=depth_unit)
print(f"clean {picks['clean']} {gr.unit}, shale {picks['shale']} {gr.unit}, from {picks['samples']} samples")
# %% [markdown]
# ## Five methods side by side
# Every method starts from the same gamma-ray index, clipped to 0-1; they differ in how they bend it.
# %%
curves = {method: pp.shale_volume(values, method=method, clean=picks['clean'], shale=picks['shale']) for method in pp.METHODS}
means = {}
for method, volume in curves.items():
    present = [v for v in volume if v is not None]
    means[method] = round(math.fsum(present) / len(present), 6)
    print(f'{pp.LABELS[method]:<32} mean {means[method]:.6f}')
missing = [i for i, g in enumerate(values) if g is None]
assert all(curves[method][i] is None for method in pp.METHODS for i in missing)
print('Missing samples stay missing:', len(missing), 'of', len(values))
if synthetic():  # the synthetic log's means, worked by hand from the published constants
    assert means == {'linear': 0.5, 'larionov-tertiary': 0.394427, 'larionov-older': 0.435935, 'clavier': 0.427542, 'steiber': 0.404551}, means
# %%
fig, axis = plt.subplots(figsize=(5, 5))
for method, volume in curves.items():
    axis.plot(volume, depth, marker='o', label=pp.LABELS[method])
axis.set_xlabel('Shale volume (V/V)')
axis.set_ylabel(f'Depth ({depth_unit})')
axis.set_xlim(0, 1)
axis.invert_yaxis()
axis.legend(fontsize='small')
fig.savefig('shale-volume-from-gamma-ray.png', bbox_inches='tight')
plt.close(fig)
print('Wrote shale-volume-from-gamma-ray.png')
# %% [markdown]
# ## Publish one method
# The file carries the calculation in its `~Other` section; the result records the method, the picks, the method
# table's digest and the exact parent revision.
# %%
METHOD = 'larionov-older'


def publish(picks, **version):
    volume = pp.shale_volume(values, method=METHOD, clean=picks['clean'], shale=picks['shale'])
    written = write_curves(depth, {'VSH': ('V/V', volume)}, depth_unit=depth_unit,
                           notes=[pp.calculation_record(METHOD, picks, gr.unit, depth_unit)])
    method = pp.shale_volume_method(method=METHOD, picks=picks, unit=gr.unit)
    receipt = client.publish_derived(written, name='Shale volume, Larionov older rocks', from_=[(log['asset_id'], log['revision'])],
                                     method=method, command_id=uuid.uuid4().hex, **version)
    return receipt, method


def derivation(receipt):
    descriptor = client.read(receipt.asset_id, receipt.revision, ['VSH']).descriptors[0].model_dump(by_alias=True)
    return descriptor['derivation']['method'], descriptor['parents']


first, first_method = publish(picks)
recorded, parents = derivation(first)
print('Published', first.asset_id[:12], 'version', first.revision_number)
print('method:', recorded['parameters']['method'], '- picks:', recorded['parameters']['picks'])
print('from:', parents)
assert recorded['parameters'] == first_method['parameters']
# %% [markdown]
# ## A changed pick is a new version of the same result
# Moving the picks to the 10th and 90th percentile adds version 2. Version 1 is kept, with its own picks.
# %%
changed = pp.picks_from_percentiles(depth, values, top, base, 10, 90, depth_unit=depth_unit)
second, second_method = publish(changed, new_version_of=first.asset_id, expected_parent=first.revision)
history = client.history(second).revisions
assert second.asset_id == first.asset_id
assert second.revision != first.revision
assert [(row.number, row.revision) for row in history] == [(1, first.revision), (2, second.revision)]
for receipt, method in ((first, first_method), (second, second_method)):
    assert derivation(receipt)[0]['parameters'] == method['parameters']
for row in history:
    print(f'version {row.number}: {row.revision[:12]}', derivation(first if row.number == 1 else second)[0]['parameters']['picks'])
