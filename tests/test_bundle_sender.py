"""E182 s2b C2: a bundle entry carries the sender of its version, at bundle 1.18 / 2.18.

The sender is `ophiolite.sender/1`'s served view, read from the same provenance answer as the source record (no new
request) and written as the entry's own field `sender`, beside `source_record`, never inside it. The minor rises to 18
only when a sender travels (T2.1, T2.2). The view is checked closed, on write and on read, rule for rule as
`sender.json` says (T2.3). The key's place is asserted on the manifest itself (T2.4); that released readers (the SDK
pinned at `conformance/older_sdk.py` and the 2026.11.19 tag) open 1.18 and 2.18 bundles and read what they read before
is a conformance task (conformance/tasks/older_readers.py), since the readers come from the monorepo's history. The
descriptor files keep today's bytes and checksums: the `sender` a gateway after E182 s2a serves on a descriptor is left
out of the file (T2.6). Everything here is synthetic."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import anyio
import httpx
import pytest
from ophiolite import Client, bundle
from ophiolite.aio import AsyncClient
from ophiolite.errors import VerificationFailed
from test_bundle import Read, rewrite, typed_items, typed_read
from test_bundle_compat import frozen
from test_bundle_provenance import las_item, typed_item
from test_bundle_source_records import RECORD, Route, entry, exact_client, ids, recorded
from test_seismic import encode, mock, served, volume

SDK = Path(__file__).resolve().parents[1]
RELEASED = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles'
SCHEMA = 'ophiolite.source-provenance/1'
REPORTED = {'schema': 'ophiolite.sender/1', 'state': 'reported', 'client': {'product': 'qgis-plugin', 'version': '1.4.0'},
            'host': {'name': 'qgis', 'version': '3.34.2'}, 'transport': 'http', 'accepted_as': 'las2/1'}
UNREPORTED = {'schema': 'ophiolite.sender/1', 'state': 'not reported', 'client': None, 'host': None, 'transport': 'mcp', 'accepted_as': 'well-tops-csv/1'}
UNRECORDED = {'schema': 'ophiolite.sender/1', 'state': 'not recorded', 'client': None, 'host': None, 'transport': None, 'accepted_as': None}
FROZEN_AT = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)


def sent(read, view=REPORTED):
    read.sender = copy.deepcopy(view); return read


def served_on_descriptor(read, view=REPORTED):
    """READ as a gateway after E182 s2a serves it: its descriptors carry `sender` too."""
    if hasattr(read, '_wire_descriptors'): read._wire_descriptors = [{**d, 'sender': copy.deepcopy(view)} for d in read._wire_descriptors]
    else: read._wire_descriptor = {**read._wire_descriptor, 'sender': copy.deepcopy(view)}
    return read


def files_of(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob('*')) if p.is_file()}


def descriptor_files(root):
    return {name: raw for name, raw in files_of(root).items() if '/descriptor' in name}


def key_paths(value, path=()):
    """Every place a `sender` key appears in VALUE, as a path of keys and indexes."""
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == 'sender': found.append(path + (key,))
            found += key_paths(inner, path + (key,))
    elif isinstance(value, list):
        for index, inner in enumerate(value): found += key_paths(inner, path + (index,))
    return found


@pytest.fixture
def frozen_time(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None): return FROZEN_AT
    monkeypatch.setattr(bundle, 'datetime', Fixed)
    return Fixed


# --- T2.1: the literal view travels in its entry, at 1.18 / 2.18 ----------------------------------------------------

def test_t2_1_a_well_log_and_a_typed_bundle_carry_the_literal_sender(tmp_path):
    las = bundle.write_bundle(tmp_path / 'las', [las_item(sent(Read()))])
    assert (las.manifest['schema'], las.manifest['bundle_version']) == (bundle.SCHEMA, '1.18.0')
    assert entry(las.path)['sender'] == REPORTED and las.assets[0].sender == REPORTED and las.assets[0].source_record is None
    typed = bundle.write_bundle(tmp_path / 'typed', [typed_item(sent(typed_read('tops'), UNREPORTED))])
    assert (typed.manifest['schema'], typed.manifest['bundle_version']) == (bundle.SCHEMA_2, '2.18.0')
    assert entry(typed.path)['sender'] == UNREPORTED and typed.assets[0].sender == UNREPORTED
    assert bundle.open_bundle(typed.path).assets[0].sender == UNREPORTED


def test_t2_1_a_record_and_a_sender_are_two_fields_of_one_entry(tmp_path):
    opened = bundle.write_bundle(tmp_path / 'b', [las_item(sent(recorded(Read()), UNRECORDED))])
    held = entry(opened.path)
    assert held['sender'] == UNRECORDED and set(held['source_record']) == {'schema', 'asset_id', 'revision', 'record'}
    assert opened.manifest['bundle_version'] == '1.18.0' and opened.assets[0].source_record == RECORD and opened.assets[0].sender == UNRECORDED


# --- T2.2: no sender, no change ------------------------------------------------------------------------------------

def frozen_ten(monkeypatch):
    module = frozen(10)

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None): return FROZEN_AT
    monkeypatch.setattr(module, 'datetime', Fixed)
    return module


@pytest.mark.parametrize('kind,version', [('las', '1.0.0'), ('las with a record', '1.10.0'), ('typed', '2.0.0'), ('typed with records', '2.10.0')])
def test_t2_2_without_a_sender_the_bundle_is_the_released_writers_byte_for_byte(tmp_path, monkeypatch, frozen_time, kind, version):
    """The released 2.10 writer (tests/frozen/bundle_2_10.py) and this one write the same bytes for the same items with
    `created_at` frozen: a version without a sender keeps its minor and every byte."""
    def items():
        if kind.startswith('las'): return [las_item(recorded(Read()) if 'record' in kind else Read())]
        made = typed_items()
        if 'record' in kind:
            for _, read in made: recorded(read)
        return made
    mine = bundle.write_bundle(tmp_path / 'mine', items())
    theirs = frozen_ten(monkeypatch).write_bundle(tmp_path / 'theirs', items())
    assert mine.manifest['bundle_version'] == version and not key_paths(mine.manifest)
    assert files_of(mine.path) == files_of(theirs.path)
    nulled = [(chosen, sent(read, None)) for chosen, read in items()]  # a gateway that served no sender
    assert files_of(bundle.write_bundle(tmp_path / 'nulled', nulled).path) == files_of(mine.path)


# --- T2.3: the full rule set, on write and on read -----------------------------------------------------------------

def _with(base, **changes):
    view = copy.deepcopy(base)
    for path, value in changes.items():
        *outer, last = path.split('__'); target = view
        for key in outer: target = target[key]
        if value is _DROP: target.pop(last)
        else: target[last] = value
    return view


_DROP = object()


def rule_cases():
    """(name, view, valid): sender.json's rules, case by case (PG/sender.py:24-32, 56-63 as the schema states them)."""
    cases = [('reported, as served', REPORTED, True), ('not reported, as served', UNREPORTED, True), ('not recorded, as served', UNRECORDED, True)]
    for key in ('schema', 'state', 'client', 'host', 'transport', 'accepted_as'):
        cases.append(('no %s' % key, _with(REPORTED, **{key: _DROP}), False))
    cases += [('an extra key', _with(REPORTED, words='Sent through QGIS.'), False),
              ('client: an extra key', _with(REPORTED, client__name='qgis'), False),
              ('client: no product', _with(REPORTED, client__product=_DROP), False),
              ('client: no version', _with(REPORTED, client__version=_DROP), False),
              ('host: an extra key', _with(REPORTED, host__build='7'), False),
              ('host: no name', _with(REPORTED, host__name=_DROP), False),
              ('host: no version', _with(REPORTED, host__version=_DROP), False),
              ('client: a list', _with(REPORTED, client=['qgis-plugin', '1.4.0']), False),
              ('another schema', _with(REPORTED, schema=bundle.SENDER_SCHEMA[:-1] + '2'), False),  # the next major, never a live id
              ('state: null', _with(REPORTED, state=None), False),
              ('state: outside the enum', _with(REPORTED, state='claimed'), False),
              ('state: a number', _with(REPORTED, state=1), False),
              # the three state rules
              ('reported without a client', _with(REPORTED, client=None), False),
              ('reported without a host', _with(REPORTED, host=None), True),
              ('reported, an unnamed program (product null)', _with(REPORTED, client__product=None), True),
              ('reported, no client version', _with(REPORTED, client__version=None), True),
              ('reported, no transport or profile', _with(REPORTED, transport=None, accepted_as=None), True),
              ('not reported with a client', _with(UNREPORTED, client={'product': 'qgis-plugin', 'version': '1.4.0'}), False),
              ('not reported with a host', _with(UNREPORTED, host={'name': 'qgis', 'version': '3.34.2'}), False),
              ('not reported, no transport or profile', _with(UNREPORTED, transport=None, accepted_as=None), True),
              ('not recorded with a transport', _with(UNRECORDED, transport='http'), False),
              ('not recorded with a profile', _with(UNRECORDED, accepted_as='las2/1'), False),
              ('not recorded with a client', _with(UNRECORDED, client={'product': None, 'version': None}), False),
              ('not recorded with a host', _with(UNRECORDED, host={'name': 'qgis', 'version': '3.34.2'}), False)]
    for path in ('client__product', 'client__version', 'host__name', 'host__version'):  # the token grammar
        cases += [('%s: 40 characters' % path, _with(REPORTED, **{path: 'a' * 40}), True),
                  ('%s: 41 characters' % path, _with(REPORTED, **{path: 'a' * 41}), False),
                  ('%s: empty' % path, _with(REPORTED, **{path: ''}), False),
                  ('%s: a leading dot' % path, _with(REPORTED, **{path: '.qgis'}), False),
                  ('%s: a slash' % path, _with(REPORTED, **{path: 'q/gis'}), False),
                  ('%s: a number' % path, _with(REPORTED, **{path: 7}), False)]
    cases += [('host__name: null', _with(REPORTED, host__name=None), False), ('host__version: null', _with(REPORTED, host__version=None), False),
              ('transport: 16 characters', _with(REPORTED, transport='a' * 16), True),
              ('transport: 17 characters', _with(REPORTED, transport='a' * 17), False),
              ('transport: upper case', _with(REPORTED, transport='HTTP'), False),
              ('transport: a leading digit', _with(REPORTED, transport='2http'), False),
              ('accepted_as: 128 characters', _with(REPORTED, accepted_as='a' * 126 + '/1'), True),
              ('accepted_as: 129 characters', _with(REPORTED, accepted_as='a' * 127 + '/1'), False),
              ('accepted_as: off the registry grammar (no major)', _with(REPORTED, accepted_as='las2'), False),
              ('accepted_as: off the registry grammar (upper case)', _with(REPORTED, accepted_as='LAS2/1'), False),
              ('accepted_as: a number', _with(REPORTED, accepted_as=1), False),
              ('not an object', [REPORTED], False), ('null', None, False)]
    return cases


