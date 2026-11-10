"""E150 s1b R1-12 against the in-process gateway with the switch on: the library's dry run, then its proposal naming
that dry run, is kept with the gateway's own run of it and shown to the person; a changed request is refused `stale`."""
import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401
from ophiolite.errors import DryRunRefused
from test_agent_evidence_gateway import issue
from test_agent_evidence import EVIDENCE_16


@pytest.fixture
def on(request, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_TRY_FIRST', 'stub')  # read once, when the app is made
    return request.getfixturevalue('web')


def configure(web, suffix):
    return {'name': 'Agent dry run ' + suffix, 'release_id': web.r['id'], 'asset_index': 0, 'curve': 'GR', 'runners': ['alice'],
            'command_id': 'cfg-' + suffix}


def test_a_proposal_with_its_dry_run_round_trips(on):
    """Mutation: propose() leaving dry_run out of the evidence → the person's plan shows no dry run."""
    alice, agent = issue(on, policy=())
    request = configure(on, 'trip')
    dry = agent.dry_run('applications/configure', request)
    assert dry.would.model_dump(exclude_none=True) == {'outcome': 'proceeds', 'effects': [{'action': 'create', 'kind': 'record', 'count': 1}]}
    proposed = agent.propose('applications/configure', request, 'Configure the gamma ray', evidence=EVIDENCE_16, dry_run=dry)
    [shown] = [p for p in alice.ok('agents', 'proposals', {})['proposals'] if p['plan'] == proposed['hash']]
    assert shown['dry_run'] == {'digest': dry.digest, 'would': {'outcome': 'proceeds', 'effects': [{'action': 'create', 'kind': 'record', 'count': 1}]}}
    with pytest.raises(DryRunRefused) as stale:
        agent.propose('applications/configure', {**request, 'name': 'Agent dry run other'}, evidence=EVIDENCE_16, dry_run=dry.digest)
    assert (stale.value.code, stale.value.message, stale.value.status) == (
        'dry-run-refused', 'The project changed since this dry run: run it again and propose with the new digest.', 400)
