"""E175 s2 C4 (strategy D-H3, D-W2; C4 tests 2-4): the SDK's checks of real masks, and `exchange get --window` of a
crop of a cube as published with positions without a trace, over the s1 mock gateway (test_published_windows).

The 5 x 7 int16 cube has no trace at four positions (ordinals): (1, 0) and (2, 0), so crossline 0 is empty in inlines
1-2; (3, 2) and (3, 3), so inline 3 is empty in crosslines 2-3. Pieces of four positions (BYTES_MAX 100) and headers
answers of sixteen (HEADERS_PER_ANSWER3 16): position 7 is the last bit of piece 1 (mask 10), 14 the third of piece
3 (mask 20), so those two pieces have different masks, equal lengths and equal popcounts (R1-10); headers answers 0
(positions 7, 14) and 1 (23, 24) likewise. Every expected mask and request list is a literal."""
import hashlib
import struct

import pytest

from ophiolite import volume_windows as vw
from ophiolite.errors import OphioliteError, VerificationFailed
from ophiolite.exchange import CannotReadHere
from test_published_windows import PublishedGateway, read_sync, rehashed, value
from test_volume_window import BASE, S, cells, world  # noqa: F401 (fixture)
from test_volume_window_2 import unchecked_descriptor  # noqa: F401 (fixture)

GONE = {(1, 0), (2, 0), (3, 2), (3, 3)}


def bitmap(bits):
    return bytes(sum(b << (7 - k) for k, b in enumerate(bits[n:n + 8])) for n in range(0, len(bits), 8))


