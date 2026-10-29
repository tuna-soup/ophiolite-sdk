"""E107a C6b: bundle 2.9 carries the original a file read on a computer was read from, beside the recorded reading.

The writer adds one `provenance` file and the entry's `read_by` only for an exported typed or LAS asset whose original
was kept; every other export keeps its version (B3: a LAS-only export with one is schema 2, 2.9.0). The reader binds the
file to `read_by.original`, to the descriptor's reading and to its manifest listing (B1). Import restores it as the
re-uploaded original's attachment with `origin.read_by` as recorded (B2); a package import stays refused (B5). Released
2.x readers refuse a 2.9 bundle by its file role (R5-3); the acceptance control proves that is the only reason (B4)."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.errors import VerificationFailed
from ophiolite.models.generated import PortableBundleManifestV2
from test_bundle import Read, rewrite, typed_read
from test_bundle_package import recipe_read

FROZEN = Path(__file__).parent / 'frozen'
ROLE_SENTENCE = 'Bundle 1.0 carries exactly one original per asset and only known file roles.'
PDF = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Title (Groningen end of well report HON-GT-01) >>\nendobj\n' + b'0' * 400


def sha(raw): return hashlib.sha256(raw).hexdigest()


def reading(raw=PDF, kept=True):
    return {'digest': 'e' * 64, 'label': 'Groningen report reader', 'version_label': 'Release 3', 'version': 3, 'rules_version': '1.0.0',
            'runner': 'ophiolite-sdk', 'original': {'name': 'end of well report.pdf', 'bytes': len(raw), 'sha256': sha(raw)},
            'conversion': 'c' * 64, 'role': 'log', **({'kept': sha(raw)} if kept else {})}


def descriptors(read):
    return read._wire_descriptors if hasattr(read, '_wire_descriptors') else [read._wire_descriptor]


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))


def listing(d, raw, rows):
    """The revision manifest the gateway serves for a kept reading: the served representation, a package read's stored rows
    and the `provenance` row (C4)."""
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized')
    reps = [{'id': r['id'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in d['representations'] if r['kind'] == 'normalized']
    reps += [{'id': name, 'sha256': sha(row), 'bytes': len(row)} for name, row in rows.items()] + [{'id': 'provenance', 'sha256': sha(raw), 'bytes': len(raw)}]
    lineage = []
    for parent in d['parents']:
        salt = '6' * 32
        lineage.append({'commitment': sha((salt + canonical(['derived-from', parent])).encode()), 'predicate': 'derived-from', 'reference': parent, 'salt': salt})
    body = {'schema': 'ophiolite.revision-manifest/1', 'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': {'sha256': artifact['sha256'], 'bytes': artifact['bytes']},
            'representations': sorted(reps, key=lambda r: r['id']), 'lineage': sorted(e['commitment'] for e in lineage)}
    return {'schema': body['schema'], 'digest': sha(canonical(body).encode()), 'artifact': body['artifact'], 'representations': reps, 'lineage': lineage}


def read_on_a_computer(read, raw=PDF, kept=True, imported=False):
    """`read` as the gateway serves a file read on a computer: the descriptor's acquisition holds the reading (or, for an
    import, its origin does) and, when kept, its manifest lists the `provenance` row; the export fetched those bytes."""
    record = reading(raw, kept)
    for d in descriptors(read):
        acquisition = {'kind': 'user-upload', 'filename': 'tops.csv', 'attribution': 'NAM', 'well_notes': '', 'identity': 'bob', 'uploaded_at': 1.0, 'rights': 'confirmed'}
        if imported: acquisition['origin'] = {'kind': 'portable-bundle', 'manifest_sha256': 'd' * 64, 'asset_id': 'a1', 'revision': 'b' * 64,
                                              'exporter': 'ophiolite-sdk', 'read_by': record}
        else: acquisition['read_by'] = record
        d['acquisition'] = acquisition
        if kept: d['manifest'] = listing(d, raw, getattr(read, 'package_rows', None) or {})
    if kept: read.provenance = raw
    return read


def las_item(read=None):
    read = read or Read(); d = read._wire_descriptors[0]
    return {'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, read


def typed_item(read):
    return {'asset_id': read._wire_descriptor['asset_id'], 'revision': read._wire_descriptor['revision'], 'curves': None}, read


def las_bundle(tmp_path, name='b', **options):
    return bundle.write_bundle(tmp_path / name, [las_item(read_on_a_computer(Read(), **options))])


def provenance_files(opened, index=0):
    return [f for f in opened.manifest['assets'][index]['files'] if f['role'] == 'provenance']


# --- writing and reading ---------------------------------------------------------------------------------------------

def test_a_kept_las_reading_is_written_as_schema_two_nine_and_reads_back_byte_equal(tmp_path):
    opened = las_bundle(tmp_path)
    assert (opened.manifest['schema'], opened.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.9.0')  # B3: an attachment forces schema 2
    entry = opened.manifest['assets'][0]
    assert entry['type'] == 'well-log' and entry['read_by'] == reading()
    [kept] = provenance_files(opened)
    assert kept['path'] == 'assets/0/provenance.pdf' and 'curve' not in kept and (kept['sha256'], kept['bytes']) == (sha(PDF), len(PDF))
    [asset] = opened.assets
    assert asset.provenance == PDF and asset.read_by == reading()
    PortableBundleManifestV2.model_validate(opened.manifest)  # the 2.9 contract


def test_a_kept_typed_reading_round_trips_at_two_nine(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', [typed_item(read_on_a_computer(typed_read('tops')))])
    assert opened.manifest['bundle_version'] == '2.9.0' and len(provenance_files(opened)) == 1
    assert opened.assets[0].provenance == PDF and opened.assets[0].read_by == reading()


def test_an_imported_reading_is_exported_as_recorded_never_as_a_new_one(tmp_path):
    """B2: the entry's reading is projected from the item's own reading, or from the reading its import recorded."""
    opened = bundle.write_bundle(tmp_path / 'b', [typed_item(read_on_a_computer(typed_read('tops'), imported=True))])
    assert opened.manifest['assets'][0]['read_by'] == reading() and opened.assets[0].provenance == PDF


@pytest.mark.parametrize('kind', ['las', 'tops'])
def test_an_unkept_reading_and_a_plain_export_keep_their_version_and_carry_no_reading(tmp_path, kind):
    def write(name, unkept):
        read = Read() if kind == 'las' else typed_read('tops')
        if unkept: read_on_a_computer(read, kept=False)
        return bundle.write_bundle(tmp_path / name, [las_item(read) if kind == 'las' else typed_item(read)])
    plain, unkept = write('plain', False), write('unkept', True)
    version = '1.0.0' if kind == 'las' else '2.0.0'
    for opened in (plain, unkept):
        assert opened.manifest['bundle_version'] == version and 'read_by' not in opened.manifest['assets'][0] and provenance_files(opened) == []
    assert [(f['path'], f['role']) for f in plain.manifest['assets'][0]['files']] == [(f['path'], f['role']) for f in unkept.manifest['assets'][0]['files']]


def test_a_recipe_read_point_set_with_its_original_carries_both_role_sets_and_its_import_stays_refused(tmp_path):
    """R5-2 as B5: export and open only; a package import is refused with its sentence."""
    opened = bundle.write_bundle(tmp_path / 'b', [typed_item(read_on_a_computer(recipe_read()))])
    roles = sorted(f['role'] for f in opened.manifest['assets'][0]['files'])
    assert roles == ['companion', 'companion', 'descriptor', 'interpretation', 'normalized', 'original', 'package', 'provenance']
    assert opened.manifest['bundle_version'] == '2.9.0' and opened.assets[0].provenance == PDF and opened.assets[0].package is not None
    [step] = bundle.import_plan(opened, {})
    assert (step['state'], step['reason']) == ('refused', bundle.NOT_IMPORTED_PACKAGE)


def test_the_import_plan_restores_the_original_beside_the_reading_as_recorded(tmp_path):
    [step] = bundle.import_plan(las_bundle(tmp_path), {})
    assert step['state'] == 'ready' and step['provenance'] == PDF and step['origin']['read_by'] == reading()
    [plain] = bundle.import_plan(bundle.write_bundle(tmp_path / 'plain', [las_item()]), {})
    assert 'provenance' not in plain and 'read_by' not in plain['origin']  # an import without one sends what it always sent


# --- B1: the attachment is bound to its reading, the descriptor and its manifest ------------------------------------

def substituted(root):
    other = PDF.replace(b'0' * 400, b'1' * 400)
    (root / 'assets/0/provenance.pdf').write_bytes(other)
    rewrite(root, lambda m: next(f for f in m['assets'][0]['files'] if f['role'] == 'provenance').update(sha256=sha(other), bytes=len(other)))


def duplicated(root):
    (root / 'assets/0/provenance-2.pdf').write_bytes(PDF)
    rewrite(root, lambda m: m['assets'][0]['files'].append({'path': 'assets/0/provenance-2.pdf', 'role': 'provenance', 'sha256': sha(PDF), 'bytes': len(PDF)}))


def missing(root):
    rewrite(root, lambda m: m['assets'][0].update(files=[f for f in m['assets'][0]['files'] if f['role'] != 'provenance']))
    (root / 'assets/0/provenance.pdf').unlink()


def without_reading(root):
    rewrite(root, lambda m: m['assets'][0].pop('read_by'))


def entry_disagrees(root):
    rewrite(root, lambda m: m['assets'][0]['read_by'].update(version=4))


def on_a_curve(root):
    rewrite(root, lambda m: next(f for f in m['assets'][0]['files'] if f['role'] == 'provenance').update(curve='GR'))


def descriptor_disagrees(tmp_path):
    """The descriptor's manifest lists another original than the one carried (and named by the reading)."""
    read = read_on_a_computer(Read())
    read._wire_descriptors[0]['manifest']['representations'][1]['sha256'] = 'a' * 64
    return read


