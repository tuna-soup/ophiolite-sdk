"""E173 s0: the held record names how an item was named and whether it stays (`ophiolite.held/2`), against the in-memory
project of tests/helpers/exchange_fake.py. No public call sets `words` or `mode` in slice 0, so the tests set them by
editing the saved record. Each test names the mutation it catches."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import Exchange

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha
NOW = 1300.0
WORDS = {'name': 'Top Rotliegend', 'type': 'horizon'}
NAMED = {'words': WORDS, 'mode': 'stays'}
CANNOT_READ = 'The project refused this: this folder holds a record this version cannot read. Nothing was sent.'


def ex(fake, work): return Exchange(fake, work, clock=lambda: NOW)


def record(work): return json.loads((work / 'held.json').read_text())


KEEP = object()


def edit(work, schema=KEEP, **fields):
    """Set fields on held entries in the saved file, as a later slice's call would have; the schema only when named
    (None removes it)."""
    held = record(work)
    for ident, values in fields.items(): held['items'][ident].update(values)
    if schema is None: del held['schema']
    elif schema is not KEEP: held['schema'] = schema
    (work / 'held.json').write_text(json.dumps(held, indent=1, sort_keys=True))


def project():
    fake = Fake(); fake.add('poro', b'porosity v1', name='Porosity'); fake.add('map', b'grid v1', name='Top Chalk map')
    return fake


def fetches(fake): return [c for c in fake.calls if c[0] == 'fetch']


# -- a folder used by id is written exactly as before -------------------------------------------------------------------

def test_a_folder_used_by_id_round_trips_byte_for_byte_through_get_check_and_send(tmp_path):
    """Mutation: /2 written always, or `words`/`mode` written (as null) on a plain entry -> the literal bytes differ."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)

    def expect(seen, entry):
        held = record(work)
        value = {'schema': 'ophiolite.held/1', 'url': 'https://project.example', 'project': 'p', 'holder_id': held['holder_id'],
                 'items': {'poro': entry}, 'seen': seen, 'pending': None}
        assert (work / 'held.json').read_bytes() == json.dumps(value, indent=1, sort_keys=True).encode()

    assert e.get('poro').outcome == 'got'
    got = {'asset_id': 'poro', 'name': 'Porosity', 'kind': 'derived', 'revision': sha(b'porosity v1'), 'number': 1, 'output': None, 'got_at': NOW, 'note': None}
    expect(None, got)
    assert e.check().outcome == 'nothing-new'
    expect(['map', 'poro'], got)
    assert e.send(b'porosity mine', name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro').outcome == 'sent-version'
    expect(['map', 'poro'], {'asset_id': 'poro', 'name': 'Porosity', 'kind': 'derived', 'revision': sha(b'porosity mine'), 'number': 2,
                             'got_at': NOW, 'sent': True, 'output': None, 'note': None})


# -- /2 once an entry carries words or a mode, and never back ------------------------------------------------------------

@pytest.mark.parametrize('fields', [{'words': WORDS}, {'mode': 'stays'}, {'mode': 'follows'}], ids=['words', 'mode-stays', 'mode-follows'])
def test_words_alone_or_a_mode_alone_promotes_the_record_to_held_2(tmp_path, fields):
    """Mutation: promotion reads only `words` (or only `mode`) -> that case is written as /1, which an older SDK accepts."""
    fake, work = project(), tmp_path / 'w'
    ex(fake, work).get('poro')
    edit(work, poro=fields)
    assert record(work)['schema'] == 'ophiolite.held/1'
    ex(fake, work).check()  # the production writer saves the record
    held = record(work)
    assert held['schema'] == exchange.SCHEMA_WORDS == 'ophiolite.held/2'
    assert {k: held['items']['poro'][k] for k in fields} == fields


def test_a_folder_with_one_plain_and_one_named_item_stays_held_2_and_the_plain_item_gains_nothing(tmp_path):
    """Mutation: `_kept` adds `words`/`mode` (as null) to every entry -> the plain item carries them."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro'); e.get('map')
    edit(work, poro=NAMED)
    fake.add('map', b'grid v2', name='Top Chalk map')
    assert e.get('map').outcome == 'got'
    held = record(work)
    assert held['schema'] == 'ophiolite.held/2'
    assert {k: held['items']['poro'][k] for k in NAMED} == NAMED
    assert set(held['items']['map']) == {'asset_id', 'name', 'kind', 'revision', 'number', 'output', 'got_at', 'note'}
    assert held['items']['map']['revision'] == sha(b'grid v2')


def test_a_held_2_folder_never_goes_back_to_held_1(tmp_path):
    """Mutation: `_save` writes /1 when no entry carries words or a mode -> a /2 folder is written back as /1."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro')
    edit(work, schema='ophiolite.held/2')
    fake.add('poro', b'porosity v2', name='Porosity')
    assert e.get('poro').outcome == 'got'
    assert record(work)['schema'] == 'ophiolite.held/2'
    e.check()
    assert record(work)['schema'] == 'ophiolite.held/2'


# -- the three sites that replace an entry keep the words and the mode ---------------------------------------------------

def test_a_plain_get_of_a_named_staying_item_stays_without_fetching_and_keeps_its_words_and_mode(tmp_path):
    """E173 s1 (F1): the folder recorded that it stays, so a plain get now stays on the held version, confirmed again
    with no fetch (slice 0 expected the new head here). Mutation: `_kept` dropped at Receipt.confirm -> the confirmed
    entry has no words."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro', output=tmp_path / 'out')
    edit(work, poro=NAMED)
    fake.add('poro', b'porosity v2', name='Porosity')  # the head moves first, so the get cannot stop at already-latest
    before = len(fetches(fake))
    done = e.get('poro', output=tmp_path / 'out')
    assert done.outcome == 'stays' and len(fetches(fake)) == before
    held = record(work)
    entry = held['items']['poro']
    assert (held['schema'], entry['revision'], entry['number']) == ('ophiolite.held/2', sha(b'porosity v1'), 1)
    assert {k: entry[k] for k in NAMED} == NAMED


def test_a_send_of_a_new_version_of_a_named_item_keeps_its_words_and_its_mode(tmp_path):
    """Mutation: `_kept` dropped at send -> the sent entry has no words and no mode (a send is not taking a version)."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro')
    edit(work, poro=NAMED)
    assert e.send(b'porosity mine', name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro').outcome == 'sent-version'
    held = record(work)
    entry = held['items']['poro']
    assert (held['schema'], entry['revision'], entry['sent']) == ('ophiolite.held/2', sha(b'porosity mine'), True)
    assert {k: entry[k] for k in NAMED} == NAMED


def test_a_replayed_send_keeps_the_words_and_the_mode(tmp_path):
    """The outcome-unknown path, then the same send again (the project replays the recorded command).
    Mutation: `_kept` dropped at send -> the replayed entry has no words and no mode."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro')
    edit(work, poro=NAMED)
    fake.drop_after_commit = True
    send = dict(name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro')
    with pytest.raises(exchange.OutcomeUnknown): e.send(b'porosity mine', **send)
    assert record(work)['pending'] is not None and {k: record(work)['items']['poro'][k] for k in NAMED} == NAMED
    assert e.send(b'porosity mine', **send).outcome == 'sent-version'
    held = record(work)
    assert held['pending'] is None and held['items']['poro']['revision'] == sha(b'porosity mine')
    assert {k: held['items']['poro'][k] for k in NAMED} == NAMED and held['schema'] == 'ophiolite.held/2'


def test_an_agents_send_run_keeps_the_words_and_the_mode(tmp_path):
    """The agent's send_run against test_agent_exchange_send.py's gateway. Mutation: `_kept` dropped at
    AgentExchange._landed -> the landed entry has no words and no mode."""
    from test_agent_exchange_send import PREV, RAW, Gateway, agent, run_folder, work
    gateway, run, folder = Gateway(), run_folder(tmp_path), work(tmp_path)
    edit(folder, schema='ophiolite.held/2', **{'a-prev': NAMED})
    done = agent(gateway).exchange(folder).send_run(run, name='Shifted tops', of='a-prev', expected=PREV)
    assert done.outcome == 'sent-run'
    held = record(folder)
    entry = held['items']['a-prev']
    assert (held['schema'], entry['revision'], entry['number']) == ('ophiolite.held/2', sha(RAW['shifted']), 3)
    assert {k: entry[k] for k in NAMED} == NAMED


def test_check_keeps_the_words_and_the_mode(tmp_path):
    """Mutation: check's `_remember` rebuilds entries -> the named entry loses its fields."""
    fake, work = project(), tmp_path / 'w'
    e = ex(fake, work)
    e.get('poro')
    edit(work, schema='ophiolite.held/2', poro=NAMED)
    fake.add('poro', b'porosity v2', name='Porosity')
    assert e.check().outcome == 'updates'
    held = record(work)
    assert held['schema'] == 'ophiolite.held/2' and held['seen'] == ['map', 'poro']
    assert {k: held['items']['poro'][k] for k in NAMED} == NAMED and held['items']['poro']['revision'] == sha(b'porosity v1')


# -- any other schema is refused with today's sentence and nothing is written --------------------------------------------

@pytest.mark.parametrize('schema', ['ophiolite.held/0', None, 'ophiolite.held'], ids=['held-0', 'no-schema', 'no-version'])
def test_any_other_schema_is_refused_with_todays_sentence_and_nothing_is_written(tmp_path, schema):
    """Mutation: `_load` accepts any `ophiolite.held/*` (or any schema) -> the folder is read and rewritten."""
    fake, work = project(), tmp_path / 'w'
    ex(fake, work).get('poro')
    edit(work, schema=schema, poro=NAMED)
    before, seen = (work / 'held.json').read_bytes(), len(fake.calls)
    e = ex(fake, work)
    calls = [lambda: e.held(), e.check, lambda: e.get('poro'),
             lambda: e.send(b'porosity mine', name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'], of='poro')]
    for call in calls:
        with pytest.raises(exchange.NotValid) as caught: call()
        assert str(caught.value) == CANNOT_READ
    assert (work / 'held.json').read_bytes() == before and not [c for c in fake.calls[seen:] if c[0] in ('fetch', 'publish')]


# -- C2: the three outcomes' sentences, frozen (D2) ------------------------------------------------------------------------
# Q3 is open: no frozen sentence names the "point set" type word; a case that would uses another word.

IDENT = re.compile(r'[0-9a-f]{32,}|oph_|usr_|[0-9a-f]{8}-[0-9a-f]{4}-|exchange-consumer/1|derived|uploaded|external-scalar-map|revision-conflict', re.I)  # test_exchange_core's
TR = 'Top Rotliegend'
ADA, BEN = {'type': 'horizon', 'who': 'Ada', 'number': 2}, {'type': 'well log', 'who': 'Ben', 'number': 1}
TAIL = '; get it with stay=False to take it.'
SDK_CASES = [
    ('stays', {'name': TR, 'number': 3, 'newer': True, 'newer_number': 5}, 'You stay on version 3 of Top Rotliegend. Version 5 is newer' + TAIL),
    ('stays', {'name': TR, 'number': None, 'newer': True, 'newer_number': 5}, 'You stay on the version of Top Rotliegend you hold. Version 5 is newer' + TAIL),
    ('stays', {'name': TR, 'number': 3, 'newer': True, 'newer_number': None}, 'You stay on version 3 of Top Rotliegend. A newer version exists' + TAIL),
    ('stays', {'name': TR, 'number': None, 'newer': True, 'newer_number': None}, 'You stay on the version of Top Rotliegend you hold. A newer version exists' + TAIL),
    ('stays', {'name': TR, 'number': 3, 'newer': False, 'newer_number': None}, 'You stay on version 3 of Top Rotliegend, the latest.'),
    ('stays', {'name': TR, 'number': None, 'newer': False, 'newer_number': None}, 'You stay on the version of Top Rotliegend you hold, the latest.'),
    ('name-unclear', {'name': TR, 'candidates': [ADA, BEN]},
     'More than one item you can see is called Top Rotliegend: a horizon by Ada (version 2) and a well log by Ben (version 1). Name the type as well.'),
    ('name-unclear', {'name': TR, 'candidates': [ADA, {'type': 'horizon', 'who': None, 'number': 1}, {'type': None, 'who': 'Ben', 'number': None}]},
     'More than one item you can see is called Top Rotliegend: a horizon by Ada (version 2), a horizon (version 1) and an item by Ben. Name the type as well.'),
    ('name-unclear', {'name': TR, 'candidates': [{'type': 'OSDU record', 'who': None, 'number': None}, {'type': None, 'who': None, 'number': 4}]},
     'More than one item you can see is called Top Rotliegend: an OSDU record and an item (version 4). Name the type as well.'),
    ('name-not-found', {'name': TR, 'type': 'horizon'}, 'No item you can see is called Top Rotliegend (horizon). Nothing was changed.'),
    ('name-not-found', {'name': 'Base Zechstein', 'type': None}, 'No item you can see is called Base Zechstein. Nothing was changed.'),
]


@pytest.mark.parametrize('code, facts, sentence', SDK_CASES, ids=['%s-%d' % (c[0], n) for n, c in enumerate(SDK_CASES)])
def test_the_sdk_sentences_of_the_three_outcomes(code, facts, sentence):
    """Mutation: "the latest" read from a missing number -> the number-unknown cases say "the latest"; a guessed author
    or type -> the missing-part cases differ."""
    said = exchange.SENTENCES[code](facts)
    assert said == sentence
    assert not IDENT.search(said) and 'point set' not in said and 'None' not in said


def test_the_refusal_classes_keep_their_category_and_their_own_code():
    """Mutation: NameNotFound given its category's code (not-found) -> the code differs."""
    assert issubclass(exchange.NameUnclear, exchange.Refused) and issubclass(exchange.NameNotFound, exchange.Unavailable)
    assert (exchange.NameUnclear.code, exchange.NameNotFound.code) == ('name-unclear', 'name-not-found')
    for code in ('name-unclear', 'name-not-found'):
        error = exchange.REFUSALS[code]('s', {}, {'candidates': ['tr-grid']})
        assert (error.outcome, error.code, str(error)) == (code, code, 's')
    assert 'stays' in exchange.OUTCOMES and 'stays' not in exchange.REFUSALS  # a success


def test_the_fixture_project_for_names():
    """D4: the fixture slice 1's acceptance runs against, in the shape s0b serves (`by` an id, `by_name` its label)."""
    fake = fake_module.names_project()
    listed = fake.inventory()
    called = [i for i in listed if i['name'] == TR]
    candidates = [{'type': exchange.type_word(i['profile']), 'who': i['by_name'], 'number': len(fake.history(i))} for i in called]
    assert candidates == [{'type': 'horizon', 'who': 'Ada', 'number': 2}, {'type': 'point set', 'who': 'Ben', 'number': 1}]
    assert [i['name'] for i in listed if i['name'] != TR] == ['Base Zechstein']
    assert {i['asset_id']: i['profile'] for i in listed} == {'bz-grid': 'zmap-plus-grid/1', 'tr-grid': 'esri-ascii-grid/1', 'tr-points': 'points-csv/1'}
    shown = [dict(c, type='well log') if c['type'] == 'point set' else c for c in candidates]  # Q3 open: another word in the sentence
    assert exchange.SENTENCES['name-unclear']({'name': TR, 'candidates': shown}) == (
        'More than one item you can see is called Top Rotliegend: a horizon by Ada (version 2) and a well log by Ben (version 1). Name the type as well.')
    assert exchange.SENTENCES['name-not-found']({'name': TR, 'type': 'seismic volume'}) == (
        'No item you can see is called Top Rotliegend (seismic volume). Nothing was changed.')
    plain = Fake(); plain.add('x', b'x', name='X')
    assert set(plain.inventory()[0]) == {'asset_id', 'kind', 'authority', 'revision', 'name'}  # an item without a profile lists as before
