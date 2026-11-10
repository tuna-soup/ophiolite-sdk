"""E162 s1 C1: BundleApplications serves a demo-compatible bundle as its project serves it, from memory, and keeps the
session's publications. The bundle is synthetic: a log with descending depths first, a second log, well tops, a
deviation survey and a grid, all in project `q`. Each test names the mutation it catches."""
import hashlib
import json
from importlib.resources import files
from pathlib import Path
import pytest
from ophiolite import Client, bundle, _core
from ophiolite.auth import Credential
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.testing import BundleApplications, FixtureServer
from ophiolite.writers import WrittenOriginal

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')
DESCENDING = [(104.0, 41.5), (103.0, None), (102.0, 22.25), (101.0, 10.0), (100.0, 0.0)]  # file order, as the log stores it
ASCENDING = [(200.0, 5.0), (201.0, 6.5), (202.0, 7.0)]
EXTENT = {'crs': 'OGC:CRS84', 'bbox': None, 'count': 0, 'untransformed': 0}


class Log:
    """A Client.read-shaped LAS log with GR, its descriptor carried through the contract checks before it is written."""
    def __init__(self, asset, well, rows, project='q', path=True):
        las = ('~Version\nVERS. 2.0 : LAS version\nWRAP. NO : One row per depth\n~Well\nNULL. -999.25 : Missing sample marker\n'
               'WELL. %s : Synthetic, not an observed well\n~Curve\nDEPT.M : Source depth; datum unknown\nGR.gAPI : Gamma ray\n~ASCII\n' % well
               + ''.join('%r %r\n' % (depth, -999.25 if value is None else value) for depth, value in rows)).encode()
        revision = hashlib.sha256(las).hexdigest()
        reference = {'authority': 'synthetic-file', 'key': asset, 'revision': revision, 'profile': 'las2/1'}
        curve = json.loads(FIXTURES.joinpath('curve.json').read_bytes())
        curve.update(axis=[d for d, _ in rows], values=[v for _, v in rows], source=reference, source_sha256=revision)
        body = json.dumps(curve).encode()
        d = json.loads(FIXTURES.joinpath('source.json').read_bytes())
        axis = [r[0] for r in rows]
        d.update(asset_id=asset, revision=revision, project_id=project, source_reference=reference)
        d['scientific'].update(sample_count=len(rows), missing_count=sum(v is None for _, v in rows),
                               axis_order='decreasing' if axis[0] > axis[-1] else 'increasing')
        d['representations'][0].update(bytes=len(las), sha256=revision)
        d['representations'][1].update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        _core.verify_pair(d, body, las, 'GR')  # a log the client accepts, so a refusal below is the server's
        self.artifact, self._wire_descriptors, self._wire_curves, self._wire_curve_bytes = las, [d], [curve], [body]
        self.source_record = {'schema': 'ophiolite.source-provenance/1', 'asset_id': asset, 'revision': revision, 'record': {
            'schema': 'ophiolite.source-provenance/1',
            'identity': {'source_system': 'upload', 'source_instance': None, 'id_scheme': 'source-path', 'source_object_id': {'path': 'logs/%s.las' % well, 'part': None}},
            'content': {'content_sha256': revision, 'source_version': None}, 'context': {'comparison': 'comparison/1', 'context_sha256': 'b' * 64}}} if path else None


def typed(name, project='q', attribution=None):
    d = json.loads(FIXTURES.joinpath(f'{name}.json').read_bytes()); d['project_id'] = project
    if attribution: d['acquisition'] = {'kind': 'user-upload', 'filename': f'{name}.csv', 'attribution': attribution, 'well_notes': '',
                                        'identity': 'operator', 'uploaded_at': 1.0, 'rights': 'confirmed'}
    return _core.typed_result(d, FIXTURES.joinpath(f'{name}-data.json').read_bytes(), FIXTURES.joinpath(f'{name}.original').read_bytes())


