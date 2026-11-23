"""E183 s2b C2 (strategy E183-s2-curve-declaration, rev 2 closed: T2.1, T2.2). Each SDK runs in its own process and
talks HTTP to the in-process gateway through a loopback proxy (the Platform's E122 s2 helper):

- T2.1: this tree's installed SDK sends `upload_las(..., curve_declaration=...)` over the existing route
  (`las-uploads/upload`, an operation `publish` already allows: no operation set changes); the stored declaration is
  the caller's.
- T2.2: the released SDK 2026.10.117 (the gateway's pinned fixture wheel) uploads without the field, as it always did,
  and reads both its own item and the declared one, unchanged.

Every file is SYNTHETIC; its header names a well and a datum no declaration uses."""
import json
import os
import subprocess
import sys

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_curve_declaration_gateway import DECLARED, LAS, stored
from project_gateway.tests.test_upload_source_released import proxy, released  # noqa: F401 (fixture)

KEY = 'oph_api_alice:read,write'
SCRIPT = r'''
import json, sys
import ophiolite
from ophiolite import Client, Credential
url, path, mode = sys.argv[1:4]
out = {'file': ophiolite.__file__, 'items': []}
with Client(url, 'p', Credential.bearer('oph_api_alice:read,write')) as c:
    if mode == 'declared':
        got = c.upload_las(open(path, 'rb').read(), name='Declared log', attribution='Synthetic test', audience=[], rights_confirmed=True,
                           command_id='wheel-declared', curve_declaration=json.loads(sys.argv[4]))
        out['items'].append([got.asset_id, got.revision])
    else:
        got = c.upload_las(open(path, 'rb').read(), name='Older log', attribution='Synthetic test', audience=[], rights_confirmed=True,
                           command_id='wheel-older')
        out['items'].append([got.asset_id, got.revision])
        for asset, revision in [out['items'][0], json.loads(sys.argv[4])]:
            view = c.read(asset, revision, ['GR'])
            out.setdefault('read', []).append(len(view.curves[0].values) if hasattr(view, 'curves') else type(view).__name__)
print(json.dumps(out))
'''


def run(tmp_path, url, mode, extra, pythonpath=None):
    las = tmp_path / 'synthetic.las'
    las.write_text(LAS)
    env = {**os.environ, **({'PYTHONPATH': str(pythonpath)} if pythonpath else {})}
    out = subprocess.run([sys.executable, '-c', SCRIPT, url, str(las), mode, json.dumps(extra)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stdout + out.stderr
    return json.loads(out.stdout)


def test_t21_t22_the_installed_sdk_declares_and_the_released_one_reads_unchanged(web, released, tmp_path):
    paths = []
    web.c.event_hooks['request'].append(lambda request: paths.append(request.url.path))
    with proxy(web) as url:
        new = run(tmp_path, url, 'declared', DECLARED)
        assert not new['file'].startswith(str(released))
        assert paths == ['/api/v1/projects/p/las-uploads/upload']  # the existing route, one request
        (asset, revision), = new['items']
        metadata, rows = stored(web, asset)
        assert metadata['curve_declaration'] == DECLARED and rows == ['curve:GR', 'well-log-curve:GR']

        old = run(tmp_path, url, 'older', [asset, revision], pythonpath=released)
        assert old['file'].startswith(str(released))
        (older, _), = old['items']
        metadata, rows = stored(web, older)
        assert 'curve_declaration' not in metadata and rows == ['curve:GR']
        samples = len(LAS.split('~ASCII\n')[1].splitlines())
        assert old['read'] == [samples, samples]
