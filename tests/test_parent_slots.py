"""E119b D2, offline: the SDK names a result's parents by the contract's one rule (`procedure.parent_slots`), the rule
the Gateway's `claim_locked` checks the header against. In this version no slot is pinned, so a residual procedure's
parents are every slot in manifest order, the selection included (private mode, Q-1). Literals by hand."""
import json
from pathlib import Path

import ophiolite
from ophiolite import procedures

FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'


def test_a_residual_procedures_parents_are_every_slot_in_manifest_order():
    """Mutation: leave the selection out of `parent_slots` -> the list starts with 'tops' -> red."""
    manifest = json.loads((FIXTURES / 'valid/process-residual.json').read_text())
    assert procedures.parent_slots(manifest) == ['selection', 'tops', 'surface', 'trajectories']


def test_the_shape_built_from_a_local_record_gives_the_same_slots():
    """`procedure_publish` builds the rule's input from the local record (slot names and output profiles only)."""
    shape = {'step': 'process', 'inputs': [{'slot': s} for s in ('selection', 'tops', 'surface', 'trajectories')], 'outputs': [{'kind': 'well-residual/1'}]}
    assert procedures.parent_slots(shape) == ['selection', 'tops', 'surface', 'trajectories']


def test_another_procedures_parents_are_its_slots():
    shape = {'step': 'process', 'inputs': [{'slot': 'tops'}, {'slot': 'reference'}], 'outputs': [{'kind': 'well-tops-csv/1'}]}
    assert procedures.parent_slots(shape) == ['tops', 'reference']
