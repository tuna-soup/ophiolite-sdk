"""Build a deterministic, output-free notebook from the tested percent script."""
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def build(source):
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
    return json.dumps({'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3'},'template_version':'0.1.0'},'nbformat':4,'nbformat_minor':5},indent=2)+'\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    directory=ROOT/'templates/notebook';output=build((directory/'read-and-plot.py').read_text());target=directory/'read-and-plot.ipynb'
    if args.check:
        if target.read_text()!=output:raise ValueError('Notebook differs from paired script')
    else:target.write_text(output)
    print('Notebook: deterministic paired script, no saved outputs')

if __name__=='__main__':main()
