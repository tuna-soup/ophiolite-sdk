"""E33 C7: the BFF's own provider leg (code + PKCE), the consent handle, and the exchange on every expiry.

The provider and Ophiolite are fakes at their HTTP boundary (httpx.MockTransport); each check the helper relies on is
made by the fake exactly as the real party makes it (PKCE S256, single-use and rotating refresh tokens, a handle that
ends), so a helper that skipped a step fails here.
"""
import base64
import hashlib
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from ophiolite.errors import Refused
from ophiolite.oauth_app import ConsentRequired, FileStore, OAuthApp, SignInRequired

URL = 'https://workspace.example'
ISSUER = 'https://id.example/realms/ophiolite'
CALLBACK = 'https://maps.example/callback'


def id_token(claims):
    part = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).rstrip(b'=').decode()
    return part({'alg': 'none'}) + '.' + part(claims) + '.'


class World:
    """The identity provider and Ophiolite, as far as the helper can see them."""
    def __init__(self):
        self.codes, self.refresh, self.handles, self.calls = {}, {}, {'handle-alice'}, []
        self.lifetime, self.exchange_lifetime, self.fail_refresh_persist = 300, 300, False

    def code(self, pending, subject='alice'):
        """The provider's answer to a browser that followed `begin()`: a code bound to the challenge and nonce."""
        query = parse_qs(urlsplit(self.authorize).query)
        code = 'code-' + str(len(self.codes))
        self.codes[code] = {'challenge': query['code_challenge'][0], 'nonce': query['nonce'][0], 'subject': subject,
                            'redirect': query['redirect_uri'][0], 'client': query['client_id'][0]}
        return code

    def tokens(self, subject, nonce=None):
        self.issued = getattr(self, 'issued', -1) + 1
        refresh = 'refresh-' + str(self.issued); self.refresh[refresh] = subject  # never reused
        return {'access_token': 'provider-' + refresh, 'refresh_token': refresh, 'expires_in': self.lifetime, 'token_type': 'Bearer',
                'id_token': id_token({'sub': subject, 'nonce': nonce, 'iss': ISSUER})}

    def __call__(self, request):
        self.calls.append((request.method, request.url.path, request.headers.get('cookie'), request.headers.get('origin')))
        if request.url.path == '/.well-known/oauth-authorization-server':
            return httpx.Response(200, json={'issuer': ISSUER, 'authorization_endpoint': ISSUER + '/protocol/openid-connect/auth',
                                             'token_endpoint': ISSUER + '/protocol/openid-connect/token'})
        if request.url.path.endswith('/token'):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form['grant_type'] == 'authorization_code':
                held = self.codes.pop(form['code'], None)
                verifier = form.get('code_verifier', '')
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                if held is None or held['challenge'] != challenge or held['redirect'] != form['redirect_uri'] or held['client'] != form['client_id']:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                return httpx.Response(200, json=self.tokens(held['subject'], held['nonce']))
            subject = self.refresh.pop(form['refresh_token'], None)  # single use; a replayed one is refused
            if subject is None: return httpx.Response(400, json={'error': 'invalid_grant'})
            return httpx.Response(200, json=self.tokens(subject))
        if request.url.path == '/api/v1/applications/exchange':
            body = json.loads(request.content)
            if body['consent'] not in self.handles or not body['access_token'].startswith('provider-'):
                return httpx.Response(403, json={'error': 'This sign-in cannot be used for this application'})
            return httpx.Response(200, json={'access_token': 'oph_app_' + body['access_token'], 'token_type': 'Bearer',
                                             'expires_in': self.exchange_lifetime, 'scopes': ['read'], 'projects': None})
        return httpx.Response(404, json={})


@pytest.fixture
def world(tmp_path):
    world = World()
    app = OAuthApp(URL, 'app_1', 'client-1', CALLBACK, store=FileStore(tmp_path / 'people'), client_secret='s3cret',
                   http=httpx.Client(transport=httpx.MockTransport(world)))
    world.app = app
    return world


def sign_in(world, subject='alice', handle='handle-alice'):
    world.authorize, pending = world.app.begin()
    person = world.app.callback(pending, world.code(pending, subject), pending['state'])
    return person, world.app.consented(person, 'st', {'consent': handle, 'state': 'st'})


def test_the_whole_flow_holds_everything_on_the_server(world, tmp_path):
    person, credential = sign_in(world)
    assert person == 'alice' and credential == 'oph_app_provider-refresh-0'
    query = parse_qs(urlsplit(world.authorize).query)
    assert (query['code_challenge_method'], query['client_id'], query['redirect_uri']) == (['S256'], ['client-1'], [CALLBACK])
    assert world.app.credential('alice') == credential  # cached until it expires
    assert parse_qs(urlsplit(world.app.consent_url('st')).query) == {'application': ['app_1'], 'redirect_uri': [CALLBACK], 'state': ['st']}
    assert not [c for c in world.calls if c[2] or c[3]]  # no cookie or Origin reaches either party
    files = list((tmp_path / 'people').glob('*.json'))
    assert len(files) == 1 and 'alice' not in files[0].name and oct(files[0].stat().st_mode & 0o777) == '0o600'


