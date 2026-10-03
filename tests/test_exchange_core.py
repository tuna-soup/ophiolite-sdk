"""E70a C2: the check, get and send core against an in-memory project (tests/helpers/exchange_fake.py). Each test
names the mutation it catches."""
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.cli import exit_code
from ophiolite.exchange import Exchange, Outcome

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, ERRORS, sha = fake_module.Fake, fake_module.ERRORS, fake_module.sha
NOW = 1000.0 + 300  # five minutes after the fixtures' first versions

V1, V2, V3 = b'porosity v1', b'porosity v2', b'porosity v3'
IDENT = re.compile(r'[0-9a-f]{32,}|oph_|usr_|[0-9a-f]{8}-[0-9a-f]{4}-|exchange-consumer/1|derived|uploaded|external-scalar-map|revision-conflict', re.I)


@pytest.fixture
def project():
    fake = Fake(); fake.add('poro', V1, name='Porosity'); fake.add('map', b'grid', name='Top Chalk map', by='Bob Example')
    return fake


def ex(fake, work, **options):
    return Exchange(fake, work, clock=lambda: NOW, **options)


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code and str(caught.value) == caught.value.sentence
    return caught.value


# -- every outcome: exact code and sentence -----------------------------------------------------------

def test_check_says_nothing_new_and_records_a_baseline_first(project, tmp_path):
    first = ex(project, tmp_path).check()
    assert (first.outcome, first.sentence) == ('nothing-new', 'You hold nothing yet. This first check noted the 2 items you can see; the next check lists what is new.')
    again = ex(project, tmp_path).check()
    assert (again.outcome, again.sentence) == ('nothing-new', 'You hold nothing yet.')


