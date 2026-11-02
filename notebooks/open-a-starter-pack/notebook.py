# %% [markdown]
# # Open a starter pack
# Read the seismic and well files of a starter pack you downloaded, draw one inline with the wells on it (and its first 2D line, when it holds lines), and check what you read against the values the pack was built with.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     pip install "ophiolite[pack]"
#     python -m ipykernel install --user --name ophiolite-gallery
#
# This notebook installs segyio (LGPL-3.0) through the `pack` extra; nothing else in Ophiolite needs it.
#
# Set `OPHIOLITE_PACK` to the folder of a starter pack you downloaded, then open the notebook with the
# `ophiolite-gallery` kernel. It reads that folder only: it needs no network and no Ophiolite project, and it blocks
# the network of its own kernel before it reads anything.
# %%
import csv
import json
import math

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from ophiolite.gallery import pack

folder = pack()  # the network is blocked from here on
files = folder / 'files'
expected = json.loads((files / 'targets/python/expected.json').read_text())
print('Starter pack:', folder)
print('Cube', expected['cube'], 'inline', expected['inline'], '-', len(expected['wells']), 'wells', '-', len(expected.get('lines', [])), '2D lines')
# %% [markdown]
# ## The cube and its grid
# segyio reads the inline and crossline numbers and the CDP coordinates from each trace header. A plane fitted through
# those coordinates turns any map position into inline and crossline numbers. A pack of 2D lines may hold no cube;
# its wells are then read without inline and crossline.
# %%
import lasio
import segyio

FLAT = "The cube's corners do not span an area; the Python target cannot place wells on it."
field = segyio.TraceField
inline = expected['inline']
if expected['cube']:
    with segyio.open(str(files / expected['cube']), iline=189, xline=193) as cube:
        rows = []
        for header in cube.header:
            scalar = header[field.SourceGroupScalar]
            scale = 1 / -scalar if scalar < 0 else (scalar or 1)
            rows.append((header[field.INLINE_3D], header[field.CROSSLINE_3D], header[field.CDP_X] * scale, header[field.CDP_Y] * scale))
        section = np.asarray(cube.iline[inline], dtype=np.float32)  # one row per crossline
        crosslines = [int(c) for c in cube.xlines]
        times = [float(t) for t in cube.samples]
    grid = np.array(rows, dtype=float)
    x0, y0 = grid[0, 2], grid[0, 3]
    plane = np.column_stack([grid[:, 2] - x0, grid[:, 3] - y0, np.ones(len(grid))])
    fit, _, rank, _ = np.linalg.lstsq(plane, grid[:, :2], rcond=None)
    if rank < 3: raise ValueError(FLAT)
    print('Inline', inline, ':', len(crosslines), 'crosslines from', crosslines[0], 'to', crosslines[-1], 'and', len(times), 'samples from', times[0], 'to', times[-1], 'ms')
else:
    print('No cube:', expected['not_computed'])


def lines(x, y):
    """(inline, crossline) of the map position (x, y); (None, None) without a cube."""
    if not expected['cube']: return None, None
    il, xl = np.array([x - x0, y - y0, 1.0]) @ fit
    return float(il), float(xl)


# %% [markdown]
# ## The wells
# Each well's first station, from its positions file, placed on the cube's lines; its log, where the pack holds one.
# %%
wells = []
for well in expected['wells']:
    with open(files / well['positions'], newline='') as handle:
        first = next(csv.DictReader(handle))
    il, xl = lines(float(first['x']), float(first['y']))
    found = {'name': well['name'], 'inline': il, 'crossline': xl, 'curves': None, 'depth': None}
    at = 'inline %.2f, crossline %.2f' % (il, xl) if il is not None else 'x %s, y %s' % (first['x'], first['y'])
    if well['las']:
        log = lasio.read(str(files / well['las']))
        found.update(curves=len(log.curves) - 1, depth=[float(log.well['STRT'].value), float(log.well['STOP'].value)])
        print('%s: %s; %d curves from %s to %s' % (well['name'], at, found['curves'], *found['depth']))
    else:
        print('%s: positions only; the pack holds no log for it' % well['name'])
    wells.append(found)
without_logs = [w['name'] for w in wells if w['curves'] is None]
# %% [markdown]
# ## The 2D lines
# segyio reads each line trace by trace in file order (`ignore_geometry`): its trace number (byte 21), its source
# point (byte 197, with its scalar at byte 201; none when both are 0), its position (bytes 181 and 185, scalar at
# 71) and its samples.
# %%
import hashlib

