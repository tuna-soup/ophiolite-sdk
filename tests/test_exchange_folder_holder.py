"""The folder's holder id for a host's own send route (`Exchange.holder_id`), and E171 design 6 as amended on 11
November: one holders read after a send that succeeded adds the Workspace's line (HeldCopies.tsx `heldSendLine`) to
the send's answer, and its counts to the facts. Against the in-memory project of tests/helpers/exchange_fake.py and,
for the SDK's transport, the fake gateway of test_cli_holders. Each test names the mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import cli, exchange
from ophiolite.exchange import ClientTransport, Exchange
from test_cli_holders import Gateway, client

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake = fake_module.Fake
V1, V2 = b'porosity v1', b'porosity v2'
SEND = dict(name='Porosity', profile='points-csv/1', how='edited', based_on=['poro'])
SENT = 'Sent Porosity as version 2. Version 1 is kept.'


class Holders(Fake):
    """The fake project with exchange/holders: `rows` answered for every item, or raised when it is an exception."""
    def __init__(self, rows=()):
        super().__init__()
        self.rows, self.asked = rows, []
        self.add('poro', V1, name='Porosity')

    def holders(self, item):
        self.asked.append(item)
        if isinstance(self.rows, Exception): raise self.rows
        return self.rows


def row(state): return {'holder': 'h', 'state': state}


def folder(tmp_path, fake):
    ex = Exchange(fake, tmp_path / 'work', clock=lambda: 1300.0)
    ex.get('poro')
    return ex


# -- holder_id ------------------------------------------------------------------------------------------------------

def test_a_fresh_folder_gets_an_id_and_its_record_is_written(tmp_path):
    """Mutation: the `_save` dropped -> held.json is not written and a second call mints another id; `_holder()` made to
    mint -> it answers an id before the call."""
    ex = Exchange(Holders(), tmp_path / 'work')
    assert ex._holder() is None and not ex.path.exists()
    holder = ex.holder_id()
    assert isinstance(holder, str) and len(holder) == 32
    record = json.loads(ex.path.read_text())
    assert record['holder_id'] == holder and record['items'] == {} and record['pending'] is None
    assert ex.holder_id() == holder and ex._holder() == holder
    assert Exchange(ex.transport, tmp_path / 'work').holder_id() == holder  # another process reads the same record


def test_an_existing_record_s_id_is_returned_and_the_record_left_byte_equal(tmp_path):
    """Mutation: `_save` called always -> the bytes are rewritten; the id minted afresh -> it differs."""
    ex = folder(tmp_path, Holders())
    before = ex.path.read_bytes()
    assert ex.holder_id() == json.loads(before)['holder_id'] and ex.path.read_bytes() == before


def test_a_later_send_names_the_same_holder(tmp_path):
    """Mutation: holder_id answers an id it does not save -> the send names another holder."""
    fake = Holders(); ex = Exchange(fake, tmp_path / 'work', clock=lambda: 1300.0)
    holder = ex.holder_id()
    ex.get('poro')
    ex.send(V2, **SEND, of='poro')
    assert fake.attributions[-1] == {'holder': holder, 'application': 'script'}


def test_holder_id_refuses_as_the_record_does(tmp_path):
    """Mutation: the error of `_load` swallowed -> an unreadable folder answers an id (and is overwritten)."""
    ex = Exchange(Holders(), tmp_path / 'work'); ex.work.mkdir()
    ex.path.write_text('not json')
    with pytest.raises(exchange.NotValid): ex.holder_id()
    assert ex.path.read_text() == 'not json'


# -- the held line after a send ----------------------------------------------------------------------------------------

def test_two_holders_one_behind_give_the_workspace_s_line(tmp_path):
    """Mutation: the plural or the "of them" clause changed -> the line differs from heldSendLine; read under the
    `sent` item's id dropped -> another item asked."""
    fake = Holders([row('current'), row('behind')]); ex = folder(tmp_path, fake)
    done = ex.send(V2, **SEND, of='poro')
    assert done.sentence == SENT  # qualification (tools/package/qualify_exchange.py) compares it exactly
    assert done.facts['held_line'] == 'Held by 2 connected applications, 1 of them on an older version.'
    assert (done.facts['held_by'], done.facts['on_an_older_version']) == (2, 1) and fake.asked == ['poro']


def test_one_holder_is_said_in_the_singular_on_a_new_item_too(tmp_path):
    """Mutation: the singular dropped -> "1 connected applications"; the line only on sent-version -> a new item has none."""
    fake = Holders([row('current')]); ex = folder(tmp_path, fake)
    done = ex.send(V2, **SEND)
    assert done.outcome == 'sent-new' and fake.asked == [done.technical['asset_id']]
    assert done.sentence == 'Sent Porosity as a new item; it is private until you share it.'
    assert done.facts['held_line'] == 'Held by 1 connected application.'
    assert exchange.held_line(1, 1) == 'Held by 1 connected application, 1 of them on an older version.'


