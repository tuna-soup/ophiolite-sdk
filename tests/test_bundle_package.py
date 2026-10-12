"""E23c C3: bundle 2.8 carries a recipe-read point set or a Shapefile-read feature set with its package, companion members and
interpretation, and every link between the parts is checked on open (verbatim /1 contract, D4a).

Literals come from the Platform contract fixture point-set-2.* (a synthetic Petrel package; Z is decided from line 2 of its README,
while the real ConSeil README states Z on line 3, which C5 tests). The package rows are built here the way the gateway stores them
(`P/las_uploads.py`: canonical package manifest and interpretation); C4 proves the same against the gateway itself.

Every tampering case is built by `rewrite_consistent`, which recomputes each layer a forger can recompute (file checksums and sizes,
the manifest listing, the descriptor's data digest and, when asked, the package digest everywhere it is written), so only the
intended discrepancy remains. Its control: with that one guard replaced by a no-op, the same bundle opens."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from ophiolite import _core, bundle, bundle_package
from ophiolite.errors import Refused, VerificationFailed
from test_bundle import FIXTURES, typed_items, typed_read

PACKAGE_DIGEST = '90524498601813dd6c8ed5991f5fa7e8499ea2f2f739c4e3b6846056014def63'
RECIPE_SHA = '23d6174b8a62a1399177c1b298f174f23b9d778a62b7422537bc5201c5a9515c'
FROZEN = Path(__file__).parent / 'frozen'
ROLE_SENTENCE = 'Bundle 1.0 carries exactly one original per asset and only known file roles.'
TYPE_SENTENCE = 'An asset has an unknown type.'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def stored_rows(descriptor, data, companions, document=None):
    """The rows the gateway stores for a package read: canonical package manifest, interpretation, one row per companion."""
    package = descriptor['package']
    records = sorted(({'name': m['name'], 'role': m['role'], 'digest': m['sha256'], 'bytes': m['bytes']} for m in package['members']), key=lambda r: r['name'])
    fidelity = data['context']['fidelity']
    if document is not None:
        interpretation = {'schema': 'ophiolite.recipe-execution/1', 'recipe': {'reference': package['recipe']['reference'], 'sha256': package['recipe']['sha256'], 'document': document},
                          'package_digest': package['package_digest'], 'decisions': fidelity['decisions'], 'execution': fidelity['execution']}
    else:
        interpretation = {'schema': 'ophiolite.package-read/1', 'interpretation': data['interpretation'], 'package_digest': package['package_digest'], 'decisions': fidelity.get('decisions') or []}
    rows = {'package': bundle_package.canonical({'schema': 'ophiolite.source-package/1', 'members': records, 'package_digest': package['package_digest']}).encode(),
            'interpretation': bundle_package.canonical(interpretation).encode()}
    rows.update({'companion:' + name: raw for name, raw in companions.items()})
    return rows


def recipe_read(descriptor=None, data=None, companions=None):
    descriptor = descriptor or json.loads(FIXTURES.joinpath('point-set-2.json').read_bytes())
    raw = FIXTURES.joinpath('point-set-2-data.json').read_bytes() if data is None else rehash(descriptor, data)
    points = _core.typed_result(descriptor, raw, FIXTURES.joinpath('point-set-2.original').read_bytes())
    companions = companions or {'point-set-2.crsmeta.xml': FIXTURES.joinpath('point-set-2.crsmeta.xml').read_bytes(),
                                'point-set-2.readme.txt': FIXTURES.joinpath('point-set-2.readme.txt').read_bytes()}
    points.package_rows = stored_rows(descriptor, json.loads(raw), companions, json.loads(FIXTURES.joinpath('point-set-2-recipe.json').read_bytes()))
    return points


def rehash(descriptor, data):
    raw = json.dumps(data).encode()
    next(r for r in descriptor['representations'] if r['kind'] == 'normalized').update(bytes=len(raw), sha256=sha(raw))
    return raw


SHAPEFILE = [('fields.shp', 'primary', None), ('fields.shx', 'companion', b'\x00\x00\x27\x0a shx index'), ('fields.dbf', 'companion', b'\x03 dbf table'),
             ('fields.prj', 'crs-metadata', b'PROJCS["ED50 / UTM zone 31N"]')]


def shapefile_read():
    """A feature set read from a Shapefile's members (E56): the contract fixture, served as the Shapefile reader serves it."""
    descriptor = json.loads(FIXTURES.joinpath('feature-set.json').read_bytes()); data = json.loads(FIXTURES.joinpath('feature-set-data.json').read_bytes())
    original = FIXTURES.joinpath('feature-set.original').read_bytes()
    descriptor['profile'] = descriptor['source_reference']['profile'] = data['source']['profile'] = 'esri-shapefile/1'
    next(r for r in descriptor['representations'] if r['kind'] == 'original').update(profile='esri-shapefile/1', media_type='application/x-esri-shapefile')
    for interpretation in (descriptor['interpretation'], data['interpretation']): interpretation['parsing_policy'] = 'package-strict/1'
    members = sorted(({'name': n, 'role': r, 'sha256': sha(b or original), 'bytes': len(b or original)} for n, r, b in SHAPEFILE), key=lambda m: m['name'])
    descriptor['package'] = {'package_digest': bundle_package.digest_of(members), 'members': members, 'recipe': None, 'status': 'decided', 'unresolved': []}
    features = _core.typed_result(descriptor, rehash(descriptor, data), original)
    features.package_rows = stored_rows(descriptor, data, {n: b for n, r, b in SHAPEFILE if b})
    return features


