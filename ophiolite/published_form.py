"""E175 s0 (strategy D-V, D-M): a seismic cube as published (`ophiolite.seismic-volume/3`, profile `segy/3`), its
integer codes and its mask read independently of the server with `struct` alone.

A code of SEG-Y format 2 (4 bytes) or 3 (2 bytes) is a big-endian two's complement integer whose value is the code
itself; no scale is applied and no code is reserved. The mask states the positions without a trace: one bit per
position in window order, 1 for absent, most significant bit first, zero bits padding the last byte.
"""
import struct

WIDTH = {1: 4, 2: 4, 3: 2, 5: 4}
_CODES = {2: 'i', 3: 'h'}


def decode(raw, code):
    """The values of big-endian integer codes of format 2 or 3."""
    if code not in _CODES: raise ValueError('format_code is 2 or 3')
    count, rest = divmod(len(raw), WIDTH[code])
    if rest: raise ValueError('The samples are not whole codes')
    return list(struct.unpack('>%d%s' % (count, _CODES[code]), raw))


def positions(raw, count):
    """The `count` positions a mask states, True where a position has no trace; a padding bit set is refused."""
    if len(raw) != (count + 7) // 8: raise ValueError('The mask is not %d bits padded to whole bytes' % count)
    out = []
    for byte in raw:
        for shift in range(7, -1, -1): out.append(byte >> shift & 1 == 1)
    if True in out[count:]: raise ValueError('A mask has a padding bit set')
    return out[:count]


def pack(absent):
    """The mask of positions (True where absent), as the server writes it."""
    bits = [1 if a else 0 for a in absent] + [0] * (-len(absent) % 8)
    return bytes(sum(bit << (7 - k) for k, bit in enumerate(bits[n:n + 8])) for n in range(0, len(bits), 8))
