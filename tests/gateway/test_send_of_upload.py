"""adhoc-e121-words2 B7 (E121 O1): `send --of` naming one's own upload. An upload takes no sent version (`publications.derive`
adds versions to derived results only; an upload's next version is an upload, E53), so its author was refused with "Only
the author can add a version to this result, of the same type". The SDK now refuses before sending and says to send a
new item based on the upload; the Gateway says the same to the upload's author when the publication reaches it. Anyone
else still reads today's words (the kind of an item is not told to someone who did not upload it)."""
import pytest

from test_exchange import two_keys, uploads, points, refused, key, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401
from ophiolite.errors import PermissionRefused

UPLOAD = 'An upload does not take a published version; publish this as a new result based on the upload'
TODAY = 'Only the author can add a version to this result, of the same type'


def test_send_of_ones_own_upload_is_refused_before_sending_naming_the_way(two_keys):
    """Mutation: the SDK check removed -> the Gateway's 403 arrives as `access-refused` -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    v2 = points(3)
    send = lambda **of: a.send(v2.bytes, name='Edited points', profile=v2.profile, declare=v2.declared, how='edited', based_on=[parent], **of)
    caught = refused('not-valid', lambda: send(of=parent))
    assert str(caught) == ('The project refused this: Picked points is an upload, which does not take a sent version; '
                           'send this as a new item based on it. Nothing was sent.')
    assert seen == []
    assert send().outcome == 'sent-new'  # the way it names


def publish(ex, parent, revision, command_id):
    """The publication itself, past the SDK's check (an older SDK, or a client of its own)."""
    v = points(4)
    request = {'name': 'Picked points', 'profile': v.profile, 'how': 'edited', 'declare': v.declared, 'of': parent}
    with pytest.raises(PermissionRefused) as caught:
        ex.transport.publish(v.bytes, request, {'parents': [{'asset_id': parent, 'revision': revision}], 'expected_parent': revision}, command_id)
    return caught.value.server_message


def test_the_gateway_tells_the_uploads_author_and_nobody_else(two_keys, tmp_path):
    """Mutation: the author's words removed -> today's words -> red; the author test removed -> Bob reads them -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    revision = a._load()['items'][parent]['revision']
    assert publish(a, parent, revision, 'b7-alice') == UPLOAD
    bob = client(web, key(web, 'bob')).exchange(tmp_path / 'bob'); bob.check(); bob.get(parent, output=tmp_path / 'pbob')
    assert publish(bob, parent, revision, 'b7-bob') == TODAY