RULES = rule_cases()


def sender_schema():
    return json.loads((SDK / 'ophiolite' / 'contracts' / 'scientific' / 'v1' / 'sender.json').read_text())


@pytest.mark.parametrize('name,view,valid', RULES, ids=[c[0] for c in RULES])
def test_t2_3_the_check_agrees_with_the_sender_schema(name, view, valid):
    jsonschema = pytest.importorskip('jsonschema')
    kept = copy.deepcopy(view)
    assert jsonschema.Draft202012Validator(sender_schema()).is_valid(view) is valid, 'the table disagrees with the schema: ' + name
    assert bundle.sender_valid(view) is valid, name
    assert view == kept  # the check reads the dict and never rewrites it


def test_t2_3_every_case_is_counted_and_both_verdicts_occur():
    # 3 served, 6 missing keys, 9 shape and constant, 3 state, 12 state rules, 24 token, 2 host nulls, 4 transport, 5 profile, 2 not an object
    assert len(RULES) == len({c[0] for c in RULES}) == 70
    assert sum(c[2] for c in RULES) == 14  # 3 served, 5 allowed by the state rules, 4 tokens at their most, transport and profile at their most


INVALID = [c for c in RULES if not c[2] and c[1] is not None]


@pytest.mark.parametrize('name,view,valid', INVALID, ids=[c[0] for c in INVALID])
def test_t2_3_each_invalid_view_is_refused_on_write_and_on_read(tmp_path, name, view, valid):
    out = tmp_path / 'out'; out.mkdir()
    with pytest.raises(VerificationFailed) as refused: bundle.write_bundle(out / 'b', [las_item(sent(Read(), view))])
    assert str(refused.value) == bundle.SENDER_SHAPE and list(out.iterdir()) == []
    root = bundle.write_bundle(tmp_path / 'valid', [las_item(sent(Read()))]).path
    rewrite(root, lambda m: m['assets'][0].update(sender=copy.deepcopy(view)))
    with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
    assert str(refused.value) == bundle.SENDER_SHAPE, name


