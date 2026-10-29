# %% [markdown]
# # Petrophysical calculations
# Andy McDonald's "Petrophysical Calculations" reading its log from your project: shale volume and density porosity
# with the notebook's own functions, published back as a result that names the exact log version it came from.
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
#
# **Source.** "05 - Petrophysical Calculations" from [Petrophysics-Python-Series](https://github.com/andymcdgeo/Petrophysics-Python-Series)
# at commit `b6bcfb17f026e8b612cf64ed24d408bb69290d4e`, by Andy McDonald, MIT licence (Copyright (c) 2021 Andy
# McDonald). The original reads an interpreted CSV of the Volve well 15/9-19; Volve data is Equinor's, under the
# Equinor Open Data Licence (credit Equinor and the Volve licence partners). This notebook ships no Volve data: it
# reads the longest gamma-ray log in your project.
#
# | Original cell | Here |
# |---|---|
# | imports; `shale_volume`, `density_porosity`, `sw_archie`, `sw_simandoux` and their demo calls | kept |
# | `well = pd.read_csv("Data/15_9-19.csv", header=0, skiprows=[1])` | **changed**: `client.find_log(curves=['GR'], name=LOG_NAME)` and an exact read as a DataFrame |
# | `well.replace(-999.00, np.nan, inplace=True)` | **skipped**: missing samples already read as `NaN` |
# | `head`, `describe`, GR histogram | kept; the histogram is saved as `petrophysical-calculations.png` |
# | VSHALE from the GR 1st and 99th percentiles | kept |
# | PHI and PHIECALC from `RHOB` | kept when the log has bulk density in g/cm3: a `DEN` curve is used as `RHOB` (stated in the output); skipped when it has none or another unit (nothing is converted) |
# | Archie and Simandoux SW, the SW limits, `describe`, the log plot | **skipped**: they need `RT` and `RW` from the original's interpreted CSV; a log holds a measured deep resistivity, and treating it as `RT` with an assumed `RW` would be an interpretation this notebook does not make for you |
# | (new) | publish the computed curves with the method, then read them back and compare |
# %%
import uuid
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.frames import write_frame
from ophiolite.gallery import connect, synthetic

client = connect()
# %%
def shale_volume(gamma_ray, gamma_ray_max, gamma_ray_min):
    vshale = (gamma_ray - gamma_ray_min) / (gamma_ray_max - gamma_ray_min)
    return round(vshale, 4)
# %%
shale_volume(120, 200, 15)
# %%
def density_porosity(input_density, matrix_density, fluid_density):
    denpor = (matrix_density - input_density) / (matrix_density - fluid_density)
    return round(denpor, 4)
# %%
density_porosity(2.45, 2.65, 1)
# %%
def sw_archie(porosity, rt, rw, archieA, archieM, archieN):
    sw = ((archieA / (porosity ** archieM)) * (rw/rt))**(1/archieN)
    return sw
# %%
sw_archie(0.1, 10, 0.1, 1, 2, 2)
# %%
# equations from https://www.spec2000.net/01-quickmath.htm
def sw_simandoux(phie, rt, rw, archieA, archieM, archieN, vshale, rshale):
    A = (1 - vshale) * archieA * rw / (phie ** archieM)
    B = A * vshale / (2 * rshale)
    C = A / rt

    sw = ((B **2 + C)**0.5 - B) **(2 / archieN)
    return sw
# %%
sw_simandoux(0.1, 10, 0.1, 1, 2, 2, 0.3, 2)
# %%
# was: well = pd.read_csv("Data/15_9-19.csv", header=0, skiprows=[1])
LOG_NAME = None  # None: the longest log with GR you may use; or the exact name of the log to read
log = client.find_log(curves=['GR'], name=LOG_NAME)
wanted = [c for c in ('GR', 'RHOB', 'DEN') if c in log['curves']]
data = client.read(log['asset_id'], log['revision'], wanted)  # the exact version
well, meta = data.to_frame()  # missing samples are NaN
units = {curve.curve: curve.unit for curve in data.curves}
density = next((c for c in ('RHOB', 'DEN') if c in well and units[c].lower().replace(' ', '') in ('g/cm3', 'g/cc')), None)
if density is None and {'RHOB', 'DEN'} & set(well):
    print('Bulk density is not in g/cm3; the porosity cells need g/cm3 and nothing is converted')
    well = well.drop(columns=[c for c in ('RHOB', 'DEN') if c in well])
