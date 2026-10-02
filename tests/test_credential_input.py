"""E51a C4: one reader for a credential a person supplies. It trims what a terminal or a hand selection spoils,
removes a stray "Bearer ", says what it removed (never the value), and refuses only an empty value, a space or line
break inside it, or a control character. It never refuses a credential for its prefix."""
import io
import json

import pytest

from ophiolite import cli, auth, Credential
from ophiolite.credential_input import read_credential, notice
from ophiolite.errors import Refused

KEY = 'oph_key_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'


@pytest.mark.parametrize('value,expected,notes', [
    (KEY, KEY, ()),
    (KEY + '\n', KEY, ('line-break',)),
    (KEY + '\r\n', KEY, ('line-break',)),
    ('  ' + KEY + '  ', KEY, ('surrounding-space',)),
    ('Bearer ' + KEY, KEY, ('bearer-prefix',)),
    ('bearer ' + KEY, KEY, ('bearer-prefix',)),
    (' Bearer ' + KEY + '\n', KEY, ('line-break', 'surrounding-space', 'bearer-prefix')),
    ('abc123', 'abc123', ()),
    ('oph_agent_x', 'oph_agent_x', ()),
    ('eyJhbGciOi.opaque-provider-token.sig', 'eyJhbGciOi.opaque-provider-token.sig', ()),
])
def test_the_reader_table(value, expected, notes):
    assert read_credential(value, source='argument') == (expected, notes)


@pytest.mark.parametrize('value,sentence', [
    ('Bearer Bearer ' + KEY, 'has a space or line break inside it'),
    ('', 'is empty'),
    ('   \n', 'is empty'),
    ('oph_key_A B', 'has a space or line break inside it'),
    ('oph_key_A\nB', 'has a space or line break inside it'),
    ('A\x00B', 'contains a control character'),
    ('\x1b', 'contains a control character'),
])
def test_the_reader_refuses_with_a_sentence_and_never_the_value(value, sentence):
    with pytest.raises(Refused) as refused: read_credential(value, source='argument')
    assert sentence in str(refused.value)
    if value.strip(): assert value.strip() not in str(refused.value) and 'oph_key_A' not in str(refused.value)


def test_oversized_input_is_refused():
    with pytest.raises(Refused, match='4 KiB'): read_credential('x' * 4097, source='file')
    assert read_credential('x' * 4096, source='file')[0] == 'x' * 4096


def test_the_notice_names_what_was_removed_and_the_application_field():
    text = notice(('line-break', 'bearer-prefix'))
    assert 'A line break' in text and '"Bearer "' in text and "the application's field needs the corrected value" in text
    assert notice(()) is None


def test_credential_bearer_reads_through_the_reader():
    spoiled = Credential.bearer(KEY + '\n')
    assert spoiled.headers('http://localhost', 'p') == {'Authorization': 'Bearer ' + KEY}
    assert spoiled.normalised == ('line-break',) and 'AAAA' not in repr(spoiled)
    with pytest.raises(Refused, match='space or line break inside'): Credential.bearer('oph_key_A B')


def test_provider_grant_and_automation_credentials_are_unchanged():
    for token in ('oph_api_alice', 'opaque-provider-token'):
        assert Credential.bearer(token).headers('http://localhost', 'p')['Authorization'] == 'Bearer ' + token
    granted = Credential.bearer('opaque-provider-token', grant='g1')
    assert granted.grant == 'g1' and granted.normalised == ()
    with pytest.raises(Refused): Credential.bearer('opaque-provider-token', grant='g 1')  # the grant is untouched: still no whitespace


def test_key_login_trims_and_keeps_its_prefix_rule(tmp_path):
    saved = auth.key_login('http://localhost', 'p', KEY + '\r\n', path=tmp_path / 'k.json')
    assert json.loads((tmp_path / 'k.json').read_text())['credential']['access_key'] == KEY and saved.kind == 'access_key'
    with pytest.raises(Refused, match='not a project access key'): auth.key_login('http://localhost', 'p', 'oph_api_alice', path=tmp_path / 'other.json')


def configuration(tmp_path):
    path = tmp_path / 'configuration.json'; path.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': 'http://localhost', 'project': 'p'})); return path


