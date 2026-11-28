"""E217 s0 (D6): outcome and procedure answers. Never executed.

These answers are the server's JSON as served (dict[str, Any], on ANY_ALLOWED with a reason). Under --disallow-any-expr
a call whose type holds Any may only be taken into a declared variable (and never read back), so each is checked by its
assignment: a return annotated otherwise fails here as an incompatible assignment.
"""
from typing import Any

from typing_extensions import assert_type

from ophiolite import Client


def outcomes(client: Client) -> None:
    one: dict[str, Any] = client.outcome_get('an-outcome-id')
    listed: list[dict[str, Any]] = client.outcome_list()
    named: dict[str, Any] = client.outcome_named('Residuals within 5 m')
    states: dict[str, Any] = client.outcome_states('an-asset-id', 'a-revision')
    claims: list[dict[str, Any]] = client.outcome_claims()
    assert_type(client.result_version('Residuals DCC@2'), tuple[str, str])


def procedures(client: Client) -> None:
    versions: list[dict[str, Any]] = client.procedure_list('residuals')
    version: dict[str, Any] = client.procedure_version('residuals', 2)
    assert_type(client.procedure_bundle('a-digest'), bytes)
