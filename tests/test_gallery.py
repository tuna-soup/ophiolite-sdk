"""E52 C5: the notebook gallery. Each listed notebook, copied alone to an empty directory, runs with a real kernel
against the installed SDK (never this checkout) in synthetic mode; its built form equals its script; the listing and
the folders agree; and the notebooks stay out of the wheel and the sdist while `ophiolite/gallery.py` ships in the wheel."""
import io
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


def run(slug, tmp_path, monkeypatch, check=None):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES') != '1': pytest.skip('Provision the notebook lock and an installed SDK, and run the required template lane')
    nbformat = pytest.importorskip('nbformat'); nbclient = pytest.importorskip('nbclient')
    for name in [k for k in os.environ if k.startswith('OPHIOLITE_') or k == 'PYTHONPATH']: monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))  # no saved sign-in, no address: the synthetic mode a new reader gets
    folder = tmp_path / 'download'; folder.mkdir()
    shutil.copy(ROOT / 'notebooks' / slug / 'notebook.ipynb', folder / (slug + '.ipynb'))
    notebook = nbformat.read(folder / (slug + '.ipynb'), as_version=4)
    if check: notebook.cells.append(nbformat.v4.new_code_cell(check + '\nprint("CHECKED")'))  # E126b: asserts on the notebook's own variables
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
    assert not check or 'CHECKED' in text
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


def test_grids_and_gis_files_draws_the_outlines_with_the_hole_empty_and_publishes_nothing_synthetic(tmp_path, monkeypatch):
    text = run('grids-and-gis-files', tmp_path, monkeypatch)
    assert "2 features: ['ELL', 'RING']" in text and 'the hole is empty' in text and "{'geojson/1': {'crs': 'EPSG:23031'}}" in text
    assert 'Synthetic mode: nothing is published.' in text


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


def test_a_spreadsheet_becomes_wells_and_tops_matches_its_columns_on_this_computer_and_sends_nothing_synthetic(tmp_path, monkeypatch):
    text = run('a-spreadsheet-becomes-wells-and-tops', tmp_path, monkeypatch)
    assert ': 6 rows, columns Well, Formation, Top MD (m)' in text and "Columns used: well from 'Well', name from 'Formation', md from 'Top MD (m)'" in text
    assert 'Synthetic mode: nothing is sent. In your project this table gives 2 sets of tops (3 rows and 2 rows), skips Row 6' in text
    assert 'Synthetic mode: nothing is sent. In your project the layout "Gallery tops" is remembered' in text  # E89


def test_layers_for_a_gis_follows_the_next_link_and_says_why_a_path_is_not_placed_synthetic(tmp_path, monkeypatch):
    text = run('layers-for-a-gis', tmp_path, monkeypatch)
    assert "Collections: ['wellbore-paths']" in text and "{'wellbore-paths': 2}" in text
    assert 'HON-GT-02: This survey does not state that its azimuths are from grid north, so it is not drawn on the map.' in text
    assert 'Wrote layers-for-a-gis.png with 1 paths placed' in text


def test_where_are_my_wells_draws_the_located_wells_and_reads_a_well_with_its_wellbore_synthetic(tmp_path, monkeypatch):
    text = run('where-are-my-wells', tmp_path, monkeypatch)
    assert '2 wells located, within [5.1, 52.1, 6.2, 52.9] (longitude and latitude)' in text
    assert '3 wells, 2 located, 1 without a location' in text and 'Wrote where-are-my-wells.png with 2 wells' in text
    assert 'Synthetic well 1: 0 filed on the well, 1 with its wellbores' in text and '  Synthetic well 1 main: 1' in text  # E66


def test_well_logs_in_a_bucket_pins_its_logs_and_reports_a_changed_one_synthetic(tmp_path, monkeypatch):
    text = run('well-logs-in-a-bucket', tmp_path, monkeypatch)
    assert 'wells/: 3 files' in text and 'W-1/gamma.las' in text and 'notes.txt' in text and 'only as a copy' in text
    assert 'Synthetic mode: nothing is sent. In your project the 2 logs are added' in text
    assert 'After W-1/gamma.las changed: a different digest; reading it reports that the revision is unavailable' in text


def test_wells_from_sql_server_and_oracle_compares_both_systems_on_this_computer_synthetic(tmp_path, monkeypatch):
    """E61 C9 (R4): synthetic mode compares typed rows; Oracle's empty string is NULL, coordinates are as stored."""
    text = run('wells-from-sql-server-and-oracle', tmp_path, monkeypatch)
    assert 'Synthetic mode: nothing is sent. Three wells, as each system returns them, are compared on this computer.' in text
    assert 'SQL Server: 3 wells in EPSG:28992' in text and 'Oracle: 3 wells in EPSG:28992' in text
    assert 'In both: 3 wells; in one only: 0; at other coordinates: 0' in text
    assert 'ALO-01 in SQL Server: ALLARDSOOG-01 at x 217009.52200567, y 568544.1263913' in text
    assert 'ALO-01 in Oracle: ALLARDSOOG-01 at x 217009.52200567, y 568544.1263913' in text
    assert "Wells without an operator: {'SQL Server': 0, 'Oracle': 1}" in text


