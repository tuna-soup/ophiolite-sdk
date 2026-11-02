"""E131 s1 (D78): a team's own code is a tool. Write one with `@ophiolite.tool`, check and run it with the helpers here,
and manage the project's tools with the `Client.tool_*` methods.

`procedure`, `ophiolite.procedures` and `Client.procedure_*` are the execution names: the names a registered tool's code
imports; they stay, silent and permanent. A tool folder still holds procedure.json and procedure.py (the bundle
contract, `ophiolite.procedure/1`), and the names here are the same objects as those in `ophiolite.procedures`."""
import functools

from .procedures import (NotRun, Stopped, compared, delivered, digest, new, not_delivered, pack, procedure, refused, run,
                         unknown, validate)

__all__ = ['tool', 'ToolClient', 'compared', 'delivered', 'refused', 'not_delivered', 'unknown', 'Stopped', 'NotRun',
           'validate', 'digest', 'pack', 'new', 'run']


def tool(function):
    """Mark the function a tool's entry names (the same mark as `@procedure`, so every release runs it)."""
    return procedure(function)


# The 13 public methods of `procedures.ProcedureClient`, frozen when E131 s1 opened (f1d813538).
VERBS = ('register', 'list', 'get', 'bundle', 'enable', 'withdraw', 'trust', 'version', 'run', 'publish', 'run_get',
         'prepare_again', 'again')


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


for _verb in VERBS:
    setattr(ToolClient, 'tool_' + _verb, _twin(_verb))
del _verb
