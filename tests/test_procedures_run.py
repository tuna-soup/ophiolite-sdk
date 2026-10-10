"""E105a C5: @procedure and `ophiolite procedures new|validate|run` — a run on this computer, in a child process,
from a fresh copy of exactly the files the digest covers; nothing is published. Expected values are literals."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ophiolite
from ophiolite import cli, procedures

FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'
REPO = Path(ophiolite.__file__).resolve().parent.parent
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
DECLARED = {'depth_unit': 'm', 'depth_basis': 'md'}
SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'


def depth_shift(tmp_path, code=None, **manifest_changes):
    folder = tmp_path / 'depth-shift'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))  # an installed SDK carries pip's bytecode
    if code is not None: (folder / 'procedure.py').write_text(code)
    if manifest_changes:
        manifest = json.loads((folder / 'procedure.json').read_text()); manifest.update(manifest_changes)
        (folder / 'procedure.json').write_text(json.dumps(manifest))
    return folder


def tops(tmp_path):
    (tmp_path / 'in').mkdir(exist_ok=True)
    (tmp_path / 'in/tops.csv').write_text(TOPS)
    (tmp_path / 'in/tops.declared.json').write_text(json.dumps(DECLARED))
    return tmp_path / 'in/tops.csv', tmp_path / 'in/tops.declared.json'


def run_shift(tmp_path, folder=None, output='out', settings=('shift=2.5',), **extra):
    path, declared = tops(tmp_path)
    return procedures.run(folder or depth_shift(tmp_path), tmp_path / output, {'tops': [str(path)]}, kinds={'tops': 'well-tops-csv/1'},
                          declared={'tops': str(declared)}, settings=list(settings), **extra)


def refused(code, call):
    with pytest.raises(procedures.NotRun) as error: call()
    assert error.value.code == code, (error.value.code, str(error.value))
    return error.value


# ---------------------------------------------------------------- runs

def test_a_process_run_writes_the_outputs_their_declarations_and_run_json(tmp_path):
    result = run_shift(tmp_path)
    out = tmp_path / 'out'
    assert sorted(p.name for p in out.iterdir()) == ['log.txt', 'run.json', 'shifted.csv']
    assert (out / 'shifted.csv').read_bytes() == SHIFTED
    record = json.loads((out / 'run.json').read_text())
    assert record == {
        'schema': 'ophiolite.local-run/0', 'runner': 'this computer', 'systems': {},
        'procedure': {'name': 'depth-shift', 'version': 1, 'digest': '560a8af5fd9a7206b9af0bc04006c36daab12576eecf9eb96396ec3d6ef475bf', 'rules_version': '1.0.0'},
        'settings': {'shift': 2.5, 'mode': 'add', 'count': 1, 'note': '', 'keep': False},
        'inputs': {'tops': [{'file': str((tmp_path / 'in/tops.csv').resolve()), 'sha256': 'bccf61bf244a0fc06d3a489d23f581fef9e51eaa3bdd97830e36dd175f285a9f',
                             'kind': 'well-tops-csv/1', 'declared': DECLARED}]},
        'outputs': {'shifted': {'file': 'shifted.csv', 'sha256': '4ef0ec9db07a6ebd81e1df13d0d2b086563ef5b1ce9ed580a9a01b0266c8ba57', 'profile': 'well-tops-csv/1', 'declared': DECLARED}}}
    assert result['sentence'] == ('Ran Shift tops by a fixed depth, version 1, on this computer: made Well tops (CSV) (out/shifted.csv). '
                                  'Nothing was published.')


def test_a_saved_output_reopens_with_its_declarations(tmp_path):
    """D1: the second run reads the first run's output; its kind and declarations come from that run.json."""
    run_shift(tmp_path)
    procedures.run(depth_shift(tmp_path / 'again'), tmp_path / 'second', {'tops': [str(tmp_path / 'out/shifted.csv')]},
                   settings=['shift=1', 'mode=subtract'])
    record = json.loads((tmp_path / 'second/run.json').read_text())
    assert record['inputs']['tops'][0]['declared'] == DECLARED and record['inputs']['tops'][0]['kind'] == 'well-tops-csv/1'
    assert record['outputs']['shifted']['declared'] == DECLARED
    assert (tmp_path / 'second/shifted.csv').read_bytes() == b'name,md\nTop Chalk,1002\nBase Chalk,1201.5\n'


