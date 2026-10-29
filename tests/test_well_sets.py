"""E119a slice 1 (C3 test 3): `client.well_sets` builds a set from wellbores, and where a wellbore has two trajectory
versions the choice is refused until a version is named by its label. The refusal lists every version by its readable
label or "Trajectory version of <date>", never by an identifier. `save` and `new_version` upload the document as
`well-set/1` with no audience."""
import base64
import hashlib
import json

import httpx
import pytest

from ophiolite import Client, Credential
from ophiolite.errors import Refused
from ophiolite import well_sets

URL = 'https://gateway.example'
W = 'well-' + '1' * 32
B1, B2, B3 = ('wellbore-' + c * 32 for c in 'abc')
GYRO = {'asset_id': 'traj-gyro-7f3a9c', 'revision': '9' * 64, 'name': 'Gyro survey'}
RAW = {'asset_id': 'traj-raw-0b1c2d', 'revision': '8' * 64, 'name': 'deviation_2f3a9c1b4d5e6f70'}
ONLY = {'asset_id': 'traj-only-4e5f6a', 'revision': '7' * 64, 'name': 'MWD survey'}
FRAME = {'crs': 'EPSG:28992', 'wellhead': {'x': 236512.4, 'y': 583104.75}, 'depth_reference': {'name': 'KB', 'elevation': 7.92, 'datum': 'NAP'},
         'north': {'survey_basis': 'grid:EPSG:28992', 'rotation_deg': 0}, 'tie_in': None, 'source': 'NLOG wellbore header'}
ENTITIES = {W: {'entity_id': W, 'kind': 'well', 'name': 'ZRP-01', 'parts': [{'entity_id': b, 'kind': 'wellbore'} for b in (B1, B2, B3)]},
            B1: {'entity_id': B1, 'kind': 'wellbore', 'name': 'ZRP-01 main', 'part_of': {'entity_id': W}},
            B2: {'entity_id': B2, 'kind': 'wellbore', 'name': 'zrp_01_s1', 'part_of': {'entity_id': W}},
            B3: {'entity_id': B3, 'kind': 'wellbore', 'name': 'ZRP-01-S2', 'part_of': {'entity_id': W}}}
TRAJECTORIES = {B1: [GYRO, RAW, GYRO], B2: [ONLY], B3: []}  # GYRO twice: two associations of one exact revision are one version
IDENTIFIERS = (W, B1, B2, B3, GYRO['asset_id'], GYRO['revision'], RAW['asset_id'], RAW['revision'], ONLY['asset_id'], 'deviation_2f3a9c1b4d5e6f70', 'zrp_01_s1')


def item(t, day):
    return {**t, 'profile': 'deviation-csv/1', 'association': {'assertion_id': 'x', 'predicate': 'of-entity', 'evidence': {}, 'asserted_by': 'alice',
                                                                'asserted_at': '2026-10-%02dT08:00:00Z' % day}}


def client(catalogue=(), refuse=None):
    sent = []

    def handle(request):
        path = request.url.path
        if request.method == 'GET':
            return httpx.Response(200, json={'items': list(catalogue), 'next_cursor': None})
        if path.endswith('/las-uploads/upload') and refuse: return httpx.Response(400, json=refuse)
        if path.endswith('/las-uploads/upload'):
            meta = json.loads(base64.b64decode(request.headers['X-Ophiolite-Upload']))
            sent.append((meta, json.loads(request.content)))
            digest = hashlib.sha256(request.content).hexdigest()
            return httpx.Response(200, json={'asset_id': meta.get('append_to') or 'set-1', 'revision': digest, 'sha256': digest, 'name': meta['name'], 'can_share': False,
                                             'acquisition': {}, 'permitted_audience': [], 'recipients': [], 'reuse_recipients': []})
        body = json.loads(request.content)
        if path.endswith('/entities/get'):
            doc = ENTITIES[body['entity_id']]
            return httpx.Response(200, json={'identity': {'provisional': True}, 'generation': 1, 'parts': [], **doc})
        if path.endswith('/entities/assets'):
            assert body['profile'] == 'deviation-csv/1'
            rows = [item(t, 20 + n) for n, t in enumerate(TRAJECTORIES[body['entity_id']])]
            return httpx.Response(200, json={'schema': 'ophiolite.entity-assets/1', 'entity': {'entity_id': body['entity_id']}, 'items': rows, 'next_cursor': None})
        raise AssertionError(path)
    return Client(URL, 'p', Credential.bearer('t'), httpx.Client(transport=httpx.MockTransport(handle))), sent


