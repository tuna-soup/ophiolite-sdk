"""E105a: procedures — a team's own code, described by a procedure.json, checked here exactly as Ophiolite checks it.

The validator is the contract's own file, `ophiolite/contracts/procedures/v1/procedure.py`, byte-identical to the
Platform's (the contract snapshot, SOURCE.json). It is loaded from its source text, so no bytecode is written into
the package. Validating, hashing and packing read files only: nothing is imported from a procedure, and nothing
here contacts a server.
"""
import types
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'procedures' / 'v1' / 'procedure.py'
_contract = None


def contract():
    """The packaged validator module (loaded once, from source text; reads and writes no bytecode)."""
    global _contract
    if _contract is None:
        module = types.ModuleType('ophiolite_procedure_contract')
        module.__file__ = str(CONTRACT)
        exec(compile(CONTRACT.read_text(encoding='utf-8'), str(CONTRACT), 'exec'), module.__dict__)
        _contract = module
    return _contract


def validate(folder):
    """The verdict on a procedure folder: {'valid', 'sentence', 'rules_version', ...}; a refusal adds 'code' and
    'field' (the JSON path or member path). The same rules_version gives the same verdict on the server."""
    return contract().validate(Path(folder))


def digest(folder):
    """The procedure's identity: sha256 over its member paths and contents (Ophiolite computes it; nobody types it)."""
    return contract().digest(Path(folder))


def pack(folder):
    """The procedure as a deterministic archive (bytes); refused when the folder is not a valid procedure."""
    return contract().pack(Path(folder))


def unpack(data, destination):
    """Check an archive completely, then write it into a new or empty folder; returns the verdict."""
    return contract().unpack_check(data, Path(destination))
