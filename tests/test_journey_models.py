"""E31 S2: the journey routes' answers are typed from the synced contract, validated inside the client methods (whose
return shapes are unchanged), and the generated TypeScript types are useful (real fields, not unknown)."""
import json
import re
from pathlib import Path
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite.models import api
from ophiolite.errors import Unavailable, VerificationFailed

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = json.loads((ROOT / 'ophiolite/contracts/openapi/v1/openapi.json').read_text())
JOURNEY = {('/api/v1/projects/list', api.ProjectsPage), ('/api/v1/projects/organizations', api.OrganizationsPage),
           ('/api/v1/projects/{project}/changes/head', api.ChangesHead), ('/api/v1/projects/{project}/changes/list', api.ChangesPage),
           ('/api/v1/projects/{project}/entities/extent', api.EntityExtent), ('/api/v1/projects/{project}/entities/list', api.EntityPage),
           ('/api/v1/projects/{project}/publications/derive', api.PublicationReceipt)}


def answer_schema(path):
    return OPENAPI['paths'][path]['post']['responses']['200']['content']['application/json']['schema']


@pytest.mark.parametrize('path,model', sorted(JOURNEY, key=lambda x: x[0]))
def test_each_journey_model_mirrors_its_documented_answer(path, model):
    schema = answer_schema(path)
    fields = {f.alias or name for name, f in model.model_fields.items()}
    required = {f.alias or name for name, f in model.model_fields.items() if f.is_required()}
    assert fields == set(schema['properties']), (path, fields ^ set(schema['properties']))
    assert required == set(schema.get('required', [])), (path, required ^ set(schema.get('required', [])))


def client(answer):
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_api_alice'),
                  http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=answer))))


def test_valid_answers_come_back_unchanged():
    head = {'epoch': 'e1', 'cursor': 4}
    with client(head) as c: assert c.sync().head() == head
    extent = {'crs': 'OGC:CRS84', 'bbox': [5.0, 52.0, 6.0, 53.0], 'count': 2, 'untransformed': 0}
    with client(extent) as c: assert c.extent() == extent


@pytest.mark.parametrize('call,answer,error', [
    (lambda c: c.sync().head(), {'epoch': 'e1'}, VerificationFailed),
    (lambda c: list(c.sync().changes('e1', 0)), {'epoch': 'e1', 'changes': [{'project': 'p'}], 'cursor': 1, 'has_more': False}, VerificationFailed),
    (lambda c: c.extent(), {'crs': 'OGC:CRS84', 'bbox': [1, 2], 'count': 1, 'untransformed': 0}, VerificationFailed),
    (lambda c: c.wells(), {'entities': 'many'}, VerificationFailed),
])
def test_an_answer_outside_its_documented_shape_is_refused(call, answer, error):
    with client(answer) as c, pytest.raises(error): call(c)


def test_project_discovery_refuses_an_undocumented_page():
    from ophiolite.account import connect
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'projects': [{'id': 'p'}], 'next_cursor': None})))
    with connect('https://ophiolite.example', Credential.bearer('oph_api_alice'), http=http) as account, pytest.raises(Unavailable):
        account.projects()


OPERATIONS = (ROOT / 'packages/typescript/src/generated/operations.ts').read_text()


@pytest.mark.parametrize('function,fields', [
    ('postProjectsList', ('"projects"', '"next_cursor"')), ('postProjectsProjectEntitiesList', ('"entities"',)),
    ('postProjectsProjectEntitiesExtent', ('"bbox"', '"untransformed"')), ('postProjectsProjectChangesList', ('"changes"', '"has_more"')),
    ('postProjectsProjectWebhooksCreate', ('"secret"',)), ('postProjectsProjectAccessEffective', ('"members"',)),
    ('postOrganizationsDetail', ('"members"', '"role"')), ('postProjectsProjectStagesTransition', ('"stage"',))])
def test_the_generated_types_have_real_fields(function, fields):
    """generate_ts_client.meaningful() accepts weak schemas, so the emitted TypeScript is read directly."""
    match = re.search(r'export function %s\(transport: Transport, input: %sInput\): Promise<(.*)> \{' % (function, function), OPERATIONS)
    assert match, function
    returned = match.group(1)
    assert returned not in ('unknown', 'Record<string, unknown>') and all(f in returned or 'Wire' in returned for f in fields), (function, returned[:200])
    body = re.search(r'export type %sInput = \{ (.*) \};' % function, OPERATIONS).group(1)
    assert 'body: unknown' not in body and 'body: Record<string, unknown>' not in body, (function, body[:200])


def test_every_post_route_is_typed_both_ways():
    coverage = json.loads((ROOT / 'packages/typescript/operation-coverage.json').read_text())
    untyped = [c['operation'] for c in coverage if c['operation'].startswith('POST') and (c['request'] == 'explicitly-untyped' or c['response'] == 'explicitly-untyped')]
    assert untyped == ['POST /api/v1/connector/{operation}'], untyped  # the connector proxy carries the named operation's own body
