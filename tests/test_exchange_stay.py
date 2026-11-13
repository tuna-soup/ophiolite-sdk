"""E173 s1 C2: get(..., stay=True) keeps the version a folder holds; stay=False takes the latest; the folder records which
(held/2 `mode`), and a plain get honours it. Against names_project() of tests/helpers/exchange_fake.py; fetches are
counted at the fake transport. Each test names the mutation it catches."""
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
HORIZON = {'name': TR, 'type': 'horizon'}
NEEDS = 'The project refused this: staying needs a folder to keep the version in. Nothing was sent.'


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


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    return caught.value


# -- acceptance 4 -----------------------------------------------------------------------------------------------------------

def test_stay_takes_the_latest_once_then_keeps_it_without_fetching_and_says_what_is_newer(tmp_path):
    """Mutation: _stay fetches the held version although the folder is intact -> one fetch more on the re-run."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    first = ex(fake, work).get(name=TR, type='horizon', output=out, stay=True)
    assert first.outcome == 'got' and (out / 'data.bin').read_bytes() == b'grid v2'
    entry = record(work)['items']['tr-grid']
    assert (entry['mode'], entry['words'], entry['revision']) == ('stays', HORIZON, sha(b'grid v2'))
    latest = ex(fake, work).get(name=TR, type='horizon', output=out, stay=True)
    assert (latest.outcome, latest.sentence) == ('stays', 'You stay on version 2 of Top Rotliegend, the latest.')
    newer(fake)
    fetched = len(fetches(fake))
    stays = ex(fake, work).get(name=TR, type='horizon', output=out, stay=True)
    assert stays.outcome == 'stays' and len(fetches(fake)) == fetched
    assert stays.sentence == 'You stay on version 2 of Top Rotliegend. Version 3 is newer; get it with stay=False to take it.'
    assert (stays.facts['number'], stays.facts['newer'], stays.facts['newer_number']) == (2, True, 3)
    assert (stays.technical['asset_id'], stays.technical['revision']) == ('tr-grid', sha(b'grid v2'))
    assert (out / 'data.bin').read_bytes() == b'grid v2' and record(work)['items']['tr-grid']['revision'] == sha(b'grid v2')
    plain, plain_out = tmp_path / 'plain', tmp_path / 'plain-top'
    ex(fake, plain).get('tr-grid', output=plain_out)  # a mode-less folder: without stay, today's get takes the new version
    assert (plain_out / 'data.bin').read_bytes() == b'grid v3' and 'mode' not in record(plain)['items']['tr-grid']


# -- R-M7: one explicit call each way --------------------------------------------------------------------------------------

def test_stay_false_on_a_staying_folder_takes_the_latest_and_follows_and_stay_true_switches_back_without_fetching(tmp_path):
    """Mutation: stay=False writes no mode -> the folder still says it stays."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    e.get(name=TR, type='horizon', output=out, stay=True)
    newer(fake)
    took = e.get(name=TR, type='horizon', output=out, stay=False)
    assert took.outcome == 'got' and (out / 'data.bin').read_bytes() == b'grid v3'
    assert (record(work)['items']['tr-grid']['mode'], record(work)['items']['tr-grid']['words']) == ('follows', HORIZON)
    fetched = len(fetches(fake))
    back = e.get(name=TR, type='horizon', output=out, stay=True)
    assert (back.outcome, back.sentence) == ('stays', 'You stay on version 3 of Top Rotliegend, the latest.')
    assert len(fetches(fake)) == fetched and record(work)['items']['tr-grid']['mode'] == 'stays'


def test_stay_false_at_the_held_version_records_follows_without_fetching_and_a_restart_reads_it(tmp_path):
    """F5. Mutation: already-latest ignores the mode asked for -> the folder still stays, and the next plain get stays."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    ex(fake, work).get('tr-grid', output=out, stay=True)
    fetched = len(fetches(fake))
    done = ex(fake, work).get('tr-grid', output=out, stay=False)
    assert done.outcome == 'already-latest' and len(fetches(fake)) == fetched
    assert record(work)['items']['tr-grid']['mode'] == 'follows' and 'words' not in record(work)['items']['tr-grid']
    newer(fake)
    assert ex(fake, work).get('tr-grid', output=out).outcome == 'got' and (out / 'data.bin').read_bytes() == b'grid v3'


# -- stay=None: what the folder recorded -----------------------------------------------------------------------------------

@pytest.mark.parametrize('mode, outcome, data', [('stays', 'stays', b'grid v2'), ('follows', 'got', b'grid v3'), (None, 'got', b'grid v3')],
                         ids=['stays', 'follows', 'no-mode'])
def test_a_plain_get_honours_the_recorded_mode(tmp_path, mode, outcome, data):
    """Mutation: stay=None ignores the record -> a staying folder takes the new version."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    e.get('tr-grid', output=out, **({'stay': mode == 'stays'} if mode else {}))
    newer(fake)
    done = e.get('tr-grid', output=out)
    assert done.outcome == outcome and (out / 'data.bin').read_bytes() == data
    entry = record(work)['items']['tr-grid']
    assert entry.get('mode') == mode and ('mode' in entry) == (mode is not None)  # absent stays absent


