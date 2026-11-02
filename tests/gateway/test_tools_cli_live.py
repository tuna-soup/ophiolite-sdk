"""E131 s1 C3 test 3 (R2-6), gateway lane: the catalogue verbs through `cli.main` under both spellings, each on a fresh
project, users and caches of an in-process gateway (`cli.Client` gives the person's in-process client). Stdout, stderr
and the exit code are the same literals for `tools` and `procedures` (piped: no notice, R2-8). The refusal without --yes
comes before any trust is recorded."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path

import pytest
try:
    from project_gateway.tests.procedure_world import rows
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
import ophiolite
from ophiolite import Client, Credential, cli

BUNDLE = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift'
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'
NOTICE = ('`ophiolite procedures` now runs as `ophiolite tools`; the old spelling is removed in a later release, announced '
          'one release ahead in the CHANGELOG.\n')


class Command:
    """`ophiolite <spelling> …` through `cli.main`, as one person (the in-process gateway's client for their key)."""
    def __init__(self, world, spelling, tmp_path, monkeypatch):
        self.spelling, self.clients, self.person = spelling, {}, None
        self.configuration = tmp_path / 'configuration.json'
        self.configuration.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': ORIGIN, 'project': 'p'}))
        for person in ('alice', 'bob', 'tina'):
            self.clients[person] = Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)
        monkeypatch.setattr(cli, 'Client', lambda url, project, credential: self.clients[self.person])
        monkeypatch.setattr(cli.Credential, 'from_file', staticmethod(lambda path: object()))
        monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))

    def __call__(self, person, *argv):
        self.person = person
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try: cli.main([self.spelling, *map(str, argv), '--configuration', str(self.configuration)])
            except SystemExit as stop: code = stop.code or 0
        err = err.getvalue()
        assert NOTICE.strip() not in err  # R2-8: piped, as a script runs it, neither spelling prints the notice
        return code, out.getvalue(), err


@pytest.mark.parametrize('spelling', ['tools', 'procedures'])
def test_the_catalogue_verbs_answer_the_same_under_both_spellings(world, tmp_path, monkeypatch, spelling):
    command = Command(world, spelling, tmp_path, monkeypatch)
    folder = tmp_path / 'depth-shift'
    shutil.copytree(BUNDLE, folder, ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in/tops.csv').write_text(TOPS)
    (tmp_path / 'in/tops.declared.json').write_text(json.dumps({'depth_unit': 'm', 'depth_basis': 'md'}))
    assert command('tina', 'register', folder) == (0, 'Registered Shift tops by a fixed depth, version 1. It is private: you and the '
                                                   'project administrators see it until an administrator enables it for everyone.\n', '')
    code, text, err = command('tina', 'list', '--json')
    [listed] = json.loads(text)['versions']
    assert (code, err, listed['name'], listed['version'], listed['state']) == (0, '', 'depth-shift', 1, 'private')
    assert command('alice', 'enable', 'depth-shift', '--version', 1) == (
        0, 'Enabled Shift tops by a fixed depth, version 1, for everyone in this project.\n', '')
    code, text, err = command('bob', 'show', 'depth-shift')
    assert (code, err) == (0, '') and text.startswith('Shift tops by a fixed depth, version 1 (depth-shift): enabled for everyone\n')
    argv = ['run', '--from-project', 'depth-shift', '--output', tmp_path / 'out', '--input', 'tops=%s' % (tmp_path / 'in/tops.csv'),
            '--kind', 'tops=well-tops-csv/1', '--declared', 'tops=%s' % (tmp_path / 'in/tops.declared.json'), '--setting', 'shift=2.5']
    code, text, err = command('bob', *argv)  # not a terminal and no --yes: refused at once
    assert (code, text) == (1, '') and err.startswith('Not run: this tool runs code someone else wrote') and not (tmp_path / 'out').exists()
    assert rows(world, 'SELECT principal FROM procedure_trust') == []  # the refusal comes before any trust
    code, text, err = command('bob', *argv, '--yes')
    assert (code, err) == (0, '') and text.startswith('Ran Shift tops by a fixed depth, version 1, on this computer')
    assert (tmp_path / 'out/shifted.csv').read_bytes() == SHIFTED
    assert rows(world, 'SELECT principal FROM procedure_trust') == [('bob',)]
    assert command('alice', 'trust', 'depth-shift', '--version', 1) == (0, 'You trust Shift tops by a fixed depth, version 1, in this project.\n', '')
    assert command('alice', 'withdraw', 'depth-shift', '--version', 1) == (
        0, 'Withdrew Shift tops by a fixed depth, version 1: it is never fetched or run again.\n', '')


@pytest.mark.parametrize('spelling', ['tools', 'procedures'])
def test_publish_and_again_make_the_same_calls_under_both_spellings(tmp_path, monkeypatch, spelling):
    calls = []

    class Recording:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def procedure_publish(self, folder, **options):
            calls.append(('publish', str(folder), options)); return {'sentence': 'Published.'}
        def procedure_again(self, *args, **options):
            calls.append(('again', [str(a) for a in args], {k: v for k, v in options.items() if k != 'prompt'}))
            return {'ran': 'Ran.', 'sentence': 'Same result.'}
    configuration = tmp_path / 'configuration.json'
    configuration.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': 'http://localhost', 'project': 'p'}))
    monkeypatch.setattr(cli, 'Client', lambda *a, **k: Recording())
    monkeypatch.setattr(cli.Credential, 'from_file', staticmethod(lambda path: object()))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        cli.main([spelling, 'publish', str(tmp_path / 'run'), '--name', 'Shifted', '--configuration', str(configuration)])
        cli.main([spelling, 'again', 'a1', '--revision', 'r1', '--output', str(tmp_path / 'again'), '--yes', '--configuration', str(configuration)])
    assert out.getvalue() == 'Published.\nRan.\nSame result.\n'
    assert calls == [('publish', str(tmp_path / 'run'), {'name': 'Shifted'}),
                     ('again', ['a1', 'r1', str(tmp_path / 'again')], {'version': None, 'folder': None, 'yes': True, 'name': None, 'for_': None})]
