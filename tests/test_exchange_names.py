"""E173 s1 C1: get, fetch and check take an item by its name and type word, resolved once; the folder records the words
(`ophiolite.held/2`). Against names_project() of tests/helpers/exchange_fake.py, in the shape E173 s0b serves. Each test
names the mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import Exchange, Receipt

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha, names_project = fake_module.Fake, fake_module.sha, fake_module.names_project
NOW = 1300.0
TR, BZ = 'Top Rotliegend', 'Base Zechstein'
HORIZON = {'name': TR, 'type': 'horizon'}
GONE = 'You can no longer see Top Rotliegend. It may have been removed or no longer shared with you.'


def ex(fake, work): return Exchange(fake, work, clock=lambda: NOW)


def record(work): return json.loads((work / 'held.json').read_text())


def fetches(fake): return [c for c in fake.calls if c[0] == 'fetch']


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code
    return caught.value


# -- acceptance 1: by name is the item by id ---------------------------------------------------------------------------

def test_a_unique_name_gets_the_same_bytes_as_its_id_and_records_the_words(tmp_path):
    """Mutation: confirm does not write the receipt's words -> the entry has none."""
    fake = names_project()
    by_name = ex(fake, tmp_path / 'w').get(name=BZ, output=tmp_path / 'named')
    by_id = ex(fake, tmp_path / 'v').get('bz-grid', output=tmp_path / 'plain')
    assert by_name.outcome == by_id.outcome == 'got'
    assert (tmp_path / 'named/data.bin').read_bytes() == b'zmap v1' == (tmp_path / 'plain/data.bin').read_bytes()  # the literal, not only equal
    assert (by_name.technical['asset_id'], by_name.technical['revision']) == ('bz-grid', sha(b'zmap v1'))
    assert by_name.sentence == 'Got Base Zechstein, version 1 by Ada, 5 minutes ago. You now hold it; saved in %s.' % (tmp_path / 'named')
    held = record(tmp_path / 'w')
    assert held['schema'] == 'ophiolite.held/2' and held['items']['bz-grid']['words'] == {'name': BZ}
    assert 'mode' not in held['items']['bz-grid']
    plain = record(tmp_path / 'v')  # a folder used by id is written as before
    assert plain['schema'] == 'ophiolite.held/1' and 'words' not in plain['items']['bz-grid']


# -- acceptance 2: a shared name refuses with the candidates, writing nothing --------------------------------------------

