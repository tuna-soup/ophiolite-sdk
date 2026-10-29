"""E60 C6: `ophiolite repositories search|bring-in|check` print with --json exactly what client.public_repositories answers
(the same words), and a refusal exits with its sentence. Against a recorded deployment (fixture_server), offline."""
import base64
import json

import pytest
from ophiolite import Client, Credential, cli
from ophiolite.errors import Refused
from ophiolite.public_repositories import RepositoryNotEnabled
from ophiolite.testing import fixture_server

ROWS = [{'code': c, 'name': c, 'field': 'Honselersdijk', 'operator': 'Example Geothermie', 'public_since': '2020-01-01', 'side': 'ON',
         'in_project': False, 'well': None} for c in ('HON-GT-01', 'HON-GT-01-S1', 'HON-GT-01-S2', 'HON-GT-02')]
CHECK = {'service': 'nlog', 'checked_at': 1760000000.0, 'sentence': '1 document changed at NLOG since 12 October. Review changes',
         'files': [{'code': 'HON-GT-02', 'name': 'tops.json', 'kind': 'tops', 'asset_id': 'a1', 'revision': '0' * 64, 'state': 'needs-review', 'changed': ['meaning']}]}
COUNTS = dict(waiting=0, reading=0, added=0, already_here=0, needs_decision=0, not_read=0, not_supported=0, cancelled=0)


def item(state):
    return {'ordinal': 0, 'path': 'HON-GT-02/tops.csv', 'bytes': 10, 'sha256': '1' * 64, 'role': 'primary', 'state': state, 'kind': 'Well tops (CSV)'}


def run(state, file_state):
    return {'run_id': 'r1', 'project_id': 'p', 'folder_name': 'NLOG: 1 borehole', 'state': state, 'label': 'Finished' if state == 'closed' else 'Adding',
            'files': 1, 'counts': {**COUNTS, file_state.replace('-', '_'): 1}, 'items': [item(file_state)]}


class Deployment:
    """public-repositories and upload-runs as a deployment answers them; ENABLED False answers NLOG's refusal."""

    def __init__(self, enabled=True):
        self.enabled, self.sent, self.files = enabled, [], 0

    def __call__(self, method, path, raw, headers):
        operation = path.rsplit('/', 1)[-1]
        if path.endswith('/upload-runs/file'):
            header = json.loads(base64.b64decode({k.lower(): v for k, v in headers.items()}['x-ophiolite-upload']))
            assert header['repository'] is True and raw == b''  # the gateway reads the file from the service; nothing is sent
            self.files += 1
            return 200, json.dumps({'run_id': 'r1', 'step': 'done', 'file': item('added')}).encode()
        body = json.loads(raw)
        self.sent.append((operation, body))
        if path.endswith('/upload-runs/status'):
            return 200, json.dumps(run('closed', 'added') if self.files else run('open', 'waiting')).encode()
        if not self.enabled:
            return 403, json.dumps({'code': 'PERMISSION_DENIED', 'message': 'This public repository is not enabled on this deployment.'}).encode()
        if operation == 'search': return 200, json.dumps({'service': 'nlog', 'items': ROWS}).encode()
        if operation == 'check': return 200, json.dumps(CHECK).encode()
        if operation == 'import': return 200, json.dumps({'run': run('open', 'waiting'), 'not_read': []}).encode()
        return 404, b'{}'


def command(tmp_path, monkeypatch, server, argv):
    config = tmp_path / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
    monkeypatch.delenv('OPHIOLITE_ACCESS_KEY', raising=False)
    monkeypatch.setattr(Credential, 'from_file', lambda path: Credential.bearer('oph_api_alice'))
    return cli.main(['repositories', *argv, '--configuration', str(config), '--credentials', str(tmp_path / 'saved.json')])


def python(server):
    return Client(server.url, 'p', Credential.bearer('oph_api_alice')).public_repositories


def test_search_and_check_print_the_python_answer(tmp_path, monkeypatch, capsys):
    with fixture_server(Deployment()) as server:
        command(tmp_path, monkeypatch, server, ['search', 'nlog', '--name', 'HON-GT', '--json'])
        printed = json.loads(capsys.readouterr().out)
        assert printed == {'service': 'nlog', 'items': python(server).search('nlog', name='HON-GT')}
        assert [r['code'] for r in printed['items']] == ['HON-GT-01', 'HON-GT-01-S1', 'HON-GT-01-S2', 'HON-GT-02']
        command(tmp_path, monkeypatch, server, ['check', 'nlog', '--json'])
        assert json.loads(capsys.readouterr().out) == python(server).check('nlog')
        command(tmp_path, monkeypatch, server, ['search', 'nlog', '--name', 'HON-GT'])
        assert capsys.readouterr().out.splitlines()[0] == '4 wells found'
        command(tmp_path, monkeypatch, server, ['check', 'nlog'])
        assert capsys.readouterr().out.splitlines() == ['1 document changed at NLOG since 12 October. Review changes', '  HON-GT-02/tops.json: needs-review (meaning)']


def test_bring_in_sends_the_chosen_kinds_and_prints_the_report(tmp_path, monkeypatch, capsys):
    deployment = Deployment()
    with fixture_server(deployment) as server:
        report = command(tmp_path, monkeypatch, server, ['bring-in', 'nlog', 'HON-GT-02', '--include', 'tops', '--audience', 'bob', '--json'])
        printed = json.loads(capsys.readouterr().out)
        assert printed == report.to_dict() and printed['upload']['state'] == 'closed' and printed['not_read'] == []
        [(_, body)] = [s for s in deployment.sent if s[0] == 'import']
        assert (body['codes'], body['include'], body['audience']) == (['HON-GT-02'], ['tops'], ['bob'])
        assert deployment.files == 1 and report.ok and report.exit_code == 0


def test_a_refusal_exits_with_the_journey_sentence(tmp_path, monkeypatch, capsys):
    with fixture_server(Deployment(enabled=False)) as server:
        with pytest.raises(RepositoryNotEnabled) as refused:
            command(tmp_path, monkeypatch, server, ['search', 'nlog', '--name', 'HON-GT'])
        assert cli.exit_code(refused.value) == cli.EXIT['access']
        assert str(refused.value) == 'NLOG is not switched on for this Ophiolite installation. Ask the person who runs it to allow NLOG.'
        with pytest.raises(RepositoryNotEnabled): python(server).search('nlog', name='HON-GT')


def test_only_search_takes_the_search_options(tmp_path, monkeypatch, capsys):
    with fixture_server(Deployment()) as server:
        with pytest.raises(Refused, match='Only search takes --name, --field or --side.'):
            command(tmp_path, monkeypatch, server, ['check', 'nlog', '--name', 'HON-GT'])
