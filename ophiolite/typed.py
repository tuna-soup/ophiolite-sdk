"""Typed scientific data (E11): well tops, trajectories and regular-grid surfaces.

Objects hold the exact original bytes, the verified descriptor and the served
normalized data. Nothing is converted: units, references and coordinate systems
are the declared ones and "unknown" stays unknown. Importing this module does
not contact a server.
"""
import math
from .errors import Refused

TYPES = ('well-tops', 'trajectory', 'regular-grid-surface', 'triangulated-surface', 'point-set', 'polyline-set', 'seismic-volume')


class TypedData:
    """Common exact-read container; `data` is the served normalized document."""
    type = None

    def __init__(self, descriptor, data, original, *, wire_descriptor=None, wire_data_bytes=None):
        self.descriptor = descriptor; self.data = data; self.original = original
        self.context = data['context']; self._wire_descriptor = wire_descriptor; self._wire_data_bytes = wire_data_bytes

    @property
    def relationships(self):
        return (self._wire_descriptor or {}).get('relationships')

    def _pandas(self):
        try: import pandas as pd
        except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
        return pd

    def __repr__(self):
        return f'<{type(self).__name__} {self.context.get("count", self.context.get("ncols"))} {self.type}>'


class WellTops(TypedData):
    type = 'well-tops'

    @property
    def tops(self): return self.data['tops']

    def to_frame(self):
        pd = self._pandas()
        return pd.DataFrame({'name': [t['name'] for t in self.tops], 'md': [t['md'] for t in self.tops],
                             'tvd': pd.array([t['tvd'] for t in self.tops], dtype='Float64'), 'source': [t['source'] for t in self.tops]})


class Trajectory(TypedData):
    type = 'trajectory'

    @property
    def stations(self): return self.data['stations']

    def to_frame(self):
        pd = self._pandas()
        column = lambda key: pd.array([s[key] for s in self.stations], dtype='Float64')
        return pd.DataFrame({'md': [s['md'] for s in self.stations], 'inclination': column('inclination'), 'azimuth': column('azimuth'), 'tvd': column('tvd')})

    def minimum_curvature(self):
        """Explicit calculation: offsets relative to the first station (dtvd, dnorth, deast).

        North/East follow the declared azimuth reference (possibly unknown). Refuses
        missing angles. A provided TVD column is never replaced by this result.
        """
        return minimum_curvature(self.stations)


class GridSurface(TypedData):
    type = 'regular-grid-surface'

    @property
    def values(self): return self.data['values']

    def cell_center(self, row, column):
        """(x, y) of a cell centre; row 0 is the northmost row."""
        c = self.context
        if not (0 <= row < c['nrows'] and 0 <= column < c['ncols']): raise Refused('That cell is outside the grid.')
        return c['x_first_center'] + column * c['cell_size'], c['y_first_center'] - row * c['cell_size']

    def to_numpy(self):
        try: import numpy as np
        except ImportError: raise Refused('Install ophiolite[numpy] for arrays.') from None
        return np.array([math.nan if v is None else v for v in self.values], dtype=float).reshape(self.context['nrows'], self.context['ncols'])

    def to_frame(self):
        pd = self._pandas(); c = self.context
        rows = [(r, k) for r in range(c['nrows']) for k in range(c['ncols'])]
        return pd.DataFrame({'row': [r for r, _ in rows], 'column': [k for _, k in rows],
                             'x': [self.cell_center(r, k)[0] for r, k in rows], 'y': [self.cell_center(r, k)[1] for r, k in rows],
                             'value': pd.array(self.values, dtype='Float64')})


class _Spatial(TypedData):
    def _attribute_columns(self, pd, reserved):
        """Attribute columns keep their written names; a name that collides with a coordinate column gets an 'attribute_' prefix."""
        return {('attribute_' + a['name'] if a['name'] in reserved else a['name']): pd.array(a['values'], dtype='Float64') for a in self.data['attributes']}


class TriangulatedSurface(_Spatial):
    """Vertices (missing z is None) and triangles exactly as written; no geometric repair."""
    type = 'triangulated-surface'

    @property
    def vertices(self): return self.data['vertices']

    @property
    def triangles(self): return self.data['triangles']

    def to_numpy(self):
        try: import numpy as np
        except ImportError: raise Refused('Install ophiolite[numpy] for arrays.') from None
        return (np.array([[math.nan if c is None else c for c in v] for v in self.vertices], dtype=float), np.array(self.triangles, dtype=np.int64))

    def to_frame(self):
        pd = self._pandas()
        return pd.DataFrame({'x': [v[0] for v in self.vertices], 'y': [v[1] for v in self.vertices], 'z': pd.array([v[2] for v in self.vertices], dtype='Float64'),
                             **self._attribute_columns(pd, {'x', 'y', 'z'})})


