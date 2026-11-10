"""E160 s0 C2: one implementation. The SDK runs the converter of its contracts snapshot (work_turns.py, loaded from its
source text like descriptors.py, so no bytecode lands in the snapshot) over the snapshot's own fixture folders: the
lines equal turns.jsonl byte for byte and every row comes back unchanged. Mutation (logs/c2-mutations.txt): the
snapshot's mapping with two places swapped -> the literal lines FAIL."""
import json
import types
from pathlib import Path

import pytest

import ophiolite

V1 = Path(ophiolite.__file__).parent / 'contracts/scientific/v1'
CACHE = V1 / '__pycache__'  # an installed wheel has one already (pip compiles); loading the converter adds nothing
BEFORE = sorted(CACHE.iterdir()) if CACHE.exists() else None  # at import, before any test here loads the converter


def converter():
    path = V1 / 'work_turns.py'
    module = types.ModuleType('ophiolite_work_turns_contract')
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


@pytest.mark.parametrize('name, count', [('shape', 3), ('auto', 4), ('empty', 0)])
def test_the_snapshot_converter_writes_the_snapshot_lines(name, count):
    c, folder = converter(), V1 / 'fixtures/work-turns' / name
    episodes = [json.loads(line) for line in (folder / 'episodes.jsonl').read_text().splitlines()]
    raw = (folder / 'turns.jsonl').read_bytes()
    assert b''.join(c.canonical(line) + b'\n' for e in episodes for line in c.turns(e)) == raw
    assert raw.count(b'\n') == count
    rows = [r for e in episodes for r in e['rows']]
    assert [c.canonical(c.row(json.loads(line))) for line in raw.splitlines()] == [c.canonical(r) for r in rows]


def test_no_bytecode_beside_the_contract():
    converter()
    assert (sorted(CACHE.iterdir()) if CACHE.exists() else None) == BEFORE
