"""E119a slice 2 (C3 test 4): `client.well_sets.bind` checks one member again before anything is computed and places its
trajectory with the one geometry, or refuses with one sentence naming the member and the defect.

The member checks are the server's own (D2, run): `bind` sends the member to `las-uploads/check-member` (E111 s4a: the
set's inspection of a one-member document; nothing is stored),
and a refusal comes back as "well-set:<key>" for that member; here the server's answers are replayed, one defect each
(withdrawn, read revoked, reuse revoked, unreadable wellbore, association ended). That the server gives exactly these
answers for these states is proved by the Gateway's `test_well_sets.py`, which runs the same `check`. The geometry
defects (coordinate system, datum, time) are `place`'s, computed here (mutation: skip the datum check in the
module, and the datum case is placed instead of refused)."""
import copy
import json

import httpx
import pytest

from ophiolite import Client, Credential
from ophiolite.errors import Refused
from ophiolite.typed import Trajectory

URL = 'https://gateway.example'
W = 'well-' + '1' * 32
B1, B2 = ('wellbore-' + c * 32 for c in 'ab')
T1 = {'asset_id': 'traj-one', 'revision': '9' * 64}
T2 = {'asset_id': 'traj-two', 'revision': '8' * 64}
FRAME = {'crs': 'EPSG:28992', 'wellhead': {'x': 236512.4, 'y': 583104.75}, 'depth_reference': {'name': 'KB', 'elevation': 7.92, 'datum': 'NAP'},
         'north': {'survey_basis': 'grid:EPSG:28992', 'rotation_deg': 0}, 'tie_in': None, 'source': 'NLOG wellbore header'}
SET = {'schema': 'ophiolite.well-set/1', 'label': 'Zuidwolde wells', 'members': [
    {'well': W, 'wellbore': B1, 'trajectory': None, 'frame': None},
    {'well': W, 'wellbore': B2, 'trajectory': T2, 'frame': FRAME}]}
SURVEY = {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'}
STATIONS = [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}, {'md': 400.0, 'inclination': 30.0, 'azimuth': 60.0, 'tvd': None}]
SURFACE = {'type': 'regular-grid-surface', 'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up',
           'vertical_datum': 'NAP'}


class Surface:
    def __init__(self, context): self.context = context


def client(refuse=None, survey=SURVEY):
    seen = {'inspected': [], 'read': []}

    def handle(request):
        assert request.method == 'POST' and request.url.path.endswith('/las-uploads/check-member'), request.url.path  # E111 s4a (D-A2)
        seen['inspected'].append(json.loads(request.content))
        if refuse: return httpx.Response(400, json={'code': 'INVALID_ARGUMENT', 'message': refuse[1], 'request_id': 'r-1', 'reason': refuse[0], 'field': 'members[0]'})
        return httpx.Response(200, json={'profile': 'well-set/1'})
    c = Client(URL, 'p', Credential.bearer('t'), httpx.Client(transport=httpx.MockTransport(handle)))

    def read_data(asset, revision):
        seen['read'].append((asset, revision))
        return Trajectory({}, {'context': dict(survey), 'stations': copy.deepcopy(STATIONS)}, None)
    c.read_data = read_data
    return c, seen


def refused(call):
    with pytest.raises(Refused) as caught: call()
    return str(caught.value).split('\n')[0], caught.value.details


def test_a_member_is_checked_by_the_server_then_read_and_placed():
    c, seen = client()
    bound = c.well_sets.bind(SET, B2, Surface(SURFACE))
    (sent,) = seen['inspected']
    assert sent == {'project_id': 'p', 'label': 'Zuidwolde wells', 'member': SET['members'][1]}  # that member only
    assert seen['read'] == [(T2['asset_id'], T2['revision'])]
    assert bound.index == 1 and bound.surface_sign == -1 and len(bound.stations) == 2
    assert bound.stations[0] == pytest.approx((0.0, 236512.4, 583104.75, -7.92))
    at = bound.positions([0, 200, 400, 401])
    assert at[0] == pytest.approx(bound.stations[0][1:]) and at[2] == pytest.approx(bound.stations[1][1:]) and at[3] is None
    assert bound.stations[0][1] < at[1][0] < bound.stations[1][1] and bound.stations[0][3] < at[1][2] < bound.stations[1][3]  # between, on the arc
    assert c.well_sets.bind(SET, 1, SURFACE).stations == bound.stations  # by position, and a surface context alone


