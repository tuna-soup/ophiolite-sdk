"""E188 C1: a send carries a curve declaration (the next version of a held LAS upload) and a sent item keeps the survey
object it was placed as. Against the in-memory project (tests/helpers/exchange_fake.py) and ClientTransport over a
recording client; synthetic values only. Each test names the mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import ClientTransport, Exchange

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha
NOW = 1000.0 + 300

V1, V2, V3 = b'~V\nlas one\n', b'~V\nlas two\n', b'~V\nlas three\n'
DECLARED = {'well': 'Synthetic-1', 'depth_kind': 'MD', 'depth_datum': 'KB'}
SEND = dict(name='GR', profile='las2/1', how='From OpendTect, survey S', based_on=['gr'], of='gr', rights_confirmed=True)


class Recording(Fake):
    """The fake project, keeping the request of every publish call (a replay included)."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.requests = []

    def publish(self, data, request, resolved, command_id, attribution=None):
        self.requests.append(json.loads(json.dumps(request)))
        return super().publish(data, request, resolved, command_id, attribution=attribution)


@pytest.fixture
def project():
    fake = Recording(); fake.add('gr', V1, name='GR', kind='uploaded', profile='las2/1')
    return fake


def held(fake, tmp_path, applied_to='Synthetic-1/GR'):
    e = Exchange(fake, tmp_path / 'w', clock=lambda: NOW)
    got = e.fetch('gr')
    got.confirm(applied_to=applied_to)
    return e


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code
    return caught.value


def test_t1_1_the_declaration_is_saved_and_sent_exactly(project, tmp_path):
    """Mutation: not put in the request -> the project's request has none -> red."""
    e = held(project, tmp_path)
    done = e.send(V2, **SEND, curve_declaration=dict(DECLARED))
    assert done.outcome == 'sent-version'
    assert project.requests[0]['curve_declaration'] == DECLARED
    assert project.uploads[0]['request']['curve_declaration'] == DECLARED


class Client:
    """What ClientTransport.publish calls on the upload route, recorded."""
    url, project = 'https://project.example', 'p'

    def __init__(self): self.calls = []

    def upload_data(self, data, **kwargs):
        self.calls.append(kwargs)
        return type('Got', (), {'asset_id': 'gr', 'revision': 'r2'})()


REQUEST = {'name': 'GR', 'profile': 'las2/1', 'how': 'From OpendTect, survey S', 'based_on': ['gr'], 'of': 'gr', 'declare': {}, 'extra': {},
           'sha256': sha(V2), 'bytes': len(V2), 'rights_confirmed': True}
RESOLVED = {'parents': [], 'expected_parent': 'r1', 'route': 'upload'}
# Today's upload_data call for this request (frozen 23 Nov 2026, before E188): no curve_declaration key.
TODAY = {'profile': 'las2/1', 'name': 'GR', 'attribution': 'From OpendTect, survey S', 'audience': [], 'rights_confirmed': True, 'declared': None,
         'filename': 'GR', 'command_id': 'c' * 32, 'append_to': 'gr', 'expected_parent': 'r1', 'application_source': None}


def test_t1_1_publish_passes_the_saved_declaration_to_upload_data():
    """Mutation: publish does not pass it -> upload_data gets none -> red."""
    client = Client()
    ClientTransport(client).publish(V2, dict(REQUEST, curve_declaration=dict(DECLARED)), RESOLVED, 'c' * 32)
    assert client.calls == [dict(TODAY, curve_declaration=DECLARED)]


def test_t1_3_without_a_declaration_the_request_and_the_call_are_todays(project, tmp_path):
    client = Client()
    ClientTransport(client).publish(V2, dict(REQUEST), RESOLVED, 'c' * 32)
    assert client.calls == [TODAY]
    e = held(project, tmp_path)
    e.send(V2, **SEND)
    assert project.requests == [{'name': 'GR', 'profile': 'las2/1', 'how': 'From OpendTect, survey S', 'based_on': ['gr'], 'of': 'gr', 'declare': {},
                                 'extra': {}, 'sha256': sha(V2), 'bytes': len(V2), 'rights_confirmed': True}]


def test_t1_2_a_rerun_after_a_lost_answer_sends_the_saved_declaration(project, tmp_path):
    """Mutation: the declaration not saved in the pending request -> the rerun's request differs from the saved one,
    or carries none -> red."""
    e = held(project, tmp_path)
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: e.send(V2, **SEND, curve_declaration=dict(DECLARED)))
    assert e._load()['pending']['request']['curve_declaration'] == DECLARED
    assert e.send(V2, **SEND, curve_declaration=dict(DECLARED)).outcome == 'sent-version'
    assert [r['curve_declaration'] for r in project.requests] == [DECLARED, DECLARED]
    assert len(project.items['gr']['versions']) == 2 and e._load()['pending'] is None


