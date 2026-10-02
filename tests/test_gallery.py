"""E52 C5: the notebook gallery. Each listed notebook, copied alone to an empty directory, runs with a real kernel
against the installed SDK (never this checkout) in synthetic mode; its built form equals its script; the listing and
the folders agree; and the notebooks stay out of the wheel and the sdist while `ophiolite/gallery.py` ships in the wheel."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
GALLERY = json.loads((ROOT / 'notebooks/gallery.json').read_text())
SLUGS = [entry['slug'] for entry in GALLERY['notebooks']]
MEANS = {'Linear (simple)': '0.500000', 'Larionov, Tertiary rocks': '0.394427', 'Larionov, older rocks': '0.435935', 'Clavier': '0.427542', 'Steiber': '0.404551'}


def run(slug, tmp_path, monkeypatch):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES') != '1': pytest.skip('Provision the notebook lock and an installed SDK, and run the required template lane')
    nbformat = pytest.importorskip('nbformat'); nbclient = pytest.importorskip('nbclient')
    for name in [k for k in os.environ if k.startswith('OPHIOLITE_') or k == 'PYTHONPATH']: monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))  # no saved sign-in, no address: the synthetic mode a new reader gets
    folder = tmp_path / 'download'; folder.mkdir()
    shutil.copy(ROOT / 'notebooks' / slug / 'notebook.ipynb', folder / (slug + '.ipynb'))
    notebook = nbformat.read(folder / (slug + '.ipynb'), as_version=4)
    notebook.cells.append(nbformat.v4.new_code_cell('import ophiolite\nprint("SDK:", ophiolite.__file__)'))
    executed = nbclient.NotebookClient(notebook, timeout=120, kernel_name='python3', resources={'metadata': {'path': str(folder)}}).execute()
    outputs = [output for cell in executed.cells for output in cell.get('outputs', [])]
    assert all(output.output_type != 'error' for output in outputs)
    text = ''.join(output.get('text', '') for output in outputs)
    where = text.split('SDK: ', 1)[1].strip()
    assert 'site-packages' in where and not where.startswith(str(ROOT)), where  # the installed wheel, not this checkout
    assert sorted(p.name for p in folder.iterdir()) == sorted([slug + '.ipynb', slug + '.png'])
    assert (folder / (slug + '.png')).read_bytes().startswith(b'\x89PNG')
    return text


def test_read_a_well_log_runs_from_an_empty_directory(tmp_path, monkeypatch):
    text = run('read-a-well-log', tmp_path, monkeypatch)
    assert 'Synthetic gamma ray - 5 samples of GR in gAPI against depth in M' in text
    assert 'Missing samples stay missing: 1 of 5 at [102.0] M' in text


def test_shale_volume_runs_publishes_two_versions_and_prints_the_hand_worked_means(tmp_path, monkeypatch):
    text = run('shale-volume-from-gamma-ray', tmp_path, monkeypatch)
    assert 'clean 1.5 gAPI, shale 38.5 gAPI, from 4 samples' in text
    for label, mean in MEANS.items():
        assert f'{label:<32} mean {mean}' in text
    assert 'Missing samples stay missing: 1 of 4' not in text and 'Missing samples stay missing: 1 of 5' in text
    assert "version 1: " in text and "version 2: " in text and "'low': 10.0, 'high': 90.0" in text


def test_every_entry_is_listed_built_and_described():
    assert GALLERY['schema'] == 'ophiolite.notebook-gallery/1' and SLUGS == ['read-a-well-log', 'shale-volume-from-gamma-ray']
    for entry in GALLERY['notebooks']:
        assert set(entry) == {'slug', 'title', 'sentence', 'modes', 'data'} and entry['modes'] == ['synthetic', 'live']
        script = (ROOT / 'notebooks' / entry['slug'] / 'notebook.py').read_text()
        assert script.startswith('# %% [markdown]\n# # ' + entry['title'] + '\n')
        assert 'pip install -r requirements.txt' in script and 'python -m ipykernel install --user' in script  # install first
        assert 'from ophiolite.gallery import connect' in script and 'sys.path' not in script and 'support' not in script
    subprocess.run([sys.executable, str(ROOT / 'tools/build_notebook.py'), '--check'], check=True, capture_output=True, text=True)


def copy_tree(tmp_path):
    copy = tmp_path / 'sdk'
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__', 'build', 'dist', '*.egg-info'))
    return copy


def check(copy):
    return subprocess.run([sys.executable, str(copy / 'tools/build_notebook.py'), '--check'], capture_output=True, text=True)


def test_a_hand_edit_an_unbuilt_entry_and_an_unlisted_folder_are_refused(tmp_path):
    copy = copy_tree(tmp_path)
    built = copy / 'notebooks/read-a-well-log/notebook.ipynb'
    built.write_text(built.read_text().replace('Read a well log', 'Read a log'))
    assert 'read-a-well-log/notebook.ipynb differs from its paired script' in check(copy).stderr
    shutil.copy(ROOT / 'notebooks/read-a-well-log/notebook.ipynb', built)
    (copy / 'notebooks/porosity').mkdir()
    assert 'not listed in notebooks/gallery.json: porosity' in check(copy).stderr
    (copy / 'notebooks/porosity').rmdir()
    listing = json.loads((copy / 'notebooks/gallery.json').read_text())
    listing['notebooks'].append(dict(listing['notebooks'][0], slug='porosity'))
    (copy / 'notebooks/gallery.json').write_text(json.dumps(listing))
    assert 'The gallery entry porosity has no notebooks/porosity/notebook.py' in check(copy).stderr


def test_notebooks_ship_in_neither_artifact_and_the_gallery_module_ships_in_the_wheel():
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist: pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel and sdist')
    wheel, = Path(dist).glob('*.whl'); sdist, = Path(dist).glob('*.tar.gz')
    names = zipfile.ZipFile(wheel).namelist()
    assert 'ophiolite/gallery.py' in names and not any(n.startswith('notebooks/') or '/notebooks/' in n for n in names)
    with tarfile.open(sdist) as archive:
        assert not any('/notebooks/' in n for n in archive.getnames())
