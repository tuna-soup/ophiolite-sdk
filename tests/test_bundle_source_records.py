"""E122 s5b: bundle 1.10 / 2.10 carries each exported version's source record as the gateway served it, unchanged.

The writer puts `assets[i].source_record` = {schema, asset_id, revision, record} only on a version that has a record and
raises the minor to 10 only then (D1, D2); an older gateway without the provenance route leaves records out with one
warning and `observations.source_records_omitted`, which follows the observation rule (R2.3). The reader binds the
wrapper to its entry and checks the record as `source-provenance/1` says, adding no rule of its own (D4, T4b's parity
table against the Platform schema). Released readers open the same export with records as without (T6)."""
import copy
import hashlib
import json
import warnings
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote

import anyio
import httpx
import pytest
from ophiolite import Client, bundle
from ophiolite.aio import AsyncClient
from ophiolite.errors import PermissionRefused, Refused, Unavailable, VerificationFailed
from test_bundle import Read, _history, rewrite, typed_read, typed_items
from test_bundle_compat import frozen
from test_bundle_provenance import las_item, read_on_a_computer, typed_item
from test_seismic import encode, mock, served, volume

FROZEN = Path(__file__).parent / 'frozen'
SCHEMA = 'ophiolite.source-provenance/1'
OLD = 'this server has no source records'
WARNING = 'Source records were left out of this bundle: this server has no source records.'
RECORD = {'schema': SCHEMA,
          'identity': {'source_system': 'upload', 'source_instance': None, 'id_scheme': 'source-path', 'source_object_id': {'path': 'wells/tops.csv', 'part': None}},
          'content': {'content_sha256': 'a' * 64, 'source_version': None}, 'context': {'comparison': 'comparison/1', 'context_sha256': 'b' * 64}}
NATIVE = {'schema': SCHEMA,
          'identity': {'source_system': 'application:qgis-plugin', 'source_instance': '/projects/groningen.qgz', 'id_scheme': 'source-native',
                       'source_object_id': {'container': 'layer-7', 'id': '42'}},
          'content': {'content_sha256': 'c' * 64, 'source_version': 'layer edit 3'}, 'context': {'comparison': 'comparison/1', 'context_sha256': 'd' * 64}}


def ids(read):
    d = read._wire_descriptors[0] if hasattr(read, '_wire_descriptors') else read._wire_descriptor
    return d['asset_id'], d['revision']


def wrap(asset, revision, record=RECORD):
    return {'schema': SCHEMA, 'asset_id': asset, 'revision': revision, 'record': copy.deepcopy(record)}


def recorded(read, record=RECORD):
    read.source_record = wrap(*ids(read), record); return read


def las_with_record(tmp_path, name='b', record=RECORD):
    return bundle.write_bundle(tmp_path / name, [las_item(recorded(Read(), record))])


def typed_with_records(tmp_path, name='t'):
    items = typed_items()
    for _, read in items: recorded(read, NATIVE)
    return bundle.write_bundle(tmp_path / name, items)


def entry(root, index=0):
    return json.loads((root / 'manifest.json').read_text())['assets'][index]


# --- C1: the released 2.9 reader, frozen ----------------------------------------------------------------------------

def test_the_frozen_two_nine_reader_is_the_released_file():
    history = _history()
    released = history.show(Path(__file__).parents[1], 'bb43d40e357594bf95b00d7c8eccd322555b3212', 'ophiolite/bundle.py')  # main before E122 s5b
    if released is not None: assert released == (FROZEN / 'bundle_2_9.py').read_bytes()
    else: assert not history.FULL, history.missing('bb43d40e3')
    assert hashlib.sha256((FROZEN / 'bundle_2_9.py').read_bytes()).hexdigest() == '889d9fc5888e6372d1053e20bec8bfe56fe7e3c4e5f441d7c16f1fdc93e000db'


# --- writing and reading (D1, D2, D4) -------------------------------------------------------------------------------