def test_share_a_procedure_checks_and_runs_it_locally_and_adds_nothing_synthetic(tmp_path, monkeypatch):
    text = run('share-a-procedure', tmp_path, monkeypatch)
    assert 'Valid: Shift tops by a fixed depth, version 1. It reads Well tops (CSV) and makes Well tops (CSV).' in text
    assert 'Measured depth before: [1000.5, 1200.0] after: [1003.0, 1202.5]' in text
    assert 'Synthetic mode: nothing is added to a project.' in text and 'Added ' not in text and 'trusts' not in text


def test_start_a_procedure_from_a_template_makes_two_valid_starts_and_refuses_a_pair_synthetic(tmp_path, monkeypatch):
    """E112 s3 C2: the sentences are the SDK's own, as literals; 49 is s1's made set."""
    text = run('start-a-procedure-from-a-template', tmp_path, monkeypatch)
    assert 'Valid: Make well tops (CSV), version 1. It reads Well tops (CSV) and makes Well tops (CSV).' in text
    assert 'Valid: Read LAS 2.0 well log file, version 1.' in text and text.count('files: data, procedure.json, procedure.py, template.json, tests') == 2
    assert 'Refused: There is no check template for grid yet; check templates compare well tops and deviation surveys.' in text
    assert 'Made a folder: False' in text and 'Starts: 49' in text


def test_a_recipe_runs_again_checks_the_recipe_and_runs_nothing_synthetic(tmp_path, monkeypatch):
    text = run('a-recipe-runs-again', tmp_path, monkeypatch, check='assert not (Path.home() / "ophiolite-recipe-work").exists()')
    assert 'Valid: "Residual report again", 3 steps.' in text
    assert '1. Run the residual report on this computer\n2. Publish the result\n3. Read its outcome states' in text
    assert 'Synthetic mode: the recipe is checked and nothing ran.' in text and 'States: Not run, Not run, Not run' in text


def test_run_it_again_makes_the_same_shifted_tops_and_refuses_a_changed_procedure_synthetic(tmp_path, monkeypatch):
    """E112 s3 C2 (7-M5): 1000.5 and 1200 shifted by 2.5 m, as literals, for both runs."""
    text = run('run-it-again', tmp_path, monkeypatch, check="assert first.again == line and again['result']['run']['outputs'] == first['run']['outputs']")
    assert 'First run: [1003.0, 1202.5]' in text and 'Run again: [1003.0, 1202.5]' in text
    assert "procedures.run('…/shift-tops', new_output, inputs={'data': ['…/tops.csv']}" in text and "settings=['shift=2.5'], expected_digest='" in text
    assert "Refused: Not run: the procedure's files changed after they were checked; nothing ran." in text  # mutation: no expected_digest


def test_who_has_access_until_when_reads_the_last_days_and_who_has_access_synthetic(tmp_path, monkeypatch):
    """E67a C6 (R12): the stored end is the start of the next UTC day; the notebook names the last day (M5 literals)."""
    text = run('who-has-access-until-when', tmp_path, monkeypatch)
    assert 'Synthetic project (member): no end date' in text and 'Shared survey (viewer): ends 1 January 2999' in text
    assert 'Alice: no end date - Member through Direct grant' in text and 'Bob: until 31 December 2999 - Member through Direct grant' in text
    assert 'Erin: no access (ended after 31 December 1999) - Member through Direct grant' in text
    assert 'Vic: no end date - Viewer through Geoscience' in text and 'Wrote who-has-access-until-when.png' in text


def test_public_repository_to_map_draws_what_nlog_listed_and_sends_nothing_synthetic(tmp_path, monkeypatch):
    text = run('public-repository-to-map', tmp_path, monkeypatch)
    assert 'Synthetic mode: nothing is sent. NLOG listed 4 wells for HON-GT:' in text
    assert 'HON-GT-01: position (75242.83, 448081.04, Dutch RD) · 24 formation tops · 1 deviation survey (67 stations)' in text
    assert 'in your project the 4 wells would be added at these positions, each with the line "Source: NLOG.NL"' in text


