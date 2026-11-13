"""E70d C1: `send(of=<a held upload>)` adds the upload's next version through the upload-version route, against the
in-memory project (tests/helpers/exchange_fake.py). Each test names the mutation it catches; the real gateway's half is
tests/gateway/test_send_of_upload.py."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import Exchange

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha
NOW = 1000.0 + 300

V1, V2, V3 = b'x,y,z\n1,2,3\n', b'x,y,z\n1,2,4\n', b'x,y,z\n1,2,5\n'
SEND = dict(name='Top', profile='points-csv/1', how='picked again', based_on=['top'], of='top', rights_confirmed=True)


@pytest.fixture
def project():
    fake = Fake(); fake.add('top', V1, name='Top', kind='uploaded', profile='points-csv/1')
    return fake


def ex(fake, work):
    return Exchange(fake, work, clock=lambda: NOW)


def held(fake, tmp_path):
    e = ex(fake, tmp_path / 'w'); e.get('top', output=tmp_path / 'o')
    return e


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code and str(caught.value) == caught.value.sentence
    return caught.value


def test_an_upload_takes_its_next_version_by_upload_and_stays_an_upload(project, tmp_path):
    """Mutation: the entry written as 'derived' -> the third send takes the derive route -> red."""
    e = held(project, tmp_path)
    done = e.send(V2, **SEND)
    assert project.uploads[0]['resolved'] == {'parents': [], 'expected_parent': sha(V1), 'route': 'upload'}
    assert (done.outcome, done.sentence) == ('sent-version', 'Sent Top as version 2. Version 1 is kept.')
    entry = e.held()['top']
    assert (entry['kind'], entry['revision'], entry['number'], entry['sent']) == ('uploaded', sha(V2), 2, True)
    assert e.send(V3, **SEND).sentence == 'Sent Top as version 3. Version 2 is kept.'
    assert [u['resolved']['route'] for u in project.uploads] == ['upload', 'upload']


def test_a_send_keeps_the_words_and_the_mode_it_was_named_with(project, tmp_path):
    e = held(project, tmp_path)
    record = e._load(); record['items']['top'].update(words={'name': 'Top', 'type': 'point set'}, mode='stays'); e._save(record)
    e.send(V2, **SEND)
    assert {k: e.held()['top'][k] for k in ('words', 'mode', 'kind')} == {'words': {'name': 'Top', 'type': 'point set'}, 'mode': 'stays', 'kind': 'uploaded'}


@pytest.mark.parametrize('kind', ['derived', 'uploaded'])
def test_a_stale_head_reads_the_same_sentence_for_a_result_and_an_upload(tmp_path, kind):
    """Mutation: the upload route with a sentence of its own -> the two differ -> red."""
    fake = Fake(); fake.add('top', V1, name='Top', kind=kind, profile='points-csv/1')
    e = held(fake, tmp_path)
    fake.add('top', V2, name='Top', by='Ada', at=1240.0)
    send = dict(SEND, rights_confirmed=kind == 'uploaded')
    stale = refused('newer-version-exists', lambda: e.send(V3, **send))
    assert stale.sentence == ('Version 2 was added by Ada, 1 minute ago. Your change was not sent. '
                              'Either get version 2 and look at it, or send yours as a new item.')
    assert e._load()['pending'] is None and len(fake.items['top']['versions']) == 2


def test_the_servers_recurrence_sentences_name_their_version(project, tmp_path):
    """D4. Mutation: the adapter removed -> A/D2 repeated is classified by digest as version 1 -> red."""
    e = held(project, tmp_path)
    assert e.send(V1, **dict(SEND, declare={'z': 'depth'})).sentence == 'Sent Top as version 2. Version 1 is kept.'  # same bytes, new declarations
    again = refused('nothing-changed', lambda: e.send(V1, **dict(SEND, declare={'z': 'depth'})))
    assert again.sentence == 'This is the same as version 2; nothing was sent.'
    back = refused('earlier-version', lambda: e.send(V1, **SEND))
    assert back.sentence == 'This content was version 1 on 1 January 1970.'
    assert len(project.items['top']['versions']) == 2 and e._load()['pending'] is None


def test_a_stale_folder_sending_the_heads_bytes_under_other_declarations_is_told_it_is_stale(project, tmp_path):
    """Mutation: the stale sentence sent through `_stale`'s digest match -> "same as version 2" -> red."""
    e = held(project, tmp_path)
    project.add('top', V2, name='Top', by='Ada', at=1240.0)
    stale = refused('newer-version-exists', lambda: e.send(V2, **dict(SEND, declare={'z': 'depth'})))
    assert stale.sentence.startswith('Version 2 was added by Ada')


