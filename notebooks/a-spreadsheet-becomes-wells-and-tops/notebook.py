# %% [markdown]
# # A spreadsheet becomes wells and tops
# Add the formation tops of two wells from one table: say which column holds what, review what would be added (the
# sets, the rows that are skipped and why, the wells each set links to), then add it and read one line per set.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the table is made and its columns
# matched on your own computer and nothing is sent. To work in your project, put the `configuration.json` from
# Connect → Use Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project
# access key); then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start
# Jupyter. Adding tops creates sets that only you can see until you share them.
# %%
import csv
import tempfile
import uuid
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic
from ophiolite.imports import parse_mapping, result_lines, review_lines

client = connect()
TAG = uuid.uuid4().hex[:6].upper()  # new well names each run, so a second run adds new sets
ROWS = [(f'GALLERY-{TAG} 1', 'North Sea Group', 0.0), (f'GALLERY-{TAG} 1', 'Chalk Group', 812.5), (f'GALLERY-{TAG} 1', 'Rijnland Group', 1290.0),
        (f'GALLERY-{TAG} 2', 'North Sea Group', 0.0), (f'GALLERY-{TAG} 2', 'Chalk Group', 'about 900'), (f'GALLERY-{TAG} 2', 'Rijnland Group', 1344.0)]
table = Path(tempfile.mkdtemp(prefix='ophiolite-table-')) / f'tops-{TAG}.csv'
with table.open('w', newline='') as out:
    writer = csv.writer(out); writer.writerow(['Well', 'Formation', 'Top MD (m)']); writer.writerows(ROWS)
mapping = parse_mapping(['well=Well,name=Formation,md=Top MD (m)'])  # the same pairs as `ophiolite import table --map`
print(f'{table.name}: {len(ROWS)} rows, columns Well, Formation, Top MD (m)')
print('Columns used:', ', '.join(f'{field} from {column!r}' for field, column in mapping.items()))
# %% [markdown]
# ## Review, then add
# A dry run reads the table on the server and says what would be added; nothing is added. The second call adds it.
# A row whose depth is not a number is skipped and named with its reason; the rest of its well is still added. The
# sets link to a well of this project with the same name; tops whose well is not found are added without a link.
# %%
if synthetic():
    counts = {'Rows read': 6, 'Rows skipped': 1}
    print('Synthetic mode: nothing is sent. In your project this table gives 2 sets of tops (3 rows and 2 rows), '
          'skips Row 6 because its measured depth "about 900" is not a number, and adds the tops without a link to a well.')
else:
    review = client.imports.from_table(table, 'well-tops', mapping, declarations={'depth_unit': 'm'}, dry_run=True)
    print('\n'.join(review_lines(review['preview'])))
    done = client.imports.from_table(table, 'well-tops', mapping, declarations={'depth_unit': 'm'}, audience=[])
    print('\n'.join(result_lines(done['run'], done['preview'])))
    counts = {'Rows read': done['preview']['counts']['rows'], 'Rows skipped': done['preview']['counts']['skipped_rows']}
fig, axis = plt.subplots(figsize=(6, 2))
axis.barh(list(counts), list(counts.values()), color='#5b7f6e')
axis.set_xlabel('Rows'); axis.set_title(f'{table.name}: one import')
fig.savefig('a-spreadsheet-becomes-wells-and-tops.png', bbox_inches='tight')
plt.close(fig)
print('Wrote a-spreadsheet-becomes-wells-and-tops.png')