SERVER = [  # (state, the server's reason and its sentence for member 1 of the one-member inspection)
    ('withdrawn', 'well-set:withdrawn', 'Member 1: The trajectory revision was withdrawn.'),
    ('read revoked', 'well-set:not-of-wellbore', 'Member 1: The trajectory revision does not belong to the wellbore this member names.'),
    ('reuse revoked', 'well-set:trajectory-unusable', 'Member 1: You can read the trajectory but not use it in your own results.'),
    ('unreadable wellbore', 'well-set:wellbore-unreadable', 'Member 1: You cannot read the wellbore this member names, or it was removed.'),
    ('association ended', 'well-set:not-of-wellbore', 'Member 1: The trajectory revision does not belong to the wellbore this member names.'),
]


@pytest.mark.parametrize('state, reason, sentence', SERVER, ids=[s for s, *_ in SERVER])
def test_a_member_the_server_refuses_is_named_by_its_own_position_and_nothing_is_read(state, reason, sentence):
    c, seen = client(refuse=(reason, sentence))
    text, details = refused(lambda: c.well_sets.bind(SET, B2, SURFACE))
    assert text == 'Member 2: ' + sentence.split(': ', 1)[1]
    assert details == {'reason': reason, 'field': 'members[1]'}
    assert seen['read'] == []


GEOMETRY = [  # (defect, the change, the geometry key)
    ('crs mismatch', lambda survey, surface: surface.update(crs='EPSG:23031'), 'crs_mismatch'),
    ('time', lambda survey, surface: surface.update(z_meaning='time', z_unit='ms', positive='down'), 'surface_time'),
]


@pytest.mark.parametrize('defect, change, key', GEOMETRY, ids=[d for d, *_ in GEOMETRY])
def test_a_member_the_geometry_cannot_place_is_refused_in_one_sentence(defect, change, key):
    survey, surface = dict(SURVEY), dict(SURFACE)
    change(survey, surface)
    c, seen = client(survey=survey)
    text, details = refused(lambda: c.well_sets.bind(SET, B2, Surface(surface)))
    from ophiolite import geometry
    assert text == 'Member 2: ' + geometry.refusals()[key]
    assert details == {'reason': 'geometry:' + key, 'field': 'members[1]'}
    assert '_' not in text and 'EPSG' not in text and len(seen['inspected']) == 1


def test_a_survey_datum_unlike_the_frame_is_refused_too():  # its sentence and details: test_declaration_words.py
    c, _ = client(survey=dict(SURVEY, depth_datum='Rotary Table'))
    assert refused(lambda: c.well_sets.bind(SET, B2, SURFACE))[1]['reason'] == 'geometry:datum_mismatch'


def test_a_member_without_a_trajectory_or_outside_the_set_is_refused_before_any_request():
    c, seen = client()
    text, details = refused(lambda: c.well_sets.bind(SET, 0, SURFACE))
    assert text == 'Member 1: It has no trajectory, so there is nothing to place.' and details == {'reason': 'no-trajectory', 'field': 'members[0]'}
    assert refused(lambda: c.well_sets.bind(SET, 'wellbore-' + 'c' * 32, SURFACE))[0] == 'That wellbore is not a member of this set.'
    assert refused(lambda: c.well_sets.bind(SET, 2, SURFACE))[0].startswith('The set has 2 members')
    assert seen['inspected'] == [] and seen['read'] == []