def item(read):
    return {'asset_id': read._wire_descriptor['asset_id'], 'revision': read._wire_descriptor['revision'], 'curves': None}, read


def written(tmp_path, read=None, name='b'):
    return bundle.write_bundle(tmp_path / name, [item(read or recipe_read())])


def frozen(minor):
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_pkg_2%d' % minor, FROZEN / ('bundle_2_%d.py' % minor))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


# --- round trips ----------------------------------------------------------------------------------------------------

def test_a_recipe_read_point_set_round_trips_with_its_package_and_decisions(tmp_path):
    opened = written(tmp_path)
    assert opened.manifest['bundle_version'] == '2.8.0'
    [asset] = opened.assets
    assert sorted(f['role'] for f in asset.entry['files']) == ['companion', 'companion', 'descriptor', 'interpretation', 'normalized', 'original', 'package']
    package = asset.package
    assert package.digest == PACKAGE_DIGEST and package.recipe['sha256'] == RECIPE_SHA and package.interpretation['recipe']['sha256'] == RECIPE_SHA
    assert package.companions == {'point-set-2.crsmeta.xml': FIXTURES.joinpath('point-set-2.crsmeta.xml').read_bytes(),
                                  'point-set-2.readme.txt': FIXTURES.joinpath('point-set-2.readme.txt').read_bytes()}
    assert [(m['name'], m['role'], m['file']) for m in package.members] == [('point-set-2.crsmeta.xml', 'crs-metadata', 'assets/0/companion-1.bin'),
                                                                           ('point-set-2.original', 'primary', 'assets/0/original.txt'),
                                                                           ('point-set-2.readme.txt', 'readme', 'assets/0/companion-2.bin')]
    z = next(d for d in asset.data.decisions if d.field == 'z_meaning')
    assert (z.selected, z.evidence[0].member, z.evidence[0].locator) == ('time', 'point-set-2.readme.txt', 'line 2')
    assert next(d for d in package.decisions if d['field'] == 'z_meaning')['selected'] == 'time'
    assert asset.original == FIXTURES.joinpath('point-set-2.original').read_bytes()


def test_a_shapefile_package_round_trips_without_a_recipe(tmp_path):
    opened = written(tmp_path, shapefile_read())
    [asset] = opened.assets
    assert opened.manifest['bundle_version'] == '2.8.0' and asset.type == 'feature-set' and asset.package.recipe is None
    assert asset.package.interpretation['schema'] == 'ophiolite.package-read/1'
    assert sorted(m['name'] for m in asset.package.members) == ['fields.dbf', 'fields.prj', 'fields.shp', 'fields.shx']
    assert asset.package.companions == {n: b for n, r, b in SHAPEFILE if b}  # byte-equal
    assert asset.original == FIXTURES.joinpath('feature-set.original').read_bytes() and asset.entry['files'][0]['path'] == 'assets/0/original.shp'


