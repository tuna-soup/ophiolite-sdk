"""E192 s2 C3: `ophiolite exchange made-for` (hidden alias `made-for`) says the exact version a name means now and
prints it as ITEM@VERSION on its own line; `ophiolite send --made-for ITEM@VERSION` carries those versions. Through
`cli._exchange` over the in-memory project (tests/helpers/exchange_fake.py). Each test names the mutation it catches."""
import importlib.util
import json
from pathlib import Path

import pytest

from ophiolite import cli
from ophiolite.exchange import Exchange

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
D5 = b'design v5'
REV5 = fake_module.sha(D5)
SAID = ('Design, version 5 by Bob Example, 2 hours ago: the version this name means now. '
        'Send with this exact version to record what your file was made for. Nothing was changed.')


class Project(fake_module.Fake):
    takes_made_for = True

    def __init__(self):
        super().__init__()
        self.made_for = []
        for n in range(1, 6): self.add('design', b'design v%d' % n, name='Design', by='Bob Example', at=1000.0, profile='points-csv/1')
        self.add('poro', b'porosity v1', name='Porosity')

    def publish(self, data, request, resolved, command_id, attribution=None):
        self.made_for.append(request.get('made_for', 'absent'))
        return super().publish(data, request, resolved, command_id, attribution)


class Client:
    """The CLI's client, as far as `_exchange` asks it."""
    def __init__(self, fake): self.fake = fake
    def exchange(self, work, sentences=None): return Exchange(self.fake, work, sentences=sentences, clock=lambda: 1000.0 + 7200)


def run(fake, argv, capsys):
    capsys.readouterr()
    done = cli._exchange(cli.parser().parse_args(argv), Client(fake))
    return (done, *capsys.readouterr())


@pytest.mark.parametrize('spelling', [['made-for'], ['exchange', 'made-for']], ids=['old', 'grouped'])
def test_made_for_prints_the_sentence_then_the_exact_version_and_writes_nothing(tmp_path, capsys, spelling):
    """Mutation: the ITEM@VERSION line dropped -> stdout is the sentence alone; printed with --json -> stdout is not one
    JSON document; 'made-for' left out of cli_groups -> the grouped spelling does not parse."""
    fake, work = Project(), tmp_path / 'work'
    done, out, err = run(fake, [*spelling, '--name', 'Design', '--work', str(work)], capsys)
    assert (out.splitlines(), err) == ([SAID, 'design@' + REV5], '')
    assert not work.exists() and not any(c[0] == 'publish' for c in fake.calls)
    done, out, err = run(fake, [*spelling, '--item', 'design', '--work', str(work), '--json'], capsys)
    assert json.loads(out) == done.to_dict() and json.loads(out)['technical'] == {'asset_id': 'design', 'revision': REV5} and err == ''


def test_send_made_for_carries_the_exact_versions_and_without_it_none(tmp_path, capsys):
    """The printed line is what --made-for takes. Mutation: `made_for=args.made_for` not passed -> the project sees
    'absent'; the flag passed when not given -> the second send carries a value."""
    fake, work = Project(), tmp_path / 'work'
    Exchange(fake, work).get('poro')
    (tmp_path / 'estimate.csv').write_bytes(b'estimate')
    _, out, _ = run(fake, ['made-for', '--name', 'Design', '--work', str(work)], capsys)
    exact = out.splitlines()[1]
    send = ['send', str(tmp_path / 'estimate.csv'), '--profile', 'points-csv/1', '--how', 'by hand', '--based-on', 'poro', '--work', str(work)]
    done, _, err = run(fake, [*send, '--name', 'Estimate', '--made-for', exact], capsys)
    assert done.outcome == 'sent-new' and err == ''
    assert fake.made_for == [[{'asset_id': 'design', 'revision': REV5}]]
    run(fake, [*send, '--name', 'Estimate 2'], capsys)
    assert fake.made_for[-1] == 'absent'


@pytest.mark.parametrize('value', ['design', 'design@' + 'A' * 64, 'design@' + 'a' * 63, '@' + 'a' * 64, 'design@'])
def test_a_malformed_exact_version_is_a_usage_error(tmp_path, capsys, value):
    """Exit 2 before any exchange opens. Mutation: the 64-hex check dropped -> the upper-case and short revisions parse."""
    with pytest.raises(SystemExit) as caught:
        cli.parser().parse_args(['send', 'f.csv', '--profile', 'points-csv/1', '--name', 'E', '--how', 'h', '--made-for', value])
    assert caught.value.code == 2
    assert 'give an exact version as ITEM@VERSION, as ophiolite exchange made-for prints it' in capsys.readouterr().err