elif density == 'DEN':
    well['RHOB'] = well.pop('DEN')
    print('Bulk density: the DEN curve (g/cm3) is used as RHOB')
print(log['name'], '- version', log['revision'][:12], '-', len(well), 'samples of', wanted, '- depth in', meta.axis.unit)
# %%
well.head()
# %%
well.describe()
# %%
fig, ax = plt.subplots()
well['GR'].plot(kind='hist', bins=230, ax=ax)
plt.xlim(0, 250)
fig.savefig('petrophysical-calculations.png', bbox_inches='tight')
plt.close(fig)
print('Wrote petrophysical-calculations.png')
# %%
#Calculate Shale Volume
well['VSHALE'] = shale_volume(well['GR'], well['GR'].quantile(q=0.99),
                             well['GR'].quantile(q=0.01))
print('GR P99', round(well['GR'].quantile(q=0.99), 6), '- P01', round(well['GR'].quantile(q=0.01), 6))
# %%
if 'RHOB' in well:
    #Calculate density porosity
    well['PHI'] = density_porosity(well['RHOB'], 2.65, 1)
    #Calculate PHIE
    well['PHIECALC'] = well['PHI'] - (well['VSHALE'] * 0.3)
else:
    print('Skipped PHI and PHIECALC: this log has no bulk density (RHOB or DEN)')
print('Skipped SW (Archie, Simandoux): RT and RW are interpretation inputs this log does not carry')
# %%
well.head(10)
# %% [markdown]
# ## Publish the computed curves
# The result names the exact log version it was computed from and the method as declared here: the notebook's
# functions, the percentiles and the densities. Nothing else is claimed about how it was made.
# %%
outputs = {'VSHALE': 'v/v', **({'PHI': 'v/v', 'PHIECALC': 'v/v'} if 'PHI' in well else {})}
written = write_frame(well[list(outputs)], outputs, depth_unit=meta.axis.unit,
                      notes=['Petrophysics-Python-Series 05 (Andy McDonald, MIT): linear VSHALE from GR P01/P99, density porosity 2.65/1.0'])
method = {'name': 'Petrophysical calculations (Petrophysics-Python-Series 05)', 'declared': True,
          'parameters': {'vshale': {'gamma_ray_min': 'GR P01', 'gamma_ray_max': 'GR P99', 'rounded': 4},
                         **({'density_porosity': {'matrix_density': 2.65, 'fluid_density': 1.0}, 'phie': {'shale_factor': 0.3}} if 'PHI' in well else {}),
                         'outputs': {name: {'unit': unit} for name, unit in outputs.items()}}}
receipt = client.publish_derived(written, name='Petrophysical calculations', from_=[(log['asset_id'], log['revision'])],
                                 method=method, command_id=uuid.uuid4().hex)
print('Published', receipt.asset_id[:12], 'version', receipt.revision_number)
# %%
result = client.read(receipt.asset_id, receipt.revision, list(outputs))
parents = result.descriptors[0].model_dump(by_alias=True)['parents']
print('from:', parents)
back, _ = result.to_frame()
pd.testing.assert_frame_equal(back, well[list(outputs)], check_names=False, check_index_type=False)
print('Read back equals the computed curves, sample for sample, missing where they are missing:', int(back['VSHALE'].isna().sum()))
print('Open it in the Workspace:', result.workspace_url())
if synthetic():  # the synthetic log's values, worked by hand: GR 0, 10, -, 30, 40 with P01 0.3 and P99 39.7
    assert back['VSHALE'].tolist()[:2] == [-0.0076, 0.2462] and back['VSHALE'].tolist()[3:] == [0.7538, 1.0076], back['VSHALE'].tolist()
    print('Synthetic mode: published to the synthetic server on this computer only.')
