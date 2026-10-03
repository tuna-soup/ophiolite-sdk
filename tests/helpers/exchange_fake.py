"""E70a: an in-memory project for the exchange core's tests (standard library and ophiolite.errors only, so a
separate process can import it). Items have versions; only the author may add one; the stale parent and the
duplicate content are both a 409 revision-conflict without author or time, as the gateway answers."""
import hashlib
import time

from ophiolite.errors import AuthenticationRequired, IntegrityConflict, PermissionRefused, Refused, Unavailable


def sha(data): return hashlib.sha256(data).hexdigest()


class Fake:
    url, project = 'https://project.example', 'p'

    def __init__(self, person='alice', key='key-1'):
        self.person, self.key = person, key
        self.items, self.hidden, self.commands, self.calls = {}, set(), {}, []
        self.fail, self.slow, self.drop_after_commit, self.history_fails = {}, 0, False, False

    def add(self, ident, data, *, name, by='Alice Example', at=1000.0, kind='derived', owner='alice'):
        item = self.items.setdefault(ident, {'name': name, 'kind': kind, 'owner': owner, 'versions': []})
        item['versions'].append({'number': len(item['versions']) + 1, 'revision': sha(data), 'by': by, 'at': at, 'data': data})
        return sha(data)

    # the transport

    def identity(self): return {'kind': 'delegate', 'fingerprint': self.key}

    def _maybe(self, name):
        if name in self.fail: raise self.fail[name]

    def inventory(self):
        self.calls.append(('inventory',)); self._maybe('inventory')
        return [{'asset_id': i, 'kind': v['kind'], 'authority': 'retained', 'revision': v['versions'][-1]['revision'], 'name': v['name']}
                for i, v in sorted(self.items.items()) if i not in self.hidden]

    def history(self, item):
        self.calls.append(('history', item['asset_id']))
        if self.history_fails: raise Unavailable('history unavailable', status=503)
        return [{k: v for k, v in ver.items() if k != 'data'} for ver in self.items[item['asset_id']]['versions']]

    def fetch(self, item, revision, output, **how):
        self.calls.append(('fetch', item['asset_id'], revision)); self._maybe('fetch')
        if self.slow: time.sleep(self.slow)
        ver = next(v for v in self.items[item['asset_id']]['versions'] if v['revision'] == revision)
        if output is not None:
            (output / 'data.bin').write_bytes(ver['data'] + (b'|' + ','.join(how.get('curves', [])).encode() if how.get('curves') else b''))
            self._maybe('after-write')
        return {'content': ver['data'], 'number': ver['number']}

    def publish(self, data, request, resolved, command_id):
        self.calls.append(('publish', command_id, resolved.get('expected_parent'))); self._maybe('publish')
        if self.slow: time.sleep(self.slow)
        scope = (self.person, command_id)
        if scope in self.commands: return self.commands[scope]  # the server replays a recorded command (after authorisation)
        of = request.get('of')
        if of is not None:
            item = self.items[of]
            if item['owner'] != self.person: raise PermissionRefused('Only the author can add a version to this result, of the same type', status=403)
            if any(v['revision'] == sha(data) for v in item['versions']):
                raise IntegrityConflict('This content is already a version of the result', status=409, code='revision-conflict')
            if item['versions'][-1]['revision'] != resolved['expected_parent']:
                raise IntegrityConflict('The result has a newer version; review it before adding another', status=409, code='revision-conflict')
            self.add(of, data, name=item['name'], by=self.person.title(), at=2000.0, owner=self.person)
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

    def same_content(self, held, request): return request['sha256'] == held.get('revision')


ERRORS = {'expired': lambda: AuthenticationRequired('Sign in again.', status=401, stage='credential-refused'),
          'forbidden': lambda: PermissionRefused('Check project access.', status=403),
          'busy': lambda: Unavailable('busy', status=429, code='busy'),
          'large': lambda: Refused('too large', status=413),
          'invalid': lambda: Refused('bad request', status=422),
          'down': lambda: Unavailable('Cannot reach the service.', code='unreachable')}
