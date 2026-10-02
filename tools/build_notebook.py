"""Build deterministic, output-free notebooks from their tested percent scripts: the notebook template and every entry
of the notebook gallery (`notebooks/gallery.json`). `--check` fails on a notebook that differs from its script, an entry
without a notebook, or a gallery folder the listing does not name."""
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def build(source,metadata=None):
    cells=[];kind='code';lines=[]
    def append():
        if not any(line.strip() for line in lines):return
        text=''.join(lines)
        if kind=='markdown':text=''.join(line[2:] if line.startswith('# ') else line[1:] if line.startswith('#') else line for line in lines)
        cell={'cell_type':kind,'metadata':{},'source':text.splitlines(keepends=True)}
        if kind=='code':cell.update(execution_count=None,outputs=[])
        cell['id']='cell-'+str(len(cells)+1)
        cells.append(cell)
    for line in source.splitlines(keepends=True):
        if line.startswith('# %%'):
            append();lines=[];kind='markdown' if '[markdown]' in line else 'code'
        else:lines.append(line)
    append()
    return json.dumps({'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3'},**(metadata or {'template_version':'0.1.0'})},'nbformat':4,'nbformat_minor':5},indent=2)+'\n'


def gallery():
    """(script, notebook, metadata) for every gallery entry, in listing order; a missing or unlisted entry is refused."""
    directory=ROOT/'notebooks';listing=json.loads((directory/'gallery.json').read_text())
    slugs=[entry['slug'] for entry in listing['notebooks']]
    if len(set(slugs))!=len(slugs):raise ValueError('The gallery lists a notebook twice')
    folders=sorted(p.name for p in directory.iterdir() if p.is_dir() and not p.name.startswith('.'))
    unlisted=sorted(set(folders)-set(slugs))
    if unlisted:raise ValueError('Notebook folders not listed in notebooks/gallery.json: '+', '.join(unlisted))
    for slug in slugs:
        script=directory/slug/'notebook.py'
        if not script.is_file():raise ValueError(f'The gallery entry {slug} has no notebooks/{slug}/notebook.py')
        yield script,directory/slug/'notebook.ipynb',{'gallery':slug}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    template=ROOT/'ophiolite/templates/notebook'
    pairs=[(template/'read-and-plot.py',template/'read-and-plot.ipynb',None),*gallery()]
    for script,target,metadata in pairs:
        output=build(script.read_text(),metadata)
        if args.check:
            if not target.is_file() or target.read_text()!=output:raise ValueError(f'{target.relative_to(ROOT)} differs from its paired script; run tools/build_notebook.py')
        else:target.write_text(output)
    print(f'Notebooks: {len(pairs)} deterministic paired scripts, no saved outputs')

if __name__=='__main__':main()