LAS = '~Version\nVERS. 2.0 : LAS version\n~Well\n'


def test_a_read_run_checks_the_file_signature(tmp_path):
    folder = tmp_path / 'team-las'
    shutil.copytree(FIXTURES / 'bundles/team-las', folder)
    (tmp_path / 'a.las').write_text(LAS)
    procedures.run(folder, tmp_path / 'out', {'file': [str(tmp_path / 'a.las')]})
    assert (tmp_path / 'out/log.las').read_text() == LAS
    assert json.loads((tmp_path / 'out/run.json').read_text())['inputs']['file'][0]['file'] == str((tmp_path / 'a.las').resolve())
    (tmp_path / 'b.las').write_text('not a log\n')
    refused('signature', lambda: procedures.run(folder, tmp_path / 'out2', {'file': [str(tmp_path / 'b.las')]}))
    (tmp_path / 'c.txt').write_text(LAS)
    refused('signature', lambda: procedures.run(folder, tmp_path / 'out3', {'file': [str(tmp_path / 'c.txt')]}))


SOURCE = '''import json
from ophiolite import procedure
from ophiolite.writers import write_location, write_tops


@procedure
def fetch(inputs, settings):
    config = inputs['database'].config
    assert config['password'] == 'hunter2-planted-secret'
    return {'tops': write_tops([{'name': 'Top ' + config['host'], 'md': 1}], depth_unit='m', depth_basis='md'),
            'location': write_location(4.5, 52.1, crs='OGC:CRS84', elevation_reference='MSL')}
'''


def test_a_source_run_uses_local_configuration_and_records_none_of_it(tmp_path):
    """D4: two outputs; the planted credential is in no file the run wrote."""
    folder = tmp_path / 'source'; folder.mkdir()
    manifest = json.loads((FIXTURES / 'valid/source.json').read_text())
    (folder / 'procedure.json').write_text(json.dumps(manifest)); (folder / 'procedure.py').write_text(SOURCE)
    config = tmp_path / 'db.json'
    config.write_text(json.dumps({'host': 'Field', 'user': 'anna', 'password': 'hunter2-planted-secret'}))
    procedures.run(folder, tmp_path / 'out', systems={'database': str(config)})
    written = {p.name: p.read_bytes() for p in (tmp_path / 'out').iterdir()}
    assert sorted(written) == ['location.json', 'log.txt', 'run.json', 'tops.csv']
    assert written['location.json'] == b'{"crs":"OGC:CRS84","elevation_reference":"MSL","x":4.5,"y":52.1}\n'
    assert not any(b'hunter2' in raw or b'anna' in raw for raw in written.values())
    assert json.loads(written['run.json'])['systems'] == {'database': 'configured on this computer'}
    config.write_text(json.dumps({'host': 'Field', 'user': 'anna'}))
    refused('system-config', lambda: procedures.run(folder, tmp_path / 'out2', systems={'database': str(config)}))


def test_an_output_named_like_the_runs_own_files_does_not_replace_them(tmp_path):
    code = ('from ophiolite import procedure\nfrom ophiolite.writers import WrittenOriginal\n\n\n@procedure\ndef shift(inputs, settings):\n'
            "    return {'log': WrittenOriginal(b'name,md\\n', 'well-tops-csv/1', {}, 'tops.txt')}\n")
    outputs = [{'role': 'log', 'label': 'Shifted tops', 'class': 'version', 'kind': 'well-tops-csv/1'}]
    run_shift(tmp_path, folder=depth_shift(tmp_path, code, outputs=outputs))
    assert (tmp_path / 'out/log-output.txt').read_bytes() == b'name,md\n'
    assert json.loads((tmp_path / 'out/run.json').read_text())['outputs']['log']['file'] == 'log-output.txt'


