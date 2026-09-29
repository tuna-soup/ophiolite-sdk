"""Explicit browser login and a private, single-writer SDK credential store.

Importing this module performs no discovery, file access or network calls.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit
import uuid
import httpx
from ._core import origin
from .errors import AuthenticationRequired, Refused

SCHEMA = 'ophiolite.sdk-credential/1'


def _fail(message='Sign in again for this project.'):
    raise AuthenticationRequired(message)


def same_origin(value, expected):
    """Authentication endpoints can have paths, but never credentials or redirects."""
    def parts(url):
        try:
            p = urlsplit(url)
            base = urlunsplit((p.scheme, p.netloc, '', '', ''))
            origin(base)
            if p.query or p.fragment or p.username or p.password:
                _fail('Untrusted authentication endpoint.')
            return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)
        except (TypeError, ValueError):
            _fail('Untrusted authentication endpoint.')
    if parts(value) != parts(expected):
        _fail('Untrusted authentication endpoint.')
    return value


def _browser_url(value, expected):
    try:
        p = urlsplit(value)
        if p.username or p.password or p.fragment:
            _fail('Invalid verification URL.')
        same_origin(urlunsplit((p.scheme,p.netloc,p.path,'','')), expected)
    except (TypeError, ValueError):
        _fail('Invalid verification URL.')
    return value


def _positive(value, maximum=None):
    try:
        result = float(value)
        if isinstance(value, bool) or not math.isfinite(result) or result <= 0:
            _fail('Invalid authorization lifetime.')
    except (TypeError, ValueError):
        _fail('Invalid authorization lifetime.')
    return min(result, maximum) if maximum is not None else result


def _token(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        _fail('Provider session expired or revoked. Run browser login again.')
    return value


def request(url, body=None, headers=None, *, form=False, http=None, empty=False):
    """One bounded request; refresh and mutation requests are never replayed."""
    owns = http is None
    client = http or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
    try:
        kwargs = {'headers':headers or {}, 'follow_redirects':False}
        if body is not None:
            kwargs['data' if form else 'json'] = body
        with client.stream('GET' if body is None else 'POST', url, **kwargs) as response:
            if 300 <= response.status_code < 400:
                _fail('Authentication redirect refused; check the configured endpoint.')
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 2_100_000:
                    _fail('Authorization response exceeds the supported size.')
            if empty and not raw and 200 <= response.status_code < 300:
                return {}
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                _fail('Invalid authorization response.')
            if not isinstance(value, dict):
                _fail('Invalid authorization response.')
            if response.status_code >= 400:
                error = value.get('error')
                if form and error in ('authorization_pending','slow_down','access_denied','expired_token','invalid_grant'):
                    return {'error':error}
                _fail('Access request failed; check account, project permissions and grant status.')
            return value
    except httpx.HTTPError:
        _fail('Authorization request did not complete. Sign in again; it was not retried.')
    finally:
        if owns: client.close()


def default_path(url, project):
    key = hashlib.sha256((origin(url)+'\0'+project).encode()).hexdigest()
    return Path.home()/'.config/ophiolite/sdk/v1/projects'/(key+'.json')


def _path(path):
    result = Path(path).expanduser().absolute()
    legacy = Path.home()/'.config/ophiolite'
    if result in (legacy/'application.json', legacy/'project.json'):
        _fail('Choose an SDK credential path and run fresh browser login; legacy caches stay separate.')
    return result


def _check(st):
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600 or (hasattr(os,'getuid') and st.st_uid != os.getuid()):
        _fail('Credential file must be owned by you, regular and mode 0600.')


def _parent(path, create=False):
    if create: path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or (hasattr(os,'getuid') and st.st_uid != os.getuid()):
        _fail('Credential directory must be owned by you and mode 0700.')


def _read(path):
    try:
        _parent(path)
        _check(path.lstat())
        fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd) as stream:
            _check(os.fstat(stream.fileno()))
            value = json.load(stream)
    except (OSError, ValueError):
        _fail('Cannot read private SDK credentials. Run browser login again.')
    if not isinstance(value,dict) or value.get('schema') != SCHEMA:
        _fail('Legacy or unknown credentials refused. Run fresh SDK browser login; do not copy tokens.')
    if type(value.get('generation')) is not int or value['generation'] < 1 or not isinstance(value.get('family'),str) or not value['family']:
        _fail('Invalid credential envelope. Run browser login again.')
    data = value.get('credential')
    if isinstance(data,dict) and data.get('kind') == 'access_key':  # E25a: a saved access key, nothing to refresh
        try:
            origin(data['url'])
            if not isinstance(data['project'],str) or not data['project']: raise ValueError()
            _token(data['access_key'])
            if not data['access_key'].startswith(KEY_PREFIX): raise ValueError()
        except (KeyError, TypeError, ValueError):
            _fail('Invalid saved access key. Run ophiolite login --key again.')
        return value
    try:
        origin(data['url'])
        same_origin(data['issuer'],data['issuer'])
        same_origin(data['token_endpoint'],data['issuer'])
        if data.get('revocation_endpoint'): same_origin(data['revocation_endpoint'],data['issuer'])
        for name in ('project','client_id','access_token','refresh_token','grant_id'):
            _token(data[name])
        _positive(data['expires_at'])
    except (KeyError, TypeError, ValueError):
        _fail('Invalid saved authorization. Run browser login again.')
    return value


@contextmanager
def _lock(path, *, cancel=None, timeout=30):
    _parent(path, create=True)
    lock_path = path.with_name(path.name+'.lock')
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os,'O_NOFOLLOW',0), 0o600)
    except OSError:
        _fail('Cannot open the private credential lock.')
    try:
        _check(os.fstat(fd))
        deadline = time.monotonic()+timeout
        while True:
            if cancel is not None and cancel.is_set(): _fail('Credential operation cancelled.')
            try:
                if os.name == 'nt':
                    import msvcrt
                    if os.fstat(fd).st_size == 0: os.write(fd,b'0')
                    os.lseek(fd,0,os.SEEK_SET)
                    msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline: _fail('Credential store is busy. Retry after the other operation finishes.')
                time.sleep(0.01)
        try:
            yield
        finally:
            if os.name == 'nt':
                os.lseek(fd,0,os.SEEK_SET)
                msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(fd,fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _write(path, envelope):
    # Never replace a legacy file, even at an explicitly supplied destination.
    if path.exists() or path.is_symlink(): _read(path)
    fd, temporary = tempfile.mkstemp(prefix='.sdk-', dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(envelope, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        if os.name != 'nt':
            parent_fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(parent_fd)
            finally: os.close(parent_fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _updated(data, tokens):
    result = dict(data)
    result.update(access_token=_token(tokens.get('access_token')),
                  refresh_token=_token(tokens.get('refresh_token')),
                  expires_at=time.time()+_positive(tokens.get('expires_in')))
    return result


class Credential:
    """Explicit bearer or an explicitly opened SDK store; secrets never appear in repr."""
    def __init__(self, token=None, grant=None, *, path=None, envelope=None, http=None):
        self.token, self.grant = token, grant
        self.path, self._envelope, self.http = path, envelope, http

    def __repr__(self): return 'Credential(<private>)'

    @classmethod
    def bearer(cls, token, *, grant=None):
        try:
            _token(token)
            if grant is not None: _token(grant)
        except AuthenticationRequired:
            raise Refused('Supply a bearer credential and application grant without whitespace.') from None
        return cls(token,grant)

    @classmethod
    def from_file(cls, path, *, http=None):
        path = _path(path)
        return cls(path=path,envelope=_read(path),http=http)

    open = from_file

    def _current(self):
        value = _read(self.path)
        if value['family'] != self._envelope['family']:
            _fail('This session was replaced. Open the new SDK credentials explicitly.')
        return value

    def headers(self, url=None, project=None, *, cancel=None):
        with self.snapshot(url,project,cancel=cancel) as headers:
            return dict(headers)

    @contextmanager
    def snapshot(self, url=None, project=None, *, cancel=None):
        if self.path is None:
            result = {'Authorization':'Bearer '+self.token}
            if self.grant is not None: result['X-Ophiolite-Application-Grant'] = self.grant
            yield result
            return
        with _lock(self.path,cancel=cancel):
            value = self._current()
            data = value['credential']
            if url is None or origin(url) != data['url'] or project != data['project']:
                _fail('Saved authorization belongs to another gateway or project; log in for this project.')
            if data.get('kind') == 'access_key':  # E25a: the key itself is the bearer; the server rechecks it
                self._envelope = value
                yield {'Authorization':'Bearer '+data['access_key']}
                return
            if time.time() >= data['expires_at']-20:
                tokens = request(data['token_endpoint'], {'client_id':data['client_id'],
                    'grant_type':'refresh_token','refresh_token':data['refresh_token']}, form=True,http=self.http)
                value['credential'] = data = _updated(data,tokens)
                value['generation'] += 1
                _write(self.path,value)
            self._envelope = value
            yield {'Authorization':'Bearer '+data['access_token'],'X-Ophiolite-Application-Grant':data['grant_id']}

    def update(self, tokens):
        if self.path is None: _fail('Open an SDK credential store before updating it.')
        with _lock(self.path):
            current = self._current()
            if current['generation'] != self._envelope['generation']:
                _fail('Authorization changed during this operation. Sign in again.')
            current['credential'] = _updated(current['credential'],tokens)
            current['generation'] += 1
            _write(self.path,current)
            self._envelope = current

    def save(self):
        if self.path is None: _fail('Open an SDK credential store before saving it.')
        with _lock(self.path):
            # update and refresh already persist; stale snapshots cannot overwrite them.
            self._envelope = self._current()
            _write(self.path,self._envelope)

    def delete(self):
        if self.path is None: return
        with _lock(self.path):
            if self.path.exists() or self.path.is_symlink():
                self._current()
                self.path.unlink()

    @property
    def kind(self):
        """'access_key' for a saved access key, 'application' for a saved sign-in, 'bearer' otherwise."""
        if self._envelope is None: return 'bearer'
        return 'access_key' if self._envelope['credential'].get('kind') == 'access_key' else 'application'

    def summary(self):
        """What a saved credential is for, without any secret: gateway, project and, for a key, its scope and expiry."""
        if self._envelope is None: return {'kind': 'bearer'}
        data = self._envelope['credential']
        keep = ('url','project','label','scope','expires_at') if self.kind == 'access_key' else ('url','project')
        return {'kind': self.kind, **{k: data.get(k) for k in keep}}

    def revoke(self):
        if self.path is None: _fail('Open an SDK credential store before revoking it.')
        if self.kind == 'access_key': _fail('An access key is removed from the account page; ophiolite logout removes only this copy.')
        failures = []
        with _lock(self.path):
            value = self._current()
            data = value['credential']
            headers = {'Authorization':'Bearer '+data['access_token'],'X-Ophiolite-Application-Grant':data['grant_id']}
            try:
                request(data['url']+'/api/v1/application-access/revoke',{'id':data['grant_id']},headers,http=self.http)
            except AuthenticationRequired:
                failures.append('Workspace grant revocation unconfirmed; revoke it in Workspace.')
            try:
                if not data.get('revocation_endpoint'): _fail()
                request(data['revocation_endpoint'],{'client_id':data['client_id'],'token':data['refresh_token'],
                    'token_type_hint':'refresh_token'},form=True,http=self.http,empty=True)
            except AuthenticationRequired:
                failures.append('Provider revocation unconfirmed; end the application session at your provider.')
            self.path.unlink()
        if failures: _fail(' '.join(failures))


KEY_PREFIX = 'oph_key_'


def key_login(url, project, key, *, path=None, label=None, scope=None, expires_at=None, http=None):
    """E25a: save an access key (created on the account page) for this gateway and project, so later
    processes can use it. Nothing is sent: the server checks the key on each call."""
    url = origin(url)
    if not isinstance(project,str) or not project: raise Refused('Choose a project.')
    try:
        _token(key)
        if not key.startswith(KEY_PREFIX): raise ValueError()
    except (AuthenticationRequired, ValueError, TypeError):
        raise Refused('That is not an access key; copy it from the account page.') from None
    path = _path(path) if path is not None else default_path(url,project)
    data = {'kind':'access_key','url':url,'project':project,'access_key':key,'label':label,'scope':scope,'expires_at':expires_at}
    with _lock(path):
        if path.exists() or path.is_symlink(): _read(path)
        _write(path,{'schema':SCHEMA,'family':uuid.uuid4().hex,'generation':1,'credential':data})
    return Credential.from_file(path,http=http)


def device_login(url, project, *, path=None, write=False, label='Local Python curve application',
                 notify=None, http=None, cancel=None, assistant=None, compute=False):
    """Obtain a fresh provider family and explicit Workspace consent, then save it.

    ``notify(url, message)`` presents browser URLs/codes to the caller. Nothing is
    opened or printed implicitly. A saved legacy cache is never read or migrated.
    """
    url = origin(url)
    if not isinstance(project,str) or not project: raise Refused('Choose a project.')
    path = _path(path) if path is not None else default_path(url,project)
    with _lock(path,cancel=cancel):
        if path.exists() or path.is_symlink(): _read(path)
        # Keep login serialized with logout/refresh. Fresh login is an explicit operation.
        config = request(url+'/api/v1/application-access/config',http=http)
        try:
            issuer = config['issuer']
            same_origin(issuer,issuer)
            metadata = request(issuer.rstrip('/')+'/.well-known/openid-configuration',http=http)
            if metadata.get('issuer') != issuer: _fail('Provider issuer mismatch.')
            device = same_origin(metadata['device_authorization_endpoint'],issuer)
            token_endpoint = same_origin(metadata['token_endpoint'],issuer)
            revocation = same_origin(metadata['revocation_endpoint'],issuer) if metadata.get('revocation_endpoint') else None
            client_id = _token(config['client_id'])
            flow = request(device,{'client_id':client_id,'scope':'openid profile email'},form=True,http=http)
            verification = _browser_url(flow.get('verification_uri_complete',flow.get('verification_uri','')),issuer)
            interval = max(5,_positive(flow.get('interval',5)))
            deadline = time.monotonic()+_positive(flow['expires_in'],600)
            if notify: notify(verification,'Sign into your Ophiolite account. Device code: '+str(flow['user_code']))
            def pause(seconds, end):
                if cancel is not None and cancel.is_set(): _fail('Credential operation cancelled.')
                remaining = end-time.monotonic()
                if remaining <= 0: _fail('Browser authorization timed out.')
                delay = min(seconds,remaining)
                if cancel is not None:
                    if cancel.wait(delay): _fail('Credential operation cancelled.')
                else: time.sleep(delay)
                if time.monotonic() >= end: _fail('Browser authorization timed out.')
            while True:
                pause(interval,deadline)
                tokens = request(token_endpoint,{'client_id':client_id,'device_code':flow['device_code'],
                    'grant_type':'urn:ietf:params:oauth:grant-type:device_code'},form=True,http=http)
                if tokens.get('access_token'): break
                if tokens.get('error') == 'slow_down': interval += 5
                elif tokens.get('error') != 'authorization_pending': _fail('Browser authorization denied or expired; run login again.')
            data = _updated({'url':url,'project':project,'issuer':issuer,'client_id':client_id,
                             'token_endpoint':token_endpoint,'revocation_endpoint':revocation},tokens)
            headers = {'Authorization':'Bearer '+data['access_token']}
            # E5: an assistant (capability 2) acts for you under the agent rules; every change waits for approval.
            body = {'project_id':project,'scopes':['read']+(['write'] if write else [])+(['compute'] if compute and assistant else []),'label':assistant or label}
            # E22b: capability 3 also reads wells, wellbores and lineage and uploads originals (bundle import).
            body['capability'] = 2 if assistant else 3
            grant = request(url+'/api/v1/application-access/request',body,headers,http=http)
            data['grant_id'] = _token(grant['id'])
            approval = _browser_url(grant['approval_url'],url)
            if notify: notify(approval,'Confirm this application code in Workspace: '+str(grant['confirmation_code']))
            headers['X-Ophiolite-Application-Grant'] = data['grant_id']
            deadline = time.monotonic()+600
            while True:
                pause(5,deadline)
                if time.time() >= data['expires_at']-20:
                    data = _updated(data,request(token_endpoint,{'client_id':client_id,'grant_type':'refresh_token',
                        'refresh_token':data['refresh_token']},form=True,http=http))
                    headers['Authorization'] = 'Bearer '+data['access_token']
                state = request(url+'/api/v1/application-access/status',{'id':data['grant_id']},headers,http=http)['state']
                if state == 'approved': break
                if state != 'pending': _fail('Application request denied or revoked.')
            envelope = {'schema':SCHEMA,'family':uuid.uuid4().hex,'generation':1,'credential':data}
            _write(path,envelope)
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error,AuthenticationRequired): raise
            _fail('Invalid authorization response. Run browser login again.')
    return Credential.from_file(path,http=http)