def test_a_record_travels_unchanged_and_raises_the_minor_to_ten(tmp_path):
    opened = las_with_record(tmp_path)
    assert opened.manifest['bundle_version'] == '1.10.0' and opened.manifest['schema'] == 'ophiolite.portable-bundle/1'
    asset_id, revision = ids(Read())
    assert entry(opened.path)['source_record'] == {'schema': SCHEMA, 'asset_id': asset_id, 'revision': revision, 'record': RECORD}
    assert opened.assets[0].source_record == RECORD and opened.summary()['source_records'] == 1
    typed = typed_with_records(tmp_path)
    assert typed.manifest['bundle_version'] == '2.10.0' and [a.source_record for a in typed.assets] == [NATIVE] * 4


def test_t3_a_record_for_another_revision_or_asset_is_refused(tmp_path):
    for field, value in (('revision', 'f' * 64), ('asset_id', 'another-asset')):
        root = las_with_record(tmp_path, field).path
        rewrite(root, lambda m: m['assets'][0]['source_record'].update({field: value}))
        with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
        assert str(refused.value) == bundle.SOURCE_OTHER, field


@pytest.mark.parametrize('case', ['an extra key', 'no schema', 'no asset_id', 'no revision', 'no record', 'another schema', 'not an object'])
def test_t4a_a_malformed_wrapper_is_refused(tmp_path, case):
    root = las_with_record(tmp_path).path
    def mutate(m):
        held = m['assets'][0]['source_record']
        if case == 'an extra key': held['words'] = 'From upload.'
        elif case.startswith('no '): held.pop(case[3:])
        elif case == 'another schema': held['schema'] = 'ophiolite.source-provenance/2'
        else: m['assets'][0]['source_record'] = [held]
    rewrite(root, mutate)
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle.SOURCE_SHAPE, case


# --- T4b: the reader's record check against the Platform schema, rule by rule (R2.4) --------------------------------

def _at(record, path):
    for key in path: record = record[key]
    return record


def _set(path, value):
    def change(record): _at(record, path[:-1])[path[-1]] = value
    return change


def _drop(path):
    def change(record): _at(record, path[:-1]).pop(path[-1])
    return change


OBJECTS = {'record': ([], ('schema', 'identity', 'content', 'context')), 'identity': (['identity'], ('source_system', 'source_instance', 'id_scheme', 'source_object_id')),
           'content': (['content'], ('content_sha256', 'source_version')), 'context': (['context'], ('comparison', 'context_sha256')),
           'path': (['identity', 'source_object_id'], ('path',)), 'native': (['identity', 'source_object_id'], ('container', 'id'))}
STRINGS = {'source_system': (['identity', 'source_system'], 160, False), 'source_instance': (['identity', 'source_instance'], 160, True),
           'source_version': (['content', 'source_version'], 256, True), 'path': (['identity', 'source_object_id', 'path'], 1024, False),
           'part': (['identity', 'source_object_id', 'part'], 128, True), 'container': (['identity', 'source_object_id', 'container'], 256, True),
           'id': (['identity', 'source_object_id', 'id'], 256, False)}
NATIVE_FIELDS = {'native', 'container', 'id'}


