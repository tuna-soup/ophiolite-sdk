"""E70a C5: `ophiolite check`, `get` and `send` through cli.entrypoint against the in-process gateway, with access keys
made the real way (test_access_key_chain.keyed). The sentence is what people read (stdout on success, stderr on a
refusal, as every other verb); the server's own text appears only under --json."""
import json
import re

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, ORIGIN  # noqa: F401
from test_exchange import key, remove, points, LAS_TEXT
from ophiolite import Client, Credential, cli
from ophiolite import exchange

DECLARE = ['--declare', 'crs=EPSG:32631']


@pytest.fixture
def run(keyed, tmp_path, monkeypatch, capsys):
    """run(key, work, *verb) -> (exit code, stdout, stderr); the key comes from OPHIOLITE_ACCESS_KEY, as for a script."""
    web = keyed
    config = tmp_path / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    cli._load()
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c))
    def call(made, work, verb, *rest):
        monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', made['key'])
        capsys.readouterr()
        try: cli.entrypoint([verb, '--configuration', str(config), '--credentials', str(tmp_path / 'not-saved.json'), '--work', str(tmp_path / work), *rest])
        except SystemExit as stop: code = stop.code
        else: code = 0
        out = capsys.readouterr()
        return code, out.out.strip(), out.err.strip()
    call.web = web
    return call


def test_check_get_and_send_from_the_command_line(run, tmp_path):
    web = run.web
    ka, kb, bob = key(web, 'alice'), key(web, 'alice'), key(web, 'bob')
    alice = Client(ORIGIN, 'p', Credential.bearer(ka['key']), web.c)
    base = points(1)
    parent = alice.upload_data(base.bytes, profile=base.profile, declared=base.declared, name='Picked points', attribution='Synthetic',
                               audience=['bob'], rights_confirmed=True, command_id='e70a-cli-parent')
    alice.share(parent, read=['bob'], reuse=['bob'], expected_generation=alice.grants(parent).generation)
    pid = parent.asset_id
    assert run(ka, 'a', 'check') == (0, 'You hold nothing yet. This first check noted the 1 item you can see; the next check lists what is new.', '')
    assert run(ka, 'a', 'get', '--item', pid, '--output', str(tmp_path / 'pa')) == (
        0, 'Got Picked points, version 1. You now hold it; saved in %s.' % (tmp_path / 'pa'), '')
    assert run(ka, 'a', 'get', '--item', pid, '--output', str(tmp_path / 'pa')) == (
        0, 'You already hold the latest version of Picked points, saved in %s.' % (tmp_path / 'pa'), '')
    v1, v2, v3 = (tmp_path / n for n in ('v1.csv', 'v2.csv', 'v3.csv'))
    for path, z in ((v1, 2), (v2, 3), (v3, 4)): path.write_bytes(points(z).bytes)
    send = ['--profile', 'points-csv/1', '--name', 'Porosity points', '--how', 'kriging', '--based-on', pid]
    assert run(ka, 'a', 'send', str(v1), *send, '--declare', 'crs') == (1, '', 'The project refused this: give each declaration as KEY=VALUE. Nothing was sent.')
    assert run(ka, 'a', 'send', str(v1), *send, *DECLARE) == (0, 'Sent Porosity points as a new item; it is private until you share it.', '')
    item = next(i for i, v in json.loads((tmp_path / 'a/held.json').read_text())['items'].items() if v.get('sent'))  # the id it now holds
    assert run(ka, 'a', 'send', str(v1), *send, *DECLARE, '--of', item) == (4, '', 'This is the same as version 1; nothing was sent.')
    for argv in (('check',), ('get', '--item', pid, '--output', str(tmp_path / 'pb')), ('get', '--item', item, '--output', str(tmp_path / 'ib'))):
        assert run(kb, 'b', *argv)[0] == 0
    assert 'EPSG:32631' in (tmp_path / 'ib/data.json').read_text() + (tmp_path / 'ib/descriptor.json').read_text()  # carried from --declare
    assert run(ka, 'a', 'send', str(v2), *send, '--of', item) == (0, 'Sent Porosity points as version 2. Version 1 is kept.', '')
    code, out, err = run(kb, 'b', 'send', str(v3), *send, *DECLARE, '--of', item)
    assert (code, out) == (4, '') and re.fullmatch(r'Version 2 was added by Alice[^,]*, [^.]+\. Your change was not sent\. Either get version 2 and look at it, '
                                                   r'or send yours as a new item\.', err), err
    code, out, err = run(kb, 'b', 'check')
    assert code == 0 and re.fullmatch(r'1 newer: Porosity points, version 2 by Alice[^,]*, .+\.', out), out
    assert run(kb, 'b', 'send', str(v3), *send[:-1], 'not-held-here', *DECLARE) == (1, '', 'You can only build on items you hold. Get that item first.')  # an id is never shown
    assert run(kb, 'b', 'get', '--item', 'nowhere', '--output', str(tmp_path / 'n')) == (
        4, '', 'You can no longer see this item. It may have been removed or no longer shared with you.')
    # Bob can read the parent but this key cannot send for him
    readonly = key(web, 'bob', 'read')
    for argv in (('check',), ('get', '--item', pid, '--output', str(tmp_path / 'bob-p'))): assert run(readonly, 'bob', *argv)[0] == 0
    assert run(readonly, 'bob', 'send', str(v3), *send, *DECLARE) == (3, '', 'The project did not allow this with this access key, so nothing was sent. '
                                                                           'Check that the key is for this project and can write, or ask the item\'s author.')
    code, out, err = run(readonly, 'bob', 'send', str(v3), *send, *DECLARE, '--json')
    error = json.loads(out)['error']
    assert code == 3 and err == '' and error['outcome'] == error['code'] == 'access-refused' and error['technical']['status'] == 403
    assert error['technical']['server_message']  # the server's own words: only here
    # a well log: its curves are named, or it is not received
    log = alice.upload_las(LAS_TEXT.encode(), name='Gamma log', attribution='Synthetic', audience=[], rights_confirmed=True)
    assert run(ka, 'a', 'get', '--item', log.asset_id, '--output', str(tmp_path / 'log')) == (
        1, '', 'This kind of item cannot be received by this script yet: name the curves to receive a well log.')
    code, out, err = run(ka, 'a', 'get', '--item', log.asset_id, '--output', str(tmp_path / 'log'), '--curve', 'GR', '--json')
    shown = json.loads(out)
    assert code == 0 and set(shown) == {'outcome', 'sentence', 'facts', 'technical'} and shown['outcome'] == 'got'
    assert shown['sentence'] == 'Got Gamma log, version 1. You now hold it; saved in %s.' % (tmp_path / 'log') and shown['facts']['name'] == 'Gamma log'
    remove(web, 'alice', ka['id'])
    assert run(ka, 'a', 'check') == (3, '', 'Your access key is not accepted any more. Ask for a new one.')