def test_t2_3_a_sender_below_minor_eighteen_is_refused(tmp_path):
    las = bundle.write_bundle(tmp_path / 'las', [las_item(sent(Read()))]).path
    typed = bundle.write_bundle(tmp_path / 'typed', [typed_item(sent(typed_read('tops')))]).path
    rewrite(las, lambda m: m.update(bundle_version='1.17.0')); rewrite(typed, lambda m: m.update(bundle_version='2.17.0'))
    for root in (las, typed):
        with pytest.raises(VerificationFailed) as refused: bundle.open_bundle(root)
        assert str(refused.value) == bundle.SENDER_NEEDS_MINOR == 'A sender needs bundle version 1.18 or 2.18.'


def test_t2_3_the_largest_valid_view_on_every_entry_stays_within_the_manifest_bound(tmp_path):
    jsonschema = pytest.importorskip('jsonschema')
    largest = _with(REPORTED, client__product='a' * 40, client__version='b' * 40, host__name='c' * 40, host__version='d' * 40,
                    transport='e' * 16, accepted_as='f' * 126 + '/1')
    jsonschema.Draft202012Validator(sender_schema()).validate(largest)
    opened = bundle.write_bundle(tmp_path / 'b', [las_item(sent(Read(), largest)) for _ in range(bundle.MAX_ASSETS)])
    assert (opened.path / 'manifest.json').stat().st_size <= bundle.MAX_MANIFEST_BYTES
    assert [a.sender for a in opened.assets] == [largest] * bundle.MAX_ASSETS