class PointSet(_Spatial):
    type = 'point-set'

    @property
    def points(self): return self.data['points']

    def to_frame(self):
        pd = self._pandas()
        columns = {'x': [p[0] for p in self.points], 'y': [p[1] for p in self.points]}
        if self.context['z_provided']: columns['z'] = pd.array([p[2] for p in self.points], dtype='Float64')
        return pd.DataFrame({**columns, **self._attribute_columns(pd, set(columns))})


class PolylineSet(TypedData):
    """Fault sticks (E16): sticks in file order, each with its points in file order, indices as written."""
    type = 'polyline-set'

    @property
    def sticks(self): return self.data['sticks']

    def to_frame(self):
        pd = self._pandas()
        rows = [(s['index'], n, p) for s in self.sticks for n, p in enumerate(s['points'])]
        return pd.DataFrame({'stick': [r[0] for r in rows], 'point': [r[1] for r in rows],
                             'x': [r[2]['x'] for r in rows], 'y': [r[2]['y'] for r in rows], 'z': [r[2]['z'] for r in rows]})


class SeismicVolume(TypedData):
    """A seismic volume's description (E16): grid, sample meaning, every header decision and the
    digests of its per-inline chunks. Samples are read as slices (Client.read_slice); the exact
    original is not downloaded (`original` is None) unless read explicitly as the artifact."""
    type = 'seismic-volume'

    @property
    def decisions(self): return self.data['decisions']

    @property
    def inlines(self):
        c = self.context['inline']; return [c['first'] + i * c['step'] for i in range(c['count'])]

    @property
    def crosslines(self):
        c = self.context['crossline']; return [c['first'] + i * c['step'] for i in range(c['count'])]

    @property
    def sample_values(self):
        c = self.context; return [c['first_sample'] + k * c['sample_interval'] for k in range(c['samples'])]

    def __repr__(self):
        c = self.context
        return f'<SeismicVolume {c["inline"]["count"]}×{c["crossline"]["count"]}×{c["samples"]} {c["z_domain"]}>'


class SeismicSlice:
    """One inline, crossline or sample slice (E16) at an exact revision, verified against its volume.
    Values are the exact decoded samples; a slice is not the complete volume (`scope`)."""
    type = 'seismic-slice'

    def __init__(self, value, raw, volume):
        self.value = value; self.raw = raw; self.volume = volume
        self.asset_id, self.revision, self.axis, self.label = value['asset_id'], value['revision'], value['axis'], value['label']
        self.scope = value['scope']; self.sample = value['sample']; self.values = value['values']
        self.rows = (value['rows']['name'], value['rows']['values']); self.columns = (value['columns']['name'], value['columns']['values'])
        self.original_sha256 = value['source_sha256']; self.chunks = value['chunks']

    def to_numpy(self):
        try: import numpy as np
        except ImportError: raise Refused('Install ophiolite[numpy] for arrays.') from None
        return np.array(self.values, dtype=float)

    def value_at(self, row, column):
        """The exact sample at (row label, column label), e.g. (crossline, time) on an inline slice."""
        try: return self.values[self.rows[1].index(row)][self.columns[1].index(column)]
        except ValueError: raise Refused('That position is not on this slice.') from None

    def __repr__(self):
        return f'<SeismicSlice {self.axis} {self.label}: {len(self.rows[1])}×{len(self.columns[1])}>'


CLASSES = {'well-tops': WellTops, 'trajectory': Trajectory, 'regular-grid-surface': GridSurface,
           'triangulated-surface': TriangulatedSurface, 'point-set': PointSet, 'polyline-set': PolylineSet, 'seismic-volume': SeismicVolume}


def minimum_curvature(stations):
    if any(s['inclination'] is None or s['azimuth'] is None for s in stations):
        raise Refused('A station has no inclination or azimuth; the calculation needs every angle.')
    out = [{'md': stations[0]['md'], 'dtvd': 0.0, 'dnorth': 0.0, 'deast': 0.0}]
    for a, b in zip(stations, stations[1:]):
        i1, i2 = math.radians(a['inclination']), math.radians(b['inclination'])
        a1, a2 = math.radians(a['azimuth']), math.radians(b['azimuth'])
        dmd = b['md'] - a['md']
        dl = math.acos(max(-1.0, min(1.0, math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1)))))
        rf = 1.0 if dl < 1e-9 else 2 / dl * math.tan(dl / 2)
        p = out[-1]
        out.append({'md': b['md'], 'dtvd': p['dtvd'] + dmd / 2 * (math.cos(i1) + math.cos(i2)) * rf,
                    'dnorth': p['dnorth'] + dmd / 2 * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf,
                    'deast': p['deast'] + dmd / 2 * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf})
    return out
