"""E122 s4a C3: `Exchange.send(source=...)` names the application object a file came from. The project keeps the
record with the version and, without `of` or `as_new`, compares the send with what that object sent before: a new
item, its next version, or nothing changed (the folder then holds the item). Through the installed SDK against the
in-process gateway over HTTP."""
import pytest

from test_exchange import two_keys, uploads, points, refused, key, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401
from ophiolite import publish as planning
from ophiolite.errors import ValidationFailed, VerificationFailed
from ophiolite.models.api import PublicationReceipt

QGIS = {'system': 'application:qgis-plugin', 'instance': '/projects/groningen.qgz', 'container': 'layer-7', 'id': '42'}
HEADER = {'project_id', 'command_id', 'profile', 'name', 'derived_from', 'method', 'output_sha256', 'output_bytes'}


def send(ex, v, parent, **over):
    return ex.send(v.bytes, name='Edited points', profile=v.profile, declare=v.declared, how='edited in QGIS', based_on=[parent], **over)


def test_a_send_naming_its_source_is_new_then_unchanged_from_another_folder_then_a_version(two_keys):
    """T3.1-T3.3. Mutations: `source` dropped from `derive_request` -> no record, the second send is a new item -> red;
    the unchanged mapping removed -> `sent-new` -> red; the changed mapping removed -> `sent-new` -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    v = points(7)
    first = send(a, v, parent, source=QGIS)
    assert first.outcome == 'sent-new' and seen[-1]['source'] == QGIS
    asset = first.technical['asset_id']
    words = a.transport.client.provenance(asset, first.technical['revision']).words
    assert words.startswith('From qgis-plugin, workspace `/projects/groningen.qgz`, object `42` in `layer-7`')
    same = refused('nothing-changed', lambda: send(b, v, parent, source=QGIS))
    assert str(same) == 'This is the same as version 1; nothing was sent.', str(same)
    assert same.technical['asset_id'] == asset and b._load()['items'][asset]['revision'] == first.technical['revision']
    changed = send(b, points(8), parent, source=QGIS)
    assert (changed.outcome, changed.technical['asset_id'], changed.facts['number']) == ('sent-version', asset, 2)


def test_a_send_without_a_source_keeps_its_request_and_header(two_keys):
    """T3.4: a pending request saved by an SDK before the change equals the replay; the header is today's. Mutation:
    `source: None` always saved -> the request differs -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    sent = send(a, points(9), parent)
    assert sent.outcome == 'sent-new' and set(seen[-1]) == HEADER
    saved = {}
    real = a.transport.publish
    a.transport.publish = lambda data, request, resolved, command: saved.setdefault('r', request) and real(data, request, resolved, command)
    send(a, points(10), parent)
    assert 'source' not in saved['r'] and set(saved['r']) == {'name', 'profile', 'how', 'based_on', 'of', 'declare', 'extra', 'sha256', 'bytes'}


def test_a_pending_send_saved_by_an_sdk_before_the_change_replays_with_its_command(two_keys, tmp_path):
    """T3.4 as written (K4, S4b C0): a pending request in the shape main 9c1c934cc's SDK saved (no `source` key) is
    replayed by the same send under its own command, with today's header. Mutation: `source: None` saved always ->
    the saved request differs -> refused, not sent -> red."""
    import hashlib, json
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    v = points(11)
    record = json.loads((tmp_path / 'a/held.json').read_text())
    request = {'name': 'Edited points', 'profile': v.profile, 'how': 'edited in QGIS', 'based_on': [parent], 'of': None,
               'declare': dict(v.declared), 'extra': {}, 'sha256': hashlib.sha256(v.bytes).hexdigest(), 'bytes': len(v.bytes)}
    record['pending'] = {'command_id': '0' * 31 + 'a', 'request': request, 'owner': a.transport.identity(), 'started': 0,
                         'resolved': {'parents': [{'asset_id': parent, 'revision': record['items'][parent]['revision']}], 'expected_parent': None}}
    (tmp_path / 'a/held.json').write_text(json.dumps(record))
    sent = send(a, v, parent)
    assert (sent.outcome, sent.technical['command_id']) == ('sent-new', '0' * 31 + 'a')
    assert len(seen) == 1 and set(seen[0]) == HEADER and seen[0]['command_id'] == '0' * 31 + 'a'


