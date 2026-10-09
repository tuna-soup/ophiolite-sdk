# %% [markdown]
# # How was this made
# Publish a shale-volume result and a second version with changed picks, then ask Ophiolite how each version was made,
# what changed between them, what was made from the log, and whether the result can be made again.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it works on a synthetic log served on
# your own computer; nothing real is read or published. To work in your project, put the `configuration.json` from
# Connect → Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a
# project access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you
# start Jupyter. Publishing there creates a result that only you can see until you share it.
# %%
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite import petrophysics as pp
from ophiolite import story
from ophiolite.cli import changed_lines
from ophiolite.errors import OphioliteError
from ophiolite.gallery import connect, synthetic
from ophiolite.writers import write_curves

client = connect()
# The longest gamma-ray log you may build on; to use another, set `log` to its entry in client.assets().
log = max((asset for asset in client.assets() if 'GR' in asset.get('curves', []) and 'use-as-input' in asset.get('allowed_operations', [])),
          key=lambda asset: asset.get('sample_count') or 0)
gr = client.read(log['asset_id'], log['revision'], ['GR']).curves[0]
depth, values, depth_unit = gr.axis, gr.values, gr.context.depth_unit
print(log['name'], '-', len(values), 'samples of GR in', gr.unit)
# %% [markdown]
# ## Two versions of one result
# Version 1 uses the 5th and 95th percentile as clean and shale values, version 2 the 10th and 90th. Each version
# records its method and picks; that record is what the rest of this notebook reads.
# %%
METHOD = 'larionov-older'
top, base = depth[0], depth[-1] + (depth[-1] - depth[-2])


def publish(picks, **version):
    volume = pp.shale_volume(values, method=METHOD, clean=picks['clean'], shale=picks['shale'])
    written = write_curves(depth, {'VSH': ('V/V', volume)}, depth_unit=depth_unit, notes=[pp.calculation_record(METHOD, picks, gr.unit, depth_unit)])
    receipt = client.publish_derived(written, name='Shale volume, made in a notebook', from_=[(log['asset_id'], log['revision'])],
                                     method=pp.shale_volume_method(method=METHOD, picks=picks, unit=gr.unit), command_id=uuid.uuid4().hex, **version)
    return receipt, volume


first, first_volume = publish(pp.picks_from_percentiles(depth, values, top, base, depth_unit=depth_unit))
second, second_volume = publish(pp.picks_from_percentiles(depth, values, top, base, 10, 90, depth_unit=depth_unit),
                                new_version_of=first.asset_id, expected_parent=first.revision)
print('Published version', first.revision_number, 'and version', second.revision_number)
fig, axis = plt.subplots(figsize=(4, 5))
axis.plot(first_volume, depth, marker='o', label='version 1 (5th and 95th percentile)')
axis.plot(second_volume, depth, marker='o', label='version 2 (10th and 90th percentile)')
axis.set_xlabel('Shale volume (V/V)'); axis.set_ylabel(f'Depth ({depth_unit})'); axis.set_xlim(0, 1); axis.invert_yaxis(); axis.legend(fontsize='small')
fig.savefig('how-was-this-made.png', bbox_inches='tight'); plt.close(fig)
print('Wrote how-was-this-made.png')
# %% [markdown]
# ## How version 2 was made
# The story of an exact version: who made it and how, its settings, and its inputs with their own stories. Ophiolite
# did not run this calculation (the notebook did and reported it), so the story says so. `story.lines` prints the page
# the way `ophiolite story` and the Workspace show it; the identifiers are under `technical` in each node.
# %%
page = client.story(second.asset_id, second.revision)
print('\n'.join(story.lines(page)))
kinds = [node['kind'] for node in page['nodes']]
assert kinds[0] == 'declared' and page['nodes'][0]['version'] == 2 and len(page['nodes'][0]['inputs']) == 1
if synthetic(): assert kinds == ['declared', 'original'], kinds
# %% [markdown]
# ## What changed between version 1 and version 2
# %%
changed = client.what_changed((first.asset_id, first.revision), (second.asset_id, second.revision))
print('\n'.join(changed_lines(changed)))
assert changed['inputs_same'] and changed['settings'], 'the picks changed; the input did not'
# %% [markdown]
# ## What was made from the log
# Every result made from this exact log version that you may open; a result you cannot open is not named.
# %%
below = client.dependents(log['asset_id'], log['revision'])
print('\n'.join(story.lines(below)))
assert any(node['asset_id'] == second.asset_id for node in below['nodes'])
# %% [markdown]
# ## Making it again
# Ophiolite makes a result again only when it ran the calculation itself (for example a shale volume made in the
# Workspace); a result whose method was reported by its publisher is refused with the reason.
# %%
try:
    client.remake(second.asset_id, second.revision)
    print('This result can be made again: run `ophiolite remake` to compare.')
except OphioliteError as refused:
    print(refused)
    assert 'did not run this calculation' in refused.message