read_lines = []
for want in expected.get('lines', []):
    with segyio.open(str(files / want['path']), ignore_geometry=True) as line:
        numbers, points, xs, ys = [], [], [], []
        for header in line.header:
            sp, sp_scalar = header[197], header[201]
            points.append(None if (sp, sp_scalar) == (0, 0) else sp / -sp_scalar if sp_scalar < 0 else float(sp * sp_scalar))
            scalar = header[field.SourceGroupScalar]
            at = (lambda v: v / -scalar) if scalar < 0 else (lambda v: float(v * (scalar or 1)))  # SEG-Y's scalar rule, divided as written
            numbers.append(header[field.CDP]); xs.append(at(header[field.CDP_X])); ys.append(at(header[field.CDP_Y]))
        traces = np.asarray(line.trace.raw[:], dtype=np.float32).reshape(line.tracecount, -1)
        z = [int(line.header[0][field.DelayRecordingTime]), int(line.bin[segyio.BinField.Interval]), int(traces.shape[1])]
    k = (traces.shape[1] - 1) // 2
    picks = sorted({0, (len(numbers) - 1) // 2, len(numbers) - 1})
    read_lines.append({'path': want['path'], 'object': want['object'], 'traces': len(numbers), 'numbers': numbers, 'source_points': points, 'x': xs, 'y': ys,
                       'z': z, 'samples': [{'trace': numbers[n], 'index': k, 'value': float(traces[n, k])} for n in picks],
                       'sum': math.fsum(float(v) for v in traces.ravel()), 'sha256': hashlib.sha256(traces.astype('>f4').tobytes()).hexdigest(), 'section': traces})
    print('Line %s: %d traces, trace numbers %d to %d, %d samples from %d ms' % (want['object'], len(numbers), numbers[0], numbers[-1], z[2], z[0]))
# %% [markdown]
# ## Draw the inline with the wells on it, and the first 2D line
# Time increases downwards; each well is a vertical line at its crossline, labelled with how many inlines it lies
# away from this one. The first 2D line is drawn by its trace order, from its first trace number to its last.
# %%
marks, plotted = {}, {}
if expected['cube']:
    fig, ax = plt.subplots(figsize=(7, 5))
    image = ax.imshow(section.T, cmap='gray', aspect='auto', origin='upper', extent=[crosslines[0], crosslines[-1], times[-1], times[0]])
    ax.set_xlim(crosslines[0], crosslines[-1])
    ax.set_ylim(times[-1], times[0])
    for w in wells:
        marks[w['name']] = ax.axvline(w['crossline'], color='tab:red')
        ax.text(w['crossline'], times[0], ' %s, %.2f inlines away' % (w['name'], abs(w['inline'] - inline)), color='tab:red', va='top')
    ax.set_xlabel('Crossline'); ax.set_ylabel('Time (ms)'); ax.set_title('Inline %d' % inline)
    fig.savefig('open-a-starter-pack.png', bbox_inches='tight')
    print('Wrote open-a-starter-pack.png')
if read_lines:
    first_line = read_lines[0]
    line_fig, line_ax = plt.subplots(figsize=(7, 5))
    top, step = first_line['z'][0], first_line['z'][1] / 1000
    bottom = top + step * (first_line['z'][2] - 1)
    line_image = line_ax.imshow(first_line['section'].T, cmap='gray', aspect='auto', origin='upper', extent=[0, first_line['traces'] - 1, bottom, top])
    line_ax.set_xlabel('Trace (%d to %d)' % (first_line['numbers'][0], first_line['numbers'][-1])); line_ax.set_ylabel('Time (ms)')
    line_ax.set_title('Line %s' % first_line['object'])
    line_fig.savefig('open-a-starter-pack-line.png', bbox_inches='tight')
    print('Wrote open-a-starter-pack-line.png')
# %% [markdown]
# ## The time-depth models
# A pack may hold a well's time-depth model: `wells/<well>-time-depth.csv`, a `depth,time` header and one pair per
# row, in the depth kind, time kind and units its pack says. The csv module reads each pair.
# %%
read_models = []
for want in expected.get('time_depth', []):
    with open(files / want['path'], newline='') as handle:
        rows = list(csv.reader(handle))
    pairs = [[float(depth), float(time)] for depth, time in rows[1:]]
    read_models.append({'well': want['well'], 'path': want['path'], 'pairs': pairs})
    print('Time-depth model %s: %d pairs, depth %g to %g' % (want['well'], len(pairs), pairs[0][0], pairs[-1][0]))
# %% [markdown]
# ## Check against the pack
# `expected.json` holds what the pack's build read from the same files. What this notebook read and what it drew (read
# back from the plot itself) must agree with it; `open-a-starter-pack.json` keeps both.
# %%
differences, samples, inline_sum = [], [], None
if expected['cube']:
    drawn = image.get_array()
    k = expected['samples'][0]['index']
    picks = [crosslines.index(s['crossline']) for s in expected['samples']]
    plotted = {'xlim': [float(v) for v in ax.get_xlim()], 'ylim': [float(v) for v in ax.get_ylim()],
               'wells': {name: float(mark.get_xdata()[0]) for name, mark in marks.items()},
               'image': {'shape': list(drawn.shape), 'values': [float(drawn[k, n]) for n in picks], 'extent': [float(v) for v in image.get_extent()], 'origin': image.origin}}
    plt.close(fig)
    samples = [{'crossline': crosslines[n], 'index': k, 'value': float(section[n, k])} for n in picks]
    inline_sum = math.fsum(float(v) for v in section.ravel())
    if inline != expected['inline'] or crosslines != list(range(expected['crosslines'][0], expected['crosslines'][1] + 1, expected['crosslines'][2])):
        differences.append('the inline or its crosslines')
    for got, want in zip(samples, expected['samples']):
        if got != want: differences.append('the sample at crossline %d' % want['crossline'])
    if inline_sum != expected['inline_sum']: differences.append('inline_sum')
    if plotted['image']['values'] != [s['value'] for s in samples]: differences.append('the plotted samples')
for got, want in zip(wells, expected['wells']):
    if want['inline'] is not None and (abs(got['inline'] - want['inline']) > 0.01 or abs(got['crossline'] - want['crossline']) > 0.01):
        differences.append('the projection of %s' % want['name'])
    if got['curves'] != want['curves']: differences.append('the curve count of %s' % want['name'])
    if got['depth'] != want['depth']: differences.append('the depth range of %s' % want['name'])
    if expected['cube'] and plotted['wells'][got['name']] != got['crossline']: differences.append('the plotted line of %s' % want['name'])
for got, want in zip(read_lines, expected.get('lines', [])):
    for key in ('traces', 'numbers', 'source_points', 'x', 'y', 'z', 'samples', 'sum', 'sha256'):
        if got[key] != want[key]: differences.append('the %s of line %s' % (key.replace('_', ' '), want['object']))
if read_lines:
    drawn_line = line_image.get_array()
    k = first_line['samples'][0]['index']
    plotted['line'] = {'object': first_line['object'], 'shape': list(drawn_line.shape),
                       'values': [float(drawn_line[k, first_line['numbers'].index(s['trace'])]) for s in first_line['samples']],
                       'extent': [float(v) for v in line_image.get_extent()], 'origin': line_image.origin}
    plt.close(line_fig)
    if plotted['line']['values'] != [s['value'] for s in first_line['samples']]: differences.append('the plotted samples of line %s' % first_line['object'])
if len(read_lines) != len(expected.get('lines', [])): differences.append('the number of 2D lines')
for got, want in zip(read_models, expected.get('time_depth', [])):
    if len(got['pairs']) != len(want['pairs']): differences.append('the number of pairs of the time-depth model of %s' % want['well'])
    for n, (pair, wanted) in enumerate(zip(got['pairs'], want['pairs']), 1):
        if pair != wanted: differences.append('pair %d of the time-depth model of %s' % (n, want['well']))
if len(read_models) != len(expected.get('time_depth', [])): differences.append('the number of time-depth models')
result = {'inline': inline, 'samples': samples, 'inline_sum': inline_sum,
          'wells': [dict(w, inline=round(w['inline'], 2) + 0.0, crossline=round(w['crossline'], 2) + 0.0) if w['inline'] is not None else w for w in wells],
          'without_logs': without_logs, 'plotted': plotted, 'differences': differences,
          **({'lines': [{k: v for k, v in got.items() if k != 'section'} for got in read_lines]} if 'lines' in expected else {}),
          **({'time_depth': [{'well': got['well'], 'path': got['path'], 'pairs': len(got['pairs'])} for got in read_models]} if 'time_depth' in expected else {})}
with open('open-a-starter-pack.json', 'w') as handle:
    json.dump(result, handle, indent=2, sort_keys=True)
    handle.write('\n')
assert not differences, 'Differs from expected.json: ' + '; '.join(differences)
if 'lines' not in expected:
    print('Agrees with expected.json: inline %d, %d samples, the inline sum and %d wells' % (inline, len(samples), len(wells)))
else:
    print('Agrees with expected.json:', 'inline %d, %d samples, the inline sum,' % (inline, len(samples)) if expected['cube'] else 'no cube,', '%d wells and %d 2D lines' % (len(wells), len(read_lines)))
if read_models:
    print('Agrees with expected.json: every pair of %d time-depth models' % len(read_models))