def test_of_with_equal_bytes_stops_before_any_request(two_keys):
    """T3.5 (R14): the folder's own comparison answers; nothing is sent and nothing is recorded."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    caught = refused('nothing-changed', lambda: send(a, v1, parent, of=item, source=QGIS))
    assert seen == [] and str(caught) == 'This is the same as version 1; nothing was sent.', str(caught)


@pytest.mark.parametrize('source, words', [
    ({**QGIS, 'system': 'connection:qgis'}, 'A send names an application source: application:<client id>.'),
    ({**QGIS, 'system': 'application:QGIS'}, 'A send names an application source: application:<client id>.'),
    ({**QGIS, 'id': ''}, 'Name the object you send by its id (1-256 characters), its workspace (up to 160) and its container (up to 256).'),
    ({**QGIS, 'colour': 'red'}, 'A send names an application source: application:<client id>.')])
def test_the_block_is_refused_before_sending_with_the_servers_words(source, words):
    from ophiolite.writers import WrittenOriginal
    written = WrittenOriginal(b'x,y,z\n1,2,3\n', 'points-csv/1', {}, 'derived')
    with pytest.raises(ValidationFailed) as caught:
        planning.derive_request('p', written, name='n', from_=[('a1', '0' * 64)], method={'name': 'm', 'declared': False}, command_id='c', source=source)
    assert caught.value.violations == (words,)


def body(**over):
    return {'project_id': 'p', 'command_id': 'c1', 'profile': 'points-csv/1', 'name': 'n', 'method': {'name': 'm', 'declared': False},
            'derived_from': [{'asset_id': 'a1', 'revision': '1' * 64}], 'output_sha256': '2' * 64, 'output_bytes': 3, **over}


def receipt(**over):
    return PublicationReceipt.model_validate({'asset_id': 'r1', 'revision': '2' * 64, 'revision_number': 1, 'profile': 'points-csv/1',
                                              'derived_from': [{'authority': 'ophiolite:derived', 'key': 'a1', 'revision': '1' * 64, 'profile': 'points-csv/1'}],
                                              'method': {'name': 'm', 'declared': False}, 'command_id': 'c1', **over})


OTHER_PARENTS = [{'authority': 'ophiolite:derived', 'key': 'a9', 'revision': '9' * 64, 'profile': 'points-csv/1'}]


def test_verify_derived_accepts_unchanged_only_for_a_compared_send():
    """T3.6 (S6). Mutations: the `compares` test removed -> a forged unchanged receipt passes -> red; the unchanged
    exemption removed -> a compared send's stored parents refused -> red."""
    compared = body(source=QGIS)
    assert planning.verify_derived(compared, receipt(source_change='unchanged', derived_from=OTHER_PARENTS)).source_change == 'unchanged'
    for wrong in ({'revision': '3' * 64}, {'command_id': 'c2'}, {'profile': 'las2/1'}):
        with pytest.raises(VerificationFailed, match='a different file or command'): planning.verify_derived(compared, receipt(source_change='unchanged', **wrong))
    for plain in (body(), body(source={**QGIS, 'as_new': True}), body(source=QGIS, new_version_of='r1', expected_parent='0' * 64)):
        with pytest.raises(VerificationFailed, match='a comparison this send did not ask for'):
            planning.verify_derived(plain, receipt(source_change='unchanged'))
    with pytest.raises(VerificationFailed, match='different parents'): planning.verify_derived(compared, receipt(source_change='changed', derived_from=OTHER_PARENTS))
    with pytest.raises(VerificationFailed, match='a different result'):
        planning.verify_derived(body(source=QGIS, new_version_of='r2', expected_parent='0' * 64), receipt())
    assert 'source_change' not in receipt().model_dump()
