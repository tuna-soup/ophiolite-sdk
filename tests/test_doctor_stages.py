"""E51a C5: doctor --online reports six stages (address, tls, credential-arrived, credential-accepted, project-readable,
features), stopping at the first failure with the server's sentence, its stage and remedy. One local fixture fails
exactly at each stage. The credential is sent only to the configured origin and never appears in any output."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ophiolite import cli, doctor, Credential
from ophiolite.errors import AuthenticationRequired, PermissionRefused
from ophiolite.application_transport import envelope, carried

KEY = 'oph_key_DOCTORDOCTORDOCTORDOCTORDOCTORDOCTORDOCTORDOCTORDOC'
STAGES = ['address', 'tls', 'credential-arrived', 'credential-accepted', 'project-readable', 'features']


def refusal(status, code, message, stage, remedy='Do the next thing.'):
    return status, {'error': message, 'code': code, 'message': message, 'stage': stage, 'remedy': remedy, 'docs': '/docs/reference/errors/#stage-' + stage, 'request_id': 'req_1'}


class Gateway:
    """A loopback stand-in for the gateway: routes -> (status, body or callable); records every request's headers."""
    def __init__(self, routes=None):
        self.seen, self.routes = [], {
            '/api/v1/contracts': (200, {'version': '1.30.0'}),
            '/api/v1/projects/list': (200, {'projects': [{'id': 'p', 'name': 'P', 'role': 'viewer', 'can_administer': False, 'organization_id': None}], 'next_cursor': None}),
            '/api/v1/projects/p/features': (200, {'title': 'P', 'links': []}),
            '/api/v1/projects/p/capabilities/describe': (200, {'scopes': ['read']}),
            '/api/v1/projects/p/features/collections': (200, {'collections': [{'id': 'wells', 'title': 'Wells'}]}),
            '/api/v1/projects/p/features/collections/wells/items': (200, {'type': 'FeatureCollection', 'features': [{'id': 'w1'}, {'id': 'w2'}], 'numberReturned': 2, 'numberMatched': 206}),
            **(routes or {})}
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def answer(self):
                length = int(self.headers.get('Content-Length') or 0)
                if length: self.rfile.read(length)
                path = self.path.split('?')[0]
                gateway.seen.append({'method': self.command, 'path': self.path, 'authorization': self.headers.get('Authorization')})
                status, body = gateway.routes.get(path, (404, {'code': 'NOT_FOUND', 'message': 'Unknown', 'error': 'Unknown'}))
                if callable(body): return body(self)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            do_GET = do_POST = answer
            def log_message(self, *a): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self): self.server.shutdown(); self.server.server_close()


@pytest.fixture
def gateway():
    made = []
    def make(routes=None):
        g = Gateway(routes); made.append(g); return g
    yield make
    for g in made: g.close()


def run(url, key=KEY, notes=(), project='p'):
    return doctor.run(url, project, Credential.bearer(key) if key else None, notes=notes)


def ids(report): return [(s['stage'], s['ok']) for s in report['stages']]


def test_all_six_stages_pass_and_the_count_is_number_matched(gateway):
    g = gateway(); report = run(g.url)
    assert ids(report) == [(s, True) for s in STAGES] and report.exit_code == 0
    assert report['stages'][-1]['detail'] == '206 wells' and report['scope'] == ['read']
    assert report['expires'] == 'not available for a key given directly'
    assert all(r['authorization'] == 'Bearer ' + KEY for r in g.seen if r['path'] != '/api/v1/contracts')
    items = [r for r in g.seen if 'items' in r['path']]
    assert len(items) == 1 and 'limit=100' in items[0]['path']  # one first page, never a next link


def test_without_number_matched_the_count_is_at_least(gateway):
    g = gateway({'/api/v1/projects/p/features/collections/wells/items': (200, {'type': 'FeatureCollection', 'features': [{'id': 'w1'}] * 100, 'numberReturned': 100,
                                                                              'links': [{'rel': 'next', 'href': '/api/v1/projects/p/features/collections/wells/items?cursor=x'}]})})
    report = run(g.url)
    assert report['stages'][-1]['detail'] == 'at least 100 wells' and not any('cursor' in r['path'] for r in g.seen)


