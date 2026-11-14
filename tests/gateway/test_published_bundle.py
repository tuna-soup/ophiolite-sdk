"""E175 s1 C6 (strategy §5 row 15, Q7): a portable bundle of slices of a cube as published is refused before anything is
written. The cube lands through the in-process gateway with the gate open (nothing patched); `export_slices` reads the
typed data (`ophiolite.seismic-volume/3` is a typed model of this SDK since C6), then asks for the first slice, which the
gateway refuses with its slice sentence (PUBLISHED_PART and the native-form remedy): no staging folder is made and
`write_bundle` is never called. A project move keeps such a cube whole (the Platform's test_published_store); the two
outcomes are kept apart (Q7). The cube is synthetic: literal codes."""
import struct
import tempfile

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)

from ophiolite import bundle
from ophiolite.errors import Incompatible
from project_gateway.tests.test_published_store import built

PUBLISHED_PART = ('This cube is read as a volume window, not as slices. Nothing was read. '
                  'Read the whole original file instead; nothing was read.')
UPLOAD = dict(declared={'crs': 'EPSG:23031', 'z_domain': 'time'}, attribution='Synthetic', audience=[], rights_confirmed=True)


@pytest.mark.parametrize('code', [3, 2])
def test_a_bundle_of_slices_of_a_cube_as_published_refuses_before_writing(web, monkeypatch, tmp_path, code):
    """Mutations: /3 dropped from validate's typed kinds (RED: the SDK's "update it" sentence before any slice is asked);
    the staging made before the slices are read (RED: a staging call)."""
    requests = []
    web.c.event_hooks['request'].append(lambda request: requests.append(request.url.path))
    calls = []
    monkeypatch.setattr(bundle, 'write_bundle', lambda *a, **k: calls.append('write_bundle'))
    made = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, 'mkdtemp', lambda *a, **k: calls.append('staging') or made(*a, **k))
    alice = client(web, 'alice', 'delegate')
    _, raw = built(code, 3, 4, 5)
    assert struct.unpack('>H', raw[3224:3226])[0] == code
    info = alice.upload_data(raw, profile='segy/3', name='Published %d' % code, filename='published.sgy', **UPLOAD)
    out = tmp_path / 'out'
    out.mkdir()
    requests.clear()
    with pytest.raises(Incompatible) as refused:
        alice.export_slices(info.asset_id, info.revision, [('inline', 1)], out / 'slices')
    assert str(refused.value) == PUBLISHED_PART and refused.value.status == 422, (refused.value, refused.value.status)
    assert any(r.endswith('/representations/data') for r in requests) and len([r for r in requests if '/slices/' in r]) == 1, requests
    assert calls == [] and list(out.iterdir()) == []
