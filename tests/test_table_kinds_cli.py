"""E203 s1 C5 (strategy D6): `client.table_kinds`, `imports.from_table(..., table_kind=)` and `ophiolite exchange
table-kinds declare | list | show | check`, `import table --table-kind`.

A fake gateway serves the kinds fixture CK as `table-kinds/*` answers; the requests it receives are compared whole. The
words name a quantity by the label a person reads (`pressure`, never its class). `check` runs offline on the files
test_table_kinds_offline writes and ends 0 (fits), 1 (each problem) or 2 (no kind, or a kind that cannot be read).

Mutations: the word or version left out of `show` -> the request differs; `table_kind` dropped in `_body` -> the preview
and start bodies lack it; the quantity class printed -> `energy per volume` in the words; a problem ending 0 -> exit
differs; an unreadable block ending 1 -> exit differs; --table-kind accepted by `import list` -> no refusal."""
import json

import httpx
import pytest

from ophiolite import Client, cli, table_kinds
from test_table_kinds_offline import EXPECTED, WORDS, block, csv_file, parquet, ref, version

SHOWN = {1: version('casing-design-1'), 2: version('casing-design-2')}


class Gateway:
    """table-kinds/declare | list | show over SHOWN; every body kept in `bodies`."""
    def __init__(self):
        self.bodies = []

    def __call__(self, request):
        operation = request.url.path.rsplit('/', 1)[1]
        assert request.url.path == '/api/v1/projects/p-kinds/table-kinds/' + operation
        body = json.loads(request.content); self.bodies.append((operation, body))
        if operation == 'list': return httpx.Response(200, json={'kinds': [SHOWN[2]]})
        if operation == 'declare': return httpx.Response(200, json=SHOWN[1])
        return httpx.Response(200, json=SHOWN[body.get('version', 2)])


def client(gateway):
    return Client('https://gateway.example', 'p-kinds', None, httpx.Client(transport=httpx.MockTransport(gateway)))


def run(gateway, *argv):
    return cli._table_kinds(cli.parser().parse_args(['table-kinds', *argv]), client(gateway))


def test_the_client_posts_each_request_as_documented():
    g = Gateway(); c = client(g)
    declaration = SHOWN[1]['declaration']
    assert c.table_kinds.declare(declaration, command_id='k-1') == SHOWN[1]
    assert c.table_kinds.declare(declaration, command_id='k-2', expected_version=1) == SHOWN[1]
    assert c.table_kinds.list() == [SHOWN[2]]
    assert c.table_kinds.show('casing-design') == SHOWN[2] and c.table_kinds.show('casing-design', 1) == SHOWN[1]
    assert g.bodies == [('declare', {'project_id': 'p-kinds', 'command_id': 'k-1', 'declaration': declaration}),
                        ('declare', {'project_id': 'p-kinds', 'command_id': 'k-2', 'declaration': declaration, 'expected_version': 1}),
                        ('list', {'project_id': 'p-kinds'}),
                        ('show', {'project_id': 'p-kinds', 'word': 'casing-design'}),
                        ('show', {'project_id': 'p-kinds', 'word': 'casing-design', 'version': 1})]
    with pytest.raises(ValueError): c.table_kinds.declare('casing-design')
    assert len(g.bodies) == 5  # nothing sent


def test_show_says_the_kind_in_words_and_json_is_the_served_version(capsys):
    run(Gateway(), 'show', 'casing-design')
    out = capsys.readouterr().out
    assert out.splitlines() == ['casing-design, version 2: Casing strings. One row: One casing string.',
                                '  string: text, required',
                                '  od: number, length in in, required',
                                '  shoe_depth: number, length in m, required',
                                '  weight: number, weight per length in lbm/ft, optional, may be empty',
                                '  grade: text, optional, may be empty',
                                '  burst: number, pressure in bar, required',
                                '  Each row is told apart by: string']
    assert 'energy per volume' not in out and 'mass per length' not in out
    assert run(Gateway(), 'show', 'casing-design', '--version', '1', '--json') == SHOWN[1]
    assert json.loads(capsys.readouterr().out) == SHOWN[1]


def test_list_and_declare_from_a_file(capsys, tmp_path):
    g = Gateway()
    run(g, 'list')
    assert capsys.readouterr().out == 'casing-design, version 2: Casing strings\n'
    path = tmp_path / 'casing.json'; path.write_text(json.dumps(SHOWN[1]['declaration']))
    run(g, 'declare', str(path))
    assert capsys.readouterr().out.splitlines()[:2] == ['Declared.', 'casing-design, version 1: Casing strings. One row: One casing string.']
    assert g.bodies[-1][1]['declaration'] == SHOWN[1]['declaration']
    path.write_text('casing-design')
    with pytest.raises(cli.Refused): run(g, 'declare', str(path))
    assert len(g.bodies) == 2


