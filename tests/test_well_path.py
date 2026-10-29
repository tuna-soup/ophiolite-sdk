"""E125 s3a: a well path given as positions read offline as WellPath, verified exactly, and refused by a bundle before
anything is written. The expected values are the literals of the strategy's §6 (the contract fixture
`contracts/assets/v1/fixtures/well-path.original`): TVDSS rises and falls, so its range is not [first, last]."""
import copy
import hashlib
import json
import tempfile
from importlib.resources import files

import pytest

from ophiolite import _core, bundle
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.typed import CLASSES, TYPES, Trajectory, WellPath
from test_bundle import Read

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
STATIONS = [{'md': 0.0, 'x': 1000.0, 'y': 2000.0, 'tvdss': 50.0}, {'md': 150.0, 'x': 1000.0, 'y': 2000.0, 'tvdss': -12.5},
            {'md': 400.5, 'x': 1003.25, 'y': 2010.5, 'tvdss': 300.25}, {'md': 800.0, 'x': 1010.0, 'y': 2030.0, 'tvdss': 610.75},
            {'md': 1100.25, 'x': 1020.5, 'y': 2055.25, 'tvdss': 480.5}]
DECLARED = {'crs': 'EPSG:23031', 'xy_unit': 'm', 'depth_unit': 'm', 'md_reference': 'KB', 'tvdss_datum': 'MSL'}
SENTENCE = 'A well path given as positions is not exported in a bundle yet; export it on its own as the original file.'


def load():
    return (json.loads(FIXTURES.joinpath('well-path.json').read_bytes()), FIXTURES.joinpath('well-path-data.json').read_bytes(),
            FIXTURES.joinpath('well-path.original').read_bytes())


def test_read_offline_and_registered():
    descriptor, body, original = load()
    path = _core.typed_result(descriptor, body, original)
    assert isinstance(path, WellPath) and 'well-path' in TYPES and CLASSES['well-path'] is WellPath and CLASSES['trajectory'] is Trajectory
    assert path.stations == STATIONS and len(path) == 5 and path.original == original and path._wire_data_bytes == body
    assert {k: path.context[k] for k in DECLARED} == DECLARED
    assert (path.context['count'], path.context['md_range'], path.context['tvdss_range']) == (5, [0.0, 1100.25], [-12.5, 610.75])
    assert repr(path) == '<WellPath 5 stations, EPSG:23031, MD from KB, TVDSS below MSL>'


def test_to_frame_literal():
    pytest.importorskip('pandas')
    frame = _core.typed_result(*load()).to_frame()
    assert list(frame.columns) == ['md', 'x', 'y', 'tvdss'] and frame.shape == (5, 4)
    assert frame.values.tolist() == [[s['md'], s['x'], s['y'], s['tvdss']] for s in STATIONS]
    assert frame.iloc[1].tolist() == [150.0, 1000.0, 2000.0, -12.5]


def rehash(descriptor, body):
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(body), hashlib.sha256(body).hexdigest()


def test_a_changed_descriptor_data_or_original_is_refused():
    descriptor, body, original = load()
    with pytest.raises(VerificationFailed, match='integrity mismatch'): _core.typed_result(descriptor, body[:-1] + b' ', original)
    with pytest.raises(VerificationFailed): _core.typed_result(descriptor, body, original + b'x')
    changed = copy.deepcopy(descriptor); changed['scientific']['md_reference'] = 'DF'
    with pytest.raises(VerificationFailed, match='disagrees'): _core.typed_result(changed, body, original)


def swap(p):
    p['stations'][1], p['stations'][2] = p['stations'][2], p['stations'][1]


@pytest.mark.parametrize('edit,context', [
    (lambda p: p['stations'].pop(), {'md_range': [0.0, 800.0], 'tvdss_range': [-12.5, 610.75]}),  # count 5 kept, four stations
    (lambda p: None, {'tvdss_range': [50.0, 480.5]}),                                            # [first, last] instead of [min, max]
    (swap, {}),                                                                                   # md no longer increasing
    (lambda p: None, {'md_range': [0.0, 1100.0]}),                                               # R3-6: a wrong md range
])
def test_semantic_corruption_with_recomputed_digests_is_refused_offline(edit, context):
    descriptor, body, original = load()
    payload = json.loads(body); edit(payload); payload['context'].update(context)
    raw = json.dumps(payload).encode(); d = copy.deepcopy(descriptor); d['scientific'] = payload['context']; rehash(d, raw)
    with pytest.raises(VerificationFailed, match='Stations and their context disagree|Measured depth must strictly increase'):
        _core.typed_result(d, raw, original)


def test_feet_are_read_as_feet():  # R3-5: the same numbers, declared in ft, are not converted
    descriptor, body, original = load()
    payload = json.loads(body); payload['context'].update(xy_unit='ft', depth_unit='ft')
    raw = json.dumps(payload).encode(); d = copy.deepcopy(descriptor); d['scientific'] = payload['context']; rehash(d, raw)
    path = _core.typed_result(d, raw, original)
    assert path.stations == STATIONS and (path.context['xy_unit'], path.context['depth_unit'], path.context['tvdss_range']) == ('ft', 'ft', [-12.5, 610.75])


@pytest.mark.parametrize('with_logs', [False, True])
def test_a_bundle_refuses_a_well_path_before_anything_is_written(tmp_path, monkeypatch, with_logs):
    path = _core.typed_result(*load())
    calls = []
    monkeypatch.setattr(tempfile, 'mkdtemp', lambda *a, **k: calls.append(a) or pytest.fail('staging created'))
    log = Read(); d = log._wire_descriptors[0]
    items = [({'asset_id': 'path', 'revision': 'f' * 64}, path)]
    if with_logs: items = [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read()), *items, ({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read())]
    destination = tmp_path / 'absent' / 'bundle'
    with pytest.raises(Refused) as refused: bundle.write_bundle(destination, items)
    assert str(refused.value) == SENTENCE and calls == [] and not destination.parent.exists()
