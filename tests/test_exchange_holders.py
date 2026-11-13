"""E171 s1 C5: the exchange core tells the project which copy this folder holds: the application word and the declared
mode on a confirmed get, the folder's holder on a send, a released copy and a deliberate get of an earlier version.
Against the in-memory project of tests/helpers/exchange_fake.py with a recording `report` and `release`; the SDK's
transport against a recording client. Each test names the mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.agent_exchange import AgentTransport
from ophiolite.errors import Refused, Unavailable
from ophiolite.exchange import ClientTransport, Exchange

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha
V1, V2 = b'porosity v1', b'porosity v2'
HOLDER = '0123456789abcdef0123456789abcdef'


class Holding(Fake):
    """The fake project with E70b's `report` and E171's `release`, every call recorded; `refuse` holds errors to raise
    in turn (an older gateway refuses the new fields as a request: 400)."""
    def __init__(self):
        super().__init__()
        self.reports, self.releases, self.refuse, self.held_rows = [], [], [], set()

    def report(self, reference, holder_id, event_id, **held):
        self.reports.append({'reference': reference, 'binding_id': holder_id, 'event_id': event_id, **held})
        if self.refuse: raise self.refuse.pop(0)
        self.held_rows.add((holder_id, reference['asset_id']))

    def release(self, holder_id, item):
        self.releases.append((holder_id, item))
        if (holder_id, item) not in self.held_rows: return False
        self.held_rows.discard((holder_id, item)); return True


@pytest.fixture
def project():
    fake = Holding(); fake.add('poro', V1, name='Porosity')
    return fake


def work(tmp_path, fake, mode=None, **options):
    """A folder holding version 1 of Porosity (confirmed once), with `mode` written into held/2 by the test (ruling of
    11 Nov, 01:30: no public call declares it in s1)."""
    ex = Exchange(fake, tmp_path / 'work', clock=lambda: 1300.0, **options)
    ex.get('poro')
    if mode is not None:
        record = json.loads(ex.path.read_text()); record['items']['poro']['mode'] = mode
        exchange._atomic(ex.path, dict(record, schema=exchange.SCHEMA_WORDS))
    return ex


# -- the confirmed get ----------------------------------------------------------------------------------------------

def test_without_a_mode_the_event_id_is_e70b_s_byte_for_byte():
    """Mutation: the nonce or the mode hashed always -> the id of an entry without a mode changes (E70b's literal,
    computed from e7eafa85e's delivery_event)."""
    literal = 'got-35c913d6010177a260189a9a5da5c0e6fb8c6c7b1835f925'
    assert exchange.delivery_event(HOLDER, 'poro', 'abc') == literal
    assert exchange.delivery_event(HOLDER, 'poro', 'abc', None, 'a-nonce') == literal


def test_a_get_reports_the_application_word_and_no_mode_when_none_is_declared(tmp_path, project):
    """Mutation: `application` left out of `_report_held` -> the report carries no application; `holds` sent as null ->
    the E70b body gains a key."""
    ex = work(tmp_path, project)
    (sent,) = project.reports
    assert sent == {'reference': {'project_id': 'p', 'asset_id': 'poro', 'revision': sha(V1)}, 'binding_id': json.loads(ex.path.read_text())['holder_id'],
                    'event_id': exchange.delivery_event(sent['binding_id'], 'poro', sha(V1)), 'application': 'script'}
    qgis = Holding(); qgis.add('poro', V1, name='Porosity')
    work(tmp_path / 'q', qgis, application='qgis-plugin')
    assert qgis.reports[0]['application'] == 'application:qgis-plugin'
    for wrong in ('application:qgis-plugin', 'QGIS', ''):
        with pytest.raises(ValueError): Exchange(qgis, tmp_path / 'x', application=wrong)


@pytest.mark.parametrize('modes', [['stays'], ['follows'], ['follows', 'stays'], ['follows', 'stays', 'follows']],
                         ids=['stays', 'follows', 'follows-stays', 'follows-stays-follows'])
def test_a_declared_mode_rides_on_each_confirmation_with_an_id_of_its_own(tmp_path, project, modes):
    """M2-M5, the mode declared by the test. Mutation: `holds` not sent -> the mode is missing; the nonce dropped
    (E70b's id with a mode) -> the second confirmation of the same version replays the first."""
    ex = work(tmp_path, project)
    ids = []
    for mode in modes:
        record = json.loads(ex.path.read_text()); record['items']['poro']['mode'] = mode
        exchange._atomic(ex.path, dict(record, schema=exchange.SCHEMA_WORDS))
        ex.get('poro', **({'output': tmp_path / 'held'} if mode == 'stays' else {}))  # E173 s1 (F6): staying needs a folder
        assert project.reports[-1]['holds'] == mode and project.reports[-1]['application'] == 'script'
        ids.append(project.reports[-1]['event_id'])
    assert len(set(ids)) == len(ids) and project.reports[0]['event_id'] not in ids


def test_an_older_gateway_is_asked_once_more_in_e70b_s_shape_with_the_same_id(tmp_path, project):
    """Mutation: no resend on a refused request -> `reported` False and nothing recorded; the resend keeps the new
    fields -> the second body carries them; a new id drawn for the resend -> two ids for one confirmation."""
    ex = work(tmp_path, project, mode='stays')
    project.reports.clear(); project.refuse = [Refused('Request body is not valid', status=400)]
    got = ex.get('poro', output=tmp_path / 'held')  # E173 s1 (F6): staying needs a folder
    assert got.technical['reported'] is True
    first, again = project.reports
    assert first['holds'] == 'stays' and first['application'] == 'script'
    assert again == {k: first[k] for k in ('reference', 'binding_id', 'event_id')}
    project.reports.clear(); project.refuse = [Unavailable('down', status=503)]
    assert ex.get('poro', output=tmp_path / 'held').technical['reported'] is False and len(project.reports) == 1  # only a refused request is asked again


# -- the send ---------------------------------------------------------------------------------------------------------

class Recording:
    """An ophiolite.Client stand-in for ClientTransport.publish: each send's keywords, answered as the gateway would."""
    url, project = 'https://project.example', 'p'

    def __init__(self): self.calls = []

    def upload_data(self, data, **kw):
        self.calls.append(('upload', kw))
        return type('Upload', (), {'asset_id': kw['append_to'], 'revision': 'r2'})()

    def publish_derived(self, written, **kw):
        self.calls.append(('derive', kw))
        return type('Receipt', (), {'asset_id': kw.get('new_version_of') or 'new', 'revision': 'r2', 'revision_number': 2, 'source_change': None})()


@pytest.mark.parametrize('route', ['derive', 'upload'])
def test_a_send_names_this_folder_as_its_holder_on_every_route(route):
    """E70d is merged: both send routes. Mutation: `**held` dropped on either call -> that route names no holder."""
    client = Recording()
    resolved = {'parents': [], 'expected_parent': 'r1', 'route': 'upload'} if route == 'upload' else {'parents': [{'asset_id': 'poro', 'revision': 'r1'}], 'expected_parent': 'r1'}
    request = {'name': 'Porosity', 'profile': 'points-csv/1', 'how': 'edited', 'of': 'poro', 'declare': {}, 'rights_confirmed': True}
    ClientTransport(client).publish(b'x,y\n', request, resolved, 'c-1', attribution={'holder': HOLDER, 'application': 'application:qgis-plugin'})
    ((called, kw),) = client.calls
    assert called == route and (kw['holder'], kw['application']) == (HOLDER, 'application:qgis-plugin')
    if route == 'upload': assert kw['rights_confirmed'] is True  # E70d's rights stay as they were
    client.calls.clear()
    ClientTransport(client).publish(b'x,y\n', request, resolved, 'c-1')
    assert not {'holder', 'application'} & set(client.calls[0][1])  # an older pending send names none


def test_the_attribution_is_saved_with_the_send_outside_the_request(tmp_path, project):
    """Mutation: the attribution put in `request` -> the request compared on a retry differs from an older SDK's; read
    from the record at send time instead of the pending send -> an older pending send gains a holder."""
    ex = work(tmp_path, project)
    holder = json.loads(ex.path.read_text())['holder_id']
    project.drop_after_commit = True
    with pytest.raises(exchange.REFUSALS['outcome-unknown']): ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro')
    pending = json.loads(ex.path.read_text())['pending']
    assert pending['attribution'] == {'holder': holder, 'application': 'script'} and 'attribution' not in pending['request'] and 'holder' not in pending['resolved']
    assert ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro').outcome == 'sent-version'
    assert project.attributions == [pending['attribution']] * 2


def test_a_send_saved_before_the_upgrade_is_resent_byte_identically(tmp_path, project):
    """Codex D4: a pending send with no attribution keeps its digest and records no `sent`. Mutation: a missing
    attribution filled in at resend -> the transport is asked with a holder."""
    ex = work(tmp_path, project)
    project.drop_after_commit = True
    with pytest.raises(exchange.REFUSALS['outcome-unknown']): ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro')
    record = json.loads(ex.path.read_text()); del record['pending']['attribution']; exchange._atomic(ex.path, record)
    before = json.loads(ex.path.read_text())['pending']
    project.attributions.clear()
    assert ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro').outcome == 'sent-version'
    assert project.attributions == [None] and project.calls[-1][:2] == ('publish', before['command_id'])


def test_a_transport_written_before_s1_is_called_as_before(tmp_path):
    """A host's own transport with E70a's `publish` and E70b's `report` signatures. Mutation: `_takes` answers True
    always -> its publish is called with `attribution` (TypeError) and its report with the new fields (reported False)."""
    class Before(Fake):
        def __init__(self): super().__init__(); self.reports = []
        def publish(self, data, request, resolved, command_id): return Fake.publish(self, data, request, resolved, command_id)
        def report(self, reference, holder_id, event_id): self.reports.append(event_id)
    old = Before(); old.add('poro', V1, name='Porosity')
    ex = work(tmp_path, old, mode='stays')
    assert ex.get('poro', output=tmp_path / 'held').technical['reported'] is True and len(old.reports) == 2  # E173 s1 (F6): staying needs a folder
    assert ex.send(V2, name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro').outcome == 'sent-version'
    assert old.attributions == [None]


# -- release and the earlier get ------------------------------------------------------------------------------------

def test_release_copy_posts_once_and_leaves_the_record_byte_equal(tmp_path, project):
    """Mutation: release_copy drops the item from held.json -> the bytes differ (a later confirm brings the copy back
    only if the file is kept); posted twice -> two calls."""
    ex = work(tmp_path, project)
    before, holder = ex.path.read_bytes(), json.loads(ex.path.read_text())['holder_id']
    assert ex.release_copy('poro') is True and project.releases == [(holder, 'poro')]
    assert ex.path.read_bytes() == before
    assert ex.release_copy('poro') is False and ex.path.read_bytes() == before
    ex.get('poro')  # the same version confirmed again: the copy is held again
    assert (holder, 'poro') in project.held_rows
    assert Exchange(project, tmp_path / 'empty').release_copy('poro') is None and not (tmp_path / 'empty/held.json').exists()


def test_an_assistant_neither_reports_nor_releases(tmp_path, project):
    """Mutation: `release = None` removed from AgentTransport -> an assistant's folder posts exchange/release."""
    assert AgentTransport.report is None and AgentTransport.release is None
    agent = Holding(); agent.add('poro', V1, name='Porosity'); agent.release = None; agent.report = None
    ex = work(tmp_path, agent)
    assert ex.release_copy('poro') is None and ex.report_earlier('poro', sha(V1)) is None and agent.releases == []


def test_an_earlier_get_reports_each_go_back_and_never_writes_the_record(tmp_path, project):
    """D6, Codex D2: r1, r2, back to r1, back to r1 again, a retried go-back, then r2. Mutation: the nonce dropped ->
    the two go-backs to r1 share an id; `earlier` not sent -> the fold ignores the go-back; held.json written -> the
    bytes differ."""
    ex = work(tmp_path, project)
    project.add('poro', V2, name='Porosity'); ex.get('poro')
    before, holder = ex.path.read_bytes(), json.loads(ex.path.read_text())['holder_id']
    project.reports.clear()
    assert ex.report_earlier('poro', sha(V1)) is True and ex.report_earlier('poro', sha(V1)) is True
    project.refuse = [Refused('Request body is not valid', status=400)]
    assert ex.report_earlier('poro', sha(V1)) is True  # an older gateway: asked again in E70b's shape, the same id
    assert ex.path.read_bytes() == before
    one, two, refused, retried = project.reports
    for r in (one, two, refused):
        assert (r['reference']['revision'], r['binding_id'], r['earlier'], r['application']) == (sha(V1), holder, True, 'script')
        assert r['event_id'].startswith('earlier-')
    assert len({one['event_id'], two['event_id'], refused['event_id']}) == 3 and retried == {k: refused[k] for k in ('reference', 'binding_id', 'event_id')}
    ex.get('poro')  # r2 confirmed again after the go-backs: E70b's id for r2
    assert project.reports[-1]['event_id'] == exchange.delivery_event(holder, 'poro', sha(V2)) and 'earlier' not in project.reports[-1]


class Posting:
    """An ophiolite.Client stand-in for ClientTransport.report and release: the bytes and bodies it would post."""
    url, project = 'https://project.example', 'p'

    def __init__(self, released=True): self.posted, self.released = [], released

    def _post_bytes(self, area, operation, raw, **options):
        self.posted.append((area, operation, json.loads(raw))); return {}

    def _post(self, area, operation, body, **options):
        self.posted.append((area, operation, body)); return {'released': self.released}


def test_the_sdk_transport_posts_e70b_s_body_plus_only_the_fields_given():
    """Mutation: the new fields sent as null -> E70b's body changes for an older caller."""
    client = Posting(); t = ClientTransport(client)
    reference = {'project_id': 'p', 'asset_id': 'poro', 'revision': 'r1'}
    t.report(reference, HOLDER, 'got-1')
    t.report(reference, HOLDER, 'earlier-1', application='application:opendtect', earlier=True)
    base = {'reference': reference, 'binding_id': HOLDER, 'profile': 'exchange-consumer/1', 'mode': 'get'}
    assert client.posted == [('activity', 'report', {**base, 'event_id': 'got-1'}),
                             ('activity', 'report', {**base, 'event_id': 'earlier-1', 'application': 'application:opendtect', 'earlier': True})]
    client.posted.clear()
    assert t.release(HOLDER, 'poro') is True and client.posted == [('exchange', 'release', {'project_id': 'p', 'binding_id': HOLDER, 'item': 'poro'})]
    assert ClientTransport(Posting(released=False)).release(HOLDER, 'poro') is False
