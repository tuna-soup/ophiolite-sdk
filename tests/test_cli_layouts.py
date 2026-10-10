"""E89 C6: `ophiolite layouts ...`, `ophiolite import table --layout NAME` and `ophiolite upload` of a table file over the
answers the Platform gave (tests/fixtures/layouts/answers.json). Layouts are named by their name; no id, digest or key
is printed without --json. A table that matches a layout is not added unless the layout is named (exit 4)."""
import json
from types import SimpleNamespace

import pytest

from ophiolite import cli
from ophiolite.errors import IntegrityConflict
from test_layouts import A, DAY, Fake, landing, table

SECRETS = [A['listed']['layouts'][0]['asset_id'], A['listed']['layouts'][0]['content_digest'], A['read']['input_id'], A['started']['id'], 'carol', 'bob']


def layouts(argv, fake):
    return cli._layouts(cli.parser().parse_args(['layouts', *argv]), fake)


def shown(capsys):
    out = capsys.readouterr().out
    assert not [s for s in SECRETS if s in out], out  # mutation guard: an id or account id in the words
    return out


def test_list_prints_names_and_people_by_their_names(capsys):
    layouts(['list'], Fake(**{'layouts/list': A['listed']}))
    assert shown(capsys).splitlines() == ['Tubbergen tops · Well tops · 4: Well Name, Top, MD (m) and 1 more · Made by Carol Smit, %s · Last used: Carol Smit, %s' % (DAY, DAY)]


def test_json_carries_the_answers(capsys):
    layouts(['list', '--json'], Fake(**{'layouts/list': A['listed']}))
    assert json.loads(capsys.readouterr().out) == {'layouts': A['listed']['layouts']}


def test_show_rename_retire_and_use_again_say_what_they_did(capsys):
    fake = Fake(**{'layouts/list': A['listed'], 'layouts/get': A['opened'], 'layouts/rename': A['renamed'], 'layouts/retire': A['retired'], 'layouts/use-again': A['again']})
    layouts(['show', 'Tubbergen tops'], fake)
    assert shown(capsys).splitlines()[:4] == ['Tubbergen tops 2026', 'Holds: Well tops', 'Made by Carol Smit on ' + DAY, 'Changed by Bram Jansen on ' + DAY]
    for argv, said in ((['rename', 'Tubbergen tops', 'Tubbergen tops 2026'], 'Renamed to "Tubbergen tops 2026".'), (['retire', 'Tubbergen tops'], '"Tubbergen tops 2026" is retired.'),
                       (['use-again', 'Tubbergen tops'], '"Tubbergen tops 2026" is offered again.')):
        layouts(argv, fake)
        assert shown(capsys).strip() == said


def test_export_writes_the_download_and_import_exits_4_when_one_is_not_added(tmp_path, capsys):
    out = tmp_path / 'Layouts.layout.json'
    layouts(['export', '--out', str(out)], Fake(**{'layouts/export': A['export_all']}))
    assert shown(capsys).strip() == 'Saved Layouts.layout.json' and json.loads(out.read_text()) == A['export_all']
    out.write_text(json.dumps(A['import_file']))
    with pytest.raises(SystemExit) as exited: layouts(['import', str(out)], Fake(**{'layouts/import': A['imported']}))
    assert exited.value.code == cli.EXIT['conflict']
    assert shown(capsys).splitlines() == ['Other tops: Already here', 'Imported tops: Added',
                                          'Bad tops: Not added: A layout in this file is not valid: the table kind is not supported. It was not added.']


def test_keep_prints_the_j1b_line_and_a_refusal_keeps_its_sentence(capsys):
    layouts(['keep', 'sql', 'w'], Fake(**{'layouts/keep': A['kept']}))
    assert shown(capsys).strip() == 'Kept as the project layout "Groningen wells". Later changes to your own mapping do not change it.'
    with pytest.raises(IntegrityConflict) as refused: layouts(['keep', 'sql', 'w'], Fake(**{'layouts/keep': A['keep_nothing']}))
    assert str(refused.value) == 'You have not saved a mapping for this table yet. Save it first, then keep it as a project layout.'
    assert cli.exit_code(refused.value) == cli.EXIT['conflict']


def test_usage_is_refused_before_any_call():
    fake = Fake()
    for argv, said in ((['rename', 'Tubbergen tops'], 'Give the layout and its new name'), (['list', '--out', 'x'], 'Only export takes --out'),
                       (['export'], 'Say where to write it')):
        with pytest.raises(ValueError, match=said): layouts(argv, fake)
    assert fake.sent == []


def test_import_table_with_a_layout_lands_and_without_one_names_it(tmp_path, capsys):
    fake = landing()
    cli._journey(cli.parser().parse_args(['import', 'table', str(table(tmp_path)), '--layout', 'Tubbergen tops']), fake)
    assert 'table-imports/start' in fake.keys() and fake.sent[fake.keys().index('table-imports/preview')][1]['layout']['id'] == A['match_one']['matches'][0]['asset_id']
    assert capsys.readouterr().out.splitlines()[-1] == 'HON-GT-01 tops: Added: 3 tops. No well named HON-GT-01 was found, so these are not linked yet.'  # E87's result words (its start line names the run to resume)
    fake = landing()
    with pytest.raises(IntegrityConflict, match=r'^Needs your decision: this table matches the layout "Tubbergen tops"\. Add it with --layout "Tubbergen tops"\.$') as refused:
        cli._journey(cli.parser().parse_args(['import', 'table', str(table(tmp_path)), '--target', 'well-tops']), fake)
    assert cli.exit_code(refused.value) == cli.EXIT['conflict'] and 'table-imports/preview' not in fake.keys()


def upload(argv, fake):
    fake.upload_runs = SimpleNamespace(upload=lambda *a, **k: pytest.fail('the ordinary upload ran'))
    return cli._upload(cli.parser().parse_args(['upload', *argv, '--attribution', 'NLOG', '--rights-confirmed']), fake)


def test_upload_of_a_matching_table_adds_nothing_unless_the_layout_is_named(tmp_path, capsys):
    fake = landing()
    with pytest.raises(IntegrityConflict, match='^Needs your decision: this table matches the layout "Tubbergen tops"'): upload([str(table(tmp_path))], fake)
    assert fake.keys() == ['layouts/list', 'table-imports/read', 'layouts/match']  # mutation guard: auto-apply lands
    fake = landing()
    upload([str(table(tmp_path)), '--layout', 'Tubbergen tops'], fake)
    assert fake.keys()[-2:] == ['table-imports/start', 'table-imports/step']
    assert shown(capsys).splitlines() == ['Finished', 'HON-GT-01 tops: Added: 3 tops. No well named HON-GT-01 was found, so these are not linked yet.']


def test_upload_without_header_layouts_is_the_ordinary_upload(tmp_path):
    fake = landing(**{'layouts/list': A['empty']})
    with pytest.raises(BaseException, match='the ordinary upload ran'): upload([str(table(tmp_path))], fake)
    assert fake.keys() == ['layouts/list']