def parity_cases():
    cases = []
    for name, (path, required) in OBJECTS.items():
        base = NATIVE if name in NATIVE_FIELDS else RECORD
        cases.append(('%s: an extra key' % name, base, _set(path + ['note'], 'x'), False))
        cases += [('%s: no %s' % (name, key), base, _drop(path + [key]), False) for key in required]
    for name, (path, most, nullable) in STRINGS.items():
        base = NATIVE if name in NATIVE_FIELDS else RECORD
        cases += [('%s: a number' % name, base, _set(path, 7), False), ('%s: true' % name, base, _set(path, True), False),
                  ('%s: empty' % name, base, _set(path, ''), False), ('%s: at its most' % name, base, _set(path, 'x' * most), True),
                  ('%s: one over' % name, base, _set(path, 'x' * (most + 1)), False), ('%s: null' % name, base, _set(path, None), nullable)]
    cases += [('schema: another constant', RECORD, _set(['schema'], 'ophiolite.source-provenance/2'), False),
              ('comparison: another constant', RECORD, _set(['context', 'comparison'], 'comparison/2'), False),
              ('id_scheme: outside the enum', RECORD, _set(['identity', 'id_scheme'], 'source-url'), False)]
    cases += [('id_scheme: %s' % s, RECORD, _set(['identity', 'id_scheme'], s), True) for s in ('source-native', 'source-path', 'none')]
    for field in (['content', 'content_sha256'], ['context', 'context_sha256']):
        cases += [('%s: uppercase' % field[1], RECORD, _set(field, 'A' * 64), False), ('%s: 63 characters' % field[1], RECORD, _set(field, 'a' * 63), False),
                  ('%s: not hex' % field[1], RECORD, _set(field, 'g' * 64), False), ('%s: a number' % field[1], RECORD, _set(field, 1), False)]
    sid = ['identity', 'source_object_id']
    cases += [('source_object_id: null', RECORD, _set(sid, None), True), ('source_object_id: a list', RECORD, _set(sid, ['wells/tops.csv']), False),
              ('source_object_id: both alternatives mixed', RECORD, _set(sid, {'path': 'a.csv', 'id': '1'}), False),
              ('source_object_id: a string', RECORD, _set(sid, 'wells/tops.csv'), False),
              ('part: omitted', RECORD, _drop(sid + ['part']), True),
              ('id_scheme none with a native id (no cross-field rule)', NATIVE, _set(['identity', 'id_scheme'], 'none'), True),
              ('id_scheme source-path with a native id (no cross-field rule)', NATIVE, _set(['identity', 'id_scheme'], 'source-path'), True),
              ('identity: a list', RECORD, _set(['identity'], []), False), ('content: null', RECORD, _set(['content'], None), False)]
    return cases


PARITY = parity_cases()


def platform_schema():
    return json.loads(files('ophiolite').joinpath('contracts/scientific/v1/source-provenance.json').read_text())


@pytest.mark.parametrize('name,base,change,valid', PARITY, ids=[c[0] for c in PARITY])
def test_t4b_the_record_check_agrees_with_the_platform_schema(name, base, change, valid):
    jsonschema = pytest.importorskip('jsonschema')
    record = copy.deepcopy(base); change(record); kept = copy.deepcopy(record)
    assert jsonschema.Draft202012Validator(platform_schema()).is_valid(record) is valid, 'the table disagrees with the schema: ' + name
    assert bundle.source_record_valid(record) is valid, name
    assert record == kept  # the check reads the dict and never rewrites it


def test_t4b_every_case_is_counted_and_both_verdicts_occur():
    # 21 object cases (an extra key and each required key, six objects), 42 string cases (six for each of seven fields),
    # 6 constant and enum cases, 8 digest cases, 9 source_object_id and nesting cases
    assert len(PARITY) == len({c[0] for c in PARITY}) == 86
    assert sum(c[3] for c in PARITY) == 18  # 7 strings at their most, 4 nullable nulls, 3 enum values, 4 structural


def test_t4b_an_invalid_record_in_a_bundle_is_refused_and_a_part_free_path_opens(tmp_path):
    root = las_with_record(tmp_path).path
    rewrite(root, lambda m: m['assets'][0]['source_record']['record']['identity']['source_object_id'].update(note='x'))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle.SOURCE_SHAPE
    partless = copy.deepcopy(RECORD); partless['identity']['source_object_id'].pop('part')
    assert las_with_record(tmp_path, 'partless', partless).assets[0].source_record == partless


