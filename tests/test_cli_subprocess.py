"""E31 S3: the command line as a process — stdout/stderr framing, the documented exit codes, --json shapes, and
--dry-run that sends nothing (a recording endpoint counts every request) and writes nothing (an isolated folder)."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from ophiolite.testing import fixture_server

ENVELOPE = {'error': 'Not a member of this project', 'code': 'PERMISSION_DENIED', 'message': 'Not a member of this project',
            'remedy': 'Use a credential whose scope, kind and project reach this operation, or ask a project administrator for access.',
            'docs': '/docs/reference/errors/#permission_denied', 'request_id': 'req_cli'}
SDK = str(Path(__file__).resolve().parents[1])


def run(tmp_path, *argv, url='http://127.0.0.1:9', key='oph_api_alice'):
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': url, 'project': 'p'}))
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('OPHIOLITE_')}, 'PYTHONPATH': SDK, 'PYTHONDONTWRITEBYTECODE': '1', 'HOME': str(tmp_path)}
    if key: env['OPHIOLITE_ACCESS_KEY'] = key
    return subprocess.run([sys.executable, '-m', 'ophiolite', *argv], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)


def gateway(routes):
    """A recording endpoint answering the named operations; anything else is a 404 envelope."""
    def handler(method, path, raw, headers):
        for suffix, answer in routes.items():
            if path.endswith(suffix): return answer(json.loads(raw or b'{}')) if callable(answer) else answer
        return 404, {**ENVELOPE, 'code': 'NOT_FOUND', 'message': 'Unknown', 'error': 'Unknown'}
    return fixture_server(handler)


def test_usage_errors_exit_2(tmp_path):
    done = run(tmp_path, 'wells', 'sideways')
    assert done.returncode == 2 and 'invalid choice' in done.stderr and done.stdout == ''


def test_journey_verbs_print_their_documented_json(tmp_path):
    well = {'entity_id': 'well-1', 'kind': 'well', 'name': 'W1', 'identity': {'authority': 'nlog', 'key': 'W1', 'provisional': False}, 'owner': 'alice',
            'generation': 1, 'parts': [], 'location': {'x': 5.1, 'y': 52.1, 'crs': 'OGC:CRS84', 'source': {'asset_id': 'a', 'revision': 'r', 'profile': 'well-location/1'}}}
    routes = {'/entities/list': (200, {'entities': [well], 'next_cursor': None, 'untransformed': 0}),
              '/entities/extent': (200, {'crs': 'OGC:CRS84', 'bbox': [5.1, 52.1, 5.1, 52.1], 'count': 1, 'untransformed': 0}),
              '/changes/head': (200, {'epoch': 'e1', 'cursor': 3}),
              '/changes/list': (200, {'epoch': 'e1', 'changes': [{'project': 'p', 'cursor': 4, 'epoch': 'e1', 'kind': 'asset-shared', 'subject_kind': 'asset', 'subject_id': 'a',
                                                               'generation': 2, 'revision': None, 'actor_kind': 'person', 'actor': 'alice', 'at': 1.0}], 'cursor': 4, 'has_more': False}),
              '/projects/list': (200, {'projects': [{'id': 'p', 'name': 'Pilot', 'role': 'member', 'can_administer': True, 'organization_id': None}], 'next_cursor': None})}
    with gateway(routes) as server:
        wells = json.loads(run(tmp_path, 'wells', 'list', '--crs', 'OGC:CRS84', '--json', url=server.url).stdout)
        extent = json.loads(run(tmp_path, 'wells', 'extent', '--json', url=server.url).stdout)
        changes = json.loads(run(tmp_path, 'changes', 'list', '--json', url=server.url).stdout)
        projects = run(tmp_path, 'projects', '--url', server.url, '--json', url=server.url)
    assert wells == {'wells': [{'entity_id': 'well-1', 'name': 'W1', 'location': well['location']}], 'crs': 'OGC:CRS84', 'untransformed': 0}
    assert extent['extent']['count'] == 1 and changes['changes'][0]['kind'] == 'asset-shared'
    assert projects.returncode == 0 and json.loads(projects.stdout)['projects'][0]['id'] == 'p'


def test_changes_follow_prints_one_json_event_per_line(tmp_path):
    page = {'epoch': 'e1', 'changes': [{'project': 'p', 'cursor': c, 'epoch': 'e1', 'kind': 'asset-changed', 'subject_kind': 'asset', 'subject_id': 'a%d' % c,
                                        'generation': 1, 'revision': 'r', 'actor_kind': 'person', 'actor': 'alice', 'at': 1.0} for c in (4, 5)], 'cursor': 5, 'has_more': False}
    frames = ('event: change\nid: e1:5\ndata: %s\n\n' % json.dumps(page)).encode()
    with gateway({'/changes/stream': (200, frames)}) as server:
        done = run(tmp_path, 'changes', 'follow', '--epoch', 'e1', '--after', '3', '--json', url=server.url)
    lines = done.stdout.splitlines()
    assert done.returncode == 0 and [json.loads(l)['cursor'] for l in lines] == [4, 5]


@pytest.mark.parametrize('status,code', [(403, 3), (401, 3), (404, 4), (409, 4), (400, 1), (503, 5)])
def test_refusals_exit_with_their_documented_code(tmp_path, status, code):
    envelope = {**ENVELOPE, 'code': {403: 'PERMISSION_DENIED', 401: 'UNAUTHENTICATED', 404: 'NOT_FOUND', 409: 'CONFLICT', 400: 'INVALID_ARGUMENT', 503: 'busy'}[status]}
    with gateway({'/entities/extent': (status, envelope)}) as server:
        human = run(tmp_path, 'wells', 'extent', url=server.url)
        machine = run(tmp_path, 'wells', 'extent', '--json', url=server.url)
    assert human.returncode == machine.returncode == code, (human.stderr, machine.stdout)
    assert human.stdout == '' and human.stderr.strip()
    error = json.loads(machine.stdout)['error']
    assert error['status'] == status and error['request_id'] == 'req_cli' and error['code'] == envelope['code']


def test_dry_run_sends_nothing_and_writes_nothing(tmp_path):
    (tmp_path / 'result.las').write_bytes(b'~V\nVERS. 2.0 :\n')
    with gateway({}) as server:
        run(tmp_path, 'skills', 'path')  # writes the configuration the calls below read (the helper's own file)
        before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))
        derive = run(tmp_path, 'publish-derived', 'result.las', '--profile', 'las2/1', '--name', 'Derived', '--from', 'a:' + 'f' * 64, '--method', 'offset',
                     '--work', 'work', '--dry-run', '--json', url=server.url, key=None)
        share = run(tmp_path, 'share', '--asset', 'a', '--read', 'bob', '--dry-run', '--json', url=server.url, key=None)
        requests = list(server.requests)
    assert derive.returncode == 0 and share.returncode == 0, (derive.stderr, share.stderr)
    plan = json.loads(derive.stdout)
    assert plan['dry_run'] is True and plan['operation'] == 'publications/derive' and plan['header']['name'] == 'Derived'
    assert json.loads(share.stdout)['read'] == ['bob']
    assert requests == [] and sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*')) == before  # no work folder, no credential file


def test_an_unreachable_server_exits_5(tmp_path):
    done = run(tmp_path, 'wells', 'extent', '--json', url='http://127.0.0.1:9')
    assert done.returncode == 5 and json.loads(done.stdout)['error']['code'] in ('unreachable', 'outcome-unknown')  # the transport's own words for no answer