def test_zero_wells_is_a_warning_not_a_failure(gateway):
    g = gateway({'/api/v1/projects/p/features/collections/wells/items': (200, {'type': 'FeatureCollection', 'features': [], 'numberReturned': 0, 'numberMatched': 0})})
    report = run(g.url)
    assert ids(report)[-1] == ('features', True) and report['stages'][-1].get('warning') and report.exit_code == 0


@pytest.mark.parametrize('failing,routes,exit_code,sentence', [
    ('credential-arrived', {'/api/v1/projects/list': refusal(401, 'UNAUTHENTICATED', "No credential reached Ophiolite; check the application's authentication settings.", 'no-credential')}, 3,
     "No credential reached Ophiolite"),
    ('credential-arrived', {'/api/v1/projects/list': refusal(403, 'PERMISSION_DENIED', 'The Authorization header is not a bearer credential of a kind Ophiolite accepts.', 'malformed-credential')}, 3,
     'not a bearer credential'),
    ('credential-accepted', {'/api/v1/projects/list': refusal(403, 'PERMISSION_DENIED', 'Project access key revoked or expired', 'credential-refused')}, 3, 'revoked or expired'),
    ('project-readable', {'/api/v1/projects/list': (200, {'projects': [{'id': 'other', 'name': 'O', 'role': 'viewer', 'can_administer': False, 'organization_id': None}], 'next_cursor': None})}, 3,
     'does not reach p'),
    ('project-readable', {'/api/v1/projects/p/features': refusal(403, 'PERMISSION_DENIED', 'Project access key scope denied', 'access-denied')}, 3, 'scope denied'),
    ('features', {'/api/v1/projects/p/features/collections': (200, {'collections': []})}, 4, 'no wells collection'),
    ('features', {'/api/v1/projects/p/features/collections/wells/items': (200, b'{not json')}, 4, 'not JSON'),
])
def test_each_stage_fails_alone_and_stops_the_report(gateway, failing, routes, exit_code, sentence):
    g = gateway(routes); report = run(g.url)
    position = STAGES.index(failing)
    assert ids(report) == [(s, True) for s in STAGES[:position]] + [(failing, False)], ids(report)
    assert report.exit_code == exit_code and sentence in report['stages'][-1]['detail']
    refused = [body for status, body in routes.values() if isinstance(body, dict) and 'stage' in body]
    if refused:  # the server's sentence, its stage and its remedy are reported as given
        last = report['stages'][-1]
        assert (last['server_stage'], last['remedy']) == (refused[0]['stage'], 'Do the next thing.')


def test_no_credential_given_stops_at_credential_arrived_without_sending_one(gateway):
    g = gateway(); report = run(g.url, key=None)
    assert ids(report) == [('address', True), ('tls', True), ('credential-arrived', False)] and report.exit_code == 3
    assert [r['path'] for r in g.seen] == ['/api/v1/contracts']


def test_an_address_that_does_not_resolve_fails_first(monkeypatch):
    def nowhere(*a, **k): raise socket.gaierror('no')
    monkeypatch.setattr(doctor.socket, 'getaddrinfo', nowhere)
    report = run('https://ophiolite.example.ts.net')
    assert ids(report) == [('address', False)] and report.exit_code == 5
    assert 'check Tailscale' in report['stages'][0]['detail']


def test_a_closed_port_fails_at_tls_and_a_private_address_says_tailscale(monkeypatch):
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    report = run('http://127.0.0.1:%d' % port)
    assert ids(report) == [('address', True), ('tls', False)] and 'cannot reach the server' in report['stages'][-1]['detail']
    monkeypatch.setattr(doctor, 'private', lambda host: True)
    assert 'check Tailscale' in run('http://127.0.0.1:%d' % port)['stages'][-1]['detail']


