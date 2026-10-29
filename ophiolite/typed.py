"""Typed scientific data (E11): well tops, trajectories and regular-grid surfaces; wavelets and sections (E53); time-depth
tables (E57).

Objects hold the exact original bytes, the verified descriptor and the served
normalized data. Nothing is converted: units, references and coordinate systems
are the declared ones and "unknown" stays unknown. Importing this module does
not contact a server.
"""
import math
from .errors import Refused
from . import recipes
from .transform import vertical_depth as _vertical_depth
from . import geometry as _geometry  # E119a: the one trajectory geometry
from . import sources as _sources  # E58b: a kept table is read with the frame code of tables read as tables

TYPES = ('well-tops', 'trajectory', 'regular-grid-surface', 'triangulated-surface', 'point-set', 'polyline-set', 'seismic-volume',
         'wavelet', 'model-section', 'seismic-section', 'well-location', 'time-depth', 'feature-set', 'table', 'well-path',
         'well-residual',  # E119b
         'well-set')  # E119a s1
WAVELET_DT = (0.0005, 0.01)  # E53 D7: a bounded spectrum (at most 1001 bins of 1 Hz)
WAVELET_SAMPLES = (3, 4095)


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

    def vertical_depth(self, mds, source='calculated', origin_tvd=None, unit=None):
        """E64: vertical depth at each measured depth in MDS (in UNIT, default the survey's): `calculated` by minimum
        curvature from the angles, or `file`, the survey's own vertical depth (None where a station does not state it).
        The two are never substituted for each other; past the last station is None. The start is never assumed:
        see `ophiolite.transform.vertical_depth`, which also returns the count beyond the survey."""
        if source not in ('calculated', 'file'): raise Refused('Vertical depth is "calculated" or "file".')
        unit = unit or self.context.get('depth_unit')
        out = _vertical_depth(self.stations, mds, origin_tvd, survey_unit=self.context.get('depth_unit'), log_unit=unit)
        return out['calculated' if source == 'calculated' else 'from_file']


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


class Evidence:
    """One observation behind a decision (E23a): a line of a package file, cited by member name, digest
    and line, or the uploader's declaration. `sufficient` is False for a statement the recipe does not
    accept on its own."""

    def __init__(self, value):
        self.value, self.source, self.role, self.sufficient = value['value'], value['source'], value['role'], value['sufficient']
        self.member, self.digest, self.locator, self.text = value.get('member'), value.get('digest'), value.get('locator'), value.get('text')

    def __repr__(self):
        return f'<Evidence {self.value!r} from {self.member + ", " + self.locator if self.member else "the declaration"}>'


class Decision:
    """How one field of context was decided (E23a): every observation, the one selected and why, or
    'needs-decision' with nothing selected. Nothing is filled in by default."""

    def __init__(self, value):
        self.field, self.selected, self.selected_by, self.reason, self.status = value['field'], value['selected'], value['selected_by'], value['reason'], value['status']
        self.evidence = [Evidence(o) for o in value['observations']]

    @property
    def decided(self): return self.status == 'decided'

    def __repr__(self):
        label = recipes.field_label(self.field)
        if not self.decided: return f'<Decision {label}: needs a decision>'
        reason = f' because {self.reason!r}' if self.selected_by in ('declaration', 'selection') and self.reason else ''
        return f'<Decision {label}: {recipes.value_label(self.field, self.selected)}{reason}>'

    def details(self):
        """The raw particulars (field key, how it was chosen, the stored reason) for Technical details."""
        return {'field': self.field, 'selected': self.selected, 'selected_by': self.selected_by, 'reason': self.reason, 'status': self.status}


class Recipe:
    """The import recipe a revision was read with (E23a): a project recipe at an exact revision, or None
    for the profile's default, and the digest of the exact rules applied. The rules themselves are the
    revision's 'interpretation' representation."""

    def __init__(self, value):
        reference = value['reference']
        self.asset_id, self.revision = (reference['asset_id'], reference['revision']) if reference else (None, None)
        self.sha256 = value['sha256']

    @property
    def default(self): return self.asset_id is None

    def __repr__(self):
        return '<Recipe the default reading of this kind of file>' if self.default else '<Recipe a reading saved in the project>'

    def details(self):
        """The raw particulars (asset id, revision, digest of the rules applied) for Technical details."""
        return {'asset_id': self.asset_id, 'revision': self.revision, 'sha256': self.sha256}


