import json
import os
from pathlib import Path
import re
import sys
import nbformat
from nbclient import NotebookClient
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from support import synthetic_server


def test_execute_notebook_figure_descriptor_and_recovery(tmp_path,monkeypatch):
    directory=Path(__file__).resolve().parents[1]
    with synthetic_server() as server:
        for key,value in {'OPHIOLITE_URL':server.url,'OPHIOLITE_PROJECT':'p','OPHIOLITE_TEMPLATE_FIXTURE':'1','OPHIOLITE_TEMPLATES_ROOT':str(directory.parent),'OPHIOLITE_NOTEBOOK_OUTPUT':str(tmp_path)}.items():monkeypatch.setenv(key,value)
        notebook=nbformat.read(directory/'read-and-plot.ipynb',as_version=4)
        executed=NotebookClient(notebook,timeout=60,kernel_name='python3',resources={'metadata':{'path':str(tmp_path)}}).execute()
    assert (tmp_path/'curve.png').read_bytes().startswith(b'\x89PNG')
    outputs=[output for cell in executed.cells for output in cell.get('outputs',[])]
    html='\n'.join(output.get('data',{}).get('text/html','') for output in outputs)
    assert 'Technical details' in html and 'Samples' in html and 'Missing' in html
    assert '/data/m~' in html and 'revision=' in html
    visible=re.sub(r'<details>.*?</details>','',html,flags=re.S)
    visible=re.sub(r'<[^>]*>','',visible)
    assert not re.search(r'las2/1|synthetic-file|[0-9a-f]{64}|source-reference',visible)
    assert 'las2/1' in html
    text='\n'.join(output.get('text','') for output in outputs)
    assert 'different depth units' in text and 'ophiolite login' in text
    assert all(output.output_type!='error' for output in outputs)