@pytest.mark.parametrize('spoil', ['state', 'verifier', 'code', 'nonce'])
def test_the_providers_leg_refuses_a_mismatched_state_verifier_or_code(world, spoil):
    world.authorize, pending = world.app.begin()
    code = world.code(pending)
    if spoil == 'state':
        with pytest.raises(Refused): world.app.callback(pending, code, 'another-state')
        return
    if spoil == 'nonce':  # an ID token minted for another sign-in
        with pytest.raises(Refused): world.app.callback({**pending, 'nonce': 'another'}, code, pending['state'])
        return
    if spoil == 'verifier': pending = {**pending, 'verifier': 'x' * 64}
    if spoil == 'code': code = 'code-never-issued'
    with pytest.raises(SignInRequired): world.app.callback(pending, code, pending['state'])


def test_a_consent_return_with_another_state_or_a_refusal_stores_no_handle(world):
    world.authorize, pending = world.app.begin()
    person = world.app.callback(pending, world.code(pending), pending['state'])
    with pytest.raises(Refused): world.app.consented(person, 'mine', {'consent': 'handle-alice', 'state': 'theirs'})
    with pytest.raises(ConsentRequired): world.app.consented(person, 'mine', {'error': 'access_denied', 'state': 'mine'})
    with pytest.raises(ConsentRequired, match='not approved'): world.app.credential(person)


def test_refresh_rotates_durably_and_exchanges_with_the_same_handle(world):
    world.lifetime = world.exchange_lifetime = 30  # expired at once under the skew
    sign_in(world)
    record = world.app.store.get('alice')
    assert record['refresh_token'] == 'refresh-0'
    second = world.app.credential('alice')
    record = world.app.store.get('alice')
    assert (second, record['refresh_token'], record['handle']) == ('oph_app_provider-refresh-1', 'refresh-1', 'handle-alice')
    assert 'refresh-0' not in world.refresh  # the old one was consumed by the provider


def test_a_lost_rotation_asks_for_sign_in_again_and_keeps_the_handle(world):
    world.lifetime = world.exchange_lifetime = 30
    sign_in(world)
    world.refresh.clear()  # the provider consumed the token, its replacement never reached the store (a crash)
    with pytest.raises(SignInRequired):
        world.app.credential('alice')
    assert world.app.store.get('alice') == {'handle': 'handle-alice'}  # an explicit re-authentication, not a silent lockout


def test_a_revoked_consent_ends_access_at_the_next_exchange_even_with_a_valid_provider_session(world):
    world.lifetime = world.exchange_lifetime = 30
    sign_in(world)
    world.handles.clear()  # the person removed the application in Workspace
    with pytest.raises(ConsentRequired):
        world.app.credential('alice')
    assert 'handle' not in world.app.store.get('alice') and world.app.store.get('alice')['refresh_token']  # sign-in kept, approval gone


def test_the_credential_lifetime_is_the_exchange_answer_not_the_provider_token(world):
    world.exchange_lifetime = 40  # Ophiolite's deadline is nearer than the provider token's expiry
    sign_in(world)
    held = world.app.store.get('alice')['credential']
    assert 35 <= held['expires_at'] - time.time() <= 40
    calls = len(world.calls)
    world.app.credential('alice')  # 40 s left, more than the skew: no new exchange
    assert len(world.calls) == calls
    world.exchange_lifetime = 20
    world.app.store.put('alice', {**world.app.store.get('alice'), 'credential': {**held, 'expires_at': time.time() + 20}})
    assert world.app.credential('alice').startswith('oph_app_') and len(world.calls) == calls + 1  # within the skew: exchanged again


def test_concurrent_refreshes_of_one_person_use_the_refresh_token_once(world):
    world.lifetime = world.exchange_lifetime = 30
    sign_in(world)
    world.lifetime = world.exchange_lifetime = 300
    answers, errors = [], []
    def call():
        try: answers.append(world.app.credential('alice'))
        except Exception as error: errors.append(error)
    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == [] and len(set(answers)) == 1 and sum(1 for c in world.calls if c[1].endswith('/token')) == 2  # code + one refresh


def test_the_discovered_endpoints_must_be_on_the_providers_origin(world):
    def lying(request):
        return httpx.Response(200, json={'issuer': ISSUER, 'authorization_endpoint': 'https://evil.example/auth', 'token_endpoint': ISSUER + '/token'})
    app = OAuthApp(URL, 'app_1', 'client-1', CALLBACK, store=world.app.store, http=httpx.Client(transport=httpx.MockTransport(lying)))
    with pytest.raises(Exception, match='Untrusted'): app.begin()


def test_a_rotated_refresh_token_is_stored_before_the_exchange_that_uses_it(world):
    world.lifetime = world.exchange_lifetime = 30
    sign_in(world)
    original = world.__call__
    def unreachable(request):  # Ophiolite does not answer after the provider rotated
        if request.url.path == '/api/v1/applications/exchange': raise httpx.ConnectError('down', request=request)
        return original(request)
    world.app.http = httpx.Client(transport=httpx.MockTransport(unreachable))
    with pytest.raises(Exception, match='did not answer'): world.app.credential('alice')
    assert world.app.store.get('alice')['refresh_token'] == 'refresh-1'  # the replacement survived; refresh-0 is spent
    world.app.http = httpx.Client(transport=httpx.MockTransport(world))
    assert world.app.credential('alice') == 'oph_app_provider-refresh-2'  # refresh-1 (the stored one) was accepted and rotated
