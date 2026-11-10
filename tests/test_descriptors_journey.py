"""E147 (D7): the release descriptors journey, from an installed SDK wheel in a clean environment.

The journey of the epic, by slice; only the steps that exist run, none is stubbed or skipped:

    s0  ophiolite bundle check on a 2.15 bundle with its citation and descriptors: verified; with croissant.json's
        licence changed: "Bundle not verified: the licence in croissant.json disagrees with the manifest.", exit 1  (this test)
    s1  write_folder writes the citation and its descriptors; bundle check verifies; pandas reads the folder unchanged
        (this test: the test interpreter writes, the base wheel checks and reads the title; X-11)
    s2  ophiolite export --title writes the citation from the story, the organisation and the files' licences, and the
        descriptors; bundle check verifies; the base wheel reads the title (this test: the base wheel exports against
        the synthetic server with the captured story page)
    s3  a starter pack carries the descriptors derived from starter.json and the Open Subsurface Data record
    s4  ophiolite story --prov writes PROV-JSON and PROV-O JSON-LD from provenance/read
    s5  ophiolite release cite --doi registers a DOI bound to the manifest digest (the account is an owner action)
    --  the STAC link to starter packs' Croissant files is Open Subsurface Data's

OPHIOLITE_TEST_WHEEL_PYTHON is the base wheel's interpreter (Visual builds build/sdk-wheel with no extras).
"""
import os
import subprocess

import pytest

WHEEL = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
COPY = r'''
import json, shutil, sys
from importlib.resources import files
from pathlib import Path
valid = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/bundle-wells')))
shutil.copytree(valid, 'wells')
shutil.copytree(valid, 'changed')
doc = json.loads(Path('changed/croissant.json').read_text())
doc['license'] = 'https://spdx.org/licenses/cc-by-4.0'
Path('changed/croissant.json').write_text(json.dumps(doc))
print(valid)
'''


def test_s0_bundle_check_verifies_the_descriptors_and_refuses_a_disagreeing_one(tmp_path):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    run = lambda *argv: subprocess.run([WHEEL, '-I', *argv], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    done = run('-c', COPY)
    assert done.returncode == 0, done.stderr
    assert 'site-packages' in done.stdout
    done = run('-m', 'ophiolite', 'bundle', 'check', 'wells')
    assert (done.returncode, done.stdout) == (0, 'Bundle verified: 1 exact revisions, 1 curves, 0 other data. Checksums show integrity, not authorship.\n'), done.stderr
    done = run('-m', 'ophiolite', 'bundle', 'check', 'changed')
    assert (done.returncode, done.stdout) == (1, 'Bundle not verified: the licence in croissant.json disagrees with the manifest.\n'), done.stderr


TITLE = r'''
import sys
from ophiolite import bundle
print(bundle.open_bundle(sys.argv[1]).manifest['citation']['title'])
'''


def test_s1_a_written_folder_checks_and_reads_in_the_base_wheel_and_pandas_reads_it(tmp_path):
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    pandas = pytest.importorskip('pandas'); pytest.importorskip('pyarrow'); pytest.importorskip('pyproj')
    from test_descriptor_validators import WRITE
    namespace = {}
    exec(compile(WRITE, 'WRITE', 'exec'), namespace)
    folder = namespace['write_cited'](tmp_path)['fixture']  # the test interpreter writes (X-11)
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    run = lambda *argv: subprocess.run([WHEEL, '-I', *argv], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    done = run('-m', 'ophiolite', 'bundle', 'check', folder.name)
    assert (done.returncode, done.stdout) == (0, 'Project folder verified: 1 item (wells, 4 rows). Checksums show integrity, not authorship.\n'), done.stderr
    done = run('-c', TITLE, folder.name)
    assert (done.returncode, done.stdout) == (0, 'Synthetic field: four wells\n'), done.stderr
    assert pandas.read_parquet(folder / 'items/wells.parquet')['id'].tolist() == ['SYN-F1', 'SYN-F2', 'SYN-F3', 'SYN-F4']


def test_s2_the_base_wheel_exports_with_a_citation_and_checks_it(tmp_path):
    """E147 s2 (C3): the base wheel's `ophiolite export --title --description` against the synthetic server, with the
    captured story page and discovery (test_export_citation.citing_server); bundle check verifies; the title reads back."""
    if not WHEEL:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
        pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    import json
    from test_export_citation import citing_server
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    run = lambda *argv, given=None: subprocess.run([WHEEL, '-I', *argv], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, input=given)
    with citing_server() as server:
        (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
        done = run('-m', 'ophiolite', 'login', '--credentials', 'credentials.json', '--key-stdin', given='oph_key_synthetic')
        assert done.returncode == 0, done.stderr
        asset, revision, _ = server.selection[0]
        done = run('-m', 'ophiolite', 'export', '--credentials', 'credentials.json', '--asset', asset, '--revision', revision, '--curve', 'GR',
                   '--output', 'cited', '--title', 'Synthetic gamma ray', '--description', 'One synthetic gamma ray log.')
        assert (done.returncode, done.stdout) == (0, 'Exported 1 exact revision(s) to cited with its citation - check it offline with: '
                                                     'ophiolite exchange bundle check cited\n'), done.stderr
    done = run('-m', 'ophiolite', 'bundle', 'check', 'cited')
    assert (done.returncode, done.stdout) == (0, 'Bundle verified: 1 exact revisions, 1 curves, 0 other data. Checksums show integrity, not authorship.\n'), done.stderr
    done = run('-c', TITLE, 'cited')
    assert (done.returncode, done.stdout) == (0, 'Synthetic gamma ray\n'), done.stderr