class PointSet(_Spatial):
    """Points in file order. point-set/2 (E23a, a recipe-read Petrel or OpendTect export) adds number,
    text and category attributes with their exact source labels, and the decisions behind its context."""
    type = 'point-set'
    DTYPES = {'number': 'Float64', 'text': 'string', 'category': 'category'}

    @property
    def points(self): return self.data['points']

    @property
    def version(self): return 2 if self.data['schema'] == 'ophiolite.point-set/2' else 1

    @property
    def attributes(self):
        """[{name, source_name, kind}] in file order (point-set/1 attributes are numbers named as written)."""
        if self.version == 1: return [{'name': a['name'], 'source_name': a['name'], 'kind': 'number'} for a in self.data['attributes']]
        return [{k: a[k] for k in ('name', 'source_name', 'kind')} for a in self.data['attributes']]

    @property
    def decisions(self):
        return [Decision(d) for d in self.context['fidelity'].get('decisions') or []] if self.version == 2 else []

    @property
    def status(self):
        """'decided', or 'needs-decision' while any field of context is undecided (point-set/2)."""
        return self.context['fidelity']['execution']['status'] if self.version == 2 else 'decided'

    @property
    def unresolved(self):
        return list(self.context['fidelity']['execution']['unresolved']) if self.version == 2 else []

    @property
    def recipe(self):
        package = (self._wire_descriptor or {}).get('package')
        return Recipe(package['recipe']) if package else None

    def to_frame(self):
        pd = self._pandas()
        columns = {'x': [p[0] for p in self.points], 'y': [p[1] for p in self.points]}
        if self.context['z_provided']: columns['z'] = pd.array([p[2] for p in self.points], dtype='Float64')
        if self.version == 1: return pd.DataFrame({**columns, **self._attribute_columns(pd, set(columns))})
        # point-set/2 names are unique, grammar-safe and never a coordinate (the contract refuses otherwise);
        # the exact labels travel in frame.attrs['source_names'].
        frame = pd.DataFrame({**columns, **{a['name']: pd.array(a['values'], dtype=self.DTYPES[a['kind']]) for a in self.data['attributes']}})
        frame.attrs['source_names'] = {a['name']: a['source_name'] for a in self.data['attributes']}
        return frame

    def __repr__(self):
        pending = ' (needs a decision: ' + ', '.join(recipes.field_label(f) for f in self.unresolved) + ')' if self.unresolved else ''
        return f'<PointSet {self.context["count"]} points{pending}>'


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


def _numpy():
    try: import numpy as np
    except ImportError: raise Refused('Install ophiolite[numpy] for arrays.') from None
    return np


class Wavelet(TypedData):
    """A wavelet (E53): the stored samples every `dt` seconds from `t0`, with the declared kind, frequencies and polarity.
    Nothing is resampled; the declared frequency is what the file says, the spectrum is what the samples say."""
    type = 'wavelet'

    @property
    def samples(self): return self.data['samples']

    def __len__(self): return len(self.samples)

    def __getitem__(self, index): return self.samples[index]

    def __iter__(self): return iter(self.samples)

    @property
    def times(self):
        c = self.context; return [c['t0'] + k * c['dt'] for k in range(len(self.samples))]

    def to_numpy(self): return _numpy().array(self.samples, dtype=float)

    def spectrum(self):
        """Magnitude of the direct DFT of the stored samples on a 1 Hz grid from 0 Hz to Nyquist: (frequencies, magnitudes)."""
        np = _numpy(); dt = self.context['dt']; n = len(self.samples)
        if not WAVELET_DT[0] <= dt <= WAVELET_DT[1]: raise Refused('A wavelet must be sampled every 0.0005 to 0.01 s.')
        if not WAVELET_SAMPLES[0] <= n <= WAVELET_SAMPLES[1]: raise Refused('A wavelet has 3 to 4095 samples.')
        frequencies = np.arange(int(math.floor(0.5 / dt + 1e-9)) + 1, dtype=float)
        phase = np.exp(-2j * math.pi * np.outer(frequencies, np.arange(n) * dt))
        return frequencies, np.abs(phase @ np.asarray(self.samples, dtype=float))

    def peak_frequency(self):
        """The strongest frequency in Hz, read as the 1 Hz grid point (the first if two are equal)."""
        frequencies, magnitudes = self.spectrum(); return float(frequencies[int(magnitudes.argmax())])

    def frequency_note(self):
        """The strongest frequency beside the declared one, e.g. 'strongest 40.0, declared 30'; None when nothing single is declared."""
        declared = self.context['frequency_hz']
        return None if declared is None else f'strongest {self.peak_frequency()}, declared {declared:g}'

    def __repr__(self):
        c = self.context; declared = f' {c["frequency_hz"]:g} Hz' if c['frequency_hz'] is not None else ''
        return f'<Wavelet {c["kind"]}{declared}, {c["sample_count"]} samples every {c["dt"]:g} s>'


