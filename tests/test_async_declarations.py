"""E217 s0 (D2): the coroutines AsyncClient and AsyncWorkFolder declare for a type checker are exactly those they attach.

The loops at the end of ophiolite/aio.py attach the coroutines at run time; a type checker sees only the declarations
under each class body's `if TYPE_CHECKING:`. This test reads the loops and the declarations with `ast` and holds each
declaration to its synchronous counterpart: the same names, the same parameters (names, kinds, defaults and annotations,
as written) and the same return annotation, so an awaited call gives what the synchronous call returns.
- AsyncClient: each declaration repeats its Client method (ophiolite/client.py).
- AsyncWorkFolder: each declaration repeats its publish.WorkFolder method's parameters (`upload_las` is
  publish._work_upload, attached to WorkFolder); WorkFolder states no returns, so the return is the Client
  counterpart's, which answers the same request (`input` is Client.run_input).
Mutations: a declaration's return changed, or a declaration removed.
"""
import ast
import inspect
from pathlib import Path

import pytest

from ophiolite import aio
from ophiolite.client import Client

SDK = Path(aio.__file__).resolve().parent


def tree(module):
    return ast.parse((SDK / module).read_text(encoding='utf-8'))


def class_body(module, name):
    return next(node for node in tree(module).body if isinstance(node, ast.ClassDef) and node.name == name).body


def declared(name):
    """name -> AsyncFunctionDef, for each declaration under the class's one `if TYPE_CHECKING:` block in aio.py."""
    blocks = [node for node in class_body('aio.py', name) if isinstance(node, ast.If) and ast.unparse(node.test) == 'TYPE_CHECKING']
    assert len(blocks) == 1, f'{name} declares its attached coroutines in one TYPE_CHECKING block'
    assert blocks[0].orelse == []
    assert all(isinstance(node, ast.AsyncFunctionDef) for node in blocks[0].body), 'only async declarations'
    return {node.name: node for node in blocks[0].body}


def attached(cls, maker):
    """The names a module-level loop of aio.py attaches with `setattr(<cls>, _name, <maker>(_name))`, in order."""
    found = []
    for node in tree('aio.py').body:
        if not (isinstance(node, ast.For) and len(node.body) == 1): continue
        if ast.unparse(node.body[0]) == f'setattr({cls}, _name, {maker}(_name))':
            found += [element.value for element in node.iter.elts]
    return found


def client_defs():
    return {node.name: node for node in class_body('client.py', 'Client') if isinstance(node, ast.FunctionDef)}


def work_folder_defs():
    found = {node.name: node for node in class_body('publish.py', 'WorkFolder') if isinstance(node, ast.FunctionDef)}
    found['upload_las'] = next(node for node in tree('publish.py').body if isinstance(node, ast.FunctionDef) and node.name == '_work_upload')
    return found


CLIENT_ATTACHED = attached('AsyncClient', '_async_application')
WORK_ATTACHED = attached('AsyncWorkFolder', '_async_work')
COUNTERPART = {'input': 'run_input'}  # AsyncWorkFolder name -> the Client method whose return it shares


def test_the_counts_recounted_after_adhoc_async_client_find():
    # C6, recounted from aio.py at 71000c279 (strategy §2 counted 37 and 7 before that lane merged)
    assert (len(CLIENT_ATTACHED), len(set(CLIENT_ATTACHED)), len(WORK_ATTACHED)) == (39, 39, 7)


def test_every_attached_coroutine_is_declared_and_nothing_else_is():
    assert sorted(declared('AsyncClient')) == sorted(CLIENT_ATTACHED)
    assert sorted(declared('AsyncWorkFolder')) == sorted(WORK_ATTACHED)
    for name in CLIENT_ATTACHED:  # what was parsed is what runs: a coroutine standing in for the Client method
        attached_function = vars(aio.AsyncClient)[name]
        assert inspect.iscoroutinefunction(attached_function) and attached_function.__wrapped__ is vars(Client)[name], name
    for name in WORK_ATTACHED:
        assert inspect.iscoroutinefunction(vars(aio.AsyncWorkFolder)[name]), name


@pytest.mark.parametrize('name', CLIENT_ATTACHED)
def test_each_async_client_declaration_repeats_its_client_method(name):
    declaration, original = declared('AsyncClient')[name], client_defs()[name]
    assert declaration.decorator_list == [] and [ast.unparse(statement) for statement in declaration.body] == ['...']
    assert ast.unparse(declaration.args) == ast.unparse(original.args), 'parameters differ from Client.' + name
    assert declaration.returns is not None and original.returns is not None
    assert ast.unparse(declaration.returns) == ast.unparse(original.returns), 'return differs from Client.' + name
    # the attached coroutine carries the Client method's annotations (functools.wraps): the declared text
    assert inspect.get_annotations(getattr(aio.AsyncClient, name)).get('return') == ast.unparse(declaration.returns)


@pytest.mark.parametrize('name', WORK_ATTACHED)
def test_each_async_work_folder_declaration_repeats_its_work_folder_method(name):
    declaration, original = declared('AsyncWorkFolder')[name], work_folder_defs()[name]
    assert declaration.decorator_list == [] and [ast.unparse(statement) for statement in declaration.body] == ['...']
    assert ast.unparse(declaration.args) == ast.unparse(original.args), 'parameters differ from WorkFolder.' + name
    counterpart = client_defs()[COUNTERPART.get(name, name)]
    assert declaration.returns is not None
    assert ast.unparse(declaration.returns) == ast.unparse(counterpart.returns), 'return differs from Client.' + counterpart.name
