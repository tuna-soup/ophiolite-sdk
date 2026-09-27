"""E20: wells and wellbores, and navigation over registered relationships.

The Client mixes in the generated `Navigation` (one assert and one follow method per predicate
people may assert, from the predicate registry) and these hand-written reads. Every call is one
route; nothing is inferred from names.
"""
from .errors import VerificationFailed


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
