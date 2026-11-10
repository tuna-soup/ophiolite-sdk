"""E162 s1 C4 (D8, K9): every route the demo does not serve answers as the gateway answers it. Each command of the
frozen list runs through cli.entrypoint against the in-process gateway (alice, a member with read access only) and
against the demo serving a bundle in the same project, each through a recording transport: the routes reached are the
frozen ones, HTTP status and envelope are equal (the error's request_id aside), and so are the CLI's words and exit."""
import json
import re
import sys
from pathlib import Path
import httpx
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite import Client, cli, testing
from ophiolite.testing import BundleApplications, FixtureServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_demo_bundle_server import DESCENDING, Log, demo_bundle, typed  # noqa: E402

ORIGIN = 'https://workspace.example'
READER = {'Authorization': 'Bearer oph_api_alice:read'}
ROWS = dict(testing.DEMO_ANSWERS)
# the members of the capabilities answer a CLI reads; operations, profiles, readers and mcp say what each one serves
DESCRIBED = ('schema', 'project_id', 'principal', 'note', 'limits', 'upload_runs')
# (command, its argv, the routes it reaches in order); {las}, {table}, {asset} and {revision} are filled per run
FROZEN = [
    ('exchange upload', ['exchange', 'upload', '{las}', '--attribution', 'Synthetic', '--audience', 'me', '--rights-confirmed'],
     [('POST', 'capabilities/describe'), ('POST', 'upload-runs/list'), ('POST', 'upload-runs/start')]),
    ('exchange import table', ['exchange', 'import', 'table', '{table}', '--target', 'wells'], [('POST', 'table-imports/read')]),
    ('account share', ['account', 'share', '--asset', '{asset}', '--read', 'bob'], [('GET', 'scientific-assets')]),
    ('results withdraw', ['results', 'withdraw', '@{asset}:{revision}', '--reason', 'demo'], [('POST', 'catalog/inventory')]),
    ('data wells from-run', ['data', 'wells', 'from-run', 'run-1', '--create-all'], [('POST', 'well-names/propose')]),
]


class Recording(httpx.BaseTransport):
    def __init__(self, inner): self.inner, self.seen = inner, []

    def handle_request(self, request):
        response = self.inner.handle_request(request); body = response.read()
        self.seen.append((request.method, request.url.path.removeprefix('/api/v1/projects/p/'), response.status_code, body))
        return httpx.Response(response.status_code, headers=response.headers, content=body, request=request)


@pytest.fixture
def demo(web, tmp_path):
    """The demo serving a bundle in project p whose first log carries the asset id of the gateway's first asset, so
    `account share --asset` names one asset that both catalogues list."""
    asset = web.c.get('/api/v1/projects/p/scientific-assets', headers=READER).json()['items'][0]['asset_id']
    applications = BundleApplications(demo_bundle(tmp_path, [Log(asset, 'SYN-A', DESCENDING, project='p'), typed('tops', project='p')]))
    with FixtureServer(applications) as server:
        yield server, applications


def run(tmp_path, monkeypatch, capsys, url, transport, argv):
    cli._load()
    configuration = tmp_path / ('configuration-%s.json' % ('demo' if url != ORIGIN else 'gateway'))
    configuration.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': url, 'project': 'p'}))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', READER['Authorization'].removeprefix('Bearer '))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(cli, 'Client', lambda u, project, credential: Client(u, project, credential, httpx.Client(transport=transport, base_url=u)))
    capsys.readouterr()
    try: cli.entrypoint([*argv, '--configuration', str(configuration)])
    except SystemExit as stop: code = stop.code
    else: code = 0
    said = capsys.readouterr()
    return code, said.out, said.err


