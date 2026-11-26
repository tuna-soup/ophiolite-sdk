"""E203 s1 C4 (strategy D5, §5 test_table_kinds_offline; acceptance 7, 9): a kind of table checked on this computer.

`ophiolite.table_kinds` is the Platform's pure module carried with the library. The oracle is the fixture CK as this
library carries it (`contracts/kinds/v1/fixtures`): every case of `expected.json` answered as written there, every
declaration case refused or broken as written there. An exported file is written here as the Platform writes one: a
Parquet file with its `ophiolite.export` record holding the kind's block, a CSV file with the block beside it. A
declaration changed after export is refused (`digest-differs`); a file without a block, or with one that cannot be read,
is refused with its own sentence; a table altered after export, its declaration intact, has the problems of
`expected.json`.

Mutations: the digest not recomputed -> the changed declaration is checked and passes; the vendored rules drift -> a CK
case red; the sidecar's units ignored -> t4-bar passes; a block read without its shape check -> the malformed case is
checked."""
import copy
import csv
import json
from pathlib import Path

import pytest

from ophiolite import table_kinds

FIXTURES = Path(table_kinds.__file__).parent / 'contracts' / 'kinds' / 'v1' / 'fixtures'
TABLES = json.loads((FIXTURES / 'tables.json').read_text())['tables']
EXPECTED = json.loads((FIXTURES / 'expected.json').read_text())['expected']
CASES = json.loads((FIXTURES / 'invalid' / 'declaration-cases.json').read_text())['cases']
DIGESTS = json.loads((FIXTURES / 'digests.json').read_text())['digests']
WORDS = table_kinds.words()


def version(name):
    return json.loads((FIXTURES / 'valid' / ('%s.json' % name)).read_text())


def block(name):
    v = version(name)
    return {'id': v['id'], 'word': v['declaration']['word'], 'version': v['version'], 'digest': v['digest'], 'declaration': v['declaration']}


def ref(name):
    return {k: v for k, v in block(name).items() if k != 'declaration'}


@pytest.mark.parametrize('case', EXPECTED, ids=lambda c: '%s/%s' % (c['kind'], c['table']))
def test_the_vendored_check_answers_every_case_as_expected_json_says(case):
    assert table_kinds.problems(version(case['kind'])['declaration'], TABLES[case['table']]) == case['problems']


@pytest.mark.parametrize('name', sorted(DIGESTS))
def test_the_digest_of_each_fixture_declaration_is_digests_json(name):
    assert table_kinds.digest(version(name)['declaration']) == DIGESTS[name] == version(name)['digest']


def changed(case):
    declaration = copy.deepcopy(version('casing-design-1')['declaration'])
    if 'set' in case:
        path, value = case['set']
        place = declaration
        for step in path[:-1]: place = place[step]
        place[path[-1]] = value
    else:
        place = declaration
        for step in case['remove'][:-1]: place = place[step]
        del place[case['remove'][-1]]
    return declaration


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_each_declaration_case_is_refused_or_broken_as_written(case):
    declaration = changed(case)
    if 'schema' in case:
        with pytest.raises(ValueError): table_kinds.TableKindDeclaration.model_validate(declaration)
        return
    assert table_kinds.TableKindDeclaration.model_validate(declaration).model_dump(mode='json') == declaration
    assert table_kinds.declaration_problems(declaration) == case['reasons']


# ---- exported files --------------------------------------------------------------------------------------------------

def read_columns(name):
    """The columns an export writes (the read ones, in order) with each one's unit and missing-value marker."""
    table = TABLES[name]
    notes = table['declarations']['columns']
    return [{'name': c['name'], 'logical': c['logical'], **{k: v for k, v in (notes.get(c['name']) or {}).items() if k in ('unit', 'missing') and v is not None}}
            for c in table['columns'] if c['read']]


def parquet(path, name, kind_block, record_extra=None):
    """A Parquet file as the Platform writes one: field metadata per column and the `ophiolite.export` record."""
    pa = pytest.importorskip('pyarrow')
    pq = pytest.importorskip('pyarrow.parquet')
    columns, rows = read_columns(name), TABLES[name]['rows']
    kinds = {'boolean': pa.bool_(), 'float': pa.float64()}
    arrays, fields = [], []
    for i, c in enumerate(columns):
        array = pa.array([row[i] for row in rows], kinds.get(c['logical'], pa.string()))
        notes = {'ophiolite.' + k: c[k] for k in ('logical', 'unit', 'missing') if k in c}
        arrays.append(array); fields.append(pa.field(c['name'], array.type, metadata=notes))
    record = {'schema': 'ophiolite.table-export/1', 'columns': columns, **(record_extra or {})}
    if kind_block is not None: record['table_kind'] = kind_block
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields, metadata={'ophiolite.export': json.dumps(record)})), path)
    return path


