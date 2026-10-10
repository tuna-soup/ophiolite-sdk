"""E88 C6: `ophiolite wells from-run RUN... [--create NAME]... [--is NAME=ENTITY]... [--skip NAME]... [--create-all]
[--link-exact-only] [--dry-run] [--json]` over the answers the Platform gave (tests/fixtures/well-names/answers.json).
No decision flag prints the list and changes nothing; --create-all is the click; --link-exact-only creates nothing; both
together exit 2. The upload report ends with the wells its files name and the command that lists them."""
import json
from types import SimpleNamespace

import pytest

from ophiolite import cli
from ophiolite.errors import Unavailable
from ophiolite.well_names import WellNames
from test_well_names import A, Fake


def run(argv, fake, **client):
    args = cli.parser().parse_args(['wells', 'from-run', *argv])
    return cli._journey(args, SimpleNamespace(well_names=WellNames(fake), **client))


def test_no_decision_flag_prints_the_list_and_changes_nothing(capsys):
    fake = Fake(propose=[A['propose']])
    run(A['runs'], fake)
    assert [s[0] for s in fake.sent] == ['propose']  # mutation guard: a list that accepts
    assert capsys.readouterr().out.splitlines()[:2] == ['Wells named in your files', '1 file and 1 table name 1 well that is not in this project.']


def test_a_dry_run_with_a_decision_lists_and_does_not_accept(capsys):
    fake = Fake(propose=[A['propose']])
    run([*A['runs'], '--create-all', '--dry-run'], fake)
    assert [s[0] for s in fake.sent] == ['propose']  # mutation guard: a dry run that calls accept
    assert capsys.readouterr().out.splitlines()[0] == 'Dry run, nothing was changed.'


def test_create_all_is_the_click(capsys):
    fake = Fake(propose=[A['propose']], accept=[A['accept']])
    run([*A['runs'], '--create-all'], fake)
    assert fake.sent[1][1]['create'] == 'all' and fake.sent[1][1]['digest'] == A['propose']['digest']
    assert capsys.readouterr().out.strip() == 'Created 1 well and 1 wellbore. Linked 2 files and sheets. 0 left.'


def test_link_exact_only_creates_nothing(capsys):
    fake = Fake(propose=[A['link']['propose'], A['link']['propose']], accept=[A['link']['accept']])
    run([*A['runs'], '--link-exact-only', '--json'], fake)
    sent = fake.sent[-1][1]
    assert 'create' not in sent and sent['link'] == ['hon-gt-1']  # mutation guard: --link-exact-only that creates
    assert json.loads(capsys.readouterr().out)['accepted'] == A['link']['accept']


def test_both_flags_exit_2_before_any_call(capsys):
    fake = Fake()
    with pytest.raises(SystemExit) as exited: run([*A['runs'], '--create-all', '--link-exact-only'], fake)
    assert exited.value.code == 2 and fake.sent == []
    assert capsys.readouterr().err.strip() == 'Choose one: --create-all or --link-exact-only.'


def test_is_writes_the_other_name_and_says_it(capsys):
    fake = Fake(propose=[A['is']['propose'], A['is']['propose']], accept=[A['is']['accept']])
    names = {A['is']['wellbore']: 'Honselersdijk-GT-1', A['is']['well']: 'Honselersdijk-GT-1'}
    run([*A['runs'], '--is', 'HON-GT-01=' + A['is']['wellbore']], fake, entity=lambda e: SimpleNamespace(name=names[e]))
    assert fake.sent[-1][1]['is'] == {'hon-gt-1': A['is']['wellbore']}
    assert capsys.readouterr().out.strip() == ('Created 0 wells and 0 wellbores. Linked 2 files and sheets. '
                                               'HON-GT-01 is now another name for Honselersdijk-GT-1. 0 left.')


def test_a_refusal_keeps_its_sentence_and_its_exit_code(capsys):
    answer = A['refusals']['list-changed']
    fake = Fake(propose=[A['propose']], accept=[answer])
    with pytest.raises(Exception) as refused: run([*A['runs'], '--create-all'], fake)
    assert str(refused.value) == answer['body']['error'] and cli.exit_code(refused.value) == cli.EXIT['conflict']


def test_list_and_extent_take_no_runs():
    args = cli.parser().parse_args(['wells', 'list', 'run-1'])
    with pytest.raises(ValueError, match='Only wells from-run takes runs'): cli._journey(args, SimpleNamespace())


def test_the_upload_report_ends_with_the_wells_its_files_name():
    fake = Fake(propose=[A['propose']])
    line = cli._named_wells(SimpleNamespace(well_names=WellNames(fake)), A['runs'][0])
    assert line == '1 file and 1 table name 1 well that is not in this project. Run: ophiolite wells from-run %s' % ' '.join(A['propose']['runs'])
    assert fake.sent == [('propose', {'runs': [A['runs'][0]]})]


def test_the_upload_report_says_nothing_when_the_server_has_no_well_names():
    gone = Fake(propose=[{'status': 404, 'body': {'error': 'Not found', 'code': 'not-found'}}])
    assert cli._named_wells(SimpleNamespace(well_names=WellNames(gone)), 'r') is None
    assert cli._named_wells(SimpleNamespace(), 'r') is None
    assert cli._named_wells(SimpleNamespace(well_names=WellNames(Fake(propose=[A['link']['propose']]))), 'r') is None


def test_ophiolite_upload_prints_the_line_after_its_report(tmp_path, capsys):
    # mutation guard: an upload report that leaves the line out
    report = SimpleNamespace(run_id=A['runs'][0], view={}, ok=True, text=lambda: 'F-MIX - 1 files - Finished. 1 Added')
    runs = SimpleNamespace(upload=lambda *a, **k: report)
    args = cli.parser().parse_args(['upload', str(tmp_path), '--attribution', 'Synthetic', '--rights-confirmed'])
    cli._upload(args, SimpleNamespace(upload_runs=runs, well_names=WellNames(Fake(propose=[A['propose']]))))
    assert capsys.readouterr().out.splitlines() == ['F-MIX - 1 files - Finished. 1 Added',
                                                    '1 file and 1 table name 1 well that is not in this project. Run: ophiolite wells from-run %s' % ' '.join(A['propose']['runs'])]