class SparseGateway(PublishedGateway):
    """The s1 mock with real masks: a position in GONE has no trace; the document's `absent` and `bytes`, each piece
    and each headers answer follow (D-M, D-H3)."""
    def __init__(self, code=3, gone=GONE):
        super().__init__(code)
        self.gone = gone
        self.ctx = dict(self.ctx, absent=len(gone))
        self.document_change = self.sparse

    def sparse(self, d):
        bits = [c in self.gone for c in cells(d)]
        d['absent'].update(count=sum(bits), sha256=hashlib.sha256(bitmap(bits)).hexdigest())
        d['bytes'] -= sum(bits) * d['shape'][-1] * d['samples']['width']

    def masked(self, body, chosen, record):
        dense = body[-(-len(chosen) // 8):]
        kept = b''.join(dense[k * record:(k + 1) * record] for k, c in enumerate(chosen) if c not in self.gone)
        return bitmap([c in self.gone for c in chosen]) + kept

    def headers_answer(self, document, n, per=None):
        body, extra = super().headers_answer(document, n)
        return self.masked(body, cells(document)[n * vw.HEADERS_PER_ANSWER3:(n + 1) * vw.HEADERS_PER_ANSWER3], 240), extra

    def piece_answer(self, document, n):
        body, extra = super().piece_answer(document, n)
        per = document['pieces']['traces_per_piece']
        return self.masked(body, cells(document)[n * per:(n + 1) * per], document['shape'][-1] * 2), extra


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(vw, 'BYTES_MAX', 100); monkeypatch.setattr(vw, 'HEADERS_PER_ANSWER3', 16)


def pieces(name): return '/volume-windows/' + name


def swap(other):
    """A tamper that answers another answer's body (its digest restated): mask, length and popcount all plausible."""
    def tamper(status, body, headers):
        return status, other, {**headers, 'x-content-sha256': hashlib.sha256(other).hexdigest()}
    return tamper


# --- 2. mask attacks on real bits ----------------------------------------------------------------------------------

def test_the_masks_are_the_literals_this_file_names(unchecked_descriptor, small):
    gateway = SparseGateway()
    document = read_sync(gateway.handler, sample='0:10').document
    assert [gateway.piece_answer(document, n)[0][0] for n in (1, 3)] == [0x10, 0x20]
    assert [gateway.headers_answer(document, n)[0][:2] for n in (0, 1)] == [bytes.fromhex('0102'), bytes.fromhex('0180')]


ATTACKS = {  # name: (answer, change, the check that names it)
    'a bit flipped': ('pieces/0', lambda b: bytearray([b[0] | 0x80]) + b[1:], 'completeness'),
    'mask truncated': ('pieces/3', lambda b: b[:0], 'completeness'),
    'padding set': ('pieces/8', lambda b: bytearray([b[0] | 0x1F]) + b[1:], 'mask'),
    'masks swapped': ('pieces/1', 'pieces/3', 'mask'),
}


def attack(gateway, name, document):
    path, change, _ = ATTACKS[name]
    if isinstance(change, str): gateway.tamper[pieces(path)] = swap(gateway.piece_answer(document, int(change.rsplit('/', 1)[1]))[0])
    else: gateway.tamper[pieces(path)] = rehashed(change)


@pytest.mark.parametrize('name', sorted(ATTACKS))
def test_each_attack_on_a_real_mask_fails_its_named_check(unchecked_descriptor, small, name):
    """R1-10: the swapped pieces pass their own length and mask checks; only the final mask digest rejects them.
    Mutations: each check removed in turn (split_masked's length and padding, MaskDigest.close)."""
    gateway = SparseGateway()
    attack(gateway, name, read_sync(SparseGateway().handler, sample='0:10').document)
    with pytest.raises(VerificationFailed) as no: read_sync(gateway.handler, sample='0:10')
    assert no.value.details['check'] == ATTACKS[name][2]


HEADER_ATTACKS = {
    'a bit flipped': ('headers/0', lambda b: bytearray([b[0] | 0x80]) + b[1:], 'completeness'),
    'padding set': ('headers/2', lambda b: bytearray([b[0] | 0x1F]) + b[1:], 'mask'),
    'masks swapped': ('headers/0', 'headers/1', 'mask'),
}


@pytest.mark.parametrize('kind,name', [('pieces', n) for n in sorted(ATTACKS)] + [('headers', n) for n in sorted(HEADER_ATTACKS)])
def test_each_attack_fails_exchange_get_and_leaves_no_output(world, unchecked_descriptor, small, kind, name):
    """The same attacks through `exchange get --window` (the writer checks pieces and headers answers itself)."""
    make, tmp = world
    gateway, clean = SparseGateway(), SparseGateway()
    document = read_document(clean)
    if kind == 'pieces': attack(gateway, name, document)
    else:
        path, change, _ = HEADER_ATTACKS[name]
        if isinstance(change, str): gateway.tamper[pieces(path)] = swap(clean.headers_answer(document, int(change.rsplit('/', 1)[1]))[0])
        else: gateway.tamper[pieces(path)] = rehashed(change)
    with pytest.raises(OphioliteError) as no: make(gateway).get('cube', output=tmp / 'out', window='sample=0:10')
    assert no.value.outcome == 'damaged' and isinstance(no.value.__cause__, VerificationFailed)  # the writer's own check, kept as the cause
    assert no.value.__cause__.details['check'] == (ATTACKS if kind == 'pieces' else HEADER_ATTACKS)[name][2] and not (tmp / 'out').exists()


def read_document(gateway):
    return read_sync(gateway.handler, sample='0:10').document


# --- 3. exchange get: written, or refused before writing ---------------------------------------------------------

def windows(gateway):
    return [u.split('?')[0][len(BASE + '/volume-windows/'):] for u in gateway.urls if '/headers/' in u or '/pieces/' in u]


def test_the_whole_sparse_cube_writes_its_31_present_traces(world, small):
    """D-W2 case 3 that passes: the pre-pass asks each headers answer once, then the write asks as s1 did. Mutation:
    absent positions written (RED: length)."""
    make, tmp = world
    gateway = SparseGateway()
    assert make(gateway).get('cube', output=tmp / 'out', window='sample=0:10').outcome == 'got'
    written = (tmp / 'out' / 'window.sgy').read_bytes()
    trace = 240 + S * 2
    assert len(written) == 3600 + 31 * trace
    present = [(i, x) for i in range(5) for x in range(7) if (i, x) not in GONE]
    assert [list(struct.unpack('>%dh' % S, written[3600 + k * trace + 240:3600 + (k + 1) * trace])) for k in range(31)] == \
        [[value(3, i, x, s) for s in range(S)] for i, x in present]
    assert windows(gateway) == ['headers/0', 'headers/1', 'headers/2',
                                'headers/0', 'pieces/0', 'pieces/1', 'pieces/2', 'pieces/3', 'headers/1', 'pieces/4', 'pieces/5', 'pieces/6', 'pieces/7',
                                'headers/2', 'pieces/8']


def test_a_full_grid_get_asks_as_s1_did(world, small):
    """C4 t4: no pre-pass when nothing is absent. Mutation: the pre-pass run for every `/3` window (RED: the list)."""
    make, tmp = world
    gateway = PublishedGateway(3)
    assert make(gateway).get('cube', output=tmp / 'out', window='sample=0:10').outcome == 'got'
    assert windows(gateway) == ['headers/0', 'pieces/0', 'pieces/1', 'pieces/2', 'pieces/3', 'headers/1', 'pieces/4', 'pieces/5', 'pieces/6', 'pieces/7',
                                'headers/2', 'pieces/8']


@pytest.mark.parametrize('crop', ['inline=1:2,crossline=0:1,by=ordinal', 'inline=3:4,crossline=2:3,by=ordinal'], ids=['empty-crossline', 'empty-inline'])
def test_a_crop_with_an_empty_line_refuses_before_the_file_is_opened(world, small, monkeypatch, crop):
    """R1-8, D-W2 case 3: each headers answer asked once, no piece, `window.sgy` never opened. Mutations: the pre-pass
    skipped (RED: opened); occupancy taken from `absent.count` alone (RED: written, the crop is not all absent)."""
    make, tmp = world
    opened = []
    monkeypatch.setattr(vw, 'open', lambda *a, **k: opened.append(a[0]) or open(*a, **k), raising=False)
    gateway = SparseGateway()
    with pytest.raises(CannotReadHere) as refused: make(gateway).get('cube', output=tmp / 'out', window=crop + ',sample=0:10')
    assert (refused.value.technical['reason'], str(refused.value)) == ('crop-not-segy', vw.CROP_NOT_SEGY)
    assert windows(gateway) == ['headers/0'] and opened == [] and not (tmp / 'out').exists()


def test_headers_changed_between_the_passes_refuses_and_leaves_no_file(world, small):
    """R1-13: the second asking of headers answer 0 moves its first absent bit from position 7 to 6 (same length and
    popcount, digest restated). Mutation: the second-pass digest check removed (RED: completed, or a later check)."""
    make, tmp = world
    gateway = SparseGateway()
    seen = []
    def second(status, body, headers):
        seen.append(1)
        if len(seen) == 1: return status, body, headers
        body = bytes([body[0] ^ 0x03]) + body[1:]
        return status, body, {**headers, 'x-content-sha256': hashlib.sha256(body).hexdigest()}
    gateway.tamper[pieces('headers/0')] = second
    with pytest.raises(OphioliteError) as refused: make(gateway).get('cube', output=tmp / 'out', window='sample=0:10')
    assert (refused.value.technical['reason'], str(refused.value)) == ('headers-changed', vw.HEADERS_CHANGED)
    assert len(seen) == 2 and not (tmp / 'out').exists() and not list(tmp.glob('.out.partial-*'))
