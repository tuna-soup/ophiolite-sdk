"""E217 s0 (D6): wells and wellbores as entities, and the data associated with one. Never executed.

An entity's data items are the server's association items as served (dict[str, Any], on ANY_ALLOWED), so they are
taken into a declared variable (never read back) rather than asserted under --disallow-any-expr.
"""
from collections.abc import Iterator
from typing import Any

from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.entities import Entity


def entities(client: Client) -> None:
    listed = client.entities(kind='well')
    assert_type(listed, Iterator[Entity])
    well = client.entity('an-entity-id')
    assert_type(well, Entity)
    assert_type(client.entity(well), Entity)
    assert_type(well.name, str)
    assert_type(well.kind, str)
    assert_type(well.generation, int)
    assert_type(well.wellbores(), list[Entity])
    assert_type(well.well(), Entity | None)
    assert_type(client.parts(well), list[Entity])
    assert_type(client.create_entity('well', 'F02-01', provisional=True), Entity)
    data: list[dict[str, Any]] = well.assets(profile='well-log/1', include_wellbores=True)
