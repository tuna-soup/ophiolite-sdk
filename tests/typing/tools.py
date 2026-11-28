"""E217 s0 (D3, D6): a `tool_*` twin is typed as its `procedure_*` call. Never executed."""
from typing import Any

from typing_extensions import assert_type

from ophiolite import Client


def twins(client: Client) -> None:
    assert_type(client.tool_bundle('a-digest'), bytes)
    assert_type(client.procedure_bundle('a-digest'), bytes)
    # answers that hold Any are checked by a declared variable, never read back (see typing/outcomes.py)
    versions: list[dict[str, Any]] = client.tool_list('residuals')
    same: list[dict[str, Any]] = client.procedure_list('residuals')
