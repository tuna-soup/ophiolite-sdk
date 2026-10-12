"""E33: colleagues sign in to this map with their organisation account (a registered application).

The browser holds one thing: this server's own session cookie, a random value that names a row in this process's
memory. The provider tokens, the consent handle and the opaque Ophiolite credential stay in the SDK's store on the
server (`ophiolite.oauth_app`); no response, header, redirect or cookie carries any of them.

    GET /sign-in                -> 302 to the identity provider (code + PKCE with this application's own client)
    GET /callback?code=&state=  -> 302 to Ophiolite's consent page
    GET /callback?consent=&state= (or error=) -> 302 to /
    POST /api/wells             -> wells for the signed-in person (same origin, session cookie, explicit header)
    POST /sign-out              -> forget the person here (their approval stays until they remove it in Workspace)
"""
import json
import secrets
import threading
from http.cookies import SimpleCookie
from ophiolite.errors import OphioliteError
from ophiolite.oauth_app import ConsentRequired, SignInRequired

COOKIE = '__Host-map-session'


class SignIn:
    def __init__(self, app, origin, project):
        self.app, self.origin, self.project = app, origin, project
        self.sessions, self.lock = {}, threading.Lock()

    def _session(self, cookie_header):
        cookie = SimpleCookie(cookie_header or '')
        key = cookie[COOKIE].value if COOKIE in cookie else None
        with self.lock:
            if key and key in self.sessions: return key, self.sessions[key]
            key = secrets.token_urlsafe(32); self.sessions[key] = {}
            return key, self.sessions[key]

    def _cookie(self, key):
        return COOKIE + '=' + key + '; Path=/; Secure; HttpOnly; SameSite=Lax'

    def handle(self, method, path, query, headers):
        """(status, headers, body) for one request; QUERY maps names to single values."""
        key, session = self._session(headers.get('cookie'))
        out = {'Cache-Control': 'no-store', 'Set-Cookie': self._cookie(key), 'Referrer-Policy': 'no-referrer'}
        redirect = lambda to: (302, {**out, 'Location': to}, b'')
        if method == 'GET' and path == '/sign-in':
            address, session['pending'] = self.app.begin()
            return redirect(address)
        if method == 'GET' and path == '/callback':
            try:
                if 'code' in query:
                    session['person'] = self.app.callback(session.pop('pending', None), query.get('code'), query.get('state'))
                    session['consent_state'] = secrets.token_urlsafe(24)
                    return redirect(self.app.consent_url(session['consent_state']))
                self.app.consented(session.get('person'), session.pop('consent_state', None), query)
                return redirect('/')
            except OphioliteError:
                return redirect('/?sign-in=ended')
        if method == 'POST' and path in ('/api/wells', '/sign-out'):
            if headers.get('origin') != self.origin or headers.get('x-requested-with') != 'map':
                return 403, out, json.dumps({'message': 'Open this application on its own address.'}).encode()
            if path == '/sign-out':
                if session.get('person'): self.app.forget(session['person'])
                session.clear()
                return 200, out, b'{}'
            if not session.get('person'):
                return 401, out, json.dumps({'message': 'Sign in first.', 'sign_in': '/sign-in'}).encode()
            try:
                with self.app.client(session['person'], self.project) as client:
                    wells = client.wells(crs='OGC:CRS84').to_geojson()
            except (SignInRequired, ConsentRequired) as ended:
                if isinstance(ended, SignInRequired): session.pop('person', None)  # a removed approval keeps the person here
                return 401, out, json.dumps({'message': 'Sign in again.', 'sign_in': '/sign-in'}).encode()
            return 200, out, json.dumps({'wells': wells}).encode()
        return 404, out, json.dumps({'message': 'Not found.'}).encode()