# --- T2.4: the key's place (released readers: conformance/tasks/older_readers.py) -----------------------------------

def test_t2_4_this_sdk_reads_the_released_senders():
    mine = [bundle.open_bundle(RELEASED / '1.18'), bundle.open_bundle(RELEASED / '2.18')]
    assert [b.manifest['bundle_version'] for b in mine] == ['1.18.0', '2.18.0']
    assert [b.assets[0].sender for b in mine] == [REPORTED, UNREPORTED]


def test_t2_4_the_sender_is_a_key_of_exactly_its_entry(tmp_path):
    written = bundle.write_bundle(tmp_path / 'b', [las_item(sent(served_on_descriptor(Read()))), typed_item(typed_read('tops'))])
    for root in (RELEASED / '1.18', RELEASED / '2.18', written.path):
        manifest = json.loads((root / 'manifest.json').read_text())
        assert key_paths(manifest) == [('assets', 0, 'sender')], root.name
        for name, raw in files_of(root).items():
            if name != 'manifest.json' and name.endswith('.json'): assert key_paths(json.loads(raw)) == [], name


# --- T2.6: the cases, through both clients --------------------------------------------------------------------------

def answer_with(senders=None, record=RECORD, old=False, words=True):
    """The provenance route of a gateway: SENDERS (a view, or {asset_id: view}) on each answer, no key when None."""
    def answer(asset, revision, count):
        if old: return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'Not Found'})
        body = {'schema': SCHEMA, 'asset_id': asset, 'revision': revision, 'record': record, 'words': 'From upload.', 'observation': {'run_id': 'run-1'}, 'gone': None}
        view = senders.get(asset) if isinstance(senders, dict) and 'schema' not in senders else senders
        if view is not None: body.update(sender=copy.deepcopy(view), **({'sender_words': 'Synthetic sender words.'} if words else {}))
        return httpx.Response(200, json=body)
    return answer


def export(path, tmp_path, answer, *, describe=None, only=None, name='b'):
    """The bundle one export through PATH writes against a gateway answering ANSWER; DESCRIBE, when given, is served on
    every descriptor too (a gateway after E182 s2a)."""
    out = tmp_path / 'out'; out.mkdir(exist_ok=True)
    route = Route()
    if path == 'export':
        route.answer = answer; client, selections = exact_client(route)
        if describe is not None:
            read, read_data = client.read, client.read_data
            client.read = lambda *a, **k: served_on_descriptor(read(*a, **k), describe)
            client.read_data = lambda *a: served_on_descriptor(read_data(*a), describe)
        with client: return client.export(selections[:only] if only else selections, out / name, groups=False, entities=False)
    v = volume()
    if describe is not None: served_on_descriptor(v, describe)
    transport, _ = mock(v, lambda axis, label: encode(served(v, axis, label)), [])
    route = Route(transport.handler); route.answer = answer
    if path == 'export_slices':
        with httpx.Client(transport=httpx.MockTransport(route)) as http:
            return Client('http://localhost', v.descriptor.project_id, http=http).export_slices(v.descriptor.asset_id, v.descriptor.revision, [('inline', 10)], out / name)

    async def main():
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
            return await AsyncClient('http://localhost', v.descriptor.project_id, http=http).export_slices(v.descriptor.asset_id, v.descriptor.revision, [('inline', 10)], out / name)
    return anyio.run(main)


PATHS = ['export', 'export_slices', 'async export_slices']


