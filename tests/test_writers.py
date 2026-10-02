"""E30b: the writers produce the exact grammar the readers parse, refuse what the format cannot carry, and
publish_derived needs a command id. Oracles are independent of the writers (expected cell centres, the
written lines themselves)."""
import inspect
import pytest
from ophiolite import writers
from ophiolite.bundle import Curve
from ophiolite.errors import ValidationFailed
from ophiolite.publish import derive_request
from ophiolite.typed import GridSurface, PointSet, PolylineSet, TriangulatedSurface, WellTops, Trajectory

SPATIAL = dict(crs='EPSG:28992', xy_unit='m', z_unit='m', z_meaning='depth', positive='down', vertical_datum='unknown')


def lines(written): return written.bytes.decode().splitlines()


def test_a_grid_is_written_row_by_row_from_the_north_with_its_origin_and_registration():
    # 3 columns × 2 rows, origin deliberately offset: lower-left corner (1000.5, 4999.25), cell 25.
    g = GridSurface.write([[1, 2, None], [4, 5.5, 6]], ncols=3, nrows=2, x_origin=1000.5, y_origin=4999.25, cell_size=25, **SPATIAL)
    assert g.profile == 'esri-ascii-grid/1' and g.declared == {k: v for k, v in SPATIAL.items() if v != 'unknown'}
    assert lines(g) == ['ncols 3', 'nrows 2', 'xllcorner 1000.5', 'yllcorner 4999.25', 'cellsize 25', 'NODATA_value -9999', '1 2 -9999', '4 5.5 6']
    # the north-west cell's centre, computed out of band: x = 1000.5 + 12.5, y = 4999.25 + 25 + 12.5
    first_center = (1000.5 + 25 / 2, 4999.25 + 25 * (2 - 1) + 25 / 2)
    assert first_center == (1013.0, 5036.75)
    centred = GridSurface.write([[1, 2, 3], [4, 5, 6]], ncols=3, nrows=2, x_origin=1013.0, y_origin=5011.75, cell_size=25, registration='center', **SPATIAL)
    assert lines(centred)[2:4] == ['xllcenter 1013', 'yllcenter 5011.75']


def test_a_grid_value_equal_to_nodata_or_a_wrong_count_is_refused():
    with pytest.raises(ValidationFailed): GridSurface.write([1, -9999, 3, 4], ncols=2, nrows=2, x_origin=0, y_origin=0, cell_size=1, **SPATIAL)
    with pytest.raises(ValidationFailed): GridSurface.write([1, 2, 3], ncols=2, nrows=2, x_origin=0, y_origin=0, cell_size=1, **SPATIAL)


def test_every_declaration_is_required_and_unknown_is_a_valid_answer():
    with pytest.raises(ValidationFailed, match='Declare the'): PointSet.write([(1, 2)], crs='EPSG:28992')
    written = PointSet.write([(1, 2)], crs='unknown', xy_unit='unknown', z_unit='unknown', z_meaning='unknown', positive='unknown', vertical_datum='unknown')
    assert written.declared == {} and lines(written) == ['x,y', '1,2']
    with pytest.raises(ValidationFailed): WellTops.write([{'name': 'A', 'md': 1}], depth_unit='m')  # no depth basis


def test_a_mesh_keeps_triangle_order_and_writes_a_missing_z_as_a_dash():
    m = TriangulatedSurface.write([(0, 0, 100), (10, 0, None), (0, 10, 110)], [(2, 0, 1), (1, 2, 0)], attributes={'amp': [1, None, 0.5]}, **SPATIAL)
    assert lines(m) == ['# ophiolite-mesh 1', 'attributes amp', 'vertices', '0 0 100 1', '10 0 - -', '0 10 110 0.5', 'triangles', '2 0 1', '1 2 0']
    with pytest.raises(ValidationFailed): TriangulatedSurface.write([(0, 0, 1), (1, 0, 1)], [(0, 1, 5)], **SPATIAL)


def test_points_tops_and_surveys_write_their_csv():
    assert lines(PointSet.write([(1, 2, 3), (4, 5, None)], attributes={'phi': [0.1, None]}, **SPATIAL)) == ['x,y,z,phi', '1,2,3,0.1', '4,5,,']
    assert lines(WellTops.write([{'name': 'Top A', 'md': 100.5}, {'name': 'Top B', 'md': 102, 'tvd': 99}], depth_unit='m', depth_basis='other')) == ['name,md,tvd', 'Top A,100.5,', 'Top B,102,99']
    with pytest.raises(ValidationFailed): WellTops.write([{'name': 'A, B', 'md': 1}], depth_unit='m', depth_basis='other')
    assert lines(Trajectory.write([{'md': 0, 'inclination': 0, 'azimuth': 0}, {'md': 100, 'inclination': None, 'azimuth': None}], depth_unit='m', azimuth_reference='grid-north', depth_datum='unknown')) == \
        ['md,inclination,azimuth', '0,0,0', '100,,']


