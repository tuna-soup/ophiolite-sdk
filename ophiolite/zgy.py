"""Read a ZGY cube on this computer and write it as SEG-Y rev 1 (E123 SZ). The cube lands through the read-on-your-
computer path as `segy/1`; the server never reads ZGY.

The vertical axis is mapped exactly or refused (D4): time in milliseconds or depth in metres starting at 0, never
rounded or rescaled. Horizontal coordinates are metres (stated, or confirmed by the person when the file states no
unit, D-B1) and are written with the coarsest SEG-Y scalar that keeps every trace coordinate exact (B2). A ZGY states
no coordinate system, so every cube asks once: `read` raises `procedures.Stopped(…, asks=True)` until the settings
are given, before any sample is decoded. Every other refusal is a `procedures.Stopped` with its sentence.

Needs the optional package pyzgy (`pip install 'ophiolite[zgy]'`); pyzgy pulls segyio (LGPL-3.0), which is why this
stays an extra and never enters the server image."""
import contextlib
import hashlib
import io
import math
import os
import warnings
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from ._version import __version__
from .errors import ValidationFailed
from .procedures import Stopped
from .writers import write_volume

PROCEDURE = Path(__file__).resolve().parent / 'reference' / 'read-zgy'  # the packaged "Read a ZGY cube on your computer"
MAX_FILE_BYTES = 32 * 1024 * 1024  # a kept original is never refused after the conversion (conversions.PROVENANCE_BYTES)
MAX_TRACES = 1_000_000  # the server's segy.MAX_TRACES
MAX_SAMPLES = 20_000  # the server's segy.MAX_SAMPLES
MAX_OUTPUT_BYTES = 128 * 1024 * 1024  # the written SEG-Y, held whole as WrittenOriginal bytes
INT32 = (-2**31, 2**31 - 1)
SCALES = (1, 10, 100, 1000)  # SEG-Y scalars -1, -10, -100, -1000, coarsest first
Z_DOMAINS = ('time', 'depth')
MISSING = ("Reading a ZGY file needs the optional package pyzgy. Install it with: pip install 'ophiolite[zgy]'. "
           'Nothing was read.')
STATED = ('size', 'datatype', 'datarange', 'zunitdim', 'zunitname', 'zunitfactor', 'zstart', 'zinc', 'hunitdim',
          'hunitname', 'hunitfactor', 'annotstart', 'annotinc', 'corners')


def _api():
    try:
        with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):  # openzgy announces absent optional parts
            warnings.simplefilter('ignore')
            import openzgy.api as api
    except ImportError:
        raise Stopped(MISSING) from None
    return api


def _check_size(path):
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise Stopped(f'This ZGY file is {size} bytes; at most {MAX_FILE_BYTES} bytes (32 MiB) are read. Nothing was read.')


def _name(value):
    return getattr(value, 'name', value)  # openzgy's enums by name, as the textual header and the sentences say them


def stated(meta):
    """The ZGY's own statements, plain values (enums by name)."""
    return {key: _name(meta[key]) for key in STATED}


def header(path):
    """The cube's stated values, from its header; no sample is decoded."""
    _check_size(path)
    api = _api()
    with api.ZgyReader(str(path)) as reader: return stated(reader.meta)


def _decimal(value):
    return Decimal(repr(float(value)))


def output_bytes(size):
    traces, samples = size[0] * size[1], size[2]
    return 3600 + traces * (240 + 4 * samples)


def _bounds(size):
    traces, samples = size[0] * size[1], size[2]
    if traces > MAX_TRACES: raise Stopped(f'This ZGY holds {traces} traces; at most {MAX_TRACES} are read. Nothing was read.')
    if samples > MAX_SAMPLES: raise Stopped(f'This ZGY holds {samples} samples per trace; at most {MAX_SAMPLES} are read. Nothing was read.')
    if output_bytes(size) > MAX_OUTPUT_BYTES:
        raise Stopped(f'The SEG-Y for this ZGY would be {output_bytes(size)} bytes; at most {MAX_OUTPUT_BYTES} bytes (128 MiB) '
                      'are written. Nothing was read.')


def _lines(meta):
    numbers = []
    for axis, word in enumerate(('inline', 'crossline')):
        start, step, count = _decimal(meta['annotstart'][axis]), _decimal(meta['annotinc'][axis]), meta['size'][axis]
        if not start.is_finite() or start != start.to_integral_value():
            raise Stopped(f'The first {word} number {meta["annotstart"][axis]!r} is not a whole number. Nothing was converted.')
        if not step.is_finite() or step != step.to_integral_value() or step <= 0:
            raise Stopped(f'The {word} increment {meta["annotinc"][axis]!r} is not a positive whole number. Nothing was converted.')
        first, last = int(start), int(start) + (count - 1) * int(step)
        for value in (first, last):
            if not INT32[0] <= value <= INT32[1]:
                raise Stopped(f'The {word} number {value} is beyond a 32-bit integer. Nothing was converted.')
        numbers.append([first + n * int(step) for n in range(count)])
    return numbers


