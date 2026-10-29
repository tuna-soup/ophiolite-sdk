"""E128: the preservation matrix, one row per process kind: what `ophiolite.readers.read` keeps of a file of that kind.

Each row is settled from the kind's profile, its server grammar and the readers registry's declarations (the `sources`
of the row). `fixed` are header lines or keys as `(name, required|optional)`; `columns` the fields of one body record,
with `extra` saying what happens to a column the grammar does not name (`kept`, `refused`, `named-attributes`,
`named-curves`, or None where a kind has no columns); `sections` LAS's sections; `nulls` how a missing value is
written; `declared` the declarations the kind takes (none: any declaration is refused); `parity` the server reader
the same bytes are compared with; `outside_parity` what is kept here and not by the server. Importing this contacts
nothing and opens no file.
"""

_SPATIAL = ('crs', 'xy_unit', 'z_meaning', 'z_unit', 'positive', 'vertical_datum')
_PROFILES = 'ophiolite-platform/contracts/profiles/v1/'
_TR = 'ophiolite-connectors/src/asset_connectors/typed_reader.py'
_SEC = 'ophiolite-connectors/src/asset_connectors/sections.py'
_REG = 'ophiolite-connectors/src/asset_connectors/readers/registry.json readers[%s].declared'
_AXES = tuple((key, 'required') for key in ('domain', 'first_sample', 'sample_interval', 'samples', 'traces', 'horizontal',
                                             'horizontal_first', 'horizontal_step'))


def _sources(kind, grammar):
    return {'profile': _PROFILES + kind.split('/')[0] + '.json', 'grammar': grammar, 'declared': _REG % kind}


