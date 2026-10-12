"""E23c C1: the released 2.7 reader is frozen before bundle.py changes, and every existing bundle keeps its minor.

The golden table states the version each kind of export is written with today; package bundles (C3) may raise the minor to 8
only for themselves. The mechanism table proves by running how each released reader refuses an asset that lists a file role it
does not know: by role for a point set, by type for a feature set below 2.7 (DD2)."""
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from ophiolite import _core, bundle
from ophiolite.errors import Refused, VerificationFailed
from test_bundle import FIXTURES, Read, rewrite, typed_items, typed_read
from test_bundle_entities import graph
from test_seismic import slices_bundle

FROZEN = Path(__file__).parent / 'frozen'
ROLE_SENTENCE = 'Bundle 1.0 carries exactly one original per asset and only known file roles.'
TYPE_SENTENCE = 'An asset has an unknown type.'
NO_ROWS = 'This revision was read from a source package; export it with Client.export, which reads the package and its decisions with it.'


def frozen(minor):
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_2%d' % minor, FROZEN / ('bundle_2_%d.py' % minor))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def item(read):
    return {'asset_id': read._wire_descriptor['asset_id'], 'revision': read._wire_descriptor['revision'], 'curves': None}, read


def reprofiled(name, profile, media_type=None):
    """A fixture read as another reader of the same kind would serve it: the profile changed in the descriptor and the data,
    digests recomputed (the writer chooses the minor from the profile alone)."""
    descriptor = json.loads(FIXTURES.joinpath(name + '.json').read_bytes()); data = json.loads(FIXTURES.joinpath(name + '-data.json').read_bytes())
    descriptor['profile'] = descriptor['source_reference']['profile'] = data['source']['profile'] = profile
    original = next(r for r in descriptor['representations'] if r['kind'] == 'original'); original['profile'] = profile
    if media_type: original['media_type'] = media_type
    raw = json.dumps(data).encode()
    next(r for r in descriptor['representations'] if r['kind'] == 'normalized').update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return _core.typed_result(descriptor, raw, FIXTURES.joinpath(name + '.original').read_bytes())