def test_safe_paths_for_long_non_ascii_names_and_eight_members_pack_and_unpack(tmp_path):
    descriptor = json.loads(FIXTURES.joinpath('point-set-2.json').read_bytes()); data = json.loads(FIXTURES.joinpath('point-set-2-data.json').read_bytes())
    companions = {'point-set-2.crsmeta.xml': FIXTURES.joinpath('point-set-2.crsmeta.xml').read_bytes(),
                  'point-set-2.readme.txt': FIXTURES.joinpath('point-set-2.readme.txt').read_bytes()}
    long_name = ('Ölfeld Groningen — Hörizont ' * 8)[:200]
    for k, name in enumerate([long_name, 'deel 2.pdf', 'メモ.txt', 'readme (copy).txt', 'x y z.dat']):
        companions[name] = ('member %d\n' % k).encode()
        descriptor['package']['members'].append({'name': name, 'role': 'companion', 'sha256': sha(companions[name]), 'bytes': len(companions[name])})
    descriptor['package']['members'].sort(key=lambda m: m['name'])
    descriptor['package']['package_digest'] = descriptor['scientific']['fidelity']['execution']['package_digest'] = \
        data['context']['fidelity']['execution']['package_digest'] = bundle_package.digest_of(descriptor['package']['members'])
    opened = written(tmp_path, recipe_read(descriptor, data, companions))
    paths = sorted(f['path'] for f in opened.assets[0].entry['files'])
    assert len(opened.assets[0].package.members) == 8 and all(bundle.PATH.fullmatch(p) for p in paths)
    assert {m['name'] for m in opened.assets[0].package.members} >= {long_name, 'メモ.txt'}
    archive = bundle.pack(opened.path, tmp_path / 'b.zip')
    unpacked = bundle.open_bundle(archive)
    assert unpacked.assets[0].package.companions == opened.assets[0].package.companions == {n: b for n, b in companions.items()}
    assert all((unpacked.path / p).read_bytes() == (opened.path / p).read_bytes() for p in paths)


def test_a_companion_over_the_file_limit_is_refused_at_export_naming_its_size(tmp_path):
    points = recipe_read(); points.package_rows['companion:point-set-2.readme.txt'] = b'x' * (bundle.MAX_FILE_BYTES + 1)
    with pytest.raises(Refused) as refused: written(tmp_path, points)
    assert str(refused.value) == ('The package file point-set-2.readme.txt is 33554433 bytes; a bundle file holds at most 33554432 bytes (32 MiB). '
                                  'Nothing was written.')
    assert not (tmp_path / 'b').exists() and not list(tmp_path.glob('.b.staging-*'))


def test_a_package_read_without_its_rows_and_an_attributed_interpretation_are_refused(tmp_path):
    points = recipe_read(); del points.package_rows
    with pytest.raises(Refused) as refused: written(tmp_path, points)
    assert str(refused.value) == bundle_package.NO_ROWS
    points = recipe_read(); record = json.loads(points.package_rows['interpretation']); record['schema'] = 'ophiolite.recipe-execution/2'
    points.package_rows['interpretation'] = json.dumps(record).encode()
    with pytest.raises(Refused) as refused: written(tmp_path, points)
    assert str(refused.value) == ("This revision's interpretation is recorded as ophiolite.recipe-execution/2, which a bundle cannot carry yet; "
                                  'it can be exported once portable interpretations are supported.')
    assert not (tmp_path / 'b').exists()


def test_import_plan_refuses_a_package_with_its_sentence(tmp_path):
    [step] = bundle.import_plan(written(tmp_path), {})
    assert (step['state'], step['reason']) == ('refused', 'Importing a file that comes with companion files is not available yet.')


def test_released_readers_refuse_the_package_bundle_and_the_current_reader_reads_older_ones(tmp_path):
    points = written(tmp_path, name='points').path; shapes = written(tmp_path, shapefile_read(), name='shapes').path
    seen = {}
    for minor in (4, 5, 6, 7):
        for kind, root in (('point-set', points), ('feature-set', shapes)):
            with pytest.raises(VerificationFailed) as refused: frozen(minor).open_bundle(root)
            seen[(kind, minor)] = str(refused.value)
    assert seen == {('point-set', 4): ROLE_SENTENCE, ('point-set', 5): ROLE_SENTENCE, ('point-set', 6): ROLE_SENTENCE, ('point-set', 7): ROLE_SENTENCE,
                    ('feature-set', 4): TYPE_SENTENCE, ('feature-set', 5): TYPE_SENTENCE, ('feature-set', 6): TYPE_SENTENCE, ('feature-set', 7): ROLE_SENTENCE}
    older = bundle.write_bundle(tmp_path / 'older', typed_items() + [item(typed_read('points')), item(typed_read('feature-set'))])
    assert older.manifest['bundle_version'] == '2.7.0' and all(a.package is None for a in bundle.open_bundle(older.path).assets)


