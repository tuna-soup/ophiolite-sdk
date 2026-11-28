"""adhoc-sdist-png: the wheel publish.yml makes (`python -m build`: the sdist, then a wheel from the unpacked sdist) is the
wheel built straight from the checkout, path for path and hash for hash: the RECORD tools/release/publish.py compares
with the qualified wheel. Release 2026.11.27 stopped at PyPI because MANIFEST.in's `global-exclude *.png` left the four
attachment fixtures (E191 s0) out of the sdist. Both wheels are built from a copy of the tracked files with this
interpreter's setuptools (PEP 517 hooks, no isolation, nothing downloaded)."""
import csv
import io
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = 'import sys\nfrom setuptools import build_meta\ngetattr(build_meta, sys.argv[1])(sys.argv[2])\n'
FIXTURES = ['figure.png', 'header-only.png', 'page-as-png.png', 'polyglot.png']


def build(hook, source, out):
    out.mkdir()
    subprocess.run([sys.executable, '-c', HOOK, hook, str(out)], cwd=source, check=True, capture_output=True)
    found, = out.iterdir()
    return found


def record(wheel):
    with zipfile.ZipFile(wheel) as archive:
        name, = [n for n in archive.namelist() if n.endswith('.dist-info/RECORD')]
        return {row[0]: row[1] for row in csv.reader(io.StringIO(archive.read(name).decode('utf-8'))) if row}


def checkout(where):
    """The tracked files only, as a clean clone of the tag has them. Outside a git checkout (the nightly SDK export runs
    these tests in a `git archive` of its commit) the tree as it is, without what a build or a test run leaves."""
    listed = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
    if listed.returncode:
        shutil.copytree(ROOT, where, ignore=shutil.ignore_patterns('build', 'dist', '*.egg-info', '__pycache__', '.pytest_cache', '.venv'))
        return where
    for name in filter(None, listed.stdout.decode().split('\0')):
        if (ROOT / name).is_file():
            (where / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, where / name)
    return where


def test_the_wheel_built_from_the_sdist_is_the_wheel_built_from_the_checkout(tmp_path):
    """Mutation: restore `global-exclude *.png` in MANIFEST.in → the four attachment fixtures are in the direct wheel only
    and this fails naming them."""
    source = checkout(tmp_path / 'checkout')
    sdist = build('build_sdist', source, tmp_path / 'sdist')
    with tarfile.open(sdist) as archive:
        archive.extractall(tmp_path / 'unpacked', filter='data')
    unpacked, = (tmp_path / 'unpacked').iterdir()
    direct, via_sdist = record(build('build_wheel', source, tmp_path / 'direct')), record(build('build_wheel', unpacked, tmp_path / 'via-sdist'))
    assert sorted(p for p in set(direct) | set(via_sdist) if direct.get(p) != via_sdist.get(p)) == []
    assert ['ophiolite/contracts/assets/v1/fixtures/attachments/files/' + name in via_sdist for name in FIXTURES] == [True] * 4