def _vertical_stated(meta):
    """Refusals that do not depend on the settings: a stated vertical unit other than milliseconds or metres."""
    dim, factor = _name(meta['zunitdim']), _decimal(meta['zunitfactor'])
    if dim == 'time' and factor != Decimal('0.001'):
        unit = 'seconds' if factor == 1 else (meta['zunitname'] or 'an unnamed unit')
        raise Stopped(f'This ZGY states vertical time in {unit} (factor {meta["zunitfactor"]!r}); only milliseconds (factor 0.001) '
                      'are read. Nothing was converted.')
    if dim == 'length' and factor != 1:
        unit = 'feet' if factor == Decimal('0.3048') else (meta['zunitname'] or 'an unnamed unit')
        raise Stopped(f'This ZGY states vertical depth in {unit} (factor {meta["zunitfactor"]!r}); only metres (factor 1.0) '
                      'are read. Nothing was converted.')
    if dim not in ('time', 'length', 'unknown'):
        raise Stopped(f'This ZGY states its vertical axis as {dim} (factor {meta["zunitfactor"]!r}); only time in milliseconds '
                      'or depth in metres are read. Nothing was converted.')


def _horizontal_stated(meta):
    """Metres only (B1): a stated length with factor 1.0, or no stated unit with factor 1.0 (confirmed by the person)."""
    dim, factor = _name(meta['hunitdim']), _decimal(meta['hunitfactor'])
    if dim in ('length', 'unknown') and factor == 1: return dim == 'unknown'
    unit = 'feet' if dim == 'length' and factor == Decimal('0.3048') else (meta['hunitname'] or dim)
    raise Stopped(f'This ZGY states horizontal coordinates in {unit} ({dim}, factor {meta["hunitfactor"]!r}); only metres '
                  '(factor 1.0) are read. Nothing was converted.')


def _scale(meta, lines):
    """The coarsest SEG-Y scale that writes every trace coordinate exactly, and each trace's (x, y) at that scale. A trace
    coordinate is corner 0 plus whole multiples of the two steps, so the corners and the steps decide exactness (B2)."""
    corners = meta['corners']
    for n, corner in enumerate(corners):
        for value in corner:
            if not math.isfinite(value): raise Stopped(f'Corner {n + 1} has the coordinate {value!r}, which is not a finite number. Nothing was converted.')
    exact = [[Fraction(_decimal(v)) for v in corner] for corner in corners]
    n_in, n_x = len(lines[0]), len(lines[1])
    step_in = [(exact[1][a] - exact[0][a]) / (n_in - 1) if n_in > 1 else Fraction(0) for a in range(2)]
    step_x = [(exact[2][a] - exact[0][a]) / (n_x - 1) if n_x > 1 else Fraction(0) for a in range(2)]
    named = [(corners[n][a], None) for n in range(4) for a in range(2)]  # what a refusal names: the stated value, or a trace's
    values = [exact[n][a] for n in range(4) for a in range(2)]
    if n_in > 1: named += [(None, (1, 0, a)) for a in range(2)]; values += [exact[0][a] + step_in[a] for a in range(2)]
    if n_x > 1: named += [(None, (0, 1, a)) for a in range(2)]; values += [exact[0][a] + step_x[a] for a in range(2)]
    scale = next((s for s in SCALES if all((v * s).denominator == 1 for v in values)), None)
    if scale is None:
        k = next(k for k, v in enumerate(values) if (v * SCALES[-1]).denominator != 1)
        corner, trace = named[k]
        what = (repr(corner) if corner is not None else
                f'{values[k]} ({"xy"[trace[2]]} of inline {lines[0][trace[0]]}, crossline {lines[1][trace[1]]})')
        raise Stopped(f'The coordinate {what} cannot be written exactly with a SEG-Y coordinate scalar (-1, -10, -100 or -1000). '
                      'Nothing was converted.')
    for axis, word in enumerate('xy'):  # corner 4 = corner 2 + corner 3 - corner 1, exactly
        if exact[3][axis] != exact[1][axis] + exact[2][axis] - exact[0][axis]:
            raise Stopped(f'The four corners do not form a parallelogram ({word} of corner 4 is {corners[3][axis]!r}). Nothing was converted.')
    for n in range(4):  # coordinates are linear in the trace position, so the corners are the extremes
        for a in range(2):
            if not INT32[0] <= exact[n][a] * scale <= INT32[1]:
                raise Stopped(f'The coordinate {corners[n][a]!r} at scalar -{scale} is beyond a 32-bit integer. Nothing was converted.')
    origin = [int(exact[0][a] * scale) for a in range(2)]
    di, dj = [int(step_in[a] * scale) for a in range(2)], [int(step_x[a] * scale) for a in range(2)]
    xy = [(origin[0] + i * di[0] + j * dj[0], origin[1] + i * di[1] + j * dj[1]) for i in range(n_in) for j in range(n_x)]
    return scale, xy


