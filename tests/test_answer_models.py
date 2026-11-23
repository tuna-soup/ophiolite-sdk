"""E187 s0 C1: the SDK reads answers it does not fully know; requests stay closed.

An `Answer` keeps a field it does not know and stays strict on the fields it knows; a `Request` refuses an unknown
field; a word of a closed vocabulary this release does not know is refused in words that name the upgrade (`NEWER`),
and every other malformed answer keeps its site's own sentence and exception type. The restricted views keep
`answers.POLICY` (the disclosure check). Every pydantic model of the package is exactly one of the two."""
import base64
import copy
import importlib
import inspect
import json
import math
import pkgutil
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, ValidationError

import ophiolite
from ophiolite import Client, Credential, cli, publish, validate
from ophiolite.account import Account
from ophiolite.agents import AgentClient, DryRun, JobStatus
from ophiolite.errors import Unavailable, VerificationFailed
from ophiolite.models import api, delivery
from ophiolite.models.answers import NEWER, POLICY, Answer, Request, refusal
from ophiolite.models.generated import ScientificAsset
from ophiolite.publish import Proposals
from ophiolite.testing import FixtureTransport

CONTRACTS = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts'
AGENTS = CONTRACTS / 'agents' / 'v1' / 'fixtures' / 'valid'
LOAD = lambda path: json.loads(path.read_text())
PROCEEDS, REFUSED, STREAM = (LOAD(AGENTS / ('dry-run-%s.json' % n)) for n in ('proceeds', 'refused', 'stream'))
JOB = LOAD(AGENTS / 'job.json')
CHOICE = LOAD(AGENTS / 'choice.json')
WAITING_JOB = {**JOB, 'state': 'waiting', 'question': CHOICE['question'], 'choices': CHOICE['choices'],
               'choice_token': CHOICE['choice_token']}
TRIAL = {'state': 'tried', 'as_of': 1.5, 'current': False, 'inputs': [{'slot': 'tops', 'name': 'Tops A', 'version': 2}],
         'lines': ['Tops within 5 m: would be rejected: 1 row over 5 m']}
_FIXTURE = LOAD(AGENTS / 'proposals.json')
PROPOSALS = {'proposals': [_FIXTURE['proposals'][0], {**_FIXTURE['proposals'][1], 'trial': TRIAL,
                                                       'dry_run': {'digest': PROCEEDS['digest'], 'would': PROCEEDS['would']}}]}
ASSET = LOAD(CONTRACTS / 'assets' / 'v1' / 'fixtures' / 'grid.json')
PROJECTS = {'projects': [{'id': 'p', 'name': 'P', 'role': 'owner', 'can_administer': True, 'organization_id': None}], 'next_cursor': None}
ORGANIZATIONS = {'organizations': [{'id': 'o', 'name': 'O'}]}
LATER, LATER_VALUE = 'e187_later', {'n': 1}

ROOTS = [(DryRun, PROCEEDS), (DryRun, REFUSED), (DryRun, STREAM), (JobStatus, JOB), (JobStatus, WAITING_JOB),
         (Proposals, PROPOSALS), (ScientificAsset, ASSET), (api.ProjectsPage, PROJECTS), (api.OrganizationsPage, ORGANIZATIONS)]
# Counted at lane open: the 14 hand mirrors and every class the roots above reach.
EXERCISED = {'DryEffect', 'DryRefusal', 'DryRun', 'DryWould', 'JobChoice', 'JobStatus', 'JobStep',
             'Proposal', 'ProposalChoice', 'ProposalDryRun', 'ProposalEvidence', 'ProposalTrial', 'ProposalTrialInput', 'Proposals',
             'GridContext', 'NotEvaluated', 'Provenance', 'Reference', 'Relationships',
             'Representation', 'Retention', 'ScientificAsset', 'TypedInterpretation', 'Fidelity',
             'ProjectEntry', 'ProjectsPage', 'OrganizationEntry', 'OrganizationsPage'}


def models(model):
    """Every model instance of a parsed tree, the root first."""
    yield model
    for name in type(model).model_fields:
        value = getattr(model, name)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, BaseModel): yield from models(item)


def inject(model, raw, into):
    """Add LATER to the raw object of every model of the parsed tree; `into` collects the classes that received it."""
    raw[LATER] = LATER_VALUE
    into.add(type(model).__name__)
    for name, field in type(model).model_fields.items():
        value, key = getattr(model, name), field.alias or name
        if isinstance(value, BaseModel): inject(value, raw[key], into)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, BaseModel): inject(item, raw[key][i], into)


