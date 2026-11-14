"""E175 s0 C1: a cube as published (`ophiolite.seismic-volume/3`, profile `segy/3`) in the SDK. The offline invariants
mirror the server's semantic rules with the same sentences. Documents are synthetic, written here from the float
fixture of the contract snapshot: a format 3 cube of 2 inlines x 3 crosslines, 4 samples, one position without a trace."""
import copy
import json

import pytest
from importlib.resources import files
from ophiolite.errors import VerificationFailed
from ophiolite.models import invariants

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
FLOAT = json.loads(FIXTURES.joinpath('seismic.json').read_text())
FLOAT_DATA = json.loads(FIXTURES.joinpath('seismic-data.json').read_text())


def context(**changes):
    c = copy.deepcopy(FLOAT['scientific'])
    c.update(format="2-byte two's complement integer", format_code=3, traces=5, cells=6, absent=1, trace_bytes=248)
    c.update(changes)
    return c


def described():
    d = copy.deepcopy(FLOAT_DATA)
    d.update(schema='ophiolite.seismic-volume/3', context=context(), decisions=list(FLOAT['scientific']['fidelity']['decisions']))
    d['source']['profile'] = 'segy/3'
    d['interpretation']['mapping'] = 'seismic-volume/3'
    d['chunks'] = [{'inline': 10, 'traces': 3, 'sha256': '1' * 64, 'bytes': 24}, {'inline': 12, 'traces': 2, 'sha256': '2' * 64, 'bytes': 16}]
    return d


def enveloped():
    e = copy.deepcopy(FLOAT)
    e['profile'] = e['source_reference']['profile'] = e['representations'][0]['profile'] = 'segy/3'
    e['representations'][1]['profile'] = 'ophiolite.seismic-volume/3'
    e['interpretation']['mapping'] = 'seismic-volume/3'
    e['scientific'] = context()
    return e


def test_a_published_description_holds_at_two_bytes_a_sample():
    """Mutation: sample_width returns 4 for format 3 (RED: the trace length and the chunk sizes fail)."""
    invariants.typed_payload(described())
    assert [invariants.sample_width({'format_code': code}) for code in (1, 2, 3, 5, 8)] == [4, 4, 2, 4, 1]


PAYLOAD = [
    ('absent not cells less traces', 'The positions without a trace are the cells less the traces', lambda d: d['context'].update(absent=2)),
    ('cells not inlines times crosslines', 'The cell count is not inlines times crosslines', lambda d: d['context'].update(cells=7, absent=2)),
    ('format and code disagree', 'The sample format and its code disagree', lambda d: d['context'].update(format="4-byte two's complement integer")),
    ('trace bytes at width 4', 'Trace length and sample count disagree', lambda d: d['context'].update(trace_bytes=256)),
    ('chunk bytes off by one width', 'A chunk has the wrong size', lambda d: d['chunks'][1].update(bytes=18)),
    ('chunk traces not the traces', 'The chunks do not hold every trace', lambda d: d['chunks'][1].update(traces=3, bytes=24)),
    ('chunks out of order', 'Chunks do not follow the inline numbers', lambda d: d['chunks'].reverse()),
]


@pytest.mark.parametrize('name,message,mutate', PAYLOAD, ids=[s[0] for s in PAYLOAD])
def test_a_hand_broken_description_is_refused_with_the_servers_sentence(name, message, mutate):
    doc = described()
    mutate(doc)
    with pytest.raises(VerificationFailed, match=message):
        invariants.typed_payload(doc)


def test_the_envelope_names_one_path_for_the_published_form():
    invariants.asset(enveloped())
    for mutate in (lambda e: e.update(profile='segy/1'), lambda e: e.update(scientific=copy.deepcopy(FLOAT['scientific']))):
        e = enveloped()
        mutate(e)
        with pytest.raises(VerificationFailed, match='A seismic cube as published is described through profile segy/3, and only it'):
            invariants.asset(e)
