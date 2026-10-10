"""E87 C7: `ophiolite import table FILE --target T --map F=C [--dry-run]` and the run's other actions, over the answers
the Platform gave (tests/fixtures/table-import/answers.json). A dry run reviews and adds nothing; a run prints its id
before the first step and one line per set in the workspace's words; a paused run exits 4 with who paused it."""
import json
from types import SimpleNamespace

import pytest

from ophiolite import cli
from ophiolite.errors import IntegrityConflict, Refused
from ophiolite.imports import Imports
from test_imports_table import A, Fake

MAP = ['well=Well,name=Formation,md=Top MD (m)']


def args(argv):
    return cli.parser().parse_args(argv)


def run(argv, fake):
    return cli._table_import(args(argv), SimpleNamespace(imports=Imports(fake)))


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / 'nlog-tops.xlsx'; path.write_bytes(b'PK'); return str(path)


def test_the_command_line_parses_the_map_and_the_reading(workbook):
    parsed = args(['import', 'table', workbook, '--target', 'well-tops', '--map', 'name=WELL,md=TOP_MD', '--header-row', '3', '--declare', 'depth_unit=m', '--dry-run'])
    assert (parsed.command, parsed.action, parsed.what, parsed.target, parsed.map, parsed.header_row, parsed.dry_run) == \
        ('import', 'table', workbook, 'well-tops', ['name=WELL,md=TOP_MD'], 3, True)


def test_a_dry_run_reviews_in_words_and_adds_nothing(workbook, capsys):
    fake = Fake('tops')
    run(['import', 'table', workbook, '--target', 'well-tops', '--map', *MAP, '--dry-run'], fake)
    assert [s[0] for s in fake.sent] == ['read', 'preview']  # mutation guard: a dry run that starts
    assert capsys.readouterr().out.splitlines() == [
        'Dry run, nothing was added.', 'Tops to add: 2 sets (HON-GT-01: 24 rows, NLW-GT-01: 37 rows)', 'Already here: 0 sets', 'Skipped rows: 0',
        'Wells found: 1 of 2', 'Wells not found: NLW-GT-01. Its tops are added without a link to a well.', 'This adds 2 of the 100 uploads left in this project.']
    assert fake.sent[1][1]['mapping']['fields'] == {'well': 'Well', 'name': 'Formation', 'md': 'Top MD (m)'}


def test_a_run_prints_its_id_first_then_one_line_per_set(workbook, capsys):
    fake = Fake('tops')
    run(['import', 'table', workbook, '--target', 'well-tops', '--map', *MAP, '--declare', 'depth_unit=m'], fake)
    ident = A['tops']['start']['id']
    assert capsys.readouterr().out.splitlines() == [
        'Import %s started. If it stops, continue with: ophiolite import resume %s' % (ident, ident), 'Finished',
        'HON-GT-01 tops: Added: 24 tops, linked to well HON-GT-01', 'NLW-GT-01 tops: Added: 37 tops. No well named NLW-GT-01 was found, so these are not linked yet.']
    assert fake.sent[1][1]['mapping']['declarations'] == {'depth_unit': 'm'}


def test_json_gives_the_documented_answers(workbook, capsys):
    run(['import', 'table', workbook, '--target', 'well-tops', '--map', *MAP, '--json'], Fake('tops'))
    out = json.loads(capsys.readouterr().out)
    assert out['import'] == A['tops']['steps'][-1] and out['preview'] == A['tops']['preview']


def test_a_paused_run_exits_4_with_who_paused_it(workbook):
    fake = Fake('pause', read=A['tops']['read'], preview=A['tops']['preview'], step=A['pause']['step'])
    with pytest.raises(IntegrityConflict, match=r'^Paused; continue when you are ready Paused by carol .* Continue with: ophiolite import resume '):
        run(['import', 'table', workbook, '--target', 'well-tops', '--map', *MAP], fake)
    assert cli.exit_code(IntegrityConflict('x')) == 4


def test_resume_continues_a_paused_run(capsys):
    ident = A['pause']['start']['id']
    fake = Fake('pause', resume=A['pause']['resumed'], step=A['pause']['steps'][-1])
    run(['import', 'resume', ident], fake)
    assert [s[0] for s in fake.sent] == ['resume', 'step'] and capsys.readouterr().out.splitlines()[0] == 'Finished'


def test_the_refusals_before_anything_is_sent(workbook):
    for argv, said in [(['import', 'table', workbook], 'Say what the table holds with --target'),
                       (['import', 'table'], 'Give the file'),
                       (['import', 'status'], 'Give the run id'),
                       (['import', 'status', 'i1', '--target', 'well-tops'], 'Only import table takes'),
                       (['import', 'table', workbook, '--target', 'well-tops', '--declare', 'depth_unit'], 'KEY=VALUE')]:
        fake = Fake('tops')
        with pytest.raises(Refused, match=said): run(argv, fake)
        assert fake.sent == []