def test_the_two_step_fetch_is_as_before_on_a_staying_folder(tmp_path):
    """D4: `stay` is get's; a connector's fetch takes the latest, whatever the folder recorded."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    e.get('tr-grid', output=out, stay=True)
    newer(fake)
    receipt = e.fetch('tr-grid', output=out)
    assert receipt.content == b'grid v3' and receipt.confirm(applied_to=out).outcome == 'got'
    assert record(work)['items']['tr-grid']['mode'] == 'stays'  # kept, as any confirm keeps it


# -- a changed or missing folder: the held version, never the head ----------------------------------------------------------

@pytest.mark.parametrize('change', ['edited', 'missing'])
def test_a_changed_or_missing_folder_under_stay_fetches_the_held_version_exactly(tmp_path, change):
    """Mutation: _stay asks the transport for the head -> the fake is asked for version 3 and the folder holds it."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    e.get(name=TR, type='horizon', output=out, stay=True)
    newer(fake)
    if change == 'edited': (out / 'data.bin').write_bytes(b'changed by hand')
    else: (out / 'data.bin').unlink(); out.rmdir()
    done = e.get(name=TR, type='horizon', output=out, stay=True)
    assert done.outcome == 'stays' and done.sentence == 'You stay on version 2 of Top Rotliegend. Version 3 is newer; get it with stay=False to take it.'
    assert fetches(fake)[-1] == ('fetch', 'tr-grid', sha(b'grid v2'))
    assert (out / 'data.bin').read_bytes() == b'grid v2'
    entry = record(work)['items']['tr-grid']
    assert entry['revision'] == sha(b'grid v2') and entry['output']['sha256'] == exchange.folder_digest(out)
    fetched = len(fetches(fake))
    assert e.get(name=TR, type='horizon', output=out, stay=True).outcome == 'stays' and len(fetches(fake)) == fetched  # intact again


# -- the re-confirmation ---------------------------------------------------------------------------------------------------

def test_the_staying_re_run_reports_once_with_the_held_version_and_holds_stays_and_keeps_note_and_words(tmp_path):
    """V5, Q6. Mutation: _stay returns without confirming -> nothing is reported and got_at does not move."""
    fake, work, out = Reporting(), tmp_path / 'w', tmp_path / 'top'
    now = [1300.0]
    e = Exchange(fake, work, clock=lambda: now[0])
    e.get(name=TR, type='horizon', output=out, stay=True)
    held = record(work); held['items']['tr-grid']['note'] = 'picked for the well tie'
    (work / 'held.json').write_text(json.dumps(held))
    newer(fake)
    fake.reports.clear(); now[0] = 1500.0
    done = e.get(name=TR, type='horizon', output=out, stay=True)
    assert done.outcome == 'stays' and done.technical['reported'] is True
    (sent,) = fake.reports
    assert sent['reference'] == {'project_id': 'p', 'asset_id': 'tr-grid', 'revision': sha(b'grid v2')} and sent['holds'] == 'stays'
    entry = record(work)['items']['tr-grid']
    assert (entry['note'], entry['words'], entry['mode'], entry['got_at'], entry['applied_to']) == (
        'picked for the well tie', HORIZON, 'stays', 1500.0, str(out))


# -- staying needs a folder (F6) ---------------------------------------------------------------------------------------------

def test_staying_without_an_output_folder_is_refused_and_changes_nothing(tmp_path):
    """Mutation: the output check dropped for a recorded `stays` -> the plain get takes the head into no folder."""
    fake, work, out = names_project(), tmp_path / 'w', tmp_path / 'top'
    e = ex(fake, work)
    assert str(refused('not-valid', lambda: e.get('tr-grid', stay=True))) == NEEDS and fake.calls == []
    e.get('tr-grid', output=out, stay=True)
    newer(fake)
    before, fetched = (work / 'held.json').read_bytes(), len(fetches(fake))
    assert str(refused('not-valid', lambda: e.get('tr-grid'))) == NEEDS
    assert (work / 'held.json').read_bytes() == before and len(fetches(fake)) == fetched
    assert str(refused('not-valid', lambda: e.get('tr-grid', output=out, stay='yes'))) == 'The project refused this: stay is True or False. Nothing was sent.'
