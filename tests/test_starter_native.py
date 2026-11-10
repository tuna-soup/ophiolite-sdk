"""E140 s1 C3 (strategy D-K): the SDK reads an 8-bit cube of `ophiolite.opendtect-export/2` back. The files are built
here byte by byte (not by the exporter), the digests written by hand.

E140 s3 C5 (D-S): the starter carries the form on: the inventory keeps form and undefined_code, the landing profile
and the declarations are per file, and cube_inline decodes the codes. The pack targets in conformance/roundtrip are
tested in tests/gateway/test_starter_native_pack.py (the SDK export holds no conformance tree)."""
import hashlib
import math
import struct

import pytest

from ophiolite import starter, starter_archive
from ophiolite.errors import Refused

AXES = {'inline': [1, 2, 1], 'crossline': [5, 5, 1], 'z': [0, 4000, 3]}
CODES = {(1, 5): [3, -128, 127], (2, 5): [-1, 0, 7]}
CARD = 'C 5 OPHIOLITE 8-BIT CODES; UNDEFINED %s'
NOTHING = ' Nothing was sent.'


def segy(path, card='-128', code=8):
    """Rev 1, fixed length, scalar -100: two traces of three one-byte codes (four-byte floats when CODE is 5)."""
    text = bytearray(b' ' * 3200)
    text[320:400] = (CARD % card).ljust(80).encode()
    binary = bytearray(400)
    struct.pack_into('>H', binary, 16, 4000); struct.pack_into('>H', binary, 20, 3); struct.pack_into('>h', binary, 24, code)
    struct.pack_into('>H', binary, 300, 0x0100); struct.pack_into('>h', binary, 302, 1)
    out = bytes(text) + bytes(binary)
    for (i, c), codes in CODES.items():
        th = bytearray(240)
        struct.pack_into('>h', th, 70, -100); struct.pack_into('>iiii', th, 180, 100 * i, 200 * i, i, c)
        struct.pack_into('>h', th, 108, 0); struct.pack_into('>HH', th, 114, 3, 4000)
        out += bytes(th) + (struct.pack('>3b', *codes) if code == 8 else struct.pack('>3f', *codes))
    path.write_bytes(out)
    return path


def entry(**form):
    return {'path': 'seismic/C.sgy', 'kind': 'seismic-3d', 'object': 'C', 'axes': AXES, 'digest': '0' * 64, **form}


def doc(fmt, *files):
    return {'format': fmt, 'survey': {}, 'cubes': {}, 'wells': {}, 'files': list(files), 'not_read': []}


def refusal(call, *args):
    with pytest.raises(Refused) as caught: call(*args)
    return str(caught.value)


@pytest.mark.parametrize('undefined_code, card', [(-128, '-128'), (None, 'NONE')])
def test_an_int8_entry_is_read_as_format_8_and_hashed_with_its_form(tmp_path, undefined_code, card):
    """Catches: the native head replaced by the float head, or the undefined code left out of it."""
    head = '{"axes":{"crossline":[5,5,1],"inline":[1,2,1],"z":[0,4000,3]},"form":"int8","kind":"seismic-3d","object":"C","undefined_code":%s}\n'
    digest = hashlib.sha256((head % ('-128' if undefined_code == -128 else 'null')).encode()
                            + struct.pack('>iiqq', 1, 5, 100, 200) + b'\x03\x80\x7f' + struct.pack('>iiqq', 2, 5, 200, 400) + b'\xff\x00\x07').hexdigest()
    assert starter_archive.read_cube(segy(tmp_path / 'C.sgy', card), entry(form='int8', undefined_code=undefined_code)) == (AXES, digest)


def test_a_format_8_file_under_a_float_entry_or_export_1_is_refused(tmp_path):
    path = segy(tmp_path / 'C.sgy')
    sentence = 'seismic/C.sgy is not the SEG-Y the export writes: format 8, revision 0x100, fixed-length flag 1.' + NOTHING
    assert refusal(starter_archive.read_cube, path, entry()) == sentence
    assert refusal(starter_archive.read_cube, path, entry(form='float32')) == sentence


def test_a_format_5_file_under_an_int8_entry_is_refused(tmp_path):
    path = segy(tmp_path / 'C.sgy', code=5)
    assert refusal(starter_archive.read_cube, path, entry(form='int8', undefined_code=-128)) == \
        'seismic/C.sgy is not the SEG-Y the export writes: format 5, revision 0x100, fixed-length flag 1.' + NOTHING


@pytest.mark.parametrize('card, undefined_code', [('NONE', -128), ('-128', None), ('-127', -128)])
def test_a_card_5_disagreeing_with_the_entry_is_refused(tmp_path, card, undefined_code):
    """Catches: card 5 not compared (a -128 that means no value would read back as a value, or the reverse)."""
    assert refusal(starter_archive.read_cube, segy(tmp_path / 'C.sgy', card), entry(form='int8', undefined_code=undefined_code)) == \
        'seismic/C.sgy is not the SEG-Y the export writes: card 5 does not state the code for no value export.json gives (%s).' % undefined_code + NOTHING


V1, V2 = 'ophiolite.opendtect-export/1', 'ophiolite.opendtect-export/2'
FORMLESS = 'export.json (%s) does not state the form of seismic/C.sgy (int8 with its undefined_code -128 or null, or float32).' % V2 + NOTHING