def test_get_then_check_then_newer_with_who_and_when(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.check()
    got = e.get('poro', output=tmp_path / 'out')
    assert (got.outcome, got.sentence) == ('got', 'Got Porosity, version 1 by Alice Example, 5 minutes ago. You now hold it; saved in %s.' % (tmp_path / 'out'))
    assert (tmp_path / 'out/data.bin').read_bytes() == V1
    assert e.check().sentence == 'Nothing is newer than what you hold.'
    project.add('poro', V2, name='Porosity', by='Alice Example', at=1240.0)
    newer = e.check()
    assert (newer.outcome, newer.sentence) == ('updates', '1 newer: Porosity, version 2 by Alice Example, 1 minute ago.')


def test_already_latest_needs_the_verified_artifact_in_this_folder_for_this_selection(project, tmp_path):
    e = ex(project, tmp_path / 'w'); out = tmp_path / 'out'
    e.get('poro', output=out)
    again = e.get('poro', output=out)
    assert (again.outcome, again.sentence) == ('already-latest', 'You already hold the latest version of Porosity, saved in %s.' % out)
    fetches = lambda: sum(1 for c in project.calls if c[0] == 'fetch')
    before = fetches()
    (out / 'data.bin').write_bytes(b'edited')                      # an edited file
    assert e.get('poro', output=out).outcome == 'got' and fetches() == before + 1
    assert e.get('poro', output=tmp_path / 'second').outcome == 'got'  # a second folder
    assert e.get('poro', output=tmp_path / 'second', curves=['GR']).outcome == 'got'  # another selection
    import shutil; shutil.rmtree(tmp_path / 'second')
    assert e.get('poro', output=tmp_path / 'second', curves=['GR']).outcome == 'got'  # deleted
    assert e.get('poro').outcome == 'got'                           # in memory: nothing is claimed present
    assert e.get('poro').outcome == 'got'


def test_not_visible_and_access_changed_keep_the_entry_and_a_reappearing_item_is_listed(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.check(); e.get('poro', output=tmp_path / 'out')
    project.hidden.add('poro')
    lost = e.check()
    assert (lost.outcome, lost.sentence) == ('access-changed', 'You can no longer see 1 item you hold: Porosity. They may have been removed or no longer shared with you.')
    gone = refused('not-visible', lambda: e.get('poro', output=tmp_path / 'out'))
    assert gone.sentence == 'You can no longer see Porosity. It may have been removed or no longer shared with you.' and exit_code(gone) == 4
    assert 'poro' in e.held()
    project.hidden.clear(); project.add('poro', V2, name='Porosity', at=1240.0)
    back = e.check()
    assert back.outcome == 'updates' and back.sentence.startswith('1 newer: Porosity, version 2')


def test_check_lists_newer_new_and_lost_in_one_answer_and_history_failure_only_drops_who(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.check(); e.get('poro', output=tmp_path / 'a'); e.get('map', output=tmp_path / 'b')
    project.add('poro', V2, name='Porosity', at=1240.0); project.hidden.add('map'); project.add('vsh', b'v', name='Shale volume')
    project.history_fails = True
    both = e.check()
    assert (both.outcome, both.sentence) == ('updates', '1 newer: Porosity. 1 new since your last check: Shale volume. 1 you can no longer see: Top Chalk map.')
    only_new = ex(project, tmp_path / 'w'); project.history_fails = False
    project.add('nphi', b'n', name='Neutron')
    assert 'new since your last check: Neutron' in only_new.check().sentence


def test_cannot_read_here_damaged_and_map_unavailable_sentences(project, tmp_path):
    e = ex(project, tmp_path / 'w')
    project.fail['fetch'] = exchange.CannotReadHere('', {'reason': 'a seismic volume is described here, not received'})
    cannot = refused('cannot-read-here', lambda: e.get('poro', output=tmp_path / 'o'))
    assert cannot.sentence == 'This kind of item cannot be received by this script yet: a seismic volume is described here, not received.' and exit_code(cannot) == 1
    project.fail['fetch'] = exchange.Damaged('', {})
    assert refused('damaged', lambda: e.get('poro', output=tmp_path / 'o')).sentence == 'The data did not match its fingerprint. Nothing was kept.'
    project.fail['fetch'] = exchange.MapUnavailable('', {})
    unavailable = refused('map-unavailable', lambda: e.get('map', output=tmp_path / 'o'))
    assert unavailable.sentence == 'That version of the map is not available (it may be withdrawn or not the one you hold).' and exit_code(unavailable) == 4
    assert not (tmp_path / 'o').exists() and not list(tmp_path.glob('.o.partial-*'))


@pytest.mark.parametrize('error,code,sentence,exit', [
    ('expired', 'sign-in-needed', 'Your access key is not accepted any more. Ask for a new one.', 3),
    ('busy', 'rate-limited', 'The project is busy. Wait a moment and run this again.', 5),
    ('down', 'could-not-reach', 'Could not reach the project. Nothing was changed; for send, run the same command again: it will not publish twice.', 5)])
def test_transport_failures_in_check_and_get(project, tmp_path, error, code, sentence, exit):
    e = ex(project, tmp_path / 'w')
    project.fail['inventory'] = ERRORS[error]()
    for call in (e.check, lambda: e.get('poro')):
        caught = refused(code, call)
        assert caught.sentence == sentence and exit_code(caught) == exit


def test_send_new_and_version_sentences(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    new = e.send(b'my porosity', name='Porosity (mine)', profile='table/1', how='cutoff 0.1', based_on=['poro'])
    assert (new.outcome, new.sentence) == ('sent-new', 'Sent Porosity (mine) as a new item; it is private until you share it.')
    version = e.send(V2, name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro')
    assert (version.outcome, version.sentence) == ('sent-version', 'Sent Porosity as version 2. Version 1 is kept.')
    assert e.held()['poro']['revision'] == sha(V2) and e.held()['poro']['number'] == 2


# -- the parent is the held version, never the head ---------------------------------------------------

def test_send_submits_the_held_parent_and_a_newer_version_is_named(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')    # holds v1 ("aaa")
    project.add('poro', V2, name='Porosity', by='Alice Example', at=1240.0)  # the head moved ("bbb")
    stale = refused('newer-version-exists', lambda: e.send(V3, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro'))
    assert [c[2] for c in project.calls if c[0] == 'publish'] == [sha(V1)]   # mutation: submit the head -> the fake accepts
    assert stale.sentence == ('Version 2 was added by Alice Example, 1 minute ago. Your change was not sent. '
                              'Either get version 2 and look at it, or send yours as a new item.') and exit_code(stale) == 4
    assert e._load()['pending'] is None and e.held()['poro']['revision'] == sha(V1)


def test_a_stale_refusal_without_history_says_a_newer_version_was_added(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.add('poro', V2, name='Porosity', at=1240.0); project.history_fails = True
    stale = refused('newer-version-exists', lambda: e.send(V3, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro'))
    assert stale.sentence == ('A newer version was added first. Your change was not sent. Either get the latest version and look at it, '
                              'or send yours as a new item.')


def test_a_transport_call_without_a_parent_is_never_made(project, tmp_path):
    e = ex(project, tmp_path / 'w')
    missing = refused('not-valid', lambda: e.send(V3, name='Porosity', profile='table/1', how='edit', based_on=[]))
    assert missing.sentence == 'The project refused this: name between 1 and 32 items it is based on, each once. Nothing was sent.'
    not_held = refused('not-held', lambda: e.send(V3, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro'))
    assert not_held.sentence == 'You can only build on items you hold. Get that item first.'
    assert not [c for c in project.calls if c[0] == 'publish']


def test_duplicate_content_names_the_earlier_version(project, tmp_path):
    project.add('poro', V2, name='Porosity'); project.add('poro', V3, name='Porosity')
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')    # holds v3
    same = refused('nothing-changed', lambda: e.send(V1, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro'))
    assert same.sentence == 'This is the same as version 1; nothing was sent.'   # not "version 3"
    local = refused('nothing-changed', lambda: e.send(V3, name='Porosity', profile='table/1', how='edit', based_on=['poro'], of='poro'))
    assert local.sentence == 'This is the same as version 3; nothing was sent.' and len([c for c in project.calls if c[0] == 'publish']) == 1


# -- the pending command ------------------------------------------------------------------------------

def send(e, data=V2, **changes):
    options = dict(name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro'); options.update(changes)
    return e.send(data, **options)


def test_a_lost_answer_is_recovered_by_the_same_send_and_never_publishes_twice(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.drop_after_commit = True
    unknown = refused('outcome-unknown', lambda: send(e))
    assert unknown.sentence == 'An earlier send of Porosity may or may not have arrived. Run the same send again to find out; it will not publish twice.'
    assert exit_code(unknown) == 5
    command = e._load()['pending']['command_id']
    project.key = 'key-2'; project.add('poro', V3, name='Porosity')        # same owner, rotated key? see test below; head moved meanwhile
    project.key = 'key-1'
    again = send(ex(project, tmp_path / 'w'))                             # a new process: the stored intent is replayed
    assert again.outcome == 'sent-version' and again.technical['command_id'] == command
    assert [c[1] for c in project.calls if c[0] == 'publish'] == [command, command]
    assert [v['revision'] for v in project.items['poro']['versions']].count(sha(V2)) == 1
    assert e.held()['poro']['revision'] == sha(V2) and e._load()['pending'] is None


def test_a_changed_intent_while_pending_is_not_valid(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.drop_after_commit = True; refused('outcome-unknown', lambda: send(e))
    for change in ({'how': 'other'}, {'name': 'Other'}, {'profile': 'table/2'}, {'extra': {'layer': 'mode'}}):
        caught = refused('not-valid', lambda: send(e, **change))
        assert caught.sentence == ('The project refused this: an earlier send from this folder is unfinished: run it again unchanged, '
                                   'or set it aside. Nothing was sent.')


def test_identical_bytes_with_different_intent_are_two_items(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    one = e.send(b'same', name='A', profile='table/1', how='one way', based_on=['poro'])
    two = e.send(b'same', name='B', profile='table/1', how='another way', based_on=['poro'])
    assert one.technical['asset_id'] != two.technical['asset_id'] and one.technical['command_id'] != two.technical['command_id']


def test_a_pending_send_is_bound_to_the_sender_and_abandoning_it_is_explicit(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.drop_after_commit = True; refused('outcome-unknown', lambda: send(e))
    project.key = 'key-of-someone-else'
    other = refused('outcome-unknown', lambda: send(e))
    assert other.sentence == ('An earlier send of Porosity was started with another access key and may or may not have arrived. '
                              'Run it again with that key to find out, or set it aside.')
    assert len([c for c in project.calls if c[0] == 'publish']) == 1          # nothing was sent under the other key
    aside = e.abandon_pending()
    assert (aside.outcome, aside.sentence) == ('abandoned', 'The unfinished send of Porosity was set aside. An item may already exist in the project; check before sending it again.')
    assert e._load()['pending'] is None


def test_a_refused_retry_keeps_the_unknown_send(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.drop_after_commit = True; refused('outcome-unknown', lambda: send(e))
    project.fail['publish'] = ERRORS['expired']()
    refused('sign-in-needed', lambda: send(e))                              # a revoked key cannot recover it
    assert e._load()['pending'] is not None


@pytest.mark.parametrize('error,code,exit', [('forbidden', 'access-refused', 3), ('large', 'too-large', 1), ('invalid', 'not-valid', 1),
                                             ('expired', 'sign-in-needed', 3), ('busy', 'rate-limited', 5)])
def test_send_refusals(project, tmp_path, error, code, exit):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.fail['publish'] = ERRORS[error]()
    caught = refused(code, lambda: send(e))
    assert exit_code(caught) == exit and 'send yours as a new item' not in caught.sentence
    if code == 'access-refused':
        assert caught.sentence == ('The project did not allow this with this access key, so nothing was sent. '
                                   "Check that the key is for this project and can write, or ask the item's author.")
    assert (e._load()['pending'] is None) == (code != 'rate-limited')


def test_a_local_oversize_file_is_too_large_with_no_call(project, tmp_path, monkeypatch):
    monkeypatch.setattr(exchange, 'MAX_SEND', 4)
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    assert refused('too-large', lambda: send(e, b'12345')).sentence == 'The file is larger than this project accepts. Nothing was sent.'
    assert not [c for c in project.calls if c[0] == 'publish']


# -- the record ---------------------------------------------------------------------------------------

def test_a_record_of_another_project_or_schema_is_refused_and_note_survives(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    record = json.loads((tmp_path / 'w/held.json').read_text())
    record['items']['poro']['note'] = {'layer': 'replace'}; (tmp_path / 'w/held.json').write_text(json.dumps(record))
    project.add('poro', V2, name='Porosity'); e.get('poro', output=tmp_path / 'o')
    assert e.held()['poro']['note'] == {'layer': 'replace'} and e.held()['poro']['revision'] == sha(V2)
    assert oct(os.stat(tmp_path / 'w/held.json').st_mode & 0o777) == '0o600'
    for change in ({'project': 'q'}, {'schema': 'ophiolite.held/0'}):
        (tmp_path / 'x').mkdir(exist_ok=True); (tmp_path / 'x/held.json').write_text(json.dumps({**record, **change}))
        refused('not-valid', ex(project, tmp_path / 'x').check)


def test_two_step_get_leaves_the_record_unchanged_until_confirmed(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    before = (tmp_path / 'w/held.json').read_bytes()
    project.add('poro', V2, name='Porosity')
    with e.fetch('poro') as receipt:
        assert receipt.content == V2  # the caller fails to apply it and never confirms
    assert (tmp_path / 'w/held.json').read_bytes() == before                # mutation: advance on fetch -> differs
    with pytest.raises(RuntimeError):
        with e.fetch('poro'):
            raise RuntimeError('the host could not display it')
    assert (tmp_path / 'w/held.json').read_bytes() == before
    receipt = e.fetch('poro'); assert receipt.confirm(applied_to='layer').outcome == 'got'
    assert e.held()['poro']['revision'] == sha(V2)


def test_a_failed_fetch_or_write_keeps_the_record(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    before = (tmp_path / 'w/held.json').read_bytes(); project.add('poro', V2, name='Porosity')
    project.fail['after-write'] = OSError('disk full')
    refused('could-not-reach', lambda: e.get('poro', output=tmp_path / 'o'))
    assert (tmp_path / 'w/held.json').read_bytes() == before and (tmp_path / 'o/data.bin').read_bytes() == V1
    assert not list(tmp_path.glob('.o.*'))


def test_a_description_only_read_is_never_got(project, tmp_path):
    project.fail['fetch'] = exchange.CannotReadHere('', {'reason': 'a seismic volume is described here, not received'})
    refused('cannot-read-here', lambda: ex(project, tmp_path / 'w').get('poro'))
    assert ex(project, tmp_path / 'w').held() == {}


# -- one program at a time (real processes) -------------------------------------------------------------

HOLDER = '''
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location('exchange_fake', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from ophiolite.exchange import Exchange
fake = m.Fake(); fake.add('poro', b'first program', name='Porosity'); fake.slow = float(sys.argv[4])
print('started', flush=True)
action = sys.argv[5]
if action == 'get': Exchange(fake, sys.argv[2]).get('poro', output=sys.argv[3])
else:
    Exchange(fake, sys.argv[2]).get('poro'); fake.slow = 0
    fake.slow = float(sys.argv[4]); Exchange(fake, sys.argv[2]).send(b'mine', name='Mine', profile='table/1', how='x', based_on=['poro'])
print('done', flush=True)
'''


def holder(tmp_path, seconds, action='get'):
    env = {**os.environ, 'PYTHONPATH': str(HERE.parent) + os.pathsep + os.environ.get('PYTHONPATH', '')}
    process = subprocess.Popen([sys.executable, '-c', HOLDER, str(HERE / 'helpers/exchange_fake.py'), str(tmp_path / 'w'), str(tmp_path / 'out'), str(seconds), action],
                               stdout=subprocess.PIPE, text=True, env=env)
    assert process.stdout.readline().strip() == 'started'
    import time
    deadline = time.monotonic() + 10
    while not (tmp_path / 'w/held.lock').exists() and time.monotonic() < deadline: time.sleep(0.02)
    time.sleep(0.3)
    return process


def test_a_second_program_gets_folder_busy_and_overwrites_nothing(project, tmp_path):
    first = holder(tmp_path, 4)
    try:
        project.items['poro']['versions'][0]['data'] = b'second program'
        busy = refused('folder-busy', lambda: Exchange(project, tmp_path / 'w', lock_timeout=0.5).get('poro', output=tmp_path / 'out'))
        assert busy.sentence == 'Another program is using this folder. Wait for it to finish, then run this again.' and exit_code(busy) == 5
        refused('folder-busy', lambda: Exchange(project, tmp_path / 'w', lock_timeout=0.5).send(b'x', name='X', profile='t/1', how='x', based_on=['poro']))
        during = Exchange(project, tmp_path / 'w').check()                 # check reads without the lock
        assert during.outcome in ('nothing-new', 'updates')
        assert first.wait(30) == 0
    finally: first.kill()
    assert (tmp_path / 'out/data.bin').read_bytes() == b'first program'      # mutation: remove the lock -> the second get overwrites


def test_the_lock_is_released_when_its_program_is_killed(project, tmp_path):
    first = holder(tmp_path, 30)
    first.send_signal(signal.SIGKILL); first.wait(10)
    assert Exchange(project, tmp_path / 'w', lock_timeout=0.5).get('poro').outcome == 'got'


def test_a_crash_after_replacing_the_output_before_confirm_fetches_again(project, tmp_path):
    e = ex(project, tmp_path / 'w'); e.get('poro', output=tmp_path / 'o')
    project.add('poro', V2, name='Porosity')
    receipt = e.fetch('poro', output=tmp_path / 'o'); receipt.release()      # the program dies before confirming
    assert e.held()['poro']['revision'] == sha(V1)
    assert e.get('poro', output=tmp_path / 'o').outcome == 'got'


# -- words --------------------------------------------------------------------------------------------

def test_no_identifier_or_engineering_word_is_rendered(tmp_path):
    fake = Fake()
    fake.add('a' * 64, V1, name='Porosity', by='usr_8f3a91c2d4')
    fake.add('poro', V1 + b'x', name='Gamma', by='0f4c2b8e-1d2a-4c3b-9e8f-7a6b5c4d3e2f')
    e = ex(fake, tmp_path / 'w'); e.check(); e.get('a' * 64); e.get('poro')
    fake.add('a' * 64, V2, name='Porosity', by='oph_key_3f9e'); fake.add('poro', V3, name='Gamma', by='exchange-consumer/1')
    fake.add('n', b'n', name=None, kind='external-scalar-map')
    texts = [e.check().sentence]
    message = 'revision-conflict usr_8f3a91c2d4 ' + 'b' * 64 + ' exchange-consumer/1 derived'
    fake.fail['publish'] = fake_module.IntegrityConflict(message, status=409, code='revision-conflict')
    for call in (lambda: send(e), lambda: send(e, of=None, based_on=['poro'])):
        try: call()
        except exchange.ExchangeRefused as refusal:
            texts.append(refusal.sentence); assert 'usr_8f3a91c2d4' in json.dumps(refusal.technical)  # raw text only in technical
    for code, sentence in exchange.SENTENCES.items():
        texts.append(sentence({'name': 'X', 'number': 2, 'who': 'someone', 'when': 'just now', 'folder': 'f', 'reason': 'r', 'reasons': 'r',
                               'newer': [], 'new': [], 'lost': [{'name': 'X'}], 'visible': 1}))
    assert len(texts) > 20 and not [t for t in texts if IDENT.search(t)], [t for t in texts if IDENT.search(t)]
    assert 'someone' in texts[0] and 'an item' in texts[0]


def test_a_host_sentence_table_replaces_every_sentence(project, tmp_path):
    table = {code: (lambda code: lambda facts: 'HOST:' + code)(code) for code in exchange.OUTCOMES}
    e = ex(project, tmp_path / 'w', sentences=table)
    assert e.check().sentence == 'HOST:nothing-new' and e.get('poro').sentence == 'HOST:got'
    project.fail['inventory'] = ERRORS['down']()
    assert str(refused('could-not-reach', e.check)) == 'HOST:could-not-reach'
    with pytest.raises(ValueError, match='no sentence for: folder-busy'):
        Exchange(project, tmp_path / 'w', sentences={k: v for k, v in table.items() if k != 'folder-busy'})


def test_outcomes_are_the_closed_list():
    assert set(exchange.OUTCOMES) == {'nothing-new', 'updates', 'access-changed', 'got', 'already-latest', 'not-visible', 'cannot-read-here', 'damaged',
                                      'map-unavailable', 'sent-new', 'sent-version', 'newer-version-exists', 'nothing-changed', 'access-refused', 'not-valid',
                                      'not-held', 'too-large', 'outcome-unknown', 'abandoned', 'folder-busy', 'rate-limited', 'sign-in-needed', 'could-not-reach'}
    assert isinstance(Outcome('got', 's'), Outcome)