def question(meta, *, horizontal_unstated):
    """The one question (D3, §6): the lead sentence, what the file states, then the settings syntax."""
    dim = _name(meta['zunitdim'])
    vertical = {'time': 'vertical time in ms', 'length': 'vertical depth in m'}.get(dim, 'no vertical unit')
    c0, c3 = meta['corners'][0], meta['corners'][3]
    sentence = ('Choose the coordinate system and confirm whether the samples represent time or depth. '
                f'This ZGY states {vertical}, start {meta["zstart"]!r}, step {meta["zinc"]!r}, and no coordinate system '
                f'(corners {c0[0]!r}, {c0[1]!r} to {c3[0]!r}, {c3[1]!r}).')
    syntax = 'crs=<EPSG code> and z_domain=time or z_domain=depth'
    if horizontal_unstated:
        sentence += ' It does not state the unit of its horizontal coordinates; confirm they are metres.'
        syntax += ' and horizontal_unit=m'
    return sentence + ' Technical details: run again with settings ' + syntax + '.'


def _vertical(meta, z_domain):
    """(sample_interval, first_sample) for the SEG-Y headers, exact or refused (D4)."""
    dim = _name(meta['zunitdim'])
    if dim != 'unknown' and {'time': 'time', 'length': 'depth'}[dim] != z_domain:
        raise Stopped(f'This ZGY states vertical {"time" if dim == "time" else "depth"}, and the setting says z_domain={z_domain}. '
                      'Nothing was converted.')
    step, start = _decimal(meta['zinc']), _decimal(meta['zstart'])
    unit = 'ms' if z_domain == 'time' else 'm'
    interval = step * 1000  # microseconds, or millimetres
    if not step.is_finite() or interval != interval.to_integral_value() or not 1 <= interval <= 65535:
        raise Stopped(f'The sample interval {meta["zinc"]!r} {unit} is not a whole number of {"microseconds" if unit == "ms" else "millimetres"} '
                      'from 1 to 65535. Nothing was converted.')
    if z_domain == 'depth':
        if start != 0:
            raise Stopped(f'This depth cube starts at {meta["zstart"]!r} m; only depth cubes starting at 0 are read. Nothing was converted.')
        return int(interval), 0
    if not start.is_finite() or start != start.to_integral_value() or not -32768 <= start <= 32767:
        raise Stopped(f'The first sample time {meta["zstart"]!r} ms is not a whole number of milliseconds from -32768 to 32767. '
                      'Nothing was converted.')
    return int(interval), int(start)


def _text(values, digest):
    lines = [f'CONVERTED FROM ZGY BY OPHIOLITE {__version__}']
    for key in STATED:
        text = ascii(values[key]) if isinstance(values[key], str) else repr(values[key])
        line = f'{key} {text}'
        lines += [line[n:n + 76] for n in range(0, len(line), 76)]
    return lines + [f'SHA-256 {digest}']


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def convert(reader, *, crs=None, z_domain=None, horizontal_unit=None, digest='', filename='volume.sgy'):
    """The conversion of an open reader (`.meta`, `.read(start, buffer)`): every check from the header first, then the
    samples once. Returns `WrittenOriginal(…, 'segy/1', declared={'crs', 'z_domain'})`."""
    meta = reader.meta
    size = tuple(meta['size'])
    _bounds(size)
    lines = _lines(meta)
    _vertical_stated(meta)
    horizontal_unstated = _horizontal_stated(meta)
    scale, xy = _scale(meta, lines)
    if not (crs or '').strip() or z_domain not in Z_DOMAINS or (horizontal_unstated and horizontal_unit != 'm'):
        raise Stopped(question(meta, horizontal_unstated=horizontal_unstated), asks=True)
    interval, delay = _vertical(meta, z_domain)
    import numpy
    samples = numpy.zeros(size, dtype=numpy.float32)  # openzgy scales int8 and int16 storage by the stated datarange
    reader.read((0, 0, 0), samples)
    try:
        return write_volume(samples, inlines=lines[0], crosslines=lines[1], sample_interval=interval, first_sample=delay,
                            cdp_xy=xy, scalar=-scale, text_lines=_text(stated(meta), digest),
                            declared={'crs': crs.strip(), 'z_domain': z_domain}, filename=filename)
    except ValidationFailed as refused:
        raise Stopped(' '.join(refused.violations) + ' Nothing was converted.') from None


def read(path, *, crs=None, z_domain=None, horizontal_unit=None):
    """Convert the ZGY at `path` to SEG-Y rev 1 (IEEE). Raises `procedures.Stopped` with `asks=True` until `crs` and
    `z_domain` (and `horizontal_unit='m'` when the file states no horizontal unit) are given; every other refusal is a
    `Stopped` naming the value."""
    _check_size(path)
    api = _api()
    with api.ZgyReader(str(path)) as reader:
        return convert(reader, crs=crs, z_domain=z_domain, horizontal_unit=horizontal_unit, digest=_sha256(path),
                       filename=Path(path).stem + '.sgy')
