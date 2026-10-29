"""E128: read a version of any process kind whole, on this computer.

`read(version)` (any object with `path`, `kind` and `declared`, such as a procedure's `LocalVersion`) or
`read(path=..., kind=..., declared=...)` returns the kind's result family with every field the kind carries, as
`MATRIX[kind]` states. A file that cannot be read whole is refused with one sentence (`ReadRefused`), never read
approximately. Slice 1 reads the CSV kinds and the well location (`tables`), slice 2 the text kinds (`text`), slice 3
the LAS kind (`las`). Importing this module contacts nothing and opens no file.
"""
from pathlib import Path

from ..errors import Refused
from .matrix import KINDS, MATRIX
from .results import Grid, Las, Location, Mesh, ModelSection, SeismicSection, Sticks, Table, Wavelet
from . import las, tables, text  # imported here, so that read() opens no module file once it has a path

__all__ = ['read', 'KINDS', 'MATRIX', 'ReadRefused', 'Table', 'Grid', 'Mesh', 'Sticks', 'Location', 'Wavelet',
           'ModelSection', 'SeismicSection', 'Las']

RESIDUAL = 'A well-residual/1 version is read with ophiolite.residuals, not ophiolite.readers.'
ARGUMENTS = 'Give read() a version, or a path and its kind, not both.'


class ReadRefused(Refused):
    """A file `read` does not read whole. `code` says why; `field` and `row` name where, or are None."""

    def __init__(self, message, *, code, field=None, row=None):
        super().__init__(message, code=code)
        self.field, self.row = field, row


def read(version=None, *, path=None, kind=None, declared=None):
    if version is not None:
        if path is not None or kind is not None or declared is not None or \
                not all(hasattr(version, name) for name in ('path', 'kind', 'declared')):
            raise ReadRefused(ARGUMENTS, code='arguments', field='version')
        path, kind, declared = version.path, version.kind, version.declared
    elif path is None and kind is None:
        raise ReadRefused(ARGUMENTS, code='arguments', field='version')
    elif path is None:
        raise ReadRefused(ARGUMENTS, code='arguments', field='path')
    elif kind is None:
        raise ReadRefused(ARGUMENTS, code='arguments', field='kind')
    if kind == 'well-residual/1':
        raise ReadRefused(RESIDUAL, code='residual-kind', field='kind')
    if not isinstance(kind, str) or kind not in MATRIX:
        raise ReadRefused('%s is not a kind ophiolite.readers reads; it reads the 12 process kinds in ophiolite.readers.KINDS.'
                          % (kind if isinstance(kind, str) else repr(kind)), code='not-a-process-kind', field='kind')
    if kind in tables.READERS: return tables._parse(kind, Path(path).read_bytes(), declared)
    if kind in text.READERS: return text._parse(kind, Path(path).read_bytes(), declared)
    return las._parse(Path(path).read_bytes(), declared)  # las2/1, the one kind left in MATRIX
