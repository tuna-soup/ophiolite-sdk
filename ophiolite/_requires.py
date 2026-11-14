"""E112 s4: the Python distributions a procedure lists under `requires`, checked against the interpreter that runs it.

The grammar and the version order are the contract's own file, `ophiolite/contracts/procedures/v1/requires.py`,
byte-identical to the Platform's copy (which judges a manifest against a sandbox image, E113 s1) and loaded from its
source text (no bytecode is read or written). This module keeps what is the interpreter's: which version is installed
here, and the command that installs what is missing. Nothing is installed: the answer names what is missing."""
import importlib.metadata
import shlex
import sys
import types
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'procedures' / 'v1' / 'requires.py'


def _load():
    module = types.ModuleType('ophiolite_requires_contract')
    module.__file__ = str(CONTRACT)
    exec(compile(CONTRACT.read_text(encoding='utf-8'), str(CONTRACT), 'exec'), module.__dict__)
    return module


contract = _load()
Malformed, parse, version_key, satisfies = contract.Malformed, contract.parse, contract.version_key, contract.satisfies


def installed(name):
    """The installed version of distribution `name` in this interpreter (PackageNotFoundError when absent)."""
    return importlib.metadata.version(name)


def unmet(texts, version=None):
    """The requirements this interpreter does not meet, in order: [{'requirement', 'name', 'found', 'readable'}].
    Raises Malformed (with `.index`) for the first text outside the grammar."""
    version = version or installed

    def found(name):
        try: return version(name)
        except importlib.metadata.PackageNotFoundError: return None
    return contract.unmet(texts, found)


def install_line(missing):
    """The command that installs them into this interpreter."""
    return '%s -m pip install %s' % (shlex.quote(sys.executable), ' '.join(shlex.quote(m['requirement']) for m in missing))
