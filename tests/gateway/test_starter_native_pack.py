"""E140 s3 C5 (strategy D-S): the starter end to end on an 8-bit cube. The fake odbind holds Syn as codes (through
FAKE_ODBIND_STATE, so the exporter's own process reads them), under each undefined-code choice, beside the float Syn2;
the real exporter (`ophiolite_opendtect.export --forms int8`), the report, the inventory, the declarations, the landing
and the Python target's expected values all run as the starter runs them. Nothing is injected.

Syn's code at inline i, crossline c, sample k is i - c + 10 k (-16 .. 36), on the default grid (inlines 10-16 step 2,
crosslines 20-26 step 2, five samples). Its first sample (inline 10, crossline 20, k 0) is NaN under `-128` (the exporter
writes code -128 and card 5 `UNDEFINED -128`) and a defined -128 under `none` (no NaN, card 5 `UNDEFINED NONE`). Inline
12, which the Python target reads, holds neither (the notebook reads codes with segyio, so a -128 there would differ:
recorded in C5's commit). Counted by hand: crosslines 20, 22 and 26 at sample 2 are 32 - c = 12, 10 and 6; the inline's
sum is 5 x (4 x 12 - 92) + 4 x 100 = 180.

The pack targets' readers in conformance/roundtrip (the journey's cube reader and the window read-back) are tested
here too, on test_starter_native's hand-built files: format 8 to the literal floats, a format-8 line still refused."""
import importlib.util
import json
import math
import os
import pickle
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

from ophiolite import starter
from test_starter_archive_pack import build, project  # noqa: F401 (project: a fixture)
from test_starter_export import CONNECTOR, FAKE, made, run
from test_starter_native import LITERAL, bits, segy
from test_starter_python import both

ROOT = Path(__file__).resolve().parents[3]

INLINES, CROSSLINES = range(10, 17, 2), range(20, 27, 2)
CHOICES = {'-128': (math.nan, -128, '-128'), 'none': (-128.0, None, 'none')}  # first sample, export's code, declaration


def code(i, c, k): return i - c + 10 * k


def odbind_state(path, first):
    """The fake odbind's state file: Syn as codes, its first sample FIRST; Syn2 stays the fake's float cube."""
    lines = {i: np.array([[code(i, c, k) for k in range(5)] for c in CROSSLINES], dtype=np.float32) for i in INLINES}
    lines[10][0, 0] = first
    syn = {'id': '100010.1', 'inlrg': [10, 16, 2], 'crlrg': [20, 26, 2], 'zrg': [100.0, 116.0, 4.0], 'comps': ['Component 1'],
           'format': 'CBVS', 'zistime': True, 'lines': lines}
    with open(path, 'wb') as f: pickle.dump({'cubes': {'Syn': syn}, 'horizons': {}}, f)


@pytest.fixture(scope='module', params=sorted(CHOICES))
def exported(request, tmp_path_factory):
    """(choice, definition folder, export OUT): the real exporter's run on the fake odbind of CHOICE."""
    choice = request.param
    where = tmp_path_factory.mktemp('native-' + choice)
    folder, export = made(where / 'definition', edit=both), where / 'export'
    export.mkdir()
    odbind_state(where / 'odbind-state.pickle', CHOICES[choice][0])
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.setenv('FAKE_ODBIND_STATE', str(where / 'odbind-state.pickle'))
        run(folder, export)
    return choice, folder, export


def landed(p, name):
    """(profile, declared) the intake read the file NAME (its pack path's last part) as."""
    (hit,) = [v for k, v in p.read.items() if k.split('/')[-1] == name]
    return hit[0], hit[1]


def test_the_native_cube_lands_as_segy_2_with_its_code_and_the_float_cube_as_segy_1(exported, project):
    """Catches: the form dropped at the inventory (Syn would land as segy/1 and its codes be refused or misread), or the
    undefined code dropped at the declarations (segy/2 sent without it)."""
    choice, folder, export = exported
    _, code_of, declared = CHOICES[choice]
    report = json.loads((export / json.loads((export / 'derived.json').read_text())['export'] / 'derived.json').read_text())
    forms = {f['path']: (f.get('form'), f.get('undefined_code', False)) for f in report['files'] if f['kind'] == 'seismic-3d'}
    assert forms == {'seismic/Syn.sgy': ('int8', code_of), 'seismic/Syn2.sgy': (None, False)}
    build(folder, export, project)
    profile, sent = landed(project, 'Syn.sgy')
    assert profile == 'segy/2' and sent['undefined_code'] == declared
    profile, sent = landed(project, 'Syn2.sgy')
    assert profile == 'segy/1' and 'undefined_code' not in sent


