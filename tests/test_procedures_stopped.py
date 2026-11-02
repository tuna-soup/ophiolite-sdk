"""E123 SZ C2: a procedure stops on purpose with procedures.Stopped, and the person reads its sentence (B4); a plain
exception still gives the generic 'raised'. Binding an input hashes it in blocks (A1). Mutations: the Stopped branch in
_child removed (both Stopped tests RED); _sha256 reading the file whole (the streaming test RED)."""
import json
from pathlib import Path

import pytest

from ophiolite import procedures
from test_procedures_run import cli_run, depth_shift, run_shift, tops

ASKS = '''from ophiolite import procedure
from ophiolite.procedures import Stopped


@procedure
def shift(inputs, settings):
    raise Stopped("Choose the coordinate system and confirm the vertical domain. {crs} stays literal.", asks=True)
'''
REFUSES = ASKS.replace('"Choose the coordinate system and confirm the vertical domain. {crs} stays literal.", asks=True', '"The file states feet (factor 0.3048); only metres are read."')
PLAIN = ASKS.replace('raise Stopped("Choose the coordinate system and confirm the vertical domain. {crs} stays literal.", asks=True)', 'raise ValueError("internal detail")')


def test_a_procedure_that_asks_is_not_run_yet_with_its_question(tmp_path):
    with pytest.raises(procedures.NotRun) as stop: run_shift(tmp_path, depth_shift(tmp_path, ASKS))
    assert stop.value.code == 'asked' and stop.value.field == '/entry'
    assert str(stop.value).startswith('Not run yet: Choose the coordinate system and confirm the vertical domain.')
    assert '{crs} stays literal' in str(stop.value)  # the sentence is not a format template
    assert not (tmp_path / 'out').exists()


def test_a_procedure_that_refuses_shows_its_sentence(tmp_path):
    with pytest.raises(procedures.NotRun) as stop: run_shift(tmp_path, depth_shift(tmp_path, REFUSES))
    assert stop.value.code == 'procedure-stopped'
    assert str(stop.value) == 'Not run: The file states feet (factor 0.3048); only metres are read.'


def test_the_cli_prints_the_procedures_sentence(tmp_path, capsys):
    folder = depth_shift(tmp_path, REFUSES); path, declared = tops(tmp_path)
    argv = ['procedures', 'run', str(folder), '--output', str(tmp_path / 'out'), '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1',
            '--declared', f'tops={declared}', '--setting', 'shift=2.5']
    code, out, err = cli_run(capsys, argv)
    assert (code, out) == (1, '') and 'only metres are read' in err


def test_a_plain_exception_stays_raised(tmp_path):
    with pytest.raises(procedures.NotRun) as stop: run_shift(tmp_path, depth_shift(tmp_path, PLAIN))
    assert stop.value.code == 'raised' and 'internal detail' not in str(stop.value)
    assert stop.value.details['message'] == 'internal detail'


def test_binding_an_input_hashes_it_in_blocks(tmp_path, monkeypatch):
    path, _ = tops(tmp_path)
    expected = procedures.hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def whole(self): raise AssertionError('read whole')
    monkeypatch.setattr(Path, 'read_bytes', whole)
    assert procedures._sha256(path) == expected