# ---------------------------------------------------------------- lifecycle (M5)

def test_an_existing_destination_or_a_symlink_there_is_refused(tmp_path):
    (tmp_path / 'out').mkdir()
    refused('destination-exists', lambda: run_shift(tmp_path))
    (tmp_path / 'elsewhere').mkdir(); (tmp_path / 'link').symlink_to(tmp_path / 'elsewhere')
    refused('destination-exists', lambda: run_shift(tmp_path, output='link'))
    assert list((tmp_path / 'elsewhere').iterdir()) == []
    (tmp_path / 'dangling').symlink_to(tmp_path / 'nowhere')
    refused('destination-exists', lambda: run_shift(tmp_path, output='dangling'))
    assert not (tmp_path / 'nowhere').exists()


def test_a_destination_overlapping_an_input_or_the_procedure_is_refused(tmp_path):
    folder = depth_shift(tmp_path)
    refused('overlap', lambda: run_shift(tmp_path, folder=folder, output='in/tops.csv/out'))
    refused('overlap', lambda: run_shift(tmp_path, folder=folder, output='depth-shift/out'))
    assert sorted(p.name for p in (tmp_path / 'in').iterdir()) == ['tops.csv', 'tops.declared.json'] and not (folder / 'out').exists()


TWO_THEN_FAIL = '''from ophiolite import procedure
from ophiolite.writers import write_tops


@procedure
def shift(inputs, settings):
    return {'shifted': write_tops([{'name': 'A', 'md': 1}], depth_unit='m', depth_basis='md'), 'broken': object()}
'''


def nothing_left(tmp_path):
    return not (tmp_path / 'out').exists() and not list(tmp_path.glob('out.partial-*'))


def test_a_failure_after_one_output_leaves_nothing(tmp_path):
    refused('returned-wrong', lambda: run_shift(tmp_path, folder=depth_shift(tmp_path, TWO_THEN_FAIL)))
    assert nothing_left(tmp_path)


def test_a_failure_while_writing_the_folder_leaves_no_partial_folder(tmp_path, monkeypatch):
    def full(*args): raise OSError(28, 'No space left on device')
    monkeypatch.setattr(procedures.os, 'rename', full)
    with pytest.raises(OSError): run_shift(tmp_path)
    assert nothing_left(tmp_path)


def test_a_procedure_killed_before_it_returns_leaves_nothing(tmp_path):
    code = 'import os, signal\nfrom ophiolite import procedure\n\n\n@procedure\ndef shift(inputs, settings):\n    os.kill(os.getpid(), signal.SIGKILL)\n'
    refused('stopped', lambda: run_shift(tmp_path, folder=depth_shift(tmp_path, code)))
    assert nothing_left(tmp_path)


def test_an_interrupted_run_never_leaves_the_destination(tmp_path):
    """The parent is killed while the procedure runs: no destination, at most a partial folder."""
    code = 'import time\nfrom ophiolite import procedure\n\n\n@procedure\ndef shift(inputs, settings):\n    time.sleep(3)\n    return {}\n'
    folder = depth_shift(tmp_path, code); path, declared = tops(tmp_path)
    env = {**os.environ, 'PYTHONPATH': str(REPO), 'PYTHONDONTWRITEBYTECODE': '1'}
    parent = subprocess.Popen([sys.executable, '-m', 'ophiolite.cli', 'procedures', 'run', str(folder), '--output', str(tmp_path / 'out'),
                               '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1', '--declared', f'tops={declared}'], env=env)
    time.sleep(1.5); parent.send_signal(signal.SIGKILL); parent.wait()
    time.sleep(2)
    assert not (tmp_path / 'out').exists()


