"""E109 S1.4 (C5 tops, D10 a): the tops-to-team-db example's writer against a real PostgreSQL (a throwaway cluster,
strategy row 6-18). Three tops of HON-GT-01 from the registered `nlog-tops.xlsx` (rights record
`docs/release/rights/nlog-table-import-2026-10-09.json`) are written into `team.tops(well, surface, md)` with the
delivery id in `team.deliveries`, in one transaction; a writer whose tops insert fails leaves neither. Without `initdb`
the cluster helper fails, never skips. This file runs the writer function directly; the journey through `ophiolite
deliver` (exact version, report, Activity and story) is test_deliver_journey.py (S1.2)."""
import csv
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

import ophiolite

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/procedures/tops-to-team-db'
XLSX = ROOT / 'conformance/fixtures/table-import/nlog-tops.xlsx'
# Written by hand from the workbook (sheet Tops, the first three HON-GT-01 rows: Formation, Top MD (m)).
THREE = [('HON-GT-01', 'NU', 0.0), ('HON-GT-01', 'NM', 220.0), ('HON-GT-01', 'NL', 240.0)]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pg = load('e109_pg', ROOT / 'tests/fixtures/e109/pg.py')
sys.path.insert(0, str(EXAMPLE))
try:
    import tops_to_team_db as writer
finally:
    sys.path.remove(str(EXAMPLE))


@pytest.fixture
def db(tmp_path):
    with pg.team_db(tmp_path) as team:  # fails, never skips, without initdb
        yield team


@pytest.fixture
def version(tmp_path):
    """The tops version a delivery reads: well-tops-csv/1 (`name,md`), the three tops taken from the workbook."""
    import openpyxl
    sheet = openpyxl.load_workbook(XLSX, read_only=True)['Tops']
    rows = [r for r in sheet.iter_rows(values_only=True) if r and r[0] == 'HON-GT-01'][:3]
    assert [(r[0], r[1], float(r[2])) for r in rows] == THREE  # the workbook says what the literal says
    path = tmp_path / 'tops.csv'
    with path.open('w', newline='', encoding='utf-8') as handle:
        csv.writer(handle).writerows([['name', 'md']] + [[r[1], r[2]] for r in rows])
    return path


def test_the_writer_puts_three_tops_and_the_delivery_id_into_the_team_schema(db, version):
    delivery_id = str(uuid.uuid4())
    assert writer.write(db.config, writer.rows_of(version, 'HON-GT-01'), delivery_id) == 3
    assert db.rows('SELECT well, surface, md FROM team.tops ORDER BY md') == THREE
    assert db.rows('SELECT delivery_id, state FROM team.deliveries') == [(delivery_id, 'delivered')]
    assert 'password' not in db.config and 'anna-writer' not in repr(db.config)  # the password stays in the password file


def test_a_failed_tops_insert_leaves_neither_the_tops_nor_the_delivery_id(db, version):
    db.sql('REVOKE INSERT ON team.tops FROM %s' % pg.WRITER)
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.write(db.config, writer.rows_of(version, 'HON-GT-01'), str(uuid.uuid4()))
    assert db.rows('SELECT count(*) FROM team.deliveries') == [(0,)]
    assert db.rows('SELECT count(*) FROM team.tops') == [(0,)]


def test_a_version_that_is_not_a_tops_table_is_refused_in_words(tmp_path):
    path = tmp_path / 'other.csv'
    path.write_text('well,depth\nHON-GT-01,1\n')
    with pytest.raises(writer.NotTops) as refused: writer.rows_of(path, 'HON-GT-01')
    assert str(refused.value) == 'This version is not a tops table with the columns name and md.'


def test_the_cluster_helper_fails_without_initdb(tmp_path):
    module = pg.cluster_module()
    module._bin = lambda name: None  # as on a computer without PostgreSQL
    with pytest.raises(RuntimeError) as missing:
        with pg.team_db(tmp_path, module=module): pass
    assert str(missing.value) == pg.MISSING


# ---------------------------------------------------------------- S2.2: reconcile and the tombstone (C3 12a, 4-1)

def attempt(db, delivery_id):
    from types import SimpleNamespace
    return SimpleNamespace(id=delivery_id, system=SimpleNamespace(config=db.config))


def test_reconcile_confirms_a_written_delivery_with_its_count(db, version):
    delivery_id = str(uuid.uuid4())
    writer.write(db.config, writer.rows_of(version, 'HON-GT-01'), delivery_id)
    assert writer.reconcile(attempt(db, delivery_id)) == ophiolite.delivered(items=3)
    assert db.rows('SELECT delivery_id, state, items FROM team.deliveries') == [(delivery_id, 'delivered', 3)]  # no tombstone


def test_an_absent_id_is_withdrawn_by_the_tombstone_and_a_late_writer_fails_on_its_key(db, version):
    delivery_id = str(uuid.uuid4())
    assert writer.reconcile(attempt(db, delivery_id)) == ophiolite.not_delivered()
    assert db.rows('SELECT delivery_id, state FROM team.deliveries') == [(delivery_id, 'withdrawn')]
    import psycopg
    with pytest.raises(psycopg.errors.UniqueViolation):
        writer.write(db.config, writer.rows_of(version, 'HON-GT-01'), delivery_id)
    assert db.rows('SELECT count(*) FROM team.tops') == [(0,)]
    assert writer.reconcile(attempt(db, delivery_id)) == ophiolite.not_delivered()  # asked again: the same answer


def test_a_writer_s_open_transaction_makes_reconcile_wait_and_say_unknown_never_not_sent(db, version, monkeypatch):
    import psycopg
    delivery_id = str(uuid.uuid4())
    open_ = psycopg.connect(host=db.config['host'], port=db.config['port'], dbname='team_tops', user=pg.WRITER)
    open_.execute('INSERT INTO team.deliveries (delivery_id, state, items) VALUES (%s, %s, %s)', (delivery_id, 'delivered', 3))
    monkeypatch.setattr(writer, 'WAIT', '200ms')
    assert writer.reconcile(attempt(db, delivery_id)) == ophiolite.unknown()
    open_.commit()
    open_.close()
    assert writer.reconcile(attempt(db, delivery_id)) == ophiolite.delivered(items=3)


def test_an_unfenced_destination_is_unknown(db):
    db.sql('DROP TABLE team.deliveries')  # no fence table: nothing can say not sent (D10, the no-reconcile case)
    assert writer.reconcile(attempt(db, str(uuid.uuid4()))) == ophiolite.unknown()


def test_an_unreachable_destination_is_unknown(db):
    gone = attempt(db, str(uuid.uuid4()))
    gone.system.config = {**db.config, 'port': 1}
    assert writer.reconcile(gone) == ophiolite.unknown()
