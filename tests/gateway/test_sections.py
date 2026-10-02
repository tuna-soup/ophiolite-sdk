"""E53: the Python route against an in-process gateway. A wavelet is uploaded and gains a version through public
upload_data(append_to=..., expected_parent=...); a wedge model is derived from a log and its synthetic from the model
and the wavelet; read_data gives back the computed arrays; an import of a bundle holding all three uploads the model
and the wavelet and reports the synthetic as not imported."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite import synthetics as syn
from ophiolite.bundle import NOT_IMPORTED_SYNTHETIC
from ophiolite.errors import IntegrityConflict, ValidationFailed
from ophiolite.typed import ModelSection, SeismicSection, Wavelet
from project_gateway.tests.test_applications import LAS

ROCKS = [{'name': 'Rodenrijs Claystone', 'vp': 4073, 'density': 2629}, {'name': 'Delft Sandstone', 'vp': 4024, 'density': 2379}]
UPLOAD = dict(attribution='Synthetic', audience=[], rights_confirmed=True)


def test_append_derive_read_back_and_import(web, tmp_path):
    alice = client(web, 'alice', 'delegate')
    w = syn.ricker(30, 0.001, duration=0.128)
    first = alice.upload_data(Wavelet.write(w).bytes, profile='wavelet-text/1', name='Ricker 30 Hz', filename='ricker.txt', **UPLOAD)
    sharper = syn.ricker(35, 0.001, duration=0.128)
    with pytest.raises(ValidationFailed, match='Name the result and the version it replaces.'):
        alice.upload_data(Wavelet.write(sharper).bytes, profile='wavelet-text/1', name='Ricker 30 Hz', append_to=first.asset_id, **UPLOAD)
    second = alice.upload_data(Wavelet.write(sharper).bytes, profile='wavelet-text/1', name='Ricker 30 Hz', append_to=first.asset_id,
                               expected_parent=first.revision, **UPLOAD)
    assert second.asset_id == first.asset_id and second.revision != first.revision
    assert alice.read_data(first.asset_id, second.revision).samples == sharper.samples
    assert alice.read_data(first.asset_id, first.revision).samples == w.samples  # version 1 is kept
    with pytest.raises(IntegrityConflict, match='A newer revision exists'):  # a stale parent is refused
        alice.upload_data(Wavelet.write(syn.ricker(40, 0.001, duration=0.128)).bytes, profile='wavelet-text/1', name='Ricker 30 Hz',
                          append_to=first.asset_id, expected_parent=first.revision, **UPLOAD)

    log = alice.upload_las(LAS.encode(), name='Log', **UPLOAD)
    model = syn.wedge(ROCKS)
    made = alice.publish_derived(ModelSection.write(model), name='Wedge model', from_=[(log.asset_id, log.revision)], method=model.method, command_id='e53-model')
    section = syn.synthetic(model, w)
    synthetic = alice.publish_derived(SeismicSection.write(section), name='Wedge synthetic, 30 Hz Ricker', method=section.method, command_id='e53-synthetic',
                                      from_=[(made.asset_id, made.revision), (first.asset_id, first.revision)])
    read = alice.read_data(synthetic.asset_id, synthetic.revision)
    assert isinstance(read, SeismicSection) and read.grid == section.grid and read.origin == 'synthetic'
    assert syn.tuning_thickness(read).trace == 13 and alice.read_data(made.asset_id, made.revision).grid == model.grid

    bundle = alice.export([(first.asset_id, first.revision, None), (made.asset_id, made.revision, None), (synthetic.asset_id, synthetic.revision, None)], tmp_path / 'b')
    assert bundle.manifest['bundle_version'] == '2.5.0'
    imported = alice.import_bundle(bundle.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert [(r['type'], r['state']) for r in imported] == [('wavelet', 'imported'), ('model-section', 'imported'), ('seismic-section', 'refused')]
    assert imported[2]['reason'] == NOT_IMPORTED_SYNTHETIC
    assert alice.read_data(imported[1]['destination']['asset_id'], imported[1]['destination']['revision']).grid == model.grid
