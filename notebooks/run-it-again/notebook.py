# %% [markdown]
# # Run it again
# A procedure made from a template shifts formation tops on your own computer. The result shows itself as a card: what
# ran, what it made, and a "Run again" line, the same call with the same inputs and settings, pinned to the exact
# procedure version that ran. Running that line makes the same tops again in a new folder; once the procedure is
# changed, the line refuses instead of running something else.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Everything here runs on your computer in both modes: nothing
# is added to a project, so `OPHIOLITE_URL` changes nothing.
# %%
import json
import tempfile
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from IPython.display import display
from ophiolite import procedures
from ophiolite.gallery import connect

client = connect()  # not used: every run here is on this computer
work = Path(tempfile.mkdtemp(prefix='run-it-again-'))  # the procedure and its runs live outside this folder
# %% [markdown]
# ## A procedure from a template
# The well-tops start reads tops with Ophiolite's reader and writes them again with its writer. Its calculation goes
# where the start marks it: here, every measured depth moves by a setting, `shift`, in metres.
# %%
folder = work / 'shift-tops'
procedures.new(folder, 'process', 'Shift tops', kind='well-tops-csv/1')
code = (folder / 'procedure.py').read_text()
code = code.replace('    # Your calculation: change values here.\n',
                    "    values['tops'] = [{**top, 'md': top['md'] + settings['shift']} for top in values['tops']]\n")
(folder / 'procedure.py').write_text(code)
manifest = json.loads((folder / 'procedure.json').read_text())
manifest['settings'] = [{'key': 'shift', 'label': 'Depth shift', 'type': 'number', 'unit': 'm', 'default': 0}]
(folder / 'procedure.json').write_text(json.dumps(manifest, indent=2))
print(procedures.validate(folder)['sentence'])
# %% [markdown]
# ## Run it, and see the card
# Two synthetic tops, declared in metres on the same depth basis as the log, shifted down by 2.5 m. Open "Run again" on the card to see
# the line; "Technical details" holds the folders and the procedure's digest.
# %%
(work / 'tops.csv').write_text('name,md\nTop Chalk,1000.5\nBase Chalk,1200\n')
(work / 'tops.declared.json').write_text(json.dumps({'depth_unit': 'm', 'depth_basis': 'same-as-log'}))
inputs = {'data': [work / 'tops.csv']}
first = procedures.run(folder, work / 'first', inputs, kinds={'data': 'well-tops-csv/1'}, declared={'data': work / 'tops.declared.json'},
                       settings=['shift=2.5'])
display(first)

def depths(path):
    return [float(line.split(',')[1]) for line in Path(path).read_text().splitlines()[1:]]

print('First run:', depths(work / 'first/data.csv'))
# %% [markdown]
# ## Run again
# The line names the procedure folder, the inputs and settings as they were when the run began, and the digest of the
# version that ran. `new_output` is a new folder for its outputs. Changing `inputs` afterwards does not change it.
# %%
inputs['data'] = [work / 'somewhere-else.csv']  # the line keeps the inputs the run started with
line = first.again
print(line.replace(str(work), '…'))
again = {'procedures': procedures, 'new_output': work / 'again'}
exec('result = ' + line, again)
print('Run again:', depths(work / 'again/data.csv'))
fig, ax = plt.subplots(figsize=(4, 5), layout='constrained')
for x, values, label in ((0, depths(work / 'tops.csv'), 'Before'), (1, depths(work / 'first/data.csv'), 'First run'),
                         (2, depths(work / 'again/data.csv'), 'Run again')):
    ax.scatter([x] * len(values), values, label=label)
ax.set_xticks([0, 1, 2], ['Before', 'First run', 'Run again'])
ax.invert_yaxis()
ax.set_ylabel('Measured depth (m)')
ax.set_title('Tops shifted by 2.5 m, twice the same')
fig.savefig('run-it-again.png', bbox_inches='tight')
plt.close(fig)
print('Wrote run-it-again.png')
# %% [markdown]
# ## A changed procedure is not run by the old line
# Edit the procedure and the same line refuses: it runs only the version that made the first result.
# %%
(folder / 'procedure.py').write_text(code.replace("settings['shift']", "2 * settings['shift']"))
try:
    exec('result = ' + line, {'procedures': procedures, 'new_output': work / 'changed'})
except procedures.NotRun as refused:
    print('Refused:', refused)
