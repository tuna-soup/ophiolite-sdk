"""E178 s2c (D-13), offline: `client.chains` is a ChainClient bound to the client; each of its seventeen methods sends
one request to its route with the body the gateway's request model names, a new command id on each write unless one
is given, and refuses nothing itself (the server decides who may declare, enable, dismiss or act). The words of a run
come from the synced vocabulary and name no step key or code."""
import json
from pathlib import Path

import pytest

import ophiolite
from ophiolite import chains
from ophiolite.client import Client
from ophiolite.errors import Refused
from ophiolite.publish import operation_path

CONTRACTS = Path(ophiolite.__file__).resolve().parent / 'contracts'
METHODS = ('declare', 'revise', 'enable', 'disable', 'withdraw', 'list', 'get', 'due', 'dismiss', 'run_start', 'run_attach', 'run_choose',
           'run_acknowledge', 'run_decide', 'run_continue', 'run_get', 'run_list')
V = {'asset_id': 'a1', 'revision': 'f' * 64}


class Fake:
    def __init__(self):
        self.sent = []

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        return {'answered': operation}


def test_client_chains_is_a_chain_client_bound_to_the_client_with_exactly_its_methods():
    client = Client('http://127.0.0.1:1', 'p')
    assert isinstance(client.chains, chains.ChainClient) and client.chains._client is client
    assert sorted(m for m in vars(chains.ChainClient) if not m.startswith('_')) == sorted(METHODS)


@pytest.mark.parametrize('area,operation', [('chains', o) for o in ('declare', 'revise', 'enable', 'disable', 'withdraw', 'list', 'get', 'due', 'dismiss')]
                         + [('chain-runs', o) for o in ('start', 'attach', 'choose', 'acknowledge', 'decide', 'continue', 'get', 'list')])
def test_the_seventeen_chain_operations_have_their_paths(area, operation):
    assert operation_path('p one', area, operation) == '/api/v1/projects/p%20one/' + area + '/' + operation


@pytest.mark.parametrize('area', ['chains', 'chain-runs'])
def test_no_other_chain_operation_is_sent(area):
    """Mutation: a `delete` added to the chains sets is sent instead of refused here (no such route)."""
    with pytest.raises(Refused, match='Unsupported application operation.'):
        operation_path('p', area, 'delete')


