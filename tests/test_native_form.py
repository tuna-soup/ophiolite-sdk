"""E140 s0: the 8-bit cube (`ophiolite.seismic-volume/2`, profile `segy/2`) in the SDK. C1: the offline invariants
mirror the server's semantic rules with the same sentences (strategy C1 test 2c). The fixture is synthetic: the
description and envelope of ophiolite-connectors/tests/fixtures/native_form/native_cube.json, copied into the SDK's
own tree (the gateway's test_native_form_contract.py asserts the copy equal)."""
import copy
import json
import math
import struct
from pathlib import Path

import pytest
from ophiolite import native_form, starter_archive
from ophiolite.errors import VerificationFailed
from ophiolite.models import invariants

CUBE = json.loads((Path(__file__).parent / 'fixtures/native_form/native_cube.json').read_text())


def test_the_fixture_description_and_envelope_hold():
    invariants.typed_payload(copy.deepcopy(CUBE['description']))
    invariants.asset(copy.deepcopy(CUBE['envelope']))


PAYLOAD = [
    ('trace length of float words', 'Trace count, grid and trace length disagree', lambda d: d['context'].update(trace_bytes=240 + 4 * 11)),
    ('grid product not the traces', 'Trace count, grid and trace length disagree', lambda d: d['context'].update(traces=36)),
    ('chunk of float words', 'A chunk has the wrong size', lambda d: d['chunks'][2].update(bytes=308)),
]


@pytest.mark.parametrize('name,message,mutate', PAYLOAD, ids=[s[0] for s in PAYLOAD])
def test_a_native_description_is_checked_with_one_byte_samples(name, message, mutate):
    """Mutation: sample_width returns 4 for format 8 (RED: the valid fixture fails on its trace length)."""
    doc = copy.deepcopy(CUBE['description'])
    mutate(doc)
    with pytest.raises(VerificationFailed, match=message):
        invariants.typed_payload(doc)


def float_profile(e):
    e['profile'] = e['source_reference']['profile'] = e['representations'][0]['profile'] = 'segy/1'
    e['representations'][1]['profile'] = 'ophiolite.seismic-volume/1'
    e['interpretation']['mapping'] = 'seismic-volume/1'


def float_context(e):
    e['scientific'] = dict(copy.deepcopy(e['scientific']), format='IEEE 4-byte floating point', format_code=5, trace_bytes=284)
    del e['scientific']['undefined_code']


ENVELOPE = [
    ('profile segy/1 with a native context', 'An 8-bit seismic cube is described through profile segy/2, and only it', float_profile),
    ('normalized /1 with a native context', 'Representation profiles must be the asset profile and its normalized profile',
     lambda e: e['representations'][1].update(profile='ophiolite.seismic-volume/1')),
    ('mapping /1 with a native context', 'Interpretation is not the one this profile declares', lambda e: e['interpretation'].update(mapping='seismic-volume/1')),
    ('a /2 envelope with a float context', 'An 8-bit seismic cube is described through profile segy/2, and only it', float_context),
]


@pytest.mark.parametrize('name,message,mutate', ENVELOPE, ids=[s[0] for s in ENVELOPE])
def test_the_envelope_names_one_path_for_the_native_form(name, message, mutate):
    doc = copy.deepcopy(CUBE['envelope'])
    mutate(doc)
    with pytest.raises(VerificationFailed, match=message):
        invariants.asset(doc)


# --- C2: the client's own decoder (ophiolite.native_form; struct only) ---------------------------------------------

def code_bytes(codes): return struct.pack('>%db' % len(codes), *codes)


def hexes(bits): return ['%08x' % b for b in bits]


def test_every_code_decodes_to_its_literal_pattern():
    """C2 test 1. Mutations: -128 decoded as -128.0 under -128 (RED); the NaN as 7fc00001 (RED); null as -128 (RED)."""
    codes = [int(c) for c in CUBE['patterns']]
    assert hexes(native_form.decode(code_bytes(codes), -128)) == list(CUBE['patterns'].values())
    assert CUBE['patterns']['-128'] == '7fc00000' and CUBE['patterns']['-1'] == 'bf800000' and CUBE['patterns']['127'] == '42fe0000'
    nulls = [c for p in CUBE['null_case']['codes'] for t in p for c in t]
    assert hexes(native_form.decode(code_bytes(nulls), None)) == ['c3000000', '00000000', '42fe0000'] == list(CUBE['null_case']['patterns'].values())
    assert math.isnan(native_form.values(b'\x80', -128)[0]) and native_form.values(b'\x80\x7f', None) == [-128.0, 127.0]


def test_the_same_bytes_differ_only_at_code_minus_128():
    """C2 test 6."""
    codes = [int(c) for c in CUBE['patterns']] + [-128, 5, -128]
    under_minus, under_none = native_form.decode(code_bytes(codes), -128), native_form.decode(code_bytes(codes), None)
    assert {c for c, a, b in zip(codes, under_minus, under_none) if a != b} == {-128}
    with pytest.raises(ValueError): native_form.decode(b'\x00', 0)


AXES = {'inline': [100, 108, 2], 'crossline': [300, 330, 5], 'z': [12, 2500, 11]}


def test_the_d9_header_binds_the_form_and_the_code_for_no_value():
    """C2 test 5. Mutation: form dropped from the native header (RED). The float header is the b36e1d2e4 literal."""
    assert native_form.head('seismic-3d', 'cube', AXES, -128) == (
        b'{"axes":{"crossline":[300,330,5],"inline":[100,108,2],"z":[12,2500,11]},"form":"int8","kind":"seismic-3d","object":"cube",'
        b'"undefined_code":-128}\n')
    assert native_form.head('seismic-3d', 'cube', AXES, None).endswith(b'"form":"int8","kind":"seismic-3d","object":"cube","undefined_code":null}\n')
    assert starter_archive.head('seismic-3d', 'cube', AXES) == (
        b'{"axes":{"crossline":[300,330,5],"inline":[100,108,2],"z":[12,2500,11]},"kind":"seismic-3d","object":"cube"}\n')
