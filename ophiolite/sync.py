"""E28: keep a local copy of a project current from its event log.

    sync = client.sync('state/checkpoint.json')   # or ophiolite.sync.Sync(client, checkpoint=...)
    sync.run()                                    # resync when needed, then catch up
    for event in sync.follow(): ...               # live, over server-sent events

An event never carries state: it names a subject, and the client re-reads it (`Cache` applies the
fencing rules). `changes()` pages the log from a cursor; `follow()` streams it and resumes with the
standard Last-Event-ID; `resync()` enumerates the exhaustive inventories (wells and wellbores, every
logical asset, result groups) into a staged snapshot stamped with the head cursor it captured first,
then replays the log from that head. The `Checkpoint` records (url, project, principal, capability
digest, epoch, cursor); any change but the cursor forces a resync, and the cursor advances only after
a batch's cache writes all succeeded. A cursor the server no longer holds (another epoch, or pruned)
raises ResyncRequired inside `changes()` and is handled by `run()`; a refused project clears the cache.

The cache covers entities, assets and result groups. Every other event (sources, subscriptions,
stages, access blocks, approvals) is delivered by `changes()` and `follow()` for the application
to act on.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote
import httpx
from .errors import AuthenticationRequired, PermissionRefused, Refused, ResyncRequired, Unavailable
from .sync_cache import Cache


ASSET_SUBJECTS = frozenset({'uploaded', 'derived', 'recipe', 'registration', 'snapshot', 'asset', 'external-curve', 'external-scalar-map', 'external-tops'})
GROUP_KINDS = frozenset({'result-group-changed', 'result-group-visibility-lost', 'result-group-deleted'})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]


def principal_id(credential):
    """A stable id for who is reading: a saved sign-in's family (it survives refresh), else the bearer and grant."""
    if credential is None: return 'none'
    if getattr(credential, 'path', None) is not None:
        data = credential._envelope['credential']
        return _digest([credential._envelope.get('family'), data.get('grant_id'), data.get('kind')])
    return _digest([credential.token, credential.grant])


class Checkpoint:
    FIELDS = ('url', 'project', 'principal_id', 'capability_digest', 'epoch', 'cursor')

    def __init__(self, path=None, **values):
        self.path = Path(path) if path else None
        self.values = {k: values.get(k) for k in self.FIELDS}

    @classmethod
    def open(cls, path):
        path = Path(path)
        values = json.loads(path.read_text()) if path.exists() else {}
        if values and set(values) != set(cls.FIELDS): raise Refused('This file is not an Ophiolite sync checkpoint.')
        return cls(path, **values)

    def scope(self):
        return tuple(self.values[k] for k in ('url', 'project', 'principal_id', 'capability_digest', 'epoch'))

    def advance(self, scope, cursor):
        self.values.update(zip(('url', 'project', 'principal_id', 'capability_digest', 'epoch'), scope)); self.values['cursor'] = cursor
        if self.path is None: return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.checkpoint-')
        with os.fdopen(fd, 'w') as out: json.dump(self.values, out, sort_keys=True); out.flush(); os.fsync(out.fileno())
        os.chmod(tmp, 0o600); os.replace(tmp, self.path)  # durable: a crash leaves the old checkpoint or the new one