def test_a_shared_name_refuses_with_both_candidates_and_writes_nothing(tmp_path):
    """Mutation: the `len(called) > 1` check removed -> the first item is fetched."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('bz-grid')
    before, fetched = (work / 'held.json').read_bytes(), len(fetches(fake))
    error = refused('name-unclear', lambda: e.get(name=TR, output=tmp_path / 'out'))
    assert str(error) == ('More than one item you can see is called Top Rotliegend: a horizon by Ada (version 2) and a point set by Ben '
                          '(version 1). Name the type as well.')
    assert error.technical == {'candidates': ['tr-grid', 'tr-points']}  # ids only here
    assert 'tr-grid' not in json.dumps(error.facts) and isinstance(error, exchange.Refused)
    assert (work / 'held.json').read_bytes() == before and len(fetches(fake)) == fetched and not (tmp_path / 'out').exists()


def test_a_candidate_with_an_identifier_for_an_author_and_a_name_like_an_identifier_are_never_shown(tmp_path):
    """F11. Mutation: `who` taken from by_name without display() -> the identifier is in the sentence."""
    fake = Fake()
    fake.add('a', b'a', name='usr_7f3a9c21b', by='usr_7f3a9c21b', profile='esri-ascii-grid/1', owner='u1')
    fake.add('b', b'b', name='usr_7f3a9c21b', by='Ben', profile='points-csv/1', owner='ben')
    e = ex(fake, tmp_path / 'w')
    error = refused('name-unclear', lambda: e.get(name='usr_7f3a9c21b'))
    assert str(error) == 'More than one item you can see is called that name: a horizon (version 1) and a point set by Ben (version 1). Name the type as well.'
    assert str(refused('name-not-found', lambda: e.get(name='usr_0000000000'))) == 'No item you can see is called that name. Nothing was changed.'
    assert e.get(name='usr_7f3a9c21b', type='point set').technical['asset_id'] == 'b'  # matching on the raw name


# -- the type word ---------------------------------------------------------------------------------------------------------

def test_a_type_word_picks_one_and_a_point_set_marked_as_a_horizon_is_a_horizon(tmp_path):
    """Mutation: the `represents` branch of _item_type removed -> the marked point set is not found as a horizon."""
    fake = names_project()
    e = ex(fake, tmp_path / 'w')
    got = e.get(name=TR, type='horizon', output=tmp_path / 'top')
    assert (got.technical['asset_id'], (tmp_path / 'top/data.bin').read_bytes()) == ('tr-grid', b'grid v2')
    assert record(tmp_path / 'w')['items']['tr-grid']['words'] == HORIZON
    fake.add('picked', b'x,y,z\n4,5,6\n', name='Picked top', by='Cy', profile='points-csv/1', owner='cy', represents='horizon')
    fake.add('plain', b'x,y,z\n7,8,9\n', name='Picked base', by='Cy', profile='points-csv/1', owner='cy')
    assert e.get(name='Picked top', type='horizon').technical['asset_id'] == 'picked'
    assert str(refused('name-not-found', lambda: e.get(name='Picked base', type='horizon'))) == (
        'No item you can see is called Picked base (horizon). Nothing was changed.')
    assert e.get(name='Picked base', type='point set').technical['asset_id'] == 'plain'


def test_an_item_without_a_profile_is_found_by_name_alone_and_never_with_a_type(tmp_path):
    fake = names_project(); fake.add('native', b'n', name='Well A', kind='native')
    e = ex(fake, tmp_path / 'w')
    for word in exchange.TYPE_WORDS: refused('name-not-found', lambda: e.get(name='Well A', type=word))
    assert e.get(name='Well A').technical['asset_id'] == 'native'


@pytest.mark.parametrize('call, reason', [
    (lambda e: e.get('bz-grid', name=BZ), 'name the item by its id or by its name, one of the two'),
    (lambda e: e.get(), 'name the item by its id or by its name, one of the two'),
    (lambda e: e.fetch(), 'name the item by its id or by its name, one of the two'),
    (lambda e: e.get('bz-grid', type='horizon'), 'a type is given only together with a name'),
    (lambda e: e.check(type='horizon'), 'a type is given only together with a name'),
    (lambda e: e.get(name=''), 'a name is the text an item is called'),
    (lambda e: e.get(name=BZ, type='grid'), 'grid is not a type this version knows'),
], ids=['both', 'neither', 'fetch-neither', 'type-with-id', 'check-type-alone', 'empty-name', 'unknown-type'])
def test_the_arguments_are_refused_before_anything_is_asked(tmp_path, call, reason):
    fake, work = names_project(), tmp_path / 'w'
    error = refused('not-valid', lambda: call(ex(fake, work)))
    assert str(error) == 'The project refused this: %s. Nothing was sent.' % reason
    assert fake.calls == [] and not work.exists()


def test_the_new_keywords_never_reach_the_transport_selection(tmp_path):
    """D1: `name` and `type` are keyword-only, so neither falls into **how (the stored selection)."""
    fake, work = names_project(), tmp_path / 'w'
    ex(fake, work).get(name=BZ, type='horizon', output=tmp_path / 'out', curves=['GR'])
    assert record(work)['items']['bz-grid']['output']['selection'] == {'curves': ['GR']}
    assert (tmp_path / 'out/data.bin').read_bytes() == b'zmap v1|GR'


# -- acceptance 3: a rename; and the record is never re-bound --------------------------------------------------------------

def test_a_renamed_item_is_still_got_by_the_recorded_words_and_the_sentence_names_it_now(tmp_path):
    """Mutation: _resolve skips the record -> the renamed grid is not found as a horizon called Top Rotliegend."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get(name=TR, type='horizon', output=tmp_path / 'top')
    fake.items['tr-grid']['name'] = 'Top Rotliegend (final)'
    fake.add('tr-grid', b'grid v3', name='Top Rotliegend (final)', by='Ada', at=1200.0, owner='ada')
    got = e.get(name=TR, type='horizon', output=tmp_path / 'top')
    assert got.technical['asset_id'] == 'tr-grid' and (tmp_path / 'top/data.bin').read_bytes() == b'grid v3'
    assert got.sentence.startswith('Got Top Rotliegend (final), version 3 by Ada, 1 minute ago.')
    entry = record(work)['items']['tr-grid']
    assert (entry['name'], entry['words']) == ('Top Rotliegend (final)', HORIZON)


