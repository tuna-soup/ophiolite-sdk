"""E42a C6, in-process gateway lane: a well import through client.well_imports() and `ophiolite well-imports`, against
the real gateway routes. The dry run keeps nothing; a start runs to Finished and prints every skipped row with its
reason; an import whose command-line process is killed is resumed, or cancelled, from a new process."""
import json
import os
import sqlite3
import subprocess
import sys

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from ophiolite import Client, Credential, cli
from ophiolite.testing import fixture_server
from ophiolite.well_imports import words

ORIGIN = 'https://workspace.example'
TOKEN = 'oph_api_alice:read,write'
ROWS = [('W-1', 'North 1', 4.1, 52.1), ('W-2', 'North 2', 4.2, 52.2), ('W-3', 'No x', None, 52.3)]
CHILD = 'import sys\nfrom ophiolite import cli\ncli.entrypoint(sys.argv[1:])'


@pytest.fixture
def table(web, tmp_path):
    """A SQLite well table on an approved connection that retains a copy, its mapping file and a configuration."""
    s = web.a.sources
    path = tmp_path / 'wells.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE wells(id TEXT, name TEXT, x REAL, y REAL)')
        db.executemany('INSERT INTO wells VALUES(?,?,?,?)', ROWS)
    s.registry.connections['sql'] = {'id': 'sql', 'type': 'sqlite', 'name': 'SQL', 'namespace': 'sql-e42a', 'path': str(path),
                                     'principals': {'alice': True}, 'tables': {'w': {'table': 'wells', 'name': 'Wells'}},
                                     'identifiers': {'authority': 'nlog'},
                                     'release_policy': {'retention_permitted': True, 'redistribution_permitted': True, 'audience': ['alice', 'bob']}}
    found = s.call('schema', {'project_id': 'p', 'connection_id': 'sql', 'key': 'w', 'profile': 'sql-wells/1'}, 'alice')
    mapping = {'entity': 'well', 'fields': {'id': 'id', 'name': 'name', 'x': 'x', 'y': 'y'}, 'crs': 'EPSG:4326', 'schema_digest': found['schema_digest']}
    (tmp_path / 'mapping.json').write_text(json.dumps(mapping))
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    client = Client(ORIGIN, 'p', Credential.bearer(TOKEN), web.c)
    return type('Table', (), {'web': web, 'path': tmp_path, 'mapping': mapping, 'client': client, 'imports': client.well_imports()})()


def census(web):
    db = web.a.journal.db
    return {t: db.execute('SELECT count(*) FROM %s' % t).fetchone()[0] for t in ('entities', 'retained_assets', 'well_imports', 'well_import_rows')}


def wells(web):
    return sorted(k for (k,) in web.a.journal.db.execute("SELECT key FROM entities WHERE project='p' AND kind='well' AND authority='nlog'"))


@pytest.fixture
def run(table, monkeypatch, capsys):
    """run(*argv) -> (exit code, stdout, stderr) through cli.entrypoint in this process."""
    cli._load()
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, table.web.c))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', TOKEN)
    def call(*argv):
        capsys.readouterr()
        try: cli.entrypoint(['well-imports', *argv, '--configuration', str(table.path / 'configuration.json')])
        except SystemExit as stop: code = stop.code
        else: code = 0
        out = capsys.readouterr()
        return code, out.out.strip(), out.err.strip()
    return call


def start_args(table, *more):
    return ('start', '--connection', 'sql', '--table', 'w', '--mapping', str(table.path / 'mapping.json'), '--audience', 'bob', *more)


def test_the_python_api_previews_starts_and_runs_to_finished(table):
    imports = table.imports
    review = imports.preview('sql', 'w', table.mapping)
    assert (review['counts']['create'], review['counts']['skipped']) == (2, 1)
    started = imports.start('sql', 'w', table.mapping, preview_digest=review['preview_digest'], audience=['bob'], command_id='e42a-sdk')
    assert imports.start('sql', 'w', table.mapping, preview_digest=review['preview_digest'], audience=['bob'], command_id='e42a-sdk')['id'] == started['id']
    seen = []
    done = imports.run(started['id'], progress=seen.append)
    assert (done['state'], done['words']) == ('complete-with-skipped', 'Finished with skipped rows') and seen[-1] == done
    assert (done['counts']['created'], done['counts']['already_here'], done['counts']['skipped']) == (2, 0, 1)
    assert [(r['row_key'], words(r)) for r in done['skipped']] == [('W-3', 'A coordinate is missing')]
    assert imports.status(started['id']) == done and [r['id'] for r in imports.list()] == [started['id']]
    assert wells(table.web) == ['W-1', 'W-2']


