"""E78 C6: share a derived publication with everyone in the project from Python and the command line.

`project=None` takes the named-sharing path unchanged; an explicit True or False needs a server that reports the
project audience (refused before anything is sent otherwise) and is verified in the answer."""
import json

import anyio
import httpx
import pytest
from ophiolite import AsyncClient, Client, Credential
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.testing import synthetic_server

from test_cli_subprocess import gateway, run
from test_share import INFO

PUB = {'asset_id': 'pub', 'revision': 'r2', 'authority': 'ophiolite:derived'}
OWNER = {**INFO, 'project_audience': 'none'}


def server(info=OWNER, answer=lambda body: {**OWNER, 'grants_generation': 4, 'project_audience': body.get('project_audience', 'none')}, lost=0):
    """Answers the catalogue, publications/info and publications/share; records (route, body). `lost` answers drop first."""
    calls, state = [], {'lost': lost}
    def handle(request):
        route = request.url.path.split('/projects/p/', 1)[1]; body = json.loads(request.content or b'{}'); calls.append((route, body))
        if route == 'applications/result-list': return httpx.Response(200, json={'results': []})
        if route == 'publications/info': return httpx.Response(200, json=info)
        if route == 'publications/share':
            if state['lost']: state['lost'] -= 1; return httpx.Response(502, json={'error': 'lost'})
            return httpx.Response(200, json={**answer(body), 'sharing_contract': 'conditional'})
        return httpx.Response(404, json={})
    return calls, httpx.MockTransport(handle)


def shares(calls):
    return [{k: v for k, v in body.items() if k not in ('command_id', 'asset_id', 'project_id')} for route, body in calls if route == 'publications/share']


@pytest.mark.parametrize('project,sent', [(True, 'read'), (False, 'none')])
def test_sync_sends_the_literal_body_and_verifies_the_answer(project, sent):
    calls, transport = server()
    with httpx.Client(transport=transport) as http:
        after = Client('http://localhost', 'p', http=http).share(PUB, read=[], expected_generation=3, project=project)
    assert shares(calls) == [{'audience': [], 'reuse_audience': [], 'project_audience': sent, 'expected_generation': 3}]
    assert after.project is project and after.generation == 4


def test_none_sends_no_field_and_grants_report_it():
    calls, transport = server()
    with httpx.Client(transport=transport) as http:
        client = Client('http://localhost', 'p', http=http)
        assert client.grants(PUB).project is False
        client.share(PUB, read=['bob'], expected_generation=3)
    assert shares(calls) == [{'audience': ['bob'], 'reuse_audience': [], 'expected_generation': 3}]


@pytest.mark.parametrize('project', [True, False])
def test_a_server_that_does_not_report_it_refuses_both_before_sending(project):
    calls, transport = server(info=INFO)  # no project_audience: a server that predates E78
    with httpx.Client(transport=transport) as http:
        client = Client('http://localhost', 'p', http=http)
        assert client.grants(PUB).project is None
        with pytest.raises(Refused, match='does not support sharing with everyone'):
            client.share(PUB, read=[], expected_generation=3, project=project)
    assert shares(calls) == []


def test_an_answer_without_the_field_fails_verification():
    calls, transport = server(answer=lambda body: {k: v for k, v in OWNER.items() if k != 'project_audience'})
    with httpx.Client(transport=transport) as http:
        with pytest.raises(VerificationFailed, match='project audience'):
            Client('http://localhost', 'p', http=http).share(PUB, read=[], expected_generation=3, project=False)
    calls, transport = server(answer=lambda body: OWNER)  # the server kept 'none' after True was asked
    with httpx.Client(transport=transport) as http:
        with pytest.raises(VerificationFailed):
            Client('http://localhost', 'p', http=http).share(PUB, read=[], expected_generation=3, project=True)


def test_a_lost_answer_is_replayed_identically():
    calls, transport = server(lost=1)
    with httpx.Client(transport=transport) as http:
        after = Client('http://localhost', 'p', http=http).share(PUB, read=[], expected_generation=3, project=True, command_id='same')
    sent = [body for route, body in calls if route == 'publications/share']
    assert len(sent) == 2 and sent[0] == sent[1] and sent[0]['project_audience'] == 'read' and after.project is True


@pytest.mark.parametrize('bad', ['read', 1, 0])
def test_only_a_boolean_or_none(bad):
    calls, transport = server()
    with httpx.Client(transport=transport) as http:
        with pytest.raises(Refused, match='True, False or None'):
            Client('http://localhost', 'p', http=http).share(PUB, read=[], expected_generation=3, project=bad)
    assert calls == []


