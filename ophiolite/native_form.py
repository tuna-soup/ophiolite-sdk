"""E140 s0 (strategy D101, D-D): the 8-bit seismic cube (`ophiolite.seismic-volume/2`, profile `segy/2`), decoded
independently of the server with `struct` alone.

A code is a one-byte two's complement integer and its value is the code itself, as a float32. When the cube's
`undefined_code` is -128, code -128 means no value and decodes to the quiet NaN 0x7fc00000; when it is None, every code
is a value. Values are returned as float32 bit patterns, so the NaN keeps its payload.
"""
import json
import struct

UNDEFINED_CODE = -128
UNDEFINED_BITS = 0x7fc00000
FORM = 'int8'


def decode(raw, undefined_code):
    """The float32 bit patterns of one-byte codes: a code is its own value, except -128 under undefined_code -128."""
    if undefined_code not in (UNDEFINED_CODE, None): raise ValueError('undefined_code is -128 or None')
    return [UNDEFINED_BITS if code == undefined_code else struct.unpack('>I', struct.pack('>f', float(code)))[0]
            for code in struct.unpack('>%db' % len(raw), raw)]


def values(raw, undefined_code):
    """The float values of one-byte codes (NaN where a code means no value)."""
    return [struct.unpack('>f', struct.pack('>I', bits))[0] for bits in decode(raw, undefined_code)]


def head(kind, name, axes, undefined_code):
    """D9's header line for a native cube: canonical JSON of kind, object and axes, as for a float cube, binding also
    the form and the code for no value (the codes alone do not say which of them is reserved)."""
    if undefined_code not in (UNDEFINED_CODE, None): raise ValueError('undefined_code is -128 or None')
    return json.dumps({'axes': axes, 'form': FORM, 'kind': kind, 'object': name, 'undefined_code': undefined_code},
                      sort_keys=True, separators=(',', ':')).encode() + b'\n'