def csv_file(path, name, kind_block, columns=None):
    """A CSV file as the Platform writes one (canonical text, an empty cell for null) and the block written beside it."""
    columns = read_columns(name) if columns is None else columns
    with open(path, 'w', newline='', encoding='utf-8') as out:
        w = csv.writer(out, lineterminator='\r\n')
        w.writerow([c['name'] for c in read_columns(name)])
        for row in TABLES[name]['rows']:
            w.writerow(['' if v is None else 'true' if v is True else 'false' if v is False else json.dumps(v) if isinstance(v, float) else v for v in row])
    if kind_block is not None:
        Path(str(path) + table_kinds.SIDECAR).write_text(json.dumps(table_kinds.sidecar(kind_block, columns)))
    return path


WRITERS = {'parquet': lambda tmp, name, b: parquet(tmp / (name + '.parquet'), name, b), 'csv': lambda tmp, name, b: csv_file(tmp / (name + '.csv'), name, b)}
KINDED = [c for c in EXPECTED if c['kind'] == 'casing-design-1']


@pytest.mark.parametrize('fmt', sorted(WRITERS))
@pytest.mark.parametrize('case', KINDED, ids=lambda c: c['table'])
def test_an_exported_file_is_checked_against_the_kind_written_with_it(tmp_path, fmt, case):
    found = table_kinds.check(WRITERS[fmt](tmp_path, case['table'], block('casing-design-1')))
    assert found == {'kind': ref('casing-design-1'), 'problems': case['problems'], 'sentences': [table_kinds.sentence(p) for p in case['problems']]}


@pytest.mark.parametrize('fmt', sorted(WRITERS))
def test_a_declaration_changed_after_export_is_refused(tmp_path, fmt):
    edited = block('casing-design-1')
    edited['declaration'] = {**edited['declaration'], 'columns': [c for c in edited['declaration']['columns'] if c['name'] != 'shoe_depth']}
    with pytest.raises(table_kinds.Unreadable) as refused:
        table_kinds.check(WRITERS[fmt](tmp_path, 't2-no-shoe-depth', edited))  # the declaration edited to let T2 pass
    assert (refused.value.reason, str(refused.value)) == ('digest-differs', WORDS['refusals']['digest-differs'])


@pytest.mark.parametrize('fmt', sorted(WRITERS))
@pytest.mark.parametrize('bad, reason', [
    (None, 'no-kind'),
    ({'word': 'casing-design'}, 'unreadable'),
    ({**block('casing-design-1'), 'digest': 'not a digest'}, 'unreadable'),
    ({**block('casing-design-1'), 'word': 'string-tally'}, 'unreadable'),
], ids=['none', 'partial', 'digest-shape', 'other-word'])
def test_a_file_without_a_readable_block_is_refused_with_its_sentence(tmp_path, fmt, bad, reason):
    with pytest.raises(table_kinds.Unreadable) as refused:
        table_kinds.check(WRITERS[fmt](tmp_path, 't1-complete', bad))
    assert (refused.value.reason, str(refused.value)) == (reason, WORDS['offline'][reason])


def test_a_csv_column_the_sidecar_does_not_name_is_text_and_its_units_come_from_the_sidecar(tmp_path):
    columns = [c if c['name'] != 'shoe_depth' else {k: v for k, v in c.items() if k != 'unit'} for c in read_columns('t1-complete')]
    found = table_kinds.check(csv_file(tmp_path / 't1.csv', 't1-complete', block('casing-design-1'), columns))
    assert [p['reason'] for p in found['problems']] == ['unit-missing']  # the units are the sidecar's, never guessed
    found = table_kinds.check(csv_file(tmp_path / 't4.csv', 't4-bar', block('casing-design-1')))
    assert found['problems'] == next(c['problems'] for c in KINDED if c['table'] == 't4-bar')


def test_a_parquet_file_without_an_export_record_carries_no_kind(tmp_path):
    pa = pytest.importorskip('pyarrow')
    pq = pytest.importorskip('pyarrow.parquet')
    pq.write_table(pa.table({'string': ['Conductor']}), tmp_path / 'plain.parquet')
    with pytest.raises(table_kinds.Unreadable) as refused: table_kinds.check(tmp_path / 'plain.parquet')
    assert refused.value.reason == 'no-kind'


def test_every_offline_sentence_is_a_sentence_a_person_reads():
    classes = {cls for cls, label in WORDS['quantities'].items() if cls != label}
    for reason, text in WORDS['offline'].items():
        assert text[0].isupper() and text.endswith('.') and not any(c in text for c in classes), reason
        assert 'pyarrow' not in text and 'table_kinds' not in text and 'ophiolite.' not in text, reason