def sources(tmp_path, monkeypatch):
    """Every way the command line takes a key, each run once: name -> argv (stdin and environment set by the caller)."""
    config = configuration(tmp_path)
    key_file = tmp_path / 'key.txt'; key_file.write_text(KEY + '\n')
    return {
        'login --key': (['login', '--configuration', str(config), '--credentials', str(tmp_path / 'a.json'), '--key', KEY], None, None),
        'login --key-file': (['login', '--configuration', str(config), '--credentials', str(tmp_path / 'b.json'), '--key-file', str(key_file)], None, None),
        'login --key-stdin': (['login', '--configuration', str(config), '--credentials', str(tmp_path / 'c.json'), '--key-stdin'], KEY + '\n', None),
        'login from the environment': (['login', '--configuration', str(config), '--credentials', str(tmp_path / 'd.json')], None, KEY),
        'projects from the environment': (['projects', '--url', 'http://localhost'], None, KEY),
        'projects --key-file': (['projects', '--url', 'http://localhost', '--key-file', str(key_file)], None, None),
        'projects --key-stdin': (['projects', '--url', 'http://localhost', '--key-stdin'], KEY, None),
        'status from the environment': (['status', '--configuration', str(config), '--credentials', str(tmp_path / 'none.json')], None, KEY),
    }


class FakeAccount:
    def __init__(self, url, credential): FakeAccount.seen.append(credential.headers(url, 'p')['Authorization'])
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def projects(self, limit=50): return [{'id': 'p', 'name': 'P', 'role': 'viewer'}]
    def organizations(self): return []


def run(argv, stdin, env, monkeypatch):
    import ophiolite.account
    monkeypatch.setattr(ophiolite.account, 'Account', FakeAccount)
    monkeypatch.setattr('sys.stdin', io.StringIO(stdin or ''))
    if env is None: monkeypatch.delenv('OPHIOLITE_ACCESS_KEY', raising=False)
    else: monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', env)
    return cli.main(argv)


def test_each_source_goes_through_the_reader(tmp_path, monkeypatch):
    """With the reader refusing, every way a key is supplied must refuse: no path bypasses it."""
    import ophiolite.credential_input as reader
    def refuse(value, *, source): raise Refused('reader refused ' + source)
    monkeypatch.setattr(reader, 'read_credential', refuse)
    for name, (argv, stdin, env) in sources(tmp_path, monkeypatch).items():
        with pytest.raises(Refused, match='reader refused'): run(argv, stdin, env, monkeypatch)


def test_a_spoiled_key_from_each_source_arrives_clean(tmp_path, monkeypatch, capsys):
    FakeAccount.seen = []
    for name, (argv, stdin, env) in sources(tmp_path, monkeypatch).items():
        if name.startswith('login'):
            run(argv, stdin, (env + '\n') if env else env, monkeypatch)
            saved = json.loads(Path_(argv[argv.index('--credentials') + 1]).read_text())['credential']['access_key']
            assert saved == KEY, name
        elif name.startswith('projects'):
            run(argv, stdin, (env + '\n') if env else env, monkeypatch)
    assert FakeAccount.seen and set(FakeAccount.seen) == {'Bearer ' + KEY}
    out = capsys.readouterr()
    assert "the application's field needs the corrected value" in out.err and KEY not in out.out + out.err


def Path_(value):
    from pathlib import Path
    return Path(value)


def test_source_precedence_and_an_empty_environment_value(tmp_path, monkeypatch):
    key_file = tmp_path / 'key.txt'; key_file.write_text('oph_key_FROMFILE')
    args = cli.parser().parse_args(['projects', '--url', 'http://localhost', '--key-file', str(key_file)])
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_key_FROMENV')
    assert cli.supplied_key(args)[0] == 'oph_key_FROMFILE'  # a key named on the command line wins over the environment
    args = cli.parser().parse_args(['projects', '--url', 'http://localhost'])
    assert cli.supplied_key(args)[0] == 'oph_key_FROMENV'
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', '')
    with pytest.raises(Refused, match='OPHIOLITE_ACCESS_KEY is empty'): cli.supplied_key(args)
    monkeypatch.delenv('OPHIOLITE_ACCESS_KEY')
    assert cli.supplied_key(args) is None


def test_the_cli_reports_the_removal_in_json_too(tmp_path, monkeypatch, capsys):
    FakeAccount.seen = []
    run(['projects', '--url', 'http://localhost', '--json'], None, '  ' + KEY + '\n', monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert payload['normalised'] == ['line-break', 'surrounding-space'] and payload['projects'][0]['id'] == 'p'


def test_saved_credentials_are_read_unchanged(tmp_path):
    path = tmp_path / 'k.json'
    auth.key_login('http://localhost', 'p', KEY, path=path)
    value = json.loads(path.read_text()); value['credential']['access_key'] = KEY + ' '
    path.write_text(json.dumps(value))
    with pytest.raises(Exception): Credential.from_file(path)  # the saved-store loader keeps its own strict rule
