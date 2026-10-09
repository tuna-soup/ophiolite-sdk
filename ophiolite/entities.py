"""E20: wells and wellbores, and navigation over registered relationships.

The Client mixes in the generated `Navigation` (one assert and one follow method per predicate
people may assert, from the predicate registry) and these hand-written reads. Every call is one
route; nothing is inferred from names.
"""
from .errors import OphioliteError, Refused, VerificationFailed


class Entity:
    """A well or wellbore as the server described it to you."""
    def __init__(self, client, document):
        self._client, self.document = client, document
        self.entity_id, self.kind, self.name = document['entity_id'], document['kind'], document['name']
        self.identity, self.generation = document['identity'], document['generation']

    def __repr__(self):
        identity = 'provisional' if self.identity['provisional'] else '%s:%s' % (self.identity['authority'], self.identity['key'])
        return 'Entity(%s %r, %s)' % (self.kind, self.name, identity)

    def assets(self, profile=None):
        """The exact revisions associated with this entity that you may read."""
        return self._client.data(self, **({'profile': profile} if profile else {}))

    def wellbores(self):
        if self.kind != 'well': return []
        return [self._client.entity(p['entity_id']) for p in self.document['parts']]

    def well(self):
        link = self.document.get('part_of')
        return self._client.entity(link['entity_id']) if link else None


def _in_its_words(call):
    """E94: a refused remake or save (409, 422) says why in the server's sentence (Journey J2: "Ophiolite did not run this
    calculation, so it cannot make it again."), not the transport's generic one; the category, code and remedy stay."""
    try: return call()
    except OphioliteError as refused:
        if refused.status not in (409, 422) or not refused.server_message or refused.server_message == refused.message: raise
        raise type(refused)(refused.server_message, refused.recovery, status=refused.status, code=refused.code, remedy=refused.remedy,
                            docs=refused.docs, request_id=refused.request_id, server_message=refused.server_message, details=refused.details) from None


