"""E192 s1 C5 (strategy D6; tests C5 (b), (c)): a bundle entry carries the stated parents of its version, at 1.19 / 2.19.

The writer copies `stated_parents` and `stated_parent_visibility` from the served descriptor into the entry, beside and
never among the parents, and the minor rises to 19 only when they travel. The reader takes them only at 19 or above,
only equal to the descriptor's, and only when each one is a disclosed made-for entry of the descriptor's revision
manifest: a bundle whose made-for entry was hidden (its predicate, reference and salt removed, the file checksums
recomputed) is refused, as a released reader of the pair could otherwise take a stated parent nothing proves was
recorded. Everything here is synthetic.

Mutations (break -> FAIL, restore -> PASS; recorded in the lane's logs/c5-mutations.txt):
a. the reader skips the disclosed check (`if False and any(... not in disclosed ...)`) -> test_c_*;
b. the reader skips the minor check (`< STATED_MINOR` -> `< 0`) -> test_b_*;
c. the writer leaves the minor at the content's (`STATED_MINOR for a in assets` -> `0 for a in assets`) -> test_a_*;
d. the writer copies nothing into the entry -> test_a_*;
e. the reader skips the entry/descriptor equality -> test_b_an_entry_*;
f. the writer's check before writing skipped -> test_b_a_malformed_* ('a parent', 'one field': the descriptor contract
   refuses them in other words; the other four are refused by the bundle's own read after writing with the same
   sentence, nothing kept: recorded)."""
import copy
import hashlib
import json

import pytest
from ophiolite import bundle
from ophiolite.errors import VerificationFailed
from test_bundle import Read, rewrite, typed_read
from test_bundle_provenance import las_item, typed_item
from test_bundle_source_records import entry

DESIGN = {'authority': 'ophiolite:uploaded', 'key': 'synthetic-design', 'revision': 'r-design-1', 'profile': 'las2/1'}
MODEL = {'authority': 'ophiolite:derived', 'key': 'synthetic-model', 'revision': 'r-model-2', 'profile': 'well-tops-csv/1'}


def disclosed(reference, predicate='made-for', salt='5' * 32):
    """A disclosed lineage entry as the gateway serves it: the commitment over the salt, the predicate and the reference."""
    return {'commitment': sha(salt + canonical([predicate, reference])), 'predicate': predicate, 'reference': reference, 'salt': salt}


def listed(d, lineage):
    """The revision manifest (/1) of descriptor D with LINEAGE, digested as the gateway digests it."""
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized')
    reps = [{'id': r['id'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in d['representations'] if r['kind'] == 'normalized']
    body = {'schema': 'ophiolite.revision-manifest/1', 'asset_id': d['asset_id'], 'revision': d['revision'],
            'artifact': {'sha256': artifact['sha256'], 'bytes': artifact['bytes']}, 'representations': sorted(reps, key=lambda r: r['id']),
            'lineage': sorted(e['commitment'] for e in lineage)}
    return {'schema': body['schema'], 'digest': sha(canonical(body)), 'artifact': body['artifact'], 'representations': reps, 'lineage': lineage}


def sha(text): return hashlib.sha256(text.encode()).hexdigest()


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))


def descriptors(read):
    return read._wire_descriptors if hasattr(read, '_wire_descriptors') else [read._wire_descriptor]


def stated(read, refs=(DESIGN,), shown='complete', lineage=None):
    """READ as a gateway after E192 s1 serves it to this SDK: the stated pair on each descriptor, and the made-for
    entries disclosed in each descriptor's revision manifest."""
    entries = [disclosed(r) for r in refs] if lineage is None else lineage
    made = [{**d, 'stated_parents': copy.deepcopy(list(refs)), 'stated_parent_visibility': shown, 'manifest': listed(d, copy.deepcopy(entries))}
            for d in descriptors(read)]
    if hasattr(read, '_wire_descriptors'): read._wire_descriptors = made
    else: read._wire_descriptor = made[0]
    return read


def descriptor_path(opened):
    return next(f['path'] for f in entry(opened.path)['files'] if f['role'] == 'descriptor')


def hide_made_for(root, path):
    """The descriptor's made-for entry reduced to its commitment, the file's checksum and size recomputed: every other
    check of the bundle still passes."""
    target = root / path
    descriptor = json.loads(target.read_text())
    descriptor['manifest']['lineage'] = [{'commitment': e['commitment']} for e in descriptor['manifest']['lineage']]
    target.write_text(json.dumps(descriptor, indent=2) + '\n')
    raw = target.read_bytes()
    rewrite(root, lambda m: [f.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)) for f in m['assets'][0]['files'] if f['path'] == path])


# --- a: written at 1.19 / 2.19, read back -----------------------------------------------------------------------------