def chosen(read):
    d = read._wire_descriptors[0] if hasattr(read, '_wire_descriptors') else read._wire_descriptor
    return {'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR'] if hasattr(read, '_wire_descriptors') else None}


def demo_bundle(tmp_path, reads=None, name='demo'):
    """A packed bundle; the first log's descriptor member is rewritten with unusual spacing and key order (K12)."""
    reads = reads or [Log('log-b', 'SYN-B', DESCENDING), Log('log-a', 'SYN-A', ASCENDING), typed('tops'), typed('trajectory'), typed('grid')]
    root = bundle.write_bundle(tmp_path / (name + '-folder'), [(chosen(r), r) for r in reads]).path
    member = root / 'assets/0/descriptor-GR.json'
    if member.exists():
        raw = (json.dumps(dict(reversed(list(json.loads(member.read_bytes()).items()))), indent=5, separators=(' ,', ' :  ')) + '\n\n').encode()
        member.write_bytes(raw)
        manifest = json.loads((root / 'manifest.json').read_bytes())
        for f in manifest['assets'][0]['files']:
            if f['path'] == 'assets/0/descriptor-GR.json': f.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (root / 'manifest.json').write_text(json.dumps(manifest))
    return bundle.pack(root, tmp_path / (name + '.zip'))


@pytest.fixture
def served(tmp_path):
    path = demo_bundle(tmp_path)
    applications = BundleApplications(path)
    with FixtureServer(applications) as server, Client(server.url, 'q', Credential.bearer('oph_api_demo')) as client:
        yield path, applications, client


def test_the_catalogue_is_the_manifest_in_order(served):
    """Mutation: drop an entry from the index or sort the catalogue → the ids differ."""
    path, applications, client = served
    manifest = bundle.open_bundle(path).manifest
    items = list(client.assets())
    assert [(i['asset_id'], i['revision']) for i in items] == [(e['asset_id'], e['revision']) for e in manifest['assets']]
    assert [i['asset_id'] for i in items][:2] == ['log-b', 'log-a'] and items[0]['curves'] == ['GR'] and items[2]['curves'] == []
    assert applications.project == 'q'


def test_a_descriptor_is_the_stored_member_byte_for_byte(served, tmp_path):
    """Mutation: serve json.dumps(json.loads(member)) → the bytes differ (the member's spacing is unusual on purpose)."""
    import zipfile
    path, applications, client = served
    member = zipfile.ZipFile(path).read('assets/0/descriptor-GR.json')
    assert b' :  ' in member and json.dumps(json.loads(member)).encode() != member
    first = next(iter(client.assets()))
    assert client._get(client.prefix + '/log-b/revisions/' + first['revision'] + '?curve=GR', 1 << 20) == member
    exact = applications.prefix + '/log-b/revisions/' + first['revision']
    assert applications('GET', exact + '?curve=DT', b'', {'Authorization': 'Bearer oph_api_demo'})[0] == 404  # a curve the bundle lacks


def test_a_descending_log_reads_in_file_order(served):
    """Mutation: sort the log by depth → the first depth is 100.0, not 104.0."""
    _, _, client = served
    first = next(iter(client.assets()))
    [curve] = client.read(first['asset_id'], first['revision'], ['GR']).curves
    assert curve.axis == [104.0, 103.0, 102.0, 101.0, 100.0] and curve.values == [41.5, None, 22.25, 10.0, 0.0]


def test_tops_survey_and_grid_read_their_stored_values(served):
    """Mutation: serve another asset's descriptor or file → verify_typed_descriptor or the digest check refuses."""
    _, _, client = served
    tops, trajectory, grid = [client.read_data(i['asset_id'], i['revision']) for i in list(client.assets())[2:]]
    assert [t['md'] for t in tops.tops] == [100.5, 103.0] and tops.tops[0]['tvd'] is None
    assert trajectory.stations[2]['inclination'] is None
    assert grid.values[1] == 0.0 and grid.values[2] is None and grid.cell_center(0, 0) == (1012.5, 5037.5)


