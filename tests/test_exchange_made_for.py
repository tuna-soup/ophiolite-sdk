"""E192 s2 C2: `Exchange.made_for` answers the exact version a name means now and writes nothing; `send(made_for=)`
carries exact versions in the saved request, so a retry sends the same ones and a retry naming others is refused before
the transport. Against the in-memory project (tests/helpers/exchange_fake.py). Each test names its mutation."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import exchange
from ophiolite.exchange import Exchange

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)

NOW = 1000.0 + 7200  # two hours after the fixtures' versions
D1, D5, D6 = b'design v1', b'design v5', b'design v6'


class Project(fake_module.Fake):
    """The fake project with a transport that takes made_for: each publish's made_for is kept in `made_for`."""
    takes_made_for = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.made_for, self.before_history = [], None

    def publish(self, data, request, resolved, command_id, attribution=None):
        self.made_for.append(request.get('made_for', 'absent'))
        return super().publish(data, request, resolved, command_id, attribution)

    def history(self, item):
        if self.before_history: self.before_history(); self.before_history = None
        return super().history(item)


class Host(Project):
    takes_made_for = False


def sha(data): return fake_module.sha(data)


@pytest.fixture
def project():
    fake = Project()
    for n in range(1, 6): fake.add('design', b'design v%d' % n, name='Design', by='Bob Example', at=1000.0, profile='points-csv/1')
    fake.add('poro', b'porosity v1', name='Porosity')
    fake.add('recipe-1', b'recipe', name='Recipe', kind='recipe')
    return fake


def ex(fake, work, **options):
    return Exchange(fake, work, clock=lambda: NOW, **options)


def refused(code, call):
    with pytest.raises(exchange.REFUSALS[code]) as caught: call()
    assert caught.value.outcome == code
    return caught.value


def folder_bytes(work):
    return {p.name: p.read_bytes() for p in sorted(Path(work).glob('*'))} if Path(work).exists() else None


# -- the first answer --------------------------------------------------------------------------------------------------

def test_by_name_the_answer_is_the_exact_version_and_nothing_is_written(project, tmp_path):
    """No work folder before, none after; with a record, the record's bytes are unchanged. Mutation: the answer saves
    the folder's record (`self._save(self._load())`) → red."""
    work = tmp_path / 'none'
    said = ex(project, work).made_for(name='Design')
    assert said.outcome == 'made-for'
    assert said.sentence == ('Design, version 5 by Bob Example, 2 hours ago: the version this name means now. '
                             'Send with this exact version to record what your file was made for. Nothing was changed.')
    assert said.technical == {'asset_id': 'design', 'revision': sha(b'design v5')}
    assert {k: said.facts[k] for k in ('name', 'number', 'by', 'at')} == {'name': 'Design', 'number': 5, 'by': 'Bob Example', 'at': 1000.0}
    assert not work.exists()
    held = tmp_path / 'held'
    ex(project, held).get('poro')
    before = folder_bytes(held)
    assert ex(project, held).made_for(name='Design', type='point set').technical['revision'] == sha(b'design v5')
    assert ex(project, held).made_for('design').technical['revision'] == sha(b'design v5')
    assert folder_bytes(held) == before
    assert not any(c[0] == 'publish' for c in project.calls)


def test_the_facts_describe_the_returned_version_when_the_head_moves_during_the_answer(project, tmp_path):
    """Version 6 is published between the inventory and the history read. Mutation: the facts taken from the newest
    history entry (`versions[-1]`) → version 6 shown beside version 5's revision."""
    project.before_history = lambda: project.add('design', D6, name='Design', by='Carol Example', at=1500.0)
    said = ex(project, tmp_path / 'w').made_for(name='Design')
    assert said.technical['revision'] == sha(b'design v5') and said.facts['number'] == 5 and said.facts['by'] == 'Bob Example'


def test_refusals_of_the_first_answer(project, tmp_path):
    work = tmp_path / 'w'
    assert refused('name-not-found', lambda: ex(project, work).made_for(name='Nothing')).facts == {'name': 'Nothing'}
    project.add('design-2', b'other', name='Design', profile='las2/1')
    refused('name-unclear', lambda: ex(project, work).made_for(name='Design'))
    assert ex(project, work).made_for(name='Design', type='well log').technical['asset_id'] == 'design-2'  # the type decides
    refused('not-visible', lambda: ex(project, work).made_for('gone'))
    project.hidden.add('poro')
    refused('not-visible', lambda: ex(project, work).made_for('poro'))
    error = refused('not-valid', lambda: ex(project, work).made_for('recipe-1'))
    assert 'only when it is an uploaded or published version' in str(error)
    project.history_fails = True
    refused('could-not-reach', lambda: ex(project, work).made_for('design'))
    assert not work.exists()


def test_a_name_this_folder_recorded_for_another_item_does_not_change_the_answer(project, tmp_path):
    """The folder named another item 'Design' (E173's held words). Mutation: `_resolve` given the folder's record →
    the held item is answered."""
    work = tmp_path / 'w'
    ex(project, work).get('poro')
    record = json.loads((work / 'held.json').read_text())
    record['items']['poro']['words'] = {'name': 'Design'}
    (work / 'held.json').write_text(json.dumps(record))
    assert ex(project, work).made_for(name='Design').technical['asset_id'] == 'design'


