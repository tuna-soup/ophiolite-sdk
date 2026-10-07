# %% [markdown]
# # A well folder in one report
# Upload a folder of well logs in one step and read one report that says what became of each file: added, already
# here, not read or not recognised, and which wellbore each log names.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the folder is made and checked on your
# own computer and nothing is sent. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. Uploading
# creates files that only you can see until you share them.
# %%
import tempfile
import uuid
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic

client = connect()
TAG = uuid.uuid4().hex[:6].upper()  # a new well name each run, so a second run adds new files


def log(well, gamma):
    """A small LAS 2.0 gamma-ray log; -999.25 marks a missing sample."""
    rows = '\n'.join(f'{100 + i * 0.5:.1f} {g}' for i, g in enumerate(gamma))
    return (f'~Version\nVERS. 2.0 : LAS\nWRAP. NO : one row per depth\n~Well\nSTRT.M 100 : start\nSTOP.M {100 + (len(gamma) - 1) * 0.5} : stop\n'
            f'STEP.M 0.5 : step\nNULL. -999.25 : missing\nWELL. {well} : well\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma ray\n~ASCII\n{rows}\n').encode()


one, two = log(f'GALLERY-{TAG} 1', [45, 60, -999.25, 82, 75]), log(f'GALLERY-{TAG} 2', [30, 33, 41, 38])
files = {'W-1/gamma.las': one, 'W-1/gamma_copy.las': one, 'W-2/gamma.las': two,
         'W-2/gamma_damaged.las': two[:-6] + b'\xff\xfe\xff' + two[-3:], 'Notes/readme.txt': b'Field notes. Nothing here is a log.\n'}
root = Path(tempfile.mkdtemp(prefix='ophiolite-folder-')) / f'Field-{TAG}'
for path, raw in files.items():
    (root / path).parent.mkdir(parents=True, exist_ok=True); (root / path).write_bytes(raw)
folder = client.upload_runs.open(root)  # read on this computer; nothing is sent
print(f'{folder.name}: {len(folder.files)} files')
for file in folder.files:
    print(f'  {file.path} ({file.size} bytes)')
# %% [markdown]
# ## Upload it and read the report
# Every file is checked on the server. A file with the same content as one added earlier is not stored twice; a damaged
# file and a file no reader recognises are named with the reason. Run the cell again after an interruption: the same
# folder continues where it stopped and files already added are not sent again.
# %%
if synthetic():
    results = {'Not sent': len(folder.files)}
    print('Synthetic mode: nothing is sent. In your project this folder gives 2 Added, 1 Already here, 1 Not read, and 1 file that no reader recognises.')
else:
    report = client.upload_runs.upload(root, attribution='Made by the Ophiolite gallery', audience=[], rights_confirmed=True)
    print(report.text())
    report.save(root.parent / 'report.csv')
    results = {}
    for row in report.rows():
        results[row['result']] = results.get(row['result'], 0) + 1
    links = [(item['ordinal'], item['proposal']['entity_id']) for item in report.items if item.get('proposal')]
    print(f'{len(links)} files name a wellbore of this project; link them with client.upload_runs.associate(report.run_id, links)')
fig, axis = plt.subplots(figsize=(6, 2.5))
axis.barh(list(results), list(results.values()), color='#5b7f6e')
axis.set_xlabel('Files'); axis.set_title(f'{folder.name}: one report')
fig.savefig('a-well-folder-in-one-report.png', bbox_inches='tight')
plt.close(fig)
print('Wrote a-well-folder-in-one-report.png')
