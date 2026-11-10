"""E139 s2 (e8 ruling on the known limitation): a point set read as its stored columns is saved and bundled under its
codec's name, `data.ophpts`, and the bundle manifest states that name; a .json name is kept only for JSON bytes, so every
existing JSON read is saved and bundled as before. A bundle that names a data file against its codec is refused."""
import json
import shutil
import struct
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_point_columns_read import DECLARED, N, served  # noqa: F401 (fixture)
from ophiolite.bundle import open_bundle
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.typed import PointSet

SMALL = b'x,y,z\n500000,0,1000.5\n500025,0,\n500050,25,1001.25\n'


@pytest.fixture
def small(web):
    """A three-node horizon: stored and served as point-set JSON."""
    from project_gateway.las_uploads import LASUploads, Upload
    landed = LASUploads(web.a).ingest(Upload(command_id='h-2', name='Small', profile='points-csv/1', declared=DECLARED, project_id='p', filename='small.csv',
                                             attribution='Synthetic', audience=[], rights_confirmed=True), SMALL, 'alice')
    return landed['asset_id'], landed['revision']


def normalized(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    return manifest, [f['path'] for a in manifest['assets'] for f in a['files'] if f['role'] == 'normalized']


def test_a_columns_read_is_bundled_as_data_ophpts_and_opens(web, served, small, tmp_path):
    """Mutation: the export writing 'data.json' for every typed read (the stated name is data.json, the import refuses
    its own bundle), or data_file naming by type instead of codec (the small JSON point set becomes data.ophpts)."""
    asset, revision, _ = served
    alice = client(web, 'alice', 'delegate')
    assert alice.read_data(asset, revision).data_file == 'data.ophpts' and alice.read_data(*small).data_file == 'data.json'
    opened = alice.export([(asset, revision, None), small + (None,)], tmp_path / 'bundle')
    _, paths = normalized(tmp_path / 'bundle')
    assert paths == ['assets/0/data.ophpts', 'assets/1/data.json']
    assert (tmp_path / 'bundle/assets/0/data.ophpts').read_bytes()[:8] == b'OPHPTS1\n'
    assert json.loads((tmp_path / 'bundle/assets/1/data.json').read_bytes())['context']['count'] == 3
    again = open_bundle(tmp_path / 'bundle')
    for got in (opened, again):
        big, little = got.assets[0].data, got.assets[1].data
        assert isinstance(big, PointSet) and big.context['count'] == N and big.points[999] == [504975.0, 50.0, None]
        assert little.points == [[500000.0, 0.0, 1000.5], [500025.0, 0.0, None], [500050.0, 25.0, 1001.25]]


def test_a_cited_columns_read_has_no_record_set_and_its_json_neighbour_has_one(web, served, small, tmp_path):
    """E147 s2b: a point set saved as data.ophpts is not a table a Croissant reader reads by jsonPath, so a cited export of
    it alone stays 2.15 with no record set; beside the small JSON point set the bundle is 2.16 with that one's set only.
    Mutation: the .ophpts file counted as a table (bundle_tables without its data.json check)."""
    from importlib.resources import files
    from ophiolite.bundle import write_bundle
    wells = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/bundle-wells/manifest.json')))
    citation = {k: v for k, v in json.loads(wells.read_text())['citation'].items() if k != 'prov'}  # write_bundle's full form
    asset, revision, _ = served
    alice = client(web, 'alice', 'delegate')
    big, little = (({'asset_id': a, 'revision': r, 'curves': None}, alice.read_data(a, r)) for a, r in ((asset, revision), small))
    assert big[1].data_file == 'data.ophpts' and little[1].data_file == 'data.json'
    alone = write_bundle(tmp_path / 'alone', [big], citation=citation)
    assert alone.manifest['bundle_version'] == '2.15.0'
    assert 'recordSet' not in json.loads((tmp_path / 'alone/croissant.json').read_bytes())
    both = write_bundle(tmp_path / 'both', [big, little], citation=citation)
    assert both.manifest['bundle_version'] == '2.16.0'
    assert [s['@id'] for s in json.loads((tmp_path / 'both/croissant.json').read_bytes())['recordSet']] == ['assets/1/point-set']


VERBOSE = b'x,y,z\n' + b''.join(b'%d.%s,%d.%s,%s.%s\n' % (x, b'0' * 4000, y, b'0' * 4000, z, b'0' * 4000)
                                for x, y, z in ((500000, 0, b'1000'), (500025, 0, b'1001'), (500050, 25, b'1002')))


@pytest.fixture
def verbose(web):
    """A three-node horizon written with 4,000 trailing zeros per value: its original (36,058 B) is larger than its data
    and than its descriptor, so a cap of exactly the original holds every other file of it."""
    from project_gateway.las_uploads import LASUploads, Upload
    landed = LASUploads(web.a).ingest(Upload(command_id='h-3', name='Verbose', profile='points-csv/1', declared=DECLARED, project_id='p', filename='verbose.csv',
                                             attribution='Synthetic', audience=[], rights_confirmed=True), VERBOSE, 'alice')
    return landed['asset_id'], landed['revision']


@pytest.fixture
def writes(monkeypatch, tmp_path):
    """Every staging folder made and every file opened for writing under tmp_path, as write_bundle makes them (K1)."""
    import os
    import tempfile
    seen = {'staging': [], 'files': []}
    mkdtemp, opened = tempfile.mkdtemp, os.open
    def staging(*args, **kwargs):
        seen['staging'].append(kwargs.get('prefix')); return mkdtemp(*args, **kwargs)
    def files(path, flags, *args, **kwargs):
        if str(path).startswith(str(tmp_path)) and flags & os.O_WRONLY: seen['files'].append(str(path))
        return opened(path, flags, *args, **kwargs)
    monkeypatch.setattr(tempfile, 'mkdtemp', staging); monkeypatch.setattr(os, 'open', files)
    return seen


def header_bytes(raw):
    """The columns body's magic, length and header (point_columns.py's layout), read from the bytes themselves."""
    return 8 + 4 + struct.unpack('<I', raw[8:12])[0]


def test_a_horizon_over_the_file_cap_is_refused_by_number_before_anything_is_written(web, served, small, tmp_path, monkeypatch, writes):
    """E139 s3 (O1, K1, K4, R2-10): a valid small horizon first, then a columns horizon whose point data is above the cap
    while its original fits: refused with the point-data sentence, and no staging folder, no file and not even the
    destination's parent was made. The cap is set to this body's header plus 90,000 nodes of its 4 columns plus 31
    bytes, so the estimate is 90,000 by hand: (header + 32 x 90,000 + 31 - header) // 32.
    Mutations: the check moved after the first put (the small item's original file is opened: `files` not empty); the
    estimate off by one or ignoring the header (not 90,000); the check measuring only the data (K4's original test)."""
    from ophiolite import bundle
    asset, revision, _ = served
    alice = client(web, 'alice', 'delegate')
    raw = alice.read_data(asset, revision)._wire_data_bytes
    cap = header_bytes(raw) + 32 * 90_000 + 31
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', cap)
    with pytest.raises(Refused) as refused: alice.export([small + (None,), (asset, revision, None)], tmp_path / 'out' / 'bundle')
    assert str(refused.value) == ("This horizon's point data is {:,} bytes; a bundle file holds at most {:,} bytes (about 90,000 nodes with its 4 columns). "
                                  'Export the original file on its own. Nothing was written.').format(len(raw), cap)
    assert len(raw) - header_bytes(raw) == 8 * 4 * N  # the body is the 4 columns of N nodes, as the estimate assumes
    assert writes == {'staging': [], 'files': []} and not (tmp_path / 'out').exists()


@pytest.mark.parametrize('cap, named', [('data', 'original file'), ('below both', 'original file')])
def test_an_original_over_the_file_cap_is_named_as_the_original(web, verbose, tmp_path, monkeypatch, writes, cap, named):
    """K4: the original is over while the point data fits (or both are over: the original, written first, is named), and
    the sentence says so with the original's size and no node estimate. Mutation: the check measuring only the data body
    (the first case exports; the second names the point data)."""
    from ophiolite import bundle
    alice = client(web, 'alice', 'delegate')
    read = alice.read_data(*verbose)
    assert (len(read.original), len(VERBOSE)) == (36058, 36058) and len(read._wire_data_bytes) < len(read.original)
    limit = len(read._wire_data_bytes) if cap == 'data' else len(read._wire_data_bytes) - 1
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', limit)
    with pytest.raises(Refused) as refused: alice.export([verbose + (None,)], tmp_path / 'out' / 'bundle')
    assert str(refused.value) == ("This horizon's %s is 36,058 bytes; a bundle file holds at most {:,} bytes. "
                                  'Export the original file on its own. Nothing was written.' % named).format(limit)
    assert writes == {'staging': [], 'files': []} and not (tmp_path / 'out').exists()


def test_a_horizon_at_the_file_cap_bundles_and_opens(web, served, verbose, tmp_path, monkeypatch):
    """K4: the exact boundary is accepted: a columns body of exactly the cap, and an original of exactly the cap.
    Mutation: '>' written as '>=' in the check (each is refused)."""
    from ophiolite import bundle
    asset, revision, _ = served
    alice = client(web, 'alice', 'delegate')
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', len(alice.read_data(asset, revision)._wire_data_bytes))
    assert open_bundle(alice.export([(asset, revision, None)], tmp_path / 'columns').path).assets[0].data.context['count'] == N
    monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', 36058)
    assert len(open_bundle(alice.export([verbose + (None,)], tmp_path / 'verbose').path).assets[0].data.points) == 3


def test_a_columns_horizon_bundles_and_reimports(web, served, tmp_path):
    """R2-4: the reimport runs here, in process, not on E15: a columns horizon under the cap bundles, imports as a new
    upload with the same original and reads back with the same nodes. Mutation: a precheck refusing every columns body
    (or one counting the bundle's total against the per-file cap) refuses this export."""
    import hashlib
    asset, revision, _ = served
    alice = client(web, 'alice', 'delegate')
    exported = alice.export([(asset, revision, None)], tmp_path / 'bundle')
    [done] = alice.import_bundle(exported.path, audience=[], attribution='Imported', rights_confirmed=True)
    assert done['state'] == 'imported' and done['destination']['revision'] == revision == hashlib.sha256(exported.assets[0].data.original).hexdigest()
    again = alice.read_data(done['destination']['asset_id'], done['destination']['revision'])
    assert again.context['count'] == N and again.points[999] == [504975.0, 50.0, None] and again.points[-1] == [500100.0, 6250.0, 1000 + (N - 1) / 4]


@pytest.mark.parametrize('which, name', [(0, 'data.json'), (1, 'data.ophpts')])
def test_a_data_file_named_against_its_codec_is_refused(web, served, small, tmp_path, which, name):
    """The same bytes and digest under the other codec's name, the manifest stating it: refused before the data is read.
    Mutation: the name check removed (both bundles open: the codec is the descriptor's, so only the name disagrees)."""
    asset, revision, _ = served
    client(web, 'alice', 'delegate').export([(asset, revision, None), small + (None,)], tmp_path / 'bundle')
    folder = tmp_path / 'bundle'
    manifest, paths = normalized(folder)
    renamed = 'assets/%d/%s' % (which, name)
    shutil.move(folder / paths[which], folder / renamed)
    for f in manifest['assets'][which]['files']:
        if f['role'] == 'normalized': f['path'] = renamed
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed) as caught: open_bundle(folder)
    assert str(caught.value) == 'A data file is not named by its codec.'