def curve_item():
    d = Read()._wire_descriptors[0]
    return {'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read()


KINDS = {  # kind of export -> (how it is written, the version it is written with today: a literal, never derived)
    'curve-only': (lambda p: bundle.write_bundle(p, [curve_item()]), '1.0.0'),
    'well-tops': (lambda p: bundle.write_bundle(p, [item(typed_read('tops'))]), '2.0.0'),
    'trajectory': (lambda p: bundle.write_bundle(p, [item(typed_read('trajectory'))]), '2.0.0'),
    'grid': (lambda p: bundle.write_bundle(p, [item(typed_read('grid'))]), '2.0.0'),
    'mesh': (lambda p: bundle.write_bundle(p, [item(typed_read('mesh'))]), '2.2.0'),
    'point-set': (lambda p: bundle.write_bundle(p, [item(typed_read('points'))]), '2.2.0'),
    'fault-sticks': (lambda p: bundle.write_bundle(p, [item(typed_read('faults'))]), '2.3.0'),
    'slices': (lambda p: slices_bundle(p.parent, p.name), '2.3.0'),
    'entity-graph': (lambda p: bundle.write_bundle(p, typed_items(), graph=graph(typed_items())), '2.4.0'),
    'wavelet': (lambda p: bundle.write_bundle(p, [item(typed_read('wavelet'))]), '2.5.0'),
    'model-section': (lambda p: bundle.write_bundle(p, [item(typed_read('model-section'))]), '2.5.0'),
    'seismic-section': (lambda p: bundle.write_bundle(p, [item(typed_read('seismic-section'))]), '2.5.0'),
    'time-depth': (lambda p: bundle.write_bundle(p, [item(typed_read('time-depth'))]), '2.6.0'),
    'geojson-feature-set': (lambda p: bundle.write_bundle(p, [item(typed_read('feature-set'))]), '2.7.0'),
    'geopackage-feature-set': (lambda p: bundle.write_bundle(p, [item(reprofiled('feature-set', 'ogc-geopackage/1', 'application/geopackage+sqlite3'))]), '2.7.0'),
    'zmap-grid': (lambda p: bundle.write_bundle(p, [item(reprofiled('grid', 'zmap-plus-grid/1'))]), '2.7.0'),
    'cps3-grid': (lambda p: bundle.write_bundle(p, [item(reprofiled('grid', 'cps3-ascii-grid/1'))]), '2.7.0'),
    'irap-grid': (lambda p: bundle.write_bundle(p, [item(reprofiled('grid', 'irap-ascii-grid/1'))]), '2.7.0'),
}


def test_the_frozen_two_seven_reader_is_the_released_file():
    released = subprocess.run(['git', '-C', str(Path(__file__).parents[1]), 'show', '67f05fc:ophiolite/bundle.py'], capture_output=True)
    if released.returncode == 0: assert released.stdout == (FROZEN / 'bundle_2_7.py').read_bytes()  # full clones prove the copy is exact
    assert hashlib.sha256((FROZEN / 'bundle_2_7.py').read_bytes()).hexdigest() == '2c462c6bc8a8a83a410be03cd7ab9b49c706a50da7cf7eb74bac6ca7345c45bc'


@pytest.mark.parametrize('kind', sorted(KINDS))
def test_every_existing_kind_keeps_its_minor_and_the_released_reader_reads_it(tmp_path, kind):
    write, version = KINDS[kind]
    opened = write(tmp_path / 'b')
    assert opened.manifest['bundle_version'] == version  # the guard that a package bundle may not raise the minor of anything else
    released = frozen(7).open_bundle(opened.path)  # no existing bundle became unreadable to the released 2.7 reader
    assert [a.type for a in released.assets] == [a.type for a in opened.assets]


def with_extra_file(root, role):
    """A well-formed bundle whose only asset lists one extra file with `role`, checksum and size correct."""
    raw = b'companion bytes\n'
    (root / 'assets/0/companion-1.bin').write_bytes(raw)
    rewrite(root, lambda m: m['assets'][0]['files'].append({'path': 'assets/0/companion-1.bin', 'role': role, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}))
    return root


# Per reader and asset type (DD2): the outcome is asserted in full, never "refused somehow".
OUTCOMES = {('point-set', 4): ROLE_SENTENCE, ('point-set', 5): ROLE_SENTENCE, ('point-set', 6): ROLE_SENTENCE, ('point-set', 7): ROLE_SENTENCE,
            ('feature-set', 4): TYPE_SENTENCE, ('feature-set', 5): TYPE_SENTENCE, ('feature-set', 6): TYPE_SENTENCE, ('feature-set', 7): ROLE_SENTENCE}


def test_released_readers_refuse_an_unknown_file_role_per_reader_and_type(tmp_path, role='companion'):
    seen = {}
    for kind, name in (('point-set', 'points'), ('feature-set', 'feature-set')):
        root = with_extra_file(bundle.write_bundle(tmp_path / kind, [item(typed_read(name))]).path, role)
        for minor in (4, 5, 6, 7):
            with pytest.raises(VerificationFailed) as refused: frozen(minor).open_bundle(root)
            seen[(kind, minor)] = str(refused.value)
    assert seen == OUTCOMES


def test_a_package_read_without_its_rows_is_refused_with_this_sentence(tmp_path):
    """E23c C3 replaced the two C1 refusals (recipe-read point set; Shapefile-read feature set) with this one: the rows travel with Client.export."""
    descriptor = json.loads(FIXTURES.joinpath('point-set-2.json').read_bytes())
    points = _core.typed_result(descriptor, FIXTURES.joinpath('point-set-2-data.json').read_bytes(), FIXTURES.joinpath('point-set-2.original').read_bytes())
    with pytest.raises(Refused) as refused: bundle.write_bundle(tmp_path / 'p', [item(points)])
    assert str(refused.value) == NO_ROWS
    features = typed_read('feature-set'); features._wire_descriptor = {**features._wire_descriptor, 'package': {'recipe': None, 'members': []}}
    with pytest.raises(Refused) as refused: bundle.write_bundle(tmp_path / 'f', [item(features)])
    assert str(refused.value) == NO_ROWS
    assert not (tmp_path / 'p').exists() and not (tmp_path / 'f').exists()