def stripped(value):
    if isinstance(value, dict): return {k: stripped(v) for k, v in value.items() if k != LATER}
    if isinstance(value, list): return [stripped(v) for v in value]
    return value


# --- (i) unknown fields are kept; known fields stay strict --------------------------------------------------------------

def test_an_unknown_field_is_kept_in_every_object_of_every_answer():
    """Mutation: Answer set to forbid → every root refused; a class left on forbid → red here and in (iv)."""
    received = set()
    for model, fixture in ROOTS:
        clean = model.model_validate(fixture)
        raw = copy.deepcopy(fixture)
        inject(clean, raw, received)
        later = model.model_validate(raw)
        assert stripped(later.model_dump(by_alias=True)) == clean.model_dump(by_alias=True)
        for each in models(later): assert each.model_extra == {LATER: LATER_VALUE}, type(each).__name__
    assert received == EXERCISED, received ^ EXERCISED


@pytest.mark.parametrize('change', ['wrong-type', 'missing', 'not-finite'])
def test_known_fields_stay_strict_and_keep_the_sites_sentence(change):
    """Mutation: Answer set to strict=False → the string budget passes; allow_inf_nan dropped → NaN passes."""
    data = copy.deepcopy(PROPOSALS)
    entry = data['proposals'][1]
    if change == 'wrong-type': entry['budget'] = {'runs': '1'}
    elif change == 'missing': del entry['plan']
    else: entry['expires_at'] = math.nan
    with pytest.raises(VerificationFailed) as failed: publish.parse_proposals(data)
    assert str(failed.value) == 'The proposals do not satisfy ophiolite.agent-proposals/1.'


# --- (ii) requests stay closed -------------------------------------------------------------------------------------------

REQUESTS = [api.UploadRequest, delivery.Delivery, delivery.DeliveryObservation, delivery.DeliveryProcedure, delivery.DeliveryRef]


@pytest.mark.parametrize('model', REQUESTS, ids=lambda m: m.__name__)
def test_every_request_model_is_closed(model):
    """Mutation: Request set to allow → red."""
    assert issubclass(model, Request) and model.model_config['extra'] == 'forbid'


@pytest.mark.parametrize('model', [api.UploadRequest, delivery.DeliveryRef, delivery.DeliveryProcedure], ids=lambda m: m.__name__)
def test_a_request_with_an_unknown_field_is_refused(model):
    with pytest.raises(ValidationError) as refused: model.model_validate({LATER: 1})
    assert 'extra_forbidden' in {e['type'] for e in refused.value.errors()}


# --- (iii) a word this release does not know names the upgrade --------------------------------------------------------

def _error():
    try: DryRun.model_validate(changed(PROCEEDS, ['would', 'outcome'], 'deferred'))
    except ValidationError as error: return error


def _refused(model, data):
    try: model.model_validate(data)
    except ValidationError as error: return refusal(error, VerificationFailed('fallback'))
    raise AssertionError('accepted')


def changed(base, path, value):
    data = copy.deepcopy(base)
    *head, last = path
    target = data
    for key in head: target = target[key]
    target[last] = value
    return data


@pytest.mark.parametrize('model,data,at', [
    (DryRun, changed(PROCEEDS, ['would', 'outcome'], 'deferred'), 'would.outcome'),
    (JobStatus, changed(JOB, ['state'], 'paused'), 'state'),
    (Proposals, changed(PROPOSALS, ['proposals', 1, 'trial', 'state'], 'partly_tried'), 'proposals.1.trial.state'),
    (ScientificAsset, changed(ASSET, ['authorization', 'status'], 'pending-review'), 'authorization'),
    (DryRun, changed(PROCEEDS, ['schema'], 'ophiolite.agent-dry-run/2'), 'schema'),
], ids=['dry-run-outcome', 'job-state', 'trial-state', 'discriminator-tag', 'schema-id'])
def test_an_unknown_word_is_refused_with_the_upgrade_sentence(model, data, at):
    """Mutations: refusal always returns the fallback → red; union_tag_invalid not a word → the tag case red."""
    error = _refused(model, data)
    assert type(error) is VerificationFailed and str(error) == NEWER and error.details['at'] == at


def test_the_location_names_fields_and_indices_only():
    class Keyed(Answer):
        words: dict[str, Literal['a']]
    error = _refused(Keyed, {'words': {'x-Y': 'b'}})
    assert str(error) == NEWER and error.details['at'] == 'words.*'


