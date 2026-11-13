"""E70a: an in-memory project for the exchange core's tests (standard library and ophiolite.errors only, so a
separate process can import it). Items have versions; only the author may add one, or (E70c) a person the project names
together with the author (`contributors`); the stale parent and the
duplicate content are both a 409 revision-conflict without author or time, as the gateway answers."""
import hashlib
import json
import time

from ophiolite.errors import AuthenticationRequired, IntegrityConflict, PermissionRefused, Refused, Unavailable


def sha(data): return hashlib.sha256(data).hexdigest()


class Fake:
    url, project = 'https://project.example', 'p'

    def __init__(self, person='alice', key='key-1'):
        self.person, self.key = person, key
        self.items, self.hidden, self.commands, self.calls = {}, set(), {}, []
        self.fail, self.slow, self.drop_after_commit, self.history_fails = {}, 0, False, False
        self.contributors = set()  # E70c: the project's list; empty means only the author
        self.uploads = []  # E70d: each upload-version request that added a version
        self.attributions = []  # E171 s1: `attribution` of every publish call

    def add(self, ident, data, *, name, by='Alice Example', at=1000.0, kind='derived', owner='alice', profile=None, declared=None, revision=None,
            represents=None):
        item = self.items.setdefault(ident, {'name': name, 'kind': kind, 'owner': owner, 'versions': []})
        if profile is not None: item['profile'] = profile
        if represents is not None: item['represents'] = represents
        revision = revision or sha(data)  # E70d: a declaration-only upload version has a revision of its own
        item['versions'].append({'number': len(item['versions']) + 1, 'revision': revision, 'by': by, 'at': at, 'data': data,
                                 **({'declared': dict(declared)} if declared else {})})
        return revision

    # the transport

    def identity(self): return {'kind': 'delegate', 'fingerprint': self.key}

    def _maybe(self, name):
        if name in self.fail: raise self.fail[name]

    def inventory(self):
        self.calls.append(('inventory',)); self._maybe('inventory')
        return [{'asset_id': i, 'kind': v['kind'], 'authority': 'retained', 'revision': v['versions'][-1]['revision'], 'name': v['name'], **self._listed(v)}
                for i, v in sorted(self.items.items()) if i not in self.hidden]

    @staticmethod
    def _listed(item):
        """E173 s0b's served fields on an item added with a profile: `profile`, `by` (who made version 1, a person id: the
        owner here), `represents` (null unless the sender said) and, as the SDK keeps the page's label, `by_name` (absent
        without one). An item without a profile lists as before."""
        if 'profile' not in item: return {}
        label = item['versions'][0]['by']
        return {'profile': item['profile'], 'by': item['owner'], 'represents': item.get('represents'), **({'by_name': label} if label else {})}

    def history(self, item):
        self.calls.append(('history', item['asset_id']))
        if self.history_fails: raise Unavailable('history unavailable', status=503)
        return [{k: v for k, v in ver.items() if k != 'data'} for ver in self.items[item['asset_id']]['versions']]

    def fetch(self, item, revision, output, **how):
        self.calls.append(('fetch', item['asset_id'], revision)); self._maybe('fetch')
        if self.slow: time.sleep(self.slow)
        ver = next(v for v in self.items[item['asset_id']]['versions'] if v['revision'] == revision)
        if output is not None:
            output.mkdir()
            (output / 'data.bin').write_bytes(ver['data'] + (b'|' + ','.join(how.get('curves', [])).encode() if how.get('curves') else b''))
            self._maybe('after-write')
        return {'content': ver['data'], 'number': ver['number']}

    appends_uploads = True  # E70d: this fake project also takes an upload's next version by upload

    def publish(self, data, request, resolved, command_id, attribution=None):
        self.calls.append(('publish', command_id, resolved.get('expected_parent'))); self._maybe('publish')
        self.attributions.append(attribution)  # E171 s1: the holder and application each send names (None: an older pending send)
        if self.slow: time.sleep(self.slow)
        scope = (self.person, command_id)
        if resolved.get('route') == 'upload': return self._append_upload(data, request, resolved, scope)
        if scope in self.commands: return self.commands[scope]  # the server replays a recorded command (after authorisation)
        of = request.get('of')
        if of is not None:
            item = self.items[of]
            named = self.contributors
            if item['owner'] != self.person and not (self.person in named and item['owner'] in named):
                raise PermissionRefused(("Only the author, or a member the project lets add versions to each other's results, can" if named else 'Only the author can')
                                        + ' add a version to this result, of the same type', status=403)
            if any(v['revision'] == sha(data) for v in item['versions']):
                raise IntegrityConflict('This content is already a version of the result', status=409, code='revision-conflict')
            if item['versions'][-1]['revision'] != resolved['expected_parent']:
                raise IntegrityConflict('The result has a newer version; review it before adding another', status=409, code='revision-conflict')
            self.add(of, data, name=item['name'], by=self.person.title(), at=2000.0, owner=item['owner'])  # the author stays the author
            receipt = {'asset_id': of, 'revision': sha(data), 'number': len(item['versions'])}
        else:
            ident = 'new-%d' % (len(self.items) + 1)
            self.add(ident, data, name=request['name'], by=self.person.title(), at=2000.0, owner=self.person)
            receipt = {'asset_id': ident, 'revision': sha(data), 'number': 1}
        self.commands[scope] = receipt
        if self.drop_after_commit:
            self.drop_after_commit = False
            raise Unavailable('Cannot reach the service.', code='unreachable')
        return receipt

    def _append_upload(self, data, request, resolved, scope):
        """E70d: `las-uploads/upload` with `append_to`, as the gateway answers it. Only the author, of the same profile
        (403); a profile that takes no version (422); a replayed command must carry the same request (409); the stale
        head first, then a recurrence of bytes AND declarations, the head first, in the server's own words. The answer
        names no number (an upload receipt carries none)."""
        item, declared = self.items[request['of']], dict(request.get('declare') or {})
        fingerprint = (sha(data), sorted(declared.items()), request['how'], request.get('rights_confirmed'), json.dumps(request.get('source'), sort_keys=True))
        if scope in self.commands:
            if self.commands[scope][1] != fingerprint: raise Refused('Upload command already used for different content', status=409, code='conflict')
            return self.commands[scope][0]
        if item['owner'] != self.person or item.get('profile', request['profile']) != request['profile']:
            raise PermissionRefused('Only the author can add a version to this result, of the same type', status=403)
        if item.get('versioned') is False: raise Refused('This type of file does not take a new version by upload.', status=422)
        if item['versions'][-1]['revision'] != resolved['expected_parent']:
            raise IntegrityConflict('The result has a newer version; review it before adding another', status=409, code='revision-conflict')
        content = (sha(data), declared)
        for ver in reversed(item['versions']):
            if (sha(ver['data']), ver.get('declared', {})) == content:
                if ver is item['versions'][-1]:
                    raise IntegrityConflict('Nothing changed: this is version %d.' % ver['number'], status=409, code='revision-conflict')
                raise IntegrityConflict('This content was version %d on %s.' % (ver['number'], time.strftime('%-d %B %Y', time.gmtime(ver['at']))),
                                        status=409, code='revision-conflict')
        recurs = any(sha(v['data']) == sha(data) for v in item['versions'])  # a declaration-only version: its own revision
        revision = self.add(request['of'], data, name=item['name'], by=self.person.title(), at=2000.0, owner=item['owner'], declared=declared,
                            revision=sha(data + json.dumps(declared, sort_keys=True).encode()) if recurs else None)
        receipt = {'asset_id': request['of'], 'revision': revision, 'number': None}
        self.uploads.append({'request': request, 'resolved': resolved})
        self.commands[scope] = (receipt, fingerprint)
        if self.drop_after_commit:
            self.drop_after_commit = False
            raise Unavailable('Cannot reach the service.', code='unreachable')
        return receipt

    def same_content(self, held, request): return held.get('kind') != 'uploaded' and request['sha256'] == held.get('revision')


