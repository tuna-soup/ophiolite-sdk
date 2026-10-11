# %% [markdown]
# # Production decline of one field
# Read a field's monthly oil production as a series, see which months have no figure, and fit an exponential decline
# over a stated window. The figures stay exact decimals until the fit asks for floats.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL`, a synthetic field made on your
# computer is used and nothing is read from a server. To work in your project, put the `configuration.json` from
# Connect → Use Python in this folder and run `ophiolite login` here. Then, before you start Jupyter, set
# `OPHIOLITE_URL`, `OPHIOLITE_PROJECT` and `OPHIOLITE_SERIES_SOURCE` (the id of your selection of the table, from
# `ophiolite sources list`). Also set `OPHIOLITE_SERIES_NAME` when the table has more than one series.
# %%
import math
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from ophiolite.gallery import connect, synthetic
from ophiolite.series import Series

client = connect()
if synthetic():
    # A synthetic field, not a real one: 52,000 a month declining by 2.6 % a month from January 2014, with a
    # wobble of 8 %, January 2014 reported without a figure, and four months shut in (zero).
    SHUT_IN = {'2018-09', '2019-05', '2019-06', '2025-05'}
    points = [{'t': '2014-01-01', 's': 'reported-gap'}]
    for i in range(1, 144):
        month = '%d-%02d' % (2014 + i // 12, i % 12 + 1)
        value = 0 if month in SHUT_IN else round(52000 * math.exp(-0.026 * i) * (1 + 0.08 * math.sin(i)))
        points.append({'t': month + '-01', 'v': str(value)})
    view = {'schema': 'ophiolite.series-view/1', 'name': 'Synthetic field - Oil', 'subject': {'kind': 'asset', 'asset_id': 'made-here'},
            'table_revision': 'made-here', 'declaration_version': None, 'declaration_digest': '0' * 64, 'kind': 'volume', 'unit': 'Not stated',
            'zone': 'Not stated', 'period': 'month', 'about': {'kind': 'name', 'text': 'Synthetic field'}, 'column': 'value',
            'range': {'from': '2014-01', 'to': '2025-12'}, 'rows': {'read': 144, 'kept': 144, 'outside_range': 0},
            'counts': {'figures': sum('v' in p for p in points), 'reported_gaps': sum('s' in p for p in points), 'absent': 0}, 'points': points}
    series = Series({'view': view, 'revision': 'made-here'})
else:
    source = client.source(os.environ['OPHIOLITE_SERIES_SOURCE'])
    series = source.series(os.environ.get('OPHIOLITE_SERIES_NAME') or source.series_list()[0]['name'])
print(series)
print(series.counts)
# %% [markdown]
# ## Months without a figure
# A month the source reports without a figure, or has no row for, is a gap. A gap is never drawn as zero, and a total
# across it is refused unless you ask for the months that have figures.
# %%
frame = series.to_frame()
print('Gaps:', [(str(t.date())[:7], s) for t, s in frame['state'].items() if s != 'figure'])
unit = 'unit not stated' if series.unit == 'Not stated' else series.unit
total = series.total(allow_gaps=True)
print('Total of the months with figures:', total, unit, '(partial: months without a figure are left out)' if total.partial else '')
print('By calendar year:', series.by('year'))
# %% [markdown]
# ## Fit an exponential decline over a stated window
# The window is January 2016 to December 2025, and t counts months from January 2016. Months with a figure of zero
# (the field was shut in) are left out of the fit, and the notebook says which. The fit is a straight line through the
# logarithm of the figures (least squares with numpy), so q = qi · exp(−D · t).
# %%
window = frame.loc['2016-01-01':'2025-12-01']
used = window[(window['state'] == 'figure') & (window['value'] > 0)]
print(f'{len(used)} of {len(window)} months fitted; left out (zero): {[str(t.date())[:7] for t in window.index.difference(used.index)]}')
t = np.array([(d.year - 2016) * 12 + d.month - 1 for d in used.index], dtype=float)
q = series.to_frame(values='float')['value'].loc[used.index].to_numpy()
slope, intercept = np.polyfit(t, np.log(q), 1)
qi, d = float(np.exp(intercept)), float(-slope)

def exponential(t):
    return qi * np.exp(-d * t)

rmse = float(np.sqrt(np.mean((exponential(t) - q) ** 2)))
print(f'Exponential (log-linear): qi {qi:,.1f}, D {d:.5f}/month, RMSE {rmse:,.1f}, q(2025-12) {exponential(119.0):,.1f}')
fig, ax = plt.subplots(figsize=(7, 4), layout='constrained')
ax.plot(used.index, q, 'o', markersize=3, label='Monthly figure')
ax.plot(window.index, exponential(np.arange(len(window), dtype=float)), label='Exponential')
ax.set_ylabel('Oil per month (%s)' % unit)
ax.set_title(series.name)
ax.legend()
fig.savefig('production-decline.png', bbox_inches='tight')
plt.close(fig)
print('Wrote production-decline.png')
