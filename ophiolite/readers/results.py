"""E128: what `ophiolite.readers.read` returns, one frozen family per grammar shape.

Every family starts with `kind`, `declared` (the declarations exactly as supplied: absent stays absent, "unknown"
stays "unknown") and `context` (the normalized projection compared with the server's readers). Measurements are
floats, counts, indices and identifiers ints, text the grammar does not interpret is the string as written, and a
missing value is None. Construction copies: every mapping becomes a read-only `MappingProxyType` and every sequence
a tuple, all the way down, so a result never shares or exposes a mutable part.
"""
from dataclasses import dataclass, fields
from types import MappingProxyType


def _frozen(value):
    if isinstance(value, (dict, MappingProxyType)): return MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)): return tuple(_frozen(v) for v in value)
    return value


class _Result:
    def __post_init__(self):
        for f in fields(self):
            object.__setattr__(self, f.name, _frozen(getattr(self, f.name)))


@dataclass(frozen=True)
class Table(_Result):
    kind: str; declared: object; context: object
    columns: tuple; rows: tuple


@dataclass(frozen=True)
class Grid(_Result):
    kind: str; declared: object; context: object
    header: tuple; ncols: int; nrows: int; registration: str; x: float; y: float; cell_size: float; nodata: object
    cells: tuple


@dataclass(frozen=True)
class Mesh(_Result):
    kind: str; declared: object; context: object
    attributes: tuple; vertices: tuple; triangles: tuple


@dataclass(frozen=True)
class Sticks(_Result):
    kind: str; declared: object; context: object
    points: tuple


@dataclass(frozen=True)
class Location(_Result):
    kind: str; declared: object; context: object
    x: float; y: float; crs: str; elevation_reference: object


@dataclass(frozen=True)
class Wavelet(_Result):
    kind: str; declared: object; context: object
    header: tuple; wavelet_kind: str; dt: float; t0: float; polarity: str; frequency_hz: object; corners_hz: object
    samples: tuple


@dataclass(frozen=True)
class ModelSection(_Result):
    kind: str; declared: object; context: object
    header: tuple; axes: object; rocks: tuple; grid: tuple


@dataclass(frozen=True)
class SeismicSection(_Result):
    kind: str; declared: object; context: object
    header: tuple; axes: object; origin: object; polarity: object; grid: tuple


@dataclass(frozen=True)
class Las(_Result):
    kind: str; declared: object; context: object
    version: str; version_section: tuple; well: tuple; curves: tuple; parameters: tuple; other: object; null: str; data: tuple


FAMILIES = (Table, Grid, Mesh, Sticks, Location, Wavelet, ModelSection, SeismicSection, Las)