EXITS = {'not-visible': 4, 'cannot-read-here': 1, 'damaged': 1, 'map-unavailable': 4, 'newer-version-exists': 4, 'nothing-changed': 4, 'access-refused': 3,
         'not-valid': 1, 'not-held': 1, 'too-large': 1, 'outcome-unknown': 5, 'folder-busy': 5, 'rate-limited': 5, 'sign-in-needed': 3, 'could-not-reach': 5}


def test_every_refusal_has_its_documented_exit_code():
    assert set(EXITS) == set(exchange.REFUSALS)  # mutation: a refusal on another SDK category moves its code
    for code, cls in exchange.REFUSALS.items(): assert cli.exit_code(cls('s', {}, {})) == EXITS[code], code


BANNED = re.compile(r'\b(cursor|epoch|head|pull|push|follow|revision|authority|kind(?! of))s?\b', re.I)  # "this kind of item" is English, not the field
FACTS = {'name': 'Top Chalk', 'number': 2, 'who': 'Alice Example', 'when': '5 minutes ago', 'folder': 'maps', 'reason': 'a reason', 'reasons': 'a reason',
         'newer': [{'name': 'Top Chalk', 'number': 2}], 'new': [{'name': 'Porosity'}], 'lost': [{'name': 'Old grid'}], 'visible': 3, 'holding': True}


def test_the_default_layer_says_none_of_the_internal_words():
    texts = [exchange.SENTENCES[code](dict(FACTS)) for code in exchange.SENTENCES if code != 'cannot-read-here']
    texts.append(exchange.SENTENCES['cannot-read-here']({'reason': exchange.UPLOAD_SUCCESSOR}))
    sub = next(a for a in cli.parser()._actions if a.dest == 'command')
    for verb in ('check', 'get', 'send'):
        texts.append(sub.choices[verb].format_help().split('options:')[0].split('\n', 1)[1])  # the verb's description and arguments
        texts += [a.help or '' for a in sub.choices[verb]._actions] + [c.help for c in sub._choices_actions if c.dest == verb]
    assert [t for t in texts if BANNED.search(t)] == []


def test_the_held_folder_defaults_to_one_beside_the_script():
    from pathlib import Path
    for argv in (['check'], ['get', '--item', 'i', '--output', 'o'], ['send', 'f', '--profile', 'las2/1', '--name', 'n', '--how', 'h', '--based-on', 'i']):
        assert cli.parser().parse_args(argv).work == Path('.ophiolite-held')