def test_a_recorded_item_that_has_gone_is_refused_by_name_as_by_id_even_when_another_item_now_has_its_name(tmp_path):
    """Acceptance 5 and F10 (no re-binding). Mutation: a gone record falls through to the inventory -> the newcomer is got."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get(name=TR, type='horizon', output=tmp_path / 'top')
    fake.hidden.add('tr-grid')
    fake.add('tr-new', b'another grid', name=TR, by='Dee', profile='esri-ascii-grid/1', owner='dee')
    before, fetched = (work / 'held.json').read_bytes(), len(fetches(fake))
    by_name = refused('not-visible', lambda: e.get(name=TR, type='horizon', output=tmp_path / 'top'))
    by_id = refused('not-visible', lambda: e.get('tr-grid', output=tmp_path / 'top'))
    assert str(by_name) == str(by_id) == GONE and by_name.technical == by_id.technical == {'asset_id': 'tr-grid'}
    assert (work / 'held.json').read_bytes() == before and len(fetches(fake)) == fetched
    assert (tmp_path / 'top/data.bin').read_bytes() == b'grid v2'


# -- F5: an answer without a fetch still records the words ---------------------------------------------------------------

def test_a_call_by_name_at_the_held_version_records_the_words_without_fetching_and_a_restart_reads_them(tmp_path):
    """Mutation: `_remember_entry` not called on already-latest -> the folder never learns the name."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    ex(fake, work).get('tr-grid', output=out)
    fetched = len(fetches(fake))
    done = ex(fake, work).get(name=TR, type='horizon', output=out)
    assert done.outcome == 'already-latest' and len(fetches(fake)) == fetched
    assert record(work)['items']['tr-grid']['words'] == HORIZON and record(work)['schema'] == 'ophiolite.held/2'
    fake.items['tr-grid']['name'] = 'Renamed'
    again = ex(fake, work).get(name=TR, type='horizon', output=out)  # a new process: the record, not the inventory
    assert (again.outcome, again.sentence) == ('already-latest', 'You already hold the latest version of Renamed, saved in %s.' % out)
    assert len(fetches(fake)) == fetched