def test_t4c_a_record_below_minor_ten_is_refused(tmp_path):
    las = las_with_record(tmp_path).path; typed = typed_with_records(tmp_path).path
    rewrite(las, lambda m: m.update(bundle_version='1.9.0')); rewrite(typed, lambda m: m.update(bundle_version='2.9.0'))
    for root in (las, typed):
        with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
        assert str(refused.value) == bundle.SOURCE_MINOR


# --- T5, T13: versions without records (Q1, R2.3) -------------------------------------------------------------------

def test_t5_an_export_without_records_keeps_its_version_and_writes_nothing(tmp_path):
    las = bundle.write_bundle(tmp_path / 'las', [las_item()]); typed = bundle.write_bundle(tmp_path / 'typed', typed_items())
    assert (las.manifest['bundle_version'], typed.manifest['bundle_version']) == ('1.0.0', '2.0.0')
    for opened in (las, typed):
        assert 'observations' not in opened.manifest and not any('source_record' in a for a in opened.manifest['assets'])
        assert all(a.source_record is None for a in opened.assets) and 'source_records' not in opened.summary()
    nulled = Read(); nulled.source_record = None
    assert 'source_record' not in entry(bundle.write_bundle(tmp_path / 'null', [las_item(nulled)]).path)


def test_t13_an_omission_alone_follows_the_observation_rule(tmp_path):
    las = bundle.write_bundle(tmp_path / 'las', [las_item()], source_records_omitted=OLD)
    typed = bundle.write_bundle(tmp_path / 'typed', typed_items(), source_records_omitted=OLD)
    assert (las.manifest['bundle_version'], typed.manifest['bundle_version']) == ('1.1.0', '2.1.0')
    assert las.manifest['observations'] == {'source_records_omitted': OLD} and las.summary()['source_records_omitted'] == OLD
    newer = typed_items() + [typed_item(typed_read('points'))]
    assert bundle.write_bundle(tmp_path / 'newer', newer).manifest['bundle_version'] == '2.2.0'
    assert bundle.write_bundle(tmp_path / 'newer-old', newer, source_records_omitted=OLD).manifest['bundle_version'] == '2.2.0'


# --- T6: released readers open the same export with records as without (0.8) ----------------------------------------

def _frozen_one():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ophiolite._frozen_bundle_s5b', FROZEN / 'bundle_1_0.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_t6_released_readers_open_a_bundle_with_records_and_expose_none(tmp_path):
    las = las_with_record(tmp_path); plain = bundle.write_bundle(tmp_path / 'plain', [las_item()])
    old = _frozen_one().open_bundle(las.path)
    assert old.assets[0].curves['GR'].values == _frozen_one().open_bundle(plain.path).assets[0].curves['GR'].values
    assert getattr(old.assets[0], 'source_record', None) is None
    typed = typed_with_records(tmp_path); typed_plain = bundle.write_bundle(tmp_path / 'typed-plain', typed_items())
    for minor in (1, 2, 4, 5, 6, 7, 8, 9):
        reader = frozen(minor)
        assets = reader.open_bundle(typed.path).assets
        assert [(a.asset_id, a.type) for a in assets] == [(a.asset_id, a.type) for a in reader.open_bundle(typed_plain.path).assets], minor
        assert all(getattr(a, 'source_record', None) is None for a in assets), minor


# --- T10, T11: beside a kept original; the manifest bound -----------------------------------------------------------

