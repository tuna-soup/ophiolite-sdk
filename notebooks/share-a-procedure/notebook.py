# %% [markdown]
# # Share a procedure with your project
# Check a procedure and run it on your own computer, add it to your project privately, have a project administrator
# enable it for everyone, and run it as a colleague: they are asked once whether they trust code you wrote, and their
# answer is recorded as theirs. Ophiolite never runs a procedure on its server; every run is on someone's computer.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the procedure is checked and run on
# your own computer and nothing is added anywhere. To work in your project, put the `configuration.json` from Connect →
# Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access
# key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter.
# Adding it there makes a private version that only you and the project administrators see until an administrator
# enables it. To see your colleague's side as well, also set `OPHIOLITE_COLLEAGUE_ACCESS_KEY` to a second project
# member's access key (a test account's, for example).
# %%
import json
import shutil
import tempfile
import uuid
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import ophiolite
from ophiolite import procedures
from ophiolite.errors import OphioliteError
from ophiolite.gallery import connect, colleague, synthetic

client = connect()
other = colleague()
work = Path(tempfile.mkdtemp(prefix='share-a-procedure-'))  # the procedure, its inputs and runs live outside this folder
# %% [markdown]
# ## The procedure
# The SDK's sample procedure shifts formation tops by a fixed depth: a `procedure.json` that says what it reads, makes
# and lets you set, and a `procedure.py` with the code. Each run of this notebook gives it a new name, so it is a new
# procedure in your project.
# %%
folder = work / 'procedure'
shutil.copytree(Path(ophiolite.__file__).parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift', folder,
                ignore=shutil.ignore_patterns('__pycache__'))
manifest = json.loads((folder / 'procedure.json').read_text())
manifest['name'] = 'shift-' + uuid.uuid4().hex[:8]
(folder / 'procedure.json').write_text(json.dumps(manifest, indent=2))
verdict = procedures.validate(folder)
print(verdict['sentence'])
assert verdict['valid']
# %% [markdown]
# ## Run it on your computer first
# Two synthetic tops, declared as measured depth in metres, shifted down by 2.5 m. The run writes the shifted tops, a
# log and a record of exactly what ran into a new folder; nothing is published.
# %%
(work / 'tops.csv').write_text('name,md\nTop Chalk,1000.5\nBase Chalk,1200\n')
(work / 'tops.declared.json').write_text(json.dumps({'depth_unit': 'm', 'depth_basis': 'md'}))
inputs = {'tops': [work / 'tops.csv']}
options = dict(kinds={'tops': 'well-tops-csv/1'}, declared={'tops': work / 'tops.declared.json'}, settings=['shift=2.5'])
mine = procedures.run(folder, work / 'mine', inputs, **options)
print(mine['sentence'])

def depths(path):
    return [float(line.split(',')[1]) for line in Path(path).read_text().splitlines()[1:]]

before, after = depths(work / 'tops.csv'), depths(work / 'mine/shifted.csv')
print('Measured depth before:', before, 'after:', after)
fig, ax = plt.subplots(figsize=(4, 5), layout='constrained')
for x, values, label in ((0, before, 'Before'), (1, after, 'After')):
    ax.scatter([x] * len(values), values, label=label)
ax.set_xticks([0, 1], ['Before', 'After'])
ax.invert_yaxis()
ax.set_ylabel('Measured depth (m)')
ax.set_title('Tops shifted by 2.5 m')
fig.savefig('share-a-procedure.png', bbox_inches='tight')
plt.close(fig)
print('Wrote share-a-procedure.png')
# %% [markdown]
# ## Add it to your project, privately
# Ophiolite checks it with the same rules your computer used and keeps the exact files. Until an administrator enables
# it, only you and the project administrators see it.
# %%
added = None
if synthetic():
    print('Synthetic mode: nothing is added to a project. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to share it in yours.')
else:
    added = client.procedure_register(folder)
    print(f"Added {added['label']}, version {added['version']}. It is private: you and the project administrators see it "
          'until an administrator enables it for everyone.')
# %% [markdown]
# ## Enable it for everyone
# Only a project administrator enables a version. If you are not one, ask one to enable it in Settings → Procedures.
# %%
if added:
    try:
        client.procedure_enable(added['digest'])
        print('Enabled for everyone in this project.')
    except OphioliteError as refused:
        print(refused, '- ask a project administrator to enable it in Settings → Procedures.')
# %% [markdown]
# ## Your colleague trusts it, once
# Your colleague would run code you wrote on their own computer, so Ophiolite asks them first: who added it, when, and
# its exact digest. Their answer is recorded as theirs, for this version only; they are not asked again for it.
# %%
if added and other is not None:
    print(procedures.question(other.procedure_get(added['digest']))['text'])
    other.procedure_trust(added['digest'])
    print('Your colleague trusts this version.')
elif added:
    print('Set OPHIOLITE_COLLEAGUE_ACCESS_KEY to a second project member\'s key to see this step.')
# %% [markdown]
# ## Your colleague runs it from the project
# The exact version is fetched, checked against its digest and run on your colleague's computer, with the same tops.
# %%
if added and other is not None:
    theirs = other.procedure_run(manifest['name'], work / 'theirs', inputs, version=added['version'], cache=work / 'cache', **options)
    print(theirs['sentence'].replace(str(work), '…'))
    assert depths(work / 'theirs/shifted.csv') == after
    print('Same shifted tops as on your computer:', after)