def test_a_dry_run_keeps_nothing_and_counts_as_the_preview(table, run):
    before = census(table.web)
    code, out, err = run(*start_args(table, '--dry-run', '--json'))
    assert (code, err) == (0, '') and census(table.web) == before
    assert json.loads(out)['preview']['counts'] == table.imports.preview('sql', 'w', table.mapping)['counts']
    code, out, _ = run(*start_args(table, '--dry-run'))
    assert code == 0 and out.splitlines() == ['Dry run, nothing was kept. Wells (w): 3 rows; 2 would be added, 0 already here, 1 skipped, 0 possible duplicates.',
                                              'Rows that would be skipped:', '  W-3: A coordinate is missing']
    assert census(table.web) == before


def test_a_start_runs_to_finished_and_prints_every_skipped_row(table, run):
    code, out, err = run(*start_args(table))
    ident = table.imports.list()[0]['id']
    assert (code, err) == (0, '') and out.splitlines() == [
        'Import %s started. If it stops, continue with: ophiolite well-imports resume %s' % (ident, ident),
        'Finished with skipped rows: 2 added, 0 already here, 1 skipped.', 'Skipped rows:', '  W-3: A coordinate is missing']
    assert run('status', ident)[1].splitlines()[0] == 'Finished with skipped rows: 2 added, 0 already here, 1 skipped.'
    assert run('list')[1] == '%s  w: Finished with skipped rows (2 added, 0 already here, 1 skipped)' % ident
    assert run('resume') == (1, '', 'Give the import id: ophiolite well-imports resume ID (see `ophiolite well-imports list`).')
    assert run('list', ident) == (1, '', 'well-imports list takes no id.')
    assert run('status', ident, '--dry-run')[:2] == (1, '')  # only start previews


def served(web):
    def handler(method, path, raw, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=raw, headers=headers)
        return response.status_code, response.json()
    return handler


def child(table, url, *argv, wait=True):
    config = table.path / ('served-%d.json' % len(list(table.path.glob('served-*.json'))))
    config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': url, 'project': 'p'}))
    env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': TOKEN, 'PYTHONPATH': os.pathsep.join(p for p in sys.path if p)}
    process = subprocess.Popen([sys.executable, '-c', CHILD, 'well-imports', *argv, '--configuration', str(config)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if not wait: return process
    out, err = process.communicate(timeout=60)
    return process.returncode, out.strip(), err.strip()


@pytest.mark.parametrize('when', ['before', 'after'])
def test_a_killed_start_is_resumed_from_a_new_process(table, when):
    """The process is killed on its first step request, before or after the server ran it; a new process resumes the same
    import by its printed id and finishes with the counts of an uninterrupted run and no well twice."""
    forward, held = served(table.web), {}
    def handler(method, path, raw, headers):
        if path.endswith('/well-imports/step') and not held.get('killed'):
            held['killed'] = True
            answer = forward(method, path, raw, headers) if when == 'after' else (503, {'error': 'stopped'})
            held['process'].kill(); held['process'].wait(timeout=30)
            return answer
        return forward(method, path, raw, headers)
    with fixture_server(handler) as server:
        held['process'] = child(table, server.url, *start_args(table), wait=False)
        out, _ = held['process'].communicate(timeout=60)
        assert held['process'].returncode == -9
        ident = table.imports.list()[0]['id']
        assert out.strip() == 'Import %s started. If it stops, continue with: ophiolite well-imports resume %s' % (ident, ident)
        assert table.imports.status(ident)['state'] == ('importing' if when == 'before' else 'complete-with-skipped')
        code, out, err = child(table, server.url, 'resume', ident)
    assert (code, err) == (0, '') and out.splitlines()[:2] == ['Finished with skipped rows: 2 added, 0 already here, 1 skipped.', 'Skipped rows:']
    assert [r['id'] for r in table.imports.list()] == [ident] and wells(table.web) == ['W-1', 'W-2']


def test_an_unfinished_import_is_cancelled_from_a_new_process(table):
    review = table.imports.preview('sql', 'w', table.mapping)
    started = table.imports.start('sql', 'w', table.mapping, preview_digest=review['preview_digest'], command_id='e42a-cancel')
    with fixture_server(served(table.web)) as server:
        code, out, err = child(table, server.url, 'cancel', started['id'], '--json')
    answer = json.loads(out)['import']
    assert (code, err) == (0, '') and (answer['state'], answer['counts']['created']) == ('cancelled', 0)
    assert table.imports.status(started['id'])['state'] == 'cancelled' and wells(table.web) == []
