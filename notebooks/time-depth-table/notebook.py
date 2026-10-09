# %% [markdown]
# # Write a time-depth table
# Compute the two-way times of a two-layer velocity model, check the interval velocities, write the table as a
# time-depth CSV with its declarations, and, in your project, upload it and read it back pair for pair.
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
# there creates a table that only you can see until you share it.
# %%
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic
from ophiolite.writers import write_time_depth

client = connect()
# Two layers: 2000 m/s down to 1000 m true vertical depth, 3000 m/s below. Two-way time in milliseconds.
def two_way_ms(depth):
    return 2000 * (min(depth, 1000) / 2000 + max(depth - 1000, 0) / 3000)

pairs = [(depth, round(two_way_ms(depth), 3)) for depth in range(0, 2001, 50)]
print(f'{len(pairs)} pairs, from {pairs[0]} to {pairs[-1]}')
# %% [markdown]
# ## Interval velocities
# Between two pairs the interval velocity is twice the depth step over the two-way time step. They are read from the
# rounded times, so they are the model's velocities to within the rounding.
# %%
interval = [2 * (d2 - d1) / ((t2 - t1) / 1000) for (d1, t1), (d2, t2) in zip(pairs, pairs[1:])]
print('Interval velocities (m/s, rounded):', sorted({round(v) for v in interval}))
assert sorted({round(v) for v in interval}) == [2000, 3000]
fig, ax = plt.subplots(figsize=(4, 5), layout='constrained')
ax.plot([t for _, t in pairs], [d for d, _ in pairs])
ax.invert_yaxis()
ax.set_xlabel('Two-way time (ms)')
ax.set_ylabel('True vertical depth (m)')
ax.set_title('Two-layer model')
fig.savefig('time-depth-table.png', bbox_inches='tight')
plt.close(fig)
print('Wrote time-depth-table.png')
# %% [markdown]
# ## Write it with its declarations
# A time-depth table does not say what its numbers mean, so every declaration is given: depth type and unit, time
# kind and unit ("unknown" is allowed and stays unknown). Depth and time must both increase.
# %%
written = write_time_depth(pairs, depth_type='tvd', depth_unit='m', time_kind='two-way', time_unit='ms')
lines = written.bytes.decode().splitlines()
print(written.profile, written.declared)
print(lines[0], lines[1], lines[-1])
# %% [markdown]
# ## Upload it and read it back
# The table you read back is the file you wrote, pair for pair, with your declarations.
# %%
if synthetic():
    print('Synthetic mode: nothing is published. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to upload in your project.')
else:
    receipt = client.upload_data(written.bytes, filename='two-layer-time-depth.csv', profile=written.profile, declared=written.declared,
                                 name='Two-layer time-depth table', attribution='Computed in the gallery notebook', audience=[],
                                 rights_confirmed=True, command_id=uuid.uuid4().hex)
    table = client.read_data(receipt.asset_id, receipt.revision)
    assert [pair[:2] for pair in table.pairs] == pairs and table.original == written.bytes
    print(table, receipt.revision[:12])