def refusal(call):
    with pytest.raises(Refused) as caught: call()
    return str(caught.value)


def test_two_versions_and_no_choice_are_refused_by_label_never_by_identifier():
    c, sent = client()
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1, B2, B3], frames={B1: FRAME, B2: FRAME}))
    assert 'ZRP-01 main has 2 trajectory versions: "Gyro survey", "Trajectory version of 2026-10-21".' in text
    assert 'Name one version by its label in choose.' in text
    assert not [i for i in IDENTIFIERS if i in text]
    assert sent == []


def test_a_named_version_is_chosen_and_the_set_is_built_member_by_member():
    c, _ = client()
    doc = c.well_sets.from_list('Zuidwolde wells', [B1, B2, B3], frames={B1: FRAME, B2: FRAME}, choose={B1: 'Gyro survey'})
    assert doc == {'schema': 'ophiolite.well-set/1', 'label': 'Zuidwolde wells', 'members': [
        {'well': W, 'wellbore': B1, 'trajectory': {'asset_id': GYRO['asset_id'], 'revision': GYRO['revision']}, 'frame': FRAME},
        {'well': W, 'wellbore': B2, 'trajectory': {'asset_id': ONLY['asset_id'], 'revision': ONLY['revision']}, 'frame': FRAME},
        {'well': W, 'wellbore': B3, 'trajectory': None, 'frame': None}]}


def test_the_fallback_label_names_a_version_too():
    c, _ = client()
    doc = c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: 'Trajectory version of 2026-10-21'})
    assert doc['members'][0]['trajectory'] == {'asset_id': RAW['asset_id'], 'revision': RAW['revision']}


def test_a_label_that_names_no_version_is_refused_with_the_versions_listed():
    c, _ = client()
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: 'Gyro 2020'}))
    assert text.startswith('ZRP-01 main has no trajectory version named "Gyro 2020"; its versions are "Gyro survey", "Trajectory version of 2026-10-21".')
    assert not [i for i in IDENTIFIERS if i in text]


def test_an_unreadable_wellbore_name_is_shown_as_unnamed_wellbore():
    c, _ = client()
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B2]))
    assert text == 'Unnamed wellbore has a trajectory but no frame; the frame says where it starts and how it is oriented.'


def test_save_and_new_version_upload_the_document_privately():
    c, sent = client()
    members = [well_sets.member(W, B1, GYRO, FRAME), well_sets.member(W, B3)]
    first = c.well_sets.save('Zuidwolde wells', members, attribution='Anna', rights_confirmed=True)
    second = c.well_sets.new_version(first, 'Zuidwolde wells', members[:1], attribution='Anna', rights_confirmed=True)
    (m1, d1), (m2, d2) = sent
    assert (m1['profile'], m1['audience'], m1['name'], m1['filename']) == ('well-set/1', [], 'Zuidwolde wells', 'well-set.json')
    assert 'append_to' not in m1 and (m2['append_to'], m2['expected_parent'], m2['audience']) == ('set-1', first.revision, [])
    assert d1 == {'schema': 'ophiolite.well-set/1', 'label': 'Zuidwolde wells', 'members': members} and d2['members'] == members[:1]
    assert second.asset_id == 'set-1'


