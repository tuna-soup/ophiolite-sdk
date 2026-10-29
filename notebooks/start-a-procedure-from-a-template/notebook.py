# %% [markdown]
# # Start a procedure from a template
# A procedure starts from a working template for a step and a kind of data: `procedure.json` says what it reads,
# makes and lets you set, `procedure.py` holds the code, and its own tests and sample data come with it. Each start
# is valid as it is made. A pair this version has no start for is refused with a sentence that says what there is.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Everything here runs on your computer in both modes: nothing
# is added to a project, so `OPHIOLITE_URL` changes nothing. To share a start once it does what you need, see the
# notebook "Share a procedure with your project".
# %%
import tempfile
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite import procedure_templates, procedures
from ophiolite.gallery import connect

client = connect()  # not used: the starts are made on this computer
work = Path(tempfile.mkdtemp(prefix='start-a-procedure-'))  # the starts live outside this folder
# %% [markdown]
# ## Two starts
# One reads a LAS file into a well log; one makes well tops from well tops, with a marked place for your calculation.
# %%
for step, kind in (('read', 'las2/1'), ('process', 'well-tops-csv/1')):
    verdict = procedures.new(work / step, step, kind=kind)
    print(verdict['sentence'])
    print('  files:', ', '.join(sorted(p.name for p in (work / step).iterdir())))
# %% [markdown]
# ## A pair with no start
# Checks compare well tops and deviation surveys in this version; a check for a grid is refused, and nothing is made.
# %%
try:
    procedures.new(work / 'check-grid', 'check', kind='esri-ascii-grid/1')
except ValueError as refused:
    print('Refused:', refused)
print('Made a folder:', (work / 'check-grid').exists())
# %% [markdown]
# ## Every start this version makes
# One dot for each step and kind with a start.
# %%
made = sorted(procedure_templates.made())
steps = sorted({step for step, _ in made})
kinds = sorted({procedure_templates.word(kind) for _, kind in made})
print('Starts:', len(made))
fig, ax = plt.subplots(figsize=(6, 5), layout='constrained')
ax.scatter([steps.index(step) for step, _ in made], [kinds.index(procedure_templates.word(kind)) for _, kind in made])
ax.set_xticks(range(len(steps)), steps)
ax.set_yticks(range(len(kinds)), kinds)
ax.set_title('Steps and kinds with a start')
fig.savefig('start-a-procedure-from-a-template.png', bbox_inches='tight')
plt.close(fig)
print('Wrote start-a-procedure-from-a-template.png')