def test_a_spreadsheet_and_a_database_joined_joins_on_the_well_name_and_sends_nothing_synthetic(tmp_path, monkeypatch):
    text = run('a-spreadsheet-and-a-database-joined', tmp_path, monkeypatch)  # E58b
    assert ': 6 samples; porosity in %, -888 means missing' in text and 'wells.sqlite: 3 wells' in text
    assert 'Synthetic mode: nothing is sent. Both tables are read on this computer.' in text
    assert 'Joined: 5 samples of 2 wells; left out: 1 sample(s) of a well not in the database' in text
    assert 'Hydreco: mean porosity 25.00 %' in text and 'Wintershall Noordzee: mean porosity 19.75 %' in text  # -888 left out of the mean


ADAPTED = {'petrophysical-calculations': '05 - Petrophysical Calculations', 'working-with-lasio': '07 - Working With LASIO',  # E126b: slug -> upstream title
           'csv-file-to-las-file': '22 - CSV File to LAS File', 'well-paths-with-wellpathpy': '31 - Creating Well Paths with wellpathpy'}
SOURCE = {'author': 'Andy McDonald', 'licence': 'MIT', 'url': 'https://github.com/andymcdgeo/Petrophysics-Python-Series',
          'commit': 'b6bcfb17f026e8b612cf64ed24d408bb69290d4e'}


def test_petrophysical_calculations_publish_vshale_on_the_exact_revision(tmp_path, monkeypatch):
    text = run('petrophysical-calculations', tmp_path, monkeypatch, check='\n'.join([  # E126b
        "import math",
        "assert receipt.revision_number == 1 and list(outputs) == ['VSHALE']",
        "assert [(p['key'], p['revision']) for p in parents] == [('curve-a', log['revision'])] and log['revision'].startswith('d899416c4221')",
        "values = back['VSHALE'].tolist()",
        "assert back.index.tolist() == [100.0, 101.0, 102.0, 103.0, 104.0] and math.isnan(values[2])",
        "assert values[:2] + values[3:] == [-0.0076, 0.2462, 0.7538, 1.0076]",
        "assert receipt.asset_id in result.workspace_url()"]))
    assert 'GR P99 39.7 - P01 0.3' in text and 'Published ' in text and ' version 1' in text
    assert 'Skipped PHI and PHIECALC: this log has no bulk density (RHOB or DEN)' in text
    assert 'Skipped SW (Archie, Simandoux): RT and RW are interpretation inputs this log does not carry' in text
    assert 'Read back equals the computed curves, sample for sample, missing where they are missing: 1' in text and 'Open it in the Workspace: ' in text


def test_working_with_lasio_counts_the_curves_of_the_project_log(tmp_path, monkeypatch):
    text = run('working-with-lasio', tmp_path, monkeypatch, check='\n'.join([  # E126b
        "import math",
        "assert [(c.mnemonic, c.unit) for c in las.curves] == [('DEPT', 'M'), ('GR', 'gAPI')]",
        "assert las.well.WELL.value == 'Synthetic well 1'",
        "assert list(las['DEPT']) == [100.0, 101.0, 102.0, 103.0, 104.0]",
        "gr = list(las['GR']); assert gr[:2] + gr[3:] == [0.0, 10.0, 30.0, 40.0] and math.isnan(gr[2])"]))
    assert 'There are a total of: 2 curves present within this file' in text and 'Curve: GR, Units: gAPI' in text
    assert 'Missing GR samples: 1' in text


def test_csv_file_to_las_file_builds_with_append_curve_and_would_upload(tmp_path, monkeypatch):
    text = run('csv-file-to-las-file', tmp_path, monkeypatch, check='\n'.join([  # E126b
        "import math",
        "assert [(c.mnemonic, c.unit) for c in back.curves] == [('DEPT', 'm'), ('GR', 'API'), ('RHOB', 'g/cm3')]",
        "assert list(back['DEPT']) == [100.0, 101.0, 102.0] and list(back['RHOB']) == [2.45, 2.5, 2.55]",
        "gr = list(back['GR']); assert gr[0] == 10.0 and math.isnan(gr[1]) and gr[2] == 30.0",
        "assert back.well.WELL.value == 'Random Well'"]))
    assert 'Built a LAS file of 3 curves and 3 rows' in text
    assert 'Synthetic mode: nothing is uploaded. In your project upload_las would add this 3-curve file as an original.' in text


def test_well_paths_with_wellpathpy_match_the_sdk_minimum_curvature(tmp_path, monkeypatch):
    text = run('well-paths-with-wellpathpy', tmp_path, monkeypatch, check='\n'.join([  # E126b
        "frozen = [(0, 0, 0), (100, 0, 0), (199.4931, 6.155, 6.155), (295.9631, 24.4331, 24.4331), (386.5678, 49.1121, 58.2951)]",
        "assert len(offsets) == 5 and all(abs(o['dtvd'] - t) < 1e-4 and abs(o['dnorth'] - n) < 1e-4 and abs(o['deast'] - e) < 1e-4 for o, (t, n, e) in zip(offsets, frozen))",
        "assert worst <= 0.01 and written.profile == 'deviation-csv/1'"]))
    assert 'station 4 md 400: TVD 386.5678 north 49.1121 east 58.2951' in text
    assert 'Ophiolite and wellpathpy agree within 0.01 m at all 5 stations' in text
    assert 'Synthetic mode: nothing is uploaded. In your project upload_data would add this deviation survey as an original with the context declared.' in text