def test_one_well_per_log_by_its_source_path_without_a_location(served):
    """Mutation: count the listed wells in extent → 2, not 0; name a well by the asset id → the names differ."""
    _, _, client = served
    wells = client.wells()
    assert [w.name for w in wells] == ['SYN-A', 'SYN-B'] and [w.location for w in wells] == [None, None]
    assert client.extent() == EXTENT
    assert list(client.wells(bbox=[0, 0, 10, 10], bbox_crs='OGC:CRS84')) == []  # only located wells are inside a box


def test_a_publication_under_the_bundle_project_reads_back_with_its_bundle_parent(served):
    """Mutations: leave project `p` in _descriptor → verify_descriptor refuses the read-back; label the parent
    `ophiolite:derived` → the authority differs from the bundle descriptor's."""
    _, applications, client = served
    first = next(iter(client.assets()))
    source = client.read(first['asset_id'], first['revision'], ['GR'])
    receipt = client.publish_derived(WrittenOriginal(source.artifact, 'las2/1', {}, 'derived.las'), name='Doubled GR',
                                     from_=[(first['asset_id'], first['revision'])], method={'name': 'synthetic', 'parameters': {}}, command_id='c1')
    [parent] = receipt.derived_from
    assert (parent.authority, parent.key, parent.revision) == ('synthetic-file', 'log-b', first['revision'])
    [back] = client.read(receipt.asset_id, receipt.revision, ['GR']).curves
    assert back.values == [41.5, None, 22.25, 10.0, 0.0] and client.describe(receipt.asset_id, receipt.revision, 'GR').project_id == 'q'


def test_requests_without_a_key_are_refused(served):
    """Mutation: drop the owner check → the catalogue answers 200."""
    path, applications, _ = served
    assert applications('GET', applications.prefix + '?limit=100&cursor=', b'', {})[0] == 401
    assert applications('POST', applications.entities + 'list', b'{}', {})[0] == 401


@pytest.mark.parametrize('case, sentence', [
    ('version-1', 'version 2 bundle only'),
    ('typed-first', 'first asset is a LAS log with a GR curve'),
    ('two-projects', 'all in one project'),
    ('no-source-path', 'path every log in the bundle was read from'),
])
def test_only_a_demo_compatible_bundle_is_served(tmp_path, case, sentence):
    """Each mutation keeps a valid bundle (it opens), so only the demo's own rule can refuse it."""
    reads = {'typed-first': [typed('tops'), Log('log-b', 'SYN-B', DESCENDING)],
             'two-projects': [Log('log-b', 'SYN-B', DESCENDING), typed('tops', project='other')],
             'no-source-path': [Log('log-b', 'SYN-B', DESCENDING), Log('log-a', 'SYN-A', ASCENDING, path=False), typed('tops')]}.get(case)
    if case == 'version-1':  # a curve-only export stays 1.x
        log = Log('log-b', 'SYN-B', DESCENDING); log.source_record = None
        path = bundle.pack(bundle.write_bundle(tmp_path / 'one', [(chosen(log), log)]).path, tmp_path / 'one.zip')
    else: path = demo_bundle(tmp_path, reads)
    bundle.open_bundle(path)
    with pytest.raises(Refused, match=sentence): BundleApplications(path)


def test_a_flipped_byte_stops_before_anything_is_served(tmp_path):
    """Mutation: skip open_bundle → the server starts on a damaged copy."""
    import zipfile
    path = demo_bundle(tmp_path)
    damaged = tmp_path / 'damaged.zip'
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(damaged, 'w') as out:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == 'assets/0/original.las': data = bytes([data[0] ^ 1]) + data[1:]
            out.writestr(info, data)
    with pytest.raises(VerificationFailed): BundleApplications(damaged)
