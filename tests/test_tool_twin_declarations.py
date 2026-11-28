"""E217 s0 (D3): the `tool_*` twins `ToolClient` declares for a type checker are exactly the twins it attaches at run time.

The loop at the end of ophiolite/tools.py attaches one `tool_<verb>` per VERBS entry; a type checker sees only the
declarations under the class body's `if TYPE_CHECKING:`. This test reads those declarations with `ast` and holds each to
its `procedure_<verb>`: the same names, the same parameters (names, kinds, defaults and annotations, as written) and the
same return annotation; and its body is the docstring the twin carries at run time. Mutations: a declaration removed
or added; a parameter or return that differs from the procedure's; a declaration docstring that differs from the twin's."""
import ast
import inspect
from pathlib import Path

import pytest

from ophiolite import procedures, tools

SDK = Path(tools.__file__).resolve().parent


def class_body(module, name):
    tree = ast.parse((SDK / module).read_text(encoding='utf-8'))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name).body


def declared():
    """name -> FunctionDef, for each declaration under ToolClient's `if TYPE_CHECKING:` block."""
    blocks = [node for node in class_body('tools.py', 'ToolClient') if isinstance(node, ast.If) and ast.unparse(node.test) == 'TYPE_CHECKING']
    assert len(blocks) == 1, 'ToolClient declares its twins in one TYPE_CHECKING block'
    assert blocks[0].orelse == []
    return {node.name: node for node in blocks[0].body if isinstance(node, ast.FunctionDef)}


def defined():
    return {node.name: node for node in class_body('procedures.py', 'ProcedureClient') if isinstance(node, ast.FunctionDef)}


def test_every_attached_twin_is_declared_and_nothing_else_is():
    attached = sorted(name for name in vars(tools.ToolClient) if name.startswith('tool_'))
    assert attached == sorted('tool_' + verb for verb in tools.VERBS)
    assert sorted(declared()) == attached


@pytest.mark.parametrize('verb', tools.VERBS)
def test_each_declaration_repeats_its_procedure(verb):
    twin, original = declared()['tool_' + verb], defined()['procedure_' + verb]
    # the body is the docstring alone, the one the twin carries at run time (a reader of the source or of the generated
    # reference sees the same sentence as help() does)
    assert twin.decorator_list == [] and len(twin.body) == 1
    assert ast.get_docstring(twin, clean=False) == getattr(tools.ToolClient, 'tool_' + verb).__doc__
    assert ast.unparse(twin.args) == ast.unparse(original.args), 'parameters differ from procedure_' + verb
    assert twin.returns is not None and original.returns is not None
    assert ast.unparse(twin.returns) == ast.unparse(original.returns), 'return differs from procedure_' + verb
    # what was parsed is what runs: the procedure's run-time annotation is the declared text
    assert inspect.signature(getattr(procedures.ProcedureClient, 'procedure_' + verb)).return_annotation == ast.unparse(twin.returns)
    assert inspect.signature(getattr(tools.ToolClient, 'tool_' + verb)).return_annotation == ast.unparse(twin.returns)
