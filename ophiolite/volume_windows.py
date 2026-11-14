"""E141 s0: part of a volume, the syntax half of the range semantics (D98), checked before anything is sent.

The server owns the grid half (labels on the survey grid, `outside`, `off-grid`) and answers `window-refused` with a
closed reason; here the same reasons and sentences refuse what needs no stored description: a malformed or stepped
range, a range that runs backwards, inline or crossline without `by`, a 2D line asked by label. Endpoints are inclusive
at both ends; a single number n means n:n; samples are zero-based positions whatever `by` says.

E141 s1 (D-C, D-S): `Client.read_window` / `iter_window` (and the async twins) read a valid window. The window
document is checked here, by name, before any piece is asked (`check_document`): its structure against the generated
`VolumeWindow` model, then identity, geometry, counts, shape, format, the piece arithmetic, the window_id recomputed
from its canonical form, the closed verification lists, and the axes recomputed from the request and the asset's own
description (a volume's described context; a line's stored description, `representations/data` — the original is
never sent to the client). Each piece is checked against its identity headers, its X-Content-SHA256 and its length
(`verify_piece`); the window digest is the sha256 of the piece bodies in index order, computed here. Limit, written
down: a body that is another valid body of equal length, with its own correct digest and the asked identity headers,
cannot be told apart by a client; that is trusted server behaviour (`verification.trusted`).

Memory: `read_window` holds the whole window decoded (Python floats cost ~8-9 x their 4-byte words, by design);
`iter_window` holds one piece decoded. Not in `errors.py`, which the QGIS plug-in vendors byte for byte.

E141 s2 (D-X, D-W, D-S): `exchange get --window` (and `Exchange.get(item, window=...)`) writes a volume window as
SEG-Y, `window.sgy`: the original's file header and each window trace's own header, verbatim but for the sample count
(115-116, and 3221-3222 in the binary header) and the start (109-110), then the stored words verbatim. A crop the
format cannot state exactly (`exact_crop`) refuses after metadata, before the file header; the revision field and the
header positions (`check_file_header`) after the file header, before any trace header or sample. Refusals there are
`CannotReadHere` with `technical.reason` one of WINDOW_CODES (`cannot`); `SegyWindowWriter` writes into
`Exchange.get`'s staging folder, which replaces the output atomically."""
import hashlib
import json
import math
import os
import re
import struct
from urllib.parse import quote, urlencode

from .errors import Busy, IntegrityConflict, OphioliteError, Unavailable, VerificationFailed

NOTHING = ' Nothing was read.'
NOT_SENT = ' Nothing was sent.'
NOT_AVAILABLE = ('Reading part of a volume is not available in this SDK yet.' + NOT_SENT +
                 ' Read one slice (Client.read_slice) or the whole original (Client.download_original).')
REASONS = ('malformed', 'unknown-parameter', 'selection-required', 'reversed', 'outside', 'off-grid', 'line-by-label',
           'not-a-volume', 'not-available-yet', 'window-changed', 'masked', 'headers-changed')  # E175 s2: the last two the client's own
MASKED = ('This window has positions without a trace, which a list of codes cannot state. Read it with to_masked(), which '
          'masks those positions.')
HEADERS_CHANGED = 'The trace headers of this window changed while it was written: ask for the window again. Nothing was written.'
AXES = ('inline', 'crossline', 'trace', 'sample')
RANGE = re.compile(r'^(-?[0-9]{1,10})(?::(-?[0-9]{1,10}))?$')
STEPPED = re.compile(r'^-?[0-9]{1,10}:-?[0-9]{1,10}:-?[0-9]{1,10}$')


class WindowRefused(OphioliteError):
    """A window refused by name: `.reason` is one of `REASONS`, the message the sentence (the server's words when the
    server refused)."""
    code = 'window-refused'

    def __init__(self, reason, sentence, **kwargs):
        if reason not in REASONS: raise ValueError('Unknown window refusal reason: %s' % reason)
        super().__init__(sentence, **kwargs)
        self.reason = reason


def _text(axis, value):
    """A range as the query carries it: n, (first, last), or 'first:last'."""
    if isinstance(value, bool): raise WindowRefused('malformed', "The %s range '%s' is not a number or two numbers joined by a colon (first:last, both included).%s" % (axis, value, NOTHING))
    if isinstance(value, int): return str(value)
    if isinstance(value, tuple) and len(value) == 2 and all(type(v) is int for v in value): return '%d:%d' % value
    if isinstance(value, str): return value
    raise WindowRefused('malformed', "The %s range '%s' is not a number or two numbers joined by a colon (first:last, both included).%s" % (axis, str(value)[:64], NOTHING))


def parse_window(*, inline=None, crossline=None, trace=None, sample=None, by=None):
    """The window's query as (name, value) pairs in a fixed order, or WindowRefused by name. `trace` asks a 2D line,
    `inline`/`crossline` a volume; `sample` either."""
    given = {'inline': inline, 'crossline': crossline, 'trace': trace, 'sample': sample}
    if trace is not None and (inline is not None or crossline is not None):
        raise WindowRefused('unknown-parameter', "A window asks a 2D line by trace or a volume by inline and crossline, not both: leave out 'trace' or 'inline' and 'crossline'." + NOTHING)
    if by is not None and by not in ('label', 'ordinal'):
        raise WindowRefused('malformed', "by is label or ordinal, not '%s'.%s" % (str(by)[:64], NOTHING))
    if trace is not None and by == 'label':
        raise WindowRefused('line-by-label', 'A 2D line is addressed by trace position in file order, not by trace number: '
                                             'use by=ordinal or leave by out.' + NOTHING)
    query = []
    for axis in AXES:
        if given[axis] is None: continue
        text = _text(axis, given[axis])
        if STEPPED.match(text):
            raise WindowRefused('malformed', "The %s range '%s' has a step; decimation is not offered: give first:last, both included.%s" % (axis, text, NOTHING))
        found = RANGE.match(text)
        if not found:
            raise WindowRefused('malformed', "The %s range '%s' is not a number or two numbers joined by a colon (first:last, both included).%s" % (axis, text[:64], NOTHING))
        first = int(found.group(1)); last = first if found.group(2) is None else int(found.group(2))
        if first > last:
            raise WindowRefused('reversed', 'The %s range %d:%d runs backwards: give the first and then the last, both included.%s' % (axis, first, last, NOTHING))
        query.append((axis, text))
    if by is None and (inline is not None or crossline is not None):
        raise WindowRefused('selection-required', 'Say whether inline and crossline are labels or ordinals: add by=label or by=ordinal.' + NOTHING)
    if by is not None: query.append(('by', by))
    return query