def test_a_server_refusal_of_one_member_reads_as_the_servers_sentence():
    sentence = 'Member 2: The trajectory is not a revision of that wellbore.'
    c, _ = client(refuse={'code': 'INVALID_ARGUMENT', 'message': sentence, 'request_id': 'r-1', 'reason': 'well-set:not-of-wellbore', 'field': 'members[1]'})
    with pytest.raises(Refused) as caught:
        c.well_sets.save('Zuidwolde wells', [well_sets.member(W, B1, GYRO, FRAME), well_sets.member(W, B2, GYRO, FRAME)], attribution='Anna', rights_confirmed=True)
    assert str(caught.value).split('\n')[0] == sentence
    assert caught.value.details == {'field': 'members[1]', 'reason': 'well-set:not-of-wellbore'}


FINAL_A = {'asset_id': 'traj-final-a1b2c3', 'revision': '6' * 64, 'name': 'Final survey'}
FINAL_B = {'asset_id': 'traj-final-d4e5f6', 'revision': '5' * 64, 'name': 'Final survey'}
EXACT_B = {'asset_id': FINAL_B['asset_id'], 'revision': FINAL_B['revision']}


def same_label(monkeypatch):
    """D-10: B1's two versions are both labelled "Final survey"."""
    monkeypatch.setitem(TRAJECTORIES, B1, [FINAL_A, FINAL_B])
    return client()[0]


def test_two_versions_under_one_label_are_refused_by_the_label_with_the_way_through(monkeypatch):
    c = same_label(monkeypatch)
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: 'Final survey'}))
    assert text == ('ZRP-01 main has more than one trajectory version named "Final survey" ("Final survey", "Final survey"). '
                    'Name one by passing the version itself in choose.')
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}))
    assert text == 'ZRP-01 main has 2 trajectory versions: "Final survey", "Final survey". Name one by passing the version itself in choose.'
    assert not [i for i in (*IDENTIFIERS, FINAL_A['asset_id'], FINAL_B['asset_id'], FINAL_A['revision']) if i in text]


def test_the_version_itself_names_one_of_two_under_one_label(monkeypatch):
    """Mutation: compare the mapping by label only -> both match "Final survey" -> red."""
    c = same_label(monkeypatch)
    for exact, want in ((EXACT_B, FINAL_B), ({'revision': FINAL_A['revision'], 'asset_id': FINAL_A['asset_id']}, FINAL_A)):
        doc = c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: exact})
        assert doc['members'][0]['trajectory'] == {'asset_id': want['asset_id'], 'revision': want['revision']}


def test_a_version_not_of_the_wellbore_is_refused_without_its_identifier(monkeypatch):
    c = same_label(monkeypatch)
    for other in ({'asset_id': ONLY['asset_id'], 'revision': ONLY['revision']}, {'asset_id': FINAL_B['asset_id'], 'revision': FINAL_A['revision']}):
        text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: other}))
        assert text == 'ZRP-01 main has no trajectory version you can read matching the one named.'  # no label names one of its two
    assert not [i for i in (*IDENTIFIERS, FINAL_B['asset_id']) if i in text]
    c, _ = client()  # where a label still names a version, the refusal says so
    text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B2], frames={B2: FRAME}, choose={B2: EXACT_B}))
    assert text == 'Unnamed wellbore has no trajectory version you can read matching the one named. Name one version by its label in choose.'


def test_a_version_named_with_other_keys_is_refused(monkeypatch):
    c = same_label(monkeypatch)
    for shape in ({**EXACT_B, 'name': 'Final survey'}, {'asset_id': FINAL_B['asset_id']}):
        text = refusal(lambda: c.well_sets.from_list('Zuidwolde wells', [B1], frames={B1: FRAME}, choose={B1: shape}))
        assert text == 'ZRP-01 main: choose names a trajectory version by its label, or by a mapping of exactly asset_id and revision.'


def test_list_returns_only_well_sets():
    c, _ = client([{'asset_id': 's', 'profile': 'well-set/1'}, {'asset_id': 't', 'profile': 'deviation-csv/1'}])
    assert [i['asset_id'] for i in c.well_sets.list()] == ['s']