def test_t10_a_kept_original_and_a_record_travel_together(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', [las_item(recorded(read_on_a_computer(Read())))])
    assert opened.manifest['bundle_version'] == '2.10.0'
    held = entry(opened.path)
    assert 'read_by' in held and [f['role'] for f in held['files']].count('provenance') == 1
    assert opened.assets[0].source_record == RECORD


def largest_record():
    """R2.7: every string at its most, of a supplementary character (U+1F600): a 12-byte escape in the manifest."""
    face = '\U0001F600'
    return {'schema': SCHEMA, 'identity': {'source_system': face * 160, 'source_instance': face * 160, 'id_scheme': 'source-path',
                                           'source_object_id': {'path': face * 1024, 'part': face * 128}},
            'content': {'content_sha256': 'a' * 64, 'source_version': face * 256}, 'context': {'comparison': 'comparison/1', 'context_sha256': 'b' * 64}}


def test_t11_records_past_the_manifest_bound_are_refused_by_the_writer_before_the_manifest(tmp_path, monkeypatch):
    jsonschema = pytest.importorskip('jsonschema')
    record = largest_record()
    jsonschema.Draft202012Validator(platform_schema()).validate(record)
    assert bundle.source_record_valid(record)
    items = [las_item(recorded(Read(), record)) for _ in range(bundle.MAX_ASSETS)]
    assert len(json.dumps([i[1].source_record for i in items], indent=2)) > bundle.MAX_MANIFEST_BYTES  # the records alone
    opened, real = [], bundle.os.open
    def spy(path, *args, **kwargs):
        if Path(path).name == 'manifest.json': opened.append(path)
        return real(path, *args, **kwargs)
    monkeypatch.setattr(bundle.os, 'open', spy)
    out = tmp_path / 'out'; out.mkdir()
    with pytest.raises(Refused) as refused: bundle.write_bundle(out / 'b', items)
    assert str(refused.value) == bundle.SOURCE_TOO_LARGE and opened == [] and list(out.iterdir()) == []


# --- T7: the exporters against a gateway's provenance answers (R2.8) -------------------------------------------------

def answer_with(kind):
    """The provenance route as a gateway answers it: records, the router of an older gateway, or a refusal."""
    def answer(asset, revision, count):
        if kind == 'old': return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'Not Found'})
        if kind == 'not-found' or (kind == 'third-not-found' and count == 3): return httpx.Response(404, json={'code': 'not-found', 'error': 'No such revision.'})
        if kind == 'forbidden': return httpx.Response(403, json={'code': 'PERMISSION_DENIED', 'message': 'Forbidden'})
        body = {'schema': SCHEMA, 'asset_id': asset, 'revision': revision, 'record': RECORD, 'words': 'From upload.',
                'observation': {'run_id': 'run-1'}, 'gone': None}
        if kind == 'malformed': body['revision'] = 'another'
        return httpx.Response(200, json=body)
    return answer


class Route:
    """Wraps a transport's handler: the provenance route answers with `answer`, everything else as before."""
    def __init__(self, inner=None):
        self.inner, self.answer, self.calls = inner, answer_with('current'), 0

    def __call__(self, request):
        parts = request.url.path.split('/')
        if parts[-1] == 'provenance':
            self.calls += 1
            return self.answer(unquote(parts[-4]), unquote(parts[-2]), self.calls)
        return self.inner(request) if self.inner else httpx.Response(404, json={'code': 'NOT_FOUND'})


def exact_client(route):
    """A Client whose reads are the bundle fixtures (three versions) and whose provenance goes over HTTP."""
    client = Client('http://localhost', 'p', http=httpx.Client(transport=httpx.MockTransport(route)))
    by_id = {ids(make())[0]: make for make in (Read, lambda: typed_read('tops'), lambda: typed_read('trajectory'))}
    client.read = lambda asset, revision, curves, **options: by_id[asset]()
    client.read_data = lambda asset, revision: by_id[asset]()
    client._kept_original = lambda *args: None
    return client, [(ids(make())[0], ids(make())[1], ['GR'] if make is Read else None) for make in by_id.values()]


