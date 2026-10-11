# %% [markdown]
# # Open it here
# Publish a result and see it the way a notebook shows it: its name, its version, a link that opens that exact version
# in the Workspace, and a "Send again" line that adds the next version. Run the line twice and get one version; run it
# after someone else added a version and get told so.
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
import html
import re
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite import petrophysics as pp
from ophiolite.errors import OphioliteError
from ophiolite.gallery import connect, synthetic
from ophiolite.writers import write_curves

client = connect()
# The longest gamma-ray log you may build on; to use another, set `log` to its entry in client.assets().
log = max((asset for asset in client.assets() if 'GR' in asset.get('curves', []) and 'use-as-input' in asset.get('allowed_operations', [])),
          key=lambda asset: asset.get('sample_count') or 0)
gr = client.read(log['asset_id'], log['revision'], ['GR']).curves[0]
depth, values, depth_unit = gr.axis, gr.values, gr.context.depth_unit
top, base = depth[0], depth[-1] + (depth[-1] - depth[-2])
METHOD = 'larionov-older'
print(log['name'], '-', len(values), 'samples of GR in', gr.unit)


def shale_file(low, high):
    """A shale-volume file from the 'low' and 'high' percentile picks, and its method record."""
    picks = pp.picks_from_percentiles(depth, values, top, base, low, high, depth_unit=depth_unit)
    volume = pp.shale_volume(values, method=METHOD, clean=picks['clean'], shale=picks['shale'])
    written = write_curves(depth, {'VSH': ('V/V', volume)}, depth_unit=depth_unit, notes=[pp.calculation_record(METHOD, picks, gr.unit, depth_unit)])
    return written, pp.shale_volume_method(method=METHOD, picks=picks, unit=gr.unit), volume
# %% [markdown]
# ## A result shows itself
# The receipt is shown by name and version. "Open in Workspace" opens this exact version; "Copy link" holds the same
# address; "Send again" holds the line that adds the next version; the identifiers are under "Technical details".
# %%
written, method, first_volume = shale_file(5, 95)
first = client.publish_derived(written, name='Shale volume, opened from a notebook', from_=[(log['asset_id'], log['revision'])],
                               method=method, command_id=uuid.uuid4().hex)
first
# %%
card = first._repr_html_()
address = re.search(r'<a href="([^"]+)">Open in Workspace</a>', card).group(1)
print('Version', first.revision_number, 'opens at', html.unescape(address))
assert html.unescape(address) == f'{client.url}/project/{client.project}/data/m~{first.asset_id}?revision={first.revision}'
assert '<p>Version 1</p>' in card and 'Copy link' in card and 'Send again' in card
# %% [markdown]
# ## Send again
# This is the line under "Send again", copied as you would copy it. `new_written` is the new file: here the same
# calculation with the 10th and 90th percentile as picks. The line names the version it builds on and one request id,
# so running it again after a lost answer gives the same version, never a second one.
# %%


def copied(receipt):
    """The text under "Send again" in the receipt's card, as Copy gives it."""
    return html.unescape(re.search(r'<summary>Send again</summary><p>.*?</p><pre>(.*?)</pre>', receipt._repr_html_(), re.S).group(1))


line = copied(first)
print(line[:80] + ' ...')
new_written, _, second_volume = shale_file(10, 90)
second = eval(line)
again = eval(line)
print('Sent again: version', second.revision_number, '- run twice, still version', again.revision_number)
assert (second.asset_id, second.revision_number) == (first.asset_id, 2) and again.revision == second.revision
second
# %% [markdown]
# ## Someone added a version first
# The line from version 2's card builds on version 2. When another version arrives before you run it, it refuses and
# says why; open the result in the Workspace, look at the newer version, and copy that version's line instead.
# %%
line = copied(second)
written, method, _ = shale_file(15, 85)
third = client.publish_derived(written, name='Shale volume, opened from a notebook', from_=[(log['asset_id'], log['revision'])],
                               method=method, command_id=uuid.uuid4().hex, new_version_of=second.asset_id, expected_parent=second.revision)
new_written, _, _ = shale_file(20, 80)
try:
    eval(line)
    raise AssertionError('the line built on version 2 added a version after version 3')
except OphioliteError as error:
    assert error.code == 'revision-conflict', error.code
    print('Version', third.revision_number, 'arrived first; the line built on version 2 was refused:', error.server_message or error)
# %%
fig, axis = plt.subplots(figsize=(4, 5))
axis.plot(first_volume, depth, marker='o', label='version 1 (5th and 95th percentile)')
axis.plot(second_volume, depth, marker='o', label='version 2, sent again (10th and 90th)')
axis.set_xlabel('Shale volume (V/V)'); axis.set_ylabel(f'Depth ({depth_unit})'); axis.set_xlim(0, 1); axis.invert_yaxis(); axis.legend(fontsize='small')
fig.savefig('open-it-here.png', bbox_inches='tight'); plt.close(fig)
print('Wrote open-it-here.png')