def test_words_are_those_last_used_by_name_and_a_call_by_id_keeps_them(tmp_path):
    """D3. Mutation: a call by id writes its (absent) words -> the recorded words are lost."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'z'
    e = ex(fake, work)
    e.get(name=BZ, type='horizon', output=out)
    e.get(name=BZ, output=out)
    assert record(work)['items']['bz-grid']['words'] == {'name': BZ}
    fake.add('bz-grid', b'zmap v2', name=BZ, by='Ada', owner='ada')
    assert e.get('bz-grid', output=out).outcome == 'got'
    assert record(work)['items']['bz-grid']['words'] == {'name': BZ}
    assert e.get('bz-grid', output=out).outcome == 'already-latest'
    assert record(work)['items']['bz-grid']['words'] == {'name': BZ}


# -- the two-step fetch connectors use --------------------------------------------------------------------------------------

def test_fetch_by_name_released_records_nothing_and_confirmed_records_the_words_and_the_selection(tmp_path):
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'z'
    e = ex(fake, work)
    receipt = e.fetch(name=BZ, output=out, curves=['GR'])
    assert isinstance(receipt, Receipt) and receipt.content == b'zmap v1'
    receipt.release()
    assert not (work / 'held.json').exists()
    receipt = e.fetch(name=BZ, type='horizon', output=out, curves=['GR'])
    assert receipt.confirm(applied_to=out).outcome == 'got'
    entry = record(work)['items']['bz-grid']
    assert (entry['words'], entry['output']['selection'], entry['revision']) == ({'name': BZ, 'type': 'horizon'}, {'curves': ['GR']}, sha(b'zmap v1'))
    assert fetches(fake) == [('fetch', 'bz-grid', sha(b'zmap v1'))] * 2
    with e.fetch('tr-grid') as plain: pass  # by id, positional, as every connector calls it
    assert plain.content == b'grid v2' and 'tr-grid' not in record(work)['items']


# -- check by name (D5, F7) ---------------------------------------------------------------------------------------------------

def test_a_check_by_name_answers_for_that_item_only_and_leaves_the_seen_list_alone(tmp_path):
    """Mutation: a check by name writes the seen list -> the later full check misses what is new."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get(name=TR, type='horizon'); e.get('bz-grid')
    assert e.check().facts['baseline'] is True
    seen = record(work)['seen']
    fake.add('tr-grid', b'grid v3', name=TR, by='Ada', at=1200.0, owner='ada')
    fake.add('bz-grid', b'zmap v2', name=BZ, by='Ada', at=1200.0, owner='ada')
    fake.add('fresh', b'f', name='Fresh', profile='las2/1', owner='eve')
    named = e.check(name=TR, type='horizon')
    assert named.outcome == 'updates' and [n['asset_id'] for n in named.facts['newer']] == ['tr-grid'] and named.facts['new'] == []
    assert named.sentence == '1 newer: Top Rotliegend, version 3 by Ada, 1 minute ago.'
    assert record(work)['seen'] == seen
    whole = e.check()
    assert [n['asset_id'] for n in whole.facts['newer']] == ['bz-grid', 'tr-grid'] and [n['asset_id'] for n in whole.facts['new']] == ['fresh']
    assert e.check(name='Fresh').facts['new'] == []  # already noted by the full check
    entry = record(work)['items']['tr-grid']
    assert entry['words'] == HORIZON and entry['revision'] == sha(b'grid v2')  # check never takes a version


def test_a_check_by_name_before_any_full_check_notes_nothing_and_a_name_held_nowhere_holds_nothing(tmp_path):
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('bz-grid')
    named = e.check(name=BZ)
    assert (named.outcome, named.facts['baseline'], named.facts['visible']) == ('nothing-new', False, 1)
    assert named.sentence == 'Nothing is newer than what you hold.' and record(work)['seen'] is None
    other = e.check(name=TR, type='point set')
    assert (other.outcome, other.sentence) == ('nothing-new', 'You hold nothing yet.')
    refused('name-unclear', lambda: e.check(name=TR))


def test_a_check_by_name_of_a_held_item_that_has_gone_is_access_changed_not_a_refusal(tmp_path):
    """F7. Mutation: _resolve refuses a gone recorded id -> the named check raises not-visible."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get(name=TR, type='horizon'); e.get('bz-grid')
    fake.hidden.add('tr-grid')
    fake.add('tr-new', b'another grid', name=TR, by='Dee', profile='esri-ascii-grid/1', owner='dee')
    named = e.check(name=TR, type='horizon')
    assert (named.outcome, named.sentence) == ('access-changed', 'You can no longer see 1 item you hold: Top Rotliegend. '
                                                                   'They may have been removed or no longer shared with you.')
    assert [n['asset_id'] for n in named.facts['lost']] == ['tr-grid'] and record(work)['items']['tr-grid']['words'] == HORIZON