def test_export_2_with_one_int8_and_one_float_cube_and_a_formed_fault_is_accepted():
    fault = {'path': 'faults/F.dat', 'kind': 'faults', 'object': 'F', 'axes': {}, 'digest': '0' * 64, 'form': 'sticks'}
    starter_archive.forms(doc(V2, entry(form='int8', undefined_code=None), {**entry(form='float32'), 'path': 'seismic/D.sgy'}, fault))
    starter_archive.forms(doc(V1, entry(), fault))


@pytest.mark.parametrize('form', [{}, {'form': 'int16'}, {'form': 'int8'}, {'form': 'int8', 'undefined_code': 5},
                                  {'form': 'float32', 'undefined_code': None}],
                         ids=['no form', 'unknown form', 'int8 without its code', 'another code', 'float32 with a code'])
def test_an_export_2_cube_entry_without_a_valid_form_is_refused(form):
    """Catches: /2 accepted without the per-cube form keys (D-K)."""
    assert refusal(starter_archive.forms, doc(V2, {**entry(form='int8', undefined_code=-128), 'path': 'seismic/D.sgy'}, entry(**form))) == FORMLESS


def test_export_2_without_an_int8_cube_and_export_1_with_a_form_are_refused():
    assert refusal(starter_archive.forms, doc(V2, entry(form='float32'))) == 'export.json is %s but holds no 8-bit cube.' % V2 + NOTHING
    assert refusal(starter_archive.forms, doc(V1, entry(form='int8', undefined_code=-128))) == \
        'export.json (%s) names a cube form; only %s does.' % (V1, V2) + NOTHING


# -- E140 s3 C5 (D-S): the starter carries the form; the pack targets read it ------------------------------------------

NAN_BITS = b'\x7f\xc0\x00\x00'
LITERAL = {-128: [[3.0, math.nan, 127.0]], None: [[3.0, -128.0, 127.0]]}  # inline 1 of CODES, decoded by hand


def bits(values):
    return [struct.pack('>f', v) for v in values]


@pytest.mark.parametrize('undefined_code, card', [(-128, '-128'), (None, 'NONE')])
def test_cube_inline_decodes_the_codes_of_a_native_cube(tmp_path, undefined_code, card):
    """Catches: cube_inline reading a native cube as float words, or the undefined code not mapped to NaN."""
    axes, headers, inline, line = starter_archive.cube_inline(segy(tmp_path / 'C.sgy', card), 'seismic/C.sgy', lambda axes: 1, undefined_code)
    assert (axes, inline) == (AXES, 1) and headers == [(1, 5, 1.0, 2.0), (2, 5, 2.0, 4.0)]
    assert [bits(t) for t in line] == [bits(t) for t in LITERAL[undefined_code]]
    if undefined_code == -128: assert line[0][1] != line[0][1] and bits(line[0])[1] == NAN_BITS


def test_cube_inline_of_a_float_cube_still_refuses_format_8(tmp_path):
    assert refusal(starter_archive.cube_inline, segy(tmp_path / 'C.sgy'), 'seismic/C.sgy', lambda axes: 1) == \
        'seismic/C.sgy is not the SEG-Y the export writes: format 8, revision 0x100, fixed-length flag 1.' + NOTHING


def exported(tmp_path, **form):
    """A report of one derived cube on disk (SEGY's bytes) under an archive, as `starter.inventory` reads it."""
    folder, archive = tmp_path / 'out', {'sha256': 'a' * 64}
    (folder / 'files' / 'seismic').mkdir(parents=True)
    path = segy(folder / 'files' / 'seismic' / 'C.sgy')
    digest, size = starter_archive.digest_of(path)
    report = {'files': [{'path': 'seismic/C.sgy', 'kind': 'seismic-3d', 'object': 'C', **form}],
              'derived': [{'path': 'seismic/C.sgy', 'sha256': digest, 'bytes': size, 'from': archive['sha256'], 'how': 'by hand'}]}
    return report, folder, archive


@pytest.mark.parametrize('undefined_code', [-128, None])
def test_the_inventory_keeps_the_form_so_the_cube_lands_as_segy_2_with_its_code(tmp_path, undefined_code):
    """Catches: the form dropped at the inventory (the cube would land as segy/1), or undefined_code dropped at the
    declarations (segy/2 would be sent without the code for no value)."""
    [d] = starter.inventory(*exported(tmp_path, form='int8', undefined_code=undefined_code), 'OUT')
    assert (d['form'], d['undefined_code']) == ('int8', undefined_code)
    assert starter.landing_profile(d) == 'segy/2'
    declared = {'seismic-3d': {'coordinate_reference_system': 'EPSG:23031'}}
    assert starter.declared_of(declared, d) == {'coordinate_reference_system': 'EPSG:23031', 'undefined_code': {-128: '-128', None: 'none'}[undefined_code]}
    assert declared == {'seismic-3d': {'coordinate_reference_system': 'EPSG:23031'}}  # the kind's table is not changed


def test_a_float_cube_lands_as_segy_1_with_its_kind_declarations(tmp_path):
    [d] = starter.inventory(*exported(tmp_path), 'OUT')
    assert 'form' not in d and 'undefined_code' not in d
    assert starter.landing_profile(d) == 'segy/1'
    assert starter.declared_of({'seismic-3d': {'a': 'b'}}, d) == {'a': 'b'}


@pytest.mark.parametrize('form', [{'form': 'int8', 'undefined_code': 5}, {'form': 'int8'}, {'form': 'float32'}, {'form': 'int16'}],
                         ids=['another code', 'no code', 'float32 named', 'unknown form'])
def test_a_report_cube_of_another_form_or_code_is_not_the_export(tmp_path, form):
    assert refusal(starter.inventory, *exported(tmp_path, **form), 'OUT') == starter.NOT_THE_EXPORT % 'OUT'