def test_t1_2_an_unfinished_send_refuses_another_declaration(project, tmp_path):
    e = held(project, tmp_path)
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: e.send(V2, **SEND, curve_declaration=dict(DECLARED)))
    saved = json.dumps(e._load()['pending'], sort_keys=True)
    caught = refused('not-valid', lambda: e.send(V2, **SEND, curve_declaration=dict(DECLARED, depth_datum='GL')))
    assert 'an earlier send from this folder is unfinished' in caught.sentence
    assert json.dumps(e._load()['pending'], sort_keys=True) == saved


SHAPE = 'The project refused this: declare the curve as its well, depth kind and depth datum, each as text. Nothing was sent.'
ROUTE = ('The project refused this: a curve declaration goes only with the next version of an uploaded LAS 2.0 file. '
         'Nothing was sent.')


@pytest.mark.parametrize('declared, sentence', [
    ({'well': 'Synthetic-1', 'depth_kind': 'MD'}, SHAPE),
    (dict(DECLARED, depth_datum=' '), SHAPE),
    (dict(DECLARED, depth_kind=1), SHAPE),
    (dict(DECLARED, extra='x'), SHAPE),
    (['Synthetic-1', 'MD', 'KB'], SHAPE),
])
def test_t1_4_a_malformed_declaration_is_refused_before_anything_is_saved(project, tmp_path, declared, sentence):
    """Mutation: the shape check removed -> the malformed declaration is sent -> red."""
    e = held(project, tmp_path)
    caught = refused('not-valid', lambda: e.send(V2, **SEND, curve_declaration=declared))
    assert caught.sentence == sentence
    assert e._load()['pending'] is None and project.requests == []


def test_t1_4_a_declaration_off_the_upload_route_or_its_profile_is_refused(tmp_path):
    """Mutation: the route check removed -> a derived send or another profile carries it -> red."""
    fake = Recording()
    fake.add('poro', V1, name='Porosity'); fake.add('pts', V1, name='Top', kind='uploaded', profile='points-csv/1')
    fake.add('gr', V1, name='GR', kind='uploaded', profile='las2/1')
    e = Exchange(fake, tmp_path / 'w', clock=lambda: NOW)
    for item in ('poro', 'pts', 'gr'): e.fetch(item).confirm()
    calls = [
        lambda: e.send(V2, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro', curve_declaration=dict(DECLARED)),
        lambda: e.send(V2, name='New', profile='las2/1', how='edit', based_on=['gr'], curve_declaration=dict(DECLARED)),
        lambda: e.send(V2, name='Top', profile='points-csv/1', how='edit', based_on=['pts'], of='pts', rights_confirmed=True,
                       curve_declaration=dict(DECLARED)),
    ]
    for call in calls:
        caught = refused('not-valid', call)
        assert (caught.sentence, caught.technical) == (ROUTE, {'argument': 'curve_declaration'})
    assert e._load()['pending'] is None and fake.requests == []


def test_t1_6_a_sent_item_keeps_where_it_was_placed(project, tmp_path):
    """Mutation: the send's save without applied_to -> the second send's entry has none -> red."""
    e = held(project, tmp_path)
    e.send(V2, **SEND, curve_declaration=dict(DECLARED))
    entry = e.held()['gr']
    assert (entry['applied_to'], entry['number'], entry['sent']) == ('Synthetic-1/GR', 2, True)
    e.send(V3, **SEND, curve_declaration=dict(DECLARED))
    assert e.held()['gr']['applied_to'] == 'Synthetic-1/GR' and e.held()['gr']['number'] == 3


def test_t1_6_an_entry_without_a_placement_gains_none(project, tmp_path):
    e = Exchange(project, tmp_path / 'w', clock=lambda: NOW); e.fetch('gr').confirm()
    e.send(V2, **SEND)
    assert 'applied_to' not in e.held()['gr']


def test_t1_6b_a_later_get_places_the_item_where_that_get_says(project, tmp_path):
    """The send keeps the placement; a get's confirm still names its own (a re-get onto another well).
    Mutation: _kept keeping applied_to -> confirm's own is overwritten by the earlier one -> red."""
    e = held(project, tmp_path)
    e.send(V2, **SEND, curve_declaration=dict(DECLARED))
    project.add('gr', V3, name='GR', kind='uploaded', profile='las2/1')
    e.fetch('gr').confirm(applied_to='Synthetic-2/GR')
    assert e.held()['gr']['applied_to'] == 'Synthetic-2/GR'
