"""E88 C6, in-process gateway lane: the F-MIX files (a folder upload with HON-GT-01.las, a table import naming hon_gt_01)
through `client.well_names` and `ophiolite wells from-run`, against the real gateway routes. The command line uses a
project access key created through a browser session and saved with `ophiolite login --key-stdin`, given with and
without a trailing line break; the list changes nothing, --create-all creates one well and its wellbore, go back
removes them, and a refusal keeps the server's sentence."""
import io
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from project_gateway.tests.test_well_names_mix import LAS, TOPS
from ophiolite import cli
from ophiolite.errors import IntegrityConflict
from ophiolite.testing import fixture_server

SETTINGS = dict(attribution='Synthetic', audience=['alice'], rights_confirmed=True)


@pytest.fixture
def runs(keyed, tmp_path):
    alice = client(keyed, 'alice', 'delegate')
    root = tmp_path / 'F-MIX'
    for path, raw in LAS:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True); (tmp_path / path).write_bytes(raw)
    folder = alice.upload_runs.upload(root, **SETTINGS).run_id
    tops = tmp_path / 'hon_gt_01-tops.csv'; tops.write_bytes(TOPS)
    table = alice.imports.from_table(tops, 'well-tops', {'well': 'well', 'name': 'surface', 'md': 'md_m'})['run']['id']
    return alice, [folder, table]


def command(web, tmp_path, monkeypatch, argv, key, line_break):
    """`ophiolite login --key-stdin` then `ophiolite wells from-run ...` over the gateway; (exit, stdout)."""
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
        return cli.main(['wells', 'from-run', *argv, '--configuration', str(config), '--credentials', str(saved)])


@pytest.mark.parametrize('line_break', [False, True])
def test_the_command_line_lists_then_creates_with_a_key_from_stdin(keyed, runs, tmp_path, monkeypatch, capsys, line_break):
    alice, ids = runs
    key = create(keyed, 'write')['key']
    command(keyed, tmp_path, monkeypatch, ids, key, line_break)
    out = capsys.readouterr().out.splitlines()
    assert out[-9:] == ['Wells named in your files', '1 file and 1 table name 1 well that is not in this project.',
                        'Nothing is created until you press a button. You can undo it until other data refers to the wells.',
                        'HON-GT-01', '  Named as a well in 1 table.', '  Named as a wellbore in 1 file.',
                        '  The Well column of hon_gt_01-tops.csv names the well, rows 2 to 3.',
                        '  The LAS header of HON-GT-01.las names the wellbore "HON-GT-01".',
                        'Provisional wells have no registry number yet. You can add one later.']
    assert [e.name for e in alice.entities()] == []  # the list changed nothing
    command(keyed, tmp_path, monkeypatch, [*ids, '--create-all'], key, line_break)
    assert capsys.readouterr().out.splitlines()[-1] == 'Created 1 well and 1 wellbore. Linked 2 files and sheets. 0 left.'
    assert sorted((e.kind, e.name) for e in alice.entities()) == [('well', 'HON-GT-01'), ('wellbore', 'HON-GT-01')]


def test_python_accepts_goes_back_and_a_replay_keeps_the_server_sentence(runs):
    alice, ids = runs
    names = alice.well_names
    listed = names.proposals(list(reversed(ids)))  # the same set in another order: the same list
    got = names.accept(ids, digest=listed['digest'], create_all=True, command_id='c1')
    assert (got['created'], got['linked']) == ({'wells': 1, 'wellbores': 1}, 2)
    back = names.go_back(ids)
    assert (back['state'], back['removed']) == ('removed', {'wells': 1, 'wellbores': 1})
    with pytest.raises(IntegrityConflict) as refused: names.accept(ids, digest=listed['digest'], create_all=True, command_id='c1')
    assert refused.value.code == 'list-removed' and str(refused.value).startswith('These wells were removed by ')
    assert names.go_back(ids)['state'] == 'nothing'
