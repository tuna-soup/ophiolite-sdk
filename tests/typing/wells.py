"""E217 s0 (D6): `client.wells()` is a list of Well, each with its name. Never executed."""
from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.locations import Well, Wells


def wells(client: Client) -> None:
    listed = client.wells(crs='OGC:CRS84', limit=10)
    assert_type(listed, Wells)
    assert_type(client.wells()[0].name, str)
    assert_type(listed[0], Well)
    assert_type(listed[0].entity_id, str)
    assert_type(listed.crs, str | None)
    assert_type(listed.untransformed, int)
    assert_type([well.name for well in listed], list[str])