@pytest.mark.parametrize('model,data', [
    (ScientificAsset, changed(ASSET, ['authorization'], {})),
    (DryRun, changed(PROCEEDS, ['dry_run'], False)),
    (DryRun, changed(PROCEEDS, ['digest'], 7)),
    (DryRun, changed(changed(PROCEEDS, ['would', 'outcome'], 'deferred'), ['digest'], 7)),
], ids=['missing-tag', 'true-given-false', 'wrong-type', 'word-and-wrong-type'])
def test_anything_else_keeps_the_sites_fallback(model, data):
    error = _refused(model, data)
    assert str(error) == 'fallback'


def test_a_value_a_union_branch_accepts_is_no_refusal():
    class Either(Answer):
        value: Literal['a'] | int
    assert Either.model_validate({'value': 3}).value == 3
    assert str(_refused(Either, {'value': 'b'})) == 'fallback'  # a word in one branch, a type in the other: mixed


# --- (iv) every model of the package is an Answer or a Request -----------------------------------------------------------

def package_models():
    found, failed = {}, []
    for info in pkgutil.walk_packages(ophiolite.__path__, 'ophiolite.'):
        if '.contracts' in info.name or info.name.endswith('__main__'): continue
        try: module = importlib.import_module(info.name)
        except Exception as error: failed.append((info.name, type(error).__name__)); continue
        for value in vars(module).values():
            if inspect.isclass(value) and issubclass(value, BaseModel) and value.__module__ == module.__name__:
                found[value.__module__ + '.' + value.__qualname__] = value
    return found, failed


def test_every_model_is_exactly_one_of_answer_or_request_with_its_policy():
    """Mutations: a new class Z(BaseModel) in agents.py → red; RestrictedRun set to allow → red."""
    found, failed = package_models()
    assert failed == []
    assert len(found) > 500  # the generated contracts are walked, not only the hand mirrors
    wrong = []
    for name, model in found.items():
        if model in (Answer, Request): continue
        answer, request = issubclass(model, Answer), issubclass(model, Request)
        want = 'forbid' if request else POLICY.get(model.__name__, 'allow')
        if answer == request or model.model_config.get('extra') != want: wrong.append(name)
    assert wrong == []
    assert {n.rsplit('.', 1)[1] for n, m in found.items() if m.__name__ in POLICY} == set(POLICY)
    assert POLICY == {'RestrictedManifest': 'forbid', 'RestrictedReceipt': 'forbid', 'RestrictedBinding': 'forbid',
                      'RestrictedRun': 'ignore', 'RestrictedResultSummary': 'ignore', 'RestrictedResultPreview': 'ignore'}


# --- (v) the restricted views ------------------------------------------------------------------------------------------

BINDING = {'name': 'Edited', 'curve': 'GR'}
MANIFEST = {'schema': 'ophiolite.derived-curves-result/1', 'media_type': 'application/json', 'bytes': 2, 'sha256': '0' * 64}
RECEIPT = {'destination': 'project', 'upstream_write': False, 'publication_id': 'pub', 'identity': 'id',
           'output_reference': {'authority': 'a', 'key': 'k', 'revision': 'r'}, 'manifest': MANIFEST}
RUN = {'id': 'r', 'owner': 'o', 'project_id': 'p', 'kind': 'run', 'binding': BINDING, 'input': None,
       'parent_visibility': 'restricted', 'application_version': '1', 'state': 'completed', 'receipt': RECEIPT}
SUMMARY = {'asset_id': 'a', 'revision': 'r', 'id': 'i', 'name': 'n', 'owner': 'o', 'input': None, 'curve': 'GR', 'receipt': RECEIPT,
           'can_share': False, 'recipients': [], 'reuse_recipients': [], 'published': 1.0}
PREVIEW = {**SUMMARY, 'rows': [], 'columns': [], 'context': {}, 'total_rows': 0, 'truncated': False}


@pytest.mark.parametrize('model,data', [(api.RestrictedManifest, MANIFEST), (api.RestrictedReceipt, RECEIPT), (api.RestrictedBinding, BINDING)],
                         ids=['manifest', 'receipt', 'binding'])
def test_a_closed_restricted_view_refuses_more_than_its_shape(model, data):
    """Mutation: RestrictedManifest set to allow → red (the disclosure check)."""
    model.model_validate(data)
    with pytest.raises(ValidationError) as refused: model.model_validate({**data, LATER: 'source'})
    assert {e['type'] for e in refused.value.errors()} == {'extra_forbidden'}


@pytest.mark.parametrize('model,data', [(api.RestrictedRun, RUN), (api.RestrictedResultSummary, SUMMARY), (api.RestrictedResultPreview, PREVIEW)],
                         ids=['run', 'summary', 'preview'])
