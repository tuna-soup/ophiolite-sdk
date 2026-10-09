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
import tempfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
GALLERY = json.loads((ROOT / 'notebooks/gallery.json').read_text())
SLUGS = [entry['slug'] for entry in GALLERY['notebooks']]
MEANS = {'Linear (simple)': '0.500000', 'Larionov, Tertiary rocks': '0.394427', 'Larionov, older rocks': '0.435935', 'Clavier': '0.427542', 'Steiber': '0.404551'}


def ipc_folder():
    """H23: a short folder for the kernel's Unix sockets (a socket path is at most 107 bytes), outside the notebook's."""
    base = os.environ.get('XDG_RUNTIME_DIR')
    folder = tempfile.mkdtemp(prefix='nb-', dir=base if base and os.access(base, os.W_OK) else None)
    if len(folder) > 60:
        shutil.rmtree(folder); folder = tempfile.mkdtemp(prefix='nb-', dir='/tmp')
    return folder


def client(notebook, folder, sockets):
    """H23: the kernel's channels over IPC sockets in SOCKETS, not TCP ports: a port chosen free can be taken by another
    process before the kernel binds it (Visual 37884770925, sdk-templates: 'Address already in use', port 32777)."""
    from traitlets.config import Config
    nbclient = pytest.importorskip('nbclient')
    config = Config({'KernelManager': {'transport': 'ipc', 'ip': os.path.join(sockets, 'kernel')}})
    return nbclient.NotebookClient(notebook, timeout=120, kernel_name='python3', resources={'metadata': {'path': str(folder)}}, config=config)


def run(slug, tmp_path, monkeypatch):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES') != '1': pytest.skip('Provision the notebook lock and an installed SDK, and run the required template lane')
    nbformat = pytest.importorskip('nbformat'); nbclient = pytest.importorskip('nbclient')
    for name in [k for k in os.environ if k.startswith('OPHIOLITE_') or k == 'PYTHONPATH']: monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))  # no saved sign-in, no address: the synthetic mode a new reader gets
    folder = tmp_path / 'download'; folder.mkdir()
    shutil.copy(ROOT / 'notebooks' / slug / 'notebook.ipynb', folder / (slug + '.ipynb'))
    notebook = nbformat.read(folder / (slug + '.ipynb'), as_version=4)
    notebook.cells.append(nbformat.v4.new_code_cell('import ophiolite\nprint("SDK:", ophiolite.__file__)'))
    sockets = ipc_folder()
    try:
        executed = client(notebook, folder, sockets).execute()
    finally:
        shutil.rmtree(sockets, ignore_errors=True)
    outputs = [output for cell in executed.cells for output in cell.get('outputs', [])]
    assert all(output.output_type != 'error' for output in outputs)
    text = ''.join(output.get('text', '') for output in outputs)
    where = text.split('SDK: ', 1)[1].strip()
    assert 'site-packages' in where and not where.startswith(str(ROOT)), where  # the installed wheel, not this checkout
    assert sorted(p.name for p in folder.iterdir()) == sorted([slug + '.ipynb', slug + '.png'])
    assert (folder / (slug + '.png')).read_bytes().startswith(b'\x89PNG')
    return text


def test_the_gallery_kernel_talks_over_ipc_sockets(tmp_path):
    """H23: while the kernel is live its transport is ipc, its sockets are files in their own folder, and a request
    gets its answer."""
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES') != '1': pytest.skip('Provision the notebook lock and an installed SDK, and run the required template lane')
    nbformat = pytest.importorskip('nbformat')
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('1 + 1')])
    sockets = ipc_folder()
    try:
        nb = client(notebook, tmp_path, sockets)
        with nb.setup_kernel():
            info = nb.km.get_connection_info()
            assert (nb.km.transport, info['transport']) == ('ipc', 'ipc')
            assert any(name.startswith('kernel-') for name in os.listdir(sockets)), os.listdir(sockets)
            cell = nb.execute_cell(notebook.cells[0], 0)
        assert cell.outputs[0]['data']['text/plain'] == '2'
    finally:
        shutil.rmtree(sockets, ignore_errors=True)


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


