"""E33: sign colleagues in to your own application's server (a backend for a browser front end, "BFF").

Two actors, two legs, both run by your server:

    1. the identity provider (code + PKCE, with YOUR registration's own client)  -> provider tokens, held here
    2. Ophiolite's consent page (the person approves your application)          -> a consent handle, held here
    3. exchange(provider access token, handle) at Ophiolite                     -> an opaque `oph_app_` credential

The provider refresh token, the handle and the opaque credential stay on your server, in `store`, keyed per person;
none of them belongs in a cookie, a redirect, a page or browser storage. Each refresh exchanges again with the SAME
handle, so a revoked or replaced consent ends the application's access at the next refresh, whatever the provider
still allows. Refreshes of one person are serialised and the rotated refresh token is written durably before the
exchange that uses it.

Importing this module performs no discovery, file access or network calls.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
import httpx
from ._core import origin
from .auth import _lock, request, same_origin
from .errors import AuthenticationRequired, Refused

SKEW = 30  # seconds before an expiry at which a credential is treated as expired


class SignInRequired(AuthenticationRequired):
    """The provider sign-in ended (expired, revoked, or a rotated refresh token was lost): sign the person in again.
    Their consent may still be current; the next consent page then answers at once with a new handle."""
    code = 'sign-in-required'


class ConsentRequired(AuthenticationRequired):
    """Ophiolite refused the handle: the person removed the application, approved it again elsewhere, its approval
    reached its deadline, or the organisation suspended the application. Send them to `consent_url()`."""
    code = 'consent-required'


class FileStore:
    """One private JSON file per person under DIRECTORY (mode 0600), replaced atomically; the file name is a digest
    of the person key, never the key. Use your own store with the same three methods for a database."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, person):
        return self.directory / (hashlib.sha256(str(person).encode()).hexdigest() + '.json')

    def lock(self, person):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return _lock(self._path(person))

    def get(self, person):
        try: return json.loads(self._path(person).read_text())
        except FileNotFoundError: return None
        except ValueError: raise SignInRequired('The saved sign-in is unreadable; sign in again.') from None

    def put(self, person, record):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(person)
        fd, temporary = tempfile.mkstemp(prefix='.oauth-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream, allow_nan=False); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            if os.name != 'nt':
                parent = os.open(self.directory, os.O_RDONLY)
                try: os.fsync(parent)
                finally: os.close(parent)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def delete(self, person):
        try: self._path(person).unlink()
        except FileNotFoundError: pass


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _claims(id_token):
    """The subject of an ID token received directly from the token endpoint over TLS (OpenID Connect Core 3.1.3.7
    allows using it without a signature check there). It is only the store key: Ophiolite checks the subject itself
    at the exchange, against the consent."""
    try:
        payload = id_token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if not isinstance(value.get('sub'), str) or not value['sub']: raise ValueError
        return value
    except (AttributeError, IndexError, ValueError, TypeError):
        raise SignInRequired('The identity provider did not say who signed in; sign in again.') from None


class OAuthApp:
    """URL is the Ophiolite Workspace origin; APPLICATION its registration id; CLIENT_ID (and, for a server that can
    keep one, CLIENT_SECRET) the registration's own provider client; REDIRECT_URI the registered address the provider
    and the consent page return to (CONSENT_REDIRECT_URI when the consent page returns elsewhere)."""

    def __init__(self, url, application, client_id, redirect_uri, *, store, client_secret=None, consent_redirect_uri=None, http=None):
        self.url, self.application, self.client_id, self.client_secret = origin(url), application, client_id, client_secret
        self.redirect_uri, self.consent_redirect_uri = redirect_uri, consent_redirect_uri or redirect_uri
        self.store, self.http = store, http or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        self._metadata, self._locks, self._guard = None, {}, threading.Lock()

    def __repr__(self): return 'OAuthApp(<private>)'

    # --- discovery ------------------------------------------------------------------------------------------------
    def metadata(self):
        """The provider's endpoints, from Ophiolite's RFC 8414 document (C5), each on the provider's own origin."""
        if self._metadata is None:
            value = request(self.url + '/.well-known/oauth-authorization-server', http=self.http)
            issuer = value.get('issuer')
            for key in ('authorization_endpoint', 'token_endpoint'):
                if not isinstance(value.get(key), str): raise Refused('This Workspace does not describe its identity provider.')
                same_origin(value[key], issuer)
            self._metadata = value
        return self._metadata

    # --- leg 1: the provider ----------------------------------------------------------------------------------------
    def begin(self):
        """(address to send the browser to, pending) — keep PENDING in your own server-side session, never in a page."""
        pending = {'state': secrets.token_urlsafe(32), 'verifier': secrets.token_urlsafe(64), 'nonce': secrets.token_urlsafe(16)}
        query = {'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': self.redirect_uri, 'scope': 'openid',
                 'state': pending['state'], 'nonce': pending['nonce'], 'code_challenge': _challenge(pending['verifier']),
                 'code_challenge_method': 'S256'}
        return self.metadata()['authorization_endpoint'] + '?' + urlencode(query), pending

    def _token(self, body):
        if self.client_secret is None: body = {**body, 'client_id': self.client_id}
        else: body = {**body, 'client_id': self.client_id, 'client_secret': self.client_secret}
        return request(self.metadata()['token_endpoint'], body, form=True, http=self.http)

    def callback(self, pending, code, state):
        """The provider's return: the state must be the one `begin()` made; the code is redeemed with its verifier.
        Answers the person key (the provider subject) and stores the provider tokens under it."""
        if not isinstance(pending, dict) or not isinstance(state, str) or not hmac.compare_digest(state.encode(), pending.get('state', '').encode()):
            raise Refused('This sign-in did not start here; start again.')
        if not isinstance(code, str) or not code: raise Refused('The identity provider returned no code; start again.')
        tokens = self._token({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.redirect_uri, 'code_verifier': pending['verifier']})
        if tokens.get('error'): raise SignInRequired('The identity provider refused the sign-in; start again.')
        claims = _claims(tokens.get('id_token'))
        if claims.get('nonce') != pending['nonce']: raise Refused('This sign-in did not start here; start again.')
        person = claims['sub']
        with self._serial(person):
            record = self.store.get(person) or {}
            record.update(self._provider(tokens))
            record.pop('credential', None)  # a new sign-in exchanges again
            self.store.put(person, record)
        return person

    @staticmethod
    def _provider(tokens):
        if not isinstance(tokens.get('access_token'), str) or not isinstance(tokens.get('refresh_token'), str):
            raise SignInRequired('The identity provider returned no session; sign in again.')
        now = time.time()
        return {'access_token': tokens['access_token'], 'refresh_token': tokens['refresh_token'],
                'access_expires_at': now + float(tokens.get('expires_in', 60))}

    # --- leg 2: Ophiolite's consent ----------------------------------------------------------------------------------
    def consent_url(self, state):
        """Where to send the browser for the person's approval; keep STATE in your session and check it on return."""
        return self.url + '/application-access/authorize?' + urlencode({'application': self.application, 'redirect_uri': self.consent_redirect_uri, 'state': state})

    def consented(self, person, expected_state, query):
        """The consent page's return (its query parameters). Stores the handle and exchanges at once."""
        if not hmac.compare_digest(str(query.get('state', '')).encode(), str(expected_state).encode()):
            raise Refused('This approval did not start here; start again.')
        if query.get('error') == 'access_denied': raise ConsentRequired('The person did not allow this application.')
        handle = query.get('consent')
        if not isinstance(handle, str) or not handle: raise ConsentRequired('Ophiolite returned no approval; start again.')
        with self._serial(person):
            record = self._record(person)
            record['handle'] = handle
            record.pop('credential', None)
            self.store.put(person, record)
            return self._exchange(person, record)

    # --- leg 3: the exchange, on every expiry --------------------------------------------------------------------------
    def credential(self, person):
        """The person's current `oph_app_` credential (a str for `Credential.bearer`), refreshed when it expires."""
        with self._serial(person):
            record = self._record(person)
            held = record.get('credential')
            if held and held['expires_at'] - SKEW > time.time(): return held['value']
            if 'handle' not in record: raise ConsentRequired('The person has not approved this application yet.')
            if record['access_expires_at'] - SKEW <= time.time():
                tokens = self._token({'grant_type': 'refresh_token', 'refresh_token': record['refresh_token']})
                if tokens.get('error'):  # expired, revoked, or the provider already consumed a token whose replacement was lost
                    self.store.put(person, {'handle': record['handle']})
                    raise SignInRequired('The sign-in with the identity provider ended; sign in again.')
                record.update(self._provider(tokens))
                self.store.put(person, record)  # durable before the exchange that uses it
            return self._exchange(person, record)

    def client(self, person, project):
        """An SDK `Client` for PROJECT acting for PERSON with this application's credential."""
        from .auth import Credential
        from .client import Client
        return Client(self.url, project, credential=Credential.bearer(self.credential(person)))

    def forget(self, person):
        """Remove everything held for PERSON (sign-out of your application; their consent stays until they remove it)."""
        with self._serial(person): self.store.delete(person)

    def _record(self, person):
        record = self.store.get(person)
        if not record or 'refresh_token' not in record: raise SignInRequired('Sign the person in first.')
        return record

    def _exchange(self, person, record):
        try:
            response = self.http.post(self.url + '/api/v1/applications/exchange', json={'access_token': record['access_token'], 'consent': record['handle']},
                                      headers={'Accept': 'application/json'}, follow_redirects=False)
        except httpx.HTTPError:
            raise AuthenticationRequired('Ophiolite did not answer the exchange; retry.') from None
        if response.status_code in (401, 403, 404):
            record.pop('handle', None); record.pop('credential', None)
            self.store.put(person, record)
            raise ConsentRequired('Ophiolite no longer accepts this approval; ask the person to approve the application again.')
        if response.status_code != 200: raise AuthenticationRequired('Ophiolite refused the exchange; retry later.')
        answer = response.json()
        value = answer.get('access_token')
        if not isinstance(value, str) or not value.startswith('oph_app_'): raise AuthenticationRequired('Ophiolite answered no application credential.')
        record['credential'] = {'value': value, 'expires_at': time.time() + float(answer.get('expires_in', 0))}
        self.store.put(person, record)
        return value

    def _serial(self, person):
        """One refresh per person at a time: in this process (a lock) and across processes (the store's file lock)."""
        with self._guard: local = self._locks.setdefault(person, threading.Lock())
        outer = self.store.lock(person) if hasattr(self.store, 'lock') else None

        class Both:
            def __enter__(_):
                local.acquire()
                try:
                    if outer is not None: outer.__enter__()
                except BaseException:
                    local.release(); raise
            def __exit__(_, *exc):
                try:
                    if outer is not None: outer.__exit__(*exc)
                finally: local.release()
        return Both()


def oauth_app(url, application, client_id, redirect_uri, *, store, **options):
    """Shorthand for `OAuthApp(...)`; see its documentation."""
    return OAuthApp(url, application, client_id, redirect_uri, store=store, **options)
