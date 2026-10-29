# %% [markdown]
# # A recipe runs again
# A recipe is a JSON file you write that names the steps you would otherwise type, in order: run the residual
# procedure on your computer, publish the run, and read the result's outcome states. Ophiolite takes the steps one at
# a time and records each in the work folder's journal, so a stop (a crash, a refusal, a lost answer) continues from
# the first step not finished when you run it again, and nothing is published twice.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the recipe is checked and its steps
# are shown; nothing runs. To run it in your project, put the `configuration.json` from Connect → Use Python in this
# folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names, and `OPHIOLITE_RECIPE_SELECTION` and
# `OPHIOLITE_RECIPE_SURFACE` to the well set and the surface to use (a name, `NAME@N` or `@ASSET:REVISION`), before
# you start Jupyter. Change the procedure, its version, the formation and the result name below to your project's.
# %%
import json
import os
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from IPython.display import display
from ophiolite import recipe_runs
from ophiolite.gallery import connect, synthetic

client = connect()
# %% [markdown]
# ## The recipe
# Three steps. The residual run reads the well set and the surface you give as inputs; the publish step publishes that
# run under a name; the states step reads how the project's outcomes judge the result. A recipe holds no credential:
# a key that names a secret is refused.
# %%
recipe = {
    'schema': 'ophiolite.recipe/1', 'name': 'Residual report again',
    'inputs': {'selection': {'type': 'item'}, 'surface': {'type': 'item'}},
    'steps': [
        {'id': 'run', 'step': 'residuals', 'with': {'procedure': 'residual-at-wells', 'version': 1, 'selection': {'input': 'selection'},
                                                     'surface': {'input': 'surface'}, 'formation': 'DCC'}},
        {'id': 'publish', 'step': 'publish', 'with': {'run': {'from': 'run'}, 'name': 'Groningen residuals at DCC'}},
        {'id': 'states', 'step': 'states', 'with': {'result': {'from': 'publish', 'role': 'residuals'}}},
    ]}
recipe_runs.check(recipe)
print('Valid: "%s", %d steps.' % (recipe['name'], len(recipe['steps'])))
words = {'residuals': 'Run the residual report on this computer', 'publish': 'Publish the result', 'states': 'Read its outcome states'}
for n, step in enumerate(recipe['steps'], 1):
    print('%d. %s' % (n, words[step['step']]))
# %% [markdown]
# ## Run it in your project
# The work folder is `~/ophiolite-recipe-work/<recipe name>`, kept after the run: if anything stops, run this cell
# again and it continues there. The card shows each step in words and, once every step is finished, a "Run again"
# line: the same recipe file and inputs in a new work folder, asking again about any procedure version you have not
# trusted.
# %%
home = Path.home() / 'ophiolite-recipe-work'
selection, surface = os.environ.get('OPHIOLITE_RECIPE_SELECTION'), os.environ.get('OPHIOLITE_RECIPE_SURFACE')
states = ['Not run'] * len(recipe['steps'])
if synthetic():
    print('Synthetic mode: the recipe is checked and nothing ran. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to run it in your project.')
elif not (selection and surface):
    print('Set OPHIOLITE_RECIPE_SELECTION and OPHIOLITE_RECIPE_SURFACE to the well set and the surface to run it on.')
else:
    home.mkdir(exist_ok=True)
    path = home / 'residual-report-again.json'
    path.write_text(json.dumps(recipe, indent=2))
    work = home / 'residual-report-again'
    print('Work folder:', work)
    result = recipe_runs.run(client, path, work, {'selection': selection, 'surface': surface})
    display(result)
    print(result['sentence'])
    states = [recipe_runs.WORDS.get(step['state'], 'Needs attention') for step in result['steps']]
print('States:', ', '.join(states))
fig, ax = plt.subplots(figsize=(8, 2), layout='constrained')
for n, (step, state) in enumerate(zip(recipe['steps'], states)):
    ax.text(n, 0, '%d. %s\n%s' % (n + 1, words[step['step']].replace(' on this computer', '').replace(' the ', '\nthe '), state),
            ha='center', va='center', bbox={'boxstyle': 'round', 'facecolor': 'white'})
    if n: ax.annotate('', (n - 0.42, 0), (n - 0.58, 0), arrowprops={'arrowstyle': '<-'})
ax.set_xlim(-0.6, len(states) - 0.4); ax.set_ylim(-1, 1); ax.axis('off')
fig.savefig('a-recipe-runs-again.png', bbox_inches='tight')
plt.close(fig)
print('Wrote a-recipe-runs-again.png')