def parse_spec(spec):
    """The CLI's `--window` spec, `inline=100:104,crossline=300:310,sample=0:5,by=label`, as parse_window's query."""
    ranges = {}
    for part in (spec or '').split(','):
        name, eq, value = part.strip().partition('=')
        if not eq or not name or not value:
            raise WindowRefused('malformed', "The window '%s' is not name=value pairs joined by commas, e.g. inline=100:104,by=label.%s" % (str(spec)[:64], NOTHING))
        if name not in AXES + ('by',):
            raise WindowRefused('unknown-parameter', "A window takes no parameter '%s': ask with inline, crossline, trace, sample and by.%s" % (name[:64], NOTHING))
        if name in ranges:
            raise WindowRefused('malformed', 'The parameter %s is given twice; give each at most once.%s' % (name, NOTHING))
        ranges[name] = value
    return parse_window(**ranges)


def not_available(query):
    """Slice 0 (the CLI's `get --window` until slice 2): a valid window is not read; refused before any request."""
    raise WindowRefused('not-available-yet', NOT_AVAILABLE, details={'window': [list(p) for p in query]})


# --- E141 s1: reading a window (D-C, D-S) ----------------------------------------------------------------------------

WINDOW = 'ophiolite.volume-window/1'
BYTES_MAX = 33554432  # the `/1` partition's piece bound, fixed by the document's identity
DOCUMENT_BYTES = 32 * 1024 * 1024
GEOMETRY_AXES = {'volume': ('inline', 'crossline', 'sample'), 'line': ('trace', 'sample')}
MAPPING = {'volume': 'seismic-volume/1', 'line': 'seismic-line/1'}
GEOMETRY_OF = {'seismic-volume': 'volume', 'seismic-line': 'line'}
FORMATS = {1: 'ibm-float32', 5: 'ieee-float32'}
CLIENT_CHECKS = ['identity', 'axes', 'shape', 'piece-identity', 'piece-digest', 'completeness']
TRUSTED = ['chunk-digests-at-read', 'trace-positions']
FIELDS = {'schema', 'asset_id', 'revision', 'source_sha256', 'interpretation', 'window_id', 'geometry', 'selection', 'axes', 'shape',
          'samples', 'bytes', 'pieces', 'verification'}
# E140 s3 (D-W, D-O): an 8-bit cube's window, `/2`, one byte per sample (SEG-Y data format 8). Asked with windows=2, and
# only for an item whose descriptor is native, so a float request stays byte-identical to `/1`'s (R5).
WINDOW2 = 'ophiolite.volume-window/2'
NATIVE_CODE, NATIVE_FORMAT, NATIVE_MAPPING = 8, 'int8-code', 'seismic-volume/2'
ASK_NATIVE = ('windows', '2')


# E175 s1 (D-5): a cube as published's window, `/3`, at the format's own width, each piece and headers answer led by its
# positions' mask (one bit each, 1 for absent, most significant first, padded to whole bytes). Asked with windows=3,
# and only for an item whose described context counts `cells`.
WINDOW3 = 'ophiolite.volume-window/3'
PUBLISHED_MAPPING = 'seismic-volume/3'
PUBLISHED_FORMATS = {1: 'ibm-float32', 2: 'int32', 3: 'int16', 5: 'ieee-float32'}
PUBLISHED_WIDTH = {1: 4, 2: 4, 3: 2, 5: 4}
INTEGER_CODES = {2: 'int32', 3: 'int16'}
CLIENT_CHECKS3 = CLIENT_CHECKS + ['mask']
HEADERS_PER_ANSWER3 = 8 * BYTES_MAX // (8 * 240 + 1)  # D-H3: 139,737 positions, an answer's mask and headers <= 32 MiB
FIELDS3 = FIELDS | {'absent', 'headers'}
ASK_PUBLISHED = ('windows', '3')


def native(description):
    """True for a volume whose described context is the 8-bit form (format_code 8)."""
    return description is not None and description.geometry == 'volume' and description.context.get('format_code') == NATIVE_CODE


def published(description):
    """E175 s1: True for a volume described as a cube as published (its context counts `cells`)."""
    return description is not None and description.geometry == 'volume' and 'cells' in description.context


def asked(query, description):
    """The query a request sends: the window's own, plus windows=2 for a native cube or windows=3 for a cube as
    published only (R5: a float request stays byte-identical)."""
    if native(description): return list(query) + [ASK_NATIVE]
    return list(query) + [ASK_PUBLISHED] if published(description) else list(query)