def test_make_a_wavelet_reads_its_strongest_frequency_and_publishes_nothing_synthetic(tmp_path, monkeypatch):
    text = run('make-a-wavelet', tmp_path, monkeypatch)
    assert '129 samples every 1 ms, from -64 to 64 ms' in text and 'Strongest at 30 Hz (read to the nearest 1 Hz); declared 30 Hz' in text
    assert 'The same samples every 2 ms: strongest at 15 Hz' in text and 'Synthetic mode: nothing is published.' in text


def test_make_a_wedge_model_reads_the_tuning_thickness_from_the_excerpt_values(tmp_path, monkeypatch):
    text = run('make-a-wedge-model', tmp_path, monkeypatch)
    assert 'Rodenrijs Claystone    4073 m/s 2629 kg/m3' in text and 'Delft Sandstone        4024 m/s 2379 kg/m3' in text
    assert 'Tuning thickness: 13 ms two-way time (trace 13, 26.2 m at 4024 m/s)' in text and 'Synthetic mode: nothing is published.' in text


def test_large_files_makes_its_volume_outside_the_folder_and_sends_nothing_synthetic(tmp_path, monkeypatch):
    text = run('large-files', tmp_path, monkeypatch)
    assert 'dipping-reflector.sgy: 19.4 MiB, 60 inlines x 80 crosslines x 1000 samples' in text
    assert 'Synthetic mode: nothing is sent. With 8 MiB requests this file goes in 3 parts.' in text


def test_a_well_folder_in_one_report_checks_its_folder_outside_the_download_and_sends_nothing_synthetic(tmp_path, monkeypatch):
    text = run('a-well-folder-in-one-report', tmp_path, monkeypatch)
    assert ': 5 files\n' in text and '/W-1/gamma_copy.las (' in text
    assert 'Synthetic mode: nothing is sent. In your project this folder gives 2 Added, 1 Already here, 1 Not read, and 1 file that no reader recognises.' in text


def test_time_depth_table_writes_the_two_layer_model_and_publishes_nothing_synthetic(tmp_path, monkeypatch):
    text = run('time-depth-table', tmp_path, monkeypatch)
    assert '41 pairs, from (0, 0.0) to (2000, 1666.667)' in text and 'Interval velocities (m/s, rounded): [2000, 3000]' in text
    assert "depth,time 0,0 2000,1666.667" in text and 'Synthetic mode: nothing is published.' in text


def test_how_was_this_made_reads_the_story_the_change_and_the_refusal_synthetic(tmp_path, monkeypatch):
    text = run('how-was-this-made', tmp_path, monkeypatch)
    assert 'Shale volume, made in a notebook, version 2\n  Reported by Alice; Ophiolite did not run this calculation.' in text
    assert '  Synthetic gamma ray, version 1\n    A file added by Alice on Not recorded: original.las.' in text
    assert 'Ophiolite did not run this calculation, so it cannot make it again.' in text and 'Nothing differs' not in text



def test_open_it_here_opens_the_exact_version_and_sends_again_once_synthetic(tmp_path, monkeypatch):
    text = run('open-it-here', tmp_path, monkeypatch)
    assert 'Version 1 opens at http://127.0.0.1:' in text and '/project/p/data/m~' in text and '?revision=' in text
    assert 'Sent again: version 2 - run twice, still version 2' in text
    assert 'Version 3 arrived first; the line built on version 2 was refused: The result has a newer version; review it before adding another' in text

def test_every_entry_is_listed_built_and_described():
    assert GALLERY['schema'] == 'ophiolite.notebook-gallery/1' and SLUGS == ['read-a-well-log', 'shale-volume-from-gamma-ray', 'make-a-wavelet', 'make-a-wedge-model', 'large-files', 'a-well-folder-in-one-report', 'time-depth-table', 'how-was-this-made', 'open-it-here']
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
