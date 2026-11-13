"""E166 s1 C2 (K1, K5; Codex R12), gateway lane: through the real SDK against an in-process gateway, an assistant's
report that would publish is refused at proposal unless the tool version is trusted by its person and verified, with
the gateway's code, reason and sentence and nothing kept; and a derive the SDK sends outside a reported run is refused
`no-run`. The world is the Platform's `test_agents_covered.World` (bob's agent, alice's enabled two-output procedure
that bob trusts and alice verified, bob's tops). Expected sentences are written here by hand.

Mutation: the gate removed from `Agents.propose` → the untrusted and unverified reports are proposed."""
import hashlib
import json
import os

import pytest
try:
    from project_gateway.tests.test_agents_covered import World, SHIFTED_RAW, count, executed  # noqa: F401 (fixture)
    from project_gateway.tests.test_one_api_matrix import web  # noqa: F401 (fixture)
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite.errors import OphioliteError
from ophiolite.procedures import AgentRun
from test_agent_procedures import Seen, agent, approve, folder

NOT_TRUSTED = 'The tool version this run names is not trusted by Bob.'
NOT_VERIFIED = 'The tool version this run names is not verified.'
NO_RUN = 'No tool ran this: an assistant publishes a result only as a step of a tool run it reported.'


@pytest.fixture
def two(web):
    return World(web, two=True, budgets={'runs': 2, 'publications': 3})


def kept(w):
    return {t: count(w.web, t) for t in ('agent_plans', 'agent_evidence', 'agent_commands', 'procedure_runs', 'agent_covered')}


def refused(raised, reason, sentence):
    error = raised.value
    assert (error.status, error.code, error.details.get('reason'), error.server_message or error.message) == (403, 'tool-run-refused', reason, sentence), vars(error)


def untrusted(w, tmp_path):
    """A run of alice's version 3 of the same procedure, enabled, which bob has not trusted (and nobody verified)."""
    from project_gateway.tests.procedure_world import archive, b64, files
    from project_gateway.tests.test_procedure_publish import TWO_ROLES
    d = w.alice.ok('procedures', 'register', {'command_id': 'sdk-reg', 'archive': b64(archive(files(outputs=TWO_ROLES, version=3)))})['digest']
    w.alice.ok('procedures', 'enable', {'command_id': 'sdk-en', 'digest': d})
    out = folder(tmp_path, w)
    record = json.loads((out / 'run.json').read_text())
    record['procedure'].update(digest=d, version=3)
    (out / 'run.json').write_text(json.dumps(record))
    return out


def test_a_report_of_a_version_its_person_does_not_trust_is_refused_at_proposal(two, tmp_path, executed):
    out = untrusted(two, tmp_path)
    before, seen = kept(two), Seen(two.web.c)
    with pytest.raises(OphioliteError) as raised:
        AgentRun(agent(two, seen), out, name='Shifted Chalk tops').report('Publish the shifted tops', sleep=approve(two))
    refused(raised, 'not-trusted', NOT_TRUSTED)
    assert seen.paths == ['agents/propose'] and kept(two) == before and executed == []


def test_a_report_of_a_version_whose_verification_was_withdrawn_is_refused_at_proposal(two, tmp_path, executed):
    [verification] = two.alice.ok('procedures', 'verifications', {'digest': two.d})['records']
    two.alice.ok('procedures', 'verify', {'command_id': 'sdk-unverify', 'digest': two.d, 'kind': 'withdrawn', 'reference': {'withdraws': verification['record']['id']}})
    before, seen = kept(two), Seen(two.web.c)
    with pytest.raises(OphioliteError) as raised:
        AgentRun(agent(two, seen), folder(tmp_path, two), name='Shifted Chalk tops').report('Publish the shifted tops', sleep=approve(two))
    refused(raised, 'not-verified', NOT_VERIFIED)
    assert seen.paths == ['agents/propose'] and kept(two) == before and executed == []


def test_a_trusted_verified_version_reports_and_publishes(two, tmp_path, executed):
    done = AgentRun(agent(two, Seen(two.web.c)), folder(tmp_path, two), name='Shifted Chalk tops').report('Publish the shifted tops', sleep=approve(two))
    assert [o['role'] for o in done['outputs']] == ['shifted', 'moved'] and len(executed) == 2


def test_a_derive_the_sdk_sends_outside_a_reported_run_is_refused_no_run(two, executed):
    """K5: sent without a plan, the SDK's derive is refused `no-run` by the gateway; nothing is kept. (Proposing one
    alone the SDK refuses itself, before sending: it is no operation an agent proposes.)"""
    header = {'command_id': 'sdk-standalone', 'profile': 'well-tops-csv/1', 'declared': {'depth_unit': 'M', 'depth_basis': 'same-as-log'},
              'name': 'Standalone', 'derived_from': [two.a], 'method': {'name': 'Hand edit', 'parameters': {}},
              'output_sha256': hashlib.sha256(SHIFTED_RAW).hexdigest(), 'output_bytes': len(SHIFTED_RAW)}
    seen = Seen(two.web.c)
    client, before = agent(two, seen), kept(two)
    with pytest.raises(OphioliteError) as raised: client.propose('publications/derive', header, 'publish it')
    assert raised.value.status is None and seen.paths == []
    with pytest.raises(OphioliteError) as raised: client.execute_step('publications/derive', header, None, raw=SHIFTED_RAW)
    refused(raised, 'no-run', NO_RUN)
    assert seen.paths == ['publications/derive'] and kept(two) == before and executed == []
