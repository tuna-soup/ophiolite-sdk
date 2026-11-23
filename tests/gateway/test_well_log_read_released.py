"""E183 s2c C2, T2.1 (acceptance 7; strategy E183-s2-curve-declaration, rev 2 closed): an item this tree's SDK uploads
with a declaration and reads in its well log form is still read by the released SDK 2026.10.117 (the gateway's pinned
fixture wheel, in its own process over HTTP) through the default answer, with the same values, and its inspect call
reads an answer that carries `header`. No 2026.11.19 wheel is in the tree, so only 2026.10.117 is run.

The file is SYNTHETIC (test_curve_declaration_gateway.LAS)."""
import json
import textwrap

from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_curve_declaration_gateway import DECLARED, LAS, SEND
from project_gateway.tests.test_upload_source_released import KEY, proxy, released, run  # noqa: F401 (fixture)

FORM = 'ophiolite.well-log-curve/1'
READ = textwrap.dedent('''
    import json, sys, ophiolite.client as c
    class Key:
        def headers(self, url, project): return {'Authorization': 'Bearer ' + sys.argv[2]}
    client = c.Client(sys.argv[1], 'p', Key())
    asset, revision, path = sys.argv[3:6]
    curves = client.read(asset, revision, ['GR'])
    inspected = client.inspect_las(open(path, 'rb').read())
    print(json.dumps({'where': c.__file__, 'axis': [list(v.axis) for v in curves.curves], 'values': [list(v.values) for v in curves.curves],
                      'header': inspected['header']}))
''')


def test_t21_the_released_sdk_reads_an_item_read_here_in_its_well_log_form(web, released, tmp_path):
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='released-read', **SEND)
    log = alice.read(info.asset_id, info.revision, ['GR'], form=FORM).curves[0]
    plain = alice.read(info.asset_id, info.revision, ['GR']).curves[0]
    (tmp_path / 'read.py').write_text(READ); (tmp_path / 'curve.las').write_text(LAS)
    with proxy(web) as url:
        done = run(released, tmp_path, str(tmp_path / 'read.py'), url, KEY, info.asset_id, info.revision, str(tmp_path / 'curve.las'))
    assert done.returncode == 0, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert out['where'].startswith(str(released))  # nothing of this tree's SDK
    assert out['values'] == [log.values] == [list(plain.values)] and out['axis'] == [log.depth] == [list(plain.axis)]
    assert set(out['header']) == {'entries_total', 'entries_kept', 'entries_withheld', 'kept_in'}
    assert out['header']['entries_total'] == log.header.entries_total