class EntityClient:
    def _entities(self, operation, body):
        return self._post('entities', operation, body)

    def entities(self, kind=None):
        cursor, seen = None, set()
        while True:
            page = self._entities('list', {**({'kind': kind} if kind else {}), **({'cursor': cursor} if cursor else {}), 'limit': 100})
            for doc in page['entities']: yield Entity(self, doc)
            cursor = page.get('next_cursor')
            if not cursor: return
            if cursor in seen: raise VerificationFailed('Repeated entity cursor.')
            seen.add(cursor)

    def associations(self, assets=None, kind=None, profile=None):
        """Every association you may read across your wells and wellbores, each item with its `entity`, in pages
        (H3): one read instead of `entity(id).assets()` for every well. `assets`: up to 100 asset ids."""
        body = {**({'asset_ids': [getattr(a, 'asset_id', a) for a in assets]} if assets is not None else {}),
                **({'kind': kind} if kind else {}), **({'profile': profile} if profile else {}), 'limit': 100}
        cursor, seen = None, set()
        while True:
            page = self._entities('associations', {**body, **({'cursor': cursor} if cursor else {})})
            yield from page['items']
            cursor = page.get('next_cursor')
            if not cursor: return
            if cursor in seen: raise VerificationFailed('Repeated association cursor.')
            seen.add(cursor)

    def entity(self, entity):
        if isinstance(entity, Entity): return entity
        return Entity(self, self._entities('get', {'entity_id': entity}))

    def create_entity(self, kind, name, *, authority=None, key=None, provisional=False, audience=(), part_of=None, statement=None, command_id=None):
        """A well or wellbore: declare its external identity (authority and key) or say it is provisional."""
        body = {'kind': kind, 'name': name, 'identity': {'provisional': True} if provisional else {'authority': authority, 'key': key}, 'audience': list(audience)}
        if part_of is not None: body['part_of'] = {'entity_id': getattr(part_of, 'entity_id', part_of), 'evidence': {'statement': statement}}
        if command_id: body['command_id'] = command_id
        return Entity(self, self._entities('create', body))

    def identify(self, entity, *, authority, key, command_id=None):
        e = self.entity(entity)
        return Entity(self, self._entities('identify', {'entity_id': e.entity_id, 'authority': authority, 'key': key, 'expected_generation': e.generation,
                                                        **({'command_id': command_id} if command_id else {})}))

    def share_entity(self, entity, audience, *, command_id=None):
        e = self.entity(entity)
        return self._entities('share', {'entity_id': e.entity_id, 'audience': list(audience), 'expected_generation': e.generation, **({'command_id': command_id} if command_id else {})})

    def dissociate(self, assertion_id, *, command_id=None):
        return self._entities('dissociate', {'assertion_id': assertion_id, **({'command_id': command_id} if command_id else {})})

    def lineage(self, asset, revision):
        """One hop each way: parents, derivations and superseded revisions you may read."""
        return self._entities('lineage', {'asset_id': asset, 'revision': revision})

    # --- E94: how a result was made, what changed, what depends on it, and making it again ------------------------

    def story(self, asset, revision, *, cursor=None, limit=None):
        """One page of how an exact result version was made: the version, its inputs and their inputs (breadth first).
        Follow `next_cursor` for the next page; `continue_from` names results to open when a history is long."""
        return self._post('results', 'story', {'asset_id': asset, 'revision': revision, **({'cursor': cursor} if cursor else {}),
                                               **({'limit': limit} if limit else {})}, retry=True)

    def what_changed(self, a, b):
        """What differs in how two exact result versions were made. `a` and `b` are (asset_id, revision) pairs."""
        pair = lambda x: {'asset_id': x[0], 'revision': x[1]}
        return self._post('results', 'what-changed', {'a': pair(a), 'b': pair(b)}, retry=True)

    def dependents(self, asset, revision, *, cursor=None, limit=None):
        """The results made from an exact version you may read, with "Newer input available" where it applies."""
        return self._post('results', 'dependents', {'asset_id': asset, 'revision': revision, **({'cursor': cursor} if cursor else {}),
                                                    **({'limit': limit} if limit else {})}, retry=True)

    def remake(self, asset, revision, *, step='preview', inputs=None, command_id=None, execution_id=None):
        """Make an exact result version again. `preview` names the exact inputs (`inputs='recorded'` or `'newer'`); `run`
        takes those inputs and a command id and holds a different output for 24 hours; `status` reads it and `discard`
        drops it. Nothing is saved: `remake_save` does that, on a separate confirm."""
        if step not in ('preview', 'run', 'status', 'discard'): raise Refused('Choose preview, run, status or discard.')
        if step == 'run' and not command_id: raise Refused('Running needs a command id; the same id answers the same receipt.')
        if step in ('status', 'discard') and not execution_id: raise Refused('Name the execution the run returned.')
        body = {'asset_id': asset, 'revision': revision, 'step': step, **({'inputs': inputs} if inputs is not None else {}),
                **({'command_id': command_id} if command_id else {}), **({'execution_id': execution_id} if execution_id else {})}
        return _in_its_words(lambda: self._post('results', 'remake-run', body, retry=step != 'discard'))

    def remake_save(self, execution_id, outputs):
        """Save held outputs that differ: each {role, target ('new-result' or 'new-version'), command_id}, and for a new
        version the `audience_digest` the status showed and the person confirmed."""
        if not isinstance(outputs, (list, tuple)) or not outputs: raise Refused('Name each output to save.')
        for one in outputs:
            if not isinstance(one, dict) or one.get('target') not in ('new-result', 'new-version') or not one.get('command_id'):
                raise Refused('Save each output as a new result or a new version, with its own command id.')
        return _in_its_words(lambda: self._post('results', 'remake-save', {'execution_id': execution_id, 'outputs': list(outputs)}, retry=True))

    def _associate(self, predicate, subject, entity, evidence, command_id):
        target = self.entity(entity) if not isinstance(entity, dict) else None
        obj = {'kind': target.kind, 'entity_id': target.entity_id} if target else entity
        return self._entities('associate', {'predicate': predicate, 'subject': subject, 'object': obj, 'evidence': evidence, **({'command_id': command_id} if command_id else {})})

    def _follow(self, predicate, entity, **filters):
        e = self.entity(entity)
        if predicate == 'part-of':
            return e.wellbores()
        items, cursor, seen = [], None, set()
        while True:
            page = self._entities('assets', {'entity_id': e.entity_id, **filters, **({'cursor': cursor} if cursor else {}), 'limit': 100})
            items += page['items']; cursor = page.get('next_cursor')
            if not cursor: return items
            if cursor in seen: raise VerificationFailed('Repeated association cursor.')
            seen.add(cursor)