REFUSED = {
    substituted: bundle.PROVENANCE_OTHER,  # the checksum was recomputed: the reading, its `kept` and the listing catch it
    duplicated: bundle.PROVENANCE_SHAPE,
    missing: bundle.PROVENANCE_SHAPE,
    without_reading: ROLE_SENTENCE,  # a provenance file is a known role only beside a reading
    entry_disagrees: 'The manifest disagrees with a descriptor (read_by).',
    on_a_curve: bundle.PROVENANCE_SHAPE,
}


@pytest.mark.parametrize('change', list(REFUSED), ids=lambda f: f.__name__)
def test_an_altered_attachment_is_refused_with_its_sentence(tmp_path, change):
    root = las_bundle(tmp_path).path
    change(root)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == REFUSED[change]


def test_a_substitute_beside_an_unlisted_reading_is_refused_by_the_reading_alone(tmp_path):
    """No manifest and no `kept` digest (a descriptor served without one): only `read_by.original` binds the bytes."""
    read = read_on_a_computer(Read()); d = read._wire_descriptors[0]
    d.pop('manifest'); d['acquisition']['read_by'].pop('kept')
    root = bundle.write_bundle(tmp_path / 'b', [las_item(read)]).path
    substituted(root)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle.PROVENANCE_OTHER


