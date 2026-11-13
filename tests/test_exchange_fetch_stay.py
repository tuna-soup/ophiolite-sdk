"""E172 s3 G-7 (R-M7): the two-step fetch takes `stay` as get does, through the same core step. stay=True without an
output (a host that keeps its own copy) answers a receipt over the HELD version, whose content is that exact version and
whose confirm says `stays`; stay=False takes the latest and follows; without stay, fetch is as before (test_exchange_stay).
Against names_project() of tests/helpers/exchange_fake.py; fetches are counted at the fake transport. Each test names the
mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import Exchange

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha, names_project = fake_module.Fake, fake_module.sha, fake_module.names_project
NOW = 1300.0
TR = 'Top Rotliegend'
STAYS = 'You stay on version 2 of Top Rotliegend. Version 3 is newer; get it with stay=False to take it.'


class Reporting(Fake):
    """The names project with E70b's `report`, every call recorded."""
    def __init__(self):
        super().__init__(); self.reports = []
        for ident, item in names_project().items.items(): self.items[ident] = item

    def report(self, reference, holder_id, event_id, **held):
        self.reports.append({'reference': reference, 'event_id': event_id, **held})


def ex(fake, work): return Exchange(fake, work, clock=lambda: NOW)


def record(work): return json.loads((work / 'held.json').read_text())


def fetches(fake): return [c for c in fake.calls if c[0] == 'fetch']


def newer(fake, data=b'grid v3'): return fake.add('tr-grid', data, name=TR, by='Ada', at=1200.0, owner='ada')


def test_fetch_stay_true_without_output_answers_the_held_version_never_the_head(tmp_path):
    """Mutation: _stay pulls the head for a host-kept copy -> the content is grid v3 and the fake is asked for it."""
    fake, work = Reporting(), tmp_path / 'w'
    e = ex(fake, work)
    first = e.fetch('tr-grid', stay=True)
    assert (first.outcome, first.content) == ('got', b'grid v2')  # nothing held: the latest, as get
    assert first.confirm(applied_to='host').outcome == 'got' and record(work)['items']['tr-grid']['mode'] == 'stays'
    newer(fake)
    receipt = e.fetch('tr-grid', stay=True)
    assert receipt.outcome == 'stays' and receipt.content == b'grid v2' and fetches(fake)[-1] == ('fetch', 'tr-grid', sha(b'grid v2'))
    assert receipt.entry['revision'] == sha(b'grid v2') and receipt.entry['output'] is None
    assert (receipt.facts['number'], receipt.facts['newer'], receipt.facts['newer_number']) == (2, True, 3)
    fake.reports.clear()
    done = receipt.confirm(applied_to='host')
    assert (done.outcome, done.sentence) == ('stays', STAYS) and done.technical['revision'] == sha(b'grid v2')
    entry = record(work)['items']['tr-grid']
    assert (entry['revision'], entry['mode'], entry['applied_to']) == (sha(b'grid v2'), 'stays', 'host')
    (sent,) = fake.reports  # the project sees the held version with `stays`: its holders list shows the copy behind
    assert sent['reference']['revision'] == sha(b'grid v2') and sent['holds'] == 'stays'


def test_fetch_stay_false_takes_the_latest_and_follows(tmp_path):
    """Mutation: fetch drops `stay` -> the mode stays `stays` after stay=False."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.fetch('tr-grid', stay=True).confirm()
    newer(fake)
    receipt = e.fetch(name=TR, type='horizon', stay=False)
    assert (receipt.outcome, receipt.content) == ('got', b'grid v3')
    assert receipt.confirm().outcome == 'got'
    entry = record(work)['items']['tr-grid']
    assert (entry['revision'], entry['mode'], entry['words']) == (sha(b'grid v3'), 'follows', {'name': TR, 'type': 'horizon'})


def test_fetch_without_stay_on_a_staying_folder_is_as_before(tmp_path):
    """Mutation: fetch honours the recorded mode -> the host is handed the held version instead of the latest."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    e.fetch('tr-grid', stay=True).confirm()
    newer(fake)
    receipt = e.fetch('tr-grid')
    assert (receipt.outcome, receipt.content) == ('got', b'grid v3') and receipt.confirm().outcome == 'got'
    assert record(work)['items']['tr-grid']['mode'] == 'stays'


def test_fetch_stay_with_an_output_keeps_the_intact_folder_without_fetching(tmp_path):
    """Mutation: a fetch with output re-reads an intact folder -> one fetch more."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    e.get('tr-grid', output=out, stay=True)
    newer(fake)
    fetched = len(fetches(fake))
    receipt = e.fetch('tr-grid', output=out, stay=True)
    assert receipt.outcome == 'stays' and receipt.content is None and len(fetches(fake)) == fetched
    assert receipt.confirm(applied_to=out).sentence == STAYS and (out / 'data.bin').read_bytes() == b'grid v2'


def test_get_and_fetch_say_the_same_on_the_same_held_state(tmp_path):
    """One rule for both doors. Mutation: fetch's staying path builds its own facts or sentence -> the answers differ."""
    answers = {}
    for door in ('get', 'fetch'):
        fake, work, out = Reporting(), tmp_path / door, tmp_path / ('%s-top' % door)
        e = ex(fake, work)
        e.get('tr-grid', output=out, stay=True)
        newer(fake)
        done = e.get('tr-grid', output=out, stay=True) if door == 'get' else e.fetch('tr-grid', output=out, stay=True).confirm(applied_to=out)
        entry = record(work)['items']['tr-grid']
        answers[door] = (done.outcome, done.sentence, done.facts, entry['mode'], entry['revision'], fake.reports[-1]['holds'])
    assert answers['get'] == answers['fetch'] and answers['get'][:2] == ('stays', STAYS)


def test_fetch_stay_is_true_or_false_and_get_still_needs_a_folder(tmp_path):
    """Mutation: fetch accepts any truthy stay, or get lets a stay without output through -> no refusal."""
    fake, work = names_project(), tmp_path / 'w'
    e = ex(fake, work)
    with pytest.raises(exchange.NotValid) as caught: e.fetch('tr-grid', stay='yes')
    assert str(caught.value) == 'The project refused this: stay is True or False. Nothing was sent.' and fake.calls == []
    e.fetch('tr-grid', stay=True).confirm()
    with pytest.raises(exchange.NotValid) as caught: e.get('tr-grid')
    assert exchange.STAY_NEEDS in str(caught.value)
