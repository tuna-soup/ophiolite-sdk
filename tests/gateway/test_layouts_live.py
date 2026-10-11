"""E89 C7, in-process gateway lane (the external-client sequence of loop step 6): F-A's three tops through the command
line against the real gateway routes, with a project access key created through a browser session and saved with
`ophiolite login --key-stdin`, given with and without a trailing line break. A table whose columns are a layout's is
not added without --layout (exit 4, the layout named); with it, it is added and reads back as the literal rows. The
download imported after the layout was renamed away is Added under its own name (the in-process gateway serves one
project; Platform's test_layouts_export imports into a second)."""
import io
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from ophiolite import cli
from ophiolite.testing import fixture_server

F_A = b'Well Name,Top,MD (m),TVD (m)\nHON-GT-01,North Sea Supergroup,0.0,0.0\nHON-GT-01,Chalk Group,512.5,511.9\nHON-GT-01,Rijnland Group,1204.0,1198.2\n'
FIELDS = {'well': 'Well Name', 'name': 'Top', 'md': 'MD (m)', 'tvd': 'TVD (m)'}


def command(web, tmp_path, monkeypatch, argv, key, line_break):
    """`ophiolite login --key-stdin` then `ophiolite ...` (the installed entry point) over the gateway; the exit code."""
    def handler(method, path, raw, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.content
    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
        saved = tmp_path / ('key-%s.json' % line_break)
        monkeypatch.delenv('OPHIOLITE_ACCESS_KEY', raising=False)
        monkeypatch.setattr('sys.stdin', io.StringIO(key + ('\n' if line_break else '')))
        cli.main(['login', '--configuration', str(config), '--credentials', str(saved), '--key-stdin'])
        assert json.loads(saved.read_text())['credential']['access_key'] == key  # the line break is removed, never sent
        try: cli.entrypoint([*argv, '--configuration', str(config), '--credentials', str(saved)])
        except SystemExit as exited: return exited.code
        return 0


@pytest.mark.parametrize('line_break', [False, True])
def test_the_command_line_names_the_layout_adds_with_it_and_carries_its_download(keyed, tmp_path, monkeypatch, capsys, line_break):
    alice = client(keyed, 'alice', 'delegate')
    table = tmp_path / 'tops-F-A.csv'; table.write_bytes(F_A)
    alice.layouts().save('well-tops', 'Tubbergen tops', ['Well Name', 'Top', 'MD (m)', 'TVD (m)'], FIELDS, declarations={'depth_unit': 'm'})
    key = create(keyed, 'write')['key']
    run = lambda *argv: command(keyed, tmp_path, monkeypatch, list(argv), key, line_break)
    before = len(alice.imports.list())
    assert run('upload', str(table), '--attribution', 'Synthetic', '--rights-confirmed') == 4
    assert capsys.readouterr().err.strip().endswith(
        'Needs your decision: this table matches the layout "Tubbergen tops". Add it with --layout "Tubbergen tops".')
    assert len(alice.imports.list()) == before  # nothing was started
    assert run('import', 'table', str(table), '--layout', 'Tubbergen tops') == 0
    assert capsys.readouterr().out.splitlines()[-2:] == ['Finished', 'HON-GT-01 tops: Added: 3 tops. No well named HON-GT-01 was found, so these are not linked yet.']
    assert run('upload', str(table), '--attribution', 'Synthetic', '--rights-confirmed', '--layout', 'Tubbergen tops') == 0
    assert capsys.readouterr().out.splitlines()[-2:] == ['Finished', 'HON-GT-01 tops: Already here']  # the same table, carried by the same layout
    unit = alice.layouts().find('Tubbergen tops')['last_used']
    landed = [u for r in alice.imports.list() if r['id'] == unit['run_id'] for u in alice.imports.status(r['id'])['units']]
    assert [(t['name'], t['md'], t['tvd']) for t in alice.read_data(landed[0]['asset_id'], landed[0]['revision']).tops] == [
        ('North Sea Supergroup', 0.0, 0.0), ('Chalk Group', 512.5, 511.9), ('Rijnland Group', 1204.0, 1198.2)]
    out = tmp_path / 'Tubbergen tops.layout.json'
    assert run('layouts', 'export', 'Tubbergen tops', '--out', str(out)) == 0 and json.loads(out.read_text())['schema'] == 'ophiolite.layout-export/1'
    assert run('layouts', 'import', str(out)) == 0 and capsys.readouterr().out.splitlines()[-1] == 'Tubbergen tops: Already here'
    assert run('layouts', 'rename', 'Tubbergen tops', 'Tubbergen tops 2026') == 0
    assert run('layouts', 'import', str(out)) == 0 and capsys.readouterr().out.splitlines()[-1] == 'Tubbergen tops: Added'
    assert run('layouts', 'list') == 0
    assert [line.split(' · ')[0] for line in capsys.readouterr().out.splitlines()[-2:]] == ['Tubbergen tops', 'Tubbergen tops 2026']
