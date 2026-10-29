"""E122 s4b C2: the block the QGIS plug-in builds (`vector_send.source_block`), sent through the shared core to the
in-process gateway over HTTP: the project records the plug-in, the project file and the layer, matches a re-send of
the layer by its id whatever its name, answers an equal file as nothing changed, keeps "as a new item" apart, and
records nothing for a send without the block. The words are the route's, which the SDK and the Workspace show."""
import hashlib

import pytest

from test_exchange import two_keys, uploads, points, refused, key, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401

try:
    from scalar_maps.qgis_plugin import vector_send as V
except ImportError:
    pytest.skip('the Connectors source is needed for the gateway lane', allow_module_level=True)

LAYER = 'parcels_7d1c2e0a_5b4f_4c1e_9f62_0a3b8e5d2c11'
PROJECT = '/projects/groningen.qgz'


def send(ex, v, parent, name='Parcels', **over):
    return ex.send(v.bytes, name=name, profile=v.profile, declare=v.declared, how='QGIS', based_on=[parent], **over)


def words(ex, outcome):
    return ex.transport.client.provenance(outcome.technical['asset_id'], outcome.technical['revision']).words


def test_a_layer_is_matched_by_its_id_whatever_its_name(two_keys):
    """T4.7, T4.8 (acceptance 4, 6, 7). Mutation: container or id taken from the layer's name -> the renamed send is
    a new item -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    seen = uploads(web)
    block = V.source_block(LAYER, PROJECT)
    v = points(21)
    first = send(a, v, parent, source=block)
    assert first.outcome == 'sent-new' and seen[-1]['source'] == block
    said = words(a, first)
    assert said == 'From qgis-plugin, workspace `%s`, object `%s` in `%s` (checksum %s…).' % (PROJECT, LAYER, LAYER, hashlib.sha256(v.bytes).hexdigest()[:12])
    # `provenance()` reads GET …/revisions/<rev>/provenance over HTTP, the route the Workspace shows verbatim (SourceLine.tsx)
    assert b.transport.client.provenance(first.technical['asset_id'], first.technical['revision']).words == said
    renamed = send(b, points(22), parent, name='Parcels edited', source=V.source_block(LAYER, PROJECT))
    assert (renamed.outcome, renamed.technical['asset_id'], renamed.facts['number']) == ('sent-version', first.technical['asset_id'], 2)


def test_an_equal_file_is_nothing_changed_and_other_bytes_are_a_version(two_keys):
    """T4.9 (K9, a stated limit): the project compares bytes; an equal file from another folder is nothing changed
    and that folder then holds the item; any other bytes are the next version. Mutation: as_new always sent -> a new
    item -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    v = points(23)
    first = send(a, v, parent, source=V.source_block(LAYER, PROJECT))
    same = refused('nothing-changed', lambda: send(b, v, parent, source=V.source_block(LAYER, PROJECT)))
    assert same.technical['asset_id'] == first.technical['asset_id'] and b._load()['items'][first.technical['asset_id']]['revision'] == first.technical['revision']
    other = send(b, points(24), parent, source=V.source_block(LAYER, PROJECT))
    assert (other.outcome, other.technical['asset_id']) == ('sent-version', first.technical['asset_id'])


def test_as_a_new_item_keeps_its_record_and_is_not_compared(two_keys):
    """T4.10 (F3). Mutation: `as_new` not sent -> the second send is a version of the first -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    first = send(a, points(25), parent, source=V.source_block(LAYER, PROJECT))
    second = send(b, points(26), parent, source={**V.source_block(LAYER, PROJECT), 'as_new': True})
    assert second.outcome == 'sent-new' and second.technical['asset_id'] != first.technical['asset_id']
    assert words(b, second).startswith('From qgis-plugin, workspace `%s`, object `%s`' % (PROJECT, LAYER))


def test_a_send_without_the_block_succeeds_and_records_nothing(two_keys):
    """T4.11 (Q1): an older plug-in. Mutation: a record written without a block -> other words -> red."""
    web, ka, kb, a, b, parent, item, v1 = two_keys
    sent = send(a, points(27), parent)
    assert sent.outcome == 'sent-new' and words(a, sent) == 'Where this came from was not recorded.'


def test_the_sdk_passes_the_servers_words_through_verbatim(two_keys, monkeypatch):
    """T4 (E122 s4c, F7, R7): the server's sentence, whatever it holds, reaches the SDK unchanged. Runs in Visual's
    "SDK native gateway lane", which imports the Connectors source. Mutation: the SDK composing, stripping or
    normalising the words -> red."""
    from project_gateway import source_provenance
    web, ka, kb, a, b, parent, item, v1 = two_keys
    monkeypatch.setattr(source_provenance, 'words', lambda record, filename=None: '  Wörds o\u0308 ✓ from the server, not the record\u00a0 ')
    first = send(a, points(28), parent, source=V.source_block(LAYER, PROJECT))
    assert words(a, first) == '  Wörds o\u0308 ✓ from the server, not the record\u00a0 '
