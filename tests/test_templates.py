"""Versioned source templates and their separately provisioned, required CI lane."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import pytest
from ophiolite import __version__
ROOT=Path(__file__).resolve().parents[1]
NAMES=('agent-workflow','notebook','derive-and-publish','map-application','sync-worker')


def test_template_versions_follow_sdk_and_have_real_commands():
    # E17p D3: the SDK version is the release name, read from _version.py; a template keeps the version of the SDK
    # commit its requirements.in locks (E31's accepted 0.1.0), which no longer moves with the release
    source_version=re.search(r"""^__version__ = '([^']+)'""",(ROOT/'ophiolite/_version.py').read_text(),re.M).group(1)
    assert source_version==__version__
    assert 'dynamic = ["version"]' in (ROOT/'pyproject.toml').read_text()
    for name in NAMES:
        directory=ROOT/'ophiolite/templates'/name;metadata=json.loads((directory/'template.json').read_text())
        assert metadata['template_version']==metadata['sdk_version']=='0.1.0'
        assert metadata['test_command']==(['python','tools/test.py'] if name=='map-application' else ['python','-m','pytest','-q','tests'])
        assert 'template_version' in (directory/'README.md').read_text()
        assert 'file://' not in (directory/'requirements.lock').read_text()


def test_notebook_is_generated_from_paired_script():
    subprocess.run([sys.executable,str(ROOT/'tools/build_notebook.py'),'--check'],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('name',NAMES)
def test_template_command(name):
    if os.environ.get('OPHIOLITE_RUN_TEMPLATES')!='1':pytest.skip('Provision locked template dependencies and run the required template lane')
    directory=ROOT/'ophiolite/templates'/name;command=json.loads((directory/'template.json').read_text())['test_command']
    result=subprocess.run([sys.executable,*command[1:]],cwd=directory,env=dict(os.environ,OPHIOLITE_PYTHON=sys.executable),capture_output=True,text=True,timeout=240)
    assert result.returncode==0,result.stdout+result.stderr


def test_the_template_client_uses_the_access_key_the_readme_names(tmp_path, monkeypatch):
    """H4 (E32 F8): with OPHIOLITE_ACCESS_KEY set and no credential file named or saved, support.client_for uses the
    key, as the sync-worker and map-application READMEs and the command line say; a saved or a named credential
    still wins, and a dangling saved link is not mistaken for 'nothing saved' (as on the command line)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ophiolite/templates'))
    import support
    from ophiolite import auth
    url, env_key, saved_key, named_key = 'https://ophiolite.example', 'oph_key_' + 'e' * 40, 'oph_key_' + 's' * 40, 'oph_key_' + 'n' * 40
    monkeypatch.setenv('HOME', str(tmp_path)); monkeypatch.delenv('OPHIOLITE_CREDENTIAL', raising=False)
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', env_key)
    with support.client_for(url, 'p') as client:
        assert client.credential.kind == 'bearer' and client.credential.token == env_key
    saved = auth.default_path(url, 'p')
    auth.key_login(url, 'p', saved_key, path=saved)
    with support.client_for(url, 'p') as client:
        assert client.credential.kind == 'access_key' and Path(client.credential.path) == saved  # the saved sign-in wins
    named = tmp_path / 'named.json'; auth.key_login(url, 'p', named_key, path=named)
    monkeypatch.setenv('OPHIOLITE_CREDENTIAL', str(named))
    with support.client_for(url, 'p') as client:
        assert Path(client.credential.path) == named  # a named file wins
    monkeypatch.delenv('OPHIOLITE_CREDENTIAL'); saved.unlink(); saved.symlink_to(tmp_path / 'missing.json')
    with pytest.raises(Exception) as refused:
        support.client_for(url, 'p')  # a dangling saved link is refused, never replaced by the environment key
    assert env_key not in str(refused.value)


def test_history_explains_that_uploaded_originals_have_no_listed_versions():
    """H4 (E32 F4): refused in plain words before any request, instead of the server's misleading refusal."""
    import httpx
    from ophiolite import Client, Credential
    from ophiolite.errors import Refused
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))
    client = Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_' + 'k' * 40), http=httpx.Client(transport=transport))
    with pytest.raises(Refused, match='uploaded original'):
        client.history({'asset_id': 'a', 'revision': 'r', 'authority': 'ophiolite:uploaded'})
    assert requests == []  # nothing was sent


# E162 s1 C2 (K16): derive-and-publish's printed answer, frozen before the --configuration and --credentials flags were
# added. Normalised: the command id is generated per run, the publication id is derived from it, and the work folder is
# the run's own; everything else, the derived file's revision and the template's method included, is literal.
FROZEN_ANSWER = {'state': 'published', 'receipt': {
    'asset_id': '<publication>', 'revision': '4f6fb253ed4d373fc84e7f2d53e641f77b3e479c5009044cc3886ae543b0ce96', 'revision_number': 1,
    'profile': 'las2/1', 'derived_from': [{'authority': 'ophiolite:derived', 'key': 'curve-a',
                                          'revision': 'd899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b', 'profile': 'las2/1'}],
    'method': {'name': 'multiply', 'declared': True, 'library': 'ophiolite-template', 'version': '0.1.0',
               'parameters': {'factor': 2, 'curve': 'GR'}, 'script_sha256': None},
    'command_id': '<command>'}, 'work_folder': '<work>'}


