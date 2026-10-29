"""E122 s0 C4: Client.provenance passes the gateway's sentence through unchanged; it composes nothing."""
import pytest
from ophiolite import Client, Credential
from ophiolite.errors import Refused, Unavailable, VerificationFailed
from ophiolite.testing import synthetic_server


def test_the_served_sentence_is_returned_unchanged():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        d = server.template_descriptor
        found = alice.provenance(d['asset_id'], d['revision'])
        assert found.words == 'Synthetic §words — 7'  # a client composing from the fields would not produce this
        assert found.record is None and found.json['schema'] == 'ophiolite.source-provenance/1'


def test_an_answer_for_another_version_and_an_unknown_version_are_refused():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        d = server.template_descriptor
        inner = server.handler
        def other(method, path, body, headers):
            status, answer = inner(method, path, body, headers)
            return (status, {**answer, 'revision': 'another'}) if path.endswith('/provenance') else (status, answer)
        server.handler = other
        with pytest.raises(VerificationFailed): alice.provenance(d['asset_id'], d['revision'])
        server.handler = inner
        with pytest.raises(Unavailable): alice.provenance(d['asset_id'], 'f' * 64)
        with pytest.raises(Refused): alice.provenance(d['asset_id'], '')


def test_a_served_record_does_not_replace_the_served_sentence():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        d = server.template_descriptor
        inner = server.handler
        record = {'schema': 'ophiolite.source-provenance/1',
                  'identity': {'source_system': 'upload', 'source_instance': None, 'id_scheme': 'source-path', 'source_object_id': {'path': 'wells/tops.csv', 'part': None}},
                  'content': {'content_sha256': 'a' * 64, 'source_version': None}, 'context': {'comparison': 'comparison/1', 'context_sha256': 'b' * 64}}
        def recorded(method, path, body, headers):
            status, answer = inner(method, path, body, headers)
            return (status, {**answer, 'record': record}) if path.endswith('/provenance') else (status, answer)
        server.handler = recorded
        found = alice.provenance(d['asset_id'], d['revision'])
        assert (found.words, found.record) == ('Synthetic §words — 7', record)