class _Section(TypedData):
    """A section's grid: one row per vertical sample, one value per trace, on the declared axes."""
    @property
    def grid(self): return self.data['grid']

    @property
    def sample_values(self):
        c = self.context; return [c['first_sample'] + k * c['sample_interval'] for k in range(c['samples'])]

    @property
    def horizontal_values(self):
        c = self.context; return [c['horizontal_first'] + k * c['horizontal_step'] for k in range(c['traces'])]

    def __repr__(self):
        c = self.context
        return f'<{type(self).__name__} {c["samples"]}×{c["traces"]} {c["domain"]}>'


class ModelSection(_Section):
    """A rock model section (E53): rocks (P-wave velocity m/s, density kg/m3) and a grid of rock indices."""
    type = 'model-section'

    @property
    def rocks(self): return self.data['rocks']

    def rock(self, index):
        try: return next(r for r in self.rocks if r['index'] == index)
        except StopIteration: raise Refused('That rock is not in this model.') from None

    def to_numpy(self): return _numpy().array(self.grid, dtype=int)


class SeismicSection(_Section):
    """A seismic section (E53): every sample exactly as stored, its origin ('synthetic' only when computed) and polarity."""
    type = 'seismic-section'

    @property
    def origin(self): return self.context['origin']

    @property
    def polarity(self): return self.context['polarity']

    def to_numpy(self): return _numpy().array(self.grid, dtype=float)


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


class WellLocation(TypedData):
    """One well's surface point as its file states it (E74b: a position file or a corrected position): `x`, `y` in
    `crs`, with the elevation reference. Nothing is converted; `original` holds the file's exact bytes."""
    type = 'well-location'

    @property
    def x(self): return self.data['x']

    @property
    def y(self): return self.data['y']

    def __repr__(self):
        return '<WellLocation %s, %s %s>' % (self.x, self.y, self.context['crs'])


class TimeDepth(TypedData):
    """A time-depth table of one wellbore (E57): depth and time pairs in file order, strictly increasing in both, with
    velocity as stated (a missing cell stays missing). Depth type and unit, time kind and unit and the datum are the
    uploader's declarations; "unknown" stays unknown and nothing is converted."""
    type = 'time-depth'

    @property
    def pairs(self):
        velocity = self.data['velocity'] or [None] * len(self.data['depth'])
        return list(zip(self.data['depth'], self.data['time'], velocity))

    def __len__(self): return len(self.data['depth'])

    def to_frame(self):
        pd = self._pandas()
        velocity = self.data['velocity'] or [None] * len(self.data['depth'])
        return pd.DataFrame({'depth': pd.array(self.data['depth'], dtype='float64'), 'time': pd.array(self.data['time'], dtype='float64'),
                             'velocity': pd.array(velocity, dtype='Float64')})

    def __repr__(self):
        c = self.context
        return '<TimeDepth %d pairs, %s %s depth, %s %s time>' % (c['count'], c['depth_type'], c['depth_unit'], c['time_kind'], c['time_unit'])



class WellPath(TypedData):
    """A well path given as positions (E125 s3a): stations in file order, measured depth strictly increasing, each with
    x (easting) and y (northing) in the declared coordinate system and map unit, and TVDSS, positive downward below the
    declared datum, in the depth unit. The coordinate system, units and datums are the uploader's declarations; "unknown"
    stays unknown and nothing is converted or reprojected. `tvdss_range` in the context is the smallest and largest TVDSS."""
    type = 'well-path'

    @property
    def stations(self): return self.data['stations']

    def __len__(self): return len(self.stations)

    def to_frame(self):
        pd = self._pandas()
        return pd.DataFrame({key: pd.array([s[key] for s in self.stations], dtype='float64') for key in ('md', 'x', 'y', 'tvdss')})

    def __repr__(self):
        c = self.context
        return '<WellPath %d stations, %s, MD from %s, TVDSS below %s>' % (c['count'], c['crs'], c['md_reference'], c['tvdss_datum'])