MATRIX = {
    'points-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('x', 'y'), 'optional': ('z',), 'extra': 'named-attributes'},
        'sections': (), 'nulls': ('an empty z cell', 'an empty attribute cell'), 'declared': _SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('points-csv/1', _TR + ':335 _points')},
    'mesh-text/1': {
        'result': 'Mesh',
        'fixed': (('# ophiolite-mesh 1', 'required'), ('attributes', 'optional'), ('vertices', 'required'),
                  ('triangles', 'required')),
        'columns': {'required': ('x', 'y', 'z'), 'optional': (), 'extra': 'named-attributes'},
        'sections': (), 'nulls': ('- for z', '- for an attribute value'), 'declared': _SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('mesh-text/1', _TR + ':295 _mesh')},
    'esri-ascii-grid/1': {
        'result': 'Grid',
        'fixed': (('ncols', 'required'), ('nrows', 'required'), ('xllcorner|xllcenter', 'required'),
                  ('yllcorner|yllcenter', 'required'), ('cellsize', 'required'), ('nodata_value', 'optional')),
        'columns': {'required': ('value',), 'optional': (), 'extra': None},
        'sections': (), 'nulls': ('a cell equal to nodata_value',), 'declared': _SPATIAL,
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('esri-ascii-grid/1', _TR + ':230 _grid')},
    'well-tops-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('name', 'md'), 'optional': ('tvd', 'source'), 'extra': 'kept'},
        'sections': (), 'nulls': ('an empty tvd cell', 'an empty source cell', 'an empty extra cell'),
        'declared': ('depth_unit', 'depth_basis', 'depth_datum'),
        'parity': 'read_typed', 'outside_parity': ('extra columns, as text',),
        'sources': _sources('well-tops-csv/1', _TR + ':114 _tops')},
    'deviation-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('md', 'inclination', 'azimuth'), 'optional': ('tvd',), 'extra': 'refused'},
        'sections': (), 'nulls': ('an empty inclination cell', 'an empty azimuth cell', 'an empty tvd cell'),
        'declared': ('depth_unit', 'azimuth_reference', 'depth_datum'),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('deviation-csv/1', _TR + ':157 _trajectory')},
    'opendtect-faultsticks/1': {
        'result': 'Sticks', 'fixed': (),
        'columns': {'required': ('x', 'y', 'z', 'stick'), 'optional': ('node',), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': _SPATIAL,
        'parity': 'read_typed', 'outside_parity': ('the node field, as text',),
        'sources': _sources('opendtect-faultsticks/1', _TR + ':426 _polylines')},
    'las2/1': {
        'result': 'Las',
        'fixed': (('VERS 1.2, 2.0, or 3.0 in the LAS 2 layout', 'required'),
                  ('WRAP NO, or YES read by the declared curve count', 'required'),
                  ('DLM SPACE or TAB', 'optional')),
        'columns': {'required': (), 'optional': (), 'extra': 'named-curves'},
        'sections': (('~V', 'required'), ('~W', 'required'), ('~C', 'required'), ('~P', 'optional'), ('~O', 'optional'),
                     ('~A', 'required')),
        'nulls': ('a data value equal to the ~W NULL value',), 'declared': (),
        'parity': 'read_las',
        'outside_parity': ('~P lines as written', '~O lines as written', 'the descriptions of ~V, ~W and ~C lines'),
        'sources': _sources('las2/1', 'ophiolite-connectors/src/asset_connectors/las_reader.py:64 read_las')},
    'well-location/1': {
        'result': 'Location',
        'fixed': (('x', 'required'), ('y', 'required'), ('crs', 'required'), ('elevation_reference', 'required')),
        'columns': {'required': (), 'optional': (), 'extra': None},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('well-location/1', _TR + ':366 _well_location')},
    'wavelet-text/1': {
        'result': 'Wavelet',
        'fixed': (('# ophiolite-wavelet 1', 'required'), ('kind', 'required'), ('dt', 'required'), ('t0', 'required'),
                  ('polarity', 'required'), ('frequency_hz', 'optional'), ('corners_hz', 'optional'),
                  ('samples', 'required')),
        'columns': {'required': ('sample',), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('wavelet-text/1', _SEC + ':64 read_wavelet')},
    'model-section-text/1': {
        'result': 'ModelSection',
        'fixed': (('# ophiolite-model-section 1', 'required'),) + _AXES + (('rocks', 'required'), ('grid', 'required')),
        'columns': {'required': ('index', 'vp', 'density', 'name'), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('model-section-text/1', _SEC + ':130 read_model_section')},
    'seismic-section-text/1': {
        'result': 'SeismicSection',
        'fixed': (('# ophiolite-seismic-section 1', 'required'),) + _AXES
                 + (('origin', 'optional'), ('polarity', 'optional'), ('grid', 'required')),
        'columns': {'required': ('sample',), 'optional': (), 'extra': 'refused'},
        'sections': (), 'nulls': (), 'declared': (),
        'parity': 'read_typed', 'outside_parity': ('origin and polarity absent stay absent',),
        'sources': _sources('seismic-section-text/1', _SEC + ':160 read_seismic_section')},
    'time-depth-csv/1': {
        'result': 'Table', 'fixed': (),
        'columns': {'required': ('depth', 'time'), 'optional': ('velocity',), 'extra': 'refused'},
        'sections': (), 'nulls': ('an empty velocity cell',),
        'declared': ('depth_type', 'depth_unit', 'time_kind', 'time_unit', 'datum', 'seismic_reference_elevation'),
        'parity': 'read_typed', 'outside_parity': (),
        'sources': _sources('time-depth-csv/1', 'ophiolite-connectors/src/asset_connectors/time_depth.py:135 read_csv')},
}

# The order of rules.json `process_kinds`, without well-residual/1 (ophiolite.residuals reads that one).
KINDS = ('points-csv/1', 'mesh-text/1', 'esri-ascii-grid/1', 'well-tops-csv/1', 'deviation-csv/1', 'opendtect-faultsticks/1',
         'las2/1', 'well-location/1', 'wavelet-text/1', 'model-section-text/1', 'seismic-section-text/1', 'time-depth-csv/1')
