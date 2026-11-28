"""E217 s0 (D6): read_data answers a TypedData (well tops, a trajectory, a surface, a table, ...). Never executed."""
from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.typed import TypedData


def typed_data(client: Client) -> None:
    assert_type(client.read_data('asset', 'revision'), TypedData)
    assert_type([client.read_data(a, r) for a, r in [('a', 'r1'), ('a', 'r2')]], list[TypedData])