class WellResidual(TypedData):
    """A residual result (E119b): one row per top in order, each the residual top.md - md of the used crossing of the
    surface in metres, or a reason it was not computed (with the depth range between, for the reasons that carry one).
    `display_unit` is how the result is shown; the values are metres and nothing is converted."""
    type = 'well-residual'

    @property
    def rows(self): return self.data['rows']

    @property
    def surface(self): return self.data['surface']

    def __len__(self): return len(self.rows)

    def to_frame(self):
        pd = self._pandas()
        rows = self.rows
        return pd.DataFrame({'wellbore': pd.array([r['wellbore'] for r in rows], dtype='string'),
                             'occurrence': pd.array([r['occurrence'] for r in rows], dtype='Int64'),
                             'top_md': pd.array([r['top']['md'] if r['top'] else None for r in rows], dtype='Float64'),
                             'crossing_md': pd.array([r['crossings'][r['used']]['md'] if r['used'] is not None else None for r in rows], dtype='Float64'),
                             'residual': pd.array([r['residual'] for r in rows], dtype='Float64'),
                             'reason': pd.array([r['reason'] for r in rows], dtype='string')})

    def __repr__(self):
        c = self.context
        return '<WellResidual %s: %d of %d rows computed, %d wellbores>' % (c['formation'], c['computed'], c['count'], c['members'])


class WellSet(TypedData):
    """A well set (E119a): its author's own list of wellbores under their wells, each with the exact trajectory version
    and the frame that places it in the world, or neither. Read as it was saved; private to its author in this version
    (`client.well_sets`)."""
    type = 'well-set'

    @property
    def label(self): return self.data['label']

    @property
    def members(self): return self.data['members']

    def __len__(self): return len(self.members)

    def to_frame(self):
        pd = self._pandas()
        members = self.members
        traj = lambda m, k: m['trajectory'][k] if m['trajectory'] else None
        return pd.DataFrame({'well': pd.array([m['well'] for m in members], dtype='string'),
                             'wellbore': pd.array([m['wellbore'] for m in members], dtype='string'),
                             'trajectory': pd.array([traj(m, 'asset_id') for m in members], dtype='string'),
                             'revision': pd.array([traj(m, 'revision') for m in members], dtype='string'),
                             'crs': pd.array([m['frame']['crs'] if m['frame'] else None for m in members], dtype='string')})

    def __repr__(self):
        c = self.context
        return '<WellSet %r: %d wellbores, %d with a trajectory>' % (self.label, c['count'], c['with_trajectory'])


class FeatureSet(TypedData):
    """Map features (E56): points, lines or polygons of one family from a Shapefile, a GeoPackage layer or a GeoJSON file,
    in file order with their coordinates as stored (nothing reprojected, rings not reoriented) and their attribute values
    by field. A feature without geometry keeps its row with `geometry` None."""
    type = 'feature-set'
    DTYPES = {'text': 'string', 'integer': 'Int64', 'number': 'Float64', 'date': 'string', 'boolean': 'boolean'}

    @property
    def features(self): return self.data['features']

    @property
    def fields(self):
        """[{name, source_name, kind}] in file order."""
        return [{k: f[k] for k in ('name', 'source_name', 'kind')} for f in self.context['fields']]

    def __len__(self): return len(self.features)

    def to_frame(self):
        """One row per feature: `index`, `geometry_type` (missing when the feature has no geometry), then each field in
        file order. Coordinates stay in `features`; the exact field labels travel in frame.attrs['source_names']."""
        pd = self._pandas()
        columns = {'index': pd.array([f['index'] for f in self.features], dtype='Int64'),
                   'geometry_type': pd.array([(f['geometry'] or {}).get('type') for f in self.features], dtype='string')}
        for field in self.fields:
            columns[field['name']] = pd.array([f['properties'].get(field['name']) for f in self.features], dtype=self.DTYPES[field['kind']])
        frame = pd.DataFrame(columns)
        frame.attrs['source_names'] = {f['name']: f['source_name'] for f in self.fields}
        return frame

    def __repr__(self):
        c = self.context
        return '<FeatureSet %d features, %s, %s>' % (c['count'], '/'.join(c['geometry_types']) or 'no geometry', c['crs'])


