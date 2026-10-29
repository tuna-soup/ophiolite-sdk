"""E108 S1 (5R-8): a version a source procedure made travels through export, offline verification and import with the
`sourced_by` the exporting project recorded: its own, or the one its import recorded, never a new one. Nothing else in
the bundle changes (no attachment, no new manifest version)."""
import pytest
from ophiolite import bundle
from test_bundle import Read, typed_read
from test_bundle_provenance import descriptors, las_item, typed_item

SOURCED = {'digest': '5a' * 32, 'label': 'Survey share', 'version_label': 'Release 2', 'version': 2, 'rules_version': '1.0.0',
           'runner': 'alice', 'system': 'Team survey share', 'role': 'well_a'}


def made_by_a_source(read, imported=False):
    """`read` as the gateway serves a file a source procedure made (or, imported, as its origin recorded it)."""
    for d in descriptors(read):
        acquisition = {'kind': 'user-upload', 'filename': 'well_a.json', 'attribution': 'NAM', 'well_notes': '', 'identity': 'alice', 'uploaded_at': 1.0, 'rights': 'confirmed'}
        if imported: acquisition['origin'] = {'kind': 'portable-bundle', 'manifest_sha256': 'd' * 64, 'asset_id': 'a1', 'revision': 'b' * 64,
                                              'exporter': 'ophiolite-sdk', 'sourced_by': SOURCED}
        else: acquisition['sourced_by'] = SOURCED
        d['acquisition'] = acquisition
    return read


@pytest.mark.parametrize('imported', [False, True], ids=['made-here', 'imported'])
@pytest.mark.parametrize('kind', ['las', 'tops'])
def test_a_source_made_version_is_imported_with_its_sourced_by_as_recorded(tmp_path, kind, imported):
    """Mutation: import_plan without the `sourced_by` origin; the step's origin has none (red)."""
    item = las_item(made_by_a_source(Read(), imported)) if kind == 'las' else typed_item(made_by_a_source(typed_read('tops'), imported))
    plain = las_item() if kind == 'las' else typed_item(typed_read('tops'))
    before = bundle.write_bundle(tmp_path / 'plain', [plain]).manifest['bundle_version']
    bundle.write_bundle(tmp_path / 'b', [item])
    opened = bundle.open_bundle(tmp_path / 'b')  # verified offline
    assert opened.manifest['bundle_version'] == before and 'read_by' not in opened.manifest['assets'][0]
    assert bundle.recorded_source(opened.assets[0].data._wire_descriptor if kind == 'tops' else next(iter(opened.assets[0].curves.values())).wire_descriptor) == SOURCED
    [step] = bundle.import_plan(opened, {})
    assert step['state'] == 'ready' and step['origin']['sourced_by'] == SOURCED and 'read_by' not in step['origin'] and 'provenance' not in step
    [without] = bundle.import_plan(bundle.open_bundle(tmp_path / 'plain'), {})
    assert 'sourced_by' not in without['origin']  # an import without one sends what it always sent
