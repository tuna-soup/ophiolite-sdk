"""E182 s2b C1: the SDK says what the gateway said sent a version, and composes nothing.

T1.1: `provenance(...).sender` is the served `ophiolite.sender/1` view and `.sender_words` the served sentence (a sentence
the SDK could not compose comes back unchanged), in both clients; an answer from before E182 s0 has neither key and both
are None. T1.2: `describe(...)` on a descriptor that carries `sender` (scientific-asset/1 1.38.0) returns a model whose
`.sender` is the provenance answer's for the same version; without it, None. Everything here is synthetic."""
import copy

import anyio
from ophiolite import Client, Credential
from ophiolite.aio import AsyncClient
from ophiolite.testing import synthetic_server

SENT = {'schema': 'ophiolite.sender/1', 'state': 'reported', 'client': {'product': 'qgis-plugin', 'version': '1.4.0'},
        'host': {'name': 'qgis', 'version': '3.34.2'}, 'transport': 'http', 'accepted_as': 'synthetic-points/1'}
WORDS = 'Synthetic sender §words — 9'  # no rule the SDK could hold composes this from SENT


def with_sender(server, sender=SENT, words=WORDS, describe=True):
    """The synthetic server, its provenance answer (and, with DESCRIBE, its descriptor) carrying the sender as a gateway
    after E182 s2a serves it."""
    inner, exact = server.handler, None
    d = server.template_descriptor
    exact = '/api/v1/projects/p/scientific-assets/%s/revisions/%s' % (d['asset_id'], d['revision'])

    def handler(method, path, body, headers):
        status, answer = inner(method, path, body, headers)
        route = path.split('?')[0]
        if status == 200 and route == exact + '/provenance': answer = {**answer, 'sender': copy.deepcopy(sender), 'sender_words': words}
        elif status == 200 and route == exact and describe: answer = {**answer, 'sender': copy.deepcopy(sender)}
        return status, answer
    server.handler = handler


def both(server, ask):
    """ASK(client) on the synchronous client and, awaited, on the asynchronous one."""
    with Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        first = ask(alice)

    async def main():
        async with AsyncClient(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
            return await ask(alice)
    return first, anyio.run(main)


def test_t1_1_the_served_sender_and_its_sentence_come_back_unchanged():
    with synthetic_server() as server:
        with_sender(server)
        d = server.template_descriptor
        for found in both(server, lambda c: c.provenance(d['asset_id'], d['revision'])):
            assert found.sender == SENT and found.sender_words == WORDS
            assert found.words == 'Synthetic §words — 7'  # the version's own sentence is untouched beside it


def test_t1_1_each_state_is_passed_through_as_served():
    for sent, words in (({**SENT, 'state': 'not reported', 'client': None, 'host': None, 'accepted_as': None}, 'Not reported, as served.'),
                        ({'schema': 'ophiolite.sender/1', 'state': 'not recorded', 'client': None, 'host': None, 'transport': None, 'accepted_as': None},
                         'Not recorded, as served.')):
        with synthetic_server() as server:
            with_sender(server, sent, words)
            d = server.template_descriptor
            for found in both(server, lambda c: c.provenance(d['asset_id'], d['revision'])):
                assert (found.sender, found.sender_words) == (sent, words)


def test_t1_1_an_answer_from_before_senders_gives_none_and_raises_nothing():
    with synthetic_server() as server:  # the synthetic provenance answer is the pre-s0 shape: no `sender`, no `sender_words`
        d = server.template_descriptor
        for found in both(server, lambda c: c.provenance(d['asset_id'], d['revision'])):
            assert 'sender' not in found.json and 'sender_words' not in found.json
            assert found.sender is None and found.sender_words is None


def test_t1_2_describe_carries_the_same_sender_as_provenance():
    with synthetic_server() as server:
        with_sender(server)
        d = server.template_descriptor
        described = both(server, lambda c: c.describe(d['asset_id'], d['revision'], 'GR'))
        found = both(server, lambda c: c.provenance(d['asset_id'], d['revision']))
        for model, answer in zip(described, found):
            assert model.sender.model_dump(by_alias=True) == answer.sender == SENT


def test_t1_2_describe_without_a_sender_gives_none():
    with synthetic_server() as server:
        with_sender(server, describe=False)
        d = server.template_descriptor
        for model in both(server, lambda c: c.describe(d['asset_id'], d['revision'], 'GR')):
            assert model.sender is None and 'sender' not in model.model_dump(by_alias=True, exclude_none=True)
