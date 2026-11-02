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
FRESH_BEFORE = 'd48a9b4b6b2b374b5bda5ca49f075a3fdefce4dff9accdf155896f2b273813df'  # E105a's no-kind start `fresh`
FRESH_DIGEST = 'cf6869202f08c9dc3d92e4bb722362d857a2366595ceb9ec62e2a31bac891a3b'  # the same start with E131's first comment
NOTICE = ('`ophiolite procedures` now runs as `ophiolite tools`; the old spelling is removed in a later release, announced '
          'one release ahead in the CHANGELOG.\n')

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


def answer(tmp, argv, monkeypatch, spelling='procedures'):
    """(exit code, stdout, stderr) of `ophiolite procedures ...` (or `ophiolite tools ...`), with no network reachable."""
    def no_network(*args, **kwargs): raise AssertionError('an offline procedure command opened a connection')
    monkeypatch.setattr(httpx.Client, 'send', no_network)
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli.main([spelling, *[a.format(tmp=tmp) for a in argv]])
        except SystemExit as stop: code = stop.code or 0
    clean = lambda text: text.replace(str(tmp), '<tmp>')
    return {'exit': code, 'stdout': clean(out.getvalue()), 'stderr': clean(err.getvalue())}


@pytest.mark.parametrize('spelling', ['tools', 'procedures'])
def test_the_offline_commands_answer_as_frozen(tmp_path, monkeypatch, spelling):
    found = {}
    for name, argv, how in CASES:
        tmp = tmp_path / name; tmp.mkdir()
        prepare(tmp, how)
        found[name] = answer(tmp, argv, monkeypatch, spelling)
        assert NOTICE.strip() not in found[name]['stderr'], name  # E131 s1 (R2-8): piped, no notice under either spelling
    if os.environ.get('OPHIOLITE_REFREEZE') == '1':
        ANSWERS.write_text(json.dumps(found, indent=2, sort_keys=True) + '\n')
    frozen = json.loads(ANSWERS.read_text())
    # E131 s1 (D4.1): the start's first comment names tools, so its digest moves; only that literal differs.
    assert frozen['new-process-json']['stdout'].count(FRESH_BEFORE) == 1
    frozen['new-process-json']['stdout'] = frozen['new-process-json']['stdout'].replace(FRESH_BEFORE, FRESH_DIGEST)
    # E131 s1 (D4.3, R2-8): the one offline answer adjusted by words, exactly this substring, for the spelling typed.
    assert frozen['new-process']['stdout'].count('ophiolite procedures validate') == 1
    frozen['new-process']['stdout'] = frozen['new-process']['stdout'].replace('ophiolite procedures validate', 'ophiolite %s validate' % spelling)
    assert found == frozen


HELP = Path(__file__).resolve().parent / 'fixtures/procedures-help-e105b.json'


def test_the_help_of_every_command_before_e106_is_unchanged(monkeypatch):
    """E106: `publish` and `again` join the group; the help of the commands that were there reads as at the E105b lane
    head (tests/fixtures/procedures-help-e105b.json, recorded from SDK 9de3d1a at 100 columns). E131 s1 (D4.3): it says
    tools, so the frozen text is compared through HELP_WORDS, each wrapped entry joined to one line; both spellings
    print the same help."""
    import sys
    from test_tools_cli import reworded, unwrap
    frozen = json.loads(HELP.read_text())
    monkeypatch.setenv('COLUMNS', str(frozen['columns'])); monkeypatch.setattr(sys, 'argv', ['ophiolite'])

    def helped(*argv):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            with pytest.raises(SystemExit): cli.parser().parse_args([*argv, '--help'])
        return text.getvalue()
    found = {verb: helped('tools', verb) for verb in frozen['help']}
    assert {verb: helped('procedures', verb) for verb in frozen['help']} == found
    found = {verb: unwrap(text) for verb, text in found.items()}
    was = {verb: reworded(text) for verb, text in frozen['help'].items()}
    run, before = found.pop('run'), was.pop('run')  # E110 (D9): run gains only these two
    added = [line for line in reworded(RUN_ADDED) if line]
    at = run.index(added[0])
    assert run[at:at + len(added)] == added  # adhoc-e121-identity: --item names @ASSET:REVISION
    assert run[1:at] + run[at + len(added):] == before[1:] and run[0] == before[0].replace(
        '[--setting SETTING]', '[--setting SETTING] [--item SLOT=ITEM[@N]|SLOT=@ASSET:REVISION] [--reference FILE|ITEM@N]')
    new, before = found.pop('new'), was.pop('new')  # E112 s0: --kind joins, --label is optional
    assert new[0] == before[0].replace('--label LABEL', '[--kind KIND] [--label LABEL]')
    step = lambda lines: next(line for line in lines if line.startswith('  --step'))
    assert step(new) == step(before) and reworded(NEW_KIND)[0] in new and reworded(NEW_LABEL)[0] in new
    assert found == was and len(found) == 7


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