def test_the_python_target_expects_the_literal_floats_of_the_codes(exported, project):
    """Catches: cube_inline reading the native cube as float words (the expected values would not be the codes)."""
    choice, folder, export = exported
    build(folder, export, project, pack='pack-' + choice)
    expected = json.loads((folder / ('pack-' + choice) / 'files' / starter.PY_EXPECTED).read_text())
    assert (expected['cube'], expected['inline'], expected['crosslines'], expected['z']) == ('seismic/Syn.sgy', 12, [20, 26, 2], [100, 4000, 5])
    assert expected['samples'] == [{'crossline': 20, 'index': 2, 'value': 12.0}, {'crossline': 22, 'index': 2, 'value': 10.0},
                                   {'crossline': 26, 'index': 2, 'value': 6.0}]
    assert expected['inline_sum'] == 180.0
    raw = (folder / ('pack-' + choice) / 'files' / 'seismic' / 'Syn.sgy').read_bytes()
    card = {'-128': '-128', 'none': 'NONE'}[choice]
    assert struct.unpack_from('>h', raw, 3224)[0] == 8 and raw[320:400].decode().rstrip() == 'C 5 OPHIOLITE 8-BIT CODES; UNDEFINED ' + card
    assert struct.unpack_from('b', raw, 3600 + 240)[0] == -128  # inline 10, crossline 20, sample 0: no value, or the value -128


# -- the pack targets' readers in conformance/roundtrip ---------------------------------------------------------------

def roundtrip(name):
    """conformance/roundtrip/NAME.py, loaded once under the key the other round-trip tests use."""
    key = 'roundtrip_' + name
    if key in sys.modules: return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / 'conformance/roundtrip' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[key] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize('undefined_code, card', [(-128, '-128'), (None, 'NONE')])
def test_the_journey_reads_a_format_8_cube_to_the_literal_floats(tmp_path, undefined_code, card):
    """Catches: the journey's cube reader decoding the codes as IEEE or IBM words, or with four bytes a sample."""
    journey = roundtrip('journey')
    path = segy(tmp_path / 'C.sgy', card)
    z, inlines, parts = journey.segy_parts(path)
    assert (z, inlines, journey.segy_traces(path)) == ([0, 8.0, 4.0], [1, 2], 2)
    held = dict(parts)
    assert held[1][(1, 5)][:2] == (1.0, 2.0) and bits(held[1][(1, 5)][2]) == bits(LITERAL[undefined_code][0])
    assert held[2][(2, 5)][2] == [-1.0, 0.0, 7.0]


def test_the_journey_refuses_an_unknown_code_by_name_and_a_format_8_line(tmp_path):
    journey = roundtrip('journey')
    with pytest.raises(ValueError, match="unknown code for no value .card 5 '-127'"): journey.segy_parts(segy(tmp_path / 'C.sgy', '-127'))
    with open(segy(tmp_path / 'L.sgy'), 'rb') as f, pytest.raises(ValueError, match=r'not IEEE float samples \(format 8\)'): journey.segy_line_parts(f)


@pytest.mark.parametrize('undefined_code', [-128, None])
def test_the_window_read_back_decodes_format_8_to_the_literal_floats(undefined_code):
    """Catches: the window read-back decoding code 8 as IBM words (the fall-through it had)."""
    readback = roundtrip('window_readback')
    assert bits(readback.decode(b'\x03\x80\x7f', 8, undefined_code)) == bits(LITERAL[undefined_code][0])
    assert list(readback.decode(struct.pack('>2f', 1.5, -2.0), 5)) == [1.5, -2.0]
    with pytest.raises(readback.Disagree, match='sample format 2'): readback.decode(b'\x00' * 4, 2)