# ---------------------------------------------------------------- the code that runs (D2, M2)

def test_stale_bytecode_beside_the_procedure_never_runs(tmp_path):
    folder = depth_shift(tmp_path)
    stale = folder / '__pycache__' / f'procedure.cpython-{sys.version_info[0]}{sys.version_info[1]}.pyc'
    stale.parent.mkdir()
    import importlib.util, marshal
    code = compile('print("STALE")\nfrom ophiolite import procedure\n@procedure\ndef shift(inputs, settings):\n    return {}\n', 'procedure.py', 'exec')
    source = folder / 'procedure.py'
    stat = source.stat()
    header = importlib.util.MAGIC_NUMBER + (0).to_bytes(4, 'little') + int(stat.st_mtime).to_bytes(4, 'little') + (stat.st_size & 0xFFFFFFFF).to_bytes(4, 'little')
    stale.write_bytes(header + marshal.dumps(code))
    run_shift(tmp_path, folder=folder)
    assert 'STALE' not in (tmp_path / 'out/log.txt').read_text()
    assert (tmp_path / 'out/shifted.csv').read_bytes() == SHIFTED


def test_a_file_changed_after_validation_is_refused(tmp_path, monkeypatch):
    folder = depth_shift(tmp_path)
    monkeypatch.setattr(procedures, '_between', lambda f: (f / 'procedure.py').write_text((f / 'procedure.py').read_text() + '\n# changed\n'))
    refused('changed', lambda: run_shift(tmp_path, folder=folder))
    assert nothing_left(tmp_path)


PROBE = '''import os
import ophiolite.writers
from ophiolite import procedure
from ophiolite.writers import write_tops


@procedure
def shift(inputs, settings):
    ophiolite.writers.TOUCHED_BY_THE_PROCEDURE = True
    return {'shifted': write_tops([{'name': 'pid', 'md': os.getpid()}], depth_unit='m', depth_basis='md')}
'''


def test_the_procedure_runs_in_another_process(tmp_path):
    import ophiolite.writers
    run_shift(tmp_path, folder=depth_shift(tmp_path, PROBE))
    pid = int((tmp_path / 'out/shifted.csv').read_text().splitlines()[1].split(',')[1])
    assert pid != os.getpid() and pid > 0
    assert not hasattr(ophiolite.writers, 'TOUCHED_BY_THE_PROCEDURE')


# ---------------------------------------------------------------- settings (M4)

@pytest.mark.parametrize('given,code,label', [
    (['shift=true'], 'setting-type', 'Depth shift'), (['shift=nan'], 'setting-type', 'Depth shift'), (['shift=inf'], 'setting-type', 'Depth shift'),
    (['shift=1e999'], 'setting-type', 'Depth shift'), (['shift=1001'], 'setting-bounds', 'Depth shift'),
    (['count=2.0'], 'setting-type', 'Number of passes'), (['count=true'], 'setting-type', 'Number of passes'),
    (['keep=yes'], 'setting-type', 'Keep empty tops'), (['keep=1'], 'setting-type', 'Keep empty tops'),
    (['mode=Add the shift'], 'setting-type', 'How to shift'), (['shift=1', 'shift=2'], 'setting-twice', 'Depth shift'),
    (['depth=1'], 'setting-unknown', None), (['shift'], 'setting-format', None)])
def test_settings_are_typed_strictly(tmp_path, given, code, label):
    error = refused(code, lambda: run_shift(tmp_path, settings=given))
    if label: assert label in str(error)
    assert 'depth_shift' not in str(error) and nothing_left(tmp_path)


