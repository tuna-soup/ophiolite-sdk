"""E23a S1: a recipe-read point set (point-set/2) verifies offline through the full typed read, by its
normalized profile rather than the bare type it shares with point-set/1; its decisions and recipe are
typed objects; the portable export refuses it until bundles can hold the package. The fixture is the
Platform contract fixture point-set-2.* (a synthetic Petrel package)."""
import copy
import hashlib
import json
from importlib.resources import files

import pytest
from ophiolite import _core, bundle, validate
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.models import invariants as rules
from ophiolite.typed import Decision, PointSet, Recipe

FIX = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load():
    return json.loads(FIX.joinpath('point-set-2.json').read_bytes()), FIX.joinpath('point-set-2-data.json').read_bytes(), FIX.joinpath('point-set-2.original').read_bytes()


def rehash(descriptor, payload):
    """Recompute the digests a tamperer would recompute; semantic rules must still refuse."""
    raw = json.dumps(payload).encode()
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized')
    rep['bytes'], rep['sha256'] = len(raw), hashlib.sha256(raw).hexdigest()
    descriptor['scientific'] = payload['context']
    return raw


def test_a_recipe_read_point_set_reads_with_kinded_columns_and_its_decisions():
    points = _core.typed_result(*load())
    assert isinstance(points, PointSet) and points.version == 2 and points.status == 'decided' and points.unresolved == []
    frame = points.to_frame()
    assert list(frame.columns) == ['x', 'y', 'z', 'TWT_auto', 'KIDTAG_Name', 'KIDTAG_Data_type', 'FLOAT_PointsNr']
    assert str(frame['TWT_auto'].dtype) == 'Float64' and str(frame['KIDTAG_Name'].dtype) == 'string' and str(frame['KIDTAG_Data_type'].dtype) == 'category'
    assert list(frame['KIDTAG_Name']) == ['SLDND_B_SCANALP2022_T', 'Pick with spaces', 'Quoted "name"', '']  # text kept exactly, empty is not missing
    assert frame.attrs['source_names']['KIDTAG_Data_type'] == 'KIDTAG,Data type' and frame['TWT_auto'][1] == 0.0
    z = next(d for d in points.decisions if d.field == 'z_meaning')
    assert isinstance(z, Decision) and z.selected == 'time' and z.evidence[0].member == 'point-set-2.readme.txt' and z.evidence[0].locator == 'line 2'
    assert isinstance(points.recipe, Recipe) and points.recipe.default and len(points.recipe.sha256) == 64


def test_point_set_1_reads_and_frames_as_before():
    descriptor = json.loads(FIX.joinpath('points.json').read_bytes())
    points = _core.typed_result(descriptor, FIX.joinpath('points-data.json').read_bytes(), FIX.joinpath('points.original').read_bytes())
    assert points.version == 1 and points.decisions == [] and points.status == 'decided' and points.recipe is None
    frame = points.to_frame()
    assert list(frame.columns) == ['x', 'y', 'z', 'porosity'] and str(frame['porosity'].dtype) == 'Float64'


def test_needs_decision_is_on_the_object():
    descriptor, body, original = load(); payload = json.loads(body)
    z = next(d for d in payload['context']['fidelity']['decisions'] if d['field'] == 'z_meaning')
    z.update(selected=None, selected_by=None, status='needs-decision')
    payload['context']['z_meaning'] = 'unknown'; payload['context']['fidelity']['unknown_context'] = ['z_meaning']
    payload['context']['fidelity']['execution'].update(status='needs-decision', unresolved=['z_meaning'])
    descriptor['package'].update(status='needs-decision', unresolved=['z_meaning'])
    points = _core.typed_result(descriptor, rehash(descriptor, payload), original)
    assert points.status == 'needs-decision' and points.unresolved == ['z_meaning'] and 'needs decision: z_meaning' in repr(points)
    assert repr(next(d for d in points.decisions if d.field == 'z_meaning')) == '<Decision z_meaning: needs decision>'


@pytest.mark.parametrize('edit,match', [
    (lambda p, d: p['context'].update(crs='EPSG:28992'), 'Scientific data does not satisfy|not the decided values'),
    (lambda p, d: p['attributes'][0]['values'].__setitem__(0, 'text'), 'another kind'),
    (lambda p, d: [a.update(name='z') for a in (p['context']['attributes'][0], p['attributes'][0])], 'collide with a coordinate'),
    (lambda p, d: d['package'].update(status='needs-decision'), 'package record and the decisions disagree'),
    (lambda p, d: next(m for m in d['package']['members'] if m['role'] == 'primary').update(bytes=1), 'primary is not the exact artifact'),
])
def test_tampering_with_recomputed_digests_is_refused_offline(edit, match):
    descriptor, body, original = load(); payload = json.loads(body)
    edit(payload, descriptor)
    with pytest.raises(VerificationFailed, match=match): _core.typed_result(descriptor, rehash(descriptor, payload), original)


def test_a_point_set_1_payload_under_a_point_set_2_descriptor_is_refused():
    """The dispatch-by-profile fix: point-set/1 data cannot pass for /2 (they share the type 'point-set')."""
    descriptor, _, original = load()
    other = FIX.joinpath('points-data.json').read_bytes()
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(other), hashlib.sha256(other).hexdigest()
    with pytest.raises(VerificationFailed, match='not the profile the descriptor names'): validate.typed_pair(descriptor, other)


def test_the_artifact_is_matched_by_kind_exactly():
    descriptor, _, _ = load()
    assert rules.artifact(descriptor)['id'] == 'artifact'
    reordered = copy.deepcopy(descriptor); reordered['representations'].reverse()
    assert rules.artifact(reordered)['id'] == 'artifact'
    extra = copy.deepcopy(descriptor); extra['representations'].insert(0, {**extra['representations'][1], 'id': 'package', 'kind': 'manifest'})
    assert rules.artifact(extra)['id'] == 'artifact'  # a third kind is never mistaken for the artifact


def test_portable_export_refuses_a_recipe_read_point_set(tmp_path):
    points = _core.typed_result(*load())
    chosen = {'asset_id': points._wire_descriptor['asset_id'], 'revision': points._wire_descriptor['revision'], 'curves': None}
    with pytest.raises(Refused, match='^Portable export is not yet supported for this type'): bundle.write_bundle(tmp_path / 'b', [(chosen, points)])
    assert not (tmp_path / 'b').exists()