@pytest.mark.parametrize('rows', [RuntimeError('the read failed'), {'rows': []}, ['not a row'], None], ids=['raises', 'dict', 'row', 'none'])
def test_a_read_that_fails_leaves_today_s_answer(tmp_path, rows):
    """Mutation: the `except` removed -> the send raises after it was kept; malformed rows counted -> a line appears."""
    fake = Holders(rows); ex = folder(tmp_path, fake)
    done = ex.send(V2, **SEND, of='poro')
    assert (done.outcome, done.sentence) == ('sent-version', SENT) and not {'held_by', 'held_line'} & set(done.facts)
    assert ex.held()['poro']['number'] == 2 and json.loads(ex.path.read_text())['pending'] is None


def test_a_transport_without_holders_gives_no_line(tmp_path):
    """Mutation: `holders` required of the transport -> AttributeError; facts filled with zeros -> facts differ."""
    fake = Fake(); fake.add('poro', V1, name='Porosity')
    ex = folder(tmp_path, fake)
    done = ex.send(V2, **SEND, of='poro')
    assert (done.sentence, done.facts) == (SENT, {'name': 'Porosity', 'number': 2})


def test_no_holder_gives_counts_but_no_line(tmp_path):
    """Mutation: the line said for zero rows -> "Held by 0 connected applications." (the Workspace shows none)."""
    done = folder(tmp_path, Holders([])).send(V2, **SEND, of='poro')
    assert done.sentence == SENT and (done.facts['held_by'], done.facts['on_an_older_version']) == (0, 0) and 'held_line' not in done.facts


def test_nothing_changed_and_refusals_read_nothing(tmp_path):
    """Mutation: the read moved before the outcome is decided -> a refused send asks for holders."""
    fake = Holders([row('behind')]); ex = folder(tmp_path, fake)
    with pytest.raises(exchange.REFUSALS['nothing-changed']): ex.send(V1, **SEND, of='poro')
    with pytest.raises(exchange.REFUSALS['newer-version-exists']): ex.send(V2, **SEND, of='poro', expected='other')
    with pytest.raises(exchange.REFUSALS['not-held']): ex.send(V2, **dict(SEND, based_on=['elsewhere']))
    assert fake.asked == []


def test_a_retried_send_reads_once_when_it_lands(tmp_path):
    """Mutation: the read made while the outcome is unknown -> holders asked before the send is known to have landed."""
    fake = Holders([row('current'), row('behind'), row('behind')]); ex = folder(tmp_path, fake)
    fake.drop_after_commit = True
    with pytest.raises(exchange.REFUSALS['outcome-unknown']): ex.send(V2, **SEND, of='poro')
    assert fake.asked == []
    done = ex.send(V2, **SEND, of='poro')
    assert done.sentence == SENT and fake.asked == ['poro']
    assert done.facts['held_line'] == 'Held by 3 connected applications, 2 of them on an older version.'


class Client:
    """The CLI's client, as far as `_exchange` asks it: the exchange over the fake project."""
    def __init__(self, fake): self.fake = fake
    def exchange(self, work, sentences=None): return Exchange(self.fake, work, sentences=sentences, clock=lambda: 1300.0)


@pytest.mark.parametrize('rows, said', [([row('current'), row('behind')], [SENT, 'Held by 2 connected applications, 1 of them on an older version.']),
                                        (RuntimeError('the read failed'), [SENT])], ids=['held', 'read-fails'])
def test_the_cli_prints_the_held_line_after_the_sentence(tmp_path, capsys, rows, said):
    """stdout stays the sentence alone (tools/package/qualify_exchange.py compares it); people see the held line on
    stderr. Mutation: the CLI's print dropped -> stderr is empty; printed to stdout -> stdout has two lines; printed
    with --json -> stderr is not empty there."""
    def send(where, *extra):
        fake = Holders(rows); folder(where, fake)
        (where / 'v2.csv').write_bytes(V2)
        argv = ['send', str(where / 'v2.csv'), '--profile', 'points-csv/1', '--name', 'Porosity', '--how', 'edited', '--based-on', 'poro',
                '--of', 'poro', '--work', str(where / 'work'), *extra]
        capsys.readouterr()
        done = cli._exchange(cli.parser().parse_args(argv), Client(fake))
        return (done, *capsys.readouterr())
    done, out, err = send(tmp_path / 'people')
    assert (out, err.splitlines()) == (SENT + '\n', said[1:]) and done.sentence == SENT
    done, out, err = send(tmp_path / 'json', '--json')
    assert json.loads(out) == done.to_dict() and json.loads(out)['sentence'] == SENT and err == ''
    assert json.loads(out)['facts'].get('held_line') == (said[1] if len(said) > 1 else None)


def test_the_sdk_transport_reads_the_rows_whole_from_exchange_holders():
    """Over the fake gateway's two pages. Mutation: the first page only -> two rows; the document returned instead of
    its rows -> nothing to count."""
    gateway = Gateway()
    rows = ClientTransport(client(gateway)).holders('horizon-top')
    assert len(rows) == 3 and [b.get('item') for b in gateway.bodies] == ['horizon-top', 'horizon-top']
    counted = (len(rows), sum(1 for r in rows if r['state'] == 'behind'))
    assert exchange.held_line(*counted) == 'Held by 3 connected applications, 2 of them on an older version.'