@pytest.mark.parametrize('change, sentence', [
    ({'rights_confirmed': False}, 'The project refused this: confirm that you may share this version. Nothing was sent.'),
    ({'based_on': ['top', 'other']}, "The project refused this: an upload's next version records only the version it builds on; "
                                     'name only Top as based on. Nothing was sent.'),
])
def test_an_upload_send_is_refused_before_anything_is_saved(project, tmp_path, change, sentence):
    project.add('other', b'other', name='Other')
    e = held(project, tmp_path); e.get('other')
    e._load()  # the folder holds both
    record = e._load(); record['items']['other'] = {'asset_id': 'other', 'name': 'Other', 'kind': 'derived', 'revision': sha(b'other')}; e._save(record)
    caught = refused('not-valid', lambda: e.send(V2, **dict(SEND, **change)))
    assert caught.sentence == sentence and e._load()['pending'] is None and project.uploads == []
    assert not [c for c in project.calls if c[0] == 'publish']


def test_rights_on_a_result_send_are_refused(tmp_path):
    fake = Fake(); fake.add('poro', V1, name='Porosity')
    e = ex(fake, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    caught = refused('not-valid', lambda: e.send(V2, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro', rights_confirmed=True))
    assert caught.sentence == ('The project refused this: only the next version of an upload asks you to confirm that you may share it. '
                               'Nothing was sent.')
    assert caught.technical == {'argument': 'rights_confirmed'} and e._load()['pending'] is None


def test_a_lost_answer_is_resent_once_and_adds_one_version(project, tmp_path):
    e = held(project, tmp_path)
    project.drop_after_commit = True
    unknown = refused('outcome-unknown', lambda: e.send(V2, **SEND))
    command = e._load()['pending']['command_id']
    assert e.send(V2, **SEND).sentence == 'Sent Top as version 2. Version 1 is kept.'
    assert len(project.items['top']['versions']) == 2 and unknown.technical['command_id'] == command
    assert [c[1] for c in project.calls if c[0] == 'publish'] == [command, command]


@pytest.mark.parametrize('change', [{'rights_confirmed': False}, {'declare': {'z': 'depth'}}, {'source': {'system': 'application:qgis-plugin', 'id': 'a'}},
                                    {'how': 'picked twice'}])
def test_an_unfinished_upload_send_refuses_a_changed_request_and_keeps_it(project, tmp_path, change):
    e = held(project, tmp_path)
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: e.send(V2, **SEND))
    saved = json.dumps(e._load()['pending'], sort_keys=True)
    caught = refused('not-valid', lambda: e.send(V2, **dict(SEND, **change)))
    assert 'an earlier send from this folder is unfinished' in caught.sentence
    assert json.dumps(e._load()['pending'], sort_keys=True) == saved


def test_an_unfinished_upload_send_under_another_key_is_unknown(project, tmp_path):
    e = held(project, tmp_path)
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: e.send(V2, **SEND))
    project.key = 'key-2'
    caught = refused('outcome-unknown', lambda: e.send(V2, **SEND))
    assert caught.facts.get('other_key') is True


def test_a_transport_without_the_upload_route_keeps_todays_refusal(project, tmp_path):
    """The QGIS plug-in's transport has no `appends_uploads`: its words stay E121 B7's, byte for byte."""
    project.appends_uploads = False
    e = held(project, tmp_path)
    caught = refused('not-valid', lambda: e.send(V2, **SEND))
    assert caught.sentence == ('The project refused this: Top is an upload, which does not take a sent version; '
                               'send this as a new item based on it. Nothing was sent.')
    assert project.uploads == []


def test_a_pending_result_send_saved_before_the_upgrade_is_resent_unchanged(tmp_path):
    fake = Fake(); fake.add('poro', V1, name='Porosity')
    e = ex(fake, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    request = {'name': 'Porosity', 'profile': 'table/1', 'how': 'edit', 'based_on': ['poro'], 'of': 'poro', 'declare': {}, 'extra': {},
               'sha256': sha(V2), 'bytes': len(V2)}
    record = e._load()
    record['pending'] = {'command_id': 'c' * 32, 'request': request, 'owner': fake.identity(), 'started': NOW,
                         'resolved': {'parents': [{'asset_id': 'poro', 'revision': sha(V1)}], 'expected_parent': sha(V1)}}
    e._save(record)
    done = e.send(V2, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro')
    assert done.outcome == 'sent-version' and fake.uploads == [] and e.held()['poro']['kind'] == 'derived'


def test_without_history_the_upload_send_says_a_new_version(project, tmp_path):
    e = held(project, tmp_path)
    project.history_fails = True
    done = e.send(V2, **SEND)
    assert (done.outcome, done.sentence) == ('sent-version', 'Sent Top as a new version. The earlier version is kept.')


def test_refusals_on_the_upload_route(project, tmp_path):
    e = held(project, tmp_path)
    project.person = 'bob'
    assert refused('access-refused', lambda: e.send(V2, **SEND))
    project.person = 'alice'; project.items['top']['versioned'] = False
    caught = refused('not-valid', lambda: e.send(V2, **SEND))
    assert caught.sentence == 'The project refused this: this type of file does not take a new version by upload. Nothing was sent.'
    assert e._load()['pending'] is None and project.uploads == []
    project.items['top'].pop('versioned'); project.fail['publish'] = fake_module.ERRORS['invalid']()
    assert refused('not-valid', lambda: e.send(V2, **SEND)).sentence == 'The project refused this: the request was not accepted. Nothing was sent.'
