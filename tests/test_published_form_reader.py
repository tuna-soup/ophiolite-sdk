"""E175 s0 C2: the SDK's own reader of a cube as published (`ophiolite.published_form`), written apart from the server's
module and sharing no import with it. The oracles are the strategy's literals (D-M, R1-10); the Connectors test checks
both sides agree bit for bit on random masks."""
import struct

import pytest
from ophiolite import published_form


def test_integer_codes_are_their_own_values():
    """Mutations: unsigned (RED); little-endian (RED)."""
    assert published_form.decode(bytes.fromhex('8000ffff00007fff'), 3) == [-32768, -1, 0, 32767]
    assert published_form.decode(bytes.fromhex('800000007fffffff'), 2) == [-2147483648, 2147483647]
    assert published_form.decode(struct.pack('>2i', 7, -7), 2) == [7, -7]
    for raw, code in ((b'\x00\x00\x00', 3), (b'\x00' * 4, 5)):
        with pytest.raises(ValueError):
            published_form.decode(raw, code)


@pytest.mark.parametrize('bits,hex_', [([True] + [False] * 7 + [True], '8080'), ([False] * 9, '0000'), ([True] * 9, 'ff80')])
def test_the_mask_oracles(bits, hex_):
    """Mutations: LSB first (RED); polarity inverted (RED)."""
    assert published_form.pack(bits).hex() == hex_
    assert published_form.positions(bytes.fromhex(hex_), 9) == bits


def test_a_padding_bit_or_a_wrong_length_is_refused():
    with pytest.raises(ValueError, match='padding bit'):
        published_form.positions(bytes.fromhex('ffc0'), 9)
    for raw in (b'\x80', b'\x80\x80\x00'):
        with pytest.raises(ValueError):
            published_form.positions(raw, 9)
    assert published_form.WIDTH == {1: 4, 2: 4, 3: 2, 5: 4}