def test_settings_take_their_defaults_and_typed_values(tmp_path):
    manifest = json.loads((FIXTURES / 'bundles/depth-shift/procedure.json').read_text())
    assert procedures._setting_values(manifest, ['count=3', 'keep=true', 'shift=-2.5e1', 'mode=subtract', 'note=from the log']) == {
        'shift': -25.0, 'mode': 'subtract', 'count': 3, 'note': 'from the log', 'keep': True}
    assert procedures._setting_values(manifest, []) == {'shift': 0, 'mode': 'add', 'count': 1, 'note': '', 'keep': False}
    del manifest['settings'][0]['default']
    refused('setting-missing', lambda: procedures._setting_values(manifest, []))


# ---------------------------------------------------------------- refusals

def test_inputs_and_outputs_are_checked(tmp_path):
    path, declared = tops(tmp_path)
    folder = depth_shift(tmp_path)
    refused('missing-input', lambda: procedures.run(folder, tmp_path / 'o1', {}))
    refused('too-many-inputs', lambda: procedures.run(folder, tmp_path / 'o2', {'tops': [str(path), str(path)]}, kinds={'tops': 'well-tops-csv/1'}))
    refused('no-kind', lambda: procedures.run(folder, tmp_path / 'o3', {'tops': [str(path)]}))
    refused('wrong-kind', lambda: procedures.run(folder, tmp_path / 'o4', {'tops': [str(path)]}, kinds={'tops': 'las2/1'}))
    refused('unknown-input', lambda: procedures.run(folder, tmp_path / 'o5', {'tops': [str(path)], 'other': [str(path)]}, kinds={'tops': 'well-tops-csv/1'}))
    (tmp_path / 'bad.json').write_text('[1]')
    refused('bad-declared', lambda: procedures.run(folder, tmp_path / 'o6', {'tops': [str(path)]}, kinds={'tops': 'well-tops-csv/1'}, declared={'tops': str(tmp_path / 'bad.json')}))


@pytest.mark.parametrize('code,body', [
    ('missing-output', "    return {}\n"),
    ('extra-output', "    return {'shifted': write_tops([{'name': 'A', 'md': 1}], depth_unit='m', depth_basis='md'), 'extra': write_tops([{'name': 'B', 'md': 2}], depth_unit='m', depth_basis='md')}\n"),
    ('wrong-profile', "    return {'shifted': WrittenOriginal(b'~Version', 'las2/1', {}, 'a.las')}\n"),
    ('returned-wrong', "    return [1]\n"),
])
def test_what_the_procedure_returns_is_checked_against_what_it_declares(tmp_path, code, body):
    source = 'from ophiolite import procedure\nfrom ophiolite.writers import WrittenOriginal, write_tops\n\n\n@procedure\ndef shift(inputs, settings):\n' + body
    refused(code, lambda: run_shift(tmp_path, folder=depth_shift(tmp_path, source)))
    assert nothing_left(tmp_path)


def test_an_unmarked_entry_is_refused(tmp_path):
    code = 'def shift(inputs, settings):\n    return {}\n'
    refused('not-marked', lambda: run_shift(tmp_path, folder=depth_shift(tmp_path, code)))


def test_send_and_check_procedures_validate_but_do_not_run(tmp_path):
    for step in ('send', 'check'):
        folder = tmp_path / step; folder.mkdir()
        (folder / 'procedure.json').write_text((FIXTURES / f'valid/{step}.json').read_text()); (folder / 'procedure.py').write_text('')
        assert procedures.validate(folder)['valid']
        error = refused('later-release', lambda: procedures.run(folder, tmp_path / f'{step}-out'))
        assert str(error) == f'Not run: running a {step} procedure comes with a later release.'


# ---------------------------------------------------------------- what the person sees (V1, V3)

NOISY = '''from ophiolite import procedure


@procedure
def shift(inputs, settings):
    print('depth_shift alice-7f3a')
    raise ValueError('depth_shift failed for alice-7f3a')
'''