# -- the send ----------------------------------------------------------------------------------------------------------

def held(project, tmp_path):
    work = tmp_path / 'w'
    ex(project, work).get('poro')
    return work


def test_the_send_carries_the_answered_version_even_after_a_newer_one(project, tmp_path):
    """Version 6 is published between the answer and the send: the version answered is the one sent. Acceptance 4:
    a send without made_for carries none. Mutation: the transport not passed `made_for` (or the request without it)."""
    work = held(project, tmp_path)
    answer = ex(project, work).made_for(name='Design')
    project.add('design', D6, name='Design')
    done = ex(project, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro'], made_for=[answer.technical])
    assert done.outcome == 'sent-new' and done.sentence == 'Sent Estimate as a new item; it is private until you share it.'
    assert project.made_for == [[{'asset_id': 'design', 'revision': sha(D5)}]]
    ex(project, work).send(b'estimate 2', name='Estimate 2', profile='points-csv/1', how='by hand', based_on=['poro'])
    assert project.made_for[-1] == 'absent'


@pytest.mark.parametrize('second', ['changed', 'removed', 'added'])
def test_a_retry_after_a_lost_answer_must_name_the_same_versions(project, tmp_path, second):
    """A lost answer leaves the send pending; a retry naming other versions (or none, or some where there were none) is
    refused before the transport; the same retry publishes once. Mutation: `made_for` kept outside `request` → the
    changed retry is sent."""
    work = held(project, tmp_path)
    first = [{'asset_id': 'design', 'revision': sha(D5)}] if second != 'added' else None
    other = {'changed': [('design', sha(b'design v4'))], 'removed': None, 'added': [('design', sha(D5))]}[second]
    send = lambda made_for: ex(project, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro'],
                                                  **({'made_for': made_for} if made_for is not None else {}))
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: send(first))
    calls = len([c for c in project.calls if c[0] == 'publish'])
    error = refused('not-valid', lambda: send(other))
    assert 'unfinished' in str(error) and len([c for c in project.calls if c[0] == 'publish']) == calls
    assert send(first).outcome == 'sent-new' and len([i for i in project.items if i.startswith('new-')]) == 1


def test_a_pending_send_saved_before_this_version_is_sent_again_as_it_was(project, tmp_path):
    """A pending request with no made_for field (as an earlier SDK saved it) replays unchanged."""
    work = held(project, tmp_path)
    project.drop_after_commit = True
    refused('outcome-unknown', lambda: ex(project, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro']))
    assert 'made_for' not in json.loads((work / 'held.json').read_text())['pending']['request']
    assert ex(project, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro']).outcome == 'sent-new'


@pytest.mark.parametrize('made_for', [[], [('design', 'x')], [('design', sha(D5))] * 2, [{'asset_id': 'design'}], 'Design', [('poro', sha(b'porosity v1'))]])
def test_malformed_made_for_or_one_that_is_also_a_parent_is_refused_before_anything_is_saved(project, tmp_path, made_for):
    """Mutation: `_made_for`'s checks or the overlap with the based-on versions removed → saved or sent."""
    work = held(project, tmp_path)
    refused('not-valid', lambda: ex(project, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro'], made_for=made_for))
    assert json.loads((work / 'held.json').read_text())['pending'] is None and not any(c[0] == 'publish' for c in project.calls)


def test_the_send_again_line_carries_made_for():
    """Mutation: `made_for` dropped from `send_again`'s order → the line forgets it."""
    from ophiolite.presentation import send_again
    line = send_again({'name': 'Estimate', 'profile': 'points-csv/1', 'how': 'by hand', 'based_on': ['poro'], 'made_for': [('design', sha(D5))]}, 'new-1', 'a' * 64)
    assert line == "ex.send(new_file, name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro'], made_for=[['design', '%s']])" % sha(D5)


def test_a_transport_that_takes_no_made_for_refuses_in_a_plain_sentence_before_saving(tmp_path):
    """QGIS and the assistant (e8, 24 Nov). Mutation: the `takes_made_for` check removed → the send is saved and sent."""
    fake = Host(); fake.add('poro', b'porosity v1', name='Porosity'); fake.add('design', D5, name='Design')
    work = tmp_path / 'w'; ex(fake, work).get('poro')
    error = refused('not-valid', lambda: ex(fake, work).send(b'estimate', name='Estimate', profile='points-csv/1', how='by hand', based_on=['poro'],
                                                           made_for=[('design', sha(D5))]))
    assert str(error) == ('The project refused this: this application does not send what a file was made for; send it from Python or the '
                          'command line. Nothing was sent.')
    assert json.loads((work / 'held.json').read_text())['pending'] is None and fake.made_for == []
    from ophiolite.agent_exchange import AgentTransport
    assert AgentTransport.takes_made_for is False and exchange.ClientTransport.takes_made_for is True