def test_the_table_kind_reaches_preview_and_start(monkeypatch, tmp_path):
    seen = []
    from ophiolite.imports import Imports
    monkeypatch.setattr(Imports, '_call', lambda self, operation, body, *models: seen.append((operation, body)) or {'preview_digest': 'p', 'id': 'r', 'state': 'complete'})
    monkeypatch.setattr(Imports, 'read', lambda self, source, **k: {'input_id': 'i', 'schema_digest': 's', 'columns': [{'name': 'string'}], 'context': {}})
    imports = client(Gateway()).imports
    imports.from_table(tmp_path / 'casing.csv', 'table', table_kind='casing-design', command_id='c')
    assert [(op, body.get('table_kind')) for op, body in seen] == [('preview', 'casing-design'), ('start', 'casing-design'), ('step', None)]
    seen.clear()
    imports.from_table(tmp_path / 'casing.csv', 'table', command_id='c', dry_run=True)
    assert 'table_kind' not in seen[0][1]


def test_import_table_takes_table_kind_and_no_other_verb_does(monkeypatch, tmp_path):
    called = {}
    from ophiolite.imports import Imports
    monkeypatch.setattr(Imports, 'from_table', lambda self, *a, **k: called.update(k) or {'preview': {'target': 'table'}, 'run': None})
    path = tmp_path / 'casing.csv'; path.write_text('string\nConductor\n')
    args = cli.parser().parse_args(['import', 'table', str(path), '--target', 'table', '--table-kind', 'casing-design', '--dry-run'])
    monkeypatch.setattr('ophiolite.imports.review_lines', lambda review: [])
    cli._table_import(args, client(Gateway()))
    assert called['table_kind'] == 'casing-design'
    with pytest.raises(cli.Refused) as refused:
        cli._table_import(cli.parser().parse_args(['import', 'list', '--table-kind', 'casing-design']), client(Gateway()))
    assert '--table-kind' in str(refused.value)


# ---- check, offline ------------------------------------------------------------------------------------------------------

def checked(path, *flags):
    return cli.main(['exchange', 'table-kinds', 'check', str(path), *flags])


@pytest.mark.parametrize('write', [parquet, csv_file], ids=['parquet', 'csv'])
def test_check_ends_0_when_the_file_fits_and_1_with_each_problem(tmp_path, capsys, write):
    fits = checked(write(tmp_path / 't1', 't1-complete', block('casing-design-1')))
    assert (fits.exit_code, capsys.readouterr().out) == (0, WORDS['offline']['fits'].format(word='casing-design', version=1) + '\n')
    found = checked(write(tmp_path / 't4', 't4-bar', block('casing-design-1')))
    problems = next(c['problems'] for c in EXPECTED if (c['kind'], c['table']) == ('casing-design-1', 't4-bar'))
    assert found.exit_code == cli.EXIT['refused'] and found['problems'] == problems and problems
    assert capsys.readouterr().out.splitlines() == [WORDS['refusals']['kind-refused'].format(word='casing-design')] + [table_kinds.sentence(p) for p in problems]
    as_json = checked(write(tmp_path / 't4j', 't4-bar', block('casing-design-1')), '--json')
    assert json.loads(capsys.readouterr().out) == dict(as_json) == {'kind': ref('casing-design-1'), 'problems': problems, 'sentences': [table_kinds.sentence(p) for p in problems]}


@pytest.mark.parametrize('bad, reason', [(None, 'no-kind'), ({'word': 'casing-design'}, 'unreadable'),
                                         ({**block('casing-design-1'), 'declaration': block('casing-design-2')['declaration']}, 'digest-differs')])
def test_check_ends_2_with_its_sentence_when_the_kind_cannot_be_read(tmp_path, capsys, bad, reason):
    with pytest.raises(SystemExit) as ended: checked(parquet(tmp_path / 't1', 't1-complete', bad))
    sentence = (WORDS['offline'].get(reason) or WORDS['refusals'][reason])
    assert (ended.value.code, capsys.readouterr().err) == (2, sentence + '\n')
    with pytest.raises(SystemExit): checked(parquet(tmp_path / 't1j', 't1-complete', bad), '--json')
    assert json.loads(capsys.readouterr().out) == {'error': {'code': reason, 'message': sentence}}


def test_check_reads_no_configuration_and_refuses_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no configuration.json here: check never asks for one
    with pytest.raises(cli.Refused): checked(tmp_path / 'absent.parquet')
    cli.entrypoint(['exchange', 'table-kinds', 'check', str(parquet(tmp_path / 't1', 't1-complete', block('casing-design-1')))])  # ends 0: no SystemExit
    with pytest.raises(SystemExit) as ended: cli.entrypoint(['exchange', 'table-kinds', 'check', str(parquet(tmp_path / 't4', 't4-bar', block('casing-design-1')))])
    assert ended.value.code == cli.EXIT['refused']