def test_the_volve_fetch_refuses_a_changed_file_and_an_unreachable_upstream_before_any_upload(monkeypatch):
    """E126b (D1): notebooks 22 and 31 fetch the pinned upstream file; neither refusal reaches an upload."""
    import urllib.error
    import urllib.request
    for slug in ('csv-file-to-las-file', 'well-paths-with-wellpathpy'):
        script = (ROOT / 'notebooks' / slug / 'notebook.py').read_text()
        source = script[script.index('def fetch('):script.index('# %%', script.index('def fetch('))]
        namespace = {'SOURCE': 'https://example.invalid/', 'urllib': urllib, 'hashlib': __import__('hashlib'), 'Path': Path}
        exec(source, namespace)
        monkeypatch.setattr(urllib.request, 'urlopen', lambda url, timeout: io.BytesIO(b'changed'))
        with pytest.raises(SystemExit, match=r'differs from the pinned copy \(sha256 ab\); nothing was uploaded\.'):
            namespace['fetch']('Data/x.csv', 'ab', '/nonexistent')
        def unreachable(url, timeout): raise urllib.error.URLError('no route')
        monkeypatch.setattr(urllib.request, 'urlopen', unreachable)
        with pytest.raises(SystemExit, match=r'^Upstream unreachable \(.*no route.*\); .* Nothing was uploaded\.$'):
            namespace['fetch']('Data/x.csv', 'ab', '/nonexistent')


def test_every_entry_is_listed_built_and_described():
    assert GALLERY['schema'] == 'ophiolite.notebook-gallery/1' and SLUGS == ['read-a-well-log', 'shale-volume-from-gamma-ray', 'make-a-wavelet', 'make-a-wedge-model', 'large-files', 'a-well-folder-in-one-report', 'time-depth-table', 'grids-and-gis-files', 'how-was-this-made', 'open-it-here', 'a-spreadsheet-becomes-wells-and-tops', 'layers-for-a-gis', 'well-logs-in-a-bucket', 'share-a-procedure', 'who-has-access-until-when', 'where-are-my-wells', 'a-spreadsheet-and-a-database-joined', 'wells-from-sql-server-and-oracle', 'public-repository-to-map', 'petrophysical-calculations', 'working-with-lasio', 'csv-file-to-las-file', 'well-paths-with-wellpathpy', 'start-a-procedure-from-a-template', 'a-recipe-runs-again', 'run-it-again']
    for entry in GALLERY['notebooks']:
        adapted = {'attribution', 'data_terms', 'minimum_sdk'} if entry['slug'] in ADAPTED else set()  # E126b (D3)
        assert set(entry) == {'slug', 'title', 'sentence', 'modes', 'data'} | adapted and entry['modes'] == ['synthetic', 'live']
        if adapted:
            assert entry['attribution'] == dict(SOURCE, title=ADAPTED[entry['slug']]) and 'Equinor and the Volve licence partners' in entry['data_terms']
            assert entry['minimum_sdk'] == 'The first Ophiolite SDK release after 2026.10.96 (it adds the lasio and DataFrame adapters); requirements.txt installs it.'
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
    listing['notebooks'].pop(); listing['notebooks'][0] = dict(listing['notebooks'][0], attribution=dict(SOURCE, title='05'))  # E126b (D3): all or none
    (copy / 'notebooks/gallery.json').write_text(json.dumps(listing))
    assert 'The gallery entry read-a-well-log states attribution without data_terms, minimum_sdk' in check(copy).stderr
    listing['notebooks'][0] = dict(listing['notebooks'][0], attribution={'title': '05'}, data_terms='T', minimum_sdk='E126a')
    (copy / 'notebooks/gallery.json').write_text(json.dumps(listing))
    assert 'The gallery entry read-a-well-log needs attribution with author, commit, licence, title, url' in check(copy).stderr


def test_notebooks_ship_in_neither_artifact_and_the_gallery_module_ships_in_the_wheel():
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist: pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel and sdist')
    wheel, = Path(dist).glob('*.whl'); sdist, = Path(dist).glob('*.tar.gz')
    names = zipfile.ZipFile(wheel).namelist()
    assert 'ophiolite/gallery.py' in names and not any(n.startswith('notebooks/') or '/notebooks/' in n for n in names)
    with tarfile.open(sdist) as archive:
        assert not any('/notebooks/' in n for n in archive.getnames())