def test_a_fault_stick_with_a_missing_coordinate_is_refused():
    written = PolylineSet.write([{'index': 3, 'points': [(1.5, 2, 3), (4, 5, 6)]}], **SPATIAL)
    assert lines(written) == ['1.5 2.0 3.0 3', '4.0 5.0 6.0 3']
    with pytest.raises(ValidationFailed, match='missing coordinate'): PolylineSet.write([{'index': 1, 'points': [(1, 2, None), (4, 5, 6)]}], **SPATIAL)
    with pytest.raises(ValidationFailed): PolylineSet.write([{'index': 1, 'points': [(1, 2, 3)]}], **SPATIAL)


def test_a_curve_keeps_its_units_and_a_value_equal_to_the_null_marker_is_refused():
    las = Curve.write([100, 100.5, 101], {'GR': ('gAPI', [1, None, 30]), 'RHOB': ('g/cm3', [2.3, 2.4, 2.5])}, depth_unit='ft')
    text = lines(las)
    assert 'DEPT.ft : depth' in text and 'GR.gAPI : GR' in text and 'RHOB.g/cm3 : RHOB' in text and 'STRT.ft 100 : start' in text
    assert text[-3:] == ['100 1 2.3', '100.5 -999.25 2.4', '101 30 2.5'] and las.profile == 'las2/1'
    with pytest.raises(ValidationFailed, match='null marker'): Curve.write([1, 2], {'GR': ('gAPI', [-999.25, 3])}, depth_unit='m')
    with pytest.raises(ValidationFailed, match='depth unit'): Curve.write([1, 2], {'GR': ('gAPI', [1, 3])})


def test_publish_derived_has_no_default_command_id():
    from ophiolite.client import Client
    parameter = inspect.signature(Client.publish_derived).parameters['command_id']
    assert parameter.default is inspect.Parameter.empty and parameter.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError): Client.publish_derived(object(), PointSet.write([(1, 2)], **{k: 'unknown' for k in SPATIAL}), name='x', from_=[('a', '0' * 64)], method={'name': 'm'})


def test_the_request_names_the_file_parents_and_method_exactly():
    written = PointSet.write([(1, 2)], **SPATIAL)
    body, headers = derive_request('p', written, name='Result', from_=[('a', '0' * 64), {'asset_id': 'b', 'revision': '1' * 64}], method={'name': 'Gridding', 'library': 'scipy'}, command_id='c-1')
    assert body['derived_from'] == [{'asset_id': 'a', 'revision': '0' * 64}, {'asset_id': 'b', 'revision': '1' * 64}] and body['output_bytes'] == len(written.bytes)
    assert body['declared'] == written.declared and headers['Content-Type'] == 'application/octet-stream'
    with pytest.raises(ValidationFailed): derive_request('p', written, name='R', from_=[('a', '0' * 64)] * 2, method={'name': 'm'}, command_id='c')
    with pytest.raises(ValidationFailed): derive_request('p', written, name='R', from_=[('a', '0' * 64)], method={'name': 'm', 'declared': False, 'library': 'x'}, command_id='c')
    with pytest.raises(ValidationFailed): derive_request('p', written, name='R', from_=[('a', '0' * 64)], method={'name': 'm'}, command_id='c', new_version_of='x')


# --- E53: wavelet, model section and seismic section ----------------------------------------------------------------

def read_back(written):
    """The pinned Connectors reader, as the server runs it on an upload."""
    from asset_connectors.typed_reader import read_typed
    return read_typed(written.profile, written.bytes, written.declared)