def test_a_a_well_log_and_a_typed_bundle_carry_the_stated_parents(tmp_path):
    las = bundle.write_bundle(tmp_path / 'las', [las_item(stated(Read()))])
    assert (las.manifest['schema'], las.manifest['bundle_version']) == (bundle.SCHEMA, '1.19.0')
    held = entry(las.path)
    assert (held['stated_parents'], held['stated_parent_visibility'], held['parents']) == ([DESIGN], 'complete', [])
    assert las.assets[0].stated_parents == [DESIGN]
    typed = bundle.write_bundle(tmp_path / 'typed', [typed_item(stated(typed_read('tops'), [DESIGN, MODEL]))])
    assert (typed.manifest['schema'], typed.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.19.0')
    assert bundle.open_bundle(typed.path).assets[0].stated_parents == [DESIGN, MODEL]


def test_a_without_stated_parents_the_minor_and_the_entry_are_unchanged(tmp_path):
    plain = bundle.write_bundle(tmp_path / 'plain', [las_item(Read())])
    assert plain.manifest['bundle_version'] == '1.0.0' and not set(bundle.STATED_FIELDS) & set(entry(plain.path))
    assert plain.assets[0].stated_parents is None


def test_a_every_one_hidden_travels_as_an_empty_restricted_list(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', [typed_item(stated(typed_read('tops'), [], 'restricted', lineage=[]))])
    assert opened.manifest['bundle_version'] == '2.19.0' and opened.assets[0].stated_parents == []
    assert entry(opened.path)['stated_parent_visibility'] == 'restricted'


# --- b: the minor, the shape and the descriptor -----------------------------------------------------------------------

@pytest.mark.parametrize('kind', ['las', 'typed'])
def test_b_a_manifest_below_19_with_stated_parents_is_refused(tmp_path, kind):
    item = las_item(stated(Read())) if kind == 'las' else typed_item(stated(typed_read('tops')))
    root = bundle.write_bundle(tmp_path / 'b', [item]).path
    rewrite(root, lambda m: m.update(bundle_version=m['bundle_version'].split('.')[0] + '.18.0'))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'Stated parents need bundle version 1.19 or 2.19.'


@pytest.mark.parametrize('case', ['a parent', 'itself', 'twice', 'empty and complete', 'one field', 'an extra key'])
def test_b_a_malformed_pair_is_refused_before_anything_is_written(tmp_path, case):
    read = typed_read('tops'); own = read._wire_descriptor
    refs, shown = {'a parent': ([DESIGN], 'complete'), 'itself': ([{**DESIGN, 'key': own['asset_id'], 'revision': own['revision']}], 'complete'),
                   'twice': ([DESIGN, DESIGN], 'complete'), 'empty and complete': ([], 'complete'),
                   'one field': ([DESIGN], 'complete'), 'an extra key': ([{**DESIGN, 'class': 'witnessed'}], 'complete')}[case]
    stated(read, refs, shown)
    if case == 'a parent': read._wire_descriptor['parents'] = [DESIGN]
    if case == 'one field': read._wire_descriptor.pop('stated_parent_visibility')
    with pytest.raises(VerificationFailed) as refused: bundle.write_bundle(tmp_path / 'b', [typed_item(read)])
    assert str(refused.value) == 'The stated parents are not distinct exact revisions beside the parents.'
    assert not (tmp_path / 'b').exists()


def test_b_an_entry_the_descriptor_does_not_carry_is_refused(tmp_path):
    root = bundle.write_bundle(tmp_path / 'b', [typed_item(stated(typed_read('tops'), [DESIGN, MODEL]))]).path
    rewrite(root, lambda m: m['assets'][0].update(stated_parents=[MODEL]))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == 'The manifest disagrees with a descriptor (stated_parents).'


# --- c: a stated parent without its disclosed made-for entry ----------------------------------------------------------

@pytest.mark.parametrize('kind', ['las', 'typed'])
def test_c_a_hidden_made_for_entry_is_refused_after_rehashing(tmp_path, kind):
    item = las_item(stated(Read())) if kind == 'las' else typed_item(stated(typed_read('tops')))
    opened = bundle.write_bundle(tmp_path / 'b', [item])
    hide_made_for(opened.path, descriptor_path(opened))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(opened.path)
    assert str(refused.value) == 'A stated parent is not a made-for entry of its revision manifest.'


def test_c_a_derived_from_entry_does_not_disclose_a_stated_parent(tmp_path):
    lineage = [disclosed(DESIGN, 'derived-from')]
    with pytest.raises(VerificationFailed) as refused: bundle.write_bundle(tmp_path / 'b', [typed_item(stated(typed_read('tops'), lineage=lineage))])
    assert str(refused.value) == 'A stated parent is not a made-for entry of its revision manifest.'
