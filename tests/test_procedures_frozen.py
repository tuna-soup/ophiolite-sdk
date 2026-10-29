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
    run, was = found.pop('run').split('\n\n', 1), frozen['help'].pop('run').split('\n\n', 1)  # E110 (D9): run gains only these two
    assert run[1].replace(RUN_ADDED, '') == was[1] and RUN_ADDED in run[1]  # adhoc-e121-identity: --item names @ASSET:REVISION
    assert ' '.join(run[0].split()) == ' '.join(was[0].split()).replace(
        '[--setting SETTING]', '[--setting SETTING] [--item SLOT=ITEM[@N]|SLOT=@ASSET:REVISION] [--reference FILE|ITEM@N]')
    new, was = found.pop('new').split('  --step'), frozen['help'].pop('new').split('  --step')  # E112 s0: --kind joins, --label is optional
    assert ' '.join(new[0].split()) == ' '.join(was[0].split()).replace('--label LABEL', '[--kind KIND] [--label LABEL]')
    assert new[1].split('\n')[0] == was[1].split('\n')[0] and NEW_KIND in new[1] and NEW_LABEL in new[1]
    assert found == frozen['help'] and len(found) == 7


NEW_KIND = '''  --kind KIND           What the procedure reads, makes or sends: a word such as well-tops or las
'''
NEW_LABEL = '''  --label LABEL         What the procedure does, in words a person reads (default: from --step and
                        --kind)
'''


RUN_ADDED = '''  --item SLOT=ITEM[@N]|SLOT=@ASSET:REVISION
                        With --from-project: a project version to run on, by name and version
                        number (default: its latest), or exactly as @ASSET:REVISION
  --reference FILE|ITEM@N
                        With --from-project, for a check procedure: the reference, a file on this
                        computer or a project version
'''