# --- one mutation per link, each with its control ------------------------------------------------------------------

def rewrite_consistent(root, change, *, digest=False):
    """Apply `change(state)` to the bundle at `root` (asset 0), then recompute every layer a forger can: the package digest everywhere
    it is written (digest=True), the descriptor's data digest, and every listed file's sha256 and size. Only the intended discrepancy is left."""
    a = root / 'assets/0'
    manifest = json.loads((root / 'manifest.json').read_text()); entry = manifest['assets'][0]
    docs = {name: json.loads((a / name).read_bytes()) for name in ('descriptor.json', 'data.json', 'package.json', 'interpretation.json') if (a / name).exists()}
    before = copy.deepcopy(docs)
    state = {'manifest': manifest, 'entry': entry, 'block': entry['package'], 'descriptor': docs['descriptor.json'], 'data': docs['data.json'],
             'row': docs.get('package.json'), 'interpretation': docs['interpretation.json'], 'folder': a}
    change(state)
    if digest:
        value = bundle_package.digest_of(state['block']['members'])
        state['block']['package_digest'] = state['descriptor']['package']['package_digest'] = value
        state['data']['context']['fidelity']['execution']['package_digest'] = state['interpretation']['package_digest'] = value
        state['descriptor']['scientific']['fidelity']['execution']['package_digest'] = state['interpretation']['execution']['package_digest'] = value
        if state['row'] is not None:
            state['row'].update(package_digest=value, members=sorted(({'name': m['name'], 'role': m['role'], 'digest': m['sha256'], 'bytes': m['bytes']} for m in state['block']['members']),
                                                                     key=lambda r: r['name']))
    for name in ('data.json', 'package.json', 'interpretation.json'):
        if name in docs and docs[name] != before[name]:
            raw = json.dumps(docs[name]).encode(); (a / name).write_bytes(raw)
            if name == 'data.json': next(r for r in state['descriptor']['representations'] if r['kind'] == 'normalized').update(bytes=len(raw), sha256=sha(raw))
    if docs['descriptor.json'] != before['descriptor.json']: (a / 'descriptor.json').write_text(json.dumps(docs['descriptor.json'], indent=2) + '\n')
    for listed in entry['files']:
        target = root / listed['path']
        if target.exists(): raw = target.read_bytes(); listed.update(sha256=sha(raw), bytes=len(raw))
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return root


def _companion(state, k):
    return next(f for f in state['entry']['files'] if f['path'] == 'assets/0/companion-%d.bin' % k)


def swap_companions(state):
    """Swap the two companion files and their records (every record of their digests, names kept): only the package digest can tell."""
    one, two = state['folder'] / 'companion-1.bin', state['folder'] / 'companion-2.bin'
    first, second = one.read_bytes(), two.read_bytes(); one.write_bytes(second); two.write_bytes(first)
    a, b = sha(first), sha(second)
    for key in ('block', 'descriptor', 'data', 'row', 'interpretation'):
        text = json.dumps(state[key]).replace(a, '@').replace(b, a).replace('@', b)
        text = text.replace('"bytes": %d, "file": "assets/0/companion-1.bin"' % len(first), '"bytes": %d, "file": "assets/0/companion-1.bin"' % len(second))
        text = text.replace('"bytes": %d, "file": "assets/0/companion-2.bin"' % len(second), '"bytes": %d, "file": "assets/0/companion-2.bin"' % len(first))
        replaced = json.loads(text); state[key].clear() if isinstance(state[key], dict) else None; state[key].update(replaced)
    for record in (state['descriptor']['package']['members'], state['row']['members']):
        for m in record:
            size = 'bytes'
            if m['name'] == 'point-set-2.crsmeta.xml': m[size] = len(second)
            if m['name'] == 'point-set-2.readme.txt': m[size] = len(first)


def change_selected_value(state):
    z = next(d for d in state['interpretation']['decisions'] if d['field'] == 'z_meaning'); z['selected'] = 'depth'


def primary_from_a_copy(state):
    raw = (state['folder'] / 'original.txt').read_bytes(); (state['folder'] / 'companion-9.bin').write_bytes(raw)
    state['entry']['files'].append({'path': 'assets/0/companion-9.bin', 'role': 'companion', 'sha256': sha(raw), 'bytes': len(raw)})
    next(m for m in state['block']['members'] if m['role'] == 'primary')['file'] = 'assets/0/companion-9.bin'


