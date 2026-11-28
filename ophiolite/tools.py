"""A team's own code is a tool. Write one with `@ophiolite.tool`, check and run it with the helpers here,
and manage the project's tools with the `Client.tool_*` methods.

`procedure`, `ophiolite.procedures` and `Client.procedure_*` are the execution names: the names a registered tool's code
imports; they stay, silent and permanent. A tool folder still holds procedure.json and procedure.py (the bundle
contract, `ophiolite.procedure/1`), and the names here are the same objects as those in `ophiolite.procedures`."""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

import functools
from typing import TYPE_CHECKING

from .procedures import (NotRun, Stopped, compared, delivered, digest, new, not_delivered, pack, procedure, refused, run,
                         unknown, validate)

if TYPE_CHECKING:  # E217 s0 (D1, D3): read by a type checker only
    import time
    from typing import Any

    from .presentation import PresentedRun

__all__ = ['tool', 'ToolClient', 'compared', 'delivered', 'refused', 'not_delivered', 'unknown', 'Stopped', 'NotRun',
           'validate', 'digest', 'pack', 'new', 'run']


def tool(function):
    """Mark the function a tool's entry names (the same mark as `@procedure`, so every release runs it)."""
    return procedure(function)


# The 13 public methods of `procedures.ProcedureClient`, frozen when E131 s1 opened (f1d813538), E165 s1's two and
# E113 s1's three (sandbox runs).
VERBS = ('register', 'list', 'get', 'bundle', 'enable', 'withdraw', 'trust', 'version', 'run', 'publish', 'run_get',
         'prepare_again', 'again', 'verify', 'verifications', 'sandbox_enable', 'sandbox_run', 'sandbox_job')


def _twin(verb):
    """`tool_<verb>`: calls `procedure_<verb>` with the same arguments and returns what it returns."""
    from .procedures import ProcedureClient
    original = getattr(ProcedureClient, 'procedure_' + verb)

    @functools.wraps(original)
    def twin(self, *args, **kwargs):
        return getattr(self, 'procedure_' + verb)(*args, **kwargs)
    twin.__name__ = twin.__qualname__ = 'tool_' + verb
    twin.__doc__ = f'The tool spelling of `procedure_{verb}` (the same call).'
    return twin


class ToolClient:
    """Mixed into `Client` beside `ProcedureClient`: the project's tools, one `tool_*` method per `procedure_*` method."""

    if TYPE_CHECKING:  # E217 s0 (D3): the twins the loop below attaches, named for a type checker; never defined at run time.
        # Each repeats its `procedure_<verb>`'s parameters and return exactly (tests/test_tool_twin_declarations.py).
        def tool_register(self, folder, *, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_register` (the same call)."""
        def tool_list(self, name: str | None = None) -> list[dict[str, Any]]:
            """The tool spelling of `procedure_list` (the same call)."""
        def tool_get(self, digest: str) -> dict[str, Any]:
            """The tool spelling of `procedure_get` (the same call)."""
        def tool_bundle(self, digest: str) -> bytes:
            """The tool spelling of `procedure_bundle` (the same call)."""
        def tool_enable(self, digest: str, *, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_enable` (the same call)."""
        def tool_withdraw(self, digest: str, *, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_withdraw` (the same call)."""
        def tool_trust(self, digest: str, *, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_trust` (the same call)."""
        def tool_version(self, name: str, version: int | None = None, *, readable: bool = False) -> dict[str, Any]:
            """The tool spelling of `procedure_version` (the same call)."""
        def tool_run(self, name: str, destination, inputs=None, *, version: int | None = None, prompt=None, yes: bool = False, cache=None,
                     kinds=None, declared=None, systems=None, settings=None, items=(), reference=None) -> PresentedRun:
            """The tool spelling of `procedure_run` (the same call)."""
        def tool_publish(self, folder, *, name: str | None = None, again_of=None, for_outcome=None) -> dict[str, Any]:
            """The tool spelling of `procedure_publish` (the same call)."""
        def tool_run_get(self, run_id: str) -> dict[str, Any]:
            """The tool spelling of `procedure_run_get` (the same call)."""
        def tool_prepare_again(self, asset: str, revision: str) -> dict[str, Any]:
            """The tool spelling of `procedure_prepare_again` (the same call)."""
        def tool_again(self, asset: str, revision: str, destination, *, version: int | None = None, folder=None, prompt=None, yes: bool = False,
                       cache=None, name: str | None = None, for_: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_again` (the same call)."""
        def tool_verify(self, digest: str, *, check: str | None = None, publication=None, withdraw: str | None = None, witnessed: str | None = None,
                        reference_run: str | None = None, statement: str | None = None, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_verify` (the same call)."""
        def tool_verifications(self, digest: str) -> dict[str, Any]:
            """The tool spelling of `procedure_verifications` (the same call)."""
        def tool_sandbox_enable(self, digest: str, enabled: bool = True, *, command_id: str | None = None) -> dict[str, Any]:
            """The tool spelling of `procedure_sandbox_enable` (the same call)."""
        def tool_sandbox_run(self, digest: str, inputs, *, settings=None, limits=None, command_id: str | None = None, wait: float = 0,
                             interval: float = 2.0, clock=time.monotonic, sleep=time.sleep) -> dict[str, Any]:
            """The tool spelling of `procedure_sandbox_run` (the same call)."""
        def tool_sandbox_job(self, job_id: str, *, wait: float = 0, interval: float = 2.0, clock=time.monotonic, sleep=time.sleep,
                             seen=None) -> dict[str, Any]:
            """The tool spelling of `procedure_sandbox_job` (the same call)."""


for _verb in VERBS:
    setattr(ToolClient, 'tool_' + _verb, _twin(_verb))
del _verb
