# %% [markdown]
# # Read an exact curve and keep its scientific context
# This example uses synthetic gamma-ray data. Missing samples remain missing;
# zero remains zero. No alignment, conversion or resampling is performed.
# Start with `make dev`. For real data, sign in with `ophiolite login` first.
# %%
import copy
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(os.environ.get('OPHIOLITE_TEMPLATES_ROOT','..')).resolve()))
from support import client_for, guidance
from ophiolite import CurveSet
from ophiolite.errors import AxisMismatch, AuthenticationRequired
from IPython.display import display
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

with client_for(os.environ['OPHIOLITE_URL'],os.environ.get('OPHIOLITE_PROJECT','p'),fixture=os.environ.get('OPHIOLITE_TEMPLATE_FIXTURE')=='1') as client:
    asset=next(client.assets())
    data=client.read(asset['asset_id'],asset['revision'],['GR'])
frame,descriptor=data.to_frame()
display(descriptor)
# %% [markdown]
# ## Plot the original samples
# Depth units and the curve unit come from the descriptor. The gap is a missing
# sample, not a zero measurement. The separate descriptor remains available.
# %%
fig,axis=plt.subplots(figsize=(5,4))
axis.plot(frame['GR'],frame.index,marker='o')
axis.set_xlabel('Gamma ray ('+descriptor.curves['GR'].unit+')')
axis.set_ylabel('Depth ('+descriptor.axis.unit+')')
axis.invert_yaxis()
output=Path(os.environ.get('OPHIOLITE_NOTEBOOK_OUTPUT','.'))
output.mkdir(parents=True,exist_ok=True)
fig.savefig(output/'curve.png',bbox_inches='tight')
display(fig)
plt.close(fig)
print('Every source sample is retained; missing values appear as a gap.')
# %% [markdown]
# ## Refusal examples
# These deliberate local examples show recovery guidance; they do not modify
# the source or revoke a real grant.
# %%
other=copy.deepcopy(data.curves[0]);other.curve='OTHER';other.context.depth_unit='FT'
other_descriptor=copy.deepcopy(data.descriptors[0]);other_descriptor.scientific.curve='OTHER';other_descriptor.scientific.axis_unit='FT'
try:
    CurveSet([data.descriptors[0],other_descriptor],[data.curves[0],other],data.artifact).to_frame()
except AxisMismatch:
    print('The curves use different depth units. Read them separately or align them explicitly.')
try:
    raise AuthenticationRequired('The example credential expired.')
except AuthenticationRequired as error:
    print(guidance(error))
