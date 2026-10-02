# %% [markdown]
# # Make a wedge model
# Take two rocks from a well log, build a wedge of one inside the other, compute its synthetic seismic section with a
# 30 Hz Ricker wavelet, and read off the tuning thickness. In your project, publish the model, the wavelet and the
# synthetic, each recording what it was made from.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it uses the rock values measured on
# the HON-GT-01 excerpt (NLOG.NL, well HONSELERSDIJK-GT-01) and publishes nothing. To work in your project, put the
# `configuration.json` from Connect → Use Python in this folder and run `ophiolite login` here (or
# `ophiolite login --key-stdin` to paste a project access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the
# address and project it names before you start Jupyter. The project needs the HON-GT-01 log with DT and RHOB; the
# notebook recomputes the rock values from it. Publishing there creates results only you can see until you share them.
# %%
import statistics
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic
from ophiolite.synthetics import ricker, synthetic as convolve_model, tuning_thickness, wedge
from ophiolite.typed import ModelSection, SeismicSection, Wavelet

client = connect()
# Two intervals of HON-GT-01, each [top, base) in metres: a claystone above a sandstone.
INTERVALS = {'Rodenrijs Claystone': (2480.0, 2557.9), 'Delft Sandstone': (2557.9, 2620.22)}
# %% [markdown]
# ## Two rocks from the log
# For each interval, the median P-wave velocity (304800 / DT, with DT in us/ft) and the median density (RHOB) of the
# rows where both are present, rounded to whole m/s and kg/m3.
# %%
if synthetic():
    log = None
    rocks = [{'name': 'Rodenrijs Claystone', 'vp': 4073.0, 'density': 2629.0}, {'name': 'Delft Sandstone', 'vp': 4024.0, 'density': 2379.0}]
    print('Rock values measured on the HON-GT-01 excerpt (779 and 624 rows):')
else:
    log = next(asset for asset in client.assets() if {'DT', 'RHOB'} <= set(asset.get('curves', [])) and 'use-as-input' in asset.get('allowed_operations', []))
    dt, rhob = client.read(log['asset_id'], log['revision'], ['DT', 'RHOB']).curves
    assert dt.unit.lower() == 'us/ft' and rhob.unit.lower() in ('g/cm3', 'g/cc'), (dt.unit, rhob.unit)
    rows = [(d, 304800 / s, r * 1000) for d, s, r in zip(dt.axis, dt.values, rhob.values) if s is not None and r is not None]
    rocks, counts = [], []
    for name, (top, base) in INTERVALS.items():
        inside = [(vp, rho) for d, vp, rho in rows if top <= d < base]
        counts.append(len(inside))
        rocks.append({'name': name, 'vp': float(round(statistics.median(v for v, _ in inside))), 'density': float(round(statistics.median(r for _, r in inside)))})
    print('Rows used per interval:', counts)
    assert counts == [779, 624], counts  # the HON-GT-01 log
for rock in rocks:
    print(f"{rock['name']:<22} {rock['vp']:.0f} m/s {rock['density']:.0f} kg/m3")
# %% [markdown]
# ## The wedge and its synthetic
# 200 samples every 1 ms of two-way time and 61 traces every 25 m: trace i holds i samples of sandstone from 80 ms.
# Each trace's reflection coefficients are convolved with the wavelet; nothing is resampled.
# %%
model = wedge(rocks)
wavelet = ricker(30, 0.001, duration=0.128)
section = convolve_model(model, wavelet)
tuning = tuning_thickness(section)
metres = tuning.thickness * rocks[1]['vp'] / 2
print(f'Tuning thickness: {tuning.thickness * 1000:.0f} ms two-way time (trace {tuning.trace}, {metres:.1f} m at {rocks[1]["vp"]:.0f} m/s)')
assert tuning.trace == 13
# %%
fig, (left, middle, right) = plt.subplots(1, 3, figsize=(13, 4), layout='constrained')
extent = [0, 1500, 199, 0]
left.imshow(model.grid, aspect='auto', extent=extent, cmap='Pastel1')
left.set_title('Rock model')
middle.imshow(section.grid, aspect='auto', extent=extent, cmap='RdBu', vmin=-0.1, vmax=0.1)
middle.set_title('Synthetic, 30 Hz Ricker')
for axis in (left, middle):
    axis.set_xlabel('Distance (m)')
    axis.set_ylabel('Two-way time (ms)')
right.plot([max(abs(row[t]) for row in section.grid) for t in range(61)])
right.axvline(tuning.trace, linestyle='--', color='grey')
right.set_xlabel('Wedge thickness (ms)')
right.set_ylabel('Largest absolute amplitude')
right.set_title(f'Tuning at {tuning.thickness * 1000:.0f} ms')
fig.savefig('make-a-wedge-model.png', bbox_inches='tight')
plt.close(fig)
print('Wrote make-a-wedge-model.png')
# %% [markdown]
# ## Publish the model, the wavelet and the synthetic
# The model records the log it was measured from, the synthetic its model and wavelet at their exact versions.
# %%
if synthetic():
    print('Synthetic mode: nothing is published. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to publish in your project.')
else:
    made = client.publish_derived(ModelSection.write(model), name='Wedge model, ' + ' and '.join(r['name'] for r in rocks),
                                  from_=[(log['asset_id'], log['revision'])], method=model.method, command_id=uuid.uuid4().hex)
    uploaded = client.upload_data(Wavelet.write(wavelet).bytes, profile='wavelet-text/1', name='Ricker 30 Hz', filename='ricker-30.txt',
                                  attribution='Computed with ophiolite.synthetics', audience=[], rights_confirmed=True, command_id=uuid.uuid4().hex)
    published = client.publish_derived(SeismicSection.write(section), name='Wedge synthetic, 30 Hz Ricker', method=section.method,
                                       from_=[(made.asset_id, made.revision), (uploaded.asset_id, uploaded.revision)], command_id=uuid.uuid4().hex)
    read = client.read_data(published.asset_id, published.revision)
    assert read.grid == section.grid and read.origin == 'synthetic' and tuning_thickness(read).trace == 13
    print('Published', published.asset_id[:12], 'made from model', made.asset_id[:12], 'and wavelet', uploaded.asset_id[:12])
