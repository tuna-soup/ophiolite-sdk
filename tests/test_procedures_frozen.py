"""E105b C1: what the offline procedure commands answer today, frozen before the catalogue joins them.

`procedures new|validate|run <folder>` stay E105a's: same words, same --json, same exit codes, no network. The answers
were recorded at the E105a lane head (SDK eec654c) into tests/fixtures/procedures-offline-answers.json; the run's
own folder paths are written as <tmp>. `OPHIOLITE_REFREEZE=1` rewrites the file (review the diff)."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

import ophiolite
from ophiolite import cli

FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'
ANSWERS = Path(__file__).resolve().parent / 'fixtures/procedures-offline-answers.json'
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
DECLARED = {'depth_unit': 'm', 'depth_basis': 'md'}

# (name, argv after `procedures`, how the folder is prepared)
CASES = [
    ('validate-valid', ['validate', '{tmp}/depth-shift'], 'bundle'),
    ('validate-valid-json', ['validate', '{tmp}/depth-shift', '--json'], 'bundle'),
    ('validate-label-snake', ['validate', '{tmp}/depth-shift', '--json'], 'label'),
    ('validate-no-manifest', ['validate', '{tmp}/depth-shift'], 'no-manifest'),
    ('validate-missing-folder', ['validate', '{tmp}/absent', '--json'], None),
    ('new-process', ['new', '{tmp}/fresh', '--step', 'process', '--label', 'Shift tops by a fixed depth'], None),
    ('new-process-json', ['new', '{tmp}/fresh', '--step', 'process', '--label', 'Shift tops by a fixed depth', '--json'], None),
    ('run-shift', ['run', '{tmp}/depth-shift', '--output', '{tmp}/out', '--input', 'tops={tmp}/in/tops.csv', '--kind', 'tops=well-tops-csv/1',
                   '--declared', 'tops={tmp}/in/tops.declared.json', '--setting', 'shift=2.5'], 'bundle'),
    ('run-bad-setting-json', ['run', '{tmp}/depth-shift', '--output', '{tmp}/out', '--input', 'tops={tmp}/in/tops.csv', '--kind', 'tops=well-tops-csv/1',
                              '--declared', 'tops={tmp}/in/tops.declared.json', '--setting', 'shift=far', '--json'], 'bundle'),
    ('run-missing-folder', ['run', '{tmp}/absent', '--output', '{tmp}/out', '--input', 'tops={tmp}/in/tops.csv'], None),
]


def prepare(tmp, how):
    (tmp / 'in').mkdir()
    (tmp / 'in/tops.csv').write_text(TOPS)
    (tmp / 'in/tops.declared.json').write_text(json.dumps(DECLARED))
    if how is None: return
    folder = tmp / 'depth-shift'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', folder, ignore=shutil.ignore_patterns('__pycache__'))
    if how == 'label':
        manifest = json.loads((folder / 'procedure.json').read_text())
        manifest['settings'][0]['label'] = 'depth_shift'
        (folder / 'procedure.json').write_text(json.dumps(manifest, indent=2))
    if how == 'no-manifest': (folder / 'procedure.json').unlink()


def answer(tmp, argv, monkeypatch):
    """(exit code, stdout, stderr) of `ophiolite procedures ...`, with no network reachable."""
    def no_network(*args, **kwargs): raise AssertionError('an offline procedure command opened a connection')
    monkeypatch.setattr(httpx.Client, 'send', no_network)
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli.main(['procedures', *[a.format(tmp=tmp) for a in argv]])
        except SystemExit as stop: code = stop.code or 0
    clean = lambda text: text.replace(str(tmp), '<tmp>')
    return {'exit': code, 'stdout': clean(out.getvalue()), 'stderr': clean(err.getvalue())}


def test_the_offline_commands_answer_as_frozen(tmp_path, monkeypatch):
    found = {}
    for name, argv, how in CASES:
        tmp = tmp_path / name; tmp.mkdir()
        prepare(tmp, how)
        found[name] = answer(tmp, argv, monkeypatch)
    if os.environ.get('OPHIOLITE_REFREEZE') == '1':
        ANSWERS.write_text(json.dumps(found, indent=2, sort_keys=True) + '\n')
    assert found == json.loads(ANSWERS.read_text())


HELP = Path(__file__).resolve().parent / 'fixtures/procedures-help-e105b.json'


def test_the_help_of_every_command_before_e106_is_unchanged(monkeypatch):
    """E106: `publish` and `again` join the group; the help of the commands that were there reads exactly as at the E105b
    lane head (tests/fixtures/procedures-help-e105b.json, recorded from SDK 9de3d1a at 100 columns)."""
    import sys
    frozen = json.loads(HELP.read_text())
    monkeypatch.setenv('COLUMNS', str(frozen['columns'])); monkeypatch.setattr(sys, 'argv', ['ophiolite'])
    found = {}
    for verb in frozen['help']:
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            with pytest.raises(SystemExit): cli.parser().parse_args(['procedures', verb, '--help'])
        found[verb] = text.getvalue()
    assert found == frozen['help'] and len(found) == 9