def test_a_descriptor_whose_manifest_lists_another_original_is_refused_at_export(tmp_path):
    with pytest.raises(VerificationFailed) as refused: bundle.write_bundle(tmp_path / 'b', [las_item(descriptor_disagrees(tmp_path))])
    assert str(refused.value) == bundle.PROVENANCE_OTHER and not (tmp_path / 'b').exists()


# --- R5-3, B4: released readers refuse a 2.9 bundle by its file role ------------------------------------------------

def frozen(minor, source=None):
    path = FROZEN / ('bundle_2_%d.py' % minor)
    spec = importlib.util.spec_from_loader('ophiolite._frozen_bundle_prov_2%d' % minor, loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source if source is not None else path.read_text(), str(path), 'exec'), module.__dict__)
    return module


def _history():
    spec = importlib.util.spec_from_file_location('sdk_history', Path(__file__).resolve().parents[1] / 'tools/history.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_the_frozen_two_eight_reader_is_the_released_file():
    history = _history()
    released = history.show(Path(__file__).parents[1], 'a3ae1793e', 'ophiolite/bundle.py')  # E23c: the 2.8 reader
    if released is not None: assert released == (FROZEN / 'bundle_2_8.py').read_bytes()
    else: assert not history.FULL, history.missing('a3ae1793e')
    assert sha((FROZEN / 'bundle_2_8.py').read_bytes()) == 'a7358d33f3fc3cdb9fe0287f9da27c8e835a3a672ec1ec780173aaa4dfc60b3f'


KNOWN = "known = {'original', 'descriptor', 'normalized'} | (set(PACKAGE_ROLES) if kind in PACKAGE_TYPES else set())"


@pytest.mark.parametrize('minor', [7, 8])
def test_the_released_two_seven_and_two_eight_readers_refuse_a_two_nine_las_bundle_by_its_file_role(tmp_path, minor):
    root = las_bundle(tmp_path).path
    with pytest.raises(VerificationFailed) as refused: frozen(minor).open_bundle(root)
    assert str(refused.value) == ROLE_SENTENCE
    plain = bundle.write_bundle(tmp_path / 'plain', [las_item()]).path
    assert [a.asset_id for a in frozen(minor).open_bundle(plain).assets] == [Read()._wire_descriptors[0]['asset_id']]  # older bundles still read


def test_acceptance_control_the_two_eight_copy_that_knows_the_role_opens_it(tmp_path):
    """B4: the refusal above is by file role and nothing else: the same reader, told the role, opens the bundle."""
    source = (FROZEN / 'bundle_2_8.py').read_text()
    assert source.count(KNOWN) == 1
    told = frozen(8, source.replace(KNOWN, KNOWN + " | {'provenance'}"))
    opened = told.open_bundle(las_bundle(tmp_path).path)
    assert [a.asset_id for a in opened.assets] == [Read()._wire_descriptors[0]['asset_id']]