def _template_answer(argv, capsys, work):
    sys.path.insert(0, str(ROOT / 'ophiolite/templates'))
    import support
    assert support.command([*argv, '--work', str(work)]) == 0, capsys.readouterr().err
    answer = json.loads(capsys.readouterr().out)
    assert re.fullmatch(r'[0-9a-f]{32}', answer['receipt']['command_id']) and re.fullmatch(r'[0-9a-f]{64}', answer['receipt']['asset_id'])
    assert answer['work_folder'] == str(work)
    answer['receipt'].update(asset_id='<publication>', command_id='<command>'); answer['work_folder'] = '<work>'
    return answer


def _closed_port():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def test_derive_and_publish_answers_as_frozen_in_fixture_and_environment_modes(tmp_path, capsys, monkeypatch):
    """K16: the flags change neither existing path. Mutation: let an absent --configuration replace the environment →
    KeyError or another server, not the frozen answer."""
    from ophiolite.testing import synthetic_server
    assert _template_answer(['--fixture'], capsys, tmp_path / 'fixture') == FROZEN_ANSWER
    monkeypatch.setenv('HOME', str(tmp_path)); monkeypatch.delenv('OPHIOLITE_CREDENTIAL', raising=False)
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice')
    with synthetic_server() as server:
        monkeypatch.setenv('OPHIOLITE_URL', server.url); monkeypatch.setenv('OPHIOLITE_PROJECT', 'p')
        assert _template_answer([], capsys, tmp_path / 'environment') == FROZEN_ANSWER


def test_derive_and_publish_runs_on_a_base_install_without_jsonschema(tmp_path, capsys, monkeypatch):
    """E162 s1 (found by the F3 run on a fresh install): `ophiolite demo`'s third line runs the template with the SDK's
    own interpreter, which a base install leaves without the `validation` extra. Mutation: call validate.schema
    unconditionally → ModuleNotFoundError; skip silently → the stderr line is missing (ruling 9 Nov)."""
    import importlib.util
    found = importlib.util.find_spec
    monkeypatch.setitem(sys.modules, 'jsonschema', None)  # an import of it fails, as in a base install
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *a: None if name == 'jsonschema' else found(name, *a))
    sys.path.insert(0, str(ROOT / 'ophiolite/templates'))
    import support
    assert support.command(['--fixture', '--work', str(tmp_path / 'fixture')]) == 0
    said = capsys.readouterr()
    assert said.err == 'schema check skipped: install ophiolite[validation]\n'
    answer = json.loads(said.out); answer['receipt'].update(asset_id='<publication>', command_id='<command>'); answer['work_folder'] = '<work>'
    assert answer == FROZEN_ANSWER


def test_configuration_and_credentials_flags_win_over_the_environment(tmp_path, capsys, monkeypatch):
    """K13: with OPHIOLITE_URL on a closed port, OPHIOLITE_PROJECT another project and an environment key, the files
    the flags name reach the server. Mutation: read the environment first → connection refused (exit 2)."""
    from ophiolite import auth
    from ophiolite.testing import synthetic_server
    monkeypatch.setenv('HOME', str(tmp_path)); monkeypatch.delenv('OPHIOLITE_CREDENTIAL', raising=False)
    monkeypatch.setenv('OPHIOLITE_URL', 'http://127.0.0.1:%d' % _closed_port()); monkeypatch.setenv('OPHIOLITE_PROJECT', 'other')
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_expired')
    with synthetic_server() as server:
        configuration = tmp_path / 'configuration.json'
        configuration.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': server.url, 'project': 'p'}))
        credentials = tmp_path / 'credential.json'; auth.key_login(server.url, 'p', 'oph_key_' + 'a' * 40, path=credentials)
        assert _template_answer(['--configuration', str(configuration), '--credentials', str(credentials)], capsys, tmp_path / 'w') == FROZEN_ANSWER
        assert any(r['path'].endswith('/publications/derive') for r in server.requests)  # published on the configured server


class _Catalogue:
    """A client whose catalogue is `items`; `read` records what it is asked and stops the template there."""
    def __init__(self, items):
        self.items, self.asked = items, []

    def assets(self):
        return iter(self.items)

    def read(self, asset, revision, curves):
        self.asked.append((asset, revision, list(curves)))
        raise LookupError('read')


def test_the_template_reads_the_catalogues_first_item_that_carries_the_curve():
    """E162 s1b: a survey first, then two GR logs (b before a, unlike their names). Mutations: the catalogue's first
    item → the survey is read; the item chosen by name → a; an explicit asset ignored → b."""
    sys.path.insert(0, str(ROOT / 'ophiolite/templates'))
    import support
    from ophiolite.errors import Refused
    items = [{'asset_id': 'survey', 'revision': '1', 'curves': None}, {'asset_id': 'b', 'revision': '2', 'curves': ['GR']},
             {'asset_id': 'a', 'revision': '3', 'curves': ['GR', 'RHOB']}]
    for call, expected in ((lambda c: support.stage(c, 'w'), ('b', '2', ['GR'])),
                           (lambda c: support.stage(c, 'w', curve='RHOB'), ('a', '3', ['RHOB'])),
                           (lambda c: support.stage(c, 'w', asset=items[2]), ('a', '3', ['GR'])),
                           (lambda c: support.interval_offset(c, 'w'), ('b', '2', ['GR']))):
        client = _Catalogue(items)
        with pytest.raises(LookupError): call(client)
        assert client.asked == [expected]
    for call in (lambda c: support.stage(c, 'w'), lambda c: support.interval_offset(c, 'w')):
        with pytest.raises(Refused, match='No permitted curve is available'): call(_Catalogue(items[:1]))