def test_the_three_writers_write_what_the_connectors_reader_reads_back_exactly():
    from ophiolite import synthetics as syn
    from ophiolite.typed import ModelSection, SeismicSection, Wavelet
    w = syn.ricker(30, 0.001, duration=0.128)
    model = syn.wedge([{'name': 'Rodenrijs Claystone', 'vp': 4073, 'density': 2629}, {'name': 'Delft Sandstone', 'vp': 4024, 'density': 2379}])
    section = syn.synthetic(model, w)
    written = Wavelet.write(w)
    assert written.profile == 'wavelet-text/1' and written.declared == {}
    assert lines(written)[:7] == ['# ophiolite-wavelet 1', 'kind ricker', 'frequency_hz 30', 'dt 0.001', 't0 -0.064', 'polarity impedance-increase-positive', 'samples']
    context, data, _ = read_back(written)
    assert data['samples'] == w.samples and context['sample_count'] == 129 and context['t0'] == w.context['t0']
    context, data, _ = read_back(ModelSection.write(model))
    assert data['grid'] == model.grid and data['rocks'] == model.rocks and context['horizontal_step'] == 25.0
    written = SeismicSection.write(section)
    assert 'origin synthetic' in lines(written) and written.profile == 'seismic-section-text/1'
    context, data, _ = read_back(written)
    assert data['grid'] == section.grid and (context['origin'], context['polarity'], context['minimum']) == ('synthetic', 'impedance-increase-positive', section.context['minimum'])
    ormsby = Wavelet.write(syn.ormsby([5, 10, 40, 50], 0.002, 101))
    assert 'corners_hz 5 10 40 50' in lines(ormsby) and read_back(ormsby)[1]['samples'] == syn.ormsby([5, 10, 40, 50], 0.002, 101).samples
    plain = SeismicSection.write([[0.0, 1.5], [2.0, -1.0]], domain='depth', first_sample=1000, sample_interval=4, horizontal='trace-number',
                                 horizontal_first=1, horizontal_step=1, polarity='unknown')
    assert lines(plain) == ['# ophiolite-seismic-section 1', 'domain depth', 'first_sample 1000', 'sample_interval 4', 'samples 2', 'traces 2',
                            'horizontal trace-number', 'horizontal_first 1', 'horizontal_step 1', 'polarity unknown', 'grid', '0 1.5', '2 -1']
    assert read_back(plain)[0]['origin'] == 'not-stated'


SECTION = dict(domain='time', first_sample=0, sample_interval=0.001, horizontal='distance', horizontal_first=0, horizontal_step=25, polarity='unknown')


@pytest.mark.parametrize('call,sentence', [
    (lambda: writers.write_wavelet([0.0, 1.0, 0.0], kind='other', t0=-0.001, polarity='unknown'), 'Declare the sample interval; nothing is inferred.'),
    (lambda: writers.write_wavelet([0.0, 1.0, 0.0], kind='other', dt=0.001, t0=-0.001), 'Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.'),
    (lambda: writers.write_wavelet([0.0, float('nan'), 0.0], kind='other', dt=0.001, t0=-0.001, polarity='unknown'), 'A sample must be finite.'),
    (lambda: writers.write_wavelet([0.0, 1.0, 0.0], kind='other', dt=0.02, t0=-0.02, polarity='unknown'), 'A wavelet must be sampled every 0.0005 to 0.01 s.'),
    (lambda: writers.write_wavelet([0.0, 1.0, 0.0, 0.0], kind='other', dt=0.001, t0=-0.001, polarity='unknown'), 'A wavelet has an odd number of samples, so one sample is its centre.'),
    (lambda: writers.write_seismic_section([[0.0]], **{**SECTION, 'domain': None}), 'Declare whether the vertical axis is time or depth; nothing is inferred.'),
    (lambda: writers.write_seismic_section([[0.0]], **{**SECTION, 'sample_interval': None}), 'Declare the sample interval; nothing is inferred.'),
    (lambda: writers.write_seismic_section([[0.0]], **{**SECTION, 'polarity': None}), 'Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.'),
    (lambda: writers.write_seismic_section([[0.0, float('nan')]], **SECTION), 'A sample must be finite.'),
    (lambda: writers.write_seismic_section([[0.0, 1.0], [2.0]], **SECTION), 'Every grid row needs one value per trace.'),
    (lambda: writers.write_seismic_section([[0.0] * 1000] * 1001, **SECTION), 'A section holds at most 1,000,000 samples.'),
    (lambda: writers.write_model_section([{'index': 1, 'name': 'Shale', 'vp': 3000, 'density': 2400}], [[1, 2]], **{k: v for k, v in SECTION.items() if k != 'polarity'}),
     'Every grid cell names a listed rock.'),
    (lambda: writers.write_model_section([{'index': 1, 'name': 'Shale', 'vp': 3000, 'density': 2400}], [[1]], **{k: v for k, v in SECTION.items() if k not in ('polarity', 'domain')}),
     'Declare whether the vertical axis is time or depth; nothing is inferred.'),
])
def test_each_missing_declaration_is_refused_with_its_sentence(call, sentence):
    with pytest.raises(ValidationFailed) as error: call()
    assert error.value.violations == (sentence,)
