"""E20: wells and wellbores, and navigation over registered relationships.

The Client mixes in the generated `Navigation` (one assert and one follow method per predicate
people may assert, from the predicate registry) and these hand-written reads. Every call is one
route; nothing is inferred from names.
"""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

from typing import TYPE_CHECKING

from .errors import OphioliteError, Refused, VerificationFailed

if TYPE_CHECKING:  # E217 s0 (D1): read by a type checker only
    from collections.abc import Iterator
    from typing import Any

    from .client import Client


class Entity:
    """A well or wellbore as the server described it to you."""
    document: dict[str, Any]  # E217 s0: the entity document as served (entities/get), no contract type in the SDK
    entity_id: str
    kind: str
    name: str
    identity: dict[str, Any]
    generation: int

    def __init__(self, client: Client, document: dict[str, Any]) -> None:
        self._client, self.document = client, document
        self.entity_id, self.kind, self.name = document['entity_id'], document['kind'], document['name']
        self.identity, self.generation = document['identity'], document['generation']

    def __repr__(self):
        identity = 'provisional' if self.identity['provisional'] else '%s:%s' % (self.identity['authority'], self.identity['key'])
        return 'Entity(%s %r, %s)' % (self.kind, self.name, identity)

    def assets(self, profile: str | None = None, include_wellbores: bool = False) -> list[dict[str, Any]]:
        """The exact revisions associated with this entity that you may read. E66: `include_wellbores=True` (a well only)
        also returns those of the well's wellbores you may read, in one read, each item naming its `entity`."""
        return self._client.data(self, **({'profile': profile} if profile else {}), **({'include_parts': True} if include_wellbores else {}))

    def wellbores(self) -> list[Entity]:
        if self.kind != 'well': return []
        return [self._client.entity(p['entity_id']) for p in self.document['parts']]

    def well(self) -> Entity | None:
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

    def entities(self, kind: str | None = None) -> Iterator[Entity]:
        """Every well and wellbore you may read in this project, one page asked at a time.

        Parameters
        ----------
        kind : str, optional
            'well' or 'wellbore' for only that kind; every kind when None.

        Returns
        -------
        Iterator[Entity]
            Each well or wellbore as the server describes it to you.

        Raises
        ------
        VerificationFailed
            When the server names a page it already gave.
        """
        cursor, seen = None, set()
        while True:
            page = self._entities('list', {**({'kind': kind} if kind else {}), **({'cursor': cursor} if cursor else {}), 'limit': 100})
            for doc in page['entities']: yield Entity(self, doc)
            cursor = page.get('next_cursor')
            if not cursor: return
            if cursor in seen: raise VerificationFailed('Repeated entity cursor.')
            seen.add(cursor)

    def associations(self, assets=None, kind=None, profile=None) -> Iterator[dict[str, Any]]:
        """Every association you may read across your wells and wellbores, each item naming its `entity`.

        One read instead of `entity(id).assets()` for every well (H3), asked one page at a time.

        Parameters
        ----------
        assets : optional
            Up to 100 items (or their ids) whose associations you want; every item when None.
        kind : optional
            'well' or 'wellbore' for only that kind of entity.
        profile : optional
            Only items of this profile.

        Returns
        -------
        Iterator[dict]
            Each association as served, with its `entity`.

        Raises
        ------
        VerificationFailed
            When the server names a page it already gave.
        """
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

    def entity(self, entity: Entity | str) -> Entity:
        """One well or wellbore, as the server describes it to you.

        Parameters
        ----------
        entity : Entity or str
            The entity's id; an `Entity` you already hold is returned as it is.

        Returns
        -------
        Entity
            The well or wellbore, with its identity and generation.
        """
        if isinstance(entity, Entity): return entity
        return Entity(self, self._entities('get', {'entity_id': entity}))

    def create_entity(self, kind: str, name: str, *, authority: str | None = None, key: str | None = None, provisional: bool = False, audience=(),
                      part_of=None, statement: str | None = None, command_id: str | None = None) -> Entity:
        """A well or wellbore: declare its external identity (authority and key) or say it is provisional.

        Parameters
        ----------
        kind : str
            'well' or 'wellbore'.
        name : str
            The name people know it by.
        authority, key : str, optional
            Its external identity, such as a national register and its number in it.
        provisional : bool
            True when it has no external identity yet; `identify` gives it one later.
        audience
            Who besides you may see it.
        part_of : optional
            For a wellbore, the well (or its id) it is part of.
        statement : str, optional
            Your own words for why the wellbore is part of that well.
        command_id : str, optional
            Sent again, the same id answers with the same entity instead of making a second one.

        Returns
        -------
        Entity
            The new well or wellbore.
        """
        body = {'kind': kind, 'name': name, 'identity': {'provisional': True} if provisional else {'authority': authority, 'key': key}, 'audience': list(audience)}
        if part_of is not None: body['part_of'] = {'entity_id': getattr(part_of, 'entity_id', part_of), 'evidence': {'statement': statement}}
        if command_id: body['command_id'] = command_id
        return Entity(self, self._entities('create', body))

    def identify(self, entity: Entity | str, *, authority: str, key: str, command_id: str | None = None) -> Entity:
        """Give a provisional well or wellbore its external identity (authority and key), if no one changed it since you read it."""
        e = self.entity(entity)
        return Entity(self, self._entities('identify', {'entity_id': e.entity_id, 'authority': authority, 'key': key, 'expected_generation': e.generation,
                                                        **({'command_id': command_id} if command_id else {})}))

    def share_entity(self, entity: Entity | str, audience, *, command_id: str | None = None) -> dict[str, Any]:
        """Replace who may see a well or wellbore, if no one changed it since you read it."""
        e = self.entity(entity)
        return self._entities('share', {'entity_id': e.entity_id, 'audience': list(audience), 'expected_generation': e.generation, **({'command_id': command_id} if command_id else {})})

    def dissociate(self, assertion_id: str, *, command_id: str | None = None) -> dict[str, Any]:
        """Close one association you made, named by the assertion id the association answered with."""
        return self._entities('dissociate', {'assertion_id': assertion_id, **({'command_id': command_id} if command_id else {})})

    def lineage(self, asset, revision) -> dict[str, Any]:
        """One hop each way: parents, derivations and superseded revisions you may read.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.

        Returns
        -------
        dict
            The lineage as served (entities/lineage).
        """
        return self._entities('lineage', {'asset_id': asset, 'revision': revision})

    # --- E94: how a result was made, what changed, what depends on it, and making it again ------------------------

    def story(self, asset, revision, *, cursor=None, limit=None) -> dict[str, Any]:
        """One page of how an exact result version was made: the version, its inputs and their inputs (breadth first).

        Parameters
        ----------
        asset
            The result's id.
        revision
            The exact version.
        cursor : optional
            The `next_cursor` of the page before, for the next page.
        limit : optional
            At most this many entries on the page.

        Returns
        -------
        dict
            The page as served; follow `next_cursor` for the next page, and `continue_from` names results to open
            when a history is long.
        """
        return self._post('results', 'story', {'asset_id': asset, 'revision': revision, **({'cursor': cursor} if cursor else {}),
                                               **({'limit': limit} if limit else {})}, retry=True)

    def what_changed(self, a, b) -> dict[str, Any]:
        """What differs in how two exact result versions were made.

        Parameters
        ----------
        a, b
            The two versions, each an (asset_id, revision) pair.

        Returns
        -------
        dict
            The differences as served (results/what-changed).
        """
        pair = lambda x: {'asset_id': x[0], 'revision': x[1]}
        return self._post('results', 'what-changed', {'a': pair(a), 'b': pair(b)}, retry=True)

    def dependents(self, asset, revision, *, cursor=None, limit=None) -> dict[str, Any]:
        """The results made from an exact version you may read, with "Newer input available" where it applies.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.
        cursor : optional
            The `next_cursor` of the page before, for the next page.
        limit : optional
            At most this many results on the page.

        Returns
        -------
        dict
            One page as served (results/dependents).
        """
        return self._post('results', 'dependents', {'asset_id': asset, 'revision': revision, **({'cursor': cursor} if cursor else {}),
                                                    **({'limit': limit} if limit else {})}, retry=True)

    def remake(self, asset, revision, *, step='preview', inputs=None, command_id=None, execution_id=None) -> dict[str, Any]:
        """Make an exact result version again, one step at a time, without saving anything.

        `preview` names the exact inputs (`inputs='recorded'` or `'newer'`); `run` takes those inputs and a command id
        and holds a different output for 24 hours; `status` reads it and `discard` drops it. Nothing is saved:
        `remake_save` does that, on a separate confirm.

        Parameters
        ----------
        asset
            The result's id.
        revision
            The exact version to make again.
        step : str
            'preview', 'run', 'status' or 'discard'.
        inputs : optional
            'recorded' or 'newer': which exact inputs the remake reads.
        command_id : optional
            Needed to run; the same id answers with the same receipt.
        execution_id : optional
            The execution a run returned, for `status` and `discard`.

        Returns
        -------
        dict
            The step's answer as served (results/remake-run).

        Raises
        ------
        Refused
            When the step is not one of the four, a run has no command id, or `status` or `discard` names no execution.
        OphioliteError
            When the server refuses, in the server's own sentence (its category stays).
        """
        if step not in ('preview', 'run', 'status', 'discard'): raise Refused('Choose preview, run, status or discard.')
        if step == 'run' and not command_id: raise Refused('Running needs a command id; the same id answers the same receipt.')
        if step in ('status', 'discard') and not execution_id: raise Refused('Name the execution the run returned.')
        body = {'asset_id': asset, 'revision': revision, 'step': step, **({'inputs': inputs} if inputs is not None else {}),
                **({'command_id': command_id} if command_id else {}), **({'execution_id': execution_id} if execution_id else {})}
        return _in_its_words(lambda: self._post('results', 'remake-run', body, retry=step != 'discard'))

    def remake_save(self, execution_id, outputs) -> dict[str, Any]:
        """Save the outputs a remake holds that differ from the version it made again.

        Parameters
        ----------
        execution_id
            The execution `remake` ran.
        outputs
            Each output to save: {role, target ('new-result' or 'new-version'), command_id}, and for a new version
            the `audience_digest` the status showed and the person confirmed.

        Returns
        -------
        dict
            What was saved, as served (results/remake-save).

        Raises
        ------
        Refused
            When no output is named, or one is not saved as a new result or a new version with its own command id.
        OphioliteError
            When the server refuses, in the server's own sentence (its category stays).
        """
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
