"""E105b C5, gateway lane: the project catalogue from the SDK and the command line against the real procedure routes
of an in-process gateway, signed in with access keys. tina registers and runs her own version (no question); alice,
an administrator, enables it; bob is asked once, with tina's name, the date and the exact digest, before anything
runs; his answer is his trust. A local copy is checked by digest before and while it runs; a withdrawal ends it."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path

import pytest
try:
    from project_gateway.tests.procedure_world import actions, rows
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
import ophiolite
from ophiolite import Client, Credential, cli, procedures
from ophiolite.procedures import NotRun

BUNDLE = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift'
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def bundle(tmp_path, version=1):
    folder = tmp_path / ('depth-shift-%d' % version)
    shutil.copytree(BUNDLE, folder, ignore=shutil.ignore_patterns('__pycache__'))
    if version != 1:
        manifest = json.loads((folder / 'procedure.json').read_text())
        manifest['version'] = version
        (folder / 'procedure.json').write_text(json.dumps(manifest, indent=2))
    return folder


@pytest.fixture
def setting(world, tmp_path):
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in/tops.csv').write_text(TOPS)
    (tmp_path / 'in/tops.declared.json').write_text(json.dumps({'depth_unit': 'm', 'depth_basis': 'md'}))
    return {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}


def run(client, tmp_path, out, **options):
    return client.procedure_run('depth-shift', tmp_path / out, {'tops': [tmp_path / 'in/tops.csv']}, kinds={'tops': 'well-tops-csv/1'},
                                declared={'tops': tmp_path / 'in/tops.declared.json'}, settings=['shift=2.5'], cache=tmp_path / ('cache-' + options.pop('who')),
                                **options)


class Asked:
    """The prompt: records each question and whether anything had run when it was asked."""
    def __init__(self, tmp_path, answer=True):
        self.tmp_path, self.answer, self.questions = tmp_path, answer, []

    def __call__(self, question):
        self.questions.append((question, sorted(p.name for p in self.tmp_path.iterdir() if p.name.startswith('out'))))
        return self.answer


def never(question): raise AssertionError('asked about a version the caller registered or trusts')


def test_the_registrant_runs_her_own_version_and_a_member_is_asked_once_per_version(world, setting, tmp_path):
    tina, alice, bob = setting['tina'], setting['alice'], setting['bob']
    v1 = tina.procedure_register(bundle(tmp_path))
    assert (v1['state'], v1['mine'], v1['already']) == ('private', True, False)
    mine = run(tina, tmp_path, 'out-tina', who='tina', version=1, prompt=never)
    assert (tmp_path / 'out-tina/shifted.csv').read_bytes() == SHIFTED and mine['run']['procedure']['digest'] == v1['digest']
    with pytest.raises(NotRun) as caught: run(bob, tmp_path, 'out-early', who='bob', prompt=never)
    assert caught.value.code == 'no-enabled-version' and str(caught.value) == 'Not run: depth-shift has no enabled version in this project.'
    alice.procedure_enable(v1['digest'])
    asked = Asked(tmp_path)
    run(bob, tmp_path, 'out-bob-1', who='bob', prompt=asked)
    [(question, ran_before)] = asked.questions
    assert (question['by'], question['digest'], question['version']) == ('tina', v1['digest'], 1) and question['date'] in question['text']
    assert ran_before == ['out-tina']  # nothing of bob's ran before the answer
    assert (tmp_path / 'out-bob-1/shifted.csv').read_bytes() == SHIFTED
    assert rows(world, 'SELECT principal,principal_kind FROM procedure_trust WHERE digest=?', v1['digest']) == [('bob', 'person')]
    assert len(actions(world, 'trust')) == 1
    run(bob, tmp_path, 'out-bob-2', who='bob', prompt=never)  # trusted: nothing asked
    v2 = tina.procedure_register(bundle(tmp_path, 2))
    alice.procedure_enable(v2['digest'])
    again = Asked(tmp_path)
    second = run(bob, tmp_path, 'out-bob-3', who='bob', prompt=again)
    assert [q['digest'] for q, _ in again.questions] == [v2['digest']] and second['run']['procedure']['version'] == 2


def test_a_declined_or_unanswerable_question_runs_and_records_nothing(world, setting, tmp_path):
    tina, alice, bob = setting['tina'], setting['alice'], setting['bob']
    v1 = tina.procedure_register(bundle(tmp_path)); alice.procedure_enable(v1['digest'])
    for prompt, code in ((Asked(tmp_path, answer=False), 'declined'), (None, 'trust-needed')):
        with pytest.raises(NotRun) as caught: run(bob, tmp_path, 'out-no', who='bob', prompt=prompt)
        assert caught.value.code == code and not (tmp_path / 'out-no').exists()
    assert rows(world, 'SELECT count(*) FROM procedure_trust')[0][0] == 0 and actions(world, 'trust') == []
    run(bob, tmp_path, 'out-yes', who='bob', yes=True)
    assert rows(world, 'SELECT principal FROM procedure_trust') == [('bob',)]


def test_a_changed_local_copy_is_refused_before_and_while_it_runs_and_a_withdrawal_ends_a_warm_cache(world, setting, tmp_path, monkeypatch):
    tina, alice, bob = setting['tina'], setting['alice'], setting['bob']
    v1 = tina.procedure_register(bundle(tmp_path)); alice.procedure_enable(v1['digest'])
    run(bob, tmp_path, 'out-1', who='bob', yes=True)
    cached = tmp_path / 'cache-bob' / v1['digest']
    code = cached / 'procedure.py'
    code.write_text(code.read_text() + '\n# changed\n')
    with pytest.raises(NotRun) as caught: run(bob, tmp_path, 'out-2', who='bob')
    assert caught.value.code == 'cache-changed' and not cached.exists() and not (tmp_path / 'out-2').exists()
    run(bob, tmp_path, 'out-3', who='bob')  # fetched again
    assert (tmp_path / 'out-3/shifted.csv').read_bytes() == SHIFTED
    def change(folder): (folder / 'procedure.py').write_text((folder / 'procedure.py').read_text() + '\n# changed while running\n')
    monkeypatch.setattr(procedures, '_before_run', change)
    with pytest.raises(NotRun) as caught: run(bob, tmp_path, 'out-4', who='bob')
    assert caught.value.code == 'changed-before-run' and not (tmp_path / 'out-4').exists()
    monkeypatch.setattr(procedures, '_before_run', lambda folder: None)
    shutil.rmtree(cached); run(bob, tmp_path, 'out-5', who='bob')  # warm again
    alice.procedure_withdraw(v1['digest'])
    with pytest.raises(NotRun) as caught: run(bob, tmp_path, 'out-6', who='bob', version=1)
    assert caught.value.code == 'withdrawn' and str(caught.value).startswith('Not run: this procedure was withdrawn on ') and not (tmp_path / 'out-6').exists()


def command(client, *argv):
    """(exit code, stdout, stderr) of one `ophiolite procedures …` catalogue verb with this client."""
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli._catalogue(cli.parser().parse_args(['procedures', *map(str, argv)]), client)
        except SystemExit as stop: code = stop.code or 0
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_the_command_line_registers_lists_enables_and_runs_with_yes_only(world, setting, tmp_path, monkeypatch):
    tina, alice, bob = setting['tina'], setting['alice'], setting['bob']
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    assert command(tina, 'register', bundle(tmp_path)) == (0, 'Registered Shift tops by a fixed depth, version 1. It is private: you and the project '
                                                             'administrators see it until an administrator enables it for everyone.', '')
    code, text, _ = command(tina, 'list', '--json')
    [listed] = json.loads(text)['versions']
    assert code == 0 and (listed['name'], listed['version'], listed['state']) == ('depth-shift', 1, 'private')
    assert command(alice, 'enable', 'depth-shift', '--version', 1) == (0, 'Enabled Shift tops by a fixed depth, version 1, for everyone in this project.', '')
    argv = ['run', '--from-project', 'depth-shift', '--output', tmp_path / 'out', '--input', 'tops=%s' % (tmp_path / 'in/tops.csv'), '--kind', 'tops=well-tops-csv/1',
            '--declared', 'tops=%s' % (tmp_path / 'in/tops.declared.json'), '--setting', 'shift=2.5']
    code, text, err = command(bob, *argv)  # not a terminal and no --yes: refused at once
    assert (code, text) == (1, '') and err.startswith('Not run: this procedure runs code someone else wrote') and not (tmp_path / 'out').exists()
    code, text, err = command(bob, *argv, '--yes')
    assert code == 0 and text.startswith('Ran Shift tops by a fixed depth, version 1, on this computer') and (tmp_path / 'out/shifted.csv').read_bytes() == SHIFTED
    assert rows(world, 'SELECT principal FROM procedure_trust') == [('bob',)]
