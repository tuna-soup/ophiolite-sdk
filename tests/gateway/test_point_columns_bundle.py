"""E139 s2 (e8 ruling on the known limitation): a point set read as its stored columns is saved and bundled under its
codec's name, `data.ophpts`, and the bundle manifest states that name; a .json name is kept only for JSON bytes, so every
existing JSON read is saved and bundled as before. A bundle that names a data file against its codec is refused."""
import json
import shutil

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_point_columns_read import DECLARED, N, served  # noqa: F401 (fixture)
from ophiolite.bundle import open_bundle
from ophiolite.errors import VerificationFailed
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
