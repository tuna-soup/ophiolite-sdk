"""E33: the colleagues' sign-in server. Every response it sends the browser is collected and searched for the
provider tokens, the consent handle and the opaque Ophiolite credential: none may appear, in any header, redirect,
cookie or body."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import httpx
from ophiolite.oauth_app import FileStore, OAuthApp

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('template_sign_in', ROOT / 'server/sign_in.py'); sign_in = importlib.util.module_from_spec(spec); spec.loader.exec_module(sign_in)
ORIGIN, URL, ISSUER = 'https://maps.example', 'https://workspace.example', 'https://id.example/realms/ophiolite'
SECRETS = ('provider-', 'refresh-', 'handle-', 'oph_app_')


class World:
    def __init__(self): self.codes, self.handles = {}, {'handle-alice'}
    def __call__(self, request):
        if request.url.path == '/.well-known/oauth-authorization-server':
            return httpx.Response(200, json={'issuer': ISSUER, 'authorization_endpoint': ISSUER + '/auth', 'token_endpoint': ISSUER + '/token'})
        if request.url.path == '/realms/ophiolite/token':
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            held = self.codes.pop(form.get('code'), None)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get('code_verifier', '').encode()).digest()).rstrip(b'=').decode()
            if held is None or held[0] != challenge: return httpx.Response(400, json={'error': 'invalid_grant'})
            claims = base64.urlsafe_b64encode(json.dumps({'sub': 'alice', 'nonce': held[1]}).encode()).rstrip(b'=').decode()
            return httpx.Response(200, json={'access_token': 'provider-1', 'refresh_token': 'refresh-1', 'expires_in': 300, 'id_token': 'e30.' + claims + '.'})
        if request.url.path == '/api/v1/applications/exchange':
            if json.loads(request.content)['consent'] not in self.handles: return httpx.Response(403, json={})
            return httpx.Response(200, json={'access_token': 'oph_app_secret-credential', 'expires_in': 300})
        return httpx.Response(404, json={})


class Wells:
    def __init__(self, seen): self.seen = seen
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def wells(self, crs): return type('W', (), {'to_geojson': lambda s: {'type': 'FeatureCollection', 'features': []}})()


def test_no_secret_reaches_the_browser_and_a_removed_approval_signs_out(tmp_path):
    world = World()
    app = OAuthApp(URL, 'app_1', 'client-1', ORIGIN + '/callback', store=FileStore(tmp_path / 'people'), client_secret='client-secret',
                   http=httpx.Client(transport=httpx.MockTransport(world)))
    seen = []
    app.client = lambda person, project: (seen.append(app.credential(person)), Wells(seen))[1]
    server = sign_in.SignIn(app, ORIGIN, 'p')
    sent = []
    def call(method, path, query=None, headers=None):
        answer = server.handle(method, path, query or {}, {'cookie': cookie, **(headers or {})})
        sent.append(answer)
        return answer
    cookie = ''
    status, headers, _ = call('GET', '/sign-in')
    cookie = headers['Set-Cookie'].split(';')[0]
    provider = parse_qs(urlsplit(headers['Location']).query)
    assert status == 302 and headers['Location'].startswith(ISSUER + '/auth?') and provider['code_challenge_method'] == ['S256']
    world.codes['code-1'] = (provider['code_challenge'][0], provider['nonce'][0])
    status, headers, _ = call('GET', '/callback', {'code': 'code-1', 'state': provider['state'][0]})
    consent = parse_qs(urlsplit(headers['Location']).query)
    assert headers['Location'].startswith(URL + '/application-access/authorize?') and consent['application'] == ['app_1']
    status, headers, _ = call('GET', '/callback', {'consent': 'handle-alice', 'state': consent['state'][0]})
    assert (status, headers['Location']) == (302, '/')
    own = {'origin': ORIGIN, 'x-requested-with': 'map'}
    assert call('POST', '/api/wells', headers={'origin': 'https://evil.example', 'x-requested-with': 'map'})[0] == 403
    assert call('POST', '/api/wells', headers=own)[0] == 200 and seen == ['oph_app_secret-credential']  # used on the server
    world.handles.clear()  # the person removed the application in Workspace
    app.store.put('alice', {**app.store.get('alice'), 'credential': {'value': 'oph_app_secret-credential', 'expires_at': 0}})
    status, _, body = call('POST', '/api/wells', headers=own)
    assert status == 401 and json.loads(body)['sign_in'] == '/sign-in'
    assert call('POST', '/sign-out', headers=own)[0] == 200 and app.store.get('alice') is None
    wire = json.dumps([[s, h, b.decode()] for s, h, b in sent])
    assert not [s for s in SECRETS if s in wire], wire  # nothing the server holds was ever sent
    assert all('HttpOnly' in h['Set-Cookie'] and 'Secure' in h['Set-Cookie'] for _, h, _ in sent)