def test_a_result_or_original_is_shared_by_name():
    entry = {'asset_id': 'run', 'revision': 'x', 'can_share': True, 'recipients': [], 'reuse_recipients': [], 'grants_generation': 1, 'project_audience': 'none'}
    calls = []
    def handle(request):
        route = request.url.path.split('/projects/p/', 1)[1]; calls.append(route)
        return httpx.Response(200, json={'results': [entry]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(Refused, match='Only a derived publication'):
            Client('http://localhost', 'p', http=http).share({'asset_id': 'run', 'revision': 'x', 'authority': 'ophiolite:derived'}, read=[], expected_generation=1, project=True)
    assert 'applications/share' not in calls


def test_async_matches_sync():
    async def go():
        calls, transport = server()
        async with AsyncClient('http://localhost', 'p', http=httpx.AsyncClient(transport=transport)) as client:
            after = await client.share(PUB, read=[], expected_generation=3, project=True)
        return calls, after
    calls, after = anyio.run(go)
    assert shares(calls) == [{'audience': [], 'reuse_audience': [], 'project_audience': 'read', 'expected_generation': 3}] and after.project is True


def test_the_fixture_server_shares_with_the_project():
    with synthetic_server() as fake, Client(fake.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        asset = next(iter(alice.assets()))
        from ophiolite.writers import WrittenOriginal
        receipt = alice.publish_derived(WrittenOriginal(b'~V\nVERS. 2.0 :\n', 'las2/1', {}, 'derived.las'), name='Shared', from_=[(asset['asset_id'], asset['revision'])],
                                        method={'name': 'offset', 'parameters': {}}, command_id='c1')
        target = {'asset_id': receipt.asset_id, 'revision': receipt.revision, 'authority': 'ophiolite:publication'}
        before = alice.grants(target)
        assert before.project is False and fake.template_applications.readable(receipt.asset_id, 'bob') is None
        after = alice.share(target, read=[], expected_generation=before.generation, project=True)
        assert after.project is True and fake.template_applications.readable(receipt.asset_id, 'bob') is not None
        fake.template_applications.project_capable = False
        with pytest.raises(Refused): alice.share(target, read=[], expected_generation=after.generation, project=False)
        assert fake.template_mutations['publication-share'] == 1


def test_the_command_line(tmp_path):
    dry = run(tmp_path, 'share', '--asset', 'pub', '--project', '--dry-run', '--json')
    assert dry.returncode == 0 and json.loads(dry.stdout)['whole_project'] is True
    both = run(tmp_path, 'share', '--asset', 'pub', '--project', '--no-project', '--dry-run')
    assert both.returncode == 2 and 'not allowed with' in both.stderr
    sent = []
    def shared(body):
        sent.append(body); return 200, {**OWNER, 'grants_generation': 4, 'project_audience': body.get('project_audience', 'none'), 'sharing_contract': 'conditional'}
    with gateway({'/scientific-assets?limit=100&cursor=': (200, {'items': [PUB], 'next_cursor': None}), '/applications/result-list': (200, {'results': []}),
                  '/publications/info': (200, OWNER), '/publications/share': shared}) as fake:
        done = run(tmp_path, 'share', '--asset', 'pub', '--project', url=fake.url)
        quiet = run(tmp_path, 'share', '--asset', 'pub', '--read', 'bob', '--json', url=fake.url)
    assert done.returncode == 0, done.stderr
    assert 'also everyone in this project, including people who join later' in done.stdout
    assert [s.get('project_audience') for s in sent] == ['read', None]
    assert json.loads(quiet.stdout)['whole_project'] is False


def test_the_command_line_shares_a_result_by_name(tmp_path, monkeypatch, capsys):
    """A run result answers a ResultSummary, which carries no project field: the command line says nothing about
    the whole project and reports `whole_project` as null (the hosted gateway lane found an AttributeError here)."""
    from types import SimpleNamespace
    from ophiolite import cli
    class Stub:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def assets(self): return [{'asset_id': 'run', 'revision': 'x', 'authority': 'ophiolite:derived'}]
        def grants(self, item): return SimpleNamespace(generation=1)
        def share(self, item, **kw): return SimpleNamespace(recipients=kw['read'], reuse_recipients=[])
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': 'http://127.0.0.1:9', 'project': 'p'}))
    monkeypatch.setenv('HOME', str(tmp_path)); monkeypatch.chdir(tmp_path); monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice')
    monkeypatch.setattr(cli, 'Client', Stub)
    cli.main(['share', '--asset', 'run', '--read', 'bob', '--json'])
    assert json.loads(capsys.readouterr().out)['whole_project'] is None
    cli.main(['share', '--asset', 'run', '--read', 'bob'])
    assert 'everyone in this project' not in capsys.readouterr().out
