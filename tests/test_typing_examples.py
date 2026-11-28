"""E217 s0 (D6): the examples in tests/typing type-check against the installed wheel, not the source tree.

The examples are copied out of the tree and checked by `mypy --strict --python-version 3.10 --disallow-any-expr`, with
the wheel's interpreter named by OPHIOLITE_TEST_WHEEL_PYTHON (the Visual job's clean wheel venv). They are never run.
D7: each Example section of a checked docstring (test_docstrings.examples) is checked with them, after the preamble
`client: ophiolite.Client`, in a file named by its method.
Without that interpreter the test skips; with OPHIOLITE_REQUIRE_WHEEL=1 it fails instead.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_docstrings import PREAMBLE, examples as docstring_examples

EXAMPLES = Path(__file__).resolve().parent / 'typing'
# one file per return family (D10); a file lost from the folder fails here rather than going unchecked
FAMILIES = ['async_calls.py', 'catalogue.py', 'entities.py', 'outcomes.py', 'readme.py', 'results.py', 'tools.py', 'typed_data.py', 'volumes.py', 'wells.py',
            'writes.py']


def wheel_python():
    given = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if given: return os.path.abspath(given) if os.sep in given else given  # the checks run in tmp_path
    if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')
    pytest.skip('Set OPHIOLITE_TEST_WHEEL_PYTHON to the installed wheel interpreter')


def outside_the_tree():
    """The environment without the tree's PYTHONPATH (or a MYPYPATH), so only the wheel's package can be found."""
    return {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'MYPYPATH')}


def installed_package(python, cwd):
    """Where the wheel interpreter imports ophiolite from, checked to be its own installed, typed package."""
    code = 'import json, sys, ophiolite; print(json.dumps([ophiolite.__file__, sys.prefix]))'
    done = subprocess.run([python, '-c', code], cwd=cwd, env=outside_the_tree(), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    module, prefix = json.loads(done.stdout)
    package, prefix = Path(module).resolve().parent, Path(prefix).resolve()
    assert package.is_relative_to(prefix), f'ophiolite is imported from {package}, outside the wheel venv {prefix}'
    assert (package / 'py.typed').is_file(), f'{package} has no py.typed'
    return package


def test_every_return_family_has_its_example():
    assert sorted(p.name for p in EXAMPLES.glob('*.py')) == FAMILIES


def test_the_examples_type_check_against_the_installed_wheel(tmp_path):
    python = wheel_python()
    if importlib.util.find_spec('mypy') is None: pytest.fail('Install the dev extra: it pins mypy, which checks these examples')
    installed_package(python, tmp_path)
    folder = tmp_path / 'examples'
    folder.mkdir()
    copies = [str(shutil.copy(EXAMPLES / name, folder / name)) for name in FAMILIES]
    for where, code in docstring_examples().items():  # D7: one file per docstring Example, named by its method
        path = folder / ('docstring_' + where.replace('.', '_') + '.py')
        path.write_text(PREAMBLE + code)
        copies.append(str(path))
    command = [sys.executable, '-m', 'mypy', '--strict', '--python-version', '3.10', '--python-executable', python,
               '--no-incremental', '--cache-dir', str(tmp_path / 'cache'), '--disallow-any-expr', *copies]
    done = subprocess.run(command, cwd=tmp_path, env=outside_the_tree(), capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-2000:]