def test_a_dropped_restricted_view_never_reaches_the_extra_field(model, data):
    """Mutation: RestrictedRun set to allow → the field is an attribute and in the dump."""
    view = model.model_validate({**data, LATER: 'source'})
    assert not hasattr(view, LATER) and LATER not in view.model_dump() and not view.model_extra


# --- (vi) the public paths go through refusal --------------------------------------------------------------------------

def gateway(path, answer):
    return httpx.Client(transport=FixtureTransport([{'method': 'POST', 'path': path, 'status': 200,
                                                     'body_base64': base64.b64encode(json.dumps(answer).encode()).decode(),
                                                     'headers': {'content-type': 'application/json'}}]))


def agent(path, answer):
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=gateway(path, answer))


def person(answer):
    return Client('https://x.example', 'p', Credential.bearer('oph_api_alice:read,write'), gateway('/api/v1/projects/p/agents/proposals', answer))


def try_(tmp_path, answer):
    body = tmp_path / 'body.json'
    body.write_text('{"result_id": "r1", "verdict": "accepted", "command_id": "v-1"}')
    return cli._try(SimpleNamespace(operation='verdicts/record', body=body, json=True), agent('/api/v1/projects/p/verdicts/record', answer))


DRY_WORD = changed(PROCEEDS, ['would', 'outcome'], 'deferred')
DRY_BAD = changed(PROCEEDS, ['digest'], 7)
CALLS = {
    'dry-run': lambda answer, tmp: agent('/api/v1/projects/p/verdicts/record', answer).dry_run('verdicts/record', {'result_id': 'r1'}),
    'job-status': lambda answer, tmp: agent('/api/v1/projects/p/jobs/status', answer).job_status(JOB['plan']),
    'proposals': lambda answer, tmp: person(answer).proposals(),
    'cli-try': lambda answer, tmp: try_(tmp, answer),
}
ANSWERS = {'dry-run': (PROCEEDS, DRY_WORD, DRY_BAD), 'job-status': (JOB, changed(JOB, ['state'], 'paused'), changed(JOB, ['step'], '2')),
           'proposals': (PROPOSALS, changed(PROPOSALS, ['proposals', 1, 'trial', 'state'], 'partly_tried'), changed(PROPOSALS, ['proposals', 1, 'plan'], 7)),
           'cli-try': (PROCEEDS, DRY_WORD, DRY_BAD)}


@pytest.mark.parametrize('call', sorted(CALLS))
def test_each_public_path_keeps_an_unknown_field_and_names_the_upgrade_for_a_word(call, tmp_path, capsys):
    """Mutation: one site reverted to its own except → its word case keeps the old sentence (red)."""
    good, word, bad = ANSWERS[call]
    CALLS[call]({**good, LATER: LATER_VALUE}, tmp_path)
    with pytest.raises(VerificationFailed) as newer: CALLS[call](word, tmp_path)
    assert str(newer.value) == NEWER
    with pytest.raises(VerificationFailed) as old: CALLS[call](bad, tmp_path)
    assert type(old.value) is VerificationFailed and str(old.value) != NEWER


def test_account_discovery_keeps_an_unknown_field_and_its_unavailable():
    """The discovery pages have no closed word; a malformed page stays Unavailable (account.checked)."""
    def account(answer): return Account('https://x.example', Credential.bearer('oph_api_alice:read,write'), gateway('/api/v1/projects/organizations', answer))
    assert account({**ORGANIZATIONS, LATER: LATER_VALUE}).organizations() == ORGANIZATIONS['organizations']
    with pytest.raises(Unavailable) as failed: account({'organizations': [{'id': 7, 'name': 'O'}]}).organizations()
    assert type(failed.value) is Unavailable and str(failed.value) == 'Invalid organisation discovery response.'


def test_served_documents_name_the_upgrade_for_a_word_and_keep_their_sentence_otherwise():
    """The site's consequence ("No files were saved.") follows the upgrade sentence (ophiolite-66's condition on the
    rule). Mutation: refusal drops the fallback's recovery → red."""
    with pytest.raises(VerificationFailed) as newer: validate.model(ScientificAsset, changed(ASSET, ['authorization', 'status'], 'pending-review'))
    assert (str(newer.value), newer.value.message, newer.value.code) == (NEWER + ' No files were saved.', NEWER, 'verification-failed')
    assert str(refusal(_error(), VerificationFailed('fallback'))) == NEWER  # a site with no consequence: the plain sentence
    with pytest.raises(VerificationFailed) as old: validate.model(ScientificAsset, changed(ASSET, ['authorization'], {}))
    assert str(old.value) == 'Scientific data does not satisfy the declared contract. No files were saved.'