def mask_bytes(positions):
    """D-M: the bytes of the mask of `positions` positions, padded to whole bytes."""
    return -(-positions // 8)


def published_per(samples, width):
    """D-M: the positions a `/3` piece holds, its mask and every trace within BYTES_MAX."""
    return 8 * BYTES_MAX // (8 * samples * width + 1)


def published_bytes(positions, absent, per, samples, width):
    """D-M: a `/3` window's bytes: each piece's mask, then the present traces' words."""
    full, rest = divmod(positions, per)
    return full * mask_bytes(per) + mask_bytes(rest) + (positions - absent) * samples * width


def _failed(check, why):
    raise VerificationFailed('The window fails its %s check: %s Nothing more was read.' % (check, why), details={'check': check})


def server_refusal(error):
    """A server's `window-refused` answer (any status) as WindowRefused with its reason and sentence, else None."""
    reason = (getattr(error, 'details', None) or {}).get('reason')
    if getattr(error, 'code', None) != 'window-refused' or reason not in REASONS: return None
    return WindowRefused(reason, error.server_message or error.message, status=error.status, remedy=error.remedy, docs=error.docs,
                         request_id=error.request_id, stage=error.stage)


def retryable(error):
    """R1-1, window reads only: a piece is asked once more after the service could not be reached (a transport error,
    a body cut mid-read included) or a 503 the transport's own retries exhausted."""
    return (isinstance(error, Busy) and error.status == 503) or (type(error) is Unavailable and error.code == 'unreachable')


def window_path(prefix, asset, revision):
    return prefix + '/' + quote(asset, safe='') + '/revisions/' + quote(revision, safe='') + '/volume-windows'


def canonical(asset_id, revision, geometry, axes, format_code, traces_per_piece, schema=WINDOW):
    """The bytes `window_id` digests (s0 D-F): ordinals only; a `/2` window the same form with `schema` set to `/2`."""
    c = {'schema': schema, 'asset_id': asset_id, 'revision': revision, 'geometry': geometry,
         'ranges': {a['name']: [a['first'], a['last']] for a in axes}, 'format_code': format_code, 'traces_per_piece': traces_per_piece}
    return json.dumps(c, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


class WindowDescription:
    """What the client checks a window's axes against: a volume's described context (no bytes), or a line's stored
    description (its context and trace numbers in file order). Reusable through `description=` for the same revision."""
    def __init__(self, asset, revision, geometry, context, numbers=None):
        self.asset, self.revision, self.geometry, self.context, self.numbers = asset, revision, geometry, context, numbers


def describe_volume(asset, revision, descriptor):
    """The description of a volume from its verified descriptor, or None for a line (its stored description is read)."""
    scientific = descriptor.get('scientific') or {}
    geometry = GEOMETRY_OF.get(scientific.get('type'))
    if geometry is None: _failed('axes', 'the asset is not a seismic volume or a 2D seismic line.')
    return WindowDescription(asset, revision, 'volume', scientific) if geometry == 'volume' else None


def line_representation(descriptor):
    found = [r for r in descriptor.get('representations') or () if r.get('id') == 'data']
    if len(found) != 1: _failed('axes', "the line's stored description is not offered.")
    return found[0]


def describe_line(asset, revision, raw):
    try: stored = json.loads(raw)
    except (ValueError, UnicodeError): _failed('axes', "the line's stored description is not JSON.")
    try:
        context, numbers = stored['context'], [int(g[0]) for g in stored['geometry']]
        if context.get('type') != 'seismic-line' or len(numbers) != context['traces']: raise ValueError
    except (KeyError, TypeError, ValueError, IndexError): _failed('axes', "the line's stored description has no trace numbers for its traces.")
    return WindowDescription(asset, revision, 'line', context, numbers)


def _span(text):
    first, _, last = text.partition(':')
    return int(first), int(last or first)


def resolve(description, query):
    """The axes a request names, recomputed here from the description (D98): the document must state exactly these."""
    given = dict(query)
    geometry, context = description.geometry, description.context
    selection = given.get('by') or 'ordinal'
    asked = [k for k in given if k != 'by']
    if any(k not in GEOMETRY_AXES[geometry] for k in asked): _failed('axes', 'the request names an axis this %s does not have.' % geometry)
    axes = []

    def ordinals(name, span, count):
        if not 0 <= span[0] <= span[1] < count: _failed('axes', 'the %s range is outside the asset, yet the server answered.' % name)
        return span
    if geometry == 'volume':
        for name in ('inline', 'crossline'):
            grid = context[name]
            if name not in given: first, last = 0, grid['count'] - 1
            elif selection == 'label':
                labels = _span(given[name])
                if any((v - grid['first']) % grid['step'] for v in labels): _failed('axes', 'the %s labels are not on the grid, yet the server answered.' % name)
                first, last = ordinals(name, tuple((v - grid['first']) // grid['step'] for v in labels), grid['count'])
            else: first, last = ordinals(name, _span(given[name]), grid['count'])
            axes.append({'name': name, 'first': first, 'last': last, 'count': last - first + 1,
                         'labels': [grid['first'] + k * grid['step'] for k in range(first, last + 1)]})
    else:
        first, last = ordinals('trace', _span(given['trace']), context['traces']) if 'trace' in given else (0, context['traces'] - 1)
        axes.append({'name': 'trace', 'first': first, 'last': last, 'count': last - first + 1, 'labels': description.numbers[first:last + 1]})
    first, last = ordinals('sample', _span(given['sample']), context['samples']) if 'sample' in given else (0, context['samples'] - 1)
    interval = float(context['sample_interval'])
    axes.append({'name': 'sample', 'first': first, 'last': last, 'count': last - first + 1, 'start': float(context['first_sample']) + first * interval,
                 'interval': interval, 'unit': context['sample_unit'], 'domain': context['z_domain']})
    return selection, axes


def check_document(document, *, asset, revision, query, description):
    """The window document, checked by name before any piece is asked (D-C); returns it. A native cube's window is
    `/2` (E140 s3): one byte per sample, its code for no value the described one."""
    from .models.generated import VolumeWindow, VolumeWindow2
    from pydantic import ValidationError
    if published(description): return _check_document3(document, asset=asset, revision=revision, query=query, description=description)
    two = native(description)
    schema, model, width = (WINDOW2, VolumeWindow2, 1) if two else (WINDOW, VolumeWindow, 4)
    if not isinstance(document, dict) or set(document) != FIELDS: _failed('identity', 'the document is not an %s document.' % schema)
    try: model.model_validate(document)
    except ValidationError: _failed('identity', 'the document does not satisfy %s.' % schema)
    d = document
    if d['asset_id'] != asset or d['revision'] != revision or d['source_sha256'] != revision:
        _failed('identity', 'the document names another asset or revision than the one asked for.')
    geometry = d['geometry']
    if geometry != description.geometry or d['interpretation']['mapping'] != (NATIVE_MAPPING if two else MAPPING[geometry]):
        _failed('axes', 'the document is not of the asset\'s geometry or not read by its mapping.')
    if tuple(a['name'] for a in d['axes']) != GEOMETRY_AXES[geometry]: _failed('axes', 'the axes are not the geometry\'s, in order.')
    if geometry == 'line' and d['selection'] != 'ordinal': _failed('axes', 'a 2D line is addressed by ordinal.')
    if any(a['count'] != a['last'] - a['first'] + 1 for a in d['axes']): _failed('shape', 'an axis count is not last - first + 1.')
    if any('labels' in a and len(a['labels']) != a['count'] for a in d['axes']): _failed('shape', 'a trace axis does not have one label per trace.')
    if d['shape'] != [a['count'] for a in d['axes']]: _failed('shape', 'the shape is not the axis counts.')
    if d['bytes'] != math.prod(d['shape']) * width: _failed('shape', 'the byte count is not the shape times %d.' % width)
    samples = d['samples']
    form = (NATIVE_FORMAT if samples['format_code'] == NATIVE_CODE else None) if two else FORMATS.get(samples['format_code'])
    if form != samples['format'] or samples['byte_order'] != 'big' or samples['width'] != width:
        _failed('shape', 'the sample format does not match its code.')
    if two and samples['undefined_code'] != description.context.get('undefined_code'):
        _failed('shape', "the code for no value is not the asset's.")
    pieces, traces = d['pieces'], math.prod(d['shape'][:-1])
    per = BYTES_MAX // (d['shape'][-1] * width)
    if pieces['bytes_max'] != BYTES_MAX or pieces['traces_per_piece'] != per or pieces['count'] != -(-traces // per):
        _failed('shape', 'the pieces do not follow the %s partition.' % ('/2' if two else '/1'))
    if d['window_id'] != hashlib.sha256(canonical(asset, revision, geometry, d['axes'], samples['format_code'], per, schema)).hexdigest():
        _failed('identity', 'the window_id is not the digest of the window it describes.')
    if d['verification'] != {'client': CLIENT_CHECKS, 'trusted': TRUSTED}: _failed('identity', 'the verification lists are not the closed lists.')
    selection, axes = resolve(description, query)
    if d['selection'] != selection or d['axes'] != axes or samples['format_code'] != description.context['format_code']:
        _failed('axes', 'the axes are not the ones the request names on this asset.')
    return d


def _check_document3(document, *, asset, revision, query, description):
    """E175 s1 (D-5): a cube as published's `/3` document, checked as `/1`'s and for its own fields: the samples at the
    format's width, the absent positions, the `/3` piece and headers partitions."""
    from .models.generated import VolumeWindow3
    from pydantic import ValidationError
    if not isinstance(document, dict) or set(document) != FIELDS3: _failed('identity', 'the document is not an %s document.' % WINDOW3)
    try: VolumeWindow3.model_validate(document)
    except ValidationError: _failed('identity', 'the document does not satisfy %s.' % WINDOW3)
    d = document
    if d['asset_id'] != asset or d['revision'] != revision or d['source_sha256'] != revision:
        _failed('identity', 'the document names another asset or revision than the one asked for.')
    if d['geometry'] != 'volume' or d['interpretation']['mapping'] != PUBLISHED_MAPPING:
        _failed('axes', 'the document is not of the asset\'s geometry or not read by its mapping.')
    if tuple(a['name'] for a in d['axes']) != GEOMETRY_AXES['volume']: _failed('axes', 'the axes are not the geometry\'s, in order.')
    if any(a['count'] != a['last'] - a['first'] + 1 for a in d['axes']): _failed('shape', 'an axis count is not last - first + 1.')
    if any('labels' in a and len(a['labels']) != a['count'] for a in d['axes']): _failed('shape', 'a trace axis does not have one label per trace.')
    if d['shape'] != [a['count'] for a in d['axes']]: _failed('shape', 'the shape is not the axis counts.')
    samples, code = d['samples'], d['samples']['format_code']
    if PUBLISHED_FORMATS.get(code) != samples['format'] or samples['byte_order'] != 'big' or samples['width'] != PUBLISHED_WIDTH.get(code):
        _failed('shape', 'the sample format does not match its code.')
    width, positions, absent = samples['width'], math.prod(d['shape'][:-1]), d['absent']
    if absent['encoding'] != 'bitmap-msb' or not 0 <= absent['count'] <= positions: _failed('mask', 'the absent positions are not a mask of this window.')
    pieces, per = d['pieces'], published_per(d['shape'][-1], width)
    if pieces['bytes_max'] != BYTES_MAX or pieces['traces_per_piece'] != per or pieces['count'] != -(-positions // per):
        _failed('shape', 'the pieces do not follow the /3 partition.')
    if d['headers'] != {'count': -(-positions // HEADERS_PER_ANSWER3), 'traces_per_answer': HEADERS_PER_ANSWER3}:
        _failed('shape', 'the headers answers do not follow the /3 partition.')
    if d['bytes'] != published_bytes(positions, absent['count'], per, d['shape'][-1], width):
        _failed('shape', 'the byte count is not the masks and the present traces.')
    if d['window_id'] != hashlib.sha256(canonical(asset, revision, 'volume', d['axes'], code, per, WINDOW3)).hexdigest():
        _failed('identity', 'the window_id is not the digest of the window it describes.')
    if d['verification'] != {'client': CLIENT_CHECKS3, 'trusted': TRUSTED}: _failed('identity', 'the verification lists are not the closed lists.')
    selection, axes = resolve(description, query)
    if d['selection'] != selection or d['axes'] != axes or code != description.context['format_code']:
        _failed('axes', 'the axes are not the ones the request names on this asset.')
    return d


class MaskDigest:
    """D-M: the window's absent bits, fed piece by piece (padding stripped) and digested as one bit string padded once
    at the end; `close()` checks the digest and the count of ones against the document's `absent`."""
    def __init__(self, document):
        self.absent, self.digest, self.carry, self.held, self.ones = document['absent'], hashlib.sha256(), 0, 0, 0

    def add(self, bits, n):
        self.ones += bits.bit_count()
        value, held = (self.carry << n) | bits, self.held + n
        whole, self.held = divmod(held, 8)
        if whole: self.digest.update((value >> self.held).to_bytes(whole, 'big'))
        self.carry = value & ((1 << self.held) - 1)

    def close(self, what='pieces'):
        if self.held: self.digest.update((self.carry << (8 - self.held)).to_bytes(1, 'big')); self.held = 0
        if self.digest.hexdigest() != self.absent['sha256'] or self.ones != self.absent['count']:
            _failed('mask', 'the %s\' masks do not digest to the window\'s absent positions.' % what)


def split_masked(index, body, positions, record):
    """E175 s1 (D-5): a `/3` piece or headers answer of `positions` positions, after its identity and digest: its mask
    (padding bits zero), then `record` bytes for each present position. Returns (bits as an integer, the records)."""
    m = mask_bytes(positions)
    if len(body) < m: _failed('completeness', 'answer %d is shorter than its mask.' % index)
    bits = int.from_bytes(body[:m], 'big')
    pad = 8 * m - positions
    if bits & ((1 << pad) - 1): _failed('mask', 'answer %d has a padding bit set in its mask.' % index)
    bits >>= pad
    present = positions - bits.bit_count()
    if len(body) != m + present * record:
        _failed('completeness', 'answer %d has %d bytes, not its mask and %d present traces.' % (index, len(body), present))
    return bits, body[m:]


def codes(body):
    """E140 s3: a native window's one-byte codes, verbatim, as two's complement integers (-128..127)."""
    return list(struct.unpack('>%db' % len(body), body))


def decode(body, code, undefined_code=None):
    """The window's stored 4-byte big-endian words as floats: IBM (code 1) exactly, IEEE (code 5) widened; a native
    window's one-byte codes (code 8) as their values, NaN where a code means no value (S/native_form.values)."""
    if code == NATIVE_CODE:
        from .native_form import values
        return values(body, undefined_code)
    if code in INTEGER_CODES:  # E175 s1: a code of a cube as published is its value, as a float (float64 holds it exactly)
        n = len(body) // PUBLISHED_WIDTH[code]
        return [float(v) for v in struct.unpack('>%d%s' % (n, 'h' if code == 3 else 'i'), body)]
    n = len(body) // 4
    if code == 5: return list(struct.unpack('>%df' % n, body))
    return [_ibm(w) for w in struct.unpack('>%dI' % n, body)]


def _ibm(word):
    """An IBM System/360 single word, exactly: sign, base-16 exponent biased by 64, 24-bit fraction (zero, negative zero
    and unnormalized words included)."""
    fraction = word & 0xFFFFFF
    value = math.ldexp(fraction, 4 * (((word >> 24) & 0x7F) - 64) - 24) if fraction else 0.0
    return -value if word >> 31 else value


class WindowPiece:
    """One verified piece: window traces `traces = (first, last)` in C order of the trace axes, `values` one list of
    floats per trace. For a native window (`/2`), `codes()` returns the stored one-byte codes verbatim, one list of
    integers per trace; `raw` is the verified body. E175 s1: for an integer cube as published (`/3`, format 2 or 3)
    `codes()` returns its stored integers, one list per position, None for an absent position (`values` too)."""
    def __init__(self, index, count, traces, values, raw=None, samples=None, integer=False):
        self.index, self.count, self.traces, self.values = index, count, traces, values
        self.raw, self._samples, self._integer = raw, samples, integer

    def codes(self):
        if self._integer: return [None if t is None else [int(v) for v in t] for t in self.values]
        if self.raw is None: raise ValueError('Only a window of an 8-bit cube or of an integer cube holds codes; this one holds float words.')
        flat, s = codes(self.raw), self._samples
        return [flat[k * s:(k + 1) * s] for k in range(len(flat) // s)]

    def __repr__(self): return 'WindowPiece(%d/%d, traces=%d:%d)' % (self.index, self.count, *self.traces)


class Window:
    """A checked window being read: the pure half both readers share (piece paths, piece checks, the digest)."""
    def __init__(self, document, query, description, base):
        self.document, self.query, self.description, self.base = document, query, description, base
        self.count, self.per = document['pieces']['count'], document['pieces']['traces_per_piece']
        self.samples, self.traces = document['shape'][-1], math.prod(document['shape'][:-1])
        self.code = document['samples']['format_code']
        self.width, self.undefined = document['samples']['width'], document['samples'].get('undefined_code')
        self.request = asked(query, description)  # E140 s3: windows=2 for a native cube only; E175 s1: 3 for a cube as published
        self.digest, self.next, self.total, self.complete = hashlib.sha256(), 0, 0, False
        self.three = document['schema'] == WINDOW3
        self.mask = MaskDigest(document) if self.three else None

    def span(self, index):
        return index * self.per, min((index + 1) * self.per, self.traces) - 1

    def piece(self, index):
        """(path, body length) of piece `index`: exact, or for `/3` the most it can be (its mask and every trace; the
        exact length is known from its mask, R1-4)."""
        first, last = self.span(index)
        n = last - first + 1
        return (self.base + '/pieces/%d?' % index + urlencode(self.request + [('window', self.document['window_id'])]),
                (mask_bytes(n) if self.three else 0) + n * self.samples * self.width)

    def accept(self, index, body, answer):
        first, last = self.span(index)
        if self.three:
            verify_piece(self.document, index, body, answer, len(body))  # identity and digest; the length follows the mask
            bits, words = split_masked(index, body, last - first + 1, self.samples * self.width)
            self.mask.add(bits, last - first + 1)
        else: verify_piece(self.document, index, body, answer, self.piece(index)[1])
        self.digest.update(body); self.total += len(body); self.next = index + 1
        if self.next == self.count:
            if self.three: self.mask.close()  # first: a coherently shortened piece is a mask defect (R1-9)
            if self.total != self.document['bytes']: _failed('completeness', 'the pieces do not add up to the window.')
            self.complete = True
        if not self.three:
            flat = decode(body, self.code, self.undefined)
            raw = body if self.code == NATIVE_CODE else None
            return WindowPiece(index, self.count, (first, last), [flat[k * self.samples:(k + 1) * self.samples] for k in range(last - first + 1)],
                               raw, self.samples)
        flat, n, traces, at = decode(words, self.code), last - first + 1, [], 0
        for k in range(n):  # MSB first: position k is bit n - 1 - k
            if bits >> (n - 1 - k) & 1: traces.append(None)
            else: traces.append(flat[at * self.samples:(at + 1) * self.samples]); at += 1
        return WindowPiece(index, self.count, (first, last), traces, None, self.samples, self.code in INTEGER_CODES)

    @property
    def window_digest(self): return self.digest.hexdigest() if self.complete else None


def verify_piece(document, index, body, answer, length):
    """A piece's identity headers (each required), its digest and its length (D-C)."""
    expected = {'x-ophiolite-window': document['window_id'], 'x-ophiolite-revision': document['revision'],
                'x-ophiolite-piece': '%d/%d' % (index, document['pieces']['count'])}
    for header, value in expected.items():
        if answer.get(header) != value: _failed('piece-identity', 'piece %d does not carry %s %s.' % (index, header, value))
    stated = answer.get('x-content-sha256')
    if not stated or hashlib.sha256(body).hexdigest() != stated:
        raise IntegrityConflict('Piece %d does not match its X-Content-SHA256; nothing of it was used.' % index, details={'check': 'piece-digest'})
    if len(body) != length: _failed('completeness', 'piece %d has %d bytes, not %d.' % (index, len(body), length))


class VolumeWindowResult:
    """A whole window read and verified: `.document`, `.axes`, `.shape`, `.values` (nested lists of float in C order:
    [inline][crossline][sample] or [trace][sample]), `.window_digest`, and `to_numpy()` when numpy is installed."""
    def __init__(self, window, traces):
        self.document, self.description = window.document, window.description
        self.axes, self.shape, self.window_digest = window.document['axes'], window.document['shape'], window.window_digest
        if len(self.shape) == 3:
            x = self.shape[1]
            self.values = [traces[i * x:(i + 1) * x] for i in range(self.shape[0])]
        else: self.values = traces

    def to_numpy(self):
        import numpy  # optional: only this method needs it
        if self.document['schema'] == WINDOW3:  # E175 s1: an absent position (none in s1) reads as NaN
            nan = [math.nan] * self.shape[-1]
            return numpy.asarray([[nan if t is None else t for t in row] for row in self.values], dtype=numpy.float64).reshape(self.shape)
        return numpy.asarray(self.values, dtype=numpy.float64).reshape(self.shape)

    def codes(self):
        """E175 s1: an integer cube as published's stored integers, [inline][crossline][sample]. E175 s2 (D-H3): a window
        with positions without a trace refuses (`masked`); its integer form is `to_masked()`."""
        if self.document['schema'] != WINDOW3 or self.document['samples']['format_code'] not in INTEGER_CODES:
            raise ValueError('Only a window of an integer cube as published holds integer codes.')
        if self.document['absent']['count']: raise WindowRefused('masked', MASKED)
        return [[None if t is None else [int(v) for v in t] for t in row] for row in self.values]

    def to_masked(self):
        """E175 s1: a `/3` window as a numpy.ma.MaskedArray, int16 or int32 for an integer cube (float64 for float
        formats), masked where a position is absent (none in s1: every mask is false)."""
        import numpy  # optional: only this method needs it
        if self.document['schema'] != WINDOW3: raise ValueError('Only a window of a cube as published has absent positions to mask.')
        dtype = {2: numpy.int32, 3: numpy.int16}.get(self.document['samples']['format_code'], numpy.float64)
        zero = [0] * self.shape[-1]
        data = numpy.asarray([[zero if t is None else t for t in row] for row in self.values], dtype=numpy.float64).astype(dtype).reshape(self.shape)
        absent = numpy.asarray([[[t is None] * self.shape[-1] for t in row] for row in self.values], dtype=bool).reshape(self.shape)
        return numpy.ma.MaskedArray(data, mask=absent)


class WindowReader:
    """`Client.iter_window`: the pieces of a checked window, one at a time, each verified (memory: one piece decoded).
    `.complete` and `.window_digest` (None until the last piece is verified); `close()` and `with`."""
    def __init__(self, client, window):
        self.client, self.window, self.closed = client, window, False

    @property
    def document(self): return self.window.document
    @property
    def complete(self): return self.window.complete
    @property
    def window_digest(self): return self.window.window_digest

    def __iter__(self): return self

    def __next__(self):
        if self.closed or self.window.next >= self.window.count: raise StopIteration
        index = self.window.next
        path, length = self.window.piece(index)
        for attempt in (0, 1):
            answer = {}
            try: body = self.client._window_get(path, length, answer)
            except OphioliteError as error:
                if attempt == 0 and retryable(error): continue
                raise
            return self.window.accept(index, body, answer)

    def close(self): self.closed = True
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class AsyncWindowReader:
    """`AsyncClient.iter_window`: as WindowReader, with `async for`, `aclose()` and `async with`; a cancelled read
    closes its open response (the transport's stream context)."""
    def __init__(self, client, window):
        self.client, self.window, self.closed = client, window, False

    @property
    def document(self): return self.window.document
    @property
    def complete(self): return self.window.complete
    @property
    def window_digest(self): return self.window.window_digest

    def __aiter__(self): return self

    async def __anext__(self):
        if self.closed or self.window.next >= self.window.count: raise StopAsyncIteration
        index = self.window.next
        path, length = self.window.piece(index)
        for attempt in (0, 1):
            answer = {}
            try: body = await self.client._window_get(path, length, answer)
            except OphioliteError as error:
                if attempt == 0 and retryable(error): continue
                raise
            return self.window.accept(index, body, answer)

    async def aclose(self): self.closed = True
    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.aclose()


# --- E141 s2: a window comes to disk as SEG-Y (D-X, D-W, D-S) -------------------------------------------------------

FILE_HEADER, TRACE_HEADER = 3600, 240
HEADERS_PER_ANSWER = BYTES_MAX // TRACE_HEADER  # D-H: 139,810 trace headers per headers answer (<= 32 MiB)
DELAY, COUNT, BINARY_COUNT, REVISION, FORMAT = 108, 114, 3220, 3500, 3224  # 0-based: bytes 109-110, 115-116, 3221-3222, 3501-3502, 3225-3226
REVISIONS = (0x0000, 0x0100)
POSITIONS = ('inline', 'crossline', 'cdp_x', 'cdp_y')
SPOKEN = {'inline': 'inline number', 'crossline': 'crossline number', 'cdp_x': 'x coordinate', 'cdp_y': 'y coordinate'}
WINDOW_CODES = ('inexact-crop', 'revision-unsupported', 'header-positions-overlap', 'window-volume-only', 'volume-needs-window', 'window-needs-output',
                'crop-not-segy')
CROP_NOT_SEGY = ('This part of the cube has a line with no trace, which a SEG-Y file cannot state. Choose a part where every '
                 'line holds a trace. Nothing was written.')
LINE_WINDOW = 'A 2D line has no window file; get writes its original.'
OTHER_WINDOW = 'Only a seismic volume is written as a window file; get this item without --window.'
VOLUME_NEEDS_WINDOW = 'Give a window, for example --window inline=100:104,by=label, or call Client.download_original for the whole file.'
NEEDS_OUTPUT = 'A window is written as a file: give a folder to write it into.'


def cannot(code, sentence, **technical):
    """D-S (R1-6): a window `exchange get` cannot write, refused as CannotReadHere (an ExchangeRefused Exchange.fetch
    keeps): `technical.reason` the code, the sentence in the facts; byte numbers go into `technical` (R1-17)."""
    from .exchange import CannotReadHere  # the vendored core never imports this module
    if code not in WINDOW_CODES and code not in REASONS: raise ValueError('Unknown window code: %s' % code)
    return CannotReadHere(sentence, {'sentence': sentence, 'reason': sentence.rstrip('.')}, {'reason': code, **technical})


def as_exchange(refused):
    """An s1 WindowRefused met by `exchange get`, as CannotReadHere with its reason and sentence (R1-6)."""
    return cannot(refused.reason, str(refused))


def _ms(us):
    """Microseconds as milliseconds, with no trailing zeros: 19500 -> '19.5', -2000 -> '-2'."""
    return ('-' if us < 0 else '') + ('%d.%03d' % divmod(abs(us), 1000)).rstrip('0').rstrip('.')


def exact_crop(document, samples=None):
    """D-X, on metadata alone (R1-5): the trace delay a window file states (bytes 109-110), or None when the window
    starts at sample 0 (the original's delay is kept). Refuses `inexact-crop` when the start is not a whole
    millisecond of a time volume or does not fit 16 bits. `samples` (the stored count) bounds the samples suggested."""
    sample = document['axes'][-1]
    s0 = sample['first']
    if s0 == 0: return None
    if sample['domain'] != 'time':
        kind = 'a depth volume' if sample['domain'] == 'depth' else 'a volume whose samples are neither time nor depth'
        raise cannot('inexact-crop', 'This window starts at sample %d of %s; this file format cannot state a cropped %s start. Start at sample 0.'
                     % (s0, kind, 'depth' if sample['domain'] == 'depth' else 'sample'), field='bytes 109-110', domain=sample['domain'])
    interval, start = round(sample['interval'] * 1000), round(sample['start'] * 1000)  # microseconds
    if start % 1000:
        first = start - s0 * interval
        last = s0 + 1000 if samples is None else samples - 1
        lower = next((k for k in range(s0 - 1, -1, -1) if (first + k * interval) % 1000 == 0), None)
        upper = next((k for k in range(s0 + 1, last + 1) if (first + k * interval) % 1000 == 0), None)
        near = ' or '.join(str(k) for k in (lower, upper) if k is not None)
        raise cannot('inexact-crop', 'This window starts at %s ms; this file format holds whole milliseconds. %s'
                     % (_ms(start), 'Start at sample %s.' % near if near else 'Start at sample 0.'),
                     field='bytes 109-110', start_us=start, nearest=[k for k in (lower, upper) if k is not None])
    delay = start // 1000
    if not -32768 <= delay <= 32767:
        raise cannot('inexact-crop', 'This window starts at %s ms; this file format holds starts from -32,768 to 32,767 ms. Start at an earlier sample.'
                     % _ms(start), field='bytes 109-110', start_us=start)
    return delay


def positions_clear(positions):
    """D-X (R1-7): no declared 4-byte header position may overlap the fields a window file rewrites (109-110, 115-116)."""
    for name in POSITIONS:
        p = positions[name]
        if any(p <= last and p + 3 >= first for first, last in ((109, 110), (115, 116))):
            raise cannot('header-positions-overlap', 'This volume keeps its %s where a window file states its start time or sample count, '
                         'so its window cannot be written as a file.' % SPOKEN[name], field=name, position=p, rewritten=['bytes 109-110', 'bytes 115-116'])
    return positions


def parse_positions(text):
    """X-Ophiolite-Header-Positions: `inline=189,crossline=193,cdp_x=181,cdp_y=185`, every name once, each 1-237."""
    found = {}
    for part in (text or '').split(','):
        name, eq, value = part.partition('=')
        if not eq or name not in POSITIONS or name in found or not value.isdigit() or not 1 <= int(value) <= 237:
            _failed('file-header', 'the file header does not state the trace header positions.')
        found[name] = int(value)
    if set(found) != set(POSITIONS): _failed('file-header', 'the file header does not state the trace header positions.')
    return found


def _identity(document, what, answer, piece=None):
    expected = {'x-ophiolite-window': document['window_id'], 'x-ophiolite-revision': document['revision']}
    if piece is not None: expected['x-ophiolite-piece'] = piece
    for header, value in expected.items():
        if answer.get(header) != value: _failed(what, 'the answer does not carry %s %s.' % (header, value))


def _digest(what, body, answer):
    stated = answer.get('x-content-sha256')
    if not stated or hashlib.sha256(body).hexdigest() != stated: _failed(what, 'the answer does not match its X-Content-SHA256.')


def check_file_header(document, body, answer):
    """The file-header answer: identity headers, digest, 3,600 bytes and the window's sample format; then (D-X, after
    the file header and before any trace header or sample) the revision field and the header positions. Returns the
    positions."""
    _identity(document, 'file-header', answer)
    _digest('file-header', body, answer)
    if len(body) != FILE_HEADER: _failed('file-header', 'the file header has %d bytes, not %d.' % (len(body), FILE_HEADER))
    if struct.unpack_from('>h', body, FORMAT)[0] != document['samples']['format_code']: _failed('file-header', 'the file header states another sample format.')
    revision = struct.unpack_from('>H', body, REVISION)[0]
    if revision not in REVISIONS:
        raise cannot('revision-unsupported', 'This volume\'s file states SEG-Y revision %d.%d; a window file is written from revision 0 or 1 files only.'
                     % divmod(revision, 256), field='bytes 3501-3502', value=revision)
    return positions_clear(parse_positions(answer.get('x-ophiolite-header-positions')))


def headers_count(document, per=None):
    traces = math.prod(document['shape'][:-1])
    return -(-traces // (per or HEADERS_PER_ANSWER))


def check_headers(document, index, count, body, answer, length):
    """A headers answer: identity headers (window, revision, n/count), digest and length (D-W)."""
    _identity(document, 'headers-identity', answer, '%d/%d' % (index, count))
    _digest('headers-digest', body, answer)
    if len(body) != length: _failed('completeness', 'headers answer %d has %d bytes, not %d.' % (index, len(body), length))


def once_more(ask):
    """R1-1, as window pieces: an answer is asked once more after a transport failure or an exhausted 503."""
    for attempt in (0, 1):
        try: return ask()
        except OphioliteError as error:
            if attempt == 0 and retryable(error): continue
            raise


class SegyWindowWriter:
    """D-W: `staging/window.sgy` from the original's file header (3221-3222 rewritten), then every window trace in C
    order: its header from the current headers answer (109-110 and 115-116 rewritten; its inline and crossline checked
    at the stored positions) and its stored words verbatim from the current samples piece (s1 partition), asking the
    next answer of either kind when one runs out. Words are never decoded. Memory: one headers answer + one piece +
    one trace. `write(ask_headers, ask_piece)`; each ask(n) returns (body, answer headers)."""
    def __init__(self, staging, document, file_header, positions, delay=None, headers_per=None):
        from pathlib import Path
        self.staging, self.document, self.positions, self.delay = Path(staging), document, positions, delay
        self.file_header = bytearray(file_header)
        self.samples, self.traces = document['shape'][-1], math.prod(document['shape'][:-1])
        self.width, self.code = document['samples']['width'], document['samples']['format_code']  # E140 s3: `/2` is 1 byte, format 8
        self.per_piece, self.pieces = document['pieces']['traces_per_piece'], document['pieces']['count']
        self.three = document['schema'] == WINDOW3  # E175 s1 (D-5): masks lead pieces and headers answers
        self.per_headers = headers_per or (document['headers']['traces_per_answer'] if self.three else HEADERS_PER_ANSWER)  # R1-4: the document's partition
        self.headers = headers_count(document, self.per_headers)
        self.path = self.staging / 'window.sgy'
        self.window_digest, self.headers_digest = hashlib.sha256(), hashlib.sha256()
        self.masks = (MaskDigest(document), MaskDigest(document)) if self.three else None  # pieces', headers answers'
        self.asked = []  # (kind, index) in the order asked

    def headers_length(self, index):
        """The most headers answer `index` can hold: 240 bytes a trace, and for `/3` its mask first (R1-4)."""
        k = min((index + 1) * self.per_headers, self.traces) - index * self.per_headers
        return (mask_bytes(k) if self.three else 0) + k * TRACE_HEADER

    def _present(self, kind, index, body, answer, positions, record, fold=True):
        """A `/3` answer checked (identity, digest, mask, length) and, when `fold`, fed to its mask digest. Returns
        (bits as an integer, the mask bytes, the records after the mask). E175 s2: a set bit is a position without a
        trace; whether the window can still be a SEG-Y file is the pre-pass's question (D-W2)."""
        if kind == 'pieces': verify_piece(self.document, index, body, answer, len(body))
        else: check_headers(self.document, index, self.headers, body, answer, len(body))
        bits, records = split_masked(index, body, positions, record)
        if fold: self.masks[kind != 'pieces'].add(bits, positions)
        return bits, bytes(body[:mask_bytes(positions)]), records

    def _occupancy(self, ask_headers):
        """E175 s2 (D-W2): every headers answer asked once, its mask verified and folded into the window-wide digest, and
        each window inline and crossline marked when it holds a present trace. A line without one refuses
        `crop-not-segy` before `window.sgy` is opened. Memory: one answer, a flag per line, 32 bytes per answer (R1-4).
        Returns the sha256 of each answer's mask, which the write's second asking must match."""
        ni, nx = self.document['shape'][0], self.document['shape'][1]
        rows, unseen, kept = [False] * ni, set(range(nx)), []  # inlines holding a trace; crosslines not yet seen holding one
        for h in range(self.headers):
            first, end = h * self.per_headers, min((h + 1) * self.per_headers, self.traces)
            self.asked.append(('headers', h))
            body, answer = ask_headers(h)
            bits, mask, _ = self._present('headers', h, body, answer, end - first, TRACE_HEADER)
            kept.append(hashlib.sha256(mask).digest())
            gone = (lambda k: mask[(k - first) >> 3] >> (7 - ((k - first) & 7)) & 1) if bits else (lambda k: 0)
            for i in range(first // nx, (end - 1) // nx + 1):
                a, b = max(first, i * nx), min(end, (i + 1) * nx)
                if not rows[i]: rows[i] = any(not gone(k) for k in range(a, b))
                unseen -= {x for x in unseen if a <= i * nx + x < b and not gone(i * nx + x)}
        self.masks[1].close('headers answers')
        if not all(rows) or unseen: raise cannot('crop-not-segy', CROP_NOT_SEGY)
        return kept

    def write(self, ask_headers, ask_piece):
        d, S, W = self.document, self.samples, self.width
        inlines, crosslines = d['axes'][0]['labels'], d['axes'][1]['labels']
        nx = len(crosslines)
        absent = d['absent']['count'] if self.three else 0
        if absent == self.traces: raise cannot('crop-not-segy', CROP_NOT_SEGY)  # D-W2 case 1: no answer asked
        kept = self._occupancy(ask_headers) if absent else None  # case 3; case 2 (none absent) asks as s1 did
        struct.pack_into('>H', self.file_header, BINARY_COUNT, S)
        struct.pack_into('>h', self.file_header, FORMAT, self.code)  # the window's sample format (checked equal to the original's)
        self.staging.mkdir(mode=0o700, exist_ok=True)
        h, p, h_body, p_body, h_first, p_first, h_end, p_end, written = -1, -1, b'', b'', 0, 0, 0, 0, 0
        h_bits = p_bits = h_at = p_at = 0
        with open(self.path, 'xb') as out:  # a refusal below leaves it in Exchange.get's staging, which is removed (R1-13)
            out.write(self.file_header); written += FILE_HEADER
            for k in range(self.traces):
                if k >= h_end:
                    h += 1; h_first, h_end, h_at = h * self.per_headers, min((h + 1) * self.per_headers, self.traces), 0
                    self.asked.append(('headers', h))
                    h_body, answer = ask_headers(h)
                    self.headers_digest.update(h_body)
                    if self.three:
                        h_bits, mask, h_body = self._present('headers', h, h_body, answer, h_end - h_first, TRACE_HEADER, fold=not absent)
                        if absent and hashlib.sha256(mask).digest() != kept[h]: raise WindowRefused('headers-changed', HEADERS_CHANGED)
                    else: check_headers(d, h, self.headers, h_body, answer, (h_end - h_first) * TRACE_HEADER)
                if k >= p_end:
                    p += 1; p_first, p_end, p_at = p * self.per_piece, min((p + 1) * self.per_piece, self.traces), 0
                    self.asked.append(('pieces', p))
                    p_body, answer = ask_piece(p)
                    self.window_digest.update(p_body)
                    if self.three: p_bits, _, p_body = self._present('pieces', p, p_body, answer, p_end - p_first, S * W)
                    else: verify_piece(d, p, p_body, answer, (p_end - p_first) * S * W)
                gone = h_bits >> (h_end - 1 - k) & 1
                if gone != p_bits >> (p_end - 1 - k) & 1:
                    _failed('mask', 'position %d is %s in the headers answer and not in its piece.' % (k, 'absent' if gone else 'present'))
                if gone: continue  # E175 s2 (D-W2): a position without a trace is not written
                header = bytearray(h_body[h_at * TRACE_HEADER:(h_at + 1) * TRACE_HEADER]); h_at += 1
                expected = (inlines[k // nx], crosslines[k % nx])
                carried = (struct.unpack_from('>i', header, self.positions['inline'] - 1)[0], struct.unpack_from('>i', header, self.positions['crossline'] - 1)[0])
                if carried != expected:
                    _failed('headers-identity', 'trace header %d carries inline %d, crossline %d, not inline %d, crossline %d.' % (k, *carried, *expected))
                struct.pack_into('>H', header, COUNT, S)
                if self.delay is not None: struct.pack_into('>h', header, DELAY, self.delay)
                out.write(header); out.write(p_body[p_at * S * W:(p_at + 1) * S * W]); p_at += 1; written += TRACE_HEADER + S * W
            if self.three: self.masks[0].close()
            if self.three and not absent: self.masks[1].close('headers answers')  # a sparse window's closed in the pre-pass
            if (h, p) != (self.headers - 1, self.pieces - 1) or written != FILE_HEADER + (self.traces - absent) * (TRACE_HEADER + S * W):
                _failed('completeness', 'the window file does not hold every trace of the window.')
            out.flush(); os.fsync(out.fileno())
        return {'bytes': written, 'traces': self.traces - absent, 'window_digest': self.window_digest.hexdigest(), 'headers_digest': self.headers_digest.hexdigest()}