def recipe_changed(state):
    recipe = state['interpretation']['recipe']; recipe['document']['profile'] += ' '
    recipe['sha256'] = sha(bundle_package.canonical(recipe['document']).encode())


def package_file_removed(state):
    (state['folder'] / 'package.json').unlink()
    state['entry']['files'] = [f for f in state['entry']['files'] if f['role'] != 'package']; state['row'] = None


def unlisted_companion(state):
    (state['folder'] / 'companion-9.bin').write_bytes(b'not a member\n')
    state['entry']['files'].append({'path': 'assets/0/companion-9.bin', 'role': 'companion', 'sha256': sha(b'not a member\n'), 'bytes': 13})


def member_twice(state):
    for members in (state['block']['members'], state['descriptor']['package']['members']):
        members.append(copy.deepcopy(members[0]))


def member_bytes_changed(state):
    (state['folder'] / 'companion-1.bin').write_bytes(b'<CRSMeta><Code>EPSG:28992</Code></CRSMeta>\n')


def block_recipe_changed(state):
    state['block']['recipe'] = {**state['block']['recipe'], 'sha256': '0' * 64}


def package_row_changed(state):
    state['row']['members'][0]['bytes'] += 1


MUTATIONS = {  # case: (change, recompute the package digest, guard, sentence)
    'swap two companion files and their records': (swap_companions, False, 'digest', bundle_package.DIGEST),
    'change a selected value in the interpretation': (change_selected_value, False, 'decisions', bundle_package.DECISIONS),
    'serve the primary from a companion copy': (primary_from_a_copy, False, 'primary', bundle_package.PRIMARY),
    'change the recipe document and its sha in the interpretation only': (recipe_changed, False, 'recipe', bundle_package.RECIPE),
    'remove the package file': (package_file_removed, False, 'shape', bundle_package.SHAPE),
    'add a companion file that is no member': (unlisted_companion, False, 'unlisted', bundle_package.UNLISTED),
    'list a member twice': (member_twice, True, 'duplicate', bundle_package.DUPLICATE),
    'change a member file but not its record': (member_bytes_changed, False, 'member-files', bundle_package.MEMBER_FILE),
    'change the recipe pin in the block only': (block_recipe_changed, False, 'descriptor', bundle_package.DESCRIPTOR % 'recipe'),
    'change the package file only': (package_row_changed, False, 'package-row', bundle_package.PACKAGE_ROW),
}


@pytest.mark.parametrize('case', sorted(MUTATIONS))
def test_each_link_refuses_its_mutation_and_the_control_shows_the_bundle_reaches_it(tmp_path, monkeypatch, case):
    change, digest, guard, sentence = MUTATIONS[case]
    root = rewrite_consistent(written(tmp_path).path, change, digest=digest)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == sentence
    original = bundle_package._guard
    monkeypatch.setattr(bundle_package, '_guard', lambda name, check: None if name == guard else original(name, check))
    assert bundle.open_bundle(root).assets[0].type == 'point-set'  # the control: only that guard stood in the way


def test_an_interpretation_of_an_unknown_kind_is_refused_never_read_as_another(tmp_path):
    root = rewrite_consistent(written(tmp_path).path, lambda s: s['interpretation'].update(schema='ophiolite.portable-interpretation/1'))
    with pytest.raises(VerificationFailed, match="^The interpretation file is of a kind this reader does not know"): bundle.open_bundle(root)


def test_package_files_on_an_asset_without_a_package_are_refused(tmp_path):
    root = written(tmp_path, typed_read('points')).path
    raw = b'{}'; (root / 'assets/0/package.json').write_bytes(raw)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['assets'][0]['files'].append({'path': 'assets/0/package.json', 'role': 'package', 'sha256': sha(raw), 'bytes': 2})
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle_package.SHAPE


def test_written_package_manifests_satisfy_the_two_eight_contract(tmp_path):
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads(Path(bundle.__file__).with_name('contracts').joinpath('bundles/v2/manifest-schema.json').read_bytes())
    for name, read in (('points', recipe_read()), ('shapes', shapefile_read())):
        manifest = written(tmp_path, read, name).manifest
        jsonschema.Draft202012Validator(schema).validate(manifest)
        assert manifest['assets'][0]['package']['interpretation'] == 'assets/0/interpretation.json'