def test_each_method_sends_the_body_its_route_names():
    fake = Fake()
    c = chains.ChainClient(fake)
    d = {'schema': 'ophiolite.chain/1'}
    c.declare(d, command_id='k1'); c.revise('c1', d, command_id='k2'); c.enable('c1', command_id='k3'); c.disable('c1', command_id='k4')
    c.withdraw('c1', command_id='k5'); c.list(); c.list(limit=5, cursor='n'); c.get('c1'); c.due(); c.due('c1', limit=3, cursor='m')
    c.dismiss('c1', 'a1', 'f' * 64, 'Superseded', command_id='k6')
    c.run_start('c1', 2, trigger=('a1', 'f' * 64), command_id='k7'); c.run_start('c1', 1, inputs=[V, ('a2', 'e' * 64)], command_id='k8')
    c.run_attach('r1', 'residuals', V, command_id='k9'); c.run_choose('r1', 'go-on', 'hold', command_id='k10')
    c.run_acknowledge('r1', 'design', 'Held', command_id='k11'); c.run_acknowledge('r1', 'design', 'Held', reference='Minutes', command_id='k12')
    c.run_decide('r1', 'design', False, 'No block', command_id='k13'); c.run_continue('r1', 'residuals', 'Known', command_id='k14')
    c.run_get('r1'); c.run_get('r1', step='design', cursor='o'); c.run_list(); c.run_list('c1', limit=1)
    assert fake.sent == [
        ('chains', 'declare', {'command_id': 'k1', 'chain': d}, True), ('chains', 'revise', {'command_id': 'k2', 'chain_id': 'c1', 'chain': d}, True),
        ('chains', 'enable', {'command_id': 'k3', 'chain_id': 'c1'}, True), ('chains', 'disable', {'command_id': 'k4', 'chain_id': 'c1'}, True),
        ('chains', 'withdraw', {'command_id': 'k5', 'chain_id': 'c1'}, True), ('chains', 'list', {}, True),
        ('chains', 'list', {'limit': 5, 'cursor': 'n'}, True), ('chains', 'get', {'chain_id': 'c1'}, True), ('chains', 'due', {}, True),
        ('chains', 'due', {'chain_id': 'c1', 'limit': 3, 'cursor': 'm'}, True),
        ('chains', 'dismiss', {'command_id': 'k6', 'chain_id': 'c1', 'asset_id': 'a1', 'revision': 'f' * 64, 'reason': 'Superseded'}, True),
        ('chain-runs', 'start', {'command_id': 'k7', 'chain_id': 'c1', 'chain_version': 2, 'trigger': V}, True),
        ('chain-runs', 'start', {'command_id': 'k8', 'chain_id': 'c1', 'chain_version': 1, 'inputs': [V, {'asset_id': 'a2', 'revision': 'e' * 64}]}, True),
        ('chain-runs', 'attach', {'command_id': 'k9', 'run_id': 'r1', 'step': 'residuals', 'result': V}, True),
        ('chain-runs', 'choose', {'command_id': 'k10', 'run_id': 'r1', 'step': 'go-on', 'choice': 'hold'}, True),
        ('chain-runs', 'acknowledge', {'command_id': 'k11', 'run_id': 'r1', 'step': 'design', 'label': 'Held'}, True),
        ('chain-runs', 'acknowledge', {'command_id': 'k12', 'run_id': 'r1', 'step': 'design', 'label': 'Held', 'reference': 'Minutes'}, True),
        ('chain-runs', 'decide', {'command_id': 'k13', 'run_id': 'r1', 'step': 'design', 'apply': False, 'reason': 'No block'}, True),
        ('chain-runs', 'continue', {'command_id': 'k14', 'run_id': 'r1', 'step': 'residuals', 'reason': 'Known'}, True),
        ('chain-runs', 'get', {'run_id': 'r1'}, True), ('chain-runs', 'get', {'run_id': 'r1', 'step': 'design', 'cursor': 'o'}, True),
        ('chain-runs', 'list', {}, True), ('chain-runs', 'list', {'chain_id': 'c1', 'limit': 1}, True)]


def test_each_write_sends_a_new_command_id_unless_one_is_given():
    fake = Fake()
    c = chains.ChainClient(fake)
    c.enable('c1'); c.enable('c1'); c.run_continue('r1', 's', 'x')
    (_, _, first, _), (_, _, second, _), (_, _, third, _) = fake.sent
    assert first['command_id'].startswith('enable-') and len(first['command_id']) == len('enable-') + 32 and first != second
    assert third['command_id'].startswith('continue-')


def test_nothing_is_refused_on_this_computer():
    """Who may declare, enable, dismiss or act is the server's (ruling 2): any body is sent as given, an empty
    declaration and an empty reason included (mutation: a client-side check raises before `_post`)."""
    fake = Fake()
    c = chains.ChainClient(fake)
    c.declare({}); c.dismiss('c1', 'a1', 'r', ''); c.run_decide('r1', 'k', True, ''); c.run_start('c1', 1)
    assert [s[1] for s in fake.sent] == ['declare', 'dismiss', 'decide', 'start']


def test_the_words_are_the_synced_vocabulary_and_name_no_key_or_code():
    words = json.loads((CONTRACTS / 'vocabulary/v1/chain-reasons.json').read_text())
    assert chains.vocabulary() == words
    did_not = {'key': 'design', 'label': 'Design review', 'state': 'did-not-apply',
               'condition': {'step': 'residuals', 'measure': 'largest_residual', 'comparison': 'above', 'value': 5.0, 'unit': 'm', 'read': 5.0,
                             'outcome': 'did-not-apply'}}
    assert chains.state_words(did_not) == 'Did not apply: the largest residual, either sign was 5 m, not above 5 m'
    between = {**did_not, 'condition': {**did_not['condition'], 'comparison': 'between', 'value': [1.5, 4.0], 'read': 5.0}}
    assert chains.state_words(between) == 'Did not apply: the largest residual, either sign was 5 m, not between 1.5 and 4 m'
    assert {chains.state_words({'state': s}) for s in words['states'] if s != 'did-not-apply' and '{' not in words['states'][s]} <= set(words['states'].values())