def test_an_untrusted_certificate_fails_tls(tmp_path):
    import ssl, subprocess
    cert, key = tmp_path / 'c.pem', tmp_path / 'k.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    g = Gateway(); context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
    g.server.socket = context.wrap_socket(g.server.socket, server_side=True)
    try:
        report = run('https://localhost:%d' % g.server.server_address[1])
        assert ids(report) == [('address', True), ('tls', False)] and 'certificate' in report['stages'][-1]['detail']
    finally: g.close()


def test_a_redirect_elsewhere_fails_and_the_credential_is_not_sent_there(gateway):
    other = gateway()
    def redirect(handler):
        handler.send_response(302); handler.send_header('Location', other.url + '/api/v1/projects/p/features'); handler.send_header('Content-Length', '0'); handler.end_headers()
    g = gateway({'/api/v1/projects/p/features': (302, redirect)})
    report = run(g.url)
    assert ids(report)[-1] == ('project-readable', False) and 'redirected' in report['stages'][-1]['detail']
    assert other.seen == []  # never followed: the credential went nowhere else


def test_a_timeout_fails_its_stage(gateway, monkeypatch):
    import time
    def slow(handler): time.sleep(1.5); handler.send_response(200); handler.send_header('Content-Length', '2'); handler.end_headers(); handler.wfile.write(b'{}')
    monkeypatch.setattr(doctor, 'TIMEOUT', 0.5)
    g = gateway({'/api/v1/projects/p/features/collections': (200, slow)})
    report = run(g.url)
    assert ids(report)[-1] == ('features', False) and 'did not answer' in report['stages'][-1]['detail']


def test_a_spoiled_key_reaches_all_six_stages_and_the_report_says_what_was_removed(gateway, tmp_path, capsys):
    g = gateway()
    config = tmp_path / 'configuration.json'; config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': g.url, 'project': 'p'}))
    key_file = tmp_path / 'key.txt'; key_file.write_text('Bearer ' + KEY + '\r\n')
    report = cli.main(['doctor', '--online', '--url', g.url, '--project', 'p', '--key-file', str(key_file), '--json'])
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert [(s['stage'], s['ok']) for s in payload['stages']] == [(s, True) for s in STAGES]
    assert payload['normalised'] == ['line-break', 'bearer-prefix'] and report.exit_code == 0
    assert KEY not in out.out + out.err
    cli.main(['doctor', '--online', '--url', g.url, '--project', 'p', '--key-file', str(key_file)])
    out = capsys.readouterr()
    assert "the application's field needs the corrected value" in out.out and 'Stage features: ok - 206 wells' in out.out and KEY not in out.out + out.err


def test_the_entrypoint_exits_with_the_failed_stage_code(gateway, tmp_path):
    g = gateway({'/api/v1/projects/list': refusal(403, 'PERMISSION_DENIED', 'Project access key revoked or expired', 'credential-refused')})
    key_file = tmp_path / 'key.txt'; key_file.write_text(KEY)
    with pytest.raises(SystemExit) as stopped: cli.entrypoint(['doctor', '--online', '--url', g.url, '--project', 'p', '--key-file', str(key_file)])
    assert stopped.value.code == 3


def test_sdk_categories_and_the_carried_stage(gateway):
    """The SDK maps 401 to AuthenticationRequired and 403 to PermissionRefused (unchanged); the server's sentence and stage ride along."""
    import httpx
    from ophiolite.account import Account
    for status, kind, stage in ((401, AuthenticationRequired, 'no-credential'), (403, PermissionRefused, 'credential-refused'), (403, PermissionRefused, 'access-denied')):
        g = gateway({'/api/v1/projects/list': refusal(status, 'X', 'Server sentence', stage)})
        with Account(g.url, Credential.bearer(KEY)) as account, pytest.raises(kind) as refused: account.projects()
        assert (refused.value.stage, refused.value.server_message) == (stage, 'Server sentence')
    response = httpx.Response(403, json={'code': 'PERMISSION_DENIED', 'message': 'm', 'stage': 'Not A Stage!', 'remedy': 'r'})
    assert carried(envelope(response))['stage'] is None  # only a well-formed stage is kept