def names_project(person='alice'):
    """E173 s0 (D4): the fixture project for names. Two items are called "Top Rotliegend": a horizon grid by Ada at
    version 2 and a point set by Ben at version 1; "Base Zechstein" is unique. Synthetic bytes."""
    fake = Fake(person)
    fake.add('tr-grid', b'grid v1', name='Top Rotliegend', by='Ada', profile='esri-ascii-grid/1', owner='ada')
    fake.add('tr-grid', b'grid v2', name='Top Rotliegend', by='Ada', at=1100.0, owner='ada')
    fake.add('tr-points', b'x,y,z\n1,2,3\n', name='Top Rotliegend', by='Ben', profile='points-csv/1', owner='ben')
    fake.add('bz-grid', b'zmap v1', name='Base Zechstein', by='Ada', profile='zmap-plus-grid/1', owner='ada')
    return fake


ERRORS = {'expired': lambda: AuthenticationRequired('Sign in again.', status=401, stage='credential-refused'),
          'forbidden': lambda: PermissionRefused('Check project access.', status=403),
          'busy': lambda: Unavailable('busy', status=429, code='busy'),
          'large': lambda: Refused('too large', status=413),
          'invalid': lambda: Refused('bad request', status=422),
          'down': lambda: Unavailable('Cannot reach the service.', code='unreachable')}
