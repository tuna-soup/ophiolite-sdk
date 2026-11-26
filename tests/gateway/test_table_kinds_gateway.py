"""E203 s1 C5, in-process gateway lane (strategy D5, D6; acceptance 1, 2, 7, 9): a kind of table declared, a table
published as it, its CSV and Parquet exports downloaded and each checked on this computer, through the SDK and the
command line against the real routes.

The kinds fixture CK as this library carries it is the oracle: casing-design 1's declaration is declared, T1 published
as it and T2 refused with the `expected.json` problems. `client.export_file(..., format='csv')` writes
`<file>.table-kind.json` beside the file: the block the Parquet record carries, and the columns as exported.

Mutations: the sidecar not written -> check refuses `no-kind`; the sidecar's block read from the latest version -> it
names version 2; `table_kind` not sent -> T2 publishes; a sidecar for a plain version -> one is written."""
import csv
import io
import json
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from ophiolite import cli, table_kinds
from ophiolite.errors import Refused

pq = pytest.importorskip('pyarrow.parquet')

FIXTURES = Path(table_kinds.__file__).parent / 'contracts' / 'kinds' / 'v1' / 'fixtures'
TABLES = json.loads((FIXTURES / 'tables.json').read_text())['tables']
EXPECTED = {(c['kind'], c['table']): c['problems'] for c in json.loads((FIXTURES / 'expected.json').read_text())['expected']}


def version(name):
    return json.loads((FIXTURES / 'valid' / ('%s.json' % name)).read_text())


def table_file(folder, name):
    """A fixture table as the CSV a person sends, and its stated units as `columns`."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow([c['name'] for c in TABLES[name]['columns']])
    w.writerows([['' if v is None else v for v in row] for row in TABLES[name]['rows']])
    path = folder / ('%s.csv' % name); path.write_text(out.getvalue())
    return path, {c: {'unit': n['unit']} for c, n in TABLES[name]['declarations']['columns'].items() if n['unit']}


@pytest.fixture
def kinds(keyed, tmp_path):
    alice = client(keyed, 'alice', 'delegate')
    (tmp_path / 'in').mkdir(); (tmp_path / 'out').mkdir()
    return type('Kinds', (), {'client': alice, 'path': tmp_path})()


def test_declared_published_exported_and_checked_here(kinds):
    c, folder = kinds.client, kinds.path
    v1 = c.table_kinds.declare(version('casing-design-1')['declaration'])
    assert (v1['version'], v1['digest'], v1['declaration']) == (1, version('casing-design-1')['digest'], version('casing-design-1')['declaration'])
    assert [k['declaration']['word'] for k in c.table_kinds.list()] == ['casing-design'] and c.table_kinds.show('casing-design') == v1
    path, units = table_file(folder / 'in', 't1-complete')
    unit = c.imports.from_table(path, 'table', columns=units, table_kind='casing-design')['run']['units'][0]
    asset, revision = unit['asset_id'], unit['revision']
    c.table_kinds.declare(version('casing-design-2')['declaration'])  # a later version: the export still names version 1
    reference = {k: v1[k] for k in ('id', 'version', 'digest')} | {'word': 'casing-design'}
    parquet = c.export_file(asset, revision, folder / 'out' / 'casing.parquet')
    record = json.loads(pq.read_schema(parquet).metadata[b'ophiolite.export'])
    assert record['table_kind'] == {**reference, 'declaration': v1['declaration']}
    text = c.export_file(asset, revision, folder / 'out' / 'casing.csv', format='csv')
    beside = json.loads(Path(str(text) + table_kinds.SIDECAR).read_text())
    assert beside['table_kind'] == record['table_kind'] and [col['name'] for col in beside['columns']] == [col['name'] for col in record['columns']]
    assert sorted(p.name for p in (folder / 'out').iterdir()) == ['casing.csv', 'casing.csv.table-kind.json', 'casing.parquet']
    for exported in (parquet, text):
        found = cli.main(['exchange', 'table-kinds', 'check', str(exported), '--json'])
        assert (found.exit_code, dict(found)) == (0, {'kind': reference, 'problems': EXPECTED[('casing-design-1', 't1-complete')], 'sentences': []})


def test_a_table_not_of_the_kind_is_refused_and_a_plain_csv_gets_nothing_beside_it(kinds):
    c, folder = kinds.client, kinds.path
    c.table_kinds.declare(version('casing-design-1')['declaration'])
    path, units = table_file(folder / 'in', 't2-no-shoe-depth')
    with pytest.raises(Refused) as refused:
        c.imports.from_table(path, 'table', columns=units, table_kind='casing-design')
    problems = EXPECTED[('casing-design-1', 't2-no-shoe-depth')]
    assert problems and str(refused.value).endswith(' '.join(table_kinds.sentence(p) for p in problems))
    unit = c.imports.from_table(path, 'table', columns=units)['run']['units'][0]
    text = c.export_file(unit['asset_id'], unit['revision'], folder / 'out' / 'plain.csv', format='csv')
    assert sorted(p.name for p in (folder / 'out').iterdir()) == ['plain.csv']
    with pytest.raises(SystemExit) as ended: cli.main(['exchange', 'table-kinds', 'check', str(text)])
    assert ended.value.code == cli.EXIT['usage']