def cli_run(capsys, argv):
    with pytest.raises(SystemExit) as stop: cli.main(argv)
    captured = capsys.readouterr()
    return stop.value.code, captured.out, captured.err


def test_identifiers_the_procedure_prints_or_raises_stay_out_of_the_default_line(tmp_path, capsys):
    folder = depth_shift(tmp_path, NOISY); path, declared = tops(tmp_path)
    argv = ['procedures', 'run', str(folder), '--output', str(tmp_path / 'out'), '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1', '--declared', f'tops={declared}']
    code, out, err = cli_run(capsys, argv)
    assert (code, out, err) == (1, '', 'Not run: the procedure stopped with an error. Its details are under --json.\n')
    code, out, err = cli_run(capsys, argv + ['--json'])
    error = json.loads(out)['error']
    assert code == 1 and error['code'] == 'raised' and error['details']['message'] == 'depth_shift failed for alice-7f3a'
    assert 'depth_shift alice-7f3a' in error['details']['log']


def test_what_a_successful_procedure_prints_goes_to_log_txt(tmp_path, capsys):
    code = 'from ophiolite import procedure\nfrom ophiolite.writers import write_tops\n\n\n@procedure\ndef shift(inputs, settings):\n    print("depth_shift alice-7f3a")\n    return {"shifted": write_tops([{"name": "A", "md": 1}], depth_unit="m", depth_basis="md")}\n'
    folder = depth_shift(tmp_path, code); path, declared = tops(tmp_path)
    cli.main(['procedures', 'run', str(folder), '--output', str(tmp_path / 'out'), '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1', '--declared', f'tops={declared}'])
    out = capsys.readouterr().out
    assert 'alice-7f3a' not in out and out.startswith('Ran Shift tops by a fixed depth, version 1, on this computer')
    assert (tmp_path / 'out/log.txt').read_text() == 'depth_shift alice-7f3a\n'


def test_validate_says_words_and_puts_identifiers_under_json(tmp_path, capsys):
    folder = depth_shift(tmp_path, settings=[{'key': 'shift', 'label': 'depth_shift', 'type': 'number'}])
    code, out, err = cli_run(capsys, ['procedures', 'validate', str(folder)])
    assert (code, out) == (1, 'Not valid: setting 1 needs a readable label, for example "Depth shift".\n')
    code, out, err = cli_run(capsys, ['procedures', 'validate', str(folder), '--json'])
    assert json.loads(out) == {'valid': False, 'rules_version': '1.0.0', 'sentence': 'Not valid: setting 1 needs a readable label, for example "Depth shift".',
                               'code': 'unreadable-label', 'field': '/settings/0/label'}
    assert cli.main(['procedures', 'validate', str(FIXTURES / 'bundles/depth-shift'), '--json'])['digest'] == '560a8af5fd9a7206b9af0bc04006c36daab12576eecf9eb96396ec3d6ef475bf'


@pytest.mark.parametrize('step', ['read', 'source', 'process', 'send', 'check'])
def test_new_writes_a_folder_that_validates(tmp_path, capsys, step):
    folder = tmp_path / 'my-procedure'
    cli.main(['procedures', 'new', str(folder), '--step', step, '--label', 'Shift tops by a fixed depth'])
    assert capsys.readouterr().out == f'Created my-procedure with procedure.json and procedure.py. Edit them, then run: ophiolite procedures validate {folder}\n'
    assert procedures.validate(folder)['valid']
    assert json.loads((folder / 'procedure.json').read_text())['step'] == step


# ---------------------------------------------------------------- existing commands (F3)

def test_every_earlier_subcommand_keeps_its_name_and_help():
    import argparse
    frozen = json.loads((Path(__file__).parent / 'fixtures/cli-subcommands-0.3.json').read_text())
    sub = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction))
    now = {choice.dest: choice.help for choice in sub._choices_actions}
    assert {name: now.get(name) for name in frozen} == frozen
    assert set(now) - set(frozen) == {'procedures'}
