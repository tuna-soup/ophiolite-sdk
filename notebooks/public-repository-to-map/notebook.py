# %% [markdown]
# # Wells from NLOG on a map
# Search NLOG, the Dutch oil and gas portal, for wells, see what it holds for each one, bring their positions into your
# project and draw them on a map. NLOG's data is public: you may copy, process and share it if you name NLOG.NL as the
# source, and Ophiolite adds that line to everything it brings in.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it draws what NLOG listed for the
# HON-GT wells on 1 October 2026 (Source: NLOG.NL) and sends nothing. To work in your project, put the
# `configuration.json` from Connect → Use Python in this folder and run `ophiolite login` here; then set `OPHIOLITE_URL`
# and `OPHIOLITE_PROJECT` to the address and project it names, and optionally `OPHIOLITE_NLOG_SEARCH` (default `HON-GT`),
# before you start Jupyter. Bringing wells in needs a project administrator and an installation that has switched NLOG on.
# %%
import os
import matplotlib
import matplotlib.ticker
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic

client = connect()
SEARCH = os.environ.get('OPHIOLITE_NLOG_SEARCH', 'HON-GT')
here = synthetic()
# What NLOG listed for HON-GT on 1 October 2026: the position recorded when each well was submitted (Dutch RD, metres),
# its formation tops and its deviation survey stations (Source: NLOG.NL, Dutch subsurface portal).
LISTED = {'HON-GT-01': (75242.83, 448081.04, 24, 67), 'HON-GT-01-S1': (75242.83, 448081.04, 4, 27),
          'HON-GT-01-S2': (75242.83, 448081.04, 5, 22), 'HON-GT-02': (75235.07, 448079.08, 23, 134)}

if here:
    codes = [code for code in LISTED if code.startswith(SEARCH)]
    positions = {code: LISTED[code][:2] for code in codes}
    print(f'Synthetic mode: nothing is sent. NLOG listed {len(codes)} wells for {SEARCH}:')
    for code in codes:
        x, y, tops, stations = LISTED[code]
        print(f'  {code}: position ({x}, {y}, Dutch RD) · {tops} formation tops · 1 deviation survey ({stations} stations)')
else:
    wells = client.public_repositories.search('nlog', name=SEARCH)
    codes = [well['code'] for well in wells]
    print(f'NLOG lists {len(codes)} wells for {SEARCH}:')
    positions = {}
    for item in client.public_repositories.preview('nlog', codes):
        position = item.get('position')
        if position and position['crs'] == 'EPSG:28992':
            positions[item['code']] = (position['x'], position['y'])
        print(f"  {item['code']}: {'position (%s, %s)' % (position['x'], position['y']) if position else 'no position'}"
              f"{' · already in this project' if item['in_project'] else ''}")
# %% [markdown]
# ## Bring the positions in
# Only the positions come in here (`include=["location"]`); the wells are created and named by NLOG's own code, never
# matched by name. Nobody else can read them until you share them. Ophiolite creates wells, not wellbores, from NLOG,
# so NLOG tops and well paths appear in QGIS only for a well that already has a wellbore.
# %%
if here:
    print(f'Synthetic mode: in your project the {len(codes)} wells would be added at these positions, each with the line "Source: NLOG.NL".')
    added = len(codes)
else:
    report = client.public_repositories.bring_in('nlog', codes, include=['location'], audience=[])
    print(report.text())
    added = sum(1 for row in report.rows() if row['result'] in ('Added', 'Already here'))
fig, axis = plt.subplots(figsize=(5, 4))
for i, (code, (x, y)) in enumerate(positions.items()):
    axis.plot(x, y, 'o', color='#5b7f6e')
    axis.annotate(code, (x, y), textcoords='offset points', xytext=(6, 10 * i - 15), fontsize=7)  # wells from one site, labels apart
axis.set_xlabel('Easting (m, Dutch RD)'); axis.set_ylabel('Northing (m, Dutch RD)')
axis.set_title(f'{SEARCH}: {len(positions)} wells (Source: NLOG.NL)')
axis.ticklabel_format(useOffset=False, style='plain'); axis.margins(0.35)
axis.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4)); axis.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
fig.savefig('public-repository-to-map.png', bbox_inches='tight')
plt.close(fig)
print('Wrote public-repository-to-map.png')