class Sync:
    def __init__(self, client, *, checkpoint=None, cache=None):
        self.client = client
        self.checkpoint = checkpoint if isinstance(checkpoint, Checkpoint) else Checkpoint.open(checkpoint) if checkpoint else Checkpoint()
        self.cache = cache

    # -- transport --------------------------------------------------------------------------------

    def _path(self, area, operation):
        return self.client.url + '/api/v1/projects/' + quote(self.client.project, safe='') + '/' + area + '/' + operation

    def _call(self, area, operation, body=None, headers=None):
        try:
            response = self.client.http.post(self._path(area, operation), json={'project_id': self.client.project, **(body or {})},
                                             headers={**self.client._headers(), **(headers or {})}, follow_redirects=False)
        except httpx.HTTPError: raise Unavailable('Cannot reach the service. Check its address and network connection.', code='unreachable') from None
        return self._answer(response)

    @staticmethod
    def _answer(response):
        if response.status_code == 200: return response.json()
        from .application_transport import envelope, carried
        meta = envelope(response); code = meta.get('code'); more = {'code': code, **carried(meta)}  # E31
        if response.status_code == 409 and code == 'CURSOR_EXPIRED': raise ResyncRequired('This copy is behind what the server keeps; resynchronise.', status=409, **more)
        if response.status_code == 401: raise AuthenticationRequired('Sign in again.', status=401, **more)
        if response.status_code == 403: raise PermissionRefused('This credential no longer reaches the project.', status=403, **more)
        raise Unavailable('The project event log answered %d.' % response.status_code, meta.get('remedy', ''), status=response.status_code, **more)

    # -- the log ----------------------------------------------------------------------------------

    def head(self):
        return self._call('changes', 'head')

    def changes(self, epoch, after, *, limit=100):
        """Pages of events after `after` (each page: epoch, changes, cursor, has_more), until the head."""
        while True:
            page = self._call('changes', 'list', {'epoch': epoch, 'after': after, 'limit': limit})
            yield page
            after = page['cursor']
            if not page['has_more']: return

    def follow(self, *, epoch=None, after=None, seconds=300, reconnect=True):
        """Events as they happen, over server-sent events; resumes from the last frame id after each reconnect."""
        last = '%s:%d' % (epoch, after) if epoch is not None and after is not None else None
        if last is None:
            head = self.head(); last = '%s:%d' % (head['epoch'], head['cursor'])
        while True:
            with self.client.http.stream('POST', self._path('changes', 'stream'), json={'project_id': self.client.project, 'seconds': seconds},
                                         headers={**self.client._headers(), 'Last-Event-ID': last, 'Accept': 'text/event-stream'}, follow_redirects=False) as response:
                if response.status_code != 200: self._answer(response)  # E31: the envelope is read with a bound
                frame = {}
                for line in response.iter_lines():
                    if line:
                        key, _, value = line.partition(': '); frame[key] = value; continue
                    if frame.get('event') == 'refused':
                        code = json.loads(frame.get('data') or '{}').get('code')
                        if code == 'CURSOR_EXPIRED': raise ResyncRequired('This copy is behind what the server keeps; resynchronise.', status=409)
                        raise PermissionRefused('This credential no longer reaches the project.', status=403)
                    if frame.get('event') == 'change':
                        last = frame['id']
                        for event in json.loads(frame['data'])['changes']: yield event
                    frame = {}
            if not reconnect: return

    # -- the cache --------------------------------------------------------------------------------

    def scope(self, epoch):
        try: described = self._call('capabilities', 'describe')
        except (PermissionRefused, Unavailable): capabilities = 'unavailable'
        else: capabilities = _digest(sorted((o.get('area'), o.get('operation') or o.get('name'), bool(o.get('allowed'))) for o in described.get('operations', [])))
        return (self.client.url, self.client.project, principal_id(self.client.credential), capabilities, epoch)

    def _inventory(self):
        items, cursor = {}, None
        while True:
            page = self._call('catalog', 'inventory', {'limit': 500, **({'cursor': cursor} if cursor else {})})
            for item in page['assets']: items[('asset', item['asset_id'])] = item
            cursor = page.get('next_cursor')
            if not cursor: return items

    def _groups(self):
        groups, cursor = {}, None
        while True:
            page = self._call('result-groups', 'list', {'limit': 200, **({'cursor': cursor} if cursor else {})})
            for group in page['groups']: groups[('result-group', group['id'])] = group
            cursor = page.get('next_cursor')
            if not cursor: return groups

    def _entity(self, entity_id):
        try: return self._call('entities', 'get', {'entity_id': entity_id})
        except (PermissionRefused, Unavailable) as error:
            raise LookupError(str(error)) from None

    def resync(self):
        """Capture the head, enumerate everything readable into a staged snapshot, swap it in, then replay from the head."""
        head = self.head()
        scope = self.scope(head['epoch'])
        if self.cache is None: self.cache = Cache(scope)
        else: self.cache.rescope(scope)
        staged = {('entity', doc['entity_id']): doc for doc in self._entities()}
        staged.update(self._inventory()); staged.update(self._groups())
        self.cache.replace_all(staged, head['cursor'])
        self.checkpoint.advance(scope, head['cursor'])
        return self.catch_up()

    def _entities(self):
        cursor = None
        while True:
            page = self._call('entities', 'list', {'limit': 100, **({'cursor': cursor} if cursor else {})})
            yield from page['entities']
            cursor = page.get('next_cursor')
            if not cursor: return

    def apply(self, page):
        """Refresh every cached subject a page names (the last event naming a subject is its fence). Raises on any
        failed read, before the caller advances the checkpoint."""
        entities, assets, groups = {}, {}, {}
        for event in page['changes']:
            kind, subject = event['kind'], event.get('subject_id')
            if subject is None: continue
            if event.get('subject_kind') == 'entity': entities[subject] = event['cursor']
            elif kind in GROUP_KINDS or event.get('subject_kind') == 'result-group': groups[subject] = event['cursor']
            elif event.get('subject_kind') in ASSET_SUBJECTS: assets[subject] = event['cursor']
        for kind, touched in (('entity', entities), ('asset', assets), ('result-group', groups)):
            for subject in touched: self.cache.invalidate(kind, subject)
        for subject, fence in entities.items(): self.cache.refresh('entity', subject, fence, lambda s=subject: self._entity(s))
        for kind, touched, enumerate_all in (('asset', assets, self._inventory), ('result-group', groups, self._groups)):
            if not touched: continue
            current = enumerate_all()
            for subject, fence in touched.items():
                def read(s=subject):
                    if (kind, s) not in current: raise LookupError('no longer readable')
                    return current[(kind, s)]
                self.cache.refresh(kind, subject, fence, read)

    def catch_up(self):
        """Replay the log from the checkpoint. Returns the number of events seen."""
        scope, cursor, seen = self.checkpoint.scope(), self.checkpoint.values['cursor'], 0
        try:
            for page in self.changes(scope[-1], cursor):
                self.apply(page)
                self.checkpoint.advance(scope, page['cursor'])  # only after the batch's cache writes all landed
                seen += len(page['changes'])
        except PermissionRefused:
            if self.cache is not None: self.cache.rescope(('refused',) + tuple(self.cache.scope[1:]))  # drop everything for this project
            raise
        return seen

    def run(self):
        """Bring the local copy up to date: a resync when the cache is new or the checkpoint no longer matches, else a
        catch-up; a cursor the server no longer holds falls back to a resync."""
        head = self.head()
        current = self.scope(head['epoch'])
        if self.cache is None or not self.cache.complete or self.checkpoint.scope() != current or self.cache.scope != current:
            return self.resync()
        try: return self.catch_up()
        except ResyncRequired: return self.resync()
