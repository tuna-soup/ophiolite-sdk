"""E129 Sa C2 (strategy rev 4, D5, R8, M3): `fidelity.written` checks every argument it is given, and `checked` pairs
`output` with converted and partial and `reason` with partial and failed, as OSD's fidelity schema does. Literals only:
validation under the pinned schema is project_gateway/tests/test_starter_fidelity.py.

Mutations (recorded in the E129 Sa Validation Record):
1. the result-enum check removed from `written`: the 'outside the enum' case fails;
2. the old pairing restored in `checked`: the valid-partial case fails."""
import copy

import pytest

from ophiolite import fidelity
from ophiolite.errors import Refused

SNAPSHOT = {'source_commit': '1' * 40, 'verification_commit': None, 'built_at': '2026-10-28T00:00:00Z', 'records_digest': 'd' * 64}
RECORD = 'ophiolite-synthetic/two-wells'
OUTPUT = {'kind': 'wellbore-logs', 'id': 'item-1', 'converter': 'asset_connectors.las_reader', 'version': '1'}
CONVERTED = {'sha256': 'a' * 64, 'name': 'syn-1.las', 'result': 'converted', 'output': OUTPUT,
             'representative': [{'field': 'GR@1000.0', 'value': 45.0, 'unit': 'GAPI'}]}
PARTIAL = {'sha256': 'b' * 64, 'name': 'syn-2.las', 'result': 'partial', 'output': dict(OUTPUT, id='item-2'), 'reason': 'One curve was not read.'}
FAILED = {'sha256': 'c' * 64, 'name': 'syn-1-tops.csv', 'result': 'failed', 'reason': 'Not added.'}
SKIPPED = {'sha256': 'e' * 64, 'name': 'syn-1-deviation.csv', 'result': 'skipped'}


def test_written_returns_the_document_and_copies_its_arguments():
    inputs = [CONVERTED, PARTIAL, FAILED, SKIPPED]
    doc = fidelity.written(SNAPSHOT, RECORD, inputs)
    assert doc == {'format': 'osd.fidelity/1', 'catalog': SNAPSHOT, 'record': RECORD, 'inputs': inputs}
    assert doc['catalog'] is not SNAPSHOT and doc['inputs'][0] is not CONVERTED


def test_a_valid_partial_entry_passes_checked():
    assert fidelity.checked({'format': 'osd.fidelity/1', 'catalog': SNAPSHOT, 'record': RECORD, 'inputs': [PARTIAL]})['inputs'] == [PARTIAL]


def without(entry, key):
    return {k: v for k, v in entry.items() if k != key}


MALFORMED = {
    'a catalogue snapshot with a missing key': ({k: v for k, v in SNAPSHOT.items() if k != 'source_commit'}, RECORD, [CONVERTED],
                                                'the catalogue snapshot needs exactly source_commit, verification_commit, built_at, records_digest'),
    'a bad built_at': (dict(SNAPSHOT, built_at='yesterday'), RECORD, [CONVERTED], 'built_at is not a date-time'),
    'a short records_digest': (dict(SNAPSHOT, records_digest='d' * 63), RECORD, [CONVERTED], 'records_digest is not a SHA-256'),
    'a commit that is not one': (dict(SNAPSHOT, source_commit='HEAD'), RECORD, [CONVERTED], 'source_commit is not a commit'),
    'a record not of the form': (SNAPSHOT, 'two-wells', [CONVERTED], 'the record id is not of the form <publisher>/<dataset>'),
    'no inputs': (SNAPSHOT, RECORD, [], 'there are no inputs'),
    'an unknown field': (SNAPSHOT, RECORD, [dict(CONVERTED, note='x')], 'input 1 is not of the schema'),
    'a missing result': (SNAPSHOT, RECORD, [without(CONVERTED, 'result')], 'input 1 is not of the schema'),
    'a result outside the enum': (SNAPSHOT, RECORD, [CONVERTED, dict(SKIPPED, result='landed')], "input 2 has result 'landed'"),
    'an output that is not an object': (SNAPSHOT, RECORD, [dict(CONVERTED, output='item-1')], 'input 1 is not of the schema'),
}


@pytest.mark.parametrize('case', sorted(MALFORMED))
def test_written_refuses_each_malformed_argument(case):
    snapshot, rid, inputs, what = MALFORMED[case]
    with pytest.raises(Refused) as refused:
        fidelity.written(snapshot, rid, inputs)
    assert str(refused.value) == 'A fidelity document cannot be written: %s. No fidelity document was written.' % what


SCHEMA_RULES = {
    'converted without output': (without(CONVERTED, 'output'), 'syn-1.las'),
    'partial without reason': (without(PARTIAL, 'reason'), 'syn-2.las'),
    'partial without output': (without(PARTIAL, 'output'), 'syn-2.las'),
    'failed without reason': (without(FAILED, 'reason'), 'syn-1-tops.csv'),
    'skipped with a reason': (dict(SKIPPED, reason='x'), 'syn-1-deviation.csv'),
    'a short sha256': (dict(CONVERTED, sha256='a' * 63), 'syn-1.las'),
    'an empty name': (dict(CONVERTED, name=''), '?'),
}


@pytest.mark.parametrize('case', sorted(SCHEMA_RULES))
def test_written_refuses_what_the_schema_refuses(case):
    entry, name = SCHEMA_RULES[case]
    with pytest.raises(Refused) as refused:
        fidelity.written(SNAPSHOT, RECORD, [copy.deepcopy(entry)])
    assert str(refused.value) == "This upload's files cannot be described exactly (%s). No fidelity document was written." % name