@pytest.mark.parametrize('path', PATHS)
def test_t2_1_both_clients_carry_the_served_sender(tmp_path, path):
    opened = export(path, tmp_path, answer_with(REPORTED))
    assert opened.manifest['bundle_version'] == '2.18.0'
    assert [e['sender'] for e in opened.manifest['assets']] == [REPORTED] * len(opened.assets) and [a.sender for a in opened.assets] == [REPORTED] * len(opened.assets)
    assert 'sender_words' not in json.dumps(opened.manifest)  # the view travels; the sentence is the gateway's, asked for again


def test_t2_1_a_well_log_export_is_one_eighteen(tmp_path):
    opened = export('export', tmp_path, answer_with(REPORTED), only=1)
    assert (opened.manifest['bundle_version'], opened.assets[0].sender) == ('1.18.0', REPORTED)


@pytest.mark.parametrize('path', PATHS)
def test_t2_6_a_sender_travels_without_a_source_record(tmp_path, path):
    opened = export(path, tmp_path, answer_with(UNRECORDED, record=None))
    assert all('source_record' not in e and e['sender'] == UNRECORDED for e in opened.manifest['assets'])
    assert opened.manifest['bundle_version'].split('.')[1] == '18' and all(a.source_record is None for a in opened.assets)


@pytest.mark.parametrize('path', PATHS)
def test_t2_6_a_record_without_a_sender_is_as_before(tmp_path, path):
    opened = export(path, tmp_path, answer_with(None))  # a gateway before E182 s0: no `sender` on its answer
    assert opened.manifest['bundle_version'].split('.')[1] == '10' and not key_paths(opened.manifest)
    assert all(a.source_record == RECORD and a.sender is None for a in opened.assets)


@pytest.mark.parametrize('path', PATHS)
def test_t2_6_an_older_gateway_without_a_provenance_route_carries_neither(tmp_path, path):
    with pytest.warns(UserWarning): opened = export(path, tmp_path, answer_with(old=True))
    before = '2.1.0' if path == 'export' else '2.3.0'  # the omission observation (1); a seismic slice (3)
    assert opened.manifest['bundle_version'] == before and not key_paths(opened.manifest)
    assert opened.manifest['observations']['source_records_omitted'] == 'this server has no source records'


def test_t2_6_mixed_entries_carry_their_own_senders(tmp_path):
    client, selections = exact_client(Route())
    by_asset = dict(zip([s[0] for s in selections], (REPORTED, None, UNREPORTED)))
    opened = export('export', tmp_path, answer_with(by_asset))
    assert [e.get('sender') for e in opened.manifest['assets']] == [REPORTED, None, UNREPORTED]
    assert [a.sender for a in opened.assets] == [REPORTED, None, UNREPORTED] and opened.manifest['bundle_version'] == '2.18.0'


@pytest.mark.parametrize('path', PATHS)
def test_t2_6_descriptor_files_keep_their_bytes_and_checksums(tmp_path, path, frozen_time):
    """A gateway after E182 s2a serves `sender` on every descriptor; the files are what a descriptor without it writes,
    and the entry's sender is the one the provenance answer served (UNREPORTED here, not the descriptor's REPORTED)."""
    plain = export(path, tmp_path, answer_with(UNREPORTED), name='plain')
    described = export(path, tmp_path, answer_with(UNREPORTED), describe=REPORTED, name='described')
    assert descriptor_files(described.path) == descriptor_files(plain.path) and descriptor_files(plain.path)
    assert all(b'"sender"' not in raw for raw in descriptor_files(described.path).values())
    assert [f['sha256'] for e in described.manifest['assets'] for f in e['files']] == [f['sha256'] for e in plain.manifest['assets'] for f in e['files']]
    assert files_of(described.path) == files_of(plain.path)  # the manifest too: the sender travels only in the entry
    assert [a.sender for a in described.assets] == [UNREPORTED] * len(described.assets)


def test_t2_6_a_malformed_served_sender_fails_the_export_and_publishes_nothing(tmp_path):
    with pytest.raises(VerificationFailed) as refused: export('export', tmp_path, answer_with(_with(REPORTED, state='claimed')))
    assert str(refused.value) == bundle.SENDER_SHAPE and list((tmp_path / 'out').iterdir()) == []


def test_t2_6_the_sender_is_read_from_the_one_provenance_request(tmp_path):
    route = Route(); route.answer = answer_with(REPORTED); client, selections = exact_client(route)
    with client: client.export(selections, tmp_path / 'b', groups=False, entities=False)
    assert route.calls == len(selections)  # one provenance request per version, as before senders