def run_export(path, tmp_path, kind, then=None):
    """(bundle, provenance calls, warnings, folder) for one export through PATH against a gateway answering KIND; with
    THEN, the same client exports again against a gateway answering THEN, and that second export's triple is appended."""
    out = tmp_path / 'out'; out.mkdir()
    results = []
    def once(export, name, answer):
        route.answer, route.calls = answer_with(answer), 0
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            opened = export(out / name)
        results.append((opened, route.calls, [str(w.message) for w in caught if issubclass(w.category, UserWarning)]))
    rounds = [('b', kind)] + ([('again', then)] if then else [])
    if path == 'export':
        route = Route(); client, selections = exact_client(route)
        try:
            for name, answer in rounds: once(lambda to: client.export(selections, to, groups=False, entities=False), name, answer)
        finally: client.close()
    else:
        v = volume(); transport, _ = mock(v, lambda axis, label: encode(served(v, axis, label)), [])
        route = Route(transport.handler)
        if path == 'export_slices':
            with httpx.Client(transport=httpx.MockTransport(route)) as http:
                client = Client('http://localhost', v.descriptor.project_id, http=http)
                for name, answer in rounds: once(lambda to: client.export_slices(v.descriptor.asset_id, v.descriptor.revision, [('inline', 10)], to), name, answer)
        else:
            async def main():
                async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
                    client = AsyncClient('http://localhost', v.descriptor.project_id, http=http)
                    for name, answer in rounds:  # one client, as for the sync paths; the warning caught around the awaited export
                        route.answer, route.calls = answer_with(answer), 0
                        with warnings.catch_warnings(record=True) as caught:
                            warnings.simplefilter('always')
                            opened = await client.export_slices(v.descriptor.asset_id, v.descriptor.revision, [('inline', 10)], out / name)
                        results.append((opened, route.calls, [str(w.message) for w in caught if issubclass(w.category, UserWarning)]))
            anyio.run(main)
    first = results[0]
    return (*first, out) if not then else (*first, out, *results[1])


PATHS = ['export', 'export_slices', 'async export_slices']


@pytest.mark.parametrize('path', PATHS)
def test_t7_a_current_gateway_gives_every_version_its_record(tmp_path, path):
    opened, calls, said, _ = run_export(path, tmp_path, 'current')
    assert calls == len(opened.assets) and said == [] and 'source_records_omitted' not in opened.manifest.get('observations', {})
    assert [a.source_record for a in opened.assets] == [RECORD] * len(opened.assets)
    assert all(set(e['source_record']) == {'schema', 'asset_id', 'revision', 'record'} for e in opened.manifest['assets'])
    assert opened.manifest['bundle_version'].split('.')[1] == '10'


@pytest.mark.parametrize('path', PATHS)
def test_t7_an_older_gateway_exports_without_records_once_and_says_so(tmp_path, path):
    opened, calls, said, _, again, again_calls, again_said = run_export(path, tmp_path, 'old', then='current')
    assert calls == 1 and said == [WARNING]
    assert opened.manifest['observations']['source_records_omitted'] == OLD and opened.summary()['source_records_omitted'] == OLD
    assert all(a.source_record is None for a in opened.assets) and opened.manifest['bundle_version'].split('.')[1] != '10'
    # M8b: the same client's next export, against a current gateway, asks again: the omission is the export's, never the client's
    assert again_calls == len(again.assets) and again_said == [] and 'source_records_omitted' not in again.manifest.get('observations', {})
    assert all(a.source_record == RECORD for a in again.assets)


REFUSALS = [('not-found', Unavailable), ('forbidden', PermissionRefused), ('malformed', VerificationFailed)]


@pytest.mark.parametrize('path,kind,error', [(p, k, e) for p in PATHS for k, e in REFUSALS] + [('export', 'third-not-found', Unavailable)])
def test_t7_a_refused_record_fails_the_export_and_publishes_nothing(tmp_path, path, kind, error):
    with pytest.raises(error): run_export(path, tmp_path, kind)
    out = tmp_path / 'out'
    assert list(out.iterdir()) == []


def test_t7_the_third_of_three_refused_after_two_records_counts_three_calls(tmp_path):
    route = Route(); client, selections = exact_client(route); route.answer = answer_with('third-not-found')
    out = tmp_path / 'out'; out.mkdir()
    with client, pytest.raises(Unavailable): client.export(selections, out / 'b', groups=False, entities=False)
    assert route.calls == 3 and list(out.iterdir()) == []
