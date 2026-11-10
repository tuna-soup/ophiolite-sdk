"""E144 s1 (C4): data rules on this computer, with no server.

`run(path, kind, declared=None)` reads the file with `ophiolite.readers.read` (the declarations the reader takes, as
an upload states them), runs the rules of this package's current rule registry (`contracts/rules/v1`) that read
`kind`, and returns the `ophiolite.rule-results/1` block the Gateway stores for the same file at landing. A kind no
rule reads answers `results: []` without reading the file; a file the reader refuses raises `ReadRefused`, and so does
a kind a rule reads but `ophiolite.readers` does not (`not-a-process-kind`; E144 s2: of the spatial kinds the SDK
reads points-csv/1 and esri-ascii-grid/1). Nothing here contacts a server.
"""
from importlib.resources import files

from . import readers
from .data_rules import engine, inputs

__all__ = ['run']


def _registry():
    root = files('ophiolite').joinpath('contracts/rules/v1')

    def read(path):
        item = root.joinpath(path)
        return item.read_bytes() if item.is_file() else None
    index = engine.parse(read('registry.json'))
    return index['current'], engine.rules_of(engine.snapshot_named(index, index['current'], read), read)


def run(path, kind, declared=None):
    version, rules = _registry()
    quantities = engine.parse(files('ophiolite').joinpath('contracts/vocabulary/v1/quantities.json').read_bytes())
    data = None
    if engine.rules_for(kind, rules):  # E144 s2: read first, so a kind ophiolite.readers does not read is its refusal
        read = readers.read(path=path, kind=kind, declared=declared)
        data = inputs.ADAPTERS[kind](read)
    return engine.run(rules, kind, data, registry_version=version, quantities=quantities)