class Table(TypedData):
    """A table kept as it is (E58b): the exact original file, and every column, the key, the declarations (unit,
    meaning, missing-value marker per column) and the rows of the columns read, in file order, as the server stored them.
    Values are as the file wrote them: a declared missing-value marker stays a value until `to_frame(missing="declared")`.
    `rows` are dicts by column name (integers as int, decimals and dates as their exact text); `not_read` lists the
    columns whose type is not read, and reading such a table warns once naming them. `download` saves it as Parquet or
    CSV, written by the server; no pyarrow is needed here."""
    type = 'table'
    _frame = staticmethod(_sources._table_frame)  # the one frame code of tables read as tables (E50b1)

    def __init__(self, descriptor, data, original, **kwargs):
        super().__init__(descriptor, data, original, **kwargs)
        columns, read, rows = _sources.verified_data_table(data, schema='ophiolite.table-file/1')
        logical = [c['logical'] for c in columns if c['read']]
        self.columns, self.read_columns = [dict(c) for c in columns], read
        self.key = tuple(data['key']) if data['key'] is not None else None
        self.declarations = data['declarations']
        coordinates = self.declarations.get('coordinates')
        self.crs = coordinates['crs'] if coordinates else None
        self.not_read = [{'name': c['name'], 'db_type': c['db_type']} for c in columns if not c['read']]
        self.rows = [{name: _sources._decoded(kind, value) for name, kind, value in zip(read, logical, row)} for row in rows]
        self.source_rows = list(data['source_rows'])
        self.profile = self.context['profile']
        wire = kwargs.get('wire_descriptor') or {}
        self.asset_id, self.revision = wire.get('asset_id'), wire.get('revision')
        self.sha256 = next((r['sha256'] for r in wire.get('representations', ()) if r.get('kind') == 'normalized'), None)
        if self.not_read:
            import warnings
            warnings.warn('Not read: %s; their type is not supported yet.' % ', '.join('%s (%s)' % (c['name'], c['db_type']) for c in self.not_read),
                          UserWarning, stacklevel=4)

    def __len__(self): return len(self.rows)

    @property
    def units(self):
        """{column: unit} as declared; a column without a declared unit is left out."""
        return {name: note['unit'] for name, note in (self.declarations.get('columns') or {}).items() if note.get('unit')}

    def to_frame(self, missing=None, decimal='exact'):
        """A DataFrame of the columns read, typed as a table read as a table (string, Int64, Float64, Decimal objects,
        datetimes): `missing="declared"` sets values equal to a column's declared marker to NA, `decimal="float"` turns
        decimals into floats (lossy); both are recorded in `frame.attrs["transformations"]` and `rows` never changes."""
        pd = self._pandas()
        if missing not in (None, 'declared') or decimal not in ('exact', 'float'):
            raise Refused('Use missing=None or "declared", and decimal="exact" or "float".')
        return type(self)._frame(self, pd, missing, decimal)

    def download(self, destination, format='parquet'):
        """Save this exact revision as one Parquet or CSV file at `destination` (Client.export_file); checked against the
        digest and the revision the server states, or nothing is saved."""
        client = getattr(self, '_client', None)
        if client is None: raise Refused('This table was not read from a server; read it with client.read_data(asset, revision).')
        return client.export_file(self.asset_id, self.revision, destination, format=format)

    def __repr__(self):
        return '<Table %d rows, %d columns read%s, %s>' % (len(self.rows), len(self.read_columns),
                                                          ', %d not read' % len(self.not_read) if self.not_read else '', self.profile)


CLASSES = {'well-tops': WellTops, 'trajectory': Trajectory, 'regular-grid-surface': GridSurface,
           'triangulated-surface': TriangulatedSurface, 'point-set': PointSet, 'polyline-set': PolylineSet, 'seismic-volume': SeismicVolume,
           'wavelet': Wavelet, 'model-section': ModelSection, 'seismic-section': SeismicSection, 'well-location': WellLocation,
           'time-depth': TimeDepth, 'feature-set': FeatureSet, 'table': Table, 'well-path': WellPath,
           'well-residual': WellResidual,  # E119b
           'well-set': WellSet}  # E119a s1


def minimum_curvature(stations):
    """[{md, dtvd, dnorth, deast}]: each station's offsets from the first by minimum curvature, computed by the one
    trajectory geometry (`ophiolite.geometry`, E119a). Refuses a missing angle; no dogleg limit applies here."""
    if any(s['inclination'] is None or s['azimuth'] is None for s in stations):
        raise Refused('A station has no inclination or azimuth; the calculation needs every angle.')
    return [{'md': s['md'], 'dtvd': tvd, 'dnorth': north, 'deast': east}
            for s, (east, north, tvd) in zip(stations, _geometry.minimum_curvature(stations))]


# E30b: each type writes the exact file an upload of that type would be (ophiolite.writers); publish it with
# Client.publish_derived. The writers need every declaration (write "unknown" when it is unknown).
from . import writers as _writers
WellTops.write = staticmethod(_writers.write_tops)
Trajectory.write = staticmethod(_writers.write_survey)
GridSurface.write = staticmethod(_writers.write_grid)
TriangulatedSurface.write = staticmethod(_writers.write_mesh)
PointSet.write = staticmethod(_writers.write_points)
PolylineSet.write = staticmethod(_writers.write_sticks)
Wavelet.write = staticmethod(_writers.write_wavelet)  # E53
ModelSection.write = staticmethod(_writers.write_model_section)
SeismicSection.write = staticmethod(_writers.write_seismic_section)
WellLocation.write = staticmethod(_writers.write_location)  # E105a