def both(web, demo, tmp_path, monkeypatch, capsys, argv):
    server, applications = demo
    first = applications.served[0]
    las = tmp_path / 'f.las'; las.write_bytes(first['files'][first['entry']['revision']])
    table = tmp_path / 'wells.csv'; table.write_text('name,x,y\nA,1,2\n')
    argv = [a.format(las=las, table=table, asset=first['entry']['asset_id'], revision=first['entry']['revision']) for a in argv]
    gateway, local = Recording(web.c._transport), Recording(httpx.HTTPTransport())
    return (run(tmp_path, monkeypatch, capsys, ORIGIN, gateway, argv), gateway.seen,
            run(tmp_path, monkeypatch, capsys, server.url, local, argv), local.seen)


def envelope(route, status, body):
    """What is compared of one answer: an error's envelope without its request_id, the CLI-read members of the
    capabilities answer, a catalogue's status only (each serves its own assets), any other body whole."""
    value = json.loads(body)
    if status >= 400:
        assert re.fullmatch(r'req_[0-9a-f]{24}', value.pop('request_id')), body
        return value
    if route == 'capabilities/describe': return {k: value[k] for k in DESCRIBED}
    return None if route == 'scientific-assets' else value


@pytest.mark.parametrize('name,argv,routes', FROZEN, ids=[f[0] for f in FROZEN])
def test_each_frozen_refusal_answers_as_the_gateway(web, demo, tmp_path, monkeypatch, capsys, name, argv, routes):
    said, gateway, said_demo, local = both(web, demo, tmp_path, monkeypatch, capsys, argv)
    assert [(m, r) for m, r, _, _ in gateway] == routes  # the frozen route, reached by the real gateway
    assert [(m, r) for m, r, _, _ in local] == routes
    for (_, route, status, body), (_, _, status_demo, body_demo) in zip(gateway, local):
        assert status_demo == status, route
        assert envelope(route, status_demo, body_demo) == envelope(route, status, body), route
    assert said_demo == said and said[0] != 0
    refused = routes[-1]
    if refused[0] == 'POST': assert demo[1].reached[-1] == (refused[0], '/api/v1/projects/p/' + refused[1])  # the handler logged it


def test_an_unknown_operation_answers_the_gateways_generic_refusal(web, demo):
    server, _ = demo
    for path in ('/api/v1/projects/p/catalog/nothing', '/api/v1/projects/p/applications/nothing'):
        answer = web.c.post(path, json={}, headers=READER)
        local = httpx.post(server.url + path, json={}, headers=READER, trust_env=False)
        assert local.status_code == answer.status_code == 404
        assert envelope(path, 404, local.content) == envelope(path, 404, answer.content) == {
            'error': 'Unknown operation', 'code': 'NOT_FOUND', 'message': 'Unknown operation',
            'remedy': 'Check the project, operation and identifiers; list them again to find current ones.', 'docs': '/docs/reference/errors/#not_found'}


def test_a_removed_row_or_a_changed_sentence_makes_that_command_differ(web, demo, tmp_path, monkeypatch, capsys):
    _, argv, _ = FROZEN[1]
    said, _, said_demo, _ = both(web, demo, tmp_path, monkeypatch, capsys, argv)
    assert said_demo == said == (3, '', 'Only contributors can add this. Ask the project owner for access.\n')
    rows = dict(ROWS); del rows[('POST', 'table-imports/read')]
    monkeypatch.setattr(testing, 'DEMO_ANSWERS', rows)
    said, _, said_demo, local = both(web, demo, tmp_path, monkeypatch, capsys, argv)
    assert said_demo != said and local[-1][2] == 404  # the generic answer instead of the refusal
    _, argv, _ = FROZEN[4]  # (never monkeypatch.undo(): it would undo the gateway fixtures' own patches too)
    rows = dict(ROWS); status, body = rows[('POST', 'well-names/propose')]
    rows[('POST', 'well-names/propose')] = (status, {**body, 'error': 'This upload is unknown.', 'message': 'This upload is unknown.'})
    monkeypatch.setattr(testing, 'DEMO_ANSWERS', rows)
    said, _, said_demo, _ = both(web, demo, tmp_path, monkeypatch, capsys, argv)
    assert said[0] == said_demo[0] == 4 and said_demo[2] == 'This upload is unknown.\n' != said[2]
